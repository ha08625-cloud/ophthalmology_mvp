"""
Dialogue Manager V2 - Multi-episode consultation orchestration

Responsibilities:
- Coordinate question-answer loop across multiple episodes
- Delegate field routing to State Manager
- Handle episode transitions with retry logic
- Generate final outputs (JSON + summary)
- Error handling and logging (typed, severity-aware)

Design principles:
- Thin orchestration layer (NO clinical authority)
- Track current_episode_id as internal UI state (cursor, not truth)
- Centralized outcome policy (no ad-hoc conditionals)
- Typed errors with severity (fatal vs non-fatal)
- Fail hard on protocol corruption
- Clear completion semantics (conversation vs outputs vs protocol)
"""

import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

# Flat imports for V2 consistency
# When copying to local, adjust to: from backend.utils.helpers import ...
from backend.utils.helpers import generate_consultation_id, generate_consultation_filename

logger = logging.getLogger(__name__)


# Error types for typed error handling
ERROR_TYPE_STATE_CORRUPTION = "STATE_CORRUPTION"
ERROR_TYPE_IO_FAILURE = "IO_FAILURE"
ERROR_TYPE_PARSER_FAILURE = "PARSER_FAILURE"
ERROR_TYPE_PROTOCOL_VIOLATION = "PROTOCOL_VIOLATION"

# Error severities
SEVERITY_FATAL = "fatal"
SEVERITY_NON_FATAL = "non_fatal"


