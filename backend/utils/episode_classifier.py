"""
Episode Classifier - Field classification for multi-episode consultations

Responsibilities:
- Classify fields as episode-specific, shared, or unknown
- Single source of truth for field routing
- Based on mvp_json_schema_v2_0_1_multi_episode.json

Design principles:
- Pure functions (no state)
- Prefix-based classification (automatic sync with ruleset)
- Easy to update when schema evolves

Prefix Convention (from ruleset.json):
- vl_* : vision loss
- cp_* : color perception  
- vp_* : visual phenomena (flashing lights, zigzags)
- dp_* : diplopia (double vision)
- h_*  : headache
- ep_* : eye pain
- ac_* : appearance changes
- hc_* : healthcare contacts
- b1_* : follow-up block 1 (optic neuritis screen)
- b2_* : follow-up block 2 (GCA screen)
- b3_* : follow-up block 3 (pituitary dysfunction screen)
- b4_* : follow-up block 4 (nutritional/toxic optic neuropathy screen)
- b5_* : follow-up block 5 (cat scratch disease screen)
- b6_* : follow-up block 6 (higher visual processing screen)
"""

from typing import Set, Literal

# Episode-specific prefixes
# Any field starting with these prefixes belongs to the current episode
EPISODE_PREFIXES = {
    'vl_',              # vision loss
    'cp_',              # color perception
    'vp_',              # visual phenomena
    'dp_',              # diplopia
    'h_',               # headache
    'ep_',              # eye pain
    'ac_',              # appearance changes
    'hc_',              # healthcare contacts
    'b1_',              # follow-up block 1
    'b2_',              # follow-up block 2
    'b3_',              # follow-up block 3
    'b4_',              # follow-up block 4
    'b5_',              # follow-up block 5
    'b6_',              # follow-up block 6
}

# Episode-specific fields WITHOUT clear prefix
# These don't follow the prefix convention but are still episode-specific
EPISODE_SPECIAL_CASES = {
    'visual_loss_present',
    'agnosia_present',
    'agnosia_description',
    'hallucinations_present',
    'hallucinations_description',
    'hallucinations_completely_resolved',
    'vertigo_present',
    'nystagmus_present',
    'dry_gritty_sensation',
    'appearance_changes_present',
    'other_symptoms',
    'functional_impact',
}

# Shared data fields (not episode-specific)
# Placeholders for now - actual collection not yet implemented
SHARED_FIELDS = {
    # Episode transition control
    'additional_episodes_present',
    
    # Past medical history (placeholder - not yet collected)
    'past_medical_history',
    
    # Medications (placeholder - not yet collected)
    'medications',
    
    # Family history (placeholder - not yet collected)
    'family_history',
    
    # Social history (placeholder - not yet collected)
    'smoking_status',
    'alcohol_use',
    'occupation',
    'living_situation'
}


def classify_field(field_name: str) -> Literal['episode', 'shared', 'unknown']:
    """
    Classify a field as episode-specific, shared, or unknown
    
    Uses prefix-based classification for automatic sync with ruleset.
    When you add new fields to ruleset.json with existing prefixes,
    they are automatically classified correctly.
    
    Args:
        field_name: Field name to classify
        
    Returns:
        'episode': Field belongs to current episode
        'shared': Field is shared across all episodes
        'unknown': Field not recognized in schema
        
    Examples:
        >>> classify_field('vl_laterality')
        'episode'
        
        >>> classify_field('vl_new_field')  # Automatically episode even if just added
        'episode'
        
        >>> classify_field('b1_uhthoff_phenomenon')  # Follow-up block field
        'episode'
        
        >>> classify_field('medications')
        'shared'
        
        >>> classify_field('unknown_field')
        'unknown'
    """
    # Check shared fields first (small set, explicit)
    if field_name in SHARED_FIELDS:
        return 'shared'
    
    # Check episode prefixes
    for prefix in EPISODE_PREFIXES:
        if field_name.startswith(prefix):
            return 'episode'
    
    # Check episode special cases
    if field_name in EPISODE_SPECIAL_CASES:
        return 'episode'
    
    # Unknown field
    return 'unknown'


def get_all_episode_prefixes() -> Set[str]:
    """
    Get set of all episode field prefixes
    
    Returns:
        Set of prefix strings
    """
    return EPISODE_PREFIXES.copy()


def get_episode_special_cases() -> Set[str]:
    """
    Get set of episode fields without standard prefix
    
    Returns:
        Set of field names
    """
    return EPISODE_SPECIAL_CASES.copy()


def get_all_shared_fields() -> Set[str]:
    """
    Get flat set of all shared field names
    
    Returns:
        Set of shared field names
    """
    return SHARED_FIELDS.copy()


def is_episode_field(field_name: str) -> bool:
    """
    Check if field is episode-specific
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if episode-specific field
    """
    return classify_field(field_name) == 'episode'


def is_shared_field(field_name: str) -> bool:
    """
    Check if field is shared data
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if shared field
    """
    return classify_field(field_name) == 'shared'


def get_prefix_documentation() -> dict:
    """
    Get documentation of what each prefix means
    
    Useful for debugging and documentation generation
    
    Returns:
        dict: {prefix: description}
    """
    return {
        'vl_': 'Vision loss',
        'cp_': 'Color perception',
        'vp_': 'Visual phenomena (flashing lights, zigzags)',
        'dp_': 'Diplopia (double vision)',
        'h_': 'Headache',
        'ep_': 'Eye pain',
        'ac_': 'Appearance changes',
        'hc_': 'Healthcare contacts',
        'b1_': 'Follow-up block 1 (Optic Neuritis Screen)',
        'b2_': 'Follow-up block 2 (Giant Cell Arteritis Screen)',
        'b3_': 'Follow-up block 3 (Pituitary Dysfunction Screen)',
        'b4_': 'Follow-up block 4 (Nutritional/Toxic Optic Neuropathy Screen)',
        'b5_': 'Follow-up block 5 (Cat Scratch Disease Screen)',
        'b6_': 'Follow-up block 6 (Higher Visual Processing Screen)',
    }