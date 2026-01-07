"""
State Manager V2 - Multi-episode consultation state management

Responsibilities:
- Store multiple episodes (array of episode objects)
- Store shared data (flat scalars + arrays)
- Store dialogue history per episode
- Minimal API - pure data storage, no business logic

Design principles:
- Episodes as array (not dict) - preserves temporal order
- Flat field structure (no dot notation nesting)
- Clean separation: episode-specific vs shared data
- No UI state in exported JSON (no "current_episode_id")
- No clinical validation (State Manager is a dumb container)

API Philosophy:
- State Manager = dumb data container
- Dialogue Manager = smart coordinator (tracks current episode)
- Question Selector = medical protocol logic

CRITICAL: Episode ID vs Array Index
- Episode IDs are 1-indexed (user-facing identifiers): 1, 2, 3, ...
- Python lists are 0-indexed (storage): episodes[0], episodes[1], episodes[2], ...
- Always use clear naming to prevent off-by-one errors:
    episode_id = 2          # User-facing ID (1-indexed)
    index = episode_id - 1  # Storage index (0-indexed)
    episode = self.episodes[index]
- NEVER assume episode_id == list index
"""

import logging
from typing import List, Dict, Any, Optional
import json
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field

# Flat imports for server testing
# When copying to local, adjust to: from backend.conversation_modes import ...
from conversation_modes import ConversationMode, VALID_MODES

logger = logging.getLogger(__name__)


# ========================
# Clarification Models
# ========================

class ClarificationResolution(str, Enum):
    """
    Outcome of clarification phase.
    
    This enum represents the outcome of ambiguity resolution,
    not clinical truth or episode identity.
    
    Values:
        CONFIRMED: User confirmed episode hypothesis
        NEGATED: User denied episode hypothesis
        FORCED: System applied forced resolution policy
        UNRESOLVABLE: Ambiguity could not be resolved
    """
    CONFIRMED = "confirmed"
    NEGATED = "negated"
    FORCED = "forced"
    UNRESOLVABLE = "unresolvable"


