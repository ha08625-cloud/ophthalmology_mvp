"""
Command types for DialogueManager control flow.

Commands are the ONLY public interface to DialogueManager.
No direct method calls. No state inspection. Commands only.
"""

from dataclasses import dataclass
from typing import Dict, Any
import copy


@dataclass(frozen=True)
class ConsultationState:
    """
    Opaque value object wrapping canonical state snapshot.
    
    Rules:
    - No code outside StateManager/DialogueManager inspects _data
    - Immutable after creation
    - Deep copied on construction
    - Serializable to/from JSON
    
    This is a sealed envelope, not a model.
    """
    _data: Dict[str, Any]
    
    @property
    def turn_count(self) -> int:
        """
        EXCEPTION: Operational metadata for turn validation.
        
        This is the ONLY permitted accessor. Any future additions
        require architectural review.
        """
        return self._data.get('turn_count', 0)
    
    def to_json(self) -> dict:
        """
        Serialize to JSON-safe dict (deep copy).
        
        Returns:
            dict: Deep copy of internal state
        """
        return copy.deepcopy(self._data)
    
    @staticmethod
    def from_json(data: dict) -> "ConsultationState":
        """
        Deserialize from JSON dict.
        
        Deep copies to ensure sealed envelope - no external
        references can mutate our internal state.
        
        Args:
            data: Raw state dict from JSON
            
        Returns:
            ConsultationState: Sealed envelope
        """
        return ConsultationState(_data=copy.deepcopy(data))


# Command types

@dataclass(frozen=True)
class StartConsultation:
    """
    Initialize new consultation.
    
    No state parameter - DM creates initial state.
    Returns: TurnResult with first question + initial state.
    """
    pass


@dataclass(frozen=True)
class UserTurn:
    """
    Process user input for current turn.
    
    Requires existing state from previous turn.
    Returns: TurnResult with next question + updated state.
    """
    user_input: str
    state: ConsultationState


@dataclass(frozen=True)
class FinalizeConsultation:
    """
    Generate final outputs (JSON + summary).
    
    Only valid when consultation_complete=True.
    Returns: FinalReport with file paths.
    """
    state: ConsultationState


# Command union type for type hints
Command = StartConsultation | UserTurn | FinalizeConsultation