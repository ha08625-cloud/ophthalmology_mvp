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
# Provenance Constants (V3)
# ========================

# Provenance sources (V3)
SOURCE_RESPONSE_PARSER = 'response_parser'
SOURCE_CLARIFICATION_PARSER = 'clarification_parser'
SOURCE_FORCED_RESOLUTION = 'forced_resolution'
SOURCE_USER_EXPLICIT = 'user_explicit'
SOURCE_DERIVED = 'derived'
SOURCE_REPLAY = 'clarification_replay'
SOURCE_SYSTEM = 'system'
SOURCE_DEFAULT = 'default'

# Valid source values
VALID_SOURCES = {
    SOURCE_RESPONSE_PARSER,
    SOURCE_CLARIFICATION_PARSER,
    SOURCE_FORCED_RESOLUTION,
    SOURCE_USER_EXPLICIT,
    SOURCE_DERIVED,
    SOURCE_REPLAY,
    SOURCE_SYSTEM,
    SOURCE_DEFAULT
}


class ProvenanceConfidence(str, Enum):
    """
    Confidence bands for field provenance.
    
    These are qualitative bands, not calibrated probabilities.
    
    Values:
        HIGH: High confidence extraction/resolution
        MEDIUM: Medium confidence extraction/resolution
        LOW: Low confidence or default provenance
    """
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'


# Valid confidence values
VALID_CONFIDENCES = {pc.value for pc in ProvenanceConfidence}

# Confidence ordering for weakest-link logic (V3)
# Used to degrade confidence on collection updates
CONFIDENCE_ORDER = {
    'low': 0,
    'medium': 1,
    'high': 2
}

# Provenance record schema (V3)
# CRITICAL: 'mode' stores ConversationMode enum value directly, not string.
# This matches conversation_mode field and prevents type drift.
#
# Schema:
# {
#     'source': str (one of VALID_SOURCES),
#     'confidence': str (one of VALID_CONFIDENCES),
#     'mode': ConversationMode (enum value, not .value string)
# }
#
# Provenance semantics:
# - Last-writer-wins: Each field write overwrites provenance completely
# - No history: Previous provenance is discarded
# - Write-once per call: Cannot write provenance without value
# - Weakest-link: Collection updates degrade confidence (never improve)
ProvenanceRecord = Dict[str, Any]  # Mixed types: str for source/confidence, enum for mode