@dataclass(frozen=True)
class ClarificationTurn:
    """
    Single turn in clarification transcript.
    
    Immutable snapshot of (question, response, replayability) at time of asking.
    The replayable flag is denormalized from template registry to ensure
    replay semantics remain stable across template changes.
    
    Fields:
        template_id: ID of clarification question template
        user_text: Raw user response (verbatim)
        replayable: Whether this turn is eligible for Response Parser replay
    """
    template_id: str
    user_text: str
    replayable: bool
    
    def __post_init__(self):
        """Validate fields after initialization"""
        if not self.user_text or not self.user_text.strip():
            raise ValueError("user_text cannot be empty")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization"""
        return {
            'template_id': self.template_id,
            'user_text': self.user_text,
            'replayable': self.replayable
        }


@dataclass
class ClarificationContext:
    """
    Clarification phase context.
    
    This object exists only during MODE_CLARIFICATION.
    It is created on mode entry and cleared on mode exit.
    
    Fields:
        transcript: Ordered list of clarification turns
        entry_count: Number of turns in transcript (redundant but useful for logging)
        resolution_status: Outcome of clarification (None until resolved)
    """
    transcript: List[ClarificationTurn] = field(default_factory=list)
    entry_count: int = 0
    resolution_status: Optional[ClarificationResolution] = None
    
    def __post_init__(self):
        """Validate entry_count matches transcript length"""
        if self.entry_count != len(self.transcript):
            raise ValueError(
                f"entry_count ({self.entry_count}) does not match "
                f"transcript length ({len(self.transcript)})"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization"""
        return {
            'transcript': [turn.to_dict() for turn in self.transcript],
            'entry_count': self.entry_count,
            'resolution_status': self.resolution_status.value if self.resolution_status else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClarificationContext':
        """Reconstruct from dict"""
        transcript = [
            ClarificationTurn(**turn_data)
            for turn_data in data.get('transcript', [])
        ]
        resolution_str = data.get('resolution_status')
        resolution = ClarificationResolution(resolution_str) if resolution_str else None
        
        return cls(
            transcript=transcript,
            entry_count=data.get('entry_count', 0),
            resolution_status=resolution
        )


class StateManagerV2:
    """Manages multi-episode consultation state"""
    
    # Operational fields excluded from clinical JSON export.
    # 
    # These fields are used internally for tracking conversation state
    # but are NOT clinical data and should not appear in final JSON output.
    #
    # Exclusion behavior by method:
    # - export_clinical_view(): EXCLUDES these fields (clinical output only)
    # - export_for_summary(): INCLUDES these fields (summary may need context)
    # - get_episode_for_selector(): INCLUDES these fields (selector needs them)
    # - get_episode(): INCLUDES these fields (internal use, full access)
    OPERATIONAL_FIELDS = {
        'questions_answered',
        'follow_up_blocks_activated',
        'follow_up_blocks_completed'
    }
    
    def __init__(self, data_model_path: str = "data/clinical_data_model.json"):
        """
        Initialize empty multi-episode state
        
        Args:
            data_model_path: Path to clinical data model JSON file
        """
        # Load clinical data model
        data_model_file = Path(data_model_path)
        if not data_model_file.exists():
            raise FileNotFoundError(f"Clinical data model not found: {data_model_path}")
            
        with open(data_model_file, 'r') as f:
            self.data_model = json.load(f)
            
        # Initialize state from template
        self.episodes: List[Dict[str, Any]] = []
        self.shared_data: Dict[str, Any] = self._deep_copy(self.data_model["shared_data_template"])
        self.dialogue_history: Dict[int, List[Dict[str, Any]]] = {}
        
        # Clarification context (only exists during MODE_CLARIFICATION)
        self.clarification_context: Optional[ClarificationContext] = None
        
        # Conversation mode (placeholder for new instances)
        # CRITICAL: This default is overridden by from_snapshot() during rehydration.
        # Only applies to fresh StateManager instances created by DialogueManager._handle_start()
        # Do not rely on this default for persistence logic.
        self.conversation_mode = ConversationMode.MODE_DISCOVERY.value

        logger.info(f"State Manager V2 initialized (multi-episode, model version {self.data_model.get('version', 'unknown')})")
    
    # ========================
    # Private Helpers
    # ========================
    
    def _validate_episode_id(self, episode_id: int) -> None:
        """
        Validate that episode_id exists.
        
        Args:
            episode_id: Episode ID to validate (1-indexed)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist")
    
    def _validate_conversation_mode(self, mode: str) -> None:
        """
        Validate conversation mode field (fail-fast data integrity check).
        
        This is data integrity validation, not business logic.
        StateManager cannot derive or repair mode - it only validates
        that the mode string is one of the recognized values.
        
        DialogueManager owns all mode transition logic.
        
        Args:
            mode: Mode string from state snapshot
            
        Raises:
            ValueError: If mode is not in VALID_MODES
            
        Example:
            # Valid
            self._validate_conversation_mode("discovery")  # OK
            
            # Invalid - will raise
            self._validate_conversation_mode("invalid")  # ValueError
            self._validate_conversation_mode(None)  # ValueError
        """
        if mode not in VALID_MODES:
            raise ValueError(
                f"Invalid conversation_mode: '{mode}'. "
                f"Must be one of {VALID_MODES}"
            )
    
    def _deep_copy(self, obj: Any) -> Any:
        """
        Create deep copy of nested dict/list structure.
        
        Args:
            obj: Object to copy (dict, list, set, or primitive)
            
        Returns:
            Deep copy of object
        """
        if isinstance(obj, dict):
            return {k: self._deep_copy(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_copy(item) for item in obj]
        elif isinstance(obj, set):
            return {self._deep_copy(item) for item in obj}
        else:
            return obj
    
    def _serialize_episode(self, episode: Dict[str, Any], exclude_operational: bool = False) -> Dict[str, Any]:
        """
        Create a serializable deep copy of an episode.
        
        Converts sets to sorted lists for JSON compatibility.
        Optionally excludes operational fields.
        
        Args:
            episode: Episode dict to serialize
            exclude_operational: If True, exclude OPERATIONAL_FIELDS
            
        Returns:
            Dict with sets converted to sorted lists, all values deep copied
        """
        result = {}
        for key, value in episode.items():
            # Skip operational fields if requested
            if exclude_operational and key in self.OPERATIONAL_FIELDS:
                continue
            
            # Convert sets to sorted lists, deep copy everything else
            if isinstance(value, set):
                result[key] = sorted(list(value))
            else:
                result[key] = self._deep_copy(value)
        
        return result
    
    # ========================
    # Clarification Buffer Management
    # ========================
    
    def init_clarification_context(self) -> None:
        """
        Initialize clarification context on entry to MODE_CLARIFICATION.
        
        Creates empty ClarificationContext.
        
        Raises:
            RuntimeError: If clarification context already exists
            
        Example:
            state.init_clarification_context()
            assert state.clarification_context is not None
            assert state.clarification_context.entry_count == 0
        """
        if self.clarification_context is not None:
            raise RuntimeError(
                "Clarification context already exists. "
                "Must clear before re-initializing."
            )
        
        self.clarification_context = ClarificationContext()
        logger.info("Clarification context initialized")
    
    def append_clarification_turn(
        self,
        template_id: str,
        user_text: str,
        replayable: bool
    ) -> None:
        """
        Append turn to clarification transcript.
        
        This method snapshots the turn at time of asking.
        The replayable flag is denormalized from the template registry
        to ensure stability across template changes.
        
        Args:
            template_id: Clarification question template ID
            user_text: Verbatim user response
            replayable: Whether turn is eligible for replay
            
        Raises:
            RuntimeError: If clarification context not initialized
            ValueError: If validation fails (empty user_text, etc.)
            
        Example:
            state.append_clarification_turn(
                template_id="clarify_location",
                user_text="It was in my left eye",
                replayable=True
            )
        """
        if self.clarification_context is None:
            raise RuntimeError(
                "Cannot append turn: clarification context not initialized. "
                "Call init_clarification_context() first."
            )
        
        # Create immutable turn (dataclass validates in __post_init__)
        turn = ClarificationTurn(
            template_id=template_id,
            user_text=user_text,
            replayable=replayable
        )
        
        # Append to transcript and sync entry_count
        self.clarification_context.transcript.append(turn)
        self.clarification_context.entry_count = len(self.clarification_context.transcript)
        
        logger.debug(
            f"Appended clarification turn: template={template_id}, "
            f"replayable={replayable}, entry_count={self.clarification_context.entry_count}"
        )
    
    def clear_clarification_context(self) -> None:
        """
        Clear clarification context on exit from MODE_CLARIFICATION.
        
        This is an atomic operation - context is either present or None.
        Always call this on mode exit, regardless of resolution outcome.
        
        Example:
            # After resolution
            state.clear_clarification_context()
            assert state.clarification_context is None
        """
        if self.clarification_context is None:
            logger.warning("clear_clarification_context() called but context already None")
            return
        
        entry_count = self.clarification_context.entry_count
        self.clarification_context = None
        logger.info(f"Clarification context cleared ({entry_count} turns discarded)")
    
    def get_clarification_transcript(self) -> List[ClarificationTurn]:
        """
        Get immutable copy of clarification transcript.
        
        Returns complete transcript, regardless of replayability.
        Caller is responsible for filtering by replayable flag if needed.
        
        Returns:
            List[ClarificationTurn]: Ordered transcript (may be empty)
            
        Raises:
            RuntimeError: If clarification context not initialized
            
        Example:
            # Get all turns
            turns = state.get_clarification_transcript()
            
            # Filter replayable only (caller's responsibility)
            replayable_turns = [t for t in turns if t.replayable]
        """
        if self.clarification_context is None:
            raise RuntimeError(
                "Cannot get transcript: clarification context not initialized"
            )
        
        # Return shallow copy (turns are immutable so this is safe)
        return list(self.clarification_context.transcript)
    
    def set_clarification_resolution(self, resolution: ClarificationResolution) -> None:
        """
        Set resolution status of clarification phase.
        
        This records the outcome but does not trigger mode transition
        or buffer clearing - those are DialogueManager's responsibility.
        
        Args:
            resolution: Resolution outcome
            
        Raises:
            RuntimeError: If clarification context not initialized
            ValueError: If resolution already set
            
        Example:
            state.set_clarification_resolution(ClarificationResolution.CONFIRMED)
        """
        if self.clarification_context is None:
            raise RuntimeError(
                "Cannot set resolution: clarification context not initialized"
            )
        
        if self.clarification_context.resolution_status is not None:
            raise ValueError(
                f"Resolution already set to {self.clarification_context.resolution_status}. "
                "Cannot change resolution once set."
            )
        
        self.clarification_context.resolution_status = resolution
        logger.info(f"Clarification resolution set: {resolution.value}")
    
    # ========================
    # Episode Management
    # ========================
    
    def create_episode(self) -> int:
        """
        Create new episode and return its ID.
        
        Returns:
            int: Episode ID (1-indexed)
            
        Example:
            episode_id = state.create_episode()
            # episode_id = 1
        """
        episode_id = len(self.episodes) + 1
        current_time = datetime.now(timezone.utc).isoformat()
        
        episode = {
            'episode_id': episode_id,
            'timestamp_started': current_time,
            'timestamp_last_updated': current_time,
            'questions_answered': set(),
            'follow_up_blocks_activated': set(),
            'follow_up_blocks_completed': set(),
            # All other fields added dynamically via set_episode_field()
        }
        
        self.episodes.append(episode)
        self.dialogue_history[episode_id] = []
        
        logger.info(f"Created episode {episode_id}")
        return episode_id
    
    def set_episode_field(self, episode_id: int, field_name: str, value: Any) -> None:
        """
        Set a field value for an episode.
        
        No validation is performed on field_name or value - State Manager
        is a dumb container. Validation belongs in Response Parser or
        a dedicated Validator.
        
        Args:
            episode_id: Episode to update (1-indexed)
            field_name: Field to set (e.g., 'vl_laterality')
            value: Value to set
            
        Raises:
            ValueError: If episode_id doesn't exist
            
        Example:
            state.set_episode_field(1, 'vl_laterality', 'right')
            state.set_episode_field(1, 'vl_first_onset', '3 months ago')
        """
        self._validate_episode_id(episode_id)
        
        index = episode_id - 1
        episode = self.episodes[index]
        episode[field_name] = value
        episode['timestamp_last_updated'] = datetime.now(timezone.utc).isoformat()
        
        logger.debug(f"Episode {episode_id}: {field_name} = {value}")
    
    def get_episode(self, episode_id: int) -> Dict[str, Any]:
        """
        Get episode data (deep copy).
        
        Args:
            episode_id: Episode to retrieve (1-indexed)
            
        Returns:
            dict: Episode data (deep copy, safe to modify)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        return self._serialize_episode(self.episodes[episode_id - 1])
    
    def get_episode_field(self, episode_id: int, field_name: str, default: Any = None) -> Any:
        """
        Get a specific field from an episode.
        
        Args:
            episode_id: Episode to query (1-indexed)
            field_name: Field to retrieve
            default: Return value if field doesn't exist
            
        Returns:
            Field value (deep copy) or default
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        value = episode.get(field_name, default)
        return self._deep_copy(value)
    
    def has_episode_field(self, episode_id: int, field_name: str) -> bool:
        """
        Check if episode has a field.
        
        Args:
            episode_id: Episode to check (1-indexed)
            field_name: Field to check
            
        Returns:
            bool: True if field exists
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        return field_name in episode
    
    def list_episode_ids(self) -> List[int]:
        """
        Get list of all episode IDs.
        
        Returns:
            list: Episode IDs (1-indexed)
            
        Example:
            ids = state.list_episode_ids()
            # [1, 2, 3]
        """
        return [ep['episode_id'] for ep in self.episodes]
    
    def get_episode_count(self) -> int:
        """
        Get total number of episodes.
        
        Returns:
            int: Number of episodes
        """
        return len(self.episodes)
    
    # ========================
    # Question Tracking (for Question Selector V2)
    # ========================
    
    def mark_question_answered(self, episode_id: int, question_id: str) -> None:
        """
        Add question_id to episode's questions_answered set.
        
        Args:
            episode_id: Episode to update (1-indexed)
            question_id: Question identifier to mark as answered
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        episode['questions_answered'].add(question_id)
        logger.debug(f"Episode {episode_id}: marked question '{question_id}' as answered")
    
    def get_questions_answered(self, episode_id: int) -> set:
        """
        Get set of answered question IDs for an episode.
        
        Args:
            episode_id: Episode to query (1-indexed)
            
        Returns:
            set[str]: Copy of questions_answered set
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        return episode['questions_answered'].copy()
    
    # ========================
    # Follow-up Block Tracking (for Question Selector V2)
    # ========================
    
    def activate_follow_up_block(self, episode_id: int, block_id: str) -> None:
        """
        Add block_id to episode's follow_up_blocks_activated set.
        
        Args:
            episode_id: Episode to update (1-indexed)
            block_id: Block identifier to activate (e.g., 'block_1')
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        episode['follow_up_blocks_activated'].add(block_id)
        logger.info(f"Episode {episode_id}: activated follow-up block '{block_id}'")
    
    def complete_follow_up_block(self, episode_id: int, block_id: str) -> None:
        """
        Add block_id to episode's follow_up_blocks_completed set.
        
        Args:
            episode_id: Episode to update (1-indexed)
            block_id: Block identifier to mark complete
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        episode['follow_up_blocks_completed'].add(block_id)
        logger.info(f"Episode {episode_id}: completed follow-up block '{block_id}'")
    
    def get_episode_for_selector(self, episode_id: int) -> Dict[str, Any]:
        """
        Get episode data formatted for Question Selector V2.
        
        Returns a dict containing all episode fields including tracking sets
        (questions_answered, follow_up_blocks_activated, follow_up_blocks_completed).
        
        Args:
            episode_id: Episode to retrieve (1-indexed)
            
        Returns:
            dict: Episode data with tracking sets (deep copy, safe to modify)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        return self._serialize_episode(self.episodes[episode_id - 1], exclude_operational=False)
    
    # ========================
    # Shared Data Management
    # ========================
    
    def set_shared_field(self, field_name: str, value: Any) -> None:
        """
        Set a shared data field (flat structure).
        
        V3 Update: Removed dot notation support. All shared fields are now flat
        with prefixes (e.g., 'sh_smoking_status', 'sr_gen_chills').
        
        Args:
            field_name: Flat field name (e.g., 'sh_smoking_status')
            value: Value to set
            
        Example:
            state.set_shared_field('sh_smoking_status', 'former')
            state.set_shared_field('sh_smoking_pack_years', 10)
            state.set_shared_field('sr_gen_chills', True)
        """
        self.shared_data[field_name] = value
        logger.debug(f"Shared data: {field_name} = {value}")
    
    def append_shared_array(self, field_name: str, item: Dict[str, Any]) -> None:
        """
        Append item to shared data array (medications, past_medical_history, etc.).
        
        Args:
            field_name: Array field name (e.g., 'medications', 'allergies')
            item: Item to append (dict with local field names)
            
        Raises:
            TypeError: If field exists but is not a list
            
        Example:
            state.append_shared_array('medications', {
                'name': 'aspirin',
                'dose': '75mg',
                'frequency': 'daily'
            })
            
        Note:
            Item fields use local names ('name', not 'med_name').
            This keeps collection items clean and standard.
        """
        if field_name not in self.shared_data:
            self.shared_data[field_name] = []
        
        if not isinstance(self.shared_data[field_name], list):
            raise TypeError(f"{field_name} is not an array")
        
        self.shared_data[field_name].append(item)
        logger.debug(f"Shared data: appended to {field_name}")
    
    def get_shared_data(self) -> Dict[str, Any]:
        """
        Get all shared data (deep copy).
        
        Returns:
            dict: Shared data (deep copy, safe to modify)
        """
        return self._deep_copy(self.shared_data)
    
    def get_shared_field(self, field_name: str, default: Any = None) -> Any:
        """
        Get a specific shared data field (flat structure).
        
        V3 Update: Removed dot notation support. All shared fields are now flat.
        
        Args:
            field_name: Flat field name (e.g., 'sh_smoking_status')
            default: Return value if field doesn't exist
            
        Returns:
            Field value (deep copy) or default
            
        Example:
            status = state.get_shared_field('sh_smoking_status')
            pack_years = state.get_shared_field('sh_smoking_pack_years', 0)
        """
        value = self.shared_data.get(field_name, default)
        return self._deep_copy(value)
    
    # ========================
    # Dialogue History
    # ========================
    
    def add_dialogue_turn(
        self, 
        episode_id: int,
        question_id: str,
        question_text: str,
        patient_response: str,
        extracted_fields: Dict[str, Any],
        timestamp: Optional[str] = None
    ) -> None:
        """
        Record a dialogue turn for an episode.
        
        Args:
            episode_id: Which episode this turn belongs to
            question_id: Question identifier
            question_text: Question asked
            patient_response: Patient's answer
            extracted_fields: Fields extracted from response
            timestamp: ISO 8601 timestamp (defaults to now if not provided)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        if timestamp is None:
            timestamp = datetime.now(timezone.utc).isoformat()
        
        turn_id = len(self.dialogue_history[episode_id]) + 1
        
        turn = {
            'turn_id': turn_id,
            'timestamp': timestamp,
            'question_id': question_id,
            'question': question_text,
            'response': patient_response,
            'extracted': self._deep_copy(extracted_fields)
        }
        
        self.dialogue_history[episode_id].append(turn)
        logger.debug(f"Episode {episode_id}: recorded dialogue turn {turn_id} (question_id={question_id})")
    
    def get_dialogue_history(self, episode_id: int) -> List[Dict[str, Any]]:
        """
        Get dialogue history for an episode (deep copy).
        
        Args:
            episode_id: Episode to query
            
        Returns:
            list: Dialogue turns (deep copy, safe to modify)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        return self._deep_copy(self.dialogue_history[episode_id])
    
    def get_all_dialogue_history(self) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get dialogue history for all episodes (deep copy).
        
        Returns:
            dict: {episode_id: [dialogue turns]} (deep copy, safe to modify)
        """
        return self._deep_copy(self.dialogue_history)
    
    # ========================
    # Export Methods
    # ========================
    
    def snapshot_state(self) -> Dict[str, Any]:
        """
        Export canonical consultation state (lossless, for persistence)
        
        This is the authoritative representation used for:
        - Transport layer persistence (Flask session, console memory)
        - Round-trip serialization (state Ã¢â€ â€™ snapshot Ã¢â€ â€™ state)
        - V3 provenance and confidence tracking
        
        Properties:
        - Lossless (no filtering)
        - Includes ALL episodes (even empty ones)
        - Includes operational fields (questions_answered, etc.)
        - Includes dialogue history
        - Schema-free (internal representation)
        - Flat structure (no nesting)
        
        Never use this for clinical output - use export_clinical_view() instead.
        
        Returns:
            dict: Complete canonical state {
                'episodes': [...],  # All episodes, with operational fields
                'shared_data': {...},  # Flat structure
                'dialogue_history': {episode_id: [turns]},
                'conversation_mode': 'discovery' | 'clarification' | 'extraction'
            }
        """
        # Serialize ALL episodes with operational fields (lossless)
        serializable_episodes = [
            self._serialize_episode(ep, exclude_operational=False)
            for ep in self.episodes
        ]
        
        # Serialize clarification context if present
        clarification_context_dict = None
        if self.clarification_context is not None:
            clarification_context_dict = self.clarification_context.to_dict()
        
        return {
            'episodes': serializable_episodes,
            'shared_data': self._deep_copy(self.shared_data),
            'dialogue_history': self._deep_copy(self.dialogue_history),
            'conversation_mode': self.conversation_mode,  # V3: Explicit mode tracking
            'clarification_context': clarification_context_dict  # V3: Clarification buffer
        }
    
    @classmethod
    def from_snapshot(cls, snapshot: Dict[str, Any], 
                      data_model_path: str = "data/clinical_data_model.json") -> 'StateManagerV2':
        """
        Rehydrate StateManager from canonical snapshot
        
        This is the ONLY valid way to restore state from persistence.
        Never rehydrate from clinical JSON output.
        
        Args:
            snapshot: Output from snapshot_state()
            data_model_path: Path to clinical data model
            
        Returns:
            StateManagerV2: Fully restored state manager
            
        Raises:
            ValueError: If snapshot is malformed
        """
        # Create fresh StateManager
        state_manager = cls(data_model_path)
        
        # Restore episodes (including empty ones)
        episodes = snapshot.get('episodes', [])
        for episode_data in episodes:
            episode_id = episode_data['episode_id']
            
            # Create episode if needed
            while episode_id > len(state_manager.episodes):
                state_manager.create_episode()
            
            # Restore all fields (including operational)
            episode = state_manager.episodes[episode_id - 1]
            for field_name, value in episode_data.items():
                if field_name == 'episode_id':
                    continue  # Already set by create_episode
                
                # Convert lists back to sets for operational fields
                if field_name in {'questions_answered', 'follow_up_blocks_activated', 
                                 'follow_up_blocks_completed'}:
                    episode[field_name] = set(value) if isinstance(value, list) else value
                else:
                    episode[field_name] = state_manager._deep_copy(value)
        
        # Restore shared data (flat structure)
        shared_data = snapshot.get('shared_data', {})
        state_manager.shared_data = state_manager._deep_copy(shared_data)
        
        # Restore dialogue history
        dialogue_history = snapshot.get('dialogue_history', {})
        # Convert string keys back to int (JSON serialization converts int keys to strings)
        state_manager.dialogue_history = {
            int(ep_id): turns 
            for ep_id, turns in dialogue_history.items()
        }
        
        # Restore conversation mode with validation (V3)
        # Default to 'extraction' for backwards compatibility with pre-V3 snapshots
        mode = snapshot.get('conversation_mode', ConversationMode.MODE_EPISODE_EXTRACTION.value)
        state_manager._validate_conversation_mode(mode)
        state_manager.conversation_mode = mode
        
        # Restore clarification context if present (V3)
        clarification_data = snapshot.get('clarification_context')
        if clarification_data is not None:
            state_manager.clarification_context = ClarificationContext.from_dict(clarification_data)
        
        logger.info(f"Rehydrated StateManager: {len(episodes)} episodes, mode={mode}")
        return state_manager
    
    def export_clinical_view(self) -> Dict[str, Any]:
        """
        Export clinical projection (lossy, for output only)
        
        This is a one-way transformation for clinical output.
        NEVER use this for persistence or rehydration.
        
        Properties:
        - Lossy (filters empty episodes)
        - Excludes operational fields
        - Flat structure (JSON Formatter handles nesting)
        - Strips provenance/confidence (when V3 adds them)
        
        Use snapshot_state() for persistence instead.
        
        Returns:
            dict: Clinical data only {
                'episodes': [...],  # Non-empty only, flat fields
                'shared_data': {...}  # Flat fields
            }
        """
        # Serialize episodes without operational fields
        serializable_episodes = [
            self._serialize_episode(ep, exclude_operational=True)
            for ep in self.episodes
        ]
        
        # Filter empty episodes (only have metadata, no clinical fields)
        metadata_fields = {'episode_id', 'timestamp_started', 'timestamp_last_updated'}
        non_empty_episodes = [
            ep for ep in serializable_episodes
            if set(ep.keys()) - metadata_fields  # Has at least one clinical field
        ]
        
        return {
            'episodes': non_empty_episodes,
            'shared_data': self._deep_copy(self.shared_data)
        }
    
    def export_for_json(self) -> Dict[str, Any]:
        """
        DEPRECATED: Use export_clinical_view() instead
        
        This method delegates to export_clinical_view() for backward compatibility.
        Will be removed in future version.
        """
        logger.warning("export_for_json() is deprecated, use export_clinical_view() instead")
        return self.export_clinical_view()
    
    def export_for_summary(self) -> Dict[str, Any]:
        """
        Export state for summary generator.
        
        Includes operational fields (summary generator may need context
        about what questions were asked).
        
        Returns:
            dict: {
                'episodes': [...],  # Flat fields with operational
                'shared_data': {...},  # Flat fields
                'dialogue_history': {episode_id: [turns]}
            }
        """
        serializable_episodes = [
            self._serialize_episode(ep, exclude_operational=False)
            for ep in self.episodes
        ]
        
        return {
            'episodes': serializable_episodes,
            'shared_data': self._deep_copy(self.shared_data),
            'dialogue_history': self._deep_copy(self.dialogue_history)
        }
    
    # ========================
    # Utility Methods
    # ========================
    
    def reset(self) -> None:
        """
        Clear all state (for starting new consultation).
        
        Warning: This erases all data. Use with caution.
        """
        self.episodes.clear()
        self.shared_data = self._deep_copy(self.data_model["shared_data_template"])
        self.dialogue_history.clear()
        logger.info("State Manager reset - all data cleared")
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics (for debugging/logging).
        
        Returns:
            dict: Summary of current state
        """
        total_fields = sum(len(ep) for ep in self.episodes)
        total_turns = sum(len(turns) for turns in self.dialogue_history.values())
        
        return {
            'total_episodes': len(self.episodes),
            'episode_ids': self.list_episode_ids(),
            'total_fields': total_fields,
            'total_dialogue_turns': total_turns,
            'shared_data_keys': list(self.shared_data.keys())
        }