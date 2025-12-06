"""
Dialogue Manager V2 - Multi-episode consultation orchestration

Responsibilities:
- Coordinate question-answer loop across multiple episodes
- Route fields to episode-specific or shared storage
- Handle episode transitions with retry logic
- Generate final outputs (JSON + summary)
- Error handling and logging

Design principles:
- Thin orchestration layer (business logic in specialized modules)
- Track current_episode_id as internal UI state
- Trust Response Parser with retry logic for ambiguity
- Quarantine unmapped fields in dialogue metadata
"""

import logging
import os
from enum import Enum, auto
from datetime import datetime
from pathlib import Path

from backend.utils.helpers import (
    generate_consultation_id,
    generate_consultation_filename,
    ConsultationValidator
)
from backend.utils.episode_classifier import classify_field

logger = logging.getLogger(__name__)


class ConsultationState(Enum):
    """Simple state enum for logging and debugging"""
    INITIALIZING = auto()
    ASKING_EPISODE = auto()
    EPISODE_TRANSITION = auto()
    COMPLETE = auto()
    ERROR = auto()


class DialogueManagerV2:
    """
    Orchestrates multi-episode ophthalmology consultation
    
    Thin coordinator - delegates work to specialized modules
    """
    
    # Commands that trigger early exit
    EXIT_COMMANDS = {"quit", "exit", "stop"}
    
    # Episode transition control
    MAX_TRANSITION_RETRIES = 2
    TRANSITION_QUESTION = {
        'id': 'episode_transition',
        'question': 'Have you had any other episodes of eye-related problems you would like to discuss?',
        'field': 'additional_episodes_present',
        'field_type': 'boolean'
    }
    
    def __init__(self, state_manager, question_selector, response_parser,
                 json_formatter, summary_generator, validator=None):
        """
        Initialize Dialogue Manager V2 with all required modules
        
        Args:
            state_manager (StateManagerV2): Multi-episode state tracker
            question_selector (QuestionSelector): Selects next question
            response_parser (ResponseParser): Extracts data from responses
            json_formatter (JSONFormatter): Generates JSON output
            summary_generator (SummaryGenerator): Generates clinical summary
            validator (ConsultationValidator, optional): Validates completeness
            
        Raises:
            TypeError: If any required module is missing or wrong type
        """
        # Validate module interfaces
        if not (hasattr(state_manager, 'create_episode') and 
                callable(getattr(state_manager, 'create_episode', None))):
            raise TypeError("state_manager must have callable create_episode() method")
        
        if not (hasattr(state_manager, 'set_episode_field') and 
                callable(getattr(state_manager, 'set_episode_field', None))):
            raise TypeError("state_manager must have callable set_episode_field() method")
        
        if not (hasattr(question_selector, 'get_next_question') and 
                callable(getattr(question_selector, 'get_next_question', None))):
            raise TypeError("question_selector must have callable get_next_question() method")
        
        if not (hasattr(response_parser, 'parse') and 
                callable(getattr(response_parser, 'parse', None))):
            raise TypeError("response_parser must have callable parse() method")
        
        if not (hasattr(json_formatter, 'to_dict') and 
                callable(getattr(json_formatter, 'to_dict', None))):
            raise TypeError("json_formatter must have callable to_dict() method")
        
        if not (hasattr(summary_generator, 'generate') and 
                callable(getattr(summary_generator, 'generate', None))):
            raise TypeError("summary_generator must have callable generate() method")
        
        # Store module references
        self.state = state_manager
        self.selector = question_selector
        self.parser = response_parser
        self.json_formatter = json_formatter
        self.summary_generator = summary_generator
        self.validator = validator
        
        # Initialize internal state
        self.consultation_state = ConsultationState.INITIALIZING
        self.current_episode_id = None  # Tracks active episode (UI state)
        self.errors = []  # Track errors during consultation
        self.consultation_id = generate_consultation_id(short=True)
        
        logger.info(f"Dialogue Manager V2 initialized (consultation_id={self.consultation_id})")
    
    def run_consultation(self, input_fn=input, output_fn=print, 
                        output_dir="outputs/consultations", on_finish=None):
        """
        Run complete multi-episode consultation from start to finish
        
        Args:
            input_fn (callable): Function to get user input (default: built-in input)
            output_fn (callable): Function to display output (default: built-in print)
            output_dir (str): Directory for output files
            on_finish (callable, optional): Callback when consultation completes
        
        Returns:
            dict: Consultation results with keys:
                - completed (bool): True if naturally complete, False if early exit
                - consultation_id (str): Unique ID for this consultation
                - total_episodes (int): Number of episodes
                - total_questions (int): Number of questions asked
                - json_path (str): Path to JSON output file
                - summary_path (str): Path to summary text file
                - json (dict): JSON data structure
                - summary (str): Summary text
                - validation (dict): Validation results
                - errors (list): Any errors encountered
        """
        try:
            # Welcome message
            self._show_welcome(output_fn)
            
            # Main conversation loop (multi-episode)
            completed, total_questions, total_episodes = self._conversation_loop_v2(
                input_fn, output_fn
            )
            
            # Generate outputs
            output_fn("\n" + "="*60)
            output_fn("GENERATING CONSULTATION OUTPUTS")
            output_fn("="*60)
            
            # TODO: JSON Formatter V2 needed - V1 won't handle episode array
            # For now, create placeholder
            json_data = {'episodes': [], 'shared_data': {}, 'metadata': {}}
            json_path = os.path.join(output_dir, "placeholder_v2.json")
            output_fn(f"⚠ JSON output: Placeholder (V2 formatter needed)")
            
            # TODO: Summary Generator V2 needed - V1 won't handle multiple episodes
            summary_text = "Multi-episode summary generation not yet implemented"
            summary_path = os.path.join(output_dir, "placeholder_v2.txt")
            output_fn(f"⚠ Summary output: Placeholder (V2 generator needed)")
            
            # Validate completeness (placeholder)
            validation_result = None
            
            # Show closing message
            self._show_closing(output_fn, completed, total_episodes, 
                             json_path, summary_path, validation_result)
            
            # Build result dict
            result = {
                'completed': completed,
                'consultation_id': self.consultation_id,
                'total_episodes': total_episodes,
                'total_questions': total_questions,
                'json_path': json_path,
                'summary_path': summary_path,
                'json': json_data,
                'summary': summary_text,
                'validation': validation_result.to_dict() if validation_result else None,
                'errors': self.errors
            }
            
            # Call finish callback if provided
            if on_finish:
                on_finish(result)
            
            self.consultation_state = ConsultationState.COMPLETE
            logger.info(f"Consultation {self.consultation_id} completed successfully")
            
            return result
            
        except Exception as e:
            self.consultation_state = ConsultationState.ERROR
            logger.error(f"Consultation failed: {e}")
            self._handle_error(e, context="run_consultation")
            raise
    
    def _conversation_loop_v2(self, input_fn, output_fn):
        """
        Main question-answer loop with multi-episode support
        
        Args:
            input_fn (callable): Get user input
            output_fn (callable): Display output
            
        Returns:
            tuple: (completed, total_questions, total_episodes)
        """
        total_questions = 0
        total_episodes = 0
        
        output_fn("\n" + "="*60)
        output_fn("CONSULTATION QUESTIONS")
        output_fn("="*60)
        output_fn("(Type 'quit', 'exit', or 'stop' to end early)\n")
        
        # Create first episode
        self.current_episode_id = self._create_first_episode()
        total_episodes = 1
        
        while True:
            self.consultation_state = ConsultationState.ASKING_EPISODE
            
            # Ask all questions for current episode
            episode_complete, questions_asked = self._ask_episode_questions(
                input_fn, output_fn, total_questions
            )
            
            total_questions += questions_asked
            
            # Check for early exit
            if not episode_complete:
                output_fn("\n✓ Consultation ended early by user")
                logger.info("User requested early exit")
                return False, total_questions, total_episodes
            
            # Episode complete - ask about additional episodes
            self.consultation_state = ConsultationState.EPISODE_TRANSITION
            
            create_new_episode = self._ask_episode_transition_question(
                input_fn, output_fn
            )
            
            if create_new_episode:
                # Create next episode
                self.current_episode_id = self.state.create_episode()
                total_episodes += 1
                logger.info(f"Created Episode {self.current_episode_id}")
                output_fn(f"\n{'='*60}")
                output_fn(f"STARTING EPISODE {self.current_episode_id}")
                output_fn(f"{'='*60}\n")
            else:
                # No more episodes - consultation complete
                output_fn("\n✓ Consultation complete - all episodes documented")
                logger.info("All episodes complete")
                return True, total_questions, total_episodes
    
    def _create_first_episode(self):
        """
        Create Episode 1 at start of consultation
        
        Returns:
            int: Episode ID (always 1 for first episode)
        """
        episode_id = self.state.create_episode()
        logger.info(f"Created Episode {episode_id}")
        return episode_id
    
    def _ask_episode_questions(self, input_fn, output_fn, question_offset):
        """
        Ask all questions for current episode
        
        Args:
            input_fn: Get user input
            output_fn: Display output
            question_offset: Starting question number (for display)
            
        Returns:
            tuple: (episode_complete, questions_asked)
                - episode_complete: True if naturally finished, False if early exit
                - questions_asked: Number of questions asked
        """
        questions_asked = 0
        
        while True:
            # Get next question for current episode
            question_dict = self.selector.get_next_question()
            
            # Check if episode complete (no more questions)
            if question_dict is None:
                logger.info(f"Episode {self.current_episode_id} complete - no more questions")
                return True, questions_asked
            
            # Display question
            question_text = question_dict.get('question', '[No question text]')
            question_id = question_dict.get('id', 'unknown')
            field = question_dict.get('field', 'unknown')
            
            question_number = question_offset + questions_asked + 1
            output_fn(f"\nQ{question_number}: {question_text}")
            logger.info(f"Episode {self.current_episode_id} - Asked: id={question_id}, field={field}")
            
            # Get patient response
            try:
                response = input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                # Handle Ctrl+D or Ctrl+C
                output_fn("\n\nConsultation interrupted by user")
                return False, questions_asked
            
            # Check for exit command
            if self._is_exit_command(response):
                return False, questions_asked
            
            # Parse response
            try:
                extracted = self.parser.parse(
                    question=question_dict,
                    patient_response=response
                )
                logger.info(f"Parsed response: id={question_id}, extracted={len(extracted)} fields")
                
            except Exception as e:
                # Don't crash on parse error - continue consultation
                logger.error(f"Parse error for {question_id}: {e}")
                self._handle_error(e, context=f"parse_{question_id}")
                extracted = {}
            
            # Route extracted fields to appropriate storage
            unmapped = self._route_extracted_fields(
                episode_id=self.current_episode_id,
                extracted=extracted
            )
            
            # Add dialogue turn with unmapped fields in metadata
            try:
                self.state.add_dialogue_turn(
                    episode_id=self.current_episode_id,
                    question_id=question_id,
                    question_text=question_text,
                    patient_response=response,
                    extracted_fields={
                        **extracted,
                        '_unmapped': unmapped  # Quarantine in dialogue metadata
                    }
                )
            except Exception as e:
                logger.error(f"Dialogue turn recording error: {e}")
                self._handle_error(e, context=f"dialogue_turn_{question_id}")
            
            questions_asked += 1
    
    def _route_extracted_fields(self, episode_id, extracted):
        """
        Route extracted fields to episode-specific or shared storage
        
        Args:
            episode_id (int): Current episode ID
            extracted (dict): Fields extracted by Response Parser
            
        Returns:
            dict: Unmapped fields (for logging in dialogue metadata)
        """
        unmapped = {}
        
        for field_name, value in extracted.items():
            # Skip metadata fields
            if field_name.startswith('_'):
                continue
            
            # Classify field
            classification = classify_field(field_name)
            
            if classification == 'episode':
                # Route to episode-specific storage
                try:
                    self.state.set_episode_field(episode_id, field_name, value)
                    logger.debug(f"Episode {episode_id}: {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to set episode field {field_name}: {e}")
                    self._handle_error(e, context=f"set_episode_field_{field_name}")
                    
            elif classification == 'shared':
                # Route to shared storage
                try:
                    self.state.set_shared_field(field_name, value)
                    logger.debug(f"Shared data: {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to set shared field {field_name}: {e}")
                    self._handle_error(e, context=f"set_shared_field_{field_name}")
                    
            else:
                # Unknown field - quarantine
                unmapped[field_name] = value
                logger.warning(
                    f"Unmapped field: {field_name} = {value} "
                    f"(episode_id={episode_id})"
                )
        
        return unmapped
    
    def _ask_episode_transition_question(self, input_fn, output_fn):
        """
        Ask "Any other episodes?" with retry logic
        
        Trusts Response Parser but adds retry mechanism for unclear responses.
        
        Args:
            input_fn: Get user input
            output_fn: Display output
            
        Returns:
            bool: True if create new episode, False if no more episodes
        """
        retry_count = 0
        
        while retry_count < self.MAX_TRANSITION_RETRIES:
            # Display question
            output_fn(f"\n{self.TRANSITION_QUESTION['question']}")
            
            # Get response
            try:
                response = input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                output_fn("\n\nConsultation interrupted")
                return False
            
            # Check for exit command
            if self._is_exit_command(response):
                logger.info("User requested exit during episode transition")
                return False
            
            # Parse response
            try:
                extracted = self.parser.parse(
                    question=self.TRANSITION_QUESTION,
                    patient_response=response
                )
            except Exception as e:
                logger.error(f"Parse error on episode transition: {e}")
                self._handle_error(e, context="episode_transition_parse")
                extracted = {}
            
            # Check if parser extracted the field
            field = self.TRANSITION_QUESTION['field']
            
            if field in extracted:
                # Parser got clear answer
                additional_episodes = extracted[field]
                
                if additional_episodes:
                    logger.info("Episode transition: User confirmed additional episode")
                    return True
                else:
                    logger.info("Episode transition: User declined additional episode")
                    return False
            
            # Parser unclear - retry
            retry_count += 1
            
            if retry_count < self.MAX_TRANSITION_RETRIES:
                output_fn("I didn't quite catch that. Please answer yes or no.")
                logger.debug(f"Episode transition unclear, retry {retry_count}/{self.MAX_TRANSITION_RETRIES}")
            else:
                # Max retries reached - assume "no"
                output_fn("I'll assume that's a no. Moving on to generate your summary.")
                logger.info("Episode transition: Max retries reached, assuming no additional episodes")
                return False
    
    def _show_welcome(self, output_fn):
        """Display welcome message"""
        output_fn("\n" + "="*60)
        output_fn("OPHTHALMOLOGY CONSULTATION SYSTEM - V2 (Multi-Episode)")
        output_fn("="*60)
        output_fn(f"Consultation ID: {self.consultation_id}")
        output_fn("This system will ask you questions about your vision.")
        output_fn("You can describe multiple episodes of symptoms.")
        output_fn("Please answer as accurately as possible.")
        output_fn("="*60)
    
    def _show_closing(self, output_fn, completed, total_episodes, 
                     json_path, summary_path, validation):
        """
        Display closing message with results
        
        Args:
            output_fn (callable): Display function
            completed (bool): Whether consultation naturally completed
            total_episodes (int): Number of episodes
            json_path (str): Path to JSON file
            summary_path (str): Path to summary file
            validation: Validation results
        """
        output_fn("\n" + "="*60)
        output_fn("CONSULTATION COMPLETE")
        output_fn("="*60)
        
        if completed:
            output_fn(f"✓ Documented {total_episodes} episode(s)")
        else:
            output_fn("⚠ Consultation ended early")
        
        output_fn(f"\nOutput files:")
        output_fn(f"  • JSON: {json_path}")
        output_fn(f"  • Summary: {summary_path}")
        
        if validation:
            output_fn(f"\nCompleteness: {validation.completeness_score:.1%}")
            if not validation.is_complete:
                output_fn(f"  Missing {len(validation.missing_required)} required fields")
        
        if self.errors:
            output_fn(f"\n⚠ {len(self.errors)} errors occurred during consultation")
            output_fn("  (See logs for details)")
        
        output_fn("\nThank you for using the consultation system.")
        output_fn("="*60)
    
    def _is_exit_command(self, text):
        """Check if user input is an exit command"""
        return text.strip().lower() in self.EXIT_COMMANDS
    
    def _handle_error(self, error, context=""):
        """
        Centralized error handling
        
        Logs error and tracks in internal error list.
        Does not raise - allows consultation to continue.
        """
        error_record = {
            'context': context,
            'error': str(error),
            'timestamp': datetime.now().isoformat()
        }
        
        self.errors.append(error_record)
        logger.error(f"Error in {context}: {error}")