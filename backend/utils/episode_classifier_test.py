"""
Episode Classifier Test V3 - Prefix-based field routing

Responsibilities:
- Classify fields as episode-specific, shared, or unknown
- Single source of truth for field ownership routing
- Fail fast on configuration errors

Design principles:
- Rule-based prefix matching (not exhaustive enumeration)
- Disjoint prefix registries (validated at import)
- Pure functions (no state)
- Collections are opaque (routed by key, not by item fields)

Architecture:
- Episode fields: Flat scalars with unique prefixes (vl_, h_, ep_, etc.)
- Shared fields: Flat scalars with shared prefixes (sh_, sr_) OR collection keys
- Collections: Arrays stored as atomic units; item fields use local names

Examples:
    Episode scalar: 'vl_laterality' -> 'episode'
    Shared scalar: 'sh_smoking_status' -> 'shared'
    Collection: 'medications' -> 'shared'
    Collection item field: 'name' (inside medications array, not routed)
"""

from typing import Literal

# Episode-specific prefixes
# Each represents a symptom category or section within an episode
EPISODE_PREFIXES = {
    'vl_',   # vision loss
    'h_',    # headache
    'ac_',   # appearance changes
    'hc_',   # healthcare contacts
    'b1_',   # follow-up block 1
    'b6_',   # follow-up block 6
}

# Shared data prefixes
# Fields with these prefixes are shared across all episodes
SHARED_PREFIXES = {
    'sh_',  # social history (smoking, alcohol, drugs, occupation)
    'sr_',  # systems review (sr_gen_, sr_neuro_, sr_cardio_, etc.)
}

# Collection fields (arrays)
# These are routed as shared data by exact key match
# Item fields inside these arrays use local names (e.g., 'name', not 'med_name')
COLLECTION_FIELDS = {
    'medications',
    'past_medical_history'
}

# Strict mode: whether to raise ValueError on unknown fields
# If False, unknown fields return 'unknown' (logged but accepted)
# If True, unknown fields raise ValueError (fail fast)
STRICT_MODE = False


def _validate_prefix_sets():
    """
    Validate prefix registries are disjoint at module import.
    
    Configuration errors must fail at load, not at runtime.
    
    Checks:
    - Episode and shared prefixes do not overlap
    - Collection fields do not match any prefix
    
    Raises:
        RuntimeError: If configuration error detected
    """
    # Check prefix overlap
    prefix_overlap = EPISODE_PREFIXES & SHARED_PREFIXES
    if prefix_overlap:
        raise RuntimeError(
            f"Prefix registry overlap detected: {prefix_overlap}. "
            f"Episode and shared prefixes must be disjoint."
        )
    
    # Check collection fields don't match prefixes
    collection_conflicts = []
    for collection_key in COLLECTION_FIELDS:
        if any(collection_key.startswith(p) for p in EPISODE_PREFIXES):
            collection_conflicts.append(f"{collection_key} matches episode prefix")
        if any(collection_key.startswith(p) for p in SHARED_PREFIXES):
            collection_conflicts.append(f"{collection_key} matches shared prefix")
    
    if collection_conflicts:
        raise RuntimeError(
            f"Collection field conflicts with prefixes: {collection_conflicts}. "
            f"Collection keys must not match any prefix pattern."
        )


# Validate configuration at import time
_validate_prefix_sets()


def classify_field(field_name: str) -> Literal['episode', 'shared', 'unknown']:
    """
    Classify a field by prefix matching.
    
    Routing rules:
    1. If field starts with episode prefix -> 'episode'
    2. If field starts with shared prefix -> 'shared'
    3. If field is collection key -> 'shared'
    4. Otherwise -> 'unknown'
    
    Ambiguous matches (multiple rules apply) raise ValueError.
    
    Args:
        field_name: Field name to classify
        
    Returns:
        'episode': Field belongs to current episode
        'shared': Field is shared across all episodes
        'unknown': Field not recognized (logged, quarantined, or raised)
        
    Raises:
        ValueError: If ambiguous routing detected (multiple matches)
        ValueError: If unknown field and STRICT_MODE is True
        
    Examples:
        >>> classify_field('vl_laterality')
        'episode'
        
        >>> classify_field('sh_smoking_status')
        'shared'
        
        >>> classify_field('medications')
        'shared'
        
        >>> classify_field('sr_gen_chills')
        'shared'
        
        >>> classify_field('unknown_field')
        'unknown'  # or raises ValueError if STRICT_MODE=True
    """
    matches = []
    
    # Check episode prefixes
    if any(field_name.startswith(p) for p in EPISODE_PREFIXES):
        matches.append('episode')
    
    # Check shared prefixes
    if any(field_name.startswith(p) for p in SHARED_PREFIXES):
        matches.append('shared')
    
    # Check collection fields (exact match only)
    if field_name in COLLECTION_FIELDS:
        matches.append('shared')
    
    # Validate single match
    if len(matches) == 1:
        return matches[0]
    
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous field routing for '{field_name}': "
            f"matches {matches}. "
            f"Fix prefix registries to ensure disjoint sets."
        )
    
    # Unknown field
    if STRICT_MODE:
        raise ValueError(
            f"Unknown field '{field_name}' not matched by any prefix or collection. "
            f"Add appropriate prefix to EPISODE_PREFIXES or SHARED_PREFIXES, "
            f"or add to COLLECTION_FIELDS if this is an array."
        )
    
    return 'unknown'


def is_episode_field(field_name: str) -> bool:
    """
    Check if field is episode-specific.
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if episode-specific field
    """
    return classify_field(field_name) == 'episode'


def is_shared_field(field_name: str) -> bool:
    """
    Check if field is shared data.
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if shared field
    """
    return classify_field(field_name) == 'shared'


def is_collection_field(field_name: str) -> bool:
    """
    Check if field is a collection (array).
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if field is a collection key
    """
    return field_name in COLLECTION_FIELDS


def get_episode_prefix_count() -> int:
    """Get total number of episode prefixes"""
    return len(EPISODE_PREFIXES)


def get_shared_prefix_count() -> int:
    """Get total number of shared prefixes"""
    return len(SHARED_PREFIXES)


def get_collection_count() -> int:
    """Get total number of collection fields"""
    return len(COLLECTION_FIELDS)


def set_strict_mode(enabled: bool) -> None:
    """
    Enable or disable strict mode for unknown fields.
    
    Args:
        enabled: If True, unknown fields raise ValueError.
                 If False, unknown fields return 'unknown'.
    """
    global STRICT_MODE
    STRICT_MODE = enabled
