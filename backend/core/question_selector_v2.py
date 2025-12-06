"""
Question Selector V2 - Multi-episode deterministic question selection

Responsibilities:
- Parse ruleset_v2_0_2.json (same as V1)
- Select next required question for current episode
- Apply conditional logic (episode-scoped)
- Detect and activate trigger blocks (per-episode)
- Track consultation progress per episode

Design principles:
- Fully deterministic - no LLM involvement
- Episode-aware - all operations scoped to current episode
- Medical protocol compliance guaranteed
- Automatic state reset on episode transition
- Thin surface - minimal API

Key differences from V1:
- get_next_question() requires episode_id parameter
- Per-episode tracking of answered questions
- Per-episode trigger activation
- Episode-scoped field checks and condition evaluation
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Set, Any

logger = logging.getLogger(__name__)


class QuestionSelectorV2:
    """Selects next question based on episode state and medical protocol"""
    
    def __init__(self, ruleset_path: str, state_manager):
        """
        Initialize Question Selector V2
        
        Args:
            ruleset_path (str): Path to ruleset_v2_0_2.json
            state_manager: StateManagerV2 instance
            
        Raises:
            FileNotFoundError: If ruleset file doesn't exist
            json.JSONDecodeError: If ruleset is malformed
        """
        self.logger = logging.getLogger(__name__)
        self.state = state_manager
        self.ruleset = self._load_ruleset(ruleset_path)
        
        # Section order (fixed sequence for MVP)
        self.section_order = [
            "vision_loss",
            "visual_disturbances",
            "headache",
            "eye_pain",
            "appearance_changes",
            "healthcare_contacts",
            "other_symptoms",
            "functional_impact"
        ]
        
        # Per-episode tracking
        self.answered_per_episode: Dict[int, Set[str]] = {}
        self.section_index_per_episode: Dict[int, int] = {}
        self.core_complete_per_episode: Dict[int, bool] = {}
        self.triggered_blocks_per_episode: Dict[int, List[str]] = {}
        self.blocks_asked_per_episode: Dict[int, Set[str]] = {}
        
        # Track last episode to detect transitions
        self.last_episode_id: Optional[int] = None
        
        self.logger.info("Question Selector V2 initialized (multi-episode)")
    
    def _load_ruleset(self, path: str) -> dict:
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
    
    def get_next_question(self, current_episode_id: int) -> Optional[dict]:
        """
        Get next question to ask for current episode
        
        Automatically resets state when episode_id changes.
        
        Args:
            current_episode_id (int): Which episode we're asking about (1-indexed)
            
        Returns:
            dict: Question object with id, question, field, etc.
                  None if episode complete
                  
        Raises:
            ValueError: If episode_id doesn't exist in State Manager
        """
        # Validate episode exists
        if current_episode_id not in self.state.list_episode_ids():
            raise ValueError(f"Episode {current_episode_id} does not exist in State Manager")
        
        # Detect episode transition - only initialize if new episode
        if current_episode_id != self.last_episode_id:
            if current_episode_id not in self.answered_per_episode:
                # New episode - initialize tracking state
                self._initialize_episode_state(current_episode_id)
            self.last_episode_id = current_episode_id
        
        # Get answered questions for this episode
        answered = self.answered_per_episode[current_episode_id]
        
        # Process core sections sequentially
        if not self.core_complete_per_episode[current_episode_id]:
            section_index = self.section_index_per_episode[current_episode_id]
            
            while section_index < len(self.section_order):
                section_name = self.section_order[section_index]
                question = self._get_next_from_section(
                    section_name, 
                    current_episode_id, 
                    answered
                )
                
                if question:
                    self.logger.debug(
                        f"Episode {current_episode_id}: Returning question {question['id']} "
                        f"from section {section_name}"
                    )
                    return question
                else:
                    # Section complete, move to next
                    self.logger.info(
                        f"Episode {current_episode_id}: Section {section_name} complete"
                    )
                    section_index += 1
                    self.section_index_per_episode[current_episode_id] = section_index
            
            # All core sections complete
            self.core_complete_per_episode[current_episode_id] = True
            self.logger.info(
                f"Episode {current_episode_id}: All core sections complete, checking triggers"
            )
            self._check_triggers(current_episode_id)
        
        # Process triggered follow-up blocks
        triggered_blocks = self.triggered_blocks_per_episode[current_episode_id]
        blocks_asked = self.blocks_asked_per_episode[current_episode_id]
        
        for block_name in triggered_blocks:
            if block_name not in blocks_asked:
                question = self._get_next_from_block(
                    block_name, 
                    current_episode_id, 
                    answered
                )
                
                if question:
                    self.logger.debug(
                        f"Episode {current_episode_id}: Returning question {question['id']} "
                        f"from block {block_name}"
                    )
                    return question
                else:
                    # Block complete
                    blocks_asked.add(block_name)
                    self.logger.info(
                        f"Episode {current_episode_id}: Block {block_name} complete"
                    )
        
        # Everything complete for this episode
        self.logger.info(f"Episode {current_episode_id}: All questions complete")
        return None
    
    def mark_question_answered(self, episode_id: int, question_id: str) -> None:
        """
        Mark a question as answered for an episode
        
        This should be called by Dialogue Manager after processing response.
        
        Args:
            episode_id (int): Episode this question belongs to
            question_id (str): Question identifier (e.g., 'vl_2')
            
        Raises:
            ValueError: If episode not initialized
        """
        if episode_id not in self.answered_per_episode:
            raise ValueError(
                f"Episode {episode_id} not initialized. "
                f"Call get_next_question() first."
            )
        
        self.answered_per_episode[episode_id].add(question_id)
        self.logger.debug(f"Episode {episode_id}: Marked {question_id} as answered")
    
    def _initialize_episode_state(self, episode_id: int) -> None:
        """
        Initialize tracking state for new episode
        
        Called automatically on episode transition.
        
        Args:
            episode_id (int): Episode to initialize
        """
        self.answered_per_episode[episode_id] = set()
        self.section_index_per_episode[episode_id] = 0
        self.core_complete_per_episode[episode_id] = False
        self.triggered_blocks_per_episode[episode_id] = []
        self.blocks_asked_per_episode[episode_id] = set()
        
        self.logger.info(f"Episode {episode_id}: Initialized question tracking state")
    
    def _get_next_from_section(
        self, 
        section_name: str, 
        episode_id: int, 
        answered: Set[str]
    ) -> Optional[dict]:
        """
        Get next applicable question from a section
        
        Args:
            section_name (str): Section identifier
            episode_id (int): Current episode
            answered (Set[str]): Set of answered question IDs
            
        Returns:
            dict: Question object or None if section complete
        """
        questions = self.ruleset["sections"][section_name]
        
        for question in questions:
            question_id = question["id"]
            
            # Skip if already answered
            if question_id in answered:
                self.logger.debug(
                    f"Episode {episode_id}: Question {question_id} already answered, skipping"
                )
                continue
            
            # Skip if field already collected (patient volunteered info)
            if "field" in question:
                if self.state.has_episode_field(episode_id, question["field"]):
                    field_value = self.state.get_episode_field(episode_id, question["field"])
                    self.logger.debug(
                        f"Episode {episode_id}: Field {question['field']} already collected "
                        f"(value: {field_value}), skipping {question_id}"
                    )
                    continue
            
            # Check conditional
            if question.get("type") == "conditional":
                condition_name = question.get("condition")
                if not condition_name:
                    self.logger.error(
                        f"Episode {episode_id}: Question {question_id} marked conditional "
                        f"but no condition specified"
                    )
                    continue
                
                if not self._evaluate_condition(condition_name, episode_id):
                    self.logger.debug(
                        f"Episode {episode_id}: Question {question_id} condition "
                        f"'{condition_name}' = False, skipping"
                    )
                    continue
                else:
                    self.logger.debug(
                        f"Episode {episode_id}: Question {question_id} condition "
                        f"'{condition_name}' = True, asking"
                    )
            
            # Question is applicable
            return question
        
        # No applicable questions remain in section
        return None
    
    def _get_next_from_block(
        self, 
        block_name: str, 
        episode_id: int, 
        answered: Set[str]
    ) -> Optional[dict]:
        """
        Get next applicable question from a triggered block
        
        Args:
            block_name (str): Block identifier (e.g., "block_1")
            episode_id (int): Current episode
            answered (Set[str]): Set of answered question IDs
            
        Returns:
            dict: Question object or None if block complete
        """
        if block_name not in self.ruleset["follow_up_blocks"]:
            self.logger.error(
                f"Episode {episode_id}: Block {block_name} not found in ruleset"
            )
            return None
        
        block = self.ruleset["follow_up_blocks"][block_name]
        questions = block["questions"]
        
        for question in questions:
            question_id = question["id"]
            
            # Skip if already answered
            if question_id in answered:
                self.logger.debug(
                    f"Episode {episode_id}: Question {question_id} already answered, skipping"
                )
                continue
            
            # Skip if field already collected
            if "field" in question:
                if self.state.has_episode_field(episode_id, question["field"]):
                    field_value = self.state.get_episode_field(episode_id, question["field"])
                    self.logger.debug(
                        f"Episode {episode_id}: Field {question['field']} already collected "
                        f"(value: {field_value}), skipping {question_id}"
                    )
                    continue
            
            # Check conditional
            if question.get("type") == "conditional":
                condition_name = question.get("condition")
                if not condition_name:
                    self.logger.error(
                        f"Episode {episode_id}: Question {question_id} marked conditional "
                        f"but no condition specified"
                    )
                    continue
                
                if not self._evaluate_condition(condition_name, episode_id):
                    self.logger.debug(
                        f"Episode {episode_id}: Question {question_id} condition "
                        f"'{condition_name}' = False, skipping"
                    )
                    continue
                else:
                    self.logger.debug(
                        f"Episode {episode_id}: Question {question_id} condition "
                        f"'{condition_name}' = True, asking"
                    )
            
            # Question is applicable
            return question
        
        # No applicable questions remain in block
        return None
    
    def _evaluate_condition(self, condition_name: str, episode_id: int) -> bool:
        """
        Evaluate a named condition from the ruleset (episode-scoped)
        
        Args:
            condition_name (str): Condition identifier
            episode_id (int): Episode to evaluate condition for
            
        Returns:
            bool: True if condition met, False otherwise
            
        Raises:
            KeyError: If condition not defined in ruleset
        """
        if condition_name not in self.ruleset["conditions"]:
            raise KeyError(
                f"Condition '{condition_name}' not defined in ruleset"
            )
        
        condition = self.ruleset["conditions"][condition_name]
        check_string = condition["check"]
        
        result = self._parse_condition_string(check_string, episode_id)
        self.logger.debug(
            f"Episode {episode_id}: Condition '{condition_name}': "
            f"{check_string} = {result}"
        )
        return result
    
    def _parse_condition_string(self, check_string: str, episode_id: int) -> bool:
        """
        Parse and evaluate a condition check string (episode-scoped)
        
        Handles:
        - Equality: "field == 'value'"
        - Inequality: "field != 'value'"
        - Membership: "field in ['a', 'b']"
        - Boolean: "field == True"
        - Null checks: "field != None"
        - Logical operators: "condition1 AND condition2"
        
        Args:
            check_string (str): Condition expression to evaluate
            episode_id (int): Episode to read fields from
            
        Returns:
            bool: Result of evaluation
            
        Raises:
            ValueError: If expression is malformed
        """
        # Handle AND operators
        if " AND " in check_string:
            parts = check_string.split(" AND ")
            results = [
                self._parse_condition_string(part.strip(), episode_id) 
                for part in parts
            ]
            return all(results)
        
        # Handle OR operators
        if " OR " in check_string:
            parts = check_string.split(" OR ")
            results = [
                self._parse_condition_string(part.strip(), episode_id) 
                for part in parts
            ]
            return any(results)
        
        # Single expression - parse it
        return self._evaluate_single_expression(check_string, episode_id)
    
    def _evaluate_single_expression(self, expression: str, episode_id: int) -> bool:
        """
        Evaluate a single comparison expression (episode-scoped)
        
        Args:
            expression (str): Single expression like "field == 'value'"
            episode_id (int): Episode to read field from
            
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
            
            # Episode-scoped field read
            field_value = self.state.get_episode_field(episode_id, field_name)
            result = field_value in values
            self.logger.debug(
                f"Episode {episode_id}: Membership check: "
                f"{field_name} (={field_value}) in {values} = {result}"
            )
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
        
        # Episode-scoped field read
        field_value = self.state.get_episode_field(episode_id, field_name)
        
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
            raise ValueError(
                f"Expected value must be True/False/None or quoted string: {expression}"
            )
        
        # Evaluate
        if operator == "==":
            result = field_value == expected_value
        else:  # !=
            # Special handling for None checks
            if expected_value is None:
                result = field_value is not None
            else:
                result = field_value != expected_value
        
        self.logger.debug(
            f"Episode {episode_id}: Comparison: "
            f"{field_name} (={field_value}) {operator} {expected_value} = {result}"
        )
        return result
    
    def _check_triggers(self, episode_id: int) -> None:
        """
        Check all trigger conditions and activate applicable blocks (episode-scoped)
        
        Modifies self.triggered_blocks_per_episode[episode_id] in place
        
        Args:
            episode_id (int): Episode to evaluate triggers for
        """
        self.logger.info(f"Episode {episode_id}: Evaluating trigger conditions")
        
        triggered = []
        
        for trigger_name, trigger_config in self.ruleset["trigger_conditions"].items():
            check_string = trigger_config["check"]
            activates = trigger_config["activates"]
            
            # Evaluate trigger condition (episode-scoped)
            try:
                result = self._parse_condition_string(check_string, episode_id)
                
                if result:
                    self.logger.info(
                        f"Episode {episode_id}: Trigger '{trigger_name}' = True, "
                        f"activating {activates}"
                    )
                    
                    # Handle both single block and list of blocks
                    if isinstance(activates, list):
                        triggered.extend(activates)
                    else:
                        triggered.append(activates)
                else:
                    self.logger.debug(f"Episode {episode_id}: Trigger '{trigger_name}' = False")
                    
            except Exception as e:
                self.logger.error(
                    f"Episode {episode_id}: Error evaluating trigger '{trigger_name}': {e}"
                )
        
        # Remove duplicates while preserving order
        seen = set()
        unique_blocks = []
        for block in triggered:
            if block not in seen:
                seen.add(block)
                unique_blocks.append(block)
        
        self.triggered_blocks_per_episode[episode_id] = unique_blocks
        
        if unique_blocks:
            self.logger.info(
                f"Episode {episode_id}: Triggered blocks: {unique_blocks}"
            )
        else:
            self.logger.info(f"Episode {episode_id}: No triggers activated")
    
    def get_progress_summary(self, episode_id: int) -> dict:
        """
        Get summary of consultation progress for specific episode
        
        Args:
            episode_id (int): Episode to query
            
        Returns:
            dict: Progress information
            
        Raises:
            ValueError: If episode not initialized
        """
        if episode_id not in self.answered_per_episode:
            raise ValueError(
                f"Episode {episode_id} not initialized. "
                f"Call get_next_question() first."
            )
        
        answered = self.answered_per_episode[episode_id]
        
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
        triggered_blocks = self.triggered_blocks_per_episode.get(episode_id, [])
        
        for block_name in triggered_blocks:
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
            "episode_id": episode_id,
            "core_sections_complete": self.core_complete_per_episode.get(episode_id, False),
            "current_section": (
                self.section_order[self.section_index_per_episode[episode_id]] 
                if self.section_index_per_episode[episode_id] < len(self.section_order) 
                else None
            ),
            "section_progress": section_progress,
            "triggered_blocks": triggered_blocks,
            "block_progress": block_progress,
            "total_questions_answered": len(answered)
        }