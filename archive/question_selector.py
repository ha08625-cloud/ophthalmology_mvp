"""
Question Selector - Deterministic module for selecting next question

Responsibilities:
- Parse mvp_ruleset.json
- Select next required question based on current state
- Apply conditional logic (skip questions if data already known)
- Detect and activate trigger blocks
- Track consultation progress

Design principles:
- Fully deterministic - no LLM involvement
- Medical protocol compliance guaranteed
- Verbose logging for MVP debugging
- Fail fast on errors
"""

import json
import logging
from pathlib import Path


class QuestionSelector:
    """Selects next question based on consultation state and medical protocol"""
    
    def __init__(self, ruleset_path, state_manager):
        """
        Initialize Question Selector
        
        Args:
            ruleset_path (str): Path to mvp_ruleset.json
            state_manager (StateManager): Reference to state manager instance
            
        Raises:
            FileNotFoundError: If ruleset file doesn't exist
            json.JSONDecodeError: If ruleset is malformed
        """
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        self.state = state_manager
        self.ruleset = self._load_ruleset(ruleset_path)
        
        # Section order (fixed sequence for MVP)
        self.section_order = [
            "chief_complaint",
            "vision_loss",
            "visual_disturbances",
            "headache",
            "eye_pain_and_changes",
            "healthcare_contacts",
            "other_symptoms",
            "functional_impact"
        ]
        
        # Internal tracking
        self.current_section_index = 0
        self.core_sections_complete = False
        self.triggered_blocks = []
        self.blocks_asked = set()
        self.first_question_asked = False
        
    def _load_ruleset(self, path):
        """
        Load and validate ruleset JSON
        
        Args:
            path (str): Path to ruleset file
            
        Returns:
            dict: Parsed ruleset
            
        Raises:
            FileNotFoundError: If file doesn't exist
            json.JSONDecodeError: If JSON is malformed
            ValueError: If required sections missing
        """
        ruleset_file = Path(path)
        
        if not ruleset_file.exists():
            raise FileNotFoundError(f"Ruleset not found: {path}")
        
        with open(ruleset_file, 'r') as f:
            ruleset = json.load(f)
        
        # Validate required sections exist
        required_sections = ["sections", "conditions", "trigger_conditions", "follow_up_blocks"]
        for section in required_sections:
            if section not in ruleset:
                raise ValueError(f"Ruleset missing required section: {section}")
        
        self.logger.info(f"Loaded ruleset from {path}")
        return ruleset
    
    def get_next_question(self):
        """
        Get next question to ask based on current state
        
        Returns:
            dict: Question object with id, question, field, etc.
                  None if consultation complete
        """
        # First question always chief_1
        if not self.first_question_asked:
            self.first_question_asked = True
            question = self.ruleset["sections"]["chief_complaint"][0]
            self.logger.info(f"Starting consultation, returning first question: {question['id']}")
            return question
        
        # Process core sections sequentially
        if not self.core_sections_complete:
            while self.current_section_index < len(self.section_order):
                section_name = self.section_order[self.current_section_index]
                question = self._get_next_from_section(section_name)
                
                if question:
                    self.logger.debug(f"Returning question {question['id']} from section {section_name}")
                    return question
                else:
                    # Section complete, move to next
                    self.logger.info(f"Section {section_name} complete")
                    self.current_section_index += 1
            
            # All core sections complete
            self.core_sections_complete = True
            self.logger.info("All core sections complete, checking triggers")
            self._check_triggers()
        
        # Process triggered follow-up blocks
        for block_name in self.triggered_blocks:
            if block_name not in self.blocks_asked:
                question = self._get_next_from_block(block_name)
                
                if question:
                    self.logger.debug(f"Returning question {question['id']} from block {block_name}")
                    return question
                else:
                    # Block complete
                    self.blocks_asked.add(block_name)
                    self.logger.info(f"Block {block_name} complete")
        
        # Everything complete
        self.logger.info("Consultation complete - no more questions")
        return None
    
    def _get_next_from_section(self, section_name):
        """
        Get next applicable question from a section
        
        Args:
            section_name (str): Section identifier
            
        Returns:
            dict: Question object or None if section complete
        """
        questions = self.ruleset["sections"][section_name]
        answered = self.state.get_answered_questions()
        
        for question in questions:
            question_id = question["id"]
            
            # Skip if already answered
            if question_id in answered:
                self.logger.debug(f"Question {question_id} already answered, skipping")
                continue
            
            # Skip if field already collected (patient volunteered info)
            if "field" in question and self.state.has_field(question["field"]):
                field_value = self.state.get_field(question["field"])
                self.logger.debug(f"Field {question['field']} already collected (value: {field_value}), skipping {question_id}")
                continue
            
            # Check conditional
            if question.get("type") == "conditional":
                condition_name = question.get("condition")
                if not condition_name:
                    self.logger.error(f"Question {question_id} marked conditional but no condition specified")
                    continue
                
                if not self._evaluate_condition(condition_name):
                    self.logger.debug(f"Question {question_id} condition '{condition_name}' = False, skipping")
                    continue
                else:
                    self.logger.debug(f"Question {question_id} condition '{condition_name}' = True, asking")
            
            # Question is applicable
            return question
        
        # No applicable questions remain in section
        return None
    
    def _get_next_from_block(self, block_name):
        """
        Get next applicable question from a triggered block
        
        Args:
            block_name (str): Block identifier (e.g., "block_1")
            
        Returns:
            dict: Question object or None if block complete
        """
        if block_name not in self.ruleset["follow_up_blocks"]:
            self.logger.error(f"Block {block_name} not found in ruleset")
            return None
        
        block = self.ruleset["follow_up_blocks"][block_name]
        questions = block["questions"]
        answered = self.state.get_answered_questions()
        
        for question in questions:
            question_id = question["id"]
            
            # Skip if already answered
            if question_id in answered:
                self.logger.debug(f"Question {question_id} already answered, skipping")
                continue
            
            # Skip if field already collected
            if "field" in question and self.state.has_field(question["field"]):
                field_value = self.state.get_field(question["field"])
                self.logger.debug(f"Field {question['field']} already collected (value: {field_value}), skipping {question_id}")
                continue
            
            # Check conditional
            if question.get("type") == "conditional":
                condition_name = question.get("condition")
                if not condition_name:
                    self.logger.error(f"Question {question_id} marked conditional but no condition specified")
                    continue
                
                if not self._evaluate_condition(condition_name):
                    self.logger.debug(f"Question {question_id} condition '{condition_name}' = False, skipping")
                    continue
                else:
                    self.logger.debug(f"Question {question_id} condition '{condition_name}' = True, asking")
            
            # Question is applicable
            return question
        
        # No applicable questions remain in block
        return None
    
    def _evaluate_condition(self, condition_name):
        """
        Evaluate a named condition from the ruleset
        
        Args:
            condition_name (str): Condition identifier
            
        Returns:
            bool: True if condition met, False otherwise
            
        Raises:
            KeyError: If condition not defined in ruleset
        """
        if condition_name not in self.ruleset["conditions"]:
            raise KeyError(f"Condition '{condition_name}' not defined in ruleset")
        
        condition = self.ruleset["conditions"][condition_name]
        check_string = condition["check"]
        
        result = self._parse_condition_string(check_string)
        self.logger.debug(f"Condition '{condition_name}': {check_string} = {result}")
        return result
    
    def _parse_condition_string(self, check_string):
        """
        Parse and evaluate a condition check string
        
        Handles:
        - Equality: "field == 'value'"
        - Inequality: "field != 'value'"
        - Membership: "field in ['a', 'b']"
        - Boolean: "field == True"
        - Null checks: "field != None"
        - Logical operators: "condition1 AND condition2"
        
        Args:
            check_string (str): Condition expression to evaluate
            
        Returns:
            bool: Result of evaluation
            
        Raises:
            ValueError: If expression is malformed
        """
        # Handle AND operators
        if " AND " in check_string:
            parts = check_string.split(" AND ")
            results = [self._parse_condition_string(part.strip()) for part in parts]
            return all(results)
        
        # Handle OR operators
        if " OR " in check_string:
            parts = check_string.split(" OR ")
            results = [self._parse_condition_string(part.strip()) for part in parts]
            return any(results)
        
        # Single expression - parse it
        return self._evaluate_single_expression(check_string)
    
    def _evaluate_single_expression(self, expression):
        """
        Evaluate a single comparison expression
        
        Args:
            expression (str): Single expression like "field == 'value'"
            
        Returns:
            bool: Result of evaluation
            
        Raises:
            ValueError: If expression format is invalid
        """
        expression = expression.strip()
        
        # Handle membership check: "field in ['a', 'b']"
        if " in [" in expression:
            field_name, values_str = expression.split(" in ")
            field_name = field_name.strip()
            
            # Extract list values
            values_str = values_str.strip()
            if not (values_str.startswith('[') and values_str.endswith(']')):
                raise ValueError(f"Invalid list format in expression: {expression}")
            
            # Parse list - handle both 'value' and "value" quotes
            values_str = values_str[1:-1]  # Remove [ ]
            values = []
            for val in values_str.split(','):
                val = val.strip()
                if val.startswith("'") and val.endswith("'"):
                    values.append(val[1:-1])
                elif val.startswith('"') and val.endswith('"'):
                    values.append(val[1:-1])
                else:
                    raise ValueError(f"List values must be quoted: {expression}")
            
            field_value = self.state.get_field(field_name)
            result = field_value in values
            self.logger.debug(f"Membership check: {field_name} (={field_value}) in {values} = {result}")
            return result
        
        # Handle equality/inequality: "field == 'value'" or "field != 'value'"
        if " == " in expression:
            operator = "=="
            field_name, expected = expression.split(" == ")
        elif " != " in expression:
            operator = "!="
            field_name, expected = expression.split(" != ")
        else:
            raise ValueError(f"Unsupported operator in expression: {expression}")
        
        field_name = field_name.strip()
        expected = expected.strip()
        
        # Get actual field value
        field_value = self.state.get_field(field_name)
        
        # Parse expected value
        if expected == "True":
            expected_value = True
        elif expected == "False":
            expected_value = False
        elif expected == "None":
            expected_value = None
        elif expected.startswith("'") and expected.endswith("'"):
            expected_value = expected[1:-1]
        elif expected.startswith('"') and expected.endswith('"'):
            expected_value = expected[1:-1]
        else:
            raise ValueError(f"Expected value must be True/False/None or quoted string: {expression}")
        
        # Evaluate
        if operator == "==":
            result = field_value == expected_value
        else:  # !=
            # Special handling for None checks
            if expected_value is None:
                result = field_value is not None
            else:
                result = field_value != expected_value
        
        self.logger.debug(f"Comparison: {field_name} (={field_value}) {operator} {expected_value} = {result}")
        return result
    
    def _check_triggers(self):
        """
        Check all trigger conditions and activate applicable blocks
        
        Modifies self.triggered_blocks in place
        """
        self.logger.info("Evaluating trigger conditions")
        
        for trigger_name, trigger_config in self.ruleset["trigger_conditions"].items():
            check_string = trigger_config["check"]
            activates = trigger_config["activates"]
            
            # Evaluate trigger condition
            try:
                result = self._parse_condition_string(check_string)
                
                if result:
                    self.logger.info(f"Trigger '{trigger_name}' = True, activating {activates}")
                    
                    # Handle both single block and list of blocks
                    if isinstance(activates, list):
                        self.triggered_blocks.extend(activates)
                    else:
                        self.triggered_blocks.append(activates)
                else:
                    self.logger.debug(f"Trigger '{trigger_name}' = False")
                    
            except Exception as e:
                self.logger.error(f"Error evaluating trigger '{trigger_name}': {e}")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_blocks = []
        for block in self.triggered_blocks:
            if block not in seen:
                seen.add(block)
                unique_blocks.append(block)
        self.triggered_blocks = unique_blocks
        
        if self.triggered_blocks:
            self.logger.info(f"Triggered blocks: {self.triggered_blocks}")
        else:
            self.logger.info("No triggers activated")
    
    def get_progress_summary(self):
        """
        Get summary of consultation progress (for debugging/UI)
        
        Returns:
            dict: Progress information
        """
        answered = self.state.get_answered_questions()
        
        # Count questions in each section
        section_progress = {}
        for section_name in self.section_order:
            questions = self.ruleset["sections"][section_name]
            total = len(questions)
            answered_count = sum(1 for q in questions if q["id"] in answered)
            section_progress[section_name] = {
                "answered": answered_count,
                "total": total,
                "complete": answered_count == total
            }
        
        # Count triggered block questions
        block_progress = {}
        for block_name in self.triggered_blocks:
            block = self.ruleset["follow_up_blocks"][block_name]
            questions = block["questions"]
            total = len(questions)
            answered_count = sum(1 for q in questions if q["id"] in answered)
            block_progress[block_name] = {
                "name": block["name"],
                "answered": answered_count,
                "total": total,
                "complete": answered_count == total
            }
        
        return {
            "core_sections_complete": self.core_sections_complete,
            "current_section": self.section_order[self.current_section_index] if self.current_section_index < len(self.section_order) else None,
            "section_progress": section_progress,
            "triggered_blocks": self.triggered_blocks,
            "block_progress": block_progress,
            "total_questions_answered": len(answered)
        }