class DialogueManagerV2:
    """
    Orchestrates multi-episode ophthalmology consultation
    
    Thin coordinator - delegates work to specialized modules.
    NO clinical authority - executes policy only.
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
    
    # Parser outcome handling policy (centralized)
    # Maps outcome -> action class (no ad-hoc conditionals)
    OUTCOME_POLICY = {
        'success': 'ACCEPT',
        'partial_success': 'ACCEPT_WITH_WARNING',
        'unclear': 'REASK_ONCE',
        'extraction_failed': 'REASK_ONCE',
        'generation_failed': 'RETRY_OR_ABORT'
    }
    
    def __init__(self, state_manager, question_selector, response_parser,
                 json_formatter, summary_generator):
        """
        Initialize Dialogue Manager V2 with all required modules
        
        Args:
            state_manager (StateManagerV2): Multi-episode state tracker
            question_selector (QuestionSelectorV2): Selects next question
            response_parser (ResponseParser): Extracts data from responses
            json_formatter (JSONFormatterV2): Generates JSON output
            summary_generator (SummaryGeneratorV2): Generates clinical summary
            
        Raises:
            TypeError: If any required module is missing or wrong type
        """
        # Validate module interfaces
        self._validate_callable(state_manager, 'create_episode', 'state_manager')
        self._validate_callable(state_manager, 'set_episode_field', 'state_manager')
        self._validate_callable(state_manager, 'get_episode_for_selector', 'state_manager')
        self._validate_callable(state_manager, 'mark_question_answered', 'state_manager')
        self._validate_callable(state_manager, 'route_and_store_fields', 'state_manager')
        
        self._validate_callable(question_selector, 'get_next_question', 'question_selector')
        self._validate_callable(question_selector, 'check_triggers', 'question_selector')
        self._validate_callable(question_selector, 'is_block_complete', 'question_selector')
        
        self._validate_callable(response_parser, 'parse', 'response_parser')
        
        self._validate_callable(json_formatter, 'format_and_save', 'json_formatter')
        
        self._validate_callable(summary_generator, 'generate_and_save', 'summary_generator')
        
        # Store module references
        self.state = state_manager
        self.selector = question_selector
        self.parser = response_parser
        self.json_formatter = json_formatter
        self.summary_generator = summary_generator
        
        # Initialize internal state
        self.current_episode_id = None  # Tracks active episode (UI cursor, not truth)
        self.errors: List[Dict[str, Any]] = []  # Typed error records
        self.consultation_id = generate_consultation_id(short=True)
        self.protocol_compromised = False  # Flag if trigger evaluation fails
        
        logger.info(f"Dialogue Manager V2 initialized (consultation_id={self.consultation_id})")
    
    def _validate_callable(self, obj, method_name: str, obj_name: str) -> None:
        """Helper to validate module interfaces"""
        if not (hasattr(obj, method_name) and callable(getattr(obj, method_name, None))):
            raise TypeError(f"{obj_name} must have callable {method_name}() method")
    
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
            dict: Consultation results with split completion semantics:
                - conversation_completed (bool): Natural conversation completion
                - conversation_aborted (bool): User quit early or protocol failed
                - abort_reason (str|None): 'user_exit' | 'protocol_corruption' | None
                - outputs_generated (bool): JSON+summary successfully created
                - output_failure_reason (str|None): Why outputs failed
                - protocol_compromised (bool): Trigger evaluation failed
                - consultation_id (str): Unique ID
                - total_episodes (int): Number of episodes
                - total_questions (int): Number of questions asked
                - json_path (str|None): Path to JSON file
                - summary_path (str|None): Path to summary file
                - errors (list): Typed error records
        """
        conversation_completed = False
        conversation_aborted = False
        abort_reason = None
        outputs_generated = False
        output_failure_reason = None
        total_questions = 0
        total_episodes = 0
        json_path = None
        summary_path = None
        
        try:
            # Ensure output directory exists
            os.makedirs(output_dir, exist_ok=True)
            
            # Welcome message
            self._show_welcome(output_fn)
            
            # Main conversation loop (multi-episode)
            conv_result = self._conversation_loop_v2(input_fn, output_fn)
            conversation_completed = conv_result['completed']
            conversation_aborted = conv_result['aborted']
            abort_reason = conv_result['abort_reason']
            total_questions = conv_result['total_questions']
            total_episodes = conv_result['total_episodes']
            
            # If protocol compromised during conversation, don't generate outputs
            if self.protocol_compromised:
                output_fn("\n" + "="*60)
                output_fn("WARNING: Protocol was compromised during consultation")
                output_fn("Outputs may be incomplete or inconsistent")
                output_fn("="*60)
                outputs_generated = False
                output_failure_reason = "protocol_compromised"
            else:
                # Generate outputs
                output_fn("\n" + "="*60)
                output_fn("GENERATING CONSULTATION OUTPUTS")
                output_fn("="*60)
                
                # Try to generate JSON and summary
                try:
                    json_path = self._generate_json_output(output_dir, output_fn)
                    summary_path = self._generate_summary_output(output_dir, output_fn)
                    outputs_generated = True
                except Exception as e:
                    logger.error(f"Output generation failed: {e}")
                    outputs_generated = False
                    output_failure_reason = str(e)
            
            # Show closing message
            self._show_closing(
                output_fn, 
                conversation_completed,
                conversation_aborted,
                total_episodes,
                json_path,
                summary_path
            )
            
            # Build result dict with split semantics
            result = {
                'conversation_completed': conversation_completed,
                'conversation_aborted': conversation_aborted,
                'abort_reason': abort_reason,
                'outputs_generated': outputs_generated,
                'output_failure_reason': output_failure_reason,
                'protocol_compromised': self.protocol_compromised,
                'consultation_id': self.consultation_id,
                'total_episodes': total_episodes,
                'total_questions': total_questions,
                'json_path': json_path,
                'summary_path': summary_path,
                'errors': self.errors
            }
            
            # Call finish callback if provided
            if on_finish:
                on_finish(result)
            
            logger.info(f"Consultation {self.consultation_id} finished")
            
            return result
            
        except Exception as e:
            logger.error(f"Consultation failed: {e}")
            self._handle_error(
                error=e,
                context="run_consultation",
                error_type=ERROR_TYPE_IO_FAILURE,
                severity=SEVERITY_FATAL
            )
            raise
    
    def _generate_json_output(self, output_dir: str, output_fn) -> Optional[str]:
        """
        Generate JSON output file using JSONFormatterV2
        
        Args:
            output_dir (str): Directory for output files
            output_fn (callable): Display function
            
        Returns:
            str: Path to saved JSON file or None if failed
            
        Raises:
            Exception: If JSON generation fails (caller handles)
        """
        # Get state data for JSON formatter
        state_data = self.state.export_for_json()
        
        # Generate filename
        json_filename = generate_consultation_filename(
            prefix="consultation", 
            extension="json"
        )
        json_path = os.path.join(output_dir, json_filename)
        
        # Delegate formatting AND saving to formatter
        self.json_formatter.format_and_save(
            state_data=state_data,
            consultation_id=self.consultation_id,
            output_path=json_path
        )
        
        output_fn(f"JSON output saved: {json_filename}")
        logger.info(f"JSON saved to {json_path}")
        
        return json_path
    
    def _generate_summary_output(self, output_dir: str, output_fn) -> Optional[str]:
        """
        Generate summary output file using SummaryGeneratorV2
        
        Args:
            output_dir (str): Directory for output files
            output_fn (callable): Display function
            
        Returns:
            str: Path to saved summary file or None if failed
            
        Raises:
            Exception: If summary generation fails (caller handles)
        """
        # Get state data for summary generator
        summary_data = self.state.export_for_summary()
        
        # Generate filename
        summary_filename = generate_consultation_filename(
            prefix="summary", 
            extension="txt"
        )
        summary_path = os.path.join(output_dir, summary_filename)
        
        # Delegate generation AND saving to summary generator
        self.summary_generator.generate_and_save(
            consultation_data=summary_data,
            output_path=summary_path,
            temperature=0.1
        )
        
        output_fn(f"Summary output saved: {summary_filename}")
        logger.info(f"Summary saved to {summary_path}")
        
        return summary_path
    
    def _conversation_loop_v2(self, input_fn, output_fn) -> Dict[str, Any]:
        """
        Main question-answer loop with multi-episode support
        
        Args:
            input_fn (callable): Get user input
            output_fn (callable): Display output
            
        Returns:
            dict: {
                'completed': bool,  # Natural completion
                'aborted': bool,    # User quit or protocol failed
                'abort_reason': str|None,  # Why aborted
                'total_questions': int,
                'total_episodes': int
            }
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
            # Check protocol status before continuing
            if self.protocol_compromised:
                output_fn("\nProtocol corruption detected - aborting consultation")
                return {
                    'completed': False,
                    'aborted': True,
                    'abort_reason': 'protocol_corruption',
                    'total_questions': total_questions,
                    'total_episodes': total_episodes
                }
            
            # Ask all questions for current episode
            episode_result = self._ask_episode_questions(
                input_fn, output_fn, total_questions
            )
            
            total_questions += episode_result['questions_asked']
            
            # Check for early exit
            if episode_result['aborted']:
                output_fn("\nConsultation ended early by user")
                logger.info("User requested early exit")
                return {
                    'completed': False,
                    'aborted': True,
                    'abort_reason': 'user_exit',
                    'total_questions': total_questions,
                    'total_episodes': total_episodes
                }
            
            # Episode complete - ask about additional episodes
            transition_result = self._ask_episode_transition_question(
                input_fn, output_fn
            )
            
            if transition_result == 'CREATE_NEW_EPISODE':
                # Create next episode
                self.current_episode_id = self.state.create_episode()
                total_episodes += 1
                logger.info(f"Created Episode {self.current_episode_id}")
                output_fn(f"\n{'='*60}")
                output_fn(f"STARTING EPISODE {self.current_episode_id}")
                output_fn(f"{'='*60}\n")
                
            elif transition_result == 'NO_MORE_EPISODES':
                # No more episodes - consultation complete
                output_fn("\nConsultation complete - all episodes documented")
                logger.info("All episodes complete")
                return {
                    'completed': True,
                    'aborted': False,
                    'abort_reason': None,
                    'total_questions': total_questions,
                    'total_episodes': total_episodes
                }
                
            elif transition_result == 'USER_EXIT':
                # User quit during transition
                output_fn("\nConsultation ended by user")
                return {
                    'completed': False,
                    'aborted': True,
                    'abort_reason': 'user_exit',
                    'total_questions': total_questions,
                    'total_episodes': total_episodes
                }
                
            else:  # UNRESOLVED
                # Could not determine - treat as complete but ambiguous
                output_fn("\nCould not determine if more episodes - proceeding to finalize")
                logger.warning("Episode transition unresolved - assuming complete")
                return {
                    'completed': True,
                    'aborted': False,
                    'abort_reason': None,
                    'total_questions': total_questions,
                    'total_episodes': total_episodes
                }
    
    def _create_first_episode(self) -> int:
        """
        Create Episode 1 at start of consultation
        
        Returns:
            int: Episode ID (always 1 for first episode)
        """
        episode_id = self.state.create_episode()
        logger.info(f"Created Episode {episode_id}")
        
        # Validate it was actually created
        if episode_id != 1:
            logger.warning(f"Expected episode_id=1, got {episode_id}")
        
        return episode_id
    
    def _validate_current_episode(self) -> None:
        """Validate current_episode_id against State Manager truth"""
        if self.current_episode_id is None:
            raise RuntimeError("current_episode_id is None - invalid state")
        
        valid_ids = self.state.list_episode_ids()
        if self.current_episode_id not in valid_ids:
            raise RuntimeError(
                f"current_episode_id={self.current_episode_id} not in "
                f"State Manager episodes: {valid_ids}"
            )
    
    def _ask_episode_questions(self, input_fn, output_fn, question_offset: int) -> Dict[str, Any]:
        """
        Ask all questions for current episode
        
        Args:
            input_fn: Get user input
            output_fn: Display output
            question_offset: Starting question number (for display)
            
        Returns:
            dict: {
                'aborted': bool,  # True if early exit
                'questions_asked': int
            }
        """
        self._validate_current_episode()
        questions_asked = 0
        
        while True:
            # Get episode data for Question Selector
            episode_data = self.state.get_episode_for_selector(self.current_episode_id)
            
            # Get next question for current episode
            question_dict = self.selector.get_next_question(episode_data)
            
            # Check if episode complete (no more questions)
            if question_dict is None:
                logger.info(f"Episode {self.current_episode_id} complete - no more questions")
                return {'aborted': False, 'questions_asked': questions_asked}
            
            # Display question
            question_text = question_dict.get('question', '[No question text]')
            question_id = question_dict.get('id', 'unknown')
            field = question_dict.get('field', 'unknown')
            
            question_number = question_offset + questions_asked + 1
            output_fn(f"\nQ{question_number}: {question_text}")
            logger.info(f"Episode {self.current_episode_id} - Asked: id={question_id}, field={field}")
            
            # Get patient response with retry logic
            retry_count = 0
            while retry_count <= 1:  # Max 1 retry
                # Get response
                try:
                    response = input_fn("> ").strip()
                except (EOFError, KeyboardInterrupt):
                    output_fn("\n\nConsultation interrupted by user")
                    return {'aborted': True, 'questions_asked': questions_asked}
                
                # Check for exit command
                if self._is_exit_command(response):
                    return {'aborted': True, 'questions_asked': questions_asked}
                
                # Parse response (ResponseParser V2 contract)
                try:
                    parse_result = self.parser.parse(
                        question=question_dict,
                        patient_response=response,
                        turn_id=f"turn_{question_number:02d}"
                    )
                    
                    outcome = parse_result['outcome']
                    fields = parse_result['fields']
                    parse_metadata = parse_result['parse_metadata']
                    
                    logger.info(
                        f"Parsed response: id={question_id}, outcome={outcome}, "
                        f"fields={len(fields)}, expected={parse_metadata['expected_field']}"
                    )
                    
                except Exception as e:
                    # Parser itself crashed (shouldn't happen but be defensive)
                    logger.error(f"Parser crashed for {question_id}: {e}")
                    self._handle_error(
                        error=e,
                        context=f"parse_{question_id}",
                        error_type=ERROR_TYPE_PARSER_FAILURE,
                        severity=SEVERITY_NON_FATAL
                    )
                    
                    # Create empty parse result
                    outcome = 'generation_failed'
                    fields = {}
                    parse_metadata = {
                        'expected_field': question_dict.get('field', 'unknown'),
                        'question_id': question_id,
                        'turn_id': f"turn_{question_number:02d}",
                        'timestamp': datetime.now().isoformat(),
                        'error_message': str(e),
                        'error_type': type(e).__name__,
                        'unexpected_fields': [],
                        'validation_warnings': [],
                        'normalization_applied': []
                    }
                
                # Decide action based on outcome policy
                action = self._handle_parse_outcome(outcome, retry_count)
                
                if action == 'ACCEPT':
                    # Accept the response and proceed
                    break
                elif action == 'REASK':
                    # Retry once
                    retry_count += 1
                    output_fn("I didn't quite understand. Could you please rephrase?")
                    logger.debug(f"Re-asking {question_id}, retry {retry_count}")
                    continue
                elif action == 'ABORT':
                    # Generation failed twice - abort consultation
                    output_fn("\nSystem error - unable to continue consultation")
                    logger.error(f"Aborting after repeated generation failures")
                    self._handle_error(
                        error=Exception("Repeated generation failures"),
                        context="ask_episode_questions",
                        error_type=ERROR_TYPE_PARSER_FAILURE,
                        severity=SEVERITY_FATAL
                    )
                    return {'aborted': True, 'questions_asked': questions_asked}
            
            # Route extracted fields to storage (delegate to State Manager)
            unmapped = self.state.route_and_store_fields(
                episode_id=self.current_episode_id,
                extracted_fields=fields
            )
            
            # Log validation warnings if present
            if parse_metadata.get('validation_warnings'):
                for warning in parse_metadata['validation_warnings']:
                    logger.warning(
                        f"Validation warning: field={warning.get('field')}, "
                        f"issue={warning.get('issue')}"
                    )
            
            # Log unexpected fields if present
            if parse_metadata.get('unexpected_fields'):
                logger.info(
                    f"Unexpected fields extracted: "
                    f"{parse_metadata['unexpected_fields']}"
                )
            
            # Mark question as answered (critical for Question Selector!)
            self.state.mark_question_answered(self.current_episode_id, question_id)
            
            # Check for triggered follow-up blocks (FATAL if fails)
            try:
                self._check_and_activate_triggers()
            except Exception as e:
                # Trigger failure = protocol corruption (FATAL)
                logger.error(f"FATAL: Trigger check failed: {e}")
                self.protocol_compromised = True
                return {'aborted': True, 'questions_asked': questions_asked}
            
            # Check for completed follow-up blocks
            self._check_block_completion()
            
            # Add dialogue turn with parse metadata
            try:
                self.state.add_dialogue_turn(
                    episode_id=self.current_episode_id,
                    question_id=question_id,
                    question_text=question_text,
                    patient_response=response,
                    extracted_fields={
                        **fields,
                        '_unmapped': unmapped,
                        '_parse_outcome': outcome,
                        '_parse_metadata': parse_metadata
                    }
                )
            except Exception as e:
                logger.error(f"Dialogue turn recording error: {e}")
                self._handle_error(
                    error=e,
                    context=f"dialogue_turn_{question_id}",
                    error_type=ERROR_TYPE_STATE_CORRUPTION,
                    severity=SEVERITY_NON_FATAL
                )
            
            questions_asked += 1
    
    def _handle_parse_outcome(self, outcome: str, retry_count: int) -> str:
        """
        Decide action based on parser outcome (centralized policy)
        
        Args:
            outcome: Parser outcome string
            retry_count: How many times we've retried (0 = first attempt)
            
        Returns:
            str: 'ACCEPT' | 'REASK' | 'ABORT'
        """
        policy = self.OUTCOME_POLICY.get(outcome, 'ACCEPT')
        
        if policy == 'ACCEPT':
            return 'ACCEPT'
            
        elif policy == 'ACCEPT_WITH_WARNING':
            logger.warning(f"Parser returned partial_success (outcome={outcome})")
            return 'ACCEPT'
            
        elif policy == 'REASK_ONCE':
            if retry_count == 0:
                return 'REASK'
            else:
                logger.warning(
                    f"Max retries reached for outcome={outcome}, "
                    f"accepting anyway"
                )
                return 'ACCEPT'
                
        elif policy == 'RETRY_OR_ABORT':
            if retry_count == 0:
                logger.warning(f"Generation failed, retrying once")
                return 'REASK'
            else:
                logger.error(f"Generation failed twice, aborting")
                return 'ABORT'
        
        # Unknown policy - default to accept
        logger.warning(f"Unknown outcome policy '{policy}' for outcome '{outcome}'")
        return 'ACCEPT'
    
    def _check_and_activate_triggers(self) -> None:
        """
        Check for triggered follow-up blocks and activate them
        
        Called after each question to detect when trigger conditions are met.
        
        Raises:
            Exception: If trigger evaluation fails (FATAL - protocol corruption)
        """
        self._validate_current_episode()
        
        # Get current episode data
        episode_data = self.state.get_episode_for_selector(self.current_episode_id)
        
        # Check which blocks should be triggered
        triggered_blocks = self.selector.check_triggers(episode_data)
        
        # Get already activated blocks
        already_activated = episode_data.get('follow_up_blocks_activated', set())
        
        # Activate new blocks
        new_blocks = triggered_blocks - already_activated
        for block_id in new_blocks:
            self.state.activate_follow_up_block(self.current_episode_id, block_id)
            logger.info(f"Episode {self.current_episode_id}: Activated follow-up block '{block_id}'")
    
    def _check_block_completion(self) -> None:
        """
        Check if any activated follow-up blocks are now complete
        
        Called after each question to mark blocks as complete when all
        their questions have been answered.
        """
        self._validate_current_episode()
        
        try:
            # Get current episode data
            episode_data = self.state.get_episode_for_selector(self.current_episode_id)
            
            # Get activated but not completed blocks
            activated = episode_data.get('follow_up_blocks_activated', set())
            completed = episode_data.get('follow_up_blocks_completed', set())
            pending = activated - completed
            
            # Check each pending block
            for block_id in pending:
                if self.selector.is_block_complete(block_id, episode_data):
                    self.state.complete_follow_up_block(self.current_episode_id, block_id)
                    logger.info(f"Episode {self.current_episode_id}: Completed follow-up block '{block_id}'")
                    
        except Exception as e:
            logger.error(f"Block completion check failed: {e}")
            self._handle_error(
                error=e,
                context="check_block_completion",
                error_type=ERROR_TYPE_PROTOCOL_VIOLATION,
                severity=SEVERITY_NON_FATAL
            )
    
    def _ask_episode_transition_question(self, input_fn, output_fn) -> str:
        """
        Ask "Any other episodes?" with retry logic
        
        NO assumptions - returns explicit semantic result.
        
        Args:
            input_fn: Get user input
            output_fn: Display output
            
        Returns:
            str: 'CREATE_NEW_EPISODE' | 'NO_MORE_EPISODES' | 'USER_EXIT' | 'UNRESOLVED'
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
                return 'USER_EXIT'
            
            # Check for exit command
            if self._is_exit_command(response):
                logger.info("User requested exit during episode transition")
                return 'USER_EXIT'
            
            # Parse response
            try:
                parse_result = self.parser.parse(
                    question=self.TRANSITION_QUESTION,
                    patient_response=response
                )
                
                outcome = parse_result['outcome']
                fields = parse_result['fields']
                
            except Exception as e:
                logger.error(f"Parser crashed on episode transition: {e}")
                self._handle_error(e, context="episode_transition_parse")
                
                # Treat crash as unclear - retry
                outcome = 'unclear'
                fields = {}
            
            # Check if we got a clear answer
            field = self.TRANSITION_QUESTION['field']
            
            if outcome in ['success', 'partial_success'] and field in fields:
                # Parser extracted the field successfully
                additional_episodes = fields[field]
                
                if additional_episodes:
                    logger.info("Episode transition: User confirmed additional episode")
                    return 'CREATE_NEW_EPISODE'
                else:
                    logger.info("Episode transition: User declined additional episode")
                    return 'NO_MORE_EPISODES'
            
            # Parser unclear or extraction failed - retry
            logger.debug(f"Episode transition unclear (outcome={outcome}), retry {retry_count}/{self.MAX_TRANSITION_RETRIES}")
            retry_count += 1
            
            # Parser unclear or extraction failed - retry
            retry_count += 1
            
            if retry_count < self.MAX_TRANSITION_RETRIES:
                output_fn("I didn't quite catch that. Please answer yes or no.")
                logger.debug(f"Episode transition unclear (outcome={outcome}), retry {retry_count}/{self.MAX_TRANSITION_RETRIES}")
        
        # Max retries reached - return UNRESOLVED (no assumption)
        output_fn("I couldn't determine your answer. Proceeding to finalize consultation.")
        logger.warning("Episode transition: Max retries reached, returning UNRESOLVED")
        return 'UNRESOLVED'
    
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
    
    def _show_closing(self, output_fn, conversation_completed: bool, 
                     conversation_aborted: bool, total_episodes: int,
                     json_path: Optional[str], summary_path: Optional[str]) -> None:
        """
        Display closing message with results
        
        Args:
            output_fn (callable): Display function
            conversation_completed (bool): Natural conversation completion
            conversation_aborted (bool): User quit or protocol failed
            total_episodes (int): Number of episodes
            json_path (str|None): Path to JSON file
            summary_path (str|None): Path to summary file
        """
        output_fn("\n" + "="*60)
        output_fn("CONSULTATION COMPLETE")
        output_fn("="*60)
        
        if conversation_completed and not conversation_aborted:
            output_fn(f"Documented {total_episodes} episode(s)")
        elif conversation_aborted:
            output_fn("Consultation ended early")
        else:
            output_fn(f"Documented {total_episodes} episode(s) (ambiguous completion)")
        
        if json_path or summary_path:
            output_fn(f"\nOutput files:")
            if json_path:
                output_fn(f"  - JSON: {json_path}")
            if summary_path:
                output_fn(f"  - Summary: {summary_path}")
        
        if self.errors:
            output_fn(f"\nWarning: {len(self.errors)} errors occurred during consultation")
            output_fn("  (See logs for details)")
        
        if self.protocol_compromised:
            output_fn("\nWARNING: Protocol was compromised - outputs may be incomplete")
        
        output_fn("\nThank you for using the consultation system.")
        output_fn("="*60)
    
    def _is_exit_command(self, text: str) -> bool:
        """Check if user input is an exit command"""
        return text.strip().lower() in self.EXIT_COMMANDS
    
    def _handle_error(self, error: Exception, context: str, 
                     error_type: str, severity: str) -> None:
        """
        Centralized typed error handling
        
        Logs error and tracks in internal error list.
        Only reacts to FATAL severity - others logged and passed through.
        
        Args:
            error: Exception that occurred
            context: Where error occurred
            error_type: Type constant (STATE_CORRUPTION, IO_FAILURE, etc.)
            severity: Severity constant (fatal, non_fatal)
        """
        error_record = {
            'type': error_type,
            'severity': severity,
            'source': 'dialogue_manager',
            'context': context,
            'error': str(error),
            'timestamp': datetime.now().isoformat()
        }
        
        self.errors.append(error_record)
        logger.error(f"Error in {context}: {error} (type={error_type}, severity={severity})")
        
        # DialogueManager only reacts to FATAL errors
        if severity == SEVERITY_FATAL:
            if error_type == ERROR_TYPE_STATE_CORRUPTION:
                self.protocol_compromised = True
                logger.critical("FATAL: State corruption detected - protocol compromised")
            elif error_type == ERROR_TYPE_IO_FAILURE:
                logger.critical("FATAL: IO failure - cannot continue")
                # Caller should re-raise