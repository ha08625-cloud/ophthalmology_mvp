"""
Episode Classifier - Field classification for multi-episode consultations

Responsibilities:
- Classify fields as episode-specific, shared, or unknown
- Single source of truth for field routing
- Based on clinical_data_model.json v2.0.0 and json_schema.json v2.1.0

Design principles:
- Pure functions (no state)
- Simple lookup tables
- Easy to update when schema evolves
"""

from typing import Set, Literal

# Episode-specific fields by section
# Each symptom/section within an episode has its own fields

VISION_LOSS_FIELDS = {
    'visual_loss_present',
    'vl_completely_resolved',
    'vl_first_onset',
    'vl_current_onset',
    'vl_temporal_pattern',
    'vl_flareup_usual_duration',
    'vl_inter_flareup_interval',
    'vl_complete_resolution',
    'vl_baseline_severity',
    'vl_worst_severity',
    'vl_current_severity',
    'vl_description',
    'vl_laterality',
    'vl_onset_simultaneity',
    'vl_field',
    'vl_degree',
    'vl_acuity_description',
    'vl_onset_speed',
    'vl_worsening',
    'vl_worsening_after_2_weeks',
    'vl_improved',
    'vl_blackouts',
    'vl_other_eye_affected',
    'agnosia_present',
    'agnosia_description'
}

VISUAL_DISTURBANCES_FIELDS = {
    # Hallucinations
    'hallucinations_present',
    'hallucinations_completely_resolved',
    'hallucinations_description',
    
    # Color perception
    'cp_present',
    'cp_completely_resolved',
    'cp_first_onset',
    'cp_temporal_pattern',
    'cp_laterality',
    'cp_field',
    'cp_colours_affected',
    
    # Visual phenomena (flashing lights, zigzags)
    'vp_present',
    'vp_completely_resolved',
    'vp_first_onset',
    'vp_temporal_pattern',
    'vp_laterality',
    'vp_description',
    'vp_duration',
    'vp_location',
    'vp_followed_by_headache',
    
    # Diplopia
    'dp_present',
    'dp_completely_resolved',
    'dp_first_onset',
    'dp_temporal_pattern',
    'dp_laterality',
    'dp_gaze_dependence',
    
    # Other
    'vertigo_present',
    'nystagmus_present'
}

HEADACHE_FIELDS = {
    'h_present',
    'h_completely_resolved',
    'h_first_onset',
    'h_current_onset',
    'h_temporal_pattern',
    'h_flareup_usual_duration',
    'h_inter_flareup_interval',
    'h_complete_resolution',
    'h_baseline_severity',
    'h_worst_severity',
    'h_current_severity',
    'h_description',
    'h_location',
    'h_worse_on_straining',
    'h_time_of_day'
}

EYE_PAIN_AND_CHANGES_FIELDS = {
    'ep_present',
    'ep_completely_resolved',
    'ep_first_onset',
    'ep_temporal_pattern',
    'ep_onset',
    'ep_severity',
    'ep_worse_on_eye_movements',
    'dry_gritty_sensation',
    'appearance_changes_present',
    'ac_redness',
    'ac_discharge',
    'ac_proptosis',
    'ac_ptosis',
    'ac_pupillary_changes',
    'ac_rashes'
}

HEALTHCARE_CONTACTS_FIELDS = {
    'hc_contact_occurred',
    'hc_investigations_and_treatments'
}

OTHER_SYMPTOMS_FIELDS = {
    'other_symptoms'
}

FUNCTIONAL_IMPACT_FIELDS = {
    'functional_impact'
}

# Follow-up blocks (triggered based on episode-specific data)
# These are episode-specific, not shared
FOLLOW_UP_BLOCK_1_FIELDS = {
    'previous_visual_loss_episodes',
    'uhthoff_phenomenon',
    'pulfrich_phenomenon'
}

FOLLOW_UP_BLOCK_2_FIELDS = {
    'scalp_tenderness',
    'jaw_claudication',
    'shoulder_girdle_pain'
}

FOLLOW_UP_BLOCK_3_FIELDS = {
    'acromegalic_features',
    'nipple_discharge',
    'menstrual_changes',
    'erectile_dysfunction',
    'breast_growth',
    'temperature_intolerance'
}

FOLLOW_UP_BLOCK_4_FIELDS = {
    'nutritional_factors',
    'toxic_medications'
}

FOLLOW_UP_BLOCK_5_FIELDS = {
    'cat_exposure'
}

