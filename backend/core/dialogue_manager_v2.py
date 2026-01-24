"""
Orchestrator module:

Coordinates question selection, response parsing, and state persistence
across episode transitions. Delegates business logic to specialized modules.

"""

import logging
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List

from backend.contracts import QuestionOutput

from backend.utils.helpers import generate_consultation_id, generate_consultation_filename
from backend.utils.episode_classifier import classify_field
from backend.utils.conversation_modes import ConversationMode
from backend.core.episode_hypothesis_generator import EpisodeHypothesisGenerator
from backend.utils.episode_safety_status import assess_episode_safety, EpisodeSafetyStatus
from backend.utils.episode_narrowing_prompt import build_episode_narrowing_prompt
from backend.utils.display_helpers import format_state_for_display
from backend.utils.prompt_builder import (
    PromptBuilder, 
    create_prompt_spec_from_question_output, 
    PromptMode, 
    PromptBuildError
)

from backend.commands import (
    ConsultationState,
    StartConsultation,
    UserTurn,
    FinalizeConsultation,
    Command
)
from backend.results import TurnResult, FinalReport, IllegalCommand

logger = logging.getLogger(__name__)


class DialogueManagerV2:
    """
    Only public method: handle(command)

    """
    
    EXIT_COMMANDS = {"quit", "exit", "stop"}
    MAX_TRANSITION_RETRIES = 2
    
    # TRANSITION_QUESTION stored as dict not QuestionOutput
    TRANSITION_QUESTION = {
        'id': 'episode_transition',
        'question': 'Have you had any other episodes of eye-related problems you would like to discuss?',
        'field': 'additional_episodes_present',
        'field_type': 'boolean',
        'field_label': 'additional episodes present',
        'field_description': 'whether patient has additional distinct episodes to discuss',
        'type': 'probe'
    }
    
    @staticmethod
    def _question_output_to_dict(question: QuestionOutput) -> Dict[str, Any]:
        """
        Convert QuestionOutput dataclass to dict for JSON serialization.
        """
        result = {
            'id': question.id,
            'question': question.question,
            'field': question.field,
            'field_type': question.field_type,
            'type': question.type
        }
        if question.valid_values is not None:
            result['valid_values'] = list(question.valid_values)
        if question.field_label is not None:
            result['field_label'] = question.field_label
        if question.field_description is not None:
            result['field_description'] = question.field_description
        if question.definitions is not None:
            # Convert tuple of tuples back to dict for JSON
            result['definitions'] = dict(question.definitions)
        return result
    
    @staticmethod
    def _dict_to_question_output(question_dict: Dict[str, Any]) -> QuestionOutput:
        valid_values = question_dict.get('valid_values')
        if valid_values is not None:
            valid_values = tuple(valid_values)
        
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
    
    def __init__(self, state_manager_class, question_selector, response_parser,
                 json_formatter, summary_generator, prompt_builder, episode_hypothesis_generator):
        """
        Initialize with module references
        """
        self._validate_modules(state_manager_class, question_selector, response_parser,
                               json_formatter, summary_generator, prompt_builder, episode_hypothesis_generator)
        
        self.state_manager_class = state_manager_class
        self.selector = question_selector
        self.parser = response_parser
        self.json_formatter = json_formatter
        self.summary_generator = summary_generator
        self.prompt_builder = prompt_builder
        self.episode_hypothesis_generator = episode_hypothesis_generator
               
        self.symptom_categories = self._extract_symptom_categories(question_selector)
        
        # Used for marking questions satisfied when fields are extracted
        self._question_to_field = question_selector._question_to_field.copy()
        self._field_to_questions = {}
        for q_id, field in self._question_to_field.items():
            if field not in self._field_to_questions:
                self._field_to_questions[field] = set()
            self._field_to_questions[field].add(q_id)
        # Freeze for safety (prevent accidental mutation)
        self._field_to_questions = {
            field: frozenset(q_ids) 
            for field, q_ids in self._field_to_questions.items()
        }
        
        # Routing debug tracking (per-turn)
        self._last_routing_info: List[tuple] = []
        
        logger.info(
            f"Dialogue Manager V2 initialized (functional core, "
            f"{len(self.symptom_categories)} symptom categories, "
            f"{len(self._question_to_field)} question-field mappings)"
        )
    
    def _validate_modules(self, state_manager_class, question_selector, response_parser,
                         json_formatter, summary_generator, prompt_builder, episode_hypothesis_generator):
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
        
        # Validate PromptBuilder interface
        if not (hasattr(prompt_builder, 'build') and 
                callable(getattr(prompt_builder, 'build', None))):
            raise TypeError("prompt_builder must have callable build() method")
        
        # Validate EpisodeHypothesisGenerator interface
        if not (hasattr(episode_hypothesis_generator, 'generate_hypothesis') and 
                callable(getattr(episode_hypothesis_generator, 'generate_hypothesis', None))):
            raise TypeError("episode_hypothesis_generator must have callable generate_hypothesis() method")
    
    def _commit_allowed(self, mode: ConversationMode) -> bool:
        """   
        Current implementation:
            Always returns True (preparation for V3 ambiguity blocking)
            
        Future expansion:
            - MODE_DISCOVERY: block commits
            - MODE_CLARIFICATION: block commits
            - MODE_EPISODE_EXTRACTION: allow commits
        """
    
    def _log_commit_block(self, fields: Dict[str, Any], mode: ConversationMode, episode_id: int) -> None:
        """
        Record structured event when episode commits are blocked for audit
            
        Logs at WARNING level with structured data.
        Does NOT modify state.
        """
        commit_block_event = {
            'mode': mode.value,
            'episode_id': episode_id,
            'blocked_fields': list(fields.keys()),
            'field_count': len(fields),
            'reason': 'commit_guard'
        }
        
        logger.warning(
            f"Commit blocked: mode={mode.value}, episode={episode_id}, "
            f"fields={list(fields.keys())[:3]}{'...' if len(fields) > 3 else ''}"
        )
        
        # V3-FUTURE: Add to state_manager audit log or clarification buffer
    
    def _extract_symptom_categories(self, question_selector) -> List[str]:
        """
        Extract symptom category field names from ruleset gating questions.
        """
        if not hasattr(question_selector, 'sections'):
            raise ValueError(
                "QuestionSelector missing 'sections' attribute. "
                "Cannot extract symptom categories without ruleset."
            )
        
        sections = question_selector.sections
        
        if 'gating_questions' not in sections:
            raise ValueError(
                "Ruleset missing 'sections.gating_questions'. "
                "Cannot extract symptom categories."
            )
        
        gating_questions = sections['gating_questions']
        
        # Fail fast: Check gating_questions is not empty
        if not gating_questions:
            raise ValueError(
                "Ruleset 'sections.gating_questions' is empty. "
                "Expected at least one gating question."
            )
        
        symptom_fields = []
        for question in gating_questions:
            if 'field' in question:
                symptom_fields.append(question['field'])
        
        if not symptom_fields:
            raise ValueError(
                f"Ruleset 'sections.gating_questions' has {len(gating_questions)} questions "
                "but none have 'field' attributes. Cannot extract symptom categories."
            )
        
        logger.info(f"Extracted {len(symptom_fields)} symptom categories from ruleset")
        return symptom_fields
    
    def _build_episode_context_for_ehg(
        self,
        state_manager,
        episode_id: int
    ) -> Dict[str, Any]:
        """
        Build current episode context for Episode Hypothesis Generator.
        """
        active_categories = []
        
        try:
            episode_data = state_manager.get_episode_for_selector(episode_id)
            
            # Check each symptom category field
            # self.symptom_categories contains field names like 'vl_present', 'cp_present'
            for field_name in self.symptom_categories:
                value = episode_data.get(field_name)
                if value is True:
                    # Extract category name from field (e.g., 'vl_present' -> 'visual_loss')
                    # For now, just use the prefix
                    category = field_name.replace('_present', '')
                    active_categories.append(category)
                    
        except Exception as e:
            logger.warning(f"Failed to build episode context for EHG: {e}")
            # Return empty context on error - EHG will handle gracefully
        
        return {
            "active_symptom_categories": active_categories
        }

    def _get_symptom_category_questions(self) -> List[QuestionOutput]:
        """
        Get QuestionOutput objects for symptom categories.
        
        Used to provide symptom category fields for prompt building.
        Only includes categories that have field_label and field_description.
        
        V4: Returns List[QuestionOutput] instead of List[Dict] for use with
        create_prompt_spec_from_question_output().
        
        Returns:
            List of QuestionOutput objects for symptom category fields
        """
        if not hasattr(self.selector, 'sections'):
            return []
        
        gating_questions = self.selector.sections.get('gating_questions', [])
        
        # Filter to only questions with required prompt metadata and convert to QuestionOutput
        valid_questions = []
        for q in gating_questions:
            if ('field_label' in q and 
                'field_description' in q and
                'field' in q and
                'field_type' in q):
                valid_questions.append(self._dict_to_question_output(q))
        
        logger.debug(
            f"Found {len(valid_questions)}/{len(gating_questions)} symptom categories "
            "with field labels/descriptions"
        )
        return valid_questions
    
    # =========================================================================
    # CONVERSATION MODE MANAGEMENT (V3)
    # =========================================================================
    
    def _determine_next_mode(
        self,
        current_mode: ConversationMode,
        state_snapshot: Dict[str, Any],
        ehg_signal: Optional[Any] = None,
        ehm_directive: Optional[str] = None
    ) -> ConversationMode:
        """
        Determine next conversation mode.
        
        CRITICAL INVARIANTS:
        - MODE_CLARIFICATION is sticky until explicit resolution
        - Mode changes are explicit, never implicit recomputation  
        - No mode changes based on convenience (e.g., episode count)
        
        NOTE:
        This function intentionally performs no transitions in V3 placeholder.
        All mode changes will be added explicitly once EHG + clarification
        plumbing is complete. Do not infer mode from state.
        
        TODO (V3-EHG-Integration): Remove no-op placeholder once:
        - EHG signals are wired through UserTurn flow
        - EHM resolution directives are implemented
        - Pivot detection is live
        
        Clarification Exit Authority:
        MODE_CLARIFICATION can ONLY be exited via explicit EHM directive.
        No falling out via timeout, retry exhaustion, or state inspection.
        Episode Hypothesis Management (EHM) owns clarification lifecycle.
        
        Args:
            current_mode: Authoritative current mode from state
            state_snapshot: State data (for future transition rules)
            ehg_signal: Episode hypothesis signal (unused in placeholder)
            ehm_directive: Episode hypothesis management directive (unused)
        
        Returns:
            ConversationMode: Next mode (currently always equals current_mode)
            
        Raises:
            TypeError: If current_mode is not ConversationMode enum
        """
        # Guardrail: Catch silent corruption early (fail-fast)
        if not isinstance(current_mode, ConversationMode):
            raise TypeError(
                f"current_mode must be ConversationMode, got {type(current_mode).__name__}"
            )
        
        # V3 Placeholder: No transitions implemented
        # Mode is sticky until explicit transition logic exists
        return current_mode
    
    # =========================================================================
    # PUBLIC API - Command Handler
    # =========================================================================
    
    def handle(self, command: Command) -> TurnResult | FinalReport | IllegalCommand:
        """
        ONLY public method. All interaction via commands.
        
        Validates command legality, routes to appropriate handler.
        
        Args:
            command: One of StartConsultation, UserTurn, FinalizeConsultation
            
        Returns:
            TurnResult: For StartConsultation, UserTurn
            FinalReport: For FinalizeConsultation
            IllegalCommand: If command invalid or illegal lifecycle transition
            
        Examples:
            >>> dm = DialogueManagerV2(...)
            >>> result = dm.handle(StartConsultation())
            >>> result = dm.handle(UserTurn("My vision is blurry", result.state))
            >>> report = dm.handle(FinalizeConsultation(result.state))
        """
        if isinstance(command, StartConsultation):
            return self._handle_start()
        
        elif isinstance(command, UserTurn):
            return self._handle_user_turn(command)
        
        elif isinstance(command, FinalizeConsultation):
            return self._handle_finalize(command)
        
        else:
            return IllegalCommand(
                reason=f"Unknown command type: {type(command).__name__}",
                command_type=type(command).__name__
            )
    
    # =========================================================================
    # COMMAND HANDLERS (Internal)
    # =========================================================================
    
    def _handle_start(self) -> TurnResult:
        """
        Handle StartConsultation command.
        
        Creates initial state, returns first question.
        
        Returns:
            TurnResult with first question + initial state
        """
        # Initialize new consultation
        state_manager, turn_count, current_episode_id, consultation_id = \
            self._initialize_new_consultation()
        
        # Get first question (returns QuestionOutput)
        episode_data = state_manager.get_episode_for_selector(current_episode_id)
        first_question = self.selector.get_next_question(episode_data)
        
        if first_question is None:
            # Shouldn't happen on first turn, but handle gracefully
            logger.error("No questions available on first turn")
            
            # Build minimal state for error case
            canonical_snapshot = state_manager.snapshot_state()
            canonical_snapshot['consultation_id'] = consultation_id
            canonical_snapshot['turn_count'] = turn_count
            canonical_snapshot['current_episode_id'] = current_episode_id
            canonical_snapshot['awaiting_first_question'] = False
            canonical_snapshot['awaiting_episode_transition'] = False
            canonical_snapshot['pending_question'] = None
            canonical_snapshot['errors'] = []
            canonical_snapshot['consultation_complete'] = True
            
            state = ConsultationState.from_json(canonical_snapshot)
            
            return TurnResult(
                system_output="Error: No questions configured",
                state=state,
                debug={'error': 'no_questions'},
                turn_metadata={'turn_count': turn_count, 'consultation_id': consultation_id},
                consultation_complete=True
            )
        
        # Convert QuestionOutput to dict for JSON storage
        question_dict = self._question_output_to_dict(first_question)
        
        # Build canonical snapshot
        canonical_snapshot = state_manager.snapshot_state()
        canonical_snapshot['consultation_id'] = consultation_id
        canonical_snapshot['turn_count'] = turn_count + 1  # First question is turn 1
        canonical_snapshot['current_episode_id'] = current_episode_id
        canonical_snapshot['awaiting_first_question'] = False
        canonical_snapshot['awaiting_episode_transition'] = False
        canonical_snapshot['pending_question'] = question_dict
        canonical_snapshot['errors'] = []
        canonical_snapshot['consultation_complete'] = False
        
        # Wrap in opaque envelope
        state = ConsultationState.from_json(canonical_snapshot)
        
        logger.info(f"Started consultation {consultation_id}")
        
        return TurnResult(
            system_output=first_question.question,  # Use attribute access
            state=state,
            debug={'first_question': True},
            turn_metadata={
                'turn_count': turn_count + 1,
                'consultation_id': consultation_id,
                'episode_id': current_episode_id
            },
            consultation_complete=False
        )
    
    def _handle_user_turn(self, command: UserTurn) -> TurnResult | IllegalCommand:
        """
        Handle UserTurn command.
        
        Processes user input, updates state, returns next question.
        
        Args:
            command: UserTurn with user_input and state
            
        Returns:
            TurnResult with next question + updated state
            IllegalCommand if state invalid
        """
        # Extract canonical dict from opaque envelope
        # DialogueManager is allowed to inspect (StateManager owner)
        state_snapshot = command.state.to_json()
        
        # Validate basic structure
        if 'consultation_id' not in state_snapshot:
            return IllegalCommand(
                reason="State missing consultation_id - invalid state",
                command_type="UserTurn"
            )
        
        # Delegate to internal turn handler
        return self._handle_turn_impl(command.user_input, state_snapshot)
    
    def _handle_finalize(self, command: FinalizeConsultation) -> FinalReport | IllegalCommand:
        """
        Handle FinalizeConsultation command.
        
        Generates JSON + summary outputs.
        
        Args:
            command: FinalizeConsultation with state
            
        Returns:
            FinalReport with file paths
            IllegalCommand if consultation not complete
        """
        # Extract state
        state_snapshot = command.state.to_json()
        
        # Validate consultation is actually complete
        if not state_snapshot.get('consultation_complete', False):
            return IllegalCommand(
                reason="Cannot finalize: consultation not complete",
                command_type="FinalizeConsultation"
            )
        
        # Call existing generate_outputs logic
        outputs = self.generate_outputs(
            state_snapshot=state_snapshot,
            output_dir="outputs/consultations"
        )
        
        logger.info(f"Finalized consultation {outputs['consultation_id']}")
        
        return FinalReport(
            json_path=outputs['json_path'],
            summary_path=outputs['summary_path'],
            json_filename=outputs['json_filename'],
            summary_filename=outputs['summary_filename'],
            consultation_id=outputs['consultation_id'],
            total_episodes=outputs['total_episodes']
        )
    
    # =========================================================================
    # INTERNAL - Turn processing implementation
    # =========================================================================
    
    def _handle_turn_impl(
        self,
        user_input: str,
        state_snapshot: Dict[str, Any]
    ) -> TurnResult:
        """
        Internal turn processing implementation.
        
        Called by _handle_user_turn after state validation.
        
        Args:
            user_input: Patient's response text
            state_snapshot: Canonical state dict (validated, non-None)
            
        Returns:
            TurnResult with updated state wrapped in ConsultationState
        """
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
        
        # V3: Extract and validate current conversation mode
        current_mode_str = state_snapshot.get('conversation_mode', ConversationMode.MODE_EPISODE_EXTRACTION.value)
        current_mode = ConversationMode(current_mode_str)
        
        # V3: Determine next mode (currently no-op, returns current_mode)
        next_mode = self._determine_next_mode(
            current_mode=current_mode,
            state_snapshot=state_snapshot,
            ehg_signal=None,  # TODO (V3-EHG): Wire Episode Hypothesis Generator
            ehm_directive=None  # TODO (V3-EHM): Wire Episode Hypothesis Management
        )
        
        # V3: Update state manager with next mode
        state_manager.conversation_mode = next_mode.value
        
        if turn_count < 0:
            raise ValueError("state_snapshot has invalid turn_count")
        
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
                consultation_complete=True,
                previous_mode=current_mode_str  # V3: Track mode changes
            )
        
        # Determine what we're processing
        if awaiting_first_question:
            # First turn after initialization - just return first question
            return self._get_first_question(
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count,
                current_episode_id=current_episode_id,
                errors=errors,
                previous_mode=current_mode_str  # V3: Track mode changes
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
                errors=errors,
                previous_mode=current_mode_str  # V3: Track mode changes
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
                errors=errors,
                previous_mode=current_mode_str  # V3: Track mode changes
            )
    
    def _initialize_new_consultation(self):
        """
        Initialize new consultation (first turn only)
        
        V3: Sets explicit initial conversation mode (policy decision).
        All consultations start in MODE_DISCOVERY until EHG-driven
        transitions are implemented.
        
        Returns:
            tuple: (state_manager, turn_count, current_episode_id, consultation_id)
        """
        consultation_id = generate_consultation_id(short=True)
        
        # Create StateManager and first episode
        state_manager = self.state_manager_class("data/clinical_data_model.json")
        first_episode_id = state_manager.create_episode()
        
        # V3: Set initial mode explicitly (policy decision, not inference)
        # StateManager.__init__ already sets MODE_DISCOVERY as default,
        # but we make it explicit here for clarity
        state_manager.conversation_mode = ConversationMode.MODE_DISCOVERY.value
        
        # No JSON formatter call - just return the state manager
        # Empty episode is preserved in canonical state
        
        logger.info(f"Initialized consultation {consultation_id}, mode={ConversationMode.MODE_DISCOVERY.value}")
        
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
        consultation_complete: bool,
        previous_mode: Optional[str] = None  # V3: For mode_changed detection
    ) -> TurnResult:
        """
        Build TurnResult with opaque ConsultationState and enhanced debug.
        
        The state is wrapped in ConsultationState envelope - Flask cannot inspect it.
        Routing debug is added to debug dict.
        
        V3: Tracks conversation mode and detects mode transitions.
        
        Args:
            previous_mode: Previous conversation mode (for detecting changes)
                         If None, mode_changed defaults to False
        """
        # Get canonical snapshot (lossless, for persistence)
        canonical_snapshot = state_manager.snapshot_state()
        
        # V3: Extract current mode from state manager
        current_mode = canonical_snapshot.get('conversation_mode', ConversationMode.MODE_EPISODE_EXTRACTION.value)
        
        # V3: Detect mode change
        mode_changed = (previous_mode is not None and previous_mode != current_mode)
        
        # Add turn-level metadata (not in StateManager)
        canonical_snapshot['consultation_id'] = consultation_id
        canonical_snapshot['turn_count'] = turn_count
        canonical_snapshot['current_episode_id'] = current_episode_id
        canonical_snapshot['awaiting_first_question'] = awaiting_first_question
        canonical_snapshot['awaiting_episode_transition'] = awaiting_episode_transition
        canonical_snapshot['pending_question'] = pending_question
        canonical_snapshot['errors'] = errors
        canonical_snapshot['consultation_complete'] = consultation_complete
        
        # Build routing debug and add to debug dict
        routing_debug = self._build_routing_debug()
        if routing_debug:  # Only add if we have routing info
            debug['routing'] = routing_debug
        
        # Add human-readable state view for UI display
        debug['state_view'] = format_state_for_display(canonical_snapshot)
        
        # Wrap state in opaque envelope
        state = ConsultationState.from_json(canonical_snapshot)
        
        return TurnResult(
            system_output=system_output,
            state=state,  # Opaque! Flask cannot inspect.
            debug=debug,
            turn_metadata={
                'turn_count': turn_count,
                'current_episode_id': current_episode_id,
                'consultation_id': consultation_id,
                'conversation_mode': current_mode,  # V3: Current mode
                'mode_changed': mode_changed  # V3: Alert transport layer
            },
            consultation_complete=consultation_complete
        )
    
    def _get_first_question(
        self,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        errors: list,
        previous_mode: Optional[str] = None  # V3: For mode change tracking
    ) -> TurnResult:
        """
        Get first question for new consultation
        
        Args:
            state_manager: Rehydrated state manager
            consultation_id: Consultation ID
            turn_count: Current turn count
            current_episode_id: Current episode ID
            errors: List of errors from previous turns
            previous_mode: Previous conversation mode (V3)
            
        Returns:
            TurnResult with first question
        """
        episode_data = state_manager.get_episode_for_selector(current_episode_id)
        
        # Get first question (returns QuestionOutput)
        first_question = self.selector.get_next_question(episode_data)
        
        if first_question is None:
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
                consultation_complete=True,
                previous_mode=previous_mode
            )
        
        # Convert QuestionOutput to dict for JSON storage
        question_dict = self._question_output_to_dict(first_question)
        
        return self._build_turn_result(
            system_output=first_question.question,  # Use attribute access
            state_manager=state_manager,
            consultation_id=consultation_id,
            turn_count=turn_count + 1,
            current_episode_id=current_episode_id,
            awaiting_first_question=False,
            awaiting_episode_transition=False,
            pending_question=question_dict,
            errors=errors,
            debug={'first_question': True},
            consultation_complete=False,
            previous_mode=previous_mode
        )
    
    def _process_regular_turn(
        self,
        user_input: str,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        pending_question: Dict,
        errors: list,
        previous_mode: Optional[str] = None  # V3: For mode change tracking
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
            previous_mode: Previous conversation mode (V3)
            
        Returns:
            TurnResult with next question or episode transition
        """
        if pending_question is None:
            raise ValueError("No pending question in state")
        
        # V3: Build current episode context for EHG
        # Simple V1: just the active symptom categories
        current_episode_context = self._build_episode_context_for_ehg(
            state_manager=state_manager,
            episode_id=current_episode_id
        )
        
        # V3: Generate episode hypothesis signal
        # TODO: Episode Hypothesis Manager will consume this signal for mode transitions
        ehg_signal = self.episode_hypothesis_generator.generate_hypothesis(
            user_utterance=user_input,
            last_system_question=pending_question.get('question'),
            current_episode_context=current_episode_context
        )
        logger.debug(
            f"EHG signal: hypothesis_count={ehg_signal.hypothesis_count}, "
            f"pivot_detected={ehg_signal.pivot_detected}"
        )
        
        # V3: Assess episode safety from EHG signal
        safety_status = assess_episode_safety(ehg_signal)
        logger.debug(f"Episode safety status: {safety_status.value}")
        
        # V3: Episode ambiguity handling - coerce back to current episode
        # If ambiguity detected, generate narrowing prompt and block RP commit
        # Stay in MODE_EPISODE_EXTRACTION, re-ask pending question
        if safety_status != EpisodeSafetyStatus.SAFE_TO_EXTRACT:
            # Generate coercion prompt
            coercion_prompt = build_episode_narrowing_prompt(safety_status)
            
            # Append the pending question to redirect focus
            system_output = f"{coercion_prompt}\n\nFor the current problem, {pending_question['question']}"
            
            logger.warning(
                f"Episode ambiguity detected: {safety_status.value}. "
                f"Coercing back to episode {current_episode_id}, "
                f"question '{pending_question['id']}'"
            )
            
            # Return early - do NOT run parser, do NOT commit any data
            # Re-present the same pending question
            return self._build_turn_result(
                system_output=system_output,
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count + 1,
                current_episode_id=current_episode_id,
                awaiting_first_question=False,
                awaiting_episode_transition=False,
                pending_question=pending_question,  # Same question again
                errors=errors,
                debug={
                    'episode_ambiguity_detected': True,
                    'safety_status': safety_status.value,
                    'ehg_signal': {
                        'hypothesis_count': ehg_signal.hypothesis_count,
                        'confidence_band': ehg_signal.confidence_band.value,
                        'pivot_detected': ehg_signal.pivot_detected,
                        'pivot_confidence_band': ehg_signal.pivot_confidence_band.value
                    },
                    'coercion_applied': True,
                    'parser_output_discarded': True
                },
                consultation_complete=False,
                previous_mode=previous_mode
            )
        
        # Safety status is SAFE_TO_EXTRACT - proceed with normal flow
        logger.debug("Episode safety check passed - proceeding with extraction")
        
        # Get next questions for multi-question metadata window (returns List[QuestionOutput])
        next_questions_output = self.selector.get_next_n_questions(
            current_question_id=pending_question['id'],
            n=3
        )
        
        # Get symptom category questions (now returns List[QuestionOutput])
        symptom_category_questions = self._get_symptom_category_questions()
        
        # Build combined additional_fields (all QuestionOutput objects)
        all_additional_questions = []
        if next_questions_output:
            all_additional_questions.extend(next_questions_output)
        if symptom_category_questions:
            all_additional_questions.extend(symptom_category_questions)
        
        # Convert pending_question dict back to QuestionOutput for prompt building
        pending_question_output = self._dict_to_question_output(pending_question)
        
        # Build extraction prompt
        try:
            # Create PromptSpec from QuestionOutput (V4)
            prompt_spec = create_prompt_spec_from_question_output(
                question=pending_question_output,
                mode=PromptMode.PRIMARY,
                next_questions=all_additional_questions if all_additional_questions else None
            )
            
            # Build prompt text
            prompt_text = self.prompt_builder.build(prompt_spec, user_input)
            
            logger.debug(
                f"Built prompt for {pending_question['id']} "
                f"({len(all_additional_questions)} additional fields)"
            )
            
        except PromptBuildError as e:
            # Prompt construction failed - this is a critical error
            # Let it propagate to crash the system
            logger.error(f"PromptBuilder failed for {pending_question['id']}: {e}")
            raise
        
        # Parse response with pre-built prompt
        try:
            parse_result = self.parser.parse(
                prompt_text=prompt_text,
                patient_response=user_input,
                expected_field=pending_question['field'],
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
        # V3-GUARD: Convert mode to enum and pass to routing for commit guard
        current_mode = ConversationMode(state_manager.conversation_mode)
        
        unmapped = self._route_extracted_fields(
            episode_id=current_episode_id,
            extracted=fields,
            state_manager=state_manager,
            mode=current_mode
        )
        
        # Mark questions satisfied based on extracted fields
        # This happens BEFORE marking the pending question as answered
        # because satisfaction is about data obtained, not about which question was asked
        for field_name in fields.keys():
            if field_name in self._field_to_questions:
                for q_id in self._field_to_questions[field_name]:
                    state_manager.mark_question_satisfied(current_episode_id, q_id)
                    logger.debug(
                        f"Episode {current_episode_id}: marked question '{q_id}' "
                        f"satisfied via field '{field_name}'"
                    )
        
        # Mark pending question as answered (separate from satisfaction)
        # This tracks which questions were explicitly asked
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
        
        # Get next question (returns QuestionOutput or None)
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
                consultation_complete=False,
                previous_mode=previous_mode
            )
        else:
            # Convert QuestionOutput to dict for storage
            next_question_dict = self._question_output_to_dict(next_question)
            
            # Continue with next question
            return self._build_turn_result(
                system_output=next_question.question,  # Use attribute access
                state_manager=state_manager,
                consultation_id=consultation_id,
                turn_count=turn_count + 1,
                current_episode_id=current_episode_id,
                awaiting_first_question=False,
                awaiting_episode_transition=False,
                pending_question=next_question_dict,
                errors=errors,
                debug={'parser_output': parse_result},
                consultation_complete=False,
                previous_mode=previous_mode
            )
    
    def _process_episode_transition(
        self,
        user_input: str,
        state_manager,
        consultation_id: str,
        turn_count: int,
        current_episode_id: int,
        pending_question: Dict,
        errors: list,
        previous_mode: Optional[str] = None  # V3: For mode change tracking
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
            previous_mode: Previous conversation mode (V3)
            
        Returns:
            TurnResult with new episode question or finalization
        """
        # Parse transition response (no next_questions for meta-question)
        try:
            # Convert TRANSITION_QUESTION dict to QuestionOutput for prompt building (V4)
            transition_question_output = self._dict_to_question_output(self.TRANSITION_QUESTION)
            
            # Build extraction prompt for transition question
            prompt_spec = create_prompt_spec_from_question_output(
                question=transition_question_output,
                mode=PromptMode.PRIMARY,
                next_questions=None  # No metadata window for transition
            )
            
            prompt_text = self.prompt_builder.build(prompt_spec, user_input)
            
            # Parse with pre-built prompt
            parse_result = self.parser.parse(
                prompt_text=prompt_text,
                patient_response=user_input,
                expected_field=self.TRANSITION_QUESTION['field'],
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
                
                # Get first question for new episode (returns QuestionOutput)
                episode_data = state_manager.get_episode_for_selector(new_episode_id)
                first_question = self.selector.get_next_question(episode_data)
                
                # Defensive check: new episode should always have questions
                if first_question is None:
                    logger.error(f"No questions available for new episode {new_episode_id}")
                    errors.append({
                        'context': 'episode_transition',
                        'error': f'No questions configured for episode {new_episode_id}',
                        'episode_id': new_episode_id
                    })
                    return self._build_turn_result(
                        system_output="Error: Unable to start new episode - no questions configured",
                        state_manager=state_manager,
                        consultation_id=consultation_id,
                        turn_count=turn_count + 1,
                        current_episode_id=new_episode_id,
                        awaiting_first_question=False,
                        awaiting_episode_transition=False,
                        pending_question=None,
                        errors=errors,
                        debug={
                            'parser_output': parse_result,
                            'new_episode': new_episode_id,
                            'error': 'no_questions_for_new_episode'
                        },
                        consultation_complete=True,
                        previous_mode=previous_mode
                    )
                
                # Convert QuestionOutput to dict for storage
                first_question_dict = self._question_output_to_dict(first_question)
                
                return self._build_turn_result(
                    system_output=f"Episode {new_episode_id} - {first_question.question}",  # Use attribute
                    state_manager=state_manager,
                    consultation_id=consultation_id,
                    turn_count=turn_count + 1,
                    current_episode_id=new_episode_id,
                    awaiting_first_question=False,
                    awaiting_episode_transition=False,
                    pending_question=first_question_dict,
                    errors=errors,
                    debug={
                        'parser_output': parse_result,
                        'new_episode': new_episode_id
                    },
                    consultation_complete=False,
                    previous_mode=previous_mode
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
                    consultation_complete=True,
                    previous_mode=previous_mode
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
                consultation_complete=False,
                previous_mode=previous_mode
            )
    
    def _route_extracted_fields(
        self,
        episode_id: int,
        extracted: Dict[str, Any],
        state_manager,
        mode: ConversationMode
    ) -> Dict[str, Any]:
        """
        Route extracted fields to episode or shared storage.
        
        V3-GUARD: Centralizes all RP ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â ÃƒÂ¢Ã¢â€šÂ¬Ã¢â€žÂ¢ State writes behind commit guard.
        
        Routing rules:
        - Episode fields: Prefix-based + guard-gated
        - Shared fields: Prefix-based + collection detection
        - Unknown fields: Quarantined in return value
        
        Commit semantics:
        - Shared fields: Always written (no guard)
        - Episode fields: Written only if commit_allowed(mode)
        - Blocked episode fields: Logged, not written
        
        Args:
            episode_id: Target episode for episode-scoped fields
            extracted: Parsed fields from Response Parser
            state_manager: StateManager instance
            mode: Current conversation mode (V3-GUARD)
            
        Returns:
            dict: Unmapped fields (quarantined, not written)
        """
        unmapped = {}
        routing_info = []  # Capture for debug
        episode_fields_to_commit = {}  # V3-GUARD: Buffer for guarded writes
        
        # Phase 1: Classify and buffer
        for field_name, value in extracted.items():
            if field_name.startswith('_'):
                continue
            
            classification = classify_field(field_name)
            
            # Capture routing decision for debug (include episode_id if episode field)
            captured_episode_id = episode_id if classification == 'episode' else None
            routing_info.append((field_name, value, classification, captured_episode_id))
            
            if classification == 'episode':
                # Buffer for guarded commit (don't write yet)
                episode_fields_to_commit[field_name] = value
                    
            elif classification == 'shared':
                # Shared fields bypass guard (always written)
                try:
                    state_manager.set_shared_field(field_name, value)
                    logger.debug(f"Shared data: {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to set shared field {field_name}: {e}")
                    
            else:
                # Quarantine unknown fields
                unmapped[field_name] = value
                logger.warning(f"Unmapped field: {field_name} = {value}")
        
        # Phase 2: Guarded episode commit (SINGLE DECISION POINT)
        if episode_fields_to_commit:
            if self._commit_allowed(mode):
                # Commit permitted - write all buffered episode fields
                for field_name, value in episode_fields_to_commit.items():
                    try:
                        state_manager.set_episode_field(episode_id, field_name, value)
                        logger.debug(f"Episode {episode_id}: {field_name} = {value}")
                    except Exception as e:
                        logger.error(f"Failed to set episode field {field_name}: {e}")
            else:
                # Commit blocked - log structured event
                self._log_commit_block(episode_fields_to_commit, mode, episode_id)
                # Note: Parsed data returned normally, just not written
        
        # Store for debug builder
        self._last_routing_info = routing_info
        
        return unmapped
    
    def _check_and_activate_triggers(self, episode_id: int, state_manager):
        """Check for triggered follow-up blocks"""
        try:
            episode_data = state_manager.get_episode_for_selector(episode_id)
            triggered_blocks = self.selector.check_triggers(episode_data)
            
            # get_episode_for_selector returns lists, convert to set for set operations
            already_activated = set(episode_data.get('follow_up_blocks_activated', []))
            
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
            
            # get_episode_for_selector returns lists, convert to sets for set operations
            activated = set(episode_data.get('follow_up_blocks_activated', []))
            completed = set(episode_data.get('follow_up_blocks_completed', []))
            pending = activated - completed
            
            for block_id in pending:
                if self.selector.is_block_complete(block_id, episode_data):
                    state_manager.complete_follow_up_block(episode_id, block_id)
                    logger.info(f"Episode {episode_id}: Completed block '{block_id}'")
                    
        except Exception as e:
            logger.error(f"Block completion check failed: {e}")
    
    def _build_routing_debug(self) -> list:
        """
        Build routing debug information from last turn.
        
        Returns routing decisions for debug panel display.
        
        Returns:
            list: Routing info dicts with field, value, resolution, episode_id, rule, recognized
        """
        # Import classifier data (flat imports for server)
        from backend.utils.episode_classifier import EPISODE_PREFIXES, SHARED_PREFIXES, COLLECTION_FIELDS
        
        routing_debug = []
        
        for field_name, value, classification, episode_id in self._last_routing_info:
            # Determine rule that matched
            if classification == 'episode':
                # Find which prefix matched
                matching_prefix = next(
                    (p for p in EPISODE_PREFIXES if field_name.startswith(p)),
                    'unknown'
                )
                rule = f"prefix:{matching_prefix}"
                
            elif classification == 'shared':
                # Check if it's a collection
                if field_name in COLLECTION_FIELDS:
                    rule = "collection"
                else:
                    # Find which prefix matched
                    matching_prefix = next(
                        (p for p in SHARED_PREFIXES if field_name.startswith(p)),
                        'unknown'
                    )
                    rule = f"prefix:{matching_prefix}"
            else:
                rule = "unknown"
            
            routing_debug.append({
                "field": field_name,
                "value": str(value)[:50],  # Truncate long values
                "resolution": classification,
                "episode_id": episode_id,
                "rule": rule,
                "recognized": classification != 'unknown'
            })
        
        return routing_debug
    
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
        
        # Use class method from already-cached formatter
        # (self.json_formatter is JSONFormatterV2 instance)
        self.json_formatter.save_to_file(json_data, json_path)
        
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
