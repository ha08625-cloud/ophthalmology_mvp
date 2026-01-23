"""
Question Selector V2 - Stateless question selection for multi-episode consultations

Responsibilities:
- Select next question based on episode state and medical protocol
- Evaluate DSL conditions from ruleset
- Detect trigger conditions for follow-up blocks
- Determine block completion status

Design principles:
- Stateless: All state comes from episode_data parameter
- Deterministic: Same input always produces same output
- Pure functions: No side effects
- Fail fast: Validate ruleset on initialization, assert invariants at runtime
- Immutable: Ruleset frozen at load, returns are QuestionOutput dataclasses

Contracts:
- episode_data must contain:
    - questions_answered: set[str]
    - questions_satisfied: set[str]
    - follow_up_blocks_activated: set[str]
    - follow_up_blocks_completed: set[str]
    - Extracted fields as key-value pairs
- Returns: QuestionOutput (immutable dataclass) or None
- Caller is responsible for trigger idempotency (check_triggers returns
  ALL matching blocks, not just new ones)

Runtime Assertions (V4):
- Public methods validate invariants with AssertionError
- These are permanent guards, not dev-only checks
- AssertionErrors should propagate to Flask boundary for logging
- Assertions catch contract drift and invalid state early

DSL Semantics:
- Missing field always evaluates to False for all operators
- Empty "all": True (vacuous truth)
- Empty "any": False (no conditions met)
- Empty DSL root: True (no constraints)
- Unknown operator: raises ValueError (fail fast)

Supported DSL operators:
- Logical: all, any
- Comparison: eq, ne, gt, gte, lt, lte
- Boolean: is_true, is_false
- Existence: exists
- String: contains_lower

Provenance hooks:
- _evaluate_condition() and _evaluate_dsl() can be wrapped later
- check_triggers() returns block IDs (can be extended with trigger names)
- is_block_complete() can be extended to return skip reasons
"""

import copy
import json
import logging
from pathlib import Path
from typing import Optional, Any, List

# Flat import for server testing
# When copying to local, adjust to: from backend.contracts import QuestionOutput
try:
    from backend.contracts import QuestionOutput
except ImportError:
    from contracts import QuestionOutput

logger = logging.getLogger(__name__)


