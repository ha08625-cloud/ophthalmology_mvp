"""
Display Helpers - Convert internal state to human-readable format

Used by dialogue manager to generate state views for UI display.
"""

from typing import Dict, Any, List, Optional


# Field name mappings: technical_name -> Human Readable Label
FIELD_LABELS = {
    # Vision Loss fields
    'vl_present': 'Vision Loss Present',
    'vl_laterality': 'Laterality',
    'vl_first_onset': 'First Onset',
    'vl_pattern': 'Pattern',
    'vl_speed': 'Speed of Onset',
    'vl_current_severity': 'Current Severity',
    'vl_initial_severity': 'Initial Severity',
    'vl_location': 'Location in Visual Field',
    'vl_progression': 'Progression',
    
    # Eye Pain fields
    'ep_present': 'Eye Pain Present',
    'ep_laterality': 'Laterality',
    'ep_first_onset': 'First Onset',
    'ep_severity': 'Severity',
    'ep_character': 'Pain Character',
    'ep_location': 'Pain Location',
    
    # Flashes fields
    'fl_present': 'Flashes Present',
    'fl_laterality': 'Laterality',
    'fl_first_onset': 'First Onset',
    'fl_frequency': 'Frequency',
    'fl_pattern': 'Pattern',
    
    # Floaters fields
    'ft_present': 'Floaters Present',
    'ft_laterality': 'Laterality',
    'ft_first_onset': 'First Onset',
    'ft_number': 'Number',
    'ft_progression': 'Progression',
    
    # Red Eye fields
    're_present': 'Red Eye Present',
    're_laterality': 'Laterality',
    're_first_onset': 'First Onset',
    're_pattern': 'Pattern',
    're_discharge': 'Discharge Present',
    
    # Diplopia fields
    'dp_present': 'Double Vision Present',
    'dp_first_onset': 'First Onset',
    'dp_pattern': 'Pattern',
    'dp_direction': 'Direction',
    
    # Add more as needed
}


# Value mappings: For categorical fields, convert values to readable text
VALUE_LABELS = {
    # Boolean values
    'true': 'Yes',
    'false': 'No',
    True: 'Yes',
    False: 'No',
    
    # Laterality
    'right': 'Right eye',
    'left': 'Left eye',
    'both': 'Both eyes',
    
    # Pattern
    'constant': 'Constant',
    'intermittent': 'Intermittent',
    'progressive': 'Progressive',
    
    # Severity
    'mild': 'Mild',
    'moderate': 'Moderate',
    'severe': 'Severe',
    
    # Speed
    'sudden': 'Sudden',
    'gradual': 'Gradual',
    'rapid': 'Rapid',
    
    # Add more as needed
}


def format_field_name(field_name: str) -> str:
    """
    Convert technical field name to human-readable label.
    
    Args:
        field_name: Technical field name (e.g., 'vl_laterality')
        
    Returns:
        Human-readable label (e.g., 'Laterality')
        Falls back to capitalized field name if not in mapping
    """
    if field_name in FIELD_LABELS:
        return FIELD_LABELS[field_name]
    
    # Fallback: capitalize and replace underscores
    return field_name.replace('_', ' ').title()


def format_field_value(value: Any) -> str:
    """
    Convert field value to human-readable text.
    
    Args:
        value: Raw field value (could be str, bool, int, etc.)
        
    Returns:
        Human-readable value as string
    """
    # Handle None
    if value is None:
        return "Not specified"
    
    # Convert to string for lookup
    value_lower = str(value).lower() if not isinstance(value, bool) else value
    
    # Check if we have a mapping
    if value_lower in VALUE_LABELS:
        return VALUE_LABELS[value_lower]
    
    # Fallback: just return as string, capitalize if single word
    value_str = str(value)
    if ' ' not in value_str and value_str.islower():
        return value_str.capitalize()
    
    return value_str


def format_state_for_display(state_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert internal state snapshot to human-readable display format.
    
    Extracts only populated clinical fields (no provenance, no operational metadata).
    
    NOTE: Episode structure is FLAT - fields are at root level of episode dict,
    not nested inside a 'data' key.
    
    Args:
        state_snapshot: Raw state from StateManager.snapshot_state()
        
    Returns:
        dict: {
            'episodes': [
                {
                    'number': 1,
                    'fields': [
                        {'label': 'Vision Loss Present', 'value': 'Yes'},
                        {'label': 'Laterality', 'value': 'Right eye'},
                        ...
                    ]
                },
                ...
            ]
        }
    """
    # Operational fields to skip (from StateManager.OPERATIONAL_FIELDS)
    OPERATIONAL_FIELDS = {
        'episode_id',
        'timestamp_started',
        'timestamp_last_updated',
        'questions_answered',
        'questions_satisfied',
        'follow_up_blocks_activated',
        'follow_up_blocks_completed'
    }
    
    display_view = {'episodes': []}
    
    episodes = state_snapshot.get('episodes', [])
    
    for idx, episode in enumerate(episodes):
        episode_num = idx + 1
        
        # Extract only populated fields (ignore None, empty strings)
        populated_fields = []
        
        # Episode structure is FLAT - fields are at root level
        for field_name, field_value in episode.items():
            # Skip operational/internal fields
            if field_name in OPERATIONAL_FIELDS:
                continue
            
            # Skip provenance fields
            if field_name.startswith('_') or field_name.endswith('_provenance') or field_name.endswith('_confidence'):
                continue
            
            # Skip empty values
            if field_value is None or field_value == '':
                continue
            
            # Format and add
            populated_fields.append({
                'label': format_field_name(field_name),
                'value': format_field_value(field_value)
            })
        
        # Add episode even if no fields (shows "Episode N" but empty)
        display_view['episodes'].append({
            'number': episode_num,
            'fields': populated_fields
        })
    
    return display_view