"""
Turn-based consultation persistence.

Append-only JSON files for audit trail and restart resilience.
"""

import json
import logging
from pathlib import Path
from typing import Optional

# When copying to local, adjust to: from backend.commands import ConsultationState
from backend.commands import ConsultationState

logger = logging.getLogger(__name__)


class ConsultationPersistence:
    """
    Manages turn-by-turn JSON persistence.
    
    Layout:
        outputs/consultations/CONSULT-abc123/
            CONSULT-abc123_TURN-001.json
            CONSULT-abc123_TURN-002.json
            ...
    
    Design:
    - Append-only (never overwrite)
    - One file per turn
    - Enables time-travel debugging
    - Restart-resilient
    """
    
    def __init__(self, base_dir: str = "outputs/consultations"):
        """
        Initialize persistence layer.
        
        Args:
            base_dir: Base directory for all consultations
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ConsultationPersistence initialized: {self.base_dir}")
    
    def save_turn(self, consultation_id: str, state: ConsultationState) -> str:
        """
        Save turn to append-only file.
        
        Args:
            consultation_id: Consultation identifier
            state: Opaque state envelope
            
        Returns:
            str: Absolute path to saved file
            
        Raises:
            FileExistsError: If turn file already exists (double-submit)
        """
        # Create consultation directory
        consult_dir = self.base_dir / f"CONSULT-{consultation_id}"
        consult_dir.mkdir(exist_ok=True)
        
        # Determine turn number from state
        turn_count = state.turn_count
        
        # Build filename
        filename = f"CONSULT-{consultation_id}_TURN-{turn_count:03d}.json"
        filepath = consult_dir / filename
        
        # Check for double-submit
        if filepath.exists():
            raise FileExistsError(
                f"Turn file already exists: {filepath}. "
                f"This indicates a double-submit or turn-count error."
            )
        
        # Write (append-only means new files, never overwrite)
        with open(filepath, 'w') as f:
            json.dump(state.to_json(), f, indent=2, ensure_ascii=False)
        
        abs_path = str(filepath.absolute())
        logger.info(f"Saved turn {turn_count} for {consultation_id}: {filename}")
        
        return abs_path
    
    def load_latest_turn(self, consultation_id: str) -> Optional[ConsultationState]:
        """
        Load latest turn for consultation.
        
        Args:
            consultation_id: Consultation identifier
            
        Returns:
            ConsultationState if consultation exists, None otherwise
        """
        consult_dir = self.base_dir / f"CONSULT-{consultation_id}"
        
        if not consult_dir.exists():
            logger.warning(f"Consultation directory not found: {consultation_id}")
            return None
        
        # Find highest turn number
        pattern = f"CONSULT-{consultation_id}_TURN-*.json"
        turn_files = list(consult_dir.glob(pattern))
        
        if not turn_files:
            logger.warning(f"No turn files found for {consultation_id}")
            return None
        
        # Sort by turn number (extract from filename)
        latest_file = max(turn_files, key=lambda p: p.name)
        
        logger.info(f"Loading latest turn for {consultation_id}: {latest_file.name}")
        
        # Load and wrap
        with open(latest_file, 'r') as f:
            data = json.load(f)
        
        return ConsultationState.from_json(data)
    
    def consultation_exists(self, consultation_id: str) -> bool:
        """
        Check if consultation has any saved turns.
        
        Args:
            consultation_id: Consultation identifier
            
        Returns:
            bool: True if at least one turn file exists
        """
        consult_dir = self.base_dir / f"CONSULT-{consultation_id}"
        return consult_dir.exists() and any(consult_dir.glob("*.json"))
    
    def get_turn_count(self, consultation_id: str) -> int:
        """
        Get number of saved turns for consultation.
        
        Args:
            consultation_id: Consultation identifier
            
        Returns:
            int: Number of turn files (0 if consultation doesn't exist)
        """
        consult_dir = self.base_dir / f"CONSULT-{consultation_id}"
        
        if not consult_dir.exists():
            return 0
        
        pattern = f"CONSULT-{consultation_id}_TURN-*.json"
        turn_files = list(consult_dir.glob(pattern))
        
        return len(turn_files)