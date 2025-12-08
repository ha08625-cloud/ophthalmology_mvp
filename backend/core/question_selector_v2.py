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

Provenance hooks:
- _evaluate_condition() and _evaluate_dsl() can be wrapped later
- check_triggers() returns block IDs (can be extended with trigger names)
- is_block_complete() can be extended to return skip reasons
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class QuestionSelectorV2:
    """
    Stateless question selector for multi-episode consultations.
    
    Determines the next question based on episode state and medical protocol.
    Does not track any state internally - all state comes from episode_data.
    """
    
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
            self.ruleset = json.load(f)
        
        # Extract top-level components
        self.section_order = self.ruleset.get("section_order")
        self.conditions = self.ruleset.get("conditions", {})
        self.trigger_conditions = self.ruleset.get("trigger_conditions", {})
        self.sections = self.ruleset.get("sections", {})
        self.follow_up_blocks = self.ruleset.get("follow_up_blocks", {})
        
        # Validate ruleset structure
        self._validate_ruleset()
        
        logger.info(f"Question Selector V2 initialized with {len(self.section_order)} sections")
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    def get_next_question(self, episode_data: dict) -> Optional[dict]:
        """
        Get next question for episode.
        
        Args:
            episode_data: Complete episode state containing:
                - questions_answered: set[str]
                - follow_up_blocks_activated: set[str]
                - follow_up_blocks_completed: set[str]
                - [extracted fields]: e.g., vl_laterality, h_present, etc.
        
        Returns:
            Question dict with keys: id, question, field, field_type, etc.
            None if no more questions for this episode.
            
        Raises:
            KeyError: If episode_data missing required keys
        """
        # Extract required state
        questions_answered = episode_data.get("questions_answered", set())
        blocks_activated = episode_data.get("follow_up_blocks_activated", set())
        blocks_completed = episode_data.get("follow_up_blocks_completed", set())
        
        # Step 1: Check for pending follow-up block questions
        pending_blocks = blocks_activated - blocks_completed
        
        for block_id in sorted(pending_blocks):  # Deterministic order
            next_q = self._get_next_block_question(block_id, questions_answered, episode_data)
            if next_q is not None:
                return next_q
        
        # Step 2: Walk sections in order
        for section_name in self.section_order:
            section_questions = self.sections.get(section_name, [])
            
            for question in section_questions:
                q_id = question.get("id")
                
                # Skip if already answered
                if q_id in questions_answered:
                    continue
                
                # Check if eligible (probe or condition met)
                if not self._is_eligible(question, episode_data):
                    continue
                
                # Found next question
                return question
        
        # Step 3: All done
        return None
    
    def check_triggers(self, episode_data: dict) -> set:
        """
        Check which follow-up blocks should be activated based on current state.
        
        Args:
            episode_data: Current episode state with extracted fields
            
        Returns:
            set[str]: Block IDs that should be activated (e.g., {'block_1', 'block_3'})
            
        Note:
            Returns ALL blocks whose conditions are met, not just new ones.
            Caller should compare with existing activated set to find new activations.
        """
        activated_blocks = set()
        
        for trigger_name, trigger_def in self.trigger_conditions.items():
            condition = trigger_def.get("condition", {})
            activates = trigger_def.get("activates")
            
            # Evaluate trigger condition
            if self._evaluate_dsl(condition, episode_data):
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
        """
        if block_id not in self.follow_up_blocks:
            logger.warning(f"Unknown block: {block_id}")
            return True  # Treat unknown block as complete
        
        questions_answered = episode_data.get("questions_answered", set())
        block_questions = self.follow_up_blocks[block_id].get("questions", [])
        
        for question in block_questions:
            q_id = question.get("id")
            
            # If answered, continue
            if q_id in questions_answered:
                continue
            
            # If not eligible (condition not met), skip
            if not self._is_eligible(question, episode_data):
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
        
        Supports: all, any, eq, ne, is_true, is_false, exists, contains_lower
        
        Args:
            dsl: DSL condition dict
            episode_data: Current episode state
            
        Returns:
            bool: Evaluation result
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
        
        # Comparison operators
        if "eq" in dsl:
            field, expected = dsl["eq"]
            actual = episode_data.get(field)
            return actual == expected
        
        if "ne" in dsl:
            field, expected = dsl["ne"]
            actual = episode_data.get(field)
            return actual != expected
        
        # Boolean operators
        if "is_true" in dsl:
            field = dsl["is_true"]
            return episode_data.get(field) is True
        
        if "is_false" in dsl:
            field = dsl["is_false"]
            return episode_data.get(field) is False
        
        # Existence operator
        if "exists" in dsl:
            field = dsl["exists"]
            return field in episode_data and episode_data[field] is not None
        
        # String operator
        if "contains_lower" in dsl:
            field, substring = dsl["contains_lower"]
            value = episode_data.get(field)
            if not isinstance(value, str):
                return False
            return substring.lower() in value.lower()
        
        # Numeric comparison operators
        if "gte" in dsl:
            field, threshold = dsl["gte"]
            value = episode_data.get(field)
            if value is None:
                return False
            try:
                return float(value) >= float(threshold)
            except (TypeError, ValueError):
                return False
        
        if "gt" in dsl:
            field, threshold = dsl["gt"]
            value = episode_data.get(field)
            if value is None:
                return False
            try:
                return float(value) > float(threshold)
            except (TypeError, ValueError):
                return False
        
        if "lte" in dsl:
            field, threshold = dsl["lte"]
            value = episode_data.get(field)
            if value is None:
                return False
            try:
                return float(value) <= float(threshold)
            except (TypeError, ValueError):
                return False
        
        if "lt" in dsl:
            field, threshold = dsl["lt"]
            value = episode_data.get(field)
            if value is None:
                return False
            try:
                return float(value) < float(threshold)
            except (TypeError, ValueError):
                return False
        
        # Unknown operator
        logger.warning(f"Unknown DSL operator: {list(dsl.keys())}")
        return False
    
    # =========================================================================
    # Question Selection Helpers
    # =========================================================================
    
    def _is_eligible(self, question: dict, episode_data: dict) -> bool:
        """
        Determine if a question is eligible to be asked.
        
        Rules:
        - Probe question: always eligible
        - Conditional question: eligible only if condition is true
        - Missing 'type' or 'condition': treated as probe
        
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
            
            # Missing condition treated as probe (always eligible)
            if not condition_name:
                return True
            
            return self._evaluate_condition(condition_name, episode_data)
        
        # Unknown type - treat as probe
        return True
    
    def _get_next_block_question(
        self, 
        block_id: str, 
        questions_answered: set, 
        episode_data: dict
    ) -> Optional[dict]:
        """
        Get next unanswered, eligible question from a block.
        
        Args:
            block_id: Block identifier
            questions_answered: Set of answered question IDs
            episode_data: Current episode state
            
        Returns:
            Question dict or None if block complete
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
    
    def _validate_ruleset(self):
        """
        Validate ruleset structure on initialization.
        
        Checks:
        - section_order exists
        - All sections in section_order are defined
        - All condition references exist
        - All trigger block references exist
        - No duplicate question IDs in blocks
        - No empty block question arrays
        - All questions have 'id' field
        
        Raises:
            ValueError: If validation fails
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
                # Check question has ID
                if "id" not in question:
                    errors.append(f"Question at index {i} in section '{section_name}' missing 'id'")
                    continue
                
                q_id = question["id"]
                
                # Check for global duplicates
                if q_id in all_question_ids:
                    errors.append(f"Duplicate question id '{q_id}'")
                all_question_ids.add(q_id)
                
                # Check condition reference
                if question.get("type") == "conditional":
                    condition_name = question.get("condition")
                    if condition_name and condition_name not in self.conditions:
                        errors.append(
                            f"Question '{q_id}' references undefined condition '{condition_name}'"
                        )
        
        # Validate follow-up blocks
        for block_id, block_def in self.follow_up_blocks.items():
            questions = block_def.get("questions", [])
            
            # Check for empty questions array
            if not questions:
                errors.append(f"Block '{block_id}' has empty questions array")
                continue
            
            block_question_ids = set()
            
            for i, question in enumerate(questions):
                # Check question has ID
                if "id" not in question:
                    errors.append(f"Question at index {i} in block '{block_id}' missing 'id'")
                    continue
                
                q_id = question["id"]
                
                # Check for duplicates within block
                if q_id in block_question_ids:
                    errors.append(f"Duplicate question id '{q_id}' in block '{block_id}'")
                block_question_ids.add(q_id)
                
                # Check for global duplicates
                if q_id in all_question_ids:
                    errors.append(f"Duplicate question id '{q_id}'")
                all_question_ids.add(q_id)
                
                # Check condition reference
                if question.get("type") == "conditional":
                    condition_name = question.get("condition")
                    if condition_name and condition_name not in self.conditions:
                        errors.append(
                            f"Question '{q_id}' in block '{block_id}' references "
                            f"undefined condition '{condition_name}'"
                        )
        
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