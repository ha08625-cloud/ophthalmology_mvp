"""
Result types returned by DialogueManager.handle()

These are the ONLY return types from the command handler.
"""

from dataclasses import dataclass
from typing import Dict, Any


# Import ConsultationState from commands to avoid circular dependency
# When copying to local, adjust to: from backend.commands import ConsultationState
from backend.commands import ConsultationState


@dataclass(frozen=True)
class TurnResult:
    """
    Successful turn processing result.
    
    Returned by: StartConsultation, UserTurn
    
    Attributes:
        system_output: Text to display to user (question or message)
        state: Opaque state envelope (Flask cannot inspect)
        debug: Debug information (parser output, routing, etc.)
        turn_metadata: Turn-level metadata (episode_id, turn_count, etc.)
        consultation_complete: Whether consultation is finished
    """
    system_output: str
    state: ConsultationState  # Opaque! Flask cannot inspect.
    debug: Dict[str, Any]
    turn_metadata: Dict[str, Any]
    consultation_complete: bool


@dataclass(frozen=True)
class FinalReport:
    """
    Final outputs after consultation completion.
    
    Returned by: FinalizeConsultation
    
    Attributes:
        json_path: Absolute path to JSON file
        summary_path: Absolute path to summary file
        json_filename: Filename only (for display)
        summary_filename: Filename only (for display)
        consultation_id: Consultation identifier
        total_episodes: Number of episodes in consultation
    """
    json_path: str
    summary_path: str
    json_filename: str
    summary_filename: str
    consultation_id: str
    total_episodes: int


@dataclass(frozen=True)
class IllegalCommand:
    """
    Command rejected by DM (invalid lifecycle transition).
    
    Examples:
    - UserTurn when no state exists
    - FinalizeConsultation when consultation_complete=False
    - StartConsultation when consultation already active
    
    Attributes:
        reason: Human-readable explanation
        command_type: Name of rejected command type
    """
    reason: str
    command_type: str