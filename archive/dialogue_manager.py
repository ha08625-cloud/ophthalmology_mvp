"""
Dialogue Manager - Orchestrates consultation flow

Responsibilities:
- Coordinate question-answer loop
- Call modules in correct sequence
- Handle user input/output via callbacks
- Generate final outputs (JSON + summary)
- Error handling and logging

Design principles:
- Thin orchestration layer (business logic in specialized modules)
- Dependency injection (all modules provided by caller)
- Callback-based I/O (testable, flexible)
- Graceful error handling (best effort, don't crash)
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

logger = logging.getLogger(__name__)


class ConsultationState(Enum):
    """Simple state enum for logging and debugging"""
    INITIALIZING = auto()
    ASKING = auto()
    COMPLETE = auto()
    ERROR = auto()


class DialogueManager:
    """
    Orchestrates complete ophthalmology consultation
    
    Thin coordinator - delegates work to specialized modules
    """
    
    # Commands that trigger early exit
    EXIT_COMMANDS = {"quit", "exit", "stop"}
    
    def __init__(self, state_manager, question_selector, response_parser,
                 json_formatter, summary_generator, validator=None):
        """
        Initialize Dialogue Manager with all required modules
        
        Args:
            state_manager (StateManager): Tracks consultation state
            question_selector (QuestionSelector): Selects next question
            response_parser (ResponseParser): Extracts data from responses
            json_formatter (JSONFormatter): Generates JSON output
            summary_generator (SummaryGenerator): Generates clinical summary
            validator (ConsultationValidator, optional): Validates completeness
            
        Raises:
            TypeError: If any required module is missing or wrong type
        """
        # Validate module interfaces (duck typing - check for required methods)
        # Use callable() to ensure methods are actually callable
        
        # State Manager
        if not (hasattr(state_manager, 'update') and callable(getattr(state_manager, 'update', None))):
            raise TypeError("state_manager must have callable update() method")
        if not (hasattr(state_manager, 'export_for_json') and callable(getattr(state_manager, 'export_for_json', None))):
            raise TypeError("state_manager must have callable export_for_json() method")
        
        # Question Selector
        if not (hasattr(question_selector, 'get_next_question') and callable(getattr(question_selector, 'get_next_question', None))):
            raise TypeError("question_selector must have callable get_next_question() method")
        
        # Response Parser
        if not (hasattr(response_parser, 'parse') and callable(getattr(response_parser, 'parse', None))):
            raise TypeError("response_parser must have callable parse() method")
        
        # JSON Formatter
        if not (hasattr(json_formatter, 'to_dict') and callable(getattr(json_formatter, 'to_dict', None))):
            raise TypeError(f"json_formatter must have callable to_dict() method. Has: {dir(json_formatter)}")
        if not (hasattr(json_formatter, 'save') and callable(getattr(json_formatter, 'save', None))):
            raise TypeError(f"json_formatter must have callable save() method. Has: {dir(json_formatter)}")
        
        # Summary Generator
        if not (hasattr(summary_generator, 'generate') and callable(getattr(summary_generator, 'generate', None))):
            raise TypeError("summary_generator must have callable generate() method")
        if not (hasattr(summary_generator, 'save_summary') and callable(getattr(summary_generator, 'save_summary', None))):
            raise TypeError("summary_generator must have callable save_summary() method")
        
        # Store module references
        self.state = state_manager
        self.selector = question_selector
        self.parser = response_parser
        self.json_formatter = json_formatter
        self.summary_generator = summary_generator
        self.validator = validator
        
        # Initialize internal state
        self.consultation_state = ConsultationState.INITIALIZING
        self.errors = []  # Track errors during consultation
        self.consultation_id = generate_consultation_id(short=True)
        
        logger.info(f"Dialogue Manager initialized (consultation_id={self.consultation_id})")
    
    def run_consultation(self, input_fn=input, output_fn=print, 
                        output_dir="outputs/consultations", on_finish=None):
        """
        Run complete consultation from start to finish
        
        Args:
            input_fn (callable): Function to get user input (default: built-in input)
                                 Signature: () -> str
            output_fn (callable): Function to display output (default: built-in print)
                                  Signature: (str) -> None
            output_dir (str): Directory for output files
            on_finish (callable, optional): Callback when consultation completes
                                           Signature: (result_dict) -> None
        
        Returns:
            dict: Consultation results with keys:
                - completed (bool): True if naturally complete, False if early exit
                - consultation_id (str): Unique ID for this consultation
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
            
            # Main conversation loop
            completed, total_questions = self._conversation_loop(input_fn, output_fn)
            
            # Generate outputs
            output_fn("\n" + "="*60)
            output_fn("GENERATING CONSULTATION OUTPUTS")
            output_fn("="*60)
            
            json_data, json_path = self._generate_json_output(output_dir)
            output_fn(f"✓ JSON output: {json_path}")
            
            summary_text, summary_path = self._generate_summary_output(output_dir)
            output_fn(f"✓ Summary output: {summary_path}")
            
            # Validate completeness
            validation_result = self._validate_consultation()
            
            # Show closing message
            self._show_closing(output_fn, completed, json_path, summary_path, validation_result)
            
            # Build result dict
            result = {
                'completed': completed,
                'consultation_id': self.consultation_id,
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
    
    def _conversation_loop(self, input_fn, output_fn):
        """
        Main question-answer loop
        
        Args:
            input_fn (callable): Get user input
            output_fn (callable): Display output
            
        Returns:
            tuple: (completed, total_questions)
                - completed (bool): True if naturally complete, False if early exit
                - total_questions (int): Number of questions asked
        """
        self.consultation_state = ConsultationState.ASKING
        total_questions = 0
        
        output_fn("\n" + "="*60)
        output_fn("CONSULTATION QUESTIONS")
        output_fn("="*60)
        output_fn("(Type 'quit', 'exit', or 'stop' to end early)\n")
        
        while True:
            # Get next question
            question_dict = self.selector.get_next_question()
            
            # Check if consultation naturally complete
            if question_dict is None:
                output_fn("\n✓ Consultation complete - all applicable questions answered")
                logger.info("Question selector returned None - consultation complete")
                return True, total_questions
            
            # Display question
            question_text = question_dict.get('question', '[No question text]')
            question_id = question_dict.get('id', 'unknown')
            field = question_dict.get('field', 'unknown')
            
            output_fn(f"\nQ{total_questions + 1}: {question_text}")
            logger.info(f"Asked question: id={question_id}, field={field}")
            
            # Get patient response
            try:
                response = input_fn("> ").strip()
            except (EOFError, KeyboardInterrupt):
                # Handle Ctrl+D or Ctrl+C
                output_fn("\n\nConsultation interrupted by user")
                return False, total_questions
            
            # Check for exit command
            if self._is_exit_command(response):
                output_fn("\n✓ Consultation ended early by user")
                logger.info("User requested early exit")
                return False, total_questions
            
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
            
            # Update state
            try:
                self.state.update(
                    question_id=question_id,
                    question_text=question_text,
                    patient_response=response,
                    extracted_fields=extracted
                )
            except Exception as e:
                logger.error(f"State update error: {e}")
                self._handle_error(e, context=f"state_update_{question_id}")
            
            total_questions += 1
        
        # Should never reach here
        return True, total_questions
    
    def _generate_json_output(self, output_dir):
        """
        Generate JSON output from consultation state
        
        Args:
            output_dir (str): Output directory path
            
        Returns:
            tuple: (json_data, json_path)
        """
        try:
            # Get state data
            state_data = self.state.export_for_json()
            
            # Generate JSON structure
            json_data = self.json_formatter.to_dict(
                state_data,
                consultation_id=self.consultation_id
            )
            
            # Generate filename and save
            filename = generate_consultation_filename(
                prefix="consultation",
                extension="json"
            )
            json_path = os.path.join(output_dir, filename)
            
            # Ensure directory exists and save
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            self.json_formatter.save(json_data, json_path)
            
            logger.info(f"JSON output generated: {json_path}")
            
            return json_data, json_path
            
        except Exception as e:
            logger.error(f"JSON generation failed: {e}")
            self._handle_error(e, context="generate_json")
            raise
    
    def _generate_summary_output(self, output_dir):
        """
        Generate clinical summary from consultation dialogue
        
        Args:
            output_dir (str): Output directory path
            
        Returns:
            tuple: (summary_text, summary_path)
        """
        try:
            # Get dialogue and structured data
            summary_data = self.state.export_for_summary()
            
            # Generate summary
            summary_text = self.summary_generator.generate(
                dialogue_history=summary_data['dialogue'],
                structured_data=summary_data['structured'],
                temperature=0.1,
                target_length="medium"
            )
            
            # Generate filename and save
            filename = generate_consultation_filename(
                prefix="summary",
                extension="txt"
            )
            summary_path = os.path.join(output_dir, filename)
            
            # Ensure directory exists and save
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            self.summary_generator.save_summary(summary_text, summary_path)
            
            logger.info(f"Summary output generated: {summary_path}")
            
            return summary_text, summary_path
            
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            self._handle_error(e, context="generate_summary")
            raise
    
    def _validate_consultation(self):
        """
        Validate consultation completeness
        
        Returns:
            ValidationResult or None: Validation results
        """
        if self.validator is None:
            logger.info("No validator provided - skipping validation")
            return None
        
        try:
            state_data = self.state.export_for_json()
            validation_result = self.validator.validate(state_data)
            
            logger.info(
                f"Validation complete: "
                f"is_complete={validation_result.is_complete}, "
                f"score={validation_result.completeness_score:.2%}"
            )
            
            return validation_result
            
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            self._handle_error(e, context="validation")
            return None
    
    def _show_welcome(self, output_fn):
        """Display welcome message"""
        output_fn("\n" + "="*60)
        output_fn("OPHTHALMOLOGY CONSULTATION SYSTEM")
        output_fn("="*60)
        output_fn(f"Consultation ID: {self.consultation_id}")
        output_fn("This system will ask you questions about your vision.")
        output_fn("Please answer as accurately as possible.")
        output_fn("="*60)
    
    def _show_closing(self, output_fn, completed, json_path, summary_path, validation):
        """
        Display closing message with results
        
        Args:
            output_fn (callable): Display function
            completed (bool): Whether consultation naturally completed
            json_path (str): Path to JSON file
            summary_path (str): Path to summary file
            validation (ValidationResult): Validation results
        """
        output_fn("\n" + "="*60)
        output_fn("CONSULTATION COMPLETE")
        output_fn("="*60)
        
        if completed:
            output_fn("✓ All applicable questions answered")
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
        """
        Check if user input is an exit command
        
        Args:
            text (str): User input
            
        Returns:
            bool: True if exit command
        """
        return text.strip().lower() in self.EXIT_COMMANDS
    
    def _handle_error(self, error, context=""):
        """
        Centralized error handling
        
        Logs error and tracks in internal error list.
        Does not raise - allows consultation to continue.
        
        Args:
            error (Exception): Error that occurred
            context (str): Context where error occurred
        """
        error_record = {
            'context': context,
            'error': str(error),
            'timestamp': datetime.now().isoformat()
        }
        
        self.errors.append(error_record)
        logger.error(f"Error in {context}: {error}")