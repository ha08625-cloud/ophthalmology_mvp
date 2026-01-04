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
- Fail fast: Validate ruleset on initialization
- Immutable: Ruleset frozen at load, returns are copies

Contracts:
- episode_data must contain:
    - questions_answered: set[str]
    - follow_up_blocks_activated: set[str]
    - follow_up_blocks_completed: set[str]
    - Extracted fields as key-value pairs
- Returns are always copies (safe to mutate)
- Caller is responsible for trigger idempotency (check_triggers returns
  ALL matching blocks, not just new ones)

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
from typing import Optional, Any

logger = logging.getLogger(__name__)


class QuestionSelectorV2:
    """
    Stateless question selector for multi-episode consultations.
    
    Determines the next question based on episode state and medical protocol.
    Does not track any state internally - all state comes from episode_data.
    
    Thread Safety:
        Ruleset is deep-copied and frozen at initialization.
        All public methods return copies, never internal references.
    """
    
    # Required keys in episode_data
    REQUIRED_EPISODE_KEYS = {
        'questions_answered',
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
        
        logger.info(f"Question Selector V2 initialized with {len(self.section_order)} sections")
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def _validate_episode_data(self, episode_data: dict) -> None:
        """
        Validate episode_data structure and types.
        
        Args:
            episode_data: Input to validate
            
        Raises:
            TypeError: If episode_data is wrong type or has wrong field types
            ValueError: If required keys are missing
        """
        if not isinstance(episode_data, dict):
            raise TypeError(f"episode_data must be dict, got {type(episode_data).__name__}")
        
        # Check required keys exist
        missing = self.REQUIRED_EPISODE_KEYS - set(episode_data.keys())
        if missing:
            raise ValueError(f"episode_data missing required keys: {missing}")
        
        # Validate types of tracking sets
        for key in self.REQUIRED_EPISODE_KEYS:
            value = episode_data[key]
            # Accept both set and list (State Manager may serialize sets as lists)
            if not isinstance(value, (set, list)):
                raise TypeError(
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
    
    def get_next_question(self, episode_data: dict) -> Optional[dict]:
        """
        Get next question for episode.
        
        Args:
            episode_data: Complete episode state containing:
                - questions_answered: set[str] or list[str]
                - follow_up_blocks_activated: set[str] or list[str]
                - follow_up_blocks_completed: set[str] or list[str]
                - [extracted fields]: e.g., vl_laterality, h_present, etc.
        
        Returns:
            Question dict (copy) with keys: id, question, field, field_type, etc.
            None if no more questions for this episode.
            
        Raises:
            TypeError: If episode_data has wrong types
            ValueError: If episode_data missing required keys
        """
        # Validate input
        self._validate_episode_data(episode_data)
        
        # Defensive copy to prevent caller mutation affecting our logic
        episode = self._defensive_copy_episode_data(episode_data)
        
        # Extract tracking sets (now guaranteed to be sets)
        questions_answered = episode["questions_answered"]
        blocks_activated = episode["follow_up_blocks_activated"]
        blocks_completed = episode["follow_up_blocks_completed"]
        
        # Step 1: Check for pending follow-up block questions
        pending_blocks = blocks_activated - blocks_completed
        
        for block_id in sorted(pending_blocks):  # Deterministic order
            next_q = self._get_next_block_question(block_id, questions_answered, episode)
            if next_q is not None:
                return copy.deepcopy(next_q)  # Return copy, not original
        
        # Step 2: Walk sections in order
        for section_name in self.section_order:
            section_questions = self.sections.get(section_name, [])
            
            for question in section_questions:
                q_id = question.get("id")
                
                # Skip if already answered
                if q_id in questions_answered:
                    continue
                
                # Check if eligible (probe or condition met)
                if not self._is_eligible(question, episode):
                    continue
                
                # Found next question - return copy
                return copy.deepcopy(question)
        
        # Step 3: All done
        return None
    
    def get_next_n_questions(self, current_question_id: str, n: int = 3) -> list:
        """
        Get the next n questions in sequence after current_question_id.
        
        This method is used to build a metadata window for the Response Parser,
        allowing it to extract information for upcoming questions when patients
        volunteer information ahead of being asked.
        
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
            List of question dicts (copies), may be empty or shorter than n.
            Each dict contains: id, question, field, field_type, valid_values, etc.
        
        Examples:
            get_next_n_questions("vl_5", 3) -> [vl_6, vl_7, vl_8]
            get_next_n_questions("vl_20", 3) -> [vl_21]  # only 1 left
            get_next_n_questions("vl_21", 3) -> []  # last question
            get_next_n_questions("cp_8", 3) -> [cp_9]  # doesn't wrap to next category
        """
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
        
        # Find next n questions after current_num
        result = []
        for q_num, question in matching_questions:
            if q_num > current_num:
                result.append(copy.deepcopy(question))
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
            TypeError: If episode_data has wrong types
            ValueError: If episode_data missing required keys
            
        Note:
            Returns ALL blocks whose conditions are met, not just new ones.
            Caller is responsible for idempotency - compare with existing
            activated set to find new activations.
        """
        # Validate input
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
            TypeError: If episode_data has wrong types
            ValueError: If episode_data missing required keys
            
        Note:
            Ineligible questions are treated as implicitly skipped.
            If eligibility later changes (new data), block cannot reopen.
            This behavior will be revisited in V3 with contradiction detection.
        """
        if block_id not in self.follow_up_blocks:
            logger.warning(f"Unknown block: {block_id}")
            return True  # Treat unknown block as complete
        
        # Validate input
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
        questions_answered: set, 
        episode_data: dict
    ) -> Optional[dict]:
        """
        Get next unanswered, eligible question from a block.
        
        This is an internal method - caller (get_next_question) is responsible
        for making a defensive copy before returning to external code.
        
        Args:
            block_id: Block identifier
            questions_answered: Set of answered question IDs
            episode_data: Current episode state (already defensively copied)
            
        Returns:
            Question dict (internal reference) or None if block complete
        """
        if block_id not in self.follow_up_blocks:
            return None
        
        block_questions = self.follow_up_blocks[block_id].get("questions", [])
        
        for question in block_questions:
            q_id = question.get("id")
            
            # Skip answered
            if q_id in questions_answered:
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