FOLLOW_UP_BLOCK_6_FIELDS = {
    'difficulty_reading',
    'can_read_by_spelling',
    'difficulty_recognising_people',
    'can_recognise_people_by_voice',
    'trouble_navigating',
    'can_see_whole_picture',
    'can_see_moving_water',
    'can_see_car_movement'
}

# Combine all episode-specific fields
EPISODE_FIELDS = (
    VISION_LOSS_FIELDS |
    VISUAL_DISTURBANCES_FIELDS |
    HEADACHE_FIELDS |
    EYE_PAIN_AND_CHANGES_FIELDS |
    HEALTHCARE_CONTACTS_FIELDS |
    OTHER_SYMPTOMS_FIELDS |
    FUNCTIONAL_IMPACT_FIELDS |
    FOLLOW_UP_BLOCK_1_FIELDS |
    FOLLOW_UP_BLOCK_2_FIELDS |
    FOLLOW_UP_BLOCK_3_FIELDS |
    FOLLOW_UP_BLOCK_4_FIELDS |
    FOLLOW_UP_BLOCK_5_FIELDS |
    FOLLOW_UP_BLOCK_6_FIELDS
)

# Shared data fields (not episode-specific)
# Based on clinical_data_model.json v2.0.0

SHARED_FIELDS = {
    # Episode transition control
    'additional_episodes_present',
    
    # Past medical history (array)
    'past_medical_history',
    
    # Medications (array)
    'medications',
    
    # Family history (array)
    'family_history',
    
    # Allergies (array)
    'allergies',
    
    # Social history (nested object fields - dot notation)
    'social_history',
    'social_history.smoking',
    'social_history.smoking.status',
    'social_history.smoking.pack_years',
    'social_history.alcohol',
    'social_history.alcohol.units_per_week',
    'social_history.alcohol.type',
    'social_history.illicit_drugs',
    'social_history.illicit_drugs.status',
    'social_history.illicit_drugs.type',
    'social_history.illicit_drugs.frequency',
    'social_history.occupation',
    'social_history.occupation.current',
    'social_history.occupation.past',
    
    # Systems review (nested object fields - dot notation)
    'systems_review',
    'systems_review.general_health',
    'systems_review.general_health.chills',
    'systems_review.general_health.chills_details',
    'systems_review.general_health.fevers',
    'systems_review.general_health.fever_details',
    'systems_review.general_health.night_sweats',
    'systems_review.general_health.night_sweats_details',
    'systems_review.general_health.fatigue',
    'systems_review.general_health.fatigue_details',
    'systems_review.general_health.appetite_or_weight_change',
    'systems_review.general_health.appetite_weight_details',
    'systems_review.general_health.lumps',
    'systems_review.general_health.lumps_details',
    'systems_review.general_health.unwell',
    'systems_review.general_health.unwell_details',
    
    # Placeholder systems (to be populated in future versions)
    'systems_review.neurological',
    'systems_review.ear_nose_throat',
    'systems_review.skin',
    'systems_review.respiratory',
    'systems_review.cardiovascular',
    'systems_review.blood',
    'systems_review.gastrointestinal',
    'systems_review.musculoskeletal',
    'systems_review.genitourinary',
    'systems_review.other'
}


def classify_field(field_name: str) -> Literal['episode', 'shared', 'unknown']:
    """
    Classify a field as episode-specific, shared, or unknown
    
    Args:
        field_name: Field name to classify
        
    Returns:
        'episode': Field belongs to current episode
        'shared': Field is shared across all episodes
        'unknown': Field not recognized in schema
        
    Examples:
        >>> classify_field('vl_laterality')
        'episode'
        
        >>> classify_field('medications')
        'shared'
        
        >>> classify_field('unknown_field')
        'unknown'
    """
    if field_name in EPISODE_FIELDS:
        return 'episode'
    elif field_name in SHARED_FIELDS:
        return 'shared'
    else:
        return 'unknown'


def get_all_episode_fields() -> Set[str]:
    """
    Get flat set of all episode field names
    
    Returns:
        Set of episode-specific field names
    """
    return EPISODE_FIELDS.copy()


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
    return field_name in EPISODE_FIELDS


def is_shared_field(field_name: str) -> bool:
    """
    Check if field is shared data
    
    Args:
        field_name: Field name to check
        
    Returns:
        True if shared field
    """
    return field_name in SHARED_FIELDS


def get_episode_field_count() -> int:
    """Get total number of episode-specific fields"""
    return len(EPISODE_FIELDS)


def get_shared_field_count() -> int:
    """Get total number of shared fields"""
    return len(SHARED_FIELDS)