class QuestionSelectorV2:
    """
    Stateless question selector for multi-episode consultations.
    
    Determines the next question based on episode state and medical protocol.
    Does not track any state internally - all state comes from episode_data.
    
    V4 Changes:
        - Returns QuestionOutput dataclass instead of dict
        - Entry-point assertions validate invariants (permanent guards)
        - AssertionErrors propagate to caller for logging
    
    Thread Safety:
        Ruleset is deep-copied and frozen at initialization.
        All public methods return immutable QuestionOutput objects.
    """
    
    # Required keys in episode_data
    REQUIRED_EPISODE_KEYS = {
        'questions_answered',
        'questions_satisfied',
        'follow_up_blocks_activated', 
        'follow_up_blocks_completed'
    }
    
    # Valid question type values
    VALID_QUESTION_TYPES = {'probe', 'conditional'}
    
    # Required fields in question dicts
    REQUIRED_QUESTION_FIELDS = {'id', 'question', 'field'}
    
    def __init__(self, ruleset_path: str):
        """
        Initialize selector with ruleset.
        
        Args:
            ruleset_path: Path to ruleset.json
            
        Raises:
            FileNotFoundError: If ruleset doesn't exist
            ValueError: If ruleset missing required keys or has invalid references
        """
        self.ruleset_path = Path(ruleset_path)
        
        if not self.ruleset_path.exists():
            raise FileNotFoundError(f"Ruleset not found: {ruleset_path}")
        
        # Load ruleset
        with open(self.ruleset_path, 'r') as f:
            raw_ruleset = json.load(f)
        
        # Deep copy to ensure we own the data
        self.ruleset = copy.deepcopy(raw_ruleset)
        
        # Extract top-level components (these are references into frozen ruleset)
        self.section_order = self.ruleset.get("section_order")
        self.conditions = self.ruleset.get("conditions", {})
        self.trigger_conditions = self.ruleset.get("trigger_conditions", {})
        self.sections = self.ruleset.get("sections", {})
        self.follow_up_blocks = self.ruleset.get("follow_up_blocks", {})
        
        # Validate ruleset structure (fail fast)
        self._validate_ruleset()
        
        # Build deterministic field mappings (derived from immutable ruleset)
        self._question_to_field = {}      # question_id -> field_name
        self._field_to_questions = {}     # field_name -> frozenset[question_id]
        self._build_field_mappings()
        
        logger.info(f"Question Selector V2 initialized with {len(self.section_order)} sections")
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def _validate_episode_data(self, episode_data: dict) -> None:
        """
        Validate episode_data structure and types using assertions.
        
        V4: Changed from TypeError/ValueError to AssertionError.
        These are permanent invariant guards that should propagate to
        the Flask boundary for logging.
        
        Args:
            episode_data: Input to validate
            
        Raises:
            AssertionError: If episode_data violates invariants
        """
        # Type check
        if not isinstance(episode_data, dict):
            raise AssertionError(
                f"episode_data must be dict, got {type(episode_data).__name__}"
            )
        
        # Check required keys exist
        missing = self.REQUIRED_EPISODE_KEYS - set(episode_data.keys())
        if missing:
            raise AssertionError(f"episode_data missing required keys: {missing}")
        
        # Validate types of tracking sets
        for key in self.REQUIRED_EPISODE_KEYS:
            value = episode_data[key]
            # Accept both set and list (State Manager may serialize sets as lists)
            if not isinstance(value, (set, list)):
                raise AssertionError(
                    f"episode_data['{key}'] must be set or list, "
                    f"got {type(value).__name__}"
                )
    
    def _defensive_copy_episode_data(self, episode_data: dict) -> dict:
        """
        Create defensive copy of episode_data with sets normalized.
        
        Converts lists to sets for tracking fields, deep copies extracted fields.
        
        Args:
            episode_data: Original episode data
            
        Returns:
            dict: Defensive copy safe to use internally
        """
        copied = {}
        
        for key, value in episode_data.items():
            if key in self.REQUIRED_EPISODE_KEYS:
                # Convert to set (handles both set and list input)
                copied[key] = set(value)
            else:
                # Deep copy extracted fields
                copied[key] = copy.deepcopy(value)
        
        return copied
    
    def _dict_to_question_output(self, question_dict: dict) -> QuestionOutput:
        """
        Convert internal question dict to QuestionOutput dataclass.
        
        This is the single conversion point from ruleset dict format
        to the public QuestionOutput contract. QuestionOutput contains
        everything needed by downstream consumers (primarily Prompt Builder).
        
        Args:
            question_dict: Internal question dict from ruleset containing:
                - id: Question identifier (required)
                - question: Question text (required)
                - field: Target field name (required)
                - field_type: 'text', 'boolean', 'categorical' (default 'text')
                - type: 'probe' or 'conditional' (default 'probe')
                - valid_values: List of allowed values for categorical (optional)
                - field_label: Human-readable field label (optional)
                - field_description: Field extraction guidance (optional)
                - definitions: Dict mapping values to descriptions (optional)
            
        Returns:
            QuestionOutput: Immutable dataclass representation
            
        Note:
            - valid_values list is converted to tuple for immutability
            - definitions dict is converted to tuple of tuples for immutability
        """
        # Convert valid_values list to tuple (immutable)
        valid_values = question_dict.get('valid_values')
        if valid_values is not None:
            valid_values = tuple(valid_values)
        
        # Convert definitions dict to tuple of tuples (immutable)
        # Format: ((key1, val1), (key2, val2), ...)
        definitions = question_dict.get('definitions')
        if definitions is not None and isinstance(definitions, dict):
            definitions = tuple((k, v) for k, v in definitions.items())
        
        return QuestionOutput(
            id=question_dict['id'],
            question=question_dict['question'],
            field=question_dict['field'],
            field_type=question_dict.get('field_type', 'text'),
            type=question_dict.get('type', 'probe'),
            valid_values=valid_values,
            field_label=question_dict.get('field_label'),
            field_description=question_dict.get('field_description'),
            definitions=definitions
        )
    
    def get_next_question(self, episode_data: dict) -> Optional[QuestionOutput]:
        """
        Get next question for episode.
        
        V4 Changes:
        - Returns QuestionOutput dataclass instead of dict
        - Entry-point assertions validate invariants
        
        Args:
            episode_data: Complete episode state containing:
                - questions_answered: set[str] or list[str]
                - questions_satisfied: set[str] or list[str]
                - follow_up_blocks_activated: set[str] or list[str]
                - follow_up_blocks_completed: set[str] or list[str]
                - [extracted fields]: e.g., vl_laterality, h_present, etc.
        
        Returns:
            QuestionOutput (immutable dataclass) or None if no more questions.
            
        Raises:
            AssertionError: If episode_data violates invariants
        """
        # Validate input (raises AssertionError on failure)
        self._validate_episode_data(episode_data)
        
        # Defensive copy to prevent caller mutation affecting our logic
        episode = self._defensive_copy_episode_data(episode_data)
        
        # Extract tracking sets (now guaranteed to be sets)
        questions_answered = episode["questions_answered"]
        questions_satisfied = episode["questions_satisfied"]
        blocks_activated = episode["follow_up_blocks_activated"]
        blocks_completed = episode["follow_up_blocks_completed"]
        
        # Step 1: Check for pending follow-up block questions
        pending_blocks = blocks_activated - blocks_completed
        
        for block_id in sorted(pending_blocks):  # Deterministic order
            next_q = self._get_next_block_question(block_id, questions_satisfied, episode)
            if next_q is not None:
                return self._dict_to_question_output(next_q)
        
        # Step 2: Walk sections in order
        for section_name in self.section_order:
            section_questions = self.sections.get(section_name, [])
            
            for question in section_questions:
                q_id = question.get("id")
                
                # Skip if already satisfied (data obtained, whether asked or volunteered)
                if q_id in questions_satisfied:
                    continue
                
                # Check if eligible (probe or condition met)
                if not self._is_eligible(question, episode):
                    continue
                
                # Found next question - convert to QuestionOutput
                return self._dict_to_question_output(question)
        
        # Step 3: All done
        return None
    
    def get_next_n_questions(self, current_question_id: str, n: int = 3) -> List[QuestionOutput]:
        """
        Get the next n questions in sequence after current_question_id.
        
        This method is used to build a metadata window for the Response Parser,
        allowing it to extract information for upcoming questions when patients
        volunteer information ahead of being asked.
        
        V4 Changes:
        - Returns List[QuestionOutput] instead of list of dicts
        - Entry-point assertions validate inputs
        
        Rules:
        - Returns only questions from the same symptom category (prefix)
        - Ignores all conditions (includes conditional questions regardless of state)
        - Returns questions in sequential numeric order
        - Does not wrap to next symptom category at boundary
        - Returns fewer than n questions if near end of category
        - Returns empty list if current question is last in category or not found
        
        Args:
            current_question_id: Question ID (e.g., "vl_5", "cp_2")
            n: Number of questions to return (default 3)
        
        Returns:
            List of QuestionOutput (immutable dataclasses), may be empty or shorter than n.
        
        Raises:
            AssertionError: If inputs violate invariants
        
        Examples:
            get_next_n_questions("vl_5", 3) -> [QuestionOutput(id='vl_6',...), ...]
            get_next_n_questions("vl_20", 3) -> [QuestionOutput(id='vl_21',...)]
            get_next_n_questions("vl_21", 3) -> []
        """
        # Entry-point assertions
        if not isinstance(current_question_id, str):
            raise AssertionError(
                f"current_question_id must be str, got {type(current_question_id).__name__}"
            )
        if not isinstance(n, int):
            raise AssertionError(f"n must be int, got {type(n).__name__}")
        
        # Handle edge case: n <= 0
        if n <= 0:
            return []
        
        # Extract symptom prefix and number from current question ID
        # e.g., "vl_5" -> prefix="vl", num=5
        parts = current_question_id.split('_')
        if len(parts) < 2:
            logger.warning(f"Invalid question_id format: {current_question_id}")
            return []
        
        # Prefix is everything except the last part (handles multi-part prefixes)
        # Last part must be numeric
        try:
            current_num = int(parts[-1])
            prefix = '_'.join(parts[:-1])
        except ValueError:
            logger.warning(f"Question ID does not end with number: {current_question_id}")
            return []
        
        # Collect all questions with matching prefix from entire ruleset
        matching_questions = []
        
        # Scan sections
        for section_name in self.section_order:
            section_questions = self.sections.get(section_name, [])
            for question in section_questions:
                q_id = question.get('id', '')
                q_parts = q_id.split('_')
                
                if len(q_parts) >= 2:
                    try:
                        q_num = int(q_parts[-1])
                        q_prefix = '_'.join(q_parts[:-1])
                        
                        if q_prefix == prefix:
                            matching_questions.append((q_num, question))
                    except ValueError:
                        continue
        
        # Scan follow-up blocks
        for block_id, block_def in self.follow_up_blocks.items():
            block_questions = block_def.get("questions", [])
            for question in block_questions:
                q_id = question.get('id', '')
                q_parts = q_id.split('_')
                
                if len(q_parts) >= 2:
                    try:
                        q_num = int(q_parts[-1])
                        q_prefix = '_'.join(q_parts[:-1])
                        
                        if q_prefix == prefix:
                            matching_questions.append((q_num, question))
                    except ValueError:
                        continue
        
        # Sort by question number
        matching_questions.sort(key=lambda x: x[0])
        
        # Find next n questions after current_num, convert to QuestionOutput
        result = []
        for q_num, question in matching_questions:
            if q_num > current_num:
                result.append(self._dict_to_question_output(question))
                if len(result) >= n:
                    break
        
        return result
    
    def check_triggers(self, episode_data: dict) -> set:
        """
        Check which follow-up blocks should be activated based on current state.
        
        Args:
            episode_data: Current episode state with extracted fields
            
        Returns:
            set[str]: Block IDs that should be activated (e.g., {'block_1', 'block_3'})
            
        Raises:
            AssertionError: If episode_data violates invariants
            
        Note:
            Returns ALL blocks whose conditions are met, not just new ones.
            Caller is responsible for idempotency - compare with existing
            activated set to find new activations.
        """
        # Validate input (raises AssertionError on failure)
        self._validate_episode_data(episode_data)
        
        # Defensive copy
        episode = self._defensive_copy_episode_data(episode_data)
        
        activated_blocks = set()
        
        for trigger_name, trigger_def in self.trigger_conditions.items():
            condition = trigger_def.get("condition", {})
            activates = trigger_def.get("activates")
            
            # Evaluate trigger condition
            if self._evaluate_dsl(condition, episode):
                # Add activated block(s)
                if isinstance(activates, list):
                    activated_blocks.update(activates)
                else:
                    activated_blocks.add(activates)
        
        return activated_blocks
    
    def is_block_complete(self, block_id: str, episode_data: dict) -> bool:
        """
        Check if all questions in a block are answered or skipped.
        
        Args:
            block_id: Block identifier (e.g., 'block_1')
            episode_data: Current episode state
            
        Returns:
            True if block is complete (all questions answered or ineligible)
            
        Raises:
            AssertionError: If episode_data violates invariants
            
        Note:
            Ineligible questions are treated as implicitly skipped.
            If eligibility later changes (new data), block cannot reopen.
            This behavior will be revisited in V3 with contradiction detection.
        """
        # Entry-point assertion for block_id
        if not isinstance(block_id, str):
            raise AssertionError(f"block_id must be str, got {type(block_id).__name__}")
        
        if block_id not in self.follow_up_blocks:
            logger.warning(f"Unknown block: {block_id}")
            return True  # Treat unknown block as complete
        
        # Validate input (raises AssertionError on failure)
        self._validate_episode_data(episode_data)
        
        # Defensive copy
        episode = self._defensive_copy_episode_data(episode_data)
        
        questions_answered = episode["questions_answered"]
        block_questions = self.follow_up_blocks[block_id].get("questions", [])
        
        for question in block_questions:
            q_id = question.get("id")
            
            # If answered, continue
            if q_id in questions_answered:
                continue
            
            # If not eligible (condition not met), skip
            if not self._is_eligible(question, episode):
                continue
            
            # Found unanswered, eligible question
            return False
        
        return True
    
    # =========================================================================
    # Condition Evaluation
    # =========================================================================
    
    def _evaluate_condition(self, condition_name: str, episode_data: dict) -> bool:
        """
        Evaluate a named condition against episode data.
        
        Args:
            condition_name: Key in ruleset['conditions']
            episode_data: Current episode state
            
        Returns:
            bool: True if condition met, False otherwise
            
        Note:
            Missing fields evaluate to False (field doesn't exist = condition not met)
        """
        condition_def = self.conditions.get(condition_name)
        
        if not condition_def:
            logger.warning(f"Unknown condition: {condition_name}")
            return False
        
        return self._evaluate_dsl(condition_def, episode_data)
    
    def _evaluate_dsl(self, dsl: dict, episode_data: dict) -> bool:
        """
        Evaluate DSL condition structure.
        
        Supported operators:
            - Logical: all, any
            - Comparison: eq, ne, gt, gte, lt, lte
            - Boolean: is_true, is_false
            - Existence: exists
            - String: contains_lower
        
        Semantics:
            - Missing field always evaluates to False (except for 'exists')
            - Empty "all": True (vacuous truth)
            - Empty "any": False (no conditions met)
            - Empty DSL root: True (no constraints)
            - Unknown operator: raises ValueError (fail fast)
        
        Args:
            dsl: DSL condition dict
            episode_data: Current episode state
            
        Returns:
            bool: Evaluation result
            
        Raises:
            ValueError: If unknown DSL operator encountered
        """
        if not dsl:
            return True  # Empty condition is vacuously true
        
        # Logical operators
        if "all" in dsl:
            conditions = dsl["all"]
            if not conditions:
                return True  # Empty all = vacuous truth
            return all(self._evaluate_dsl(sub, episode_data) for sub in conditions)
        
        if "any" in dsl:
            conditions = dsl["any"]
            if not conditions:
                return False  # Empty any = no conditions met
            return any(self._evaluate_dsl(sub, episode_data) for sub in conditions)
        
        # Comparison operators - missing field = False
        if "eq" in dsl:
            field, expected = dsl["eq"]
            if field not in episode_data:
                return False  # Missing field = condition not met
            return episode_data[field] == expected
        
        if "ne" in dsl:
            field, expected = dsl["ne"]
            if field not in episode_data:
                return False  # Missing field = condition not met (FIXED: was True)
            return episode_data[field] != expected
        
        # Boolean operators - missing field = False
        if "is_true" in dsl:
            field = dsl["is_true"]
            if field not in episode_data:
                return False  # Missing field = condition not met
            return episode_data[field] is True
        
        if "is_false" in dsl:
            field = dsl["is_false"]
            if field not in episode_data:
                return False  # Missing field = condition not met
            return episode_data[field] is False
        
        # Existence operator - the one operator where missing field matters
        if "exists" in dsl:
            field = dsl["exists"]
            return field in episode_data and episode_data[field] is not None
        
        # String operator - missing field = False
        if "contains_lower" in dsl:
            field, substring = dsl["contains_lower"]
            if field not in episode_data:
                return False  # Missing field = condition not met
            value = episode_data[field]
            if not isinstance(value, str):
                return False  # Non-string = condition not met
            return substring.lower() in value.lower()
        
        # Numeric comparison operators - missing field = False
        if "gte" in dsl:
            field, threshold = dsl["gte"]
            if field not in episode_data:
                return False  # Missing field = condition not met
            value = episode_data[field]
            if value is None:
                return False
            try:
                return float(value) >= float(threshold)
            except (TypeError, ValueError):
                return False  # Type mismatch = condition not met
        
        if "gt" in dsl:
            field, threshold = dsl["gt"]
            if field not in episode_data:
                return False
            value = episode_data[field]
            if value is None:
                return False
            try:
                return float(value) > float(threshold)
            except (TypeError, ValueError):
                return False
        
        if "lte" in dsl:
            field, threshold = dsl["lte"]
            if field not in episode_data:
                return False
            value = episode_data[field]
            if value is None:
                return False
            try:
                return float(value) <= float(threshold)
            except (TypeError, ValueError):
                return False
        
        if "lt" in dsl:
            field, threshold = dsl["lt"]
            if field not in episode_data:
                return False
            value = episode_data[field]
            if value is None:
                return False
            try:
                return float(value) < float(threshold)
            except (TypeError, ValueError):
                return False
        
        # Unknown operator - fail fast (this is a ruleset bug)
        raise ValueError(f"Unknown DSL operator: {list(dsl.keys())}")
    
    # =========================================================================
    # Question Selection Helpers
    # =========================================================================
    
    def _is_eligible(self, question: dict, episode_data: dict) -> bool:
        """
        Determine if a question is eligible to be asked.
        
        Rules:
        - Probe question: always eligible
        - Conditional question: eligible only if condition is true
        
        Note: Type and condition presence validated at initialization by _validate_ruleset()
        
        Args:
            question: Question dict from ruleset
            episode_data: Current episode state
            
        Returns:
            True if question should be asked
        """
        q_type = question.get("type", "probe")
        
        # Probe questions are always eligible
        if q_type == "probe":
            return True
        
        # Conditional questions require condition to be met
        if q_type == "conditional":
            condition_name = question.get("condition")
            return self._evaluate_condition(condition_name, episode_data)
        
        # Unknown type - treat as probe (shouldn't happen due to validation)
        return True
    
    def _get_next_block_question(
        self, 
        block_id: str, 
        questions_satisfied: set, 
        episode_data: dict
    ) -> Optional[dict]:
        """
        Get next unanswered, eligible question from a block.
        
        This is an internal method - caller (get_next_question) is responsible
        for making a defensive copy before returning to external code.
        
        Args:
            block_id: Block identifier
            questions_satisfied: Set of satisfied question IDs (data obtained)
            episode_data: Current episode state (already defensively copied)
            
        Returns:
            Question dict (internal reference) or None if block complete
        """
        if block_id not in self.follow_up_blocks:
            return None
        
        block_questions = self.follow_up_blocks[block_id].get("questions", [])
        
        for question in block_questions:
            q_id = question.get("id")
            
            # Skip satisfied (data already obtained)
            if q_id in questions_satisfied:
                continue
            
            # Skip ineligible
            if not self._is_eligible(question, episode_data):
                continue
            
            return question
        
        return None
    
    # =========================================================================
    # Validation
    # =========================================================================
    
    def _validate_question(self, question: dict, location: str, errors: list) -> Optional[str]:
        """
        Validate a single question dict.
        
        Args:
            question: Question dict to validate
            location: Description of where question is (for error messages)
            errors: List to append errors to
            
        Returns:
            Question ID if valid (for duplicate tracking), None if ID missing
        """
        # Check required fields
        missing_fields = self.REQUIRED_QUESTION_FIELDS - set(question.keys())
        if missing_fields:
            if 'id' in missing_fields:
                errors.append(f"Question in {location} missing 'id' field")
                return None
            else:
                q_id = question['id']
                errors.append(f"Question '{q_id}' in {location} missing required fields: {missing_fields}")
                return q_id
        
        q_id = question['id']
        
        # Check question type is valid
        q_type = question.get('type', '').strip()
        if not q_type:
            errors.append(f"Question '{q_id}' in {location} has no type specified")
            q_type = 'probe'  # Set default for remaining validation
        
        if q_type not in self.VALID_QUESTION_TYPES:
            errors.append(
                f"Question '{q_id}' in {location} has invalid type '{q_type}'. "
                f"Valid types: {self.VALID_QUESTION_TYPES}"
            )
        
        # Check conditional questions have condition reference
        if q_type == 'conditional':
            condition_name = question.get('condition', '').strip()
            if not condition_name:
                errors.append(f"Question '{q_id}' in {location} is conditional but has no condition specified")
            elif condition_name not in self.conditions:
                errors.append(
                    f"Question '{q_id}' in {location} references undefined condition '{condition_name}'"
                )
        
        return q_id
    
    def _validate_ruleset(self):
        """
        Validate ruleset structure on initialization.
        
        Checks:
        - section_order exists and references defined sections
        - All questions have required fields (id, question, field)
        - All question types are valid (probe, conditional)
        - All condition references exist
        - All trigger block references exist
        - No duplicate question IDs globally
        - No empty block question arrays
        
        Raises:
            ValueError: If validation fails (fail fast)
        """
        errors = []
        
        # Check section_order exists
        if not self.section_order:
            errors.append("Missing 'section_order' in ruleset")
        else:
            # Check all sections in order are defined
            for section_name in self.section_order:
                if section_name not in self.sections:
                    errors.append(f"Section '{section_name}' in section_order but not defined in sections")
        
        # Collect all question IDs for duplicate detection
        all_question_ids = set()
        
        # Validate section questions
        for section_name, questions in self.sections.items():
            for i, question in enumerate(questions):
                location = f"section '{section_name}' index {i}"
                q_id = self._validate_question(question, location, errors)
                
                if q_id:
                    # Check for global duplicates
                    if q_id in all_question_ids:
                        errors.append(f"Duplicate question id '{q_id}'")
                    all_question_ids.add(q_id)
        
        # Validate follow-up blocks
        for block_id, block_def in self.follow_up_blocks.items():
            questions = block_def.get("questions", [])
            
            # Check for empty questions array
            if not questions:
                errors.append(f"Block '{block_id}' has empty questions array")
                continue
            
            block_question_ids = set()
            
            for i, question in enumerate(questions):
                location = f"block '{block_id}' index {i}"
                q_id = self._validate_question(question, location, errors)
                
                if q_id:
                    # Check for duplicates within block
                    if q_id in block_question_ids:
                        errors.append(f"Duplicate question id '{q_id}' within block '{block_id}'")
                    block_question_ids.add(q_id)
                    
                    # Check for global duplicates
                    if q_id in all_question_ids:
                        errors.append(f"Duplicate question id '{q_id}'")
                    all_question_ids.add(q_id)
        
        # Validate trigger conditions
        for trigger_name, trigger_def in self.trigger_conditions.items():
            activates = trigger_def.get("activates")
            
            if not activates:
                errors.append(f"Trigger '{trigger_name}' missing 'activates' field")
                continue
            
            # Check block references
            block_ids = activates if isinstance(activates, list) else [activates]
            
            for block_id in block_ids:
                if block_id not in self.follow_up_blocks:
                    errors.append(
                        f"Trigger '{trigger_name}' activates undefined block '{block_id}'"
                    )
        
        # Raise if any errors
        if errors:
            error_msg = "Ruleset validation failed:\n  - " + "\n  - ".join(errors)
            raise ValueError(error_msg)
        
        logger.info("Ruleset validation passed")
    
    def _build_field_mappings(self) -> None:
        """
        Build deterministic fieldâ†”question mappings from ruleset.
        
        Called once during initialization. Treats every question-field pair
        as 1:1 (primary field only).
        
        Walks through all questions in sections and follow_up_blocks to create:
        - _question_to_field: Maps question_id -> field_name
        - _field_to_questions: Maps field_name -> frozenset of question_ids
        
        This mapping is derived from the immutable ruleset and enables the
        Question Satisfaction Model: when a field is extracted, we can mark
        all questions that would provide that field as satisfied.
        
        Design rationale:
        - One field per question (primary field)
        - Multi-field questions deferred to V5+
        - Deterministic: same ruleset always produces same mapping
        - Immutable: built once, never modified
        """
        # Temporary mutable dict for building
        field_to_questions_temp = {}
        
        # Walk all section questions
        for section_name in self.section_order:
            section_questions = self.sections.get(section_name, [])
            
            for question in section_questions:
                q_id = question.get("id")
                field = question.get("field")
                
                if not q_id or not field:
                    # Should not happen - validation caught this
                    continue
                
                # Record question -> field (1:1)
                self._question_to_field[q_id] = field
                
                # Record field -> questions (1:many)
                if field not in field_to_questions_temp:
                    field_to_questions_temp[field] = set()
                field_to_questions_temp[field].add(q_id)
        
        # Walk all follow-up block questions
        for block_id, block_def in self.follow_up_blocks.items():
            block_questions = block_def.get("questions", [])
            
            for question in block_questions:
                q_id = question.get("id")
                field = question.get("field")
                
                if not q_id or not field:
                    # Should not happen - validation caught this
                    continue
                
                # Record question -> field (1:1)
                self._question_to_field[q_id] = field
                
                # Record field -> questions (1:many)
                if field not in field_to_questions_temp:
                    field_to_questions_temp[field] = set()
                field_to_questions_temp[field].add(q_id)
        
        # Freeze field -> questions mapping (immutable after construction)
        self._field_to_questions = {
            field: frozenset(q_ids)
            for field, q_ids in field_to_questions_temp.items()
        }
        
        logger.info(
            f"Built field mappings: {len(self._question_to_field)} questions, "
            f"{len(self._field_to_questions)} unique fields"
        )
    
    # =========================================================================
    # Public Field Mapping API
    # =========================================================================
    
    def get_question_requirements(self) -> dict[str, frozenset[str]]:
        """
        Get field requirements for each question.
        
        Returns a mapping from question_id to the set of fields required to
        satisfy that question. Currently always a singleton set (1:1 mapping)
        as we treat each question as having exactly one primary field.
        
        This mapping is derived from the immutable ruleset and can be used by
        the Dialogue Manager to determine which questions should be marked
        satisfied when fields are extracted.
        
        Returns:
            dict mapping question_id -> frozenset of required field names
            
        Note:
            Currently always returns singleton frozensets (one field per question).
            Future versions may support multi-field questions.
            
        Example:
            {
                'vl_1': frozenset({'vl_present'}),
                'vl_2': frozenset({'vl_single_eye'}),
                'vl_3': frozenset({'vl_laterality'}),
                ...
            }
        """
        return {
            q_id: frozenset([field]) 
            for q_id, field in self._question_to_field.items()
        }
    
    def get_field_to_questions_mapping(self) -> dict[str, frozenset[str]]:
        """
        Get reverse mapping: field -> questions that would satisfy it.
        
        This is the inverse of get_question_requirements() and is more
        convenient for the Dialogue Manager's use case: given extracted
        fields, find all questions to mark as satisfied.
        
        Returns:
            dict mapping field_name -> frozenset of question_ids
            
        Example:
            {
                'vl_present': frozenset({'vl_1'}),
                'vl_single_eye': frozenset({'vl_2'}),
                'vl_laterality': frozenset({'vl_3'}),
                ...
            }
        """
        # Return copy to prevent external mutation
        return self._field_to_questions.copy()
