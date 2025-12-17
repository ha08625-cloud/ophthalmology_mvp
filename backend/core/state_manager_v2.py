"""
State Manager V2 - Multi-episode consultation state management

Responsibilities:
- Store multiple episodes (array of episode objects)
- Store shared data (PMH, medications, FH, SH)
- Store dialogue history per episode
- Minimal API - pure data storage, no business logic

Design principles:
- Episodes as array (not dict) - preserves temporal order
- Flat field structure within episodes (maintains compatibility)
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

logger = logging.getLogger(__name__)


class StateManagerV2:
    """Manages multi-episode consultation state"""
    
    # Operational fields excluded from clinical JSON export.
    # 
    # These fields are used internally for tracking conversation state
    # but are NOT clinical data and should not appear in final JSON output.
    #
    # Exclusion behavior by method:
    # - export_for_json(): EXCLUDES these fields (clinical output only)
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
    
    def route_and_store_fields(self, episode_id: int, extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route extracted fields to episode or shared storage (ROUTING AUTHORITY)
        
        This method owns field routing logic. DialogueManager must not
        call classify_field or set_episode_field/set_shared_field directly.
        
        Args:
            episode_id: Current episode (1-indexed)
            extracted_fields: Fields from Response Parser
            
        Returns:
            dict: Unmapped fields (unknown classification)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        from backend.utils.episode_classifier import classify_field
        
        self._validate_episode_id(episode_id)
        unmapped = {}
        
        for field_name, value in extracted_fields.items():
            # Skip internal metadata fields
            if field_name.startswith('_'):
                continue
            
            # Classify field (State Manager authority)
            classification = classify_field(field_name)
            
            if classification == 'episode':
                # Route to episode storage
                try:
                    self.set_episode_field(episode_id, field_name, value)
                    logger.debug(f"Episode {episode_id}: routed {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to store episode field {field_name}: {e}")
                    unmapped[field_name] = value
                    
            elif classification == 'shared':
                # Route to shared storage
                try:
                    self.set_shared_field(field_name, value)
                    logger.debug(f"Shared data: routed {field_name} = {value}")
                except Exception as e:
                    logger.error(f"Failed to store shared field {field_name}: {e}")
                    unmapped[field_name] = value
                    
            else:  # 'unknown'
                # Quarantine unmapped fields
                unmapped[field_name] = value
                logger.warning(
                    f"Unmapped field: {field_name} = {value} "
                    f"(episode_id={episode_id}, classification={classification})"
                )
        
        return unmapped
    
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
        Set a shared data field (supports nested paths with dot notation).
        
        Args:
            field_name: Field to set (supports dot notation for nesting)
            value: Value to set
            
        Example:
            state.set_shared_field('social_history.smoking.status', 'former')
            state.set_shared_field('social_history.smoking.pack_years', 10)
        """
        if '.' in field_name:
            parts = field_name.split('.')
            
            # Navigate to the parent container
            container = self.shared_data
            for part in parts[:-1]:
                if part not in container:
                    container[part] = {}
                container = container[part]
            
            # Set the final value
            container[parts[-1]] = value
        else:
            self.shared_data[field_name] = value
        
        logger.debug(f"Shared data: {field_name} = {value}")
    
    def append_shared_array(self, field_name: str, item: Dict[str, Any]) -> None:
        """
        Append item to shared data array (PMH, medications, FH, allergies).
        
        Args:
            field_name: Array field name
            item: Item to append
            
        Raises:
            TypeError: If field exists but is not a list
            
        Example:
            state.append_shared_array('medications', {
                'medication_name': 'aspirin',
                'dose': '75mg',
                'frequency': 'daily'
            })
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
        Get a specific shared data field (supports nested paths with dot notation).
        
        Args:
            field_name: Field to retrieve (supports dot notation for nesting)
            default: Return value if field doesn't exist
            
        Returns:
            Field value (deep copy) or default
            
        Example:
            status = state.get_shared_field('social_history.smoking.status')
            pack_years = state.get_shared_field('social_history.smoking.pack_years', 0)
        """
        if '.' in field_name:
            parts = field_name.split('.')
            
            # Navigate through the nested structure
            container = self.shared_data
            for part in parts[:-1]:
                if part not in container or not isinstance(container[part], dict):
                    return default
                container = container[part]
            
            value = container.get(parts[-1], default)
        else:
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
    
    def export_for_json(self) -> Dict[str, Any]:
        """
        Export complete state for JSON formatter (clinical data only).
        
        Returns:
            dict: {
                'episodes': [...],
                'shared_data': {...}
            }
            
        Note: 
            - Does NOT include current_episode_id (UI state)
            - Excludes operational fields (questions_answered, follow_up_blocks_*)
            - Excludes empty episodes (no clinical fields set)
            - Converts sets to sorted lists for JSON serialization
        """
        # Serialize episodes, excluding operational fields
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
    
    def export_for_summary(self) -> Dict[str, Any]:
        """
        Export state for summary generator.
        
        Includes operational fields (summary generator may need context
        about what questions were asked).
        
        Returns:
            dict: {
                'episodes': [...],
                'shared_data': {...},
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