"""
Dialogue Manager V2 - Multi-episode consultation orchestration (Functional Core)

Responsibilities:
- Coordinate question-answer loop across multiple episodes
- Route fields to episode-specific or shared storage
- Handle episode transitions with retry logic
- Generate final outputs (JSON + summary)
- Error handling and logging

Design principles:
- Ephemeral per turn (no consultation state held between turns)
- Functional core with serialized state in/out
- Thin orchestration layer (business logic in specialized modules)
- Trust Response Parser with retry logic for ambiguity
- Quarantine unmapped fields in dialogue metadata
"""

import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, Any

# Flat imports for server testing
# When copying to local, adjust to: from backend.utils.helpers import ...
from backend.utils.helpers import generate_consultation_id, generate_consultation_filename
from backend.utils.episode_classifier import classify_field

logger = logging.getLogger(__name__)


@dataclass
class TurnResult:
    """
    Result of processing a single turn
    
    Attributes:
        system_output: Text to show user (question or message)
        state_snapshot: Canonical consultation state (for persistence, lossless)
        clinical_output: Clinical projection (for JSON formatter, lossy)
        debug: Debug information (parser output, errors, etc.)
        turn_metadata: Turn-level metadata (episode_id, turn_count, etc.)
        consultation_complete: Whether consultation is finished
    """
    system_output: str
    state_snapshot: Dict[str, Any]  # Canonical, lossless
    clinical_output: Dict[str, Any]  # Clinical projection, lossy
    debug: Dict[str, Any]
    turn_metadata: Dict[str, Any]
    consultation_complete: bool


