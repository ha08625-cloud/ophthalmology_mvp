"""
JSON Formatter V2 - Multi-episode consultation JSON serialization

Responsibilities:
- Transform State Manager V2 output to JSON-serializable dict
- Add metadata (consultation_id, generated_at, schema_version)
- Validate required structure
- Log unexpected fields (permissive acceptance)

Design principles:
- Pure serialization (no business logic)
- No completeness calculation
- No type conversion (except own generated_at timestamp)
- Validate structure, accept extra fields
- Single reserved field for future V3 features

Breaking changes from V1:
- Episodes array instead of flat sections
- No completeness/status blocks
- No field mapping to schema sections
- No type conversion logic
- Clean break - rejects V1 input explicitly
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class JSONFormatterV2:
    """
    Pure serialization layer for multi-episode consultation output
    
    Transforms State Manager V2 output into schema-compliant JSON.
    """
    
    def __init__(self, schema_version: str = "2.0.0"):
        """
        Initialize JSON Formatter V2
        
        Args:
            schema_version: Schema version string (default: "2.0.0")
        """
        self.schema_version = schema_version
        logger.info(f"JSON Formatter V2 initialized (schema_version={schema_version})")
    
    def format_state(self, state_data: dict, consultation_id: str) -> dict:
        """
        Transform state data to JSON-serializable dict
        
        Pure function: validates structure and adds metadata, but does not
        transform or filter the clinical data itself.
        
        Args:
            state_data: Output from state.export_for_json()
                Expected structure:
                {
                    'episodes': [list of episode dicts],
                    'shared_data': {shared data dict}
                }
            consultation_id: Unique consultation identifier
            
        Returns:
            dict: JSON-ready structure with schema_version, metadata,
                  episodes, shared_data, and audit_metadata
                  
        Raises:
            ValueError: If required structure is missing or invalid
            
        Example:
            >>> formatter = JSONFormatterV2()
            >>> state_data = state.export_for_json()
            >>> output = formatter.format_state(state_data, "abc123")
            >>> assert output['schema_version'] == '2.0.0'
            >>> assert output['metadata']['consultation_id'] == 'abc123'
        """
        # Validate input type
        if not isinstance(state_data, dict):
            raise ValueError(f"state_data must be dict, got {type(state_data).__name__}")
        
        if not isinstance(consultation_id, str) or not consultation_id.strip():
            raise ValueError("consultation_id must be non-empty string")
        
        # Validate required structure (strict)
        self._validate_required_structure(state_data)
        
        # Validate episode structure
        self._validate_episodes(state_data['episodes'])
        
        # Log unexpected fields (permissive)
        self._log_unexpected_fields(state_data)
        
        # Generate metadata
        metadata = self._generate_metadata(
            consultation_id=consultation_id,
            episodes=state_data['episodes']
        )
        
        # Build output structure
        output = {
            "schema_version": self.schema_version,
            "metadata": metadata,
            "episodes": state_data['episodes'],
            "shared_data": state_data['shared_data'],
            "audit_metadata": {}  # Reserved for V3
        }
        
        logger.info(
            f"Formatted consultation {consultation_id}: "
            f"{len(state_data['episodes'])} episodes"
        )
        
        return output
    
    def _validate_required_structure(self, state_data: dict) -> None:
        """
        Validate required top-level structure
        
        Args:
            state_data: Input data to validate
            
        Raises:
            ValueError: If required fields missing or wrong type
        """
        # Check required keys exist
        if 'episodes' not in state_data:
            raise ValueError("Missing required field 'episodes' in state_data")
        
        if 'shared_data' not in state_data:
            raise ValueError("Missing required field 'shared_data' in state_data")
        
        # Check types
        if not isinstance(state_data['episodes'], list):
            raise ValueError(
                f"'episodes' must be list, got {type(state_data['episodes']).__name__}"
            )
        
        if not isinstance(state_data['shared_data'], dict):
            raise ValueError(
                f"'shared_data' must be dict, got {type(state_data['shared_data']).__name__}"
            )
    
    def _validate_episodes(self, episodes: list) -> None:
        """
        Validate episode structure
        
        Args:
            episodes: List of episode dicts
            
        Raises:
            ValueError: If episode structure invalid
        """
        for i, episode in enumerate(episodes):
            if not isinstance(episode, dict):
                raise ValueError(
                    f"episodes[{i}] must be dict, got {type(episode).__name__}"
                )
            
            # Check required episode_id field
            if 'episode_id' not in episode:
                raise ValueError(f"episodes[{i}] missing required field 'episode_id'")
            
            episode_id = episode['episode_id']
            if not isinstance(episode_id, int):
                raise ValueError(
                    f"episodes[{i}].episode_id must be integer, "
                    f"got {type(episode_id).__name__}"
                )
            
            # Validate timestamp types if present
            for timestamp_field in ['timestamp_started', 'timestamp_last_updated']:
                if timestamp_field in episode:
                    if not isinstance(episode[timestamp_field], str):
                        raise ValueError(
                            f"episodes[{i}].{timestamp_field} must be string, "
                            f"got {type(episode[timestamp_field]).__name__}"
                        )
    
    def _log_unexpected_fields(self, state_data: dict) -> None:
        """
        Log warnings for unexpected fields (but accept them)
        
        This helps detect typos or future-added fields without breaking
        the serialization process.
        
        Args:
            state_data: State data to check
        """
        # Expected root-level keys
        expected_root = {'episodes', 'shared_data'}
        actual_root = set(state_data.keys())
        
        unexpected_root = actual_root - expected_root
        if unexpected_root:
            logger.warning(
                f"Unexpected root-level fields: {sorted(unexpected_root)} "
                f"- serializing anyway"
            )
        
        # Check episodes for unexpected patterns (informational only)
        # We don't know the full schema, so we can't validate field names,
        # but we can log if episodes have wildly different field sets
        if len(state_data['episodes']) > 1:
            field_sets = [set(ep.keys()) for ep in state_data['episodes']]
            all_fields = set().union(*field_sets)
            
            # Log if any episode is missing fields that others have
            # (may indicate inconsistent data entry)
            for i, ep_fields in enumerate(field_sets):
                missing = all_fields - ep_fields
                # Filter out expected variability
                missing = missing - {
                    'episode_id', 'timestamp_started', 'timestamp_last_updated'
                }
                if len(missing) > 5:  # Arbitrary threshold
                    logger.debug(
                        f"episodes[{i}] missing {len(missing)} fields present "
                        f"in other episodes (expected variability)"
                    )
    
    def _generate_metadata(self, consultation_id: str, episodes: list) -> dict:
        """
        Generate metadata block
        
        Args:
            consultation_id: Consultation identifier
            episodes: Episodes array (for counting)
            
        Returns:
            dict: Metadata with consultation_id, generated_at, total_episodes
        """
        # Generate ISO 8601 timestamp with Z suffix
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        
        return {
            "consultation_id": consultation_id,
            "generated_at": timestamp,
            "total_episodes": len(episodes)
        }
    
    @staticmethod
    def save_to_file(data_dict: dict, file_path: str) -> str:
        """
        Convenience method to save formatted dict to JSON file
        
        Args:
            data_dict: Output from format_state()
            file_path: Path to save file
            
        Returns:
            str: Absolute path to saved file
            
        Raises:
            TypeError: If data_dict is not JSON-serializable
            OSError: If file cannot be written
            
        Example:
            >>> output = formatter.format_state(state_data, "abc123")
            >>> path = JSONFormatterV2.save_to_file(output, "output.json")
            >>> print(f"Saved to {path}")
        """
        output_file = Path(file_path)
        
        # Create parent directory if needed
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write pretty-printed JSON
        with open(output_file, 'w') as f:
            json.dump(data_dict, f, indent=2, ensure_ascii=False)
        
        abs_path = str(output_file.absolute())
        logger.info(f"JSON saved to {abs_path}")
        
        return abs_path