# V3: Collection fields for weakest-link confidence logic
# MUST match collection_schemas in clinical_data_model.json
# TODO: Auto-detect from data model in future version
COLLECTION_FIELDS = {'medications', 'allergies', 'past_medical_history', 'family_history'}


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
        rendered_text: The actual question text shown to user (with placeholders filled).
            Optional for backward compatibility with pre-V3.1 snapshots.
            If None, replay adapter will fail loudly if replay is attempted.
    """
    template_id: str
    user_text: str
    replayable: bool
    rendered_text: Optional[str] = None
    
    def __post_init__(self):
        """Validate fields after initialization"""
        if not self.user_text or not self.user_text.strip():
            raise ValueError("user_text cannot be empty")
        # Note: rendered_text can be None for backward compatibility
        # Replay adapter validates rendered_text presence when needed
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for serialization"""
        return {
            'template_id': self.template_id,
            'user_text': self.user_text,
            'replayable': self.replayable,
            'rendered_text': self.rendered_text
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ClarificationTurn':
        """
        Create ClarificationTurn from dict.
        
        Backward compatible: handles snapshots without rendered_text field.
        If rendered_text is missing, sets to None. Replay adapter will
        fail loudly if replay is attempted on such turns.
        
        Args:
            data: Dict with template_id, user_text, replayable, and optionally rendered_text
            
        Returns:
            ClarificationTurn instance
        """
        return cls(
            template_id=data['template_id'],
            user_text=data['user_text'],
            replayable=data['replayable'],
            rendered_text=data.get('rendered_text')  # None if missing (backward compat)
        )


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
        """
        Reconstruct from dict.
        
        Backward compatible: delegates to ClarificationTurn.from_dict()
        which handles missing rendered_text field gracefully.
        
        Args:
            data: Dict with transcript, entry_count, resolution_status
            
        Returns:
            ClarificationContext instance
        """
        transcript = [
            ClarificationTurn.from_dict(turn_data)
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
    # V3: _provenance is handled separately via exclude_provenance parameter
    # in _serialize_episode() and _serialize_shared_data().
    #
    # Exclusion behavior by method:
    # - export_clinical_view(): EXCLUDES operational + provenance
    # - export_for_summary(): INCLUDES operational + filtered provenance (source, confidence only)
    # - get_episode_for_selector(): INCLUDES operational, INCLUDES full provenance
    # - get_episode(): INCLUDES operational, INCLUDES full provenance
    # - snapshot_state(): INCLUDES operational, INCLUDES full provenance
    OPERATIONAL_FIELDS = {
        'questions_answered',
        'questions_satisfied',
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
        self.shared_data['_provenance'] = {}  # V3: Field-level provenance tracking
        self.dialogue_history: Dict[int, List[Dict[str, Any]]] = {}
        
        # Clarification context (only exists during MODE_CLARIFICATION)
        self.clarification_context: Optional[ClarificationContext] = None
        
        # V3: Conversation mode (enum, not string)
        # CRITICAL: Store enum directly for type consistency with provenance.
        # This default is overridden by from_snapshot() during rehydration.
        # Only applies to fresh StateManager instances created by DialogueManager._handle_start()
        # Do not rely on this default for persistence logic.
        self.conversation_mode = ConversationMode.MODE_DISCOVERY  # Not .value

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
    
    def _validate_conversation_mode(self, mode) -> None:
        """
        Validate conversation mode value.
        
        V3: Accepts both ConversationMode enum and string for backwards compatibility.
        Prefer enum for internal use; string accepted for migration period.
        
        This is data integrity validation, not business logic.
        StateManager cannot derive or repair mode - it only validates
        that the mode value is recognized.
        
        DialogueManager owns all mode transition logic.
        
        Args:
            mode: ConversationMode enum or string value
            
        Raises:
            ValueError: If mode is invalid
            
        Example:
            # Enum (preferred, V3)
            self._validate_conversation_mode(ConversationMode.MODE_DISCOVERY)
            
            # String (backwards compat)
            self._validate_conversation_mode("discovery")
            
            # Invalid - will raise
            self._validate_conversation_mode("invalid")  # ValueError
            self._validate_conversation_mode(None)  # ValueError
        """
        # Accept enum directly (V3)
        if isinstance(mode, ConversationMode):
            return
        
        # Accept string for backwards compat
        if mode not in VALID_MODES:
            raise ValueError(
                f"Invalid conversation_mode: '{mode}'. "
                f"Must be one of {VALID_MODES} or ConversationMode enum"
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
    
    # ========================
    # Provenance Helpers (V3)
    # ========================
    
    def _validate_provenance(self, provenance: Optional[Dict[str, Any]]) -> None:
        """
        Validate provenance dict structure.
        
        Args:
            provenance: Provenance dict to validate
            
        Raises:
            ValueError: If provenance invalid
            TypeError: If mode not ConversationMode enum
        """
        if provenance is None:
            return
        
        if not isinstance(provenance, dict):
            raise ValueError("Provenance must be dict or None")
        
        # Check required keys
        required_keys = {'source', 'confidence', 'mode'}
        missing = required_keys - provenance.keys()
        if missing:
            raise ValueError(f"Provenance missing required keys: {missing}")
        
        # Validate source
        if provenance['source'] not in VALID_SOURCES:
            raise ValueError(
                f"Invalid provenance source: {provenance['source']}. "
                f"Must be one of {VALID_SOURCES}"
            )
        
        # Validate confidence
        if provenance['confidence'] not in VALID_CONFIDENCES:
            raise ValueError(
                f"Invalid provenance confidence: {provenance['confidence']}. "
                f"Must be one of {VALID_CONFIDENCES}"
            )
        
        # Validate mode (must be ConversationMode enum, not string)
        if not isinstance(provenance['mode'], ConversationMode):
            raise TypeError(
                f"Invalid provenance mode type: {type(provenance['mode'])}. "
                f"Must be ConversationMode enum, not string. "
                f"Use ConversationMode.MODE_EPISODE_EXTRACTION, not 'extraction'."
            )
    
    def _default_provenance(self) -> ProvenanceRecord:
        """
        Generate default provenance for legacy writes.
        
        Returns:
            dict: Default provenance record with enum mode
        """
        return {
            'source': SOURCE_DEFAULT,
            'confidence': ProvenanceConfidence.LOW.value,
            'mode': self.conversation_mode  # Already a ConversationMode enum
        }
    
    def _apply_weakest_link_confidence(
        self,
        existing_provenance: Optional[ProvenanceRecord],
        new_provenance: ProvenanceRecord
    ) -> ProvenanceRecord:
        """
        Apply weakest-link confidence degradation for collection updates.
        
        When updating a collection field that already has provenance,
        confidence must never improve, only degrade.
        
        Args:
            existing_provenance: Current provenance (None if first write)
            new_provenance: New provenance being applied
            
        Returns:
            dict: New provenance with degraded confidence if applicable
        """
        if existing_provenance is None:
            # First write - no degradation
            return new_provenance
        
        old_conf = existing_provenance['confidence']
        new_conf = new_provenance['confidence']
        
        # Take lower confidence
        if CONFIDENCE_ORDER[old_conf] < CONFIDENCE_ORDER[new_conf]:
            degraded = self._deep_copy(new_provenance)
            degraded['confidence'] = old_conf
            logger.debug(
                f"Degraded confidence from {new_conf} to {old_conf} "
                f"(weakest-link for collection update)"
            )
            return degraded
        
        return new_provenance
    
    def _store_provenance(
        self,
        provenance_dict: Dict[str, ProvenanceRecord],
        field_name: str,
        provenance: Optional[ProvenanceRecord],
        is_collection: bool = False
    ) -> None:
        """
        Store provenance for a field.
        
        V3 Invariants:
        - Provenance is last-writer-wins (no history)
        - Cannot write provenance without value (enforced by API)
        - Collection fields apply weakest-link confidence degradation
        
        Args:
            provenance_dict: Target _provenance dict (episode or shared)
            field_name: Field being written
            provenance: Provenance record or None (use default)
            is_collection: Whether field is a collection (weakest-link applies)
        """
        if provenance is None:
            provenance = self._default_provenance()
        else:
            self._validate_provenance(provenance)
        
        # Apply weakest-link for collections
        if is_collection:
            existing = provenance_dict.get(field_name)
            provenance = self._apply_weakest_link_confidence(existing, provenance)
        
        # Store (overwrites existing - last-writer-wins)
        provenance_dict[field_name] = self._deep_copy(provenance)
        logger.debug(f"Stored provenance for {field_name}: {provenance}")
    
    # ========================
    # Serialization Helpers
    # ========================
    
    def _serialize_episode(
        self,
        episode: Dict[str, Any],
        exclude_operational: bool = False,
        exclude_provenance: bool = False,  # V3: New parameter
        serialize_provenance: bool = True  # V3: Convert enum to string for JSON
    ) -> Dict[str, Any]:
        """
        Create a serializable deep copy of an episode.
        
        V3: Added exclude_provenance and serialize_provenance parameters.
        Handles ConversationMode enum serialization in provenance.
        
        Converts sets to sorted lists for JSON compatibility.
        Optionally excludes operational fields and/or provenance.
        
        Args:
            episode: Episode dict to serialize
            exclude_operational: If True, exclude OPERATIONAL_FIELDS
            exclude_provenance: If True, exclude _provenance dict (V3)
            serialize_provenance: If True, convert enum mode to string for JSON (V3)
            
        Returns:
            Dict with sets converted to sorted lists, all values deep copied
        """
        result = {}
        for key, value in episode.items():
            # Skip operational fields if requested
            if exclude_operational and key in self.OPERATIONAL_FIELDS:
                continue
            
            # V3: Skip provenance if requested
            if exclude_provenance and key == '_provenance':
                continue
            
            # V3: Serialize provenance dict (handle enum mode)
            if key == '_provenance' and isinstance(value, dict):
                if serialize_provenance:
                    result[key] = self._serialize_provenance_dict(value)
                else:
                    # Deep copy but keep enum
                    result[key] = self._deep_copy(value)
                continue
            
            # Convert sets to sorted lists, deep copy everything else
            if isinstance(value, set):
                result[key] = sorted(list(value))
            else:
                result[key] = self._deep_copy(value)
        
        return result
    
    def _serialize_provenance_dict(self, provenance_dict: Dict[str, ProvenanceRecord]) -> Dict[str, Dict[str, Any]]:
        """
        Serialize provenance dict with enum mode conversion.
        
        Converts ConversationMode enum to string for JSON serialization.
        
        Args:
            provenance_dict: Raw _provenance dict
            
        Returns:
            dict: Serialized provenance with mode as string
        """
        serialized = {}
        for field_name, prov_record in provenance_dict.items():
            serialized[field_name] = {
                'source': prov_record['source'],
                'confidence': prov_record['confidence'],
                'mode': prov_record['mode'].value  # Enum -> string for JSON
            }
        return serialized
    
    def _deserialize_provenance_dict(self, provenance_dict: Dict[str, Dict[str, Any]]) -> Dict[str, ProvenanceRecord]:
        """
        Deserialize provenance dict with string mode conversion.
        
        Converts mode string back to ConversationMode enum.
        
        Args:
            provenance_dict: Serialized _provenance dict (mode as string)
            
        Returns:
            dict: Provenance with mode as ConversationMode enum
        """
        deserialized = {}
        for field_name, prov_record in provenance_dict.items():
            deserialized[field_name] = {
                'source': prov_record['source'],
                'confidence': prov_record['confidence'],
                'mode': ConversationMode(prov_record['mode'])  # String -> enum
            }
        return deserialized
    
    def _serialize_shared_data(self, exclude_provenance: bool = False) -> Dict[str, Any]:
        """
        Serialize shared_data with optional provenance filtering.
        
        V3: Added exclude_provenance parameter for clinical exports.
        Handles ConversationMode enum serialization in provenance.
        
        Args:
            exclude_provenance: Strip _provenance dict
            
        Returns:
            dict: Serialized shared_data
        """
        serialized = self._deep_copy(self.shared_data)
        
        if exclude_provenance and '_provenance' in serialized:
            del serialized['_provenance']
        elif '_provenance' in serialized:
            # Serialize provenance dict (handle enum mode)
            serialized['_provenance'] = self._serialize_provenance_dict(serialized['_provenance'])
        
        return serialized
    
    def _filter_provenance_for_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Filter provenance for summary generator.
        
        V3: Summary gets source + confidence only (no mode).
        
        CRITICAL: Deep-copies input before mutation to prevent contaminating
        other consumers in the call stack.
        
        Args:
            data: Episode or shared_data dict with _provenance
            
        Returns:
            dict: Deep-copied data with filtered _provenance
        """
        # CRITICAL: Deep-copy before mutation
        data = self._deep_copy(data)
        
        if '_provenance' not in data:
            return data
        
        filtered_provenance = {}
        for field_name, prov_record in data['_provenance'].items():
            # Strip 'mode', keep 'source' and 'confidence'
            filtered_provenance[field_name] = {
                'source': prov_record['source'],
                'confidence': prov_record['confidence']
            }
        
        data['_provenance'] = filtered_provenance
        return data
    
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
            'questions_satisfied': set(),
            'follow_up_blocks_activated': set(),
            'follow_up_blocks_completed': set(),
            '_provenance': {},  # V3: Field-level provenance tracking
            # All other fields added dynamically via set_episode_field()
        }
        
        self.episodes.append(episode)
        self.dialogue_history[episode_id] = []
        
        logger.info(f"Created episode {episode_id}")
        return episode_id
    
    def set_episode_field(
        self,
        episode_id: int,
        field_name: str,
        value: Any,
        provenance: Optional[ProvenanceRecord] = None
    ) -> None:
        """
        Set field value in episode with optional provenance.
        
        V3: Provenance is optional. If not provided, default provenance is applied.
        
        No validation is performed on field_name or value - State Manager
        is a dumb container. Validation belongs in Response Parser or
        a dedicated Validator.
        
        Provenance Semantics (V3):
        - Last-writer-wins: Overwrites existing provenance completely
        - No history: Previous provenance is discarded
        - Cannot write provenance without value (no separate set_provenance API)
        
        Args:
            episode_id: Episode to update (1-indexed)
            field_name: Field to set (e.g., 'vl_laterality')
            value: Value to set
            provenance: Optional provenance record {source, confidence, mode}
                - source: str (one of VALID_SOURCES)
                - confidence: str ('high'|'medium'|'low')
                - mode: ConversationMode enum (NOT string)
                If None, defaults to {SOURCE_DEFAULT, confidence=LOW, mode=current_mode}
            
        Raises:
            ValueError: If episode_id doesn't exist or provenance invalid
            TypeError: If provenance mode not ConversationMode enum
            
        Example:
            # Legacy call (default provenance applied)
            state.set_episode_field(1, 'vl_laterality', 'right')
            
            # Explicit provenance (V3)
            state.set_episode_field(
                1, 'vl_laterality', 'right',
                provenance={
                    'source': SOURCE_RESPONSE_PARSER,
                    'confidence': 'high',
                    'mode': ConversationMode.MODE_EPISODE_EXTRACTION  # Enum, not string
                }
            )
        """
        self._validate_episode_id(episode_id)
        
        index = episode_id - 1
        episode = self.episodes[index]
        
        # Write value (provenance cannot exist without value)
        episode[field_name] = value
        episode['timestamp_last_updated'] = datetime.now(timezone.utc).isoformat()
        
        # Store provenance (episode fields are not collections)
        self._store_provenance(episode['_provenance'], field_name, provenance, is_collection=False)
        
        logger.debug(f"Episode {episode_id}: {field_name} = {value}")
    
    def get_episode(self, episode_id: int) -> Dict[str, Any]:
        """
        Get episode data (deep copy).
        
        V3: Returns internal representation with enum mode in provenance.
        Use snapshot_state() for JSON-serializable output.
        
        Args:
            episode_id: Episode to retrieve (1-indexed)
            
        Returns:
            dict: Episode data (deep copy, safe to modify)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        # V3: serialize_provenance=False keeps enum mode (internal representation)
        return self._serialize_episode(self.episodes[episode_id - 1], serialize_provenance=False)
    
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
    
    def mark_question_satisfied(self, episode_id: int, question_id: str) -> None:
        """
        Mark question as satisfied (data obtained, whether asked or volunteered).
        
        A question is satisfied when we have data for its primary field,
        regardless of whether we explicitly asked that question.
        
        Semantic distinction:
        - questions_answered: We explicitly asked this question
        - questions_satisfied: We have data for this question's intent
        
        Relationship: questions_answered âŠ† questions_satisfied
        
        Args:
            episode_id: Episode to update (1-indexed)
            question_id: Question identifier to mark as satisfied
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        episode['questions_satisfied'].add(question_id)
        logger.debug(f"Episode {episode_id}: marked question '{question_id}' as satisfied")
    
    def get_questions_satisfied(self, episode_id: int) -> set:
        """
        Get set of satisfied question IDs for an episode.
        
        Args:
            episode_id: Episode to query (1-indexed)
            
        Returns:
            set[str]: Copy of questions_satisfied set
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        
        episode = self.episodes[episode_id - 1]
        return episode['questions_satisfied'].copy()
    
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
        
        V3: Returns internal representation with enum mode in provenance.
        
        Returns a dict containing all episode fields including tracking sets
        (questions_answered, questions_satisfied, follow_up_blocks_activated, 
        follow_up_blocks_completed).
        
        Args:
            episode_id: Episode to retrieve (1-indexed)
            
        Returns:
            dict: Episode data with tracking sets (deep copy, safe to modify)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        self._validate_episode_id(episode_id)
        # V3: serialize_provenance=False keeps enum mode (internal representation)
        return self._serialize_episode(self.episodes[episode_id - 1], exclude_operational=False, serialize_provenance=False)
    
    # ========================
    # Shared Data Management
    # ========================
    
    def set_shared_field(
        self,
        field_name: str,
        value: Any,
        provenance: Optional[ProvenanceRecord] = None
    ) -> None:
        """
        Set field value in shared data with optional provenance.
        
        V3: Provenance is optional. If not provided, default provenance is applied.
        V3 Update: Removed dot notation support. All shared fields are now flat
        with prefixes (e.g., 'sh_smoking_status', 'sr_gen_chills').
        
        Collection Invariants (V3):
        - Whole-array replacement only (no mutation, append, delete)
        - Single provenance entry per collection field
        - Confidence reflects weakest link (degrades on update, never improves)
        - Forced resolution applies to entire collection
        
        Provenance Semantics (V3):
        - Last-writer-wins: Overwrites existing provenance completely
        - No history: Previous provenance is discarded
        - Cannot write provenance without value (no separate set_provenance API)
        - Collections apply weakest-link confidence degradation
        
        Args:
            field_name: Flat field name (e.g., 'sh_smoking_status', 'medications')
            value: Value to set
            provenance: Optional provenance record {source, confidence, mode}
                - source: str (one of VALID_SOURCES)
                - confidence: str ('high'|'medium'|'low')
                - mode: ConversationMode enum (NOT string)
                If None, defaults to {SOURCE_DEFAULT, confidence=LOW, mode=current_mode}
            
        Raises:
            ValueError: If provenance invalid
            TypeError: If provenance mode not ConversationMode enum
            
        Example:
            # Legacy call (default provenance applied)
            state.set_shared_field('medications', [...])
            
            # Explicit provenance (V3)
            state.set_shared_field(
                'medications', [...],
                provenance={
                    'source': SOURCE_RESPONSE_PARSER,
                    'confidence': 'high',
                    'mode': ConversationMode.MODE_EPISODE_EXTRACTION  # Enum, not string
                }
            )
        """
        # Write value (provenance cannot exist without value)
        self.shared_data[field_name] = value
        
        # Determine if this is a collection field (weakest-link applies)
        is_collection = field_name in COLLECTION_FIELDS
        
        # Store provenance with weakest-link for collections
        self._store_provenance(
            self.shared_data['_provenance'], 
            field_name, 
            provenance, 
            is_collection=is_collection
        )
        
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
        - Round-trip serialization (state ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ snapshot ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â‚¬Å¾Ã‚Â¢ state)
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
            'shared_data': self._serialize_shared_data(exclude_provenance=False),  # V3: Include provenance
            'dialogue_history': self._deep_copy(self.dialogue_history),
            'conversation_mode': self.conversation_mode.value,  # V3: Serialize enum to string
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
            
            # Restore all fields (including operational and provenance)
            episode = state_manager.episodes[episode_id - 1]
            for field_name, value in episode_data.items():
                if field_name == 'episode_id':
                    continue  # Already set by create_episode
                
                # V3: Deserialize provenance dict (convert mode string to enum)
                if field_name == '_provenance' and isinstance(value, dict):
                    episode[field_name] = state_manager._deserialize_provenance_dict(value)
                    continue
                
                # Convert lists back to sets for operational fields
                if field_name in {'questions_answered', 'questions_satisfied',
                                 'follow_up_blocks_activated', 
                                 'follow_up_blocks_completed'}:
                    episode[field_name] = set(value) if isinstance(value, list) else value
                else:
                    episode[field_name] = state_manager._deep_copy(value)
            
            # Backward compatibility: Hydrate questions_satisfied if missing from snapshot
            # Rule: questions_satisfied = questions_answered for old sessions
            # Check if it was in the original snapshot data (not just if key exists now)
            if 'questions_satisfied' not in episode_data:
                episode['questions_satisfied'] = set(episode.get('questions_answered', set()))
                logger.debug(f"Episode {episode_id}: hydrated questions_satisfied from questions_answered (backward compatibility)")
        
        # Restore shared data (flat structure)
        shared_data = snapshot.get('shared_data', {})
        state_manager.shared_data = state_manager._deep_copy(shared_data)
        
        # V3: Deserialize provenance if present
        if '_provenance' in state_manager.shared_data:
            state_manager.shared_data['_provenance'] = state_manager._deserialize_provenance_dict(
                state_manager.shared_data['_provenance']
            )
        
        # Restore dialogue history
        dialogue_history = snapshot.get('dialogue_history', {})
        # Convert string keys back to int (JSON serialization converts int keys to strings)
        state_manager.dialogue_history = {
            int(ep_id): turns 
            for ep_id, turns in dialogue_history.items()
        }
        
        # Restore conversation mode with validation (V3)
        # Default to MODE_EPISODE_EXTRACTION for backwards compatibility with pre-V3 snapshots
        # Accept both enum and string for migration period
        mode = snapshot.get('conversation_mode', ConversationMode.MODE_EPISODE_EXTRACTION.value)
        state_manager._validate_conversation_mode(mode)
        
        # V3: Store as enum if string provided (migration path)
        if isinstance(mode, str):
            state_manager.conversation_mode = ConversationMode(mode)
        else:
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
        - Excludes provenance (V3)
        - Flat structure (JSON Formatter handles nesting)
        
        Use snapshot_state() for persistence instead.
        
        Returns:
            dict: Clinical data only {
                'episodes': [...],  # Non-empty only, flat fields, no provenance
                'shared_data': {...}  # Flat fields, no provenance
            }
        """
        # V3: Strip operational AND provenance for clinical output
        serializable_episodes = [
            self._serialize_episode(ep, exclude_operational=True, exclude_provenance=True)
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
            'shared_data': self._serialize_shared_data(exclude_provenance=True)  # V3: Strip provenance
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
        
        V3: Includes operational fields and filtered provenance (source + confidence only).
        
        Includes operational fields (summary generator may need context
        about what questions were asked).
        
        Returns:
            dict: {
                'episodes': [...],  # Flat fields with operational, filtered provenance
                'shared_data': {...},  # Flat fields, filtered provenance
                'dialogue_history': {episode_id: [turns]}
            }
        """
        # V3: Include provenance but filter mode field
        serializable_episodes = [
            self._filter_provenance_for_summary(
                self._serialize_episode(ep, exclude_operational=False)
            )
            for ep in self.episodes
        ]
        
        return {
            'episodes': serializable_episodes,
            'shared_data': self._filter_provenance_for_summary(
                self._serialize_shared_data(exclude_provenance=False)
            ),
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