class DialogueManagerV2:
    """
    Orchestrates multi-episode ophthalmology consultation
    
    Functional core design:
    - Ephemeral per turn (configs cached, state external)
    - handle_turn() transforms state deterministically
    - No implicit state accumulation
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
    
    def __init__(self, state_manager_class, question_selector, response_parser,
                 json_formatter, summary_generator):
        """
        Initialize Dialogue Manager V2 with module references (NOT instances)
        
        Caches:
        - Module classes/constructors
        - Config file paths
        - Rulesets/schemas (loaded once)
        
        Does NOT cache:
        - Consultation state
        - Dialogue history
        - Current episode tracking
        
        Args:
            state_manager_class: StateManagerV2 class (not instance)
            question_selector: QuestionSelectorV2 instance (stateless, safe to cache)
            response_parser: ResponseParserV2 instance (stateless, safe to cache)
            json_formatter: JSONFormatterV2 instance (stateless, safe to cache)
            summary_generator: SummaryGeneratorV2 instance (stateless, safe to cache)
            
        Raises:
            TypeError: If any required module is missing or wrong type
        """
        # Validate module interfaces
        self._validate_modules(state_manager_class, question_selector, response_parser,
                               json_formatter, summary_generator)
        
        # Cache module references (configs only, no state)
        self.state_manager_class = state_manager_class
        self.selector = question_selector  # Stateless, safe to cache
        self.parser = response_parser      # Stateless, safe to cache
        self.json_formatter = json_formatter  # Stateless, safe to cache
        self.summary_generator = summary_generator  # Stateless, safe to cache
        
        logger.info("Dialogue Manager V2 initialized (functional core)")
    
    def _validate_modules(self, state_manager_class, question_selector, response_parser,
                         json_formatter, summary_generator):
        """Validate module interfaces"""
        # Validate QuestionSelectorV2 interface
        if not (hasattr(question_selector, 'get_next_question') and 
                callable(getattr(question_selector, 'get_next_question', None))):
            raise TypeError("question_selector must have callable get_next_question() method")
        
        if not (hasattr(question_selector, 'check_triggers') and 
                callable(getattr(question_selector, 'check_triggers', None))):
            raise TypeError("question_selector must have callable check_triggers() method")
        
        if not (hasattr(question_selector, 'is_block_complete') and 
                callable(getattr(question_selector, 'is_block_complete', None))):
            raise TypeError("question_selector must have callable is_block_complete() method")
        
        # Validate ResponseParser interface
        if not (hasattr(response_parser, 'parse') and 
                callable(getattr(response_parser, 'parse', None))):
            raise TypeError("response_parser must have callable parse() method")
        
        # Validate JSONFormatterV2 interface
        if not (hasattr(json_formatter, 'format_state') and 
                callable(getattr(json_formatter, 'format_state', None))):
            raise TypeError("json_formatter must have callable format_state() method")
        
        # Validate SummaryGeneratorV2 interface
        if not (hasattr(summary_generator, 'generate') and 
                callable(getattr(summary_generator, 'generate', None))):
            raise TypeError("summary_generator must have callable generate() method")
    
    def handle_turn(
        self,
        user_input: str,
        state_snapshot: Optional[Dict[str, Any]] = None
    ) -> TurnResult:
        """
        Process a single turn of conversation
        
        Functional core contract:
        - Input: user text + canonical state snapshot
        - Output: system response + updated canonical snapshot + clinical view
        - No side effects (logging excepted)
        
        Canonical state structure (lossless, for persistence):
        {
            'episodes': [...],  # All episodes, with operational fields
            'shared_data': {...},
            'dialogue_history': {episode_id: [turns]}
        }
        
        Args:
            user_input: Patient's response text
            state_snapshot: Canonical state (from snapshot_state(), or None for first turn)
            
        Returns:
            TurnResult with:
            - system_output: Question or message to display
            - state_snapshot: Updated canonical state (pass to next turn)
            - clinical_output: Clinical projection (for JSON formatter)
            - debug: Parser output and error info
            - turn_metadata: episode_id, turn_count, etc.
            - consultation_complete: Whether consultation is done
            
        Raises:
            ValueError: If state is malformed or turn_count invalid
        """
        # Initialize or restore state
        if state_snapshot is None:
            # First turn - initialize new consultation
            state_manager, turn_count, current_episode_id, consultation_id = self._initialize_new_consultation()
            expected_turn = 0
            awaiting_first_question = True
            awaiting_episode_transition = False
            pending_question = None
            errors = []
        else:
            # Restore from canonical snapshot
            state_manager = self.state_manager_class.from_snapshot(
                state_snapshot,
                data_model_path="data/clinical_data_model.json"
            )
            
            # Extract turn-level state (not stored in StateManager)
            turn_count = state_snapshot.get('turn_count', 0)
            current_episode_id = state_snapshot.get('current_episode_id')
            consultation_id = state_snapshot.get('consultation_id')
            awaiting_first_question = state_snapshot.get('awaiting_first_question', False)
            awaiting_episode_transition = state_snapshot.get('awaiting_episode_transition', False)
            pending_question = state_snapshot.get('pending_question')
            errors = state_snapshot.get('errors', [])
            
            if turn_count < 0:
                raise ValueError("state_snapshot missing or invalid turn_count")
            
            expected_turn = turn_count
        
        # Check for exit command
        if user_input.strip().lower() in self.EXIT_COMMANDS:
            return self._build_turn_result(
                system_output="Consultation ended by user",
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count,
                current_episode_id=current_episode_id,
                awaiting_first_question=awaiting_first_question,
                awaiting_episode_transition=awaiting_episode_transition,
                pending_question=pending_question,
                errors=errors,
                debug={'exit_command': True},
                consultation_complete=True
            )
        
        # Determine what we're processing
        if awaiting_first_question:
            # First turn after initialization - just return first question
            return self._get_first_question(
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count,
                current_episode_id=current_episode_id,
                errors=errors
            )
        
        elif awaiting_episode_transition:
            # Processing answer to episode transition question
            return self._process_episode_transition(
                user_input=user_input,
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count,
                current_episode_id=current_episode_id,
                pending_question=pending_question,
                errors=errors
            )
        
        else:
            # Processing answer to regular question
            return self._process_regular_turn(
                user_input=user_input,
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count,
                current_episode_id=current_episode_id,
                pending_question=pending_question,
                errors=errors
            )
    
    def _initialize_new_consultation(self):
        """
        Initialize new consultation (first turn only)
        
        Returns:
            tuple: (state_manager, turn_count, current_episode_id, consultation_id)
        """
        consultation_id = generate_consultation_id(short=True)
        
        # Create StateManager and first episode
        state_manager = self.state_manager_class("data/clinical_data_model.json")
        first_episode_id = state_manager.create_episode()
        
        # No JSON formatter call - just return the state manager
        # Empty episode is preserved in canonical state
        
        logger.info(f"Initialized consultation {consultation_id}")
        
        return state_manager, 0, first_episode_id, consultation_id
    
    def _build_turn_result(
        self,
        system_output: str,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        awaiting_first_question: bool,
        awaiting_episode_transition: bool,
        pending_question: Optional[Dict],
        errors: list,
        debug: Dict,
        consultation_complete: bool
    ) -> TurnResult:
        """
        Build TurnResult with both canonical snapshot and clinical projection
        
        This enforces the separation: canonical state for persistence,
        clinical view for output only.
        """
        # Get canonical snapshot (lossless, for persistence)
        canonical_snapshot = state_manager.snapshot_state()
        
        # Add turn-level metadata (not in StateManager)
        canonical_snapshot['consultation_id'] = consultation_id
        canonical_snapshot['turn_count'] = turn_count
        canonical_snapshot['current_episode_id'] = current_episode_id
        canonical_snapshot['awaiting_first_question'] = awaiting_first_question
        canonical_snapshot['awaiting_episode_transition'] = awaiting_episode_transition
        canonical_snapshot['pending_question'] = pending_question
        canonical_snapshot['errors'] = errors
        
        # Get clinical projection (lossy, for output)
        clinical_view = state_manager.export_clinical_view()
        
        return TurnResult(
            system_output=system_output,
            state_snapshot=canonical_snapshot,
            clinical_output=clinical_view,
            debug=debug,
            turn_metadata={
                'turn_count': turn_count,
                'current_episode_id': current_episode_id,
                'consultation_id': consultation_id
            },
            consultation_complete=consultation_complete
        )
    
    def _get_first_question(
        self,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        errors: list
    ) -> TurnResult:
        """
        Get first question for new consultation
        
        Args:
            state_manager: Rehydrated state manager
            consultation_id: Consultation ID
            turn_count: Current turn count
            current_episode_id: Current episode ID
            errors: List of errors from previous turns
            
        Returns:
            TurnResult with first question
        """
        episode_data = state_manager.get_episode_for_selector(current_episode_id)
        
        # Get first question
        question_dict = self.selector.get_next_question(episode_data)
        
        if question_dict is None:
            # Shouldn't happen on first turn, but handle gracefully
            logger.error("No questions available on first turn")
            return self._build_turn_result(
                system_output="Error: No questions configured",
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count,
                current_episode_id=current_episode_id,
                awaiting_first_question=False,
                awaiting_episode_transition=False,
                pending_question=None,
                errors=errors,
                debug={'error': 'no_questions'},
                consultation_complete=True
            )
        
        return self._build_turn_result(
            system_output=question_dict['question'],
            state_manager=state_manager,
            consultation_id=consultation_id,
            turn_count=turn_count + 1,
            current_episode_id=current_episode_id,
            awaiting_first_question=False,
            awaiting_episode_transition=False,
            pending_question=question_dict,
            errors=errors,
            debug={'first_question': True},
            consultation_complete=False
        )
    
    def _process_regular_turn(
        self,
        user_input: str,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        pending_question: Dict,
        errors: list
    ) -> TurnResult:
        """
        Process answer to regular question
        
        Args:
            user_input: Patient response
            state_manager: Rehydrated state manager
            consultation_id: Consultation ID
            turn_count: Current turn count
            current_episode_id: Current episode ID
            pending_question: Question being answered
            errors: List of errors from previous turns
            
        Returns:
            TurnResult with next question or episode transition
        """
        if pending_question is None:
            raise ValueError("No pending question in state")
        
        # Parse response
        try:
            parse_result = self.parser.parse(
                question=pending_question,
                patient_response=user_input,
                turn_id=f"turn_{turn_count + 1:03d}"
            )
            
            outcome = parse_result['outcome']
            fields = parse_result['fields']
            parse_metadata = parse_result['parse_metadata']
            
            logger.info(
                f"Parsed: id={pending_question['id']}, outcome={outcome}, "
                f"fields={len(fields)}"
            )
            
        except Exception as e:
            logger.error(f"Parser crashed: {e}")
            errors.append({
                'context': 'parse',
                'error': str(e),
                'question_id': pending_question['id']
            })
            
            # Create empty parse result
            outcome = 'generation_failed'
            fields = {}
            parse_metadata = {
                'expected_field': pending_question.get('field', 'unknown'),
                'question_id': pending_question['id'],
                'turn_id': f"turn_{turn_count + 1:03d}",
                'timestamp': datetime.now().isoformat(),
                'error_message': str(e),
                'error_type': type(e).__name__,
                'unexpected_fields': [],
                'validation_warnings': [],
                'normalization_applied': []
            }
            parse_result = {
                'outcome': outcome,
                'fields': fields,
                'parse_metadata': parse_metadata
            }
        
        # Route extracted fields
        unmapped = self._route_extracted_fields(
            episode_id=current_episode_id,
            extracted=fields,
            state_manager=state_manager
        )
        
        # Mark question answered
        state_manager.mark_question_answered(current_episode_id, pending_question['id'])
        
        # Check triggers and block completion
        self._check_and_activate_triggers(current_episode_id, state_manager)
        self._check_block_completion(current_episode_id, state_manager)
        
        # Record dialogue turn
        state_manager.add_dialogue_turn(
            episode_id=current_episode_id,
            question_id=pending_question['id'],
            question_text=pending_question['question'],
            patient_response=user_input,
            extracted_fields={
                **fields,
                '_unmapped': unmapped,
                '_parse_outcome': outcome,
                '_parse_metadata': parse_metadata
            }
        )
        
        # Get next question
        episode_data = state_manager.get_episode_for_selector(current_episode_id)
        next_question = self.selector.get_next_question(episode_data)
        
        if next_question is None:
            # Episode complete - ask about additional episodes
            return self._build_turn_result(
                system_output=self.TRANSITION_QUESTION['question'],
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count + 1,
                current_episode_id=current_episode_id,
                awaiting_first_question=False,
                awaiting_episode_transition=True,
                pending_question=self.TRANSITION_QUESTION,
                errors=errors,
                debug={
                    'parser_output': parse_result,
                    'episode_complete': True
                },
                consultation_complete=False
            )
        else:
            # Continue with next question
            return self._build_turn_result(
                system_output=next_question['question'],
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count + 1,
                current_episode_id=current_episode_id,
                awaiting_first_question=False,
                awaiting_episode_transition=False,
                pending_question=next_question,
                errors=errors,
                debug={'parser_output': parse_result},
                consultation_complete=False
            )
    
    def _process_episode_transition(
        self,
        user_input: str,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        pending_question: Dict,
        errors: list
    ) -> TurnResult:
        """
        Process answer to episode transition question
        
        Args:
            user_input: Patient response
            state_manager: Rehydrated state manager
            consultation_id: Consultation ID
            turn_count: Current turn count
            current_episode_id: Current episode ID
            pending_question: Episode transition question
            errors: List of errors from previous turns
            
        Returns:
            TurnResult with new episode question or finalization
        """
        # Parse transition response
        try:
            parse_result = self.parser.parse(
                question=self.TRANSITION_QUESTION,
                patient_response=user_input,
                turn_id=f"turn_{turn_count + 1:03d}"
            )
            
            outcome = parse_result['outcome']
            fields = parse_result['fields']
            
        except Exception as e:
            logger.error(f"Transition parse failed: {e}")
            outcome = 'unclear'
            fields = {}
            parse_result = {
                'outcome': outcome,
                'fields': fields,
                'parse_metadata': {}
            }
        
        # Check if we got a clear answer
        field = self.TRANSITION_QUESTION['field']
        
        if outcome in ['success', 'partial_success'] and field in fields:
            additional_episodes = fields[field]
            
            if additional_episodes:
                # Create new episode
                new_episode_id = state_manager.create_episode()
                
                # Get first question for new episode
                episode_data = state_manager.get_episode_for_selector(new_episode_id)
                first_question = self.selector.get_next_question(episode_data)
                
                return self._build_turn_result(
                    system_output=f"Episode {new_episode_id} - {first_question['question']}",
                    state_manager=state_manager,
                    consultation_id=consultation_id,
                    turn_count=turn_count + 1,
                    current_episode_id=new_episode_id,
                    awaiting_first_question=False,
                    awaiting_episode_transition=False,
                    pending_question=first_question,
                    errors=errors,
                    debug={
                        'parser_output': parse_result,
                        'new_episode': new_episode_id
                    },
                    consultation_complete=False
                )
            else:
                # No more episodes - consultation complete
                return self._build_turn_result(
                    system_output="Consultation complete. Generating outputs...",
                    state_manager=state_manager,
                    consultation_id=consultation_id,
                    turn_count=turn_count + 1,
                    current_episode_id=current_episode_id,
                    awaiting_first_question=False,
                    awaiting_episode_transition=False,
                    pending_question=None,
                    errors=errors,
                    debug={
                        'parser_output': parse_result,
                        'no_more_episodes': True
                    },
                    consultation_complete=True
                )
        
        else:
            # Unclear response - retry (simplified for now)
            return self._build_turn_result(
                system_output="I didn't quite catch that. Please answer yes or no: " + 
                             self.TRANSITION_QUESTION['question'],
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count + 1,
                current_episode_id=current_episode_id,
                awaiting_first_question=False,
                awaiting_episode_transition=True,
                pending_question=self.TRANSITION_QUESTION,
                errors=errors,
                debug={
                    'parser_output': parse_result,
                    'unclear_transition': True
                },
                consultation_complete=False
            )
    
    def _route_extracted_fields(
        self,
        episode_id: int,
        extracted: Dict[str, Any],
        state_manager
    ) -> Dict[str, Any]:
        """Route extracted fields to episode or shared storage"""
        unmapped = {}
        
        for field_name, value in extracted.items():
            if field_name.startswith('_'):
                continue
            
            classification = classify_field(field_name)
            
            if classification == 'episode':
                try:
                    state_manager.set_episode_field(episode_id, field_name, value)
                    logger.debug(f"Episode {episode_id}: {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to set episode field {field_name}: {e}")
                    
            elif classification == 'shared':
                try:
                    state_manager.set_shared_field(field_name, value)
                    logger.debug(f"Shared data: {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to set shared field {field_name}: {e}")
                    
            else:
                unmapped[field_name] = value
                logger.warning(f"Unmapped field: {field_name} = {value}")
        
        return unmapped
    
    def _check_and_activate_triggers(self, episode_id: int, state_manager):
        """Check for triggered follow-up blocks"""
        try:
            episode_data = state_manager.get_episode_for_selector(episode_id)
            triggered_blocks = self.selector.check_triggers(episode_data)
            already_activated = episode_data.get('follow_up_blocks_activated', set())
            
            new_blocks = triggered_blocks - already_activated
            for block_id in new_blocks:
                state_manager.activate_follow_up_block(episode_id, block_id)
                logger.info(f"Episode {episode_id}: Activated block '{block_id}'")
                
        except Exception as e:
            logger.error(f"Trigger check failed: {e}")
    
    def _check_block_completion(self, episode_id: int, state_manager):
        """Check if any blocks are now complete"""
        try:
            episode_data = state_manager.get_episode_for_selector(episode_id)
            activated = episode_data.get('follow_up_blocks_activated', set())
            completed = episode_data.get('follow_up_blocks_completed', set())
            pending = activated - completed
            
            for block_id in pending:
                if self.selector.is_block_complete(block_id, episode_data):
                    state_manager.complete_follow_up_block(episode_id, block_id)
                    logger.info(f"Episode {episode_id}: Completed block '{block_id}'")
                    
        except Exception as e:
            logger.error(f"Block completion check failed: {e}")
    
    def generate_outputs(
        self,
        state_snapshot: Dict[str, Any],
        output_dir: str = "outputs/consultations"
    ) -> Dict[str, Any]:
        """
        Generate final JSON and summary outputs
        
        Args:
            state_snapshot: Final canonical consultation state snapshot
            output_dir: Directory for output files
            
        Returns:
            dict: Paths to generated files and metadata
        """
        import os
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
        
        consultation_id = state_snapshot['consultation_id']
        
        # Rehydrate state manager from canonical snapshot
        state_manager = self.state_manager_class.from_snapshot(
            state_snapshot,
            data_model_path="data/clinical_data_model.json"
        )
        
        # Generate clinical view for JSON output
        clinical_view = state_manager.export_clinical_view()
        
        # Format and save JSON
        json_data = self.json_formatter.format_state(
            state_data=clinical_view,
            consultation_id=consultation_id
        )
        
        json_filename = generate_consultation_filename(
            prefix="consultation",
            extension="json"
        )
        json_path = os.path.join(output_dir, json_filename)
        
        from json_formatter_v2 import JSONFormatterV2
        JSONFormatterV2.save_to_file(json_data, json_path)
        
        # Generate summary
        summary_data = state_manager.export_for_summary()
        
        summary_text = self.summary_generator.generate(
            consultation_data=summary_data,
            temperature=0.1
        )
        
        summary_filename = generate_consultation_filename(
            prefix="summary",
            extension="txt"
        )
        summary_path = os.path.join(output_dir, summary_filename)
        
        self.summary_generator.save_summary(summary_text, summary_path)
        
        logger.info(f"Outputs generated: {json_filename}, {summary_filename}")
        
        return {
            'json_path': json_path,
            'summary_path': summary_path,
            'json_filename': json_filename,
            'summary_filename': summary_filename,
            'consultation_id': consultation_id,
            'total_episodes': len(state_manager.episodes)
        }