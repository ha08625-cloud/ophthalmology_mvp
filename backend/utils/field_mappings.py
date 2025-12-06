"""
Field Mappings - Standardize patient responses to canonical values

Responsibilities:
- Map natural language variations to standardized field values
- Handle common synonyms and phrasings
- Return canonical value that matches schema

Design principles:
- Start minimal, expand as needed
- Case-insensitive matching
- Return raw value if no mapping found (don't block)
- Single source of truth for value standardization

Note: This is a simple lookup table for MVP.
V2 might use more sophisticated semantic matching.
"""

# Laterality mappings
LATERALITY_MAP = {
    # Right eye
    'right': 'monocular_right',
    'right eye': 'monocular_right',
    'my right eye': 'monocular_right',
    'the right eye': 'monocular_right',
    'the right one': 'monocular_right',
    'right side': 'monocular_right',
    'od': 'monocular_right',  # oculus dexter
    
    # Left eye
    'left': 'monocular_left',
    'left eye': 'monocular_left',
    'my left eye': 'monocular_left',
    'the left eye': 'monocular_left',
    'the left one': 'monocular_left',
    'left side': 'monocular_left',
    'os': 'monocular_left',  # oculus sinister
    
    # Both eyes
    'both': 'binocular',
    'both eyes': 'binocular',
    'both of them': 'binocular',
    'each eye': 'binocular',
    'bilateral': 'binocular',
    'ou': 'binocular',  # oculus uterque
}

# Onset speed mappings
ONSET_SPEED_MAP = {
    # Acute (seconds to minutes)
    'sudden': 'acute',
    'suddenly': 'acute',
    'immediate': 'acute',
    'immediately': 'acute',
    'instant': 'acute',
    'instantly': 'acute',
    'all at once': 'acute',
    'right away': 'acute',
    
    # Subacute (hours to days)
    'gradual': 'subacute',
    'gradually': 'subacute',
    'over hours': 'subacute',
    'over a day': 'subacute',
    'over days': 'subacute',
    'few hours': 'subacute',
    'few days': 'subacute',
    
    # Chronic (weeks or longer)
    'slow': 'chronic',
    'slowly': 'chronic',
    'over weeks': 'chronic',
    'over months': 'chronic',
    'over time': 'chronic',
    'progressive': 'chronic',
    'progressively': 'chronic',
}

# Temporal pattern mappings
TEMPORAL_PATTERN_MAP = {
    # Permanent
    'constant': 'permanent',
    'constantly': 'permanent',
    'all the time': 'permanent',
    'continuous': 'permanent',
    'continuously': 'permanent',
    'persistent': 'permanent',
    'never goes away': 'permanent',
    'still there': 'permanent',
    
    # Transient (came and went once)
    'went away': 'transient',
    'resolved': 'transient',
    'got better': 'transient',
    'improved': 'transient',
    'temporary': 'transient',
    'briefly': 'transient',
    
    # Intermittent (comes and goes)
    'comes and goes': 'intermittent',
    'on and off': 'intermittent',
    'sometimes': 'intermittent',
    'occasional': 'intermittent',
    'occasionally': 'intermittent',
    'episodic': 'intermittent',
    'recurrent': 'intermittent',
}

# Degree mappings (severity)
DEGREE_MAP = {
    # Partial loss
    'partial': 'partial',
    'blurry': 'partial',
    'blurred': 'partial',
    'dim': 'partial',
    'dimmed': 'partial',
    'reduced': 'partial',
    'fuzzy': 'partial',
    'hazy': 'partial',
    'cloudy': 'partial',
    
    # Total loss
    'total': 'total',
    'complete': 'total',
    'completely': 'total',
    'totally': 'total',
    'gone': 'total',
    'black': 'total',
    'blackout': 'total',
    'blind': 'total',
    'nothing': 'total',
    'can\'t see': 'total',
    'cannot see': 'total',
}

# Boolean mappings (yes/no responses)
BOOLEAN_MAP = {
    # True
    'yes': True,
    'yeah': True,
    'yep': True,
    'yup': True,
    'correct': True,
    'right': True,
    'that\'s right': True,
    'true': True,
    'definitely': True,
    'absolutely': True,
    
    # False
    'no': False,
    'nope': False,
    'nah': False,
    'not really': False,
    'no way': False,
    'false': False,
    'incorrect': False,
    'wrong': False,
}

# Field-specific mapping registry
FIELD_MAPPINGS = {
    'vl_laterality': LATERALITY_MAP,
    'vl_onset_speed': ONSET_SPEED_MAP,
    'vl_temporal_pattern': TEMPORAL_PATTERN_MAP,
    'h_temporal_pattern': TEMPORAL_PATTERN_MAP,  # Same as vision loss
    'vl_degree': DEGREE_MAP,
    
    # Laterality fields in other sections
    'cp_laterality': LATERALITY_MAP,
    'vp_laterality': LATERALITY_MAP,
    'dp_laterality': LATERALITY_MAP,
}


def map_field_value(field_name, raw_value, valid_values=None):
    """
    Map natural language value to standardized field value
    
    Args:
        field_name (str): Field being mapped (e.g., 'vl_laterality')
        raw_value (str): Raw extracted value from LLM
        valid_values (list): Optional list of valid values from question
        
    Returns:
        str: Standardized value (or raw_value if no mapping found)
        
    Examples:
        >>> map_field_value('vl_laterality', 'right eye', None)
        'monocular_right'
        
        >>> map_field_value('vl_onset_speed', 'suddenly', None)
        'acute'
        
        >>> map_field_value('unknown_field', 'some value', None)
        'some value'  # No mapping, returns as-is
    """
    if not isinstance(raw_value, str):
        # If it's already bool, int, etc., return as-is
        return raw_value
    
    # Normalize: lowercase, strip whitespace
    normalized = raw_value.lower().strip()
    
    # Check if this field has a mapping table
    if field_name in FIELD_MAPPINGS:
        mapping_table = FIELD_MAPPINGS[field_name]
        
        # Try exact match first
        if normalized in mapping_table:
            return mapping_table[normalized]
        
        # Try substring match (e.g., "my right eye went blurry" contains "right eye")
        for key, value in mapping_table.items():
            if key in normalized:
                return value
    
    # Check for boolean fields (anything with 'present', '_occurred', etc.)
    if field_name.endswith('_present') or field_name.endswith('_occurred') or \
       any(bool_key in field_name for bool_key in ['is_', 'has_', 'can_']):
        if normalized in BOOLEAN_MAP:
            return BOOLEAN_MAP[normalized]
    
    # No mapping found - return raw value
    # (Don't block the conversation, just pass through)
    return raw_value


def validate_against_schema(field_name, value, valid_values):
    """
    Check if value is in valid_values list
    
    Args:
        field_name (str): Field name
        value: Value to validate
        valid_values (list): List of acceptable values
        
    Returns:
        bool: True if valid or no valid_values specified
    """
    if valid_values is None:
        return True
    
    return value in valid_values


def get_field_type_hint(field_name):
    """
    Infer expected type from field name
    
    Args:
        field_name (str): Field name
        
    Returns:
        str: 'boolean', 'categorical', 'text', or 'unknown'
    """
    if field_name.endswith('_present') or field_name.endswith('_occurred'):
        return 'boolean'
    
    if field_name in FIELD_MAPPINGS:
        return 'categorical'
    
    if field_name.endswith('_description') or field_name.endswith('_details'):
        return 'text'
    
    return 'unknown'