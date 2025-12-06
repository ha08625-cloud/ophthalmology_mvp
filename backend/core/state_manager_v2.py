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

API Philosophy:
- State Manager = dumb data container
- Dialogue Manager = smart coordinator (tracks current episode)
- Question Selector = medical protocol logic
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class StateManagerV2:
    """Manages multi-episode consultation state"""
    
    def __init__(self):
        """Initialize empty multi-episode state"""
        self.episodes = []  # List of episode dicts
        self.shared_data = {
            'past_medical_history': [],
            'medications': [],
            'family_history': [],
            'social_history': {}
        }
        self.dialogue_history = {}  # episode_id -> list of dialogue turns
        
        logger.info("State Manager V2 initialized (multi-episode)")
    
    # ========================
    # Episode Management
    # ========================
    
    def create_episode(self, symptom_type: str = "visual_loss") -> int:
        """
        Create new episode and return its ID
        
        Args:
            symptom_type: Primary symptom category (convenience field)
            
        Returns:
            int: Episode ID (1-indexed)
            
        Example:
            episode_id = state.create_episode("visual_loss")
            # episode_id = 1
        """
        episode_id = len(self.episodes) + 1
        
        episode = {
            'episode_id': episode_id,
            'symptom_type': symptom_type,
            'currently_active': True,  # Default to active
            'completely_resolved': False,  # Default to unresolved
            # All other fields added dynamically via set_episode_field()
        }
        
        self.episodes.append(episode)
        self.dialogue_history[episode_id] = []
        
        logger.info(f"Created episode {episode_id} (symptom_type={symptom_type})")
        return episode_id
    
    def set_episode_field(self, episode_id: int, field_name: str, value: Any) -> None:
        """
        Set a field value for an episode
        
        Args:
            episode_id: Episode to update (1-indexed)
            field_name: Field to set (e.g., 'vl_laterality')
            value: Value to set
            
        Raises:
            ValueError: If episode_id doesn't exist
            
        Example:
            state.set_episode_field(1, 'vl_laterality', 'monocular_right')
            state.set_episode_field(1, 'vl_first_onset', '3 months ago')
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist (valid range: 1-{len(self.episodes)})")
        
        # Episodes are 1-indexed, list is 0-indexed
        episode = self.episodes[episode_id - 1]
        episode[field_name] = value
        
        logger.debug(f"Episode {episode_id}: {field_name} = {value}")
    
    def get_episode(self, episode_id: int) -> Dict[str, Any]:
        """
        Get episode data
        
        Args:
            episode_id: Episode to retrieve (1-indexed)
            
        Returns:
            dict: Episode data (copy, not reference)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist (valid range: 1-{len(self.episodes)})")
        
        return self.episodes[episode_id - 1].copy()
    
    def get_episode_field(self, episode_id: int, field_name: str, default: Any = None) -> Any:
        """
        Get a specific field from an episode
        
        Args:
            episode_id: Episode to query (1-indexed)
            field_name: Field to retrieve
            default: Return value if field doesn't exist
            
        Returns:
            Field value or default
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist (valid range: 1-{len(self.episodes)})")
        
        episode = self.episodes[episode_id - 1]
        return episode.get(field_name, default)
    
    def has_episode_field(self, episode_id: int, field_name: str) -> bool:
        """
        Check if episode has a field
        
        Args:
            episode_id: Episode to check (1-indexed)
            field_name: Field to check
            
        Returns:
            bool: True if field exists
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist (valid range: 1-{len(self.episodes)})")
        
        episode = self.episodes[episode_id - 1]
        return field_name in episode
    
    def list_episode_ids(self) -> List[int]:
        """
        Get list of all episode IDs
        
        Returns:
            list: Episode IDs (1-indexed)
            
        Example:
            ids = state.list_episode_ids()
            # [1, 2, 3]
        """
        return [ep['episode_id'] for ep in self.episodes]
    
    def get_episode_count(self) -> int:
        """
        Get total number of episodes
        
        Returns:
            int: Number of episodes
        """
        return len(self.episodes)
    
    # ========================
    # Shared Data Management
    # ========================
    
    def set_shared_field(self, field_name: str, value: Any) -> None:
        """
        Set a shared data field
        
        Args:
            field_name: Field to set
            value: Value to set
            
        Example:
            state.set_shared_field('smoking_status', 'never')
            state.set_shared_field('occupation', 'teacher')
        """
        # Handle nested paths (e.g., 'social_history.smoking_status')
        if '.' in field_name:
            parts = field_name.split('.')
            container = parts[0]
            subfield = parts[1]
            
            if container not in self.shared_data:
                self.shared_data[container] = {}
            
            self.shared_data[container][subfield] = value
            logger.debug(f"Shared data: {container}.{subfield} = {value}")
        else:
            self.shared_data[field_name] = value
            logger.debug(f"Shared data: {field_name} = {value}")
    
    def append_shared_array(self, field_name: str, item: Dict[str, Any]) -> None:
        """
        Append item to shared data array (PMH, medications, FH)
        
        Args:
            field_name: Array field name
            item: Item to append
            
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
        Get all shared data
        
        Returns:
            dict: Shared data (copy, not reference)
        """
        return self.shared_data.copy()
    
    def get_shared_field(self, field_name: str, default: Any = None) -> Any:
        """
        Get a specific shared data field
        
        Args:
            field_name: Field to retrieve
            default: Return value if field doesn't exist
            
        Returns:
            Field value or default
        """
        # Handle nested paths
        if '.' in field_name:
            parts = field_name.split('.')
            container = parts[0]
            subfield = parts[1]
            
            if container not in self.shared_data:
                return default
            
            if not isinstance(self.shared_data[container], dict):
                return default
            
            return self.shared_data[container].get(subfield, default)
        
        return self.shared_data.get(field_name, default)
    
    # ========================
    # Dialogue History
    # ========================
    
    def add_dialogue_turn(
        self, 
        episode_id: int,
        question_id: str,
        question_text: str,
        patient_response: str,
        extracted_fields: Dict[str, Any]
    ) -> None:
        """
        Record a dialogue turn for an episode
        
        Args:
            episode_id: Which episode this turn belongs to
            question_id: Question identifier
            question_text: Question asked
            patient_response: Patient's answer
            extracted_fields: Fields extracted from response
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist")
        
        turn = {
            'question_id': question_id,
            'question': question_text,
            'response': patient_response,
            'extracted': extracted_fields
        }
        
        self.dialogue_history[episode_id].append(turn)
        logger.debug(f"Episode {episode_id}: recorded dialogue turn (question_id={question_id})")
    
    def get_dialogue_history(self, episode_id: int) -> List[Dict[str, Any]]:
        """
        Get dialogue history for an episode
        
        Args:
            episode_id: Episode to query
            
        Returns:
            list: Dialogue turns (copy)
            
        Raises:
            ValueError: If episode_id doesn't exist
        """
        if episode_id < 1 or episode_id > len(self.episodes):
            raise ValueError(f"Episode {episode_id} does not exist")
        
        return self.dialogue_history[episode_id].copy()
    
    def get_all_dialogue_history(self) -> Dict[int, List[Dict[str, Any]]]:
        """
        Get dialogue history for all episodes
        
        Returns:
            dict: {episode_id: [dialogue turns]}
        """
        return {eid: turns.copy() for eid, turns in self.dialogue_history.items()}
    
    # ========================
    # Export Methods
    # ========================
    
    def export_for_json(self) -> Dict[str, Any]:
        """
        Export complete state for JSON formatter
        
        Returns:
            dict: {
                'episodes': [...],
                'shared_data': {...}
            }
            
        Note: Does NOT include current_episode_id (UI state)
        """
        return {
            'episodes': [ep.copy() for ep in self.episodes],
            'shared_data': self.shared_data.copy()
        }
    
    def export_for_summary(self) -> Dict[str, Any]:
        """
        Export state for summary generator
        
        Returns:
            dict: {
                'episodes': [...],
                'shared_data': {...},
                'dialogue_history': {episode_id: [turns]}
            }
        """
        return {
            'episodes': [ep.copy() for ep in self.episodes],
            'shared_data': self.shared_data.copy(),
            'dialogue_history': self.get_all_dialogue_history()
        }
    
    # ========================
    # Utility Methods
    # ========================
    
    def reset(self) -> None:
        """
        Clear all state (for starting new consultation)
        
        Warning: This erases all data. Use with caution.
        """
        self.episodes.clear()
        self.shared_data = {
            'past_medical_history': [],
            'medications': [],
            'family_history': [],
            'social_history': {}
        }
        self.dialogue_history.clear()
        logger.info("State Manager reset - all data cleared")
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """
        Get summary statistics (for debugging/logging)
        
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