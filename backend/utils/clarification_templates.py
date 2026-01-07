"""
Clarification Template Registry

Defines template IDs for clarification questions and their replay eligibility.

Template Classification:
- Episode-structural (replayable=False): Questions about episode identity/relation
- Clinically referential (replayable=True): Questions extracting episode-specific details

The replayable flag determines whether the user's response can be replayed
to the Response Parser after episode resolution.
"""

from enum import Enum
from typing import Dict


class ClarificationTemplateID(str, Enum):
    """
    Template identifiers for clarification questions.
    
    Naming convention: CLARIFY_<TOPIC>
    """
    # Episode-structural templates (not replayable)
    CLARIFY_EPISODE_SAME_OR_DIFFERENT = "clarify_episode_same_or_different"
    CLARIFY_TEMPORAL_RELATION = "clarify_temporal_relation"
    
    # Clinically referential templates (replayable)
    CLARIFY_LOCATION = "clarify_location"
    CLARIFY_LATERALITY = "clarify_laterality"


# Template metadata: maps template_id to replayability
# This is the single source of truth for replay policy per template
TEMPLATE_METADATA: Dict[str, bool] = {
    # Episode-structural - cannot be replayed
    ClarificationTemplateID.CLARIFY_EPISODE_SAME_OR_DIFFERENT: False,
    ClarificationTemplateID.CLARIFY_TEMPORAL_RELATION: False,
    
    # Clinically referential - can be replayed
    ClarificationTemplateID.CLARIFY_LOCATION: True,
    ClarificationTemplateID.CLARIFY_LATERALITY: True,
}


def is_replayable(template_id: str) -> bool:
    """
    Check if a template is replayable.
    
    Args:
        template_id: Template identifier string
        
    Returns:
        bool: True if template is replayable, False otherwise
        
    Raises:
        KeyError: If template_id not found in registry
    """
    return TEMPLATE_METADATA[template_id]


def validate_template_id(template_id: str) -> None:
    """
    Validate that template_id exists in registry.
    
    Args:
        template_id: Template identifier to validate
        
    Raises:
        ValueError: If template_id not in registry
    """
    if template_id not in TEMPLATE_METADATA:
        valid_ids = list(TEMPLATE_METADATA.keys())
        raise ValueError(
            f"Invalid template_id: '{template_id}'. "
            f"Must be one of: {valid_ids}"
        )