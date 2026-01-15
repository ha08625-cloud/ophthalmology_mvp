"""
Clarification Template Registry

Defines template IDs for clarification questions and their replay eligibility.

Template Classification:
- Episode-structural (replayable=False): Questions about episode identity/relation
- Clinically referential (replayable=True): Questions extracting episode-specific details

The replayable flag determines whether the user's response can be replayed
to the Response Parser after episode resolution.

Template Text:
- TEMPLATE_TEXT contains pattern strings with placeholders for question generation
- Rendered text (with placeholders filled) is stored in ClarificationTurn.rendered_text
- Replay adapter uses rendered_text, not template patterns

Forced Resolution Policies:
- ForcedResolutionPolicy enum defines authoritative policies for forced resolution
- These are injected verbatim into RP replay prompts
- Policy selection is owned by Episode Hypothesis Manager (not implemented here)
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


class ForcedResolutionPolicy(str, Enum):
    """
    Policies applied when clarification exceeds attempt limit.
    
    These values are injected verbatim into Response Parser replay prompts.
    The policy is authoritative and non-overridable by the RP.
    
    Values:
        SEPARATION_PROTOCOL: Treat input as new, distinct episode.
            RP is instructed not to link to prior episodes.
        CONTINUITY_PROTOCOL: Merge input into existing active episode.
            Allowed only if episode of same symptom class exists.
            Temporal language treated as progression, not new event.
        ISOLATION_PROTOCOL: Extract data into Limbo episode.
            All fields tagged with low confidence and ambiguous provenance.
            Limbo episodes are write-only, excluded from protocol flow.
    """
    SEPARATION_PROTOCOL = "separation_protocol"
    CONTINUITY_PROTOCOL = "continuity_protocol"
    ISOLATION_PROTOCOL = "isolation_protocol"


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


# Template text patterns: maps template_id to question pattern with placeholders
# Placeholders use {placeholder_name} format for string formatting
# Rendered text (with placeholders filled) is stored in ClarificationTurn.rendered_text
TEMPLATE_TEXT: Dict[ClarificationTemplateID, str] = {
    # Episode-structural templates
    ClarificationTemplateID.CLARIFY_EPISODE_SAME_OR_DIFFERENT: (
        "You mentioned {mention_1} and {mention_2}. "
        "Are these the same episode or different episodes?"
    ),
    ClarificationTemplateID.CLARIFY_TEMPORAL_RELATION: (
        "Did {mention_1} happen before, after, or at the same time as {mention_2}?"
    ),
    
    # Clinically referential templates
    ClarificationTemplateID.CLARIFY_LOCATION: (
        "Where exactly was {mention_1} located?"
    ),
    ClarificationTemplateID.CLARIFY_LATERALITY: (
        "Was {mention_1} on the left side, right side, or both?"
    ),
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


def get_template_text(template_id: str) -> str:
    """
    Get template text pattern for a template ID.
    
    Args:
        template_id: Template identifier string
        
    Returns:
        str: Template text pattern with placeholders
        
    Raises:
        KeyError: If template_id not found in registry
    """
    # Convert string to enum if needed
    if isinstance(template_id, str) and not isinstance(template_id, ClarificationTemplateID):
        template_id = ClarificationTemplateID(template_id)
    return TEMPLATE_TEXT[template_id]


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
