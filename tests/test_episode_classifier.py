"""
Unit tests for Episode Classifier

Tests field classification logic against schema v2.0.1
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.utils.episode_classifier import (
    classify_field,
    get_all_episode_fields,
    get_all_shared_fields,
    is_episode_field,
    is_shared_field,
    get_episode_field_count,
    get_shared_field_count
)


def test_classify_vision_loss_fields():
    """Test vision loss fields classified as episode-specific"""
    vision_loss_samples = [
        'vl_laterality',
        'vl_completely_resolved',
        'vl_first_onset',
        'vl_temporal_pattern',
        'vl_degree',
        'agnosia_present'
    ]
    
    for field in vision_loss_samples:
        result = classify_field(field)
        assert result == 'episode', f"{field} should be 'episode', got '{result}'"
    
    print("✓ Vision loss fields classified correctly")


def test_classify_visual_disturbances_fields():
    """Test visual disturbances fields classified as episode-specific"""
    disturbance_samples = [
        'hallucinations_present',
        'cp_present',
        'cp_laterality',
        'vp_present',
        'vp_followed_by_headache',
        'dp_present',
        'vertigo_present',
        'nystagmus_present'
    ]
    
    for field in disturbance_samples:
        result = classify_field(field)
        assert result == 'episode', f"{field} should be 'episode', got '{result}'"
    
    print("✓ Visual disturbances fields classified correctly")


def test_classify_headache_fields():
    """Test headache fields classified as episode-specific"""
    headache_samples = [
        'h_present',
        'h_completely_resolved',
        'h_first_onset',
        'h_temporal_pattern',
        'h_worse_on_straining'
    ]
    
    for field in headache_samples:
        result = classify_field(field)
        assert result == 'episode', f"{field} should be 'episode', got '{result}'"
    
    print("✓ Headache fields classified correctly")


def test_classify_eye_pain_fields():
    """Test eye pain and appearance fields classified as episode-specific"""
    eye_pain_samples = [
        'ep_present',
        'ep_severity',
        'appearance_changes_present',
        'ac_redness',
        'ac_proptosis',
        'dry_gritty_sensation'
    ]
    
    for field in eye_pain_samples:
        result = classify_field(field)
        assert result == 'episode', f"{field} should be 'episode', got '{result}'"
    
    print("✓ Eye pain/appearance fields classified correctly")


def test_classify_follow_up_block_fields():
    """Test follow-up block fields classified as episode-specific"""
    block_samples = [
        # Block 1 (Optic Neuritis)
        'previous_visual_loss_episodes',
        'uhthoff_phenomenon',
        
        # Block 2 (GCA)
        'scalp_tenderness',
        'jaw_claudication',
        
        # Block 3 (Pituitary)
        'acromegalic_features',
        'nipple_discharge',
        
        # Block 6 (Higher visual processing)
        'difficulty_reading',
        'can_see_moving_water'
    ]
    
    for field in block_samples:
        result = classify_field(field)
        assert result == 'episode', f"{field} should be 'episode', got '{result}'"
    
    print("✓ Follow-up block fields classified correctly")


def test_classify_shared_fields():
    """Test shared data fields classified correctly"""
    shared_samples = [
        'additional_episodes_present',
        'past_medical_history',
        'medications',
        'family_history',
        'smoking_status',
        'occupation'
    ]
    
    for field in shared_samples:
        result = classify_field(field)
        assert result == 'shared', f"{field} should be 'shared', got '{result}'"
    
    print("✓ Shared fields classified correctly")


def test_classify_unknown_fields():
    """Test unknown fields classified correctly"""
    unknown_samples = [
        'totally_made_up_field',
        'random_data',
        'not_in_schema',
        'future_field_name'
    ]
    
    for field in unknown_samples:
        result = classify_field(field)
        assert result == 'unknown', f"{field} should be 'unknown', got '{result}'"
    
    print("✓ Unknown fields classified correctly")


def test_is_episode_field():
    """Test is_episode_field() helper"""
    assert is_episode_field('vl_laterality') == True
    assert is_episode_field('h_present') == True
    assert is_episode_field('medications') == False
    assert is_episode_field('unknown') == False
    
    print("✓ is_episode_field() works correctly")


def test_is_shared_field():
    """Test is_shared_field() helper"""
    assert is_shared_field('medications') == True
    assert is_shared_field('smoking_status') == True
    assert is_shared_field('vl_laterality') == False
    assert is_shared_field('unknown') == False
    
    print("✓ is_shared_field() works correctly")


def test_get_all_episode_fields():
    """Test get_all_episode_fields() returns correct set"""
    episode_fields = get_all_episode_fields()
    
    assert isinstance(episode_fields, set)
    assert len(episode_fields) > 0
    assert 'vl_laterality' in episode_fields
    assert 'h_present' in episode_fields
    assert 'medications' not in episode_fields
    
    print(f"✓ get_all_episode_fields() returns {len(episode_fields)} fields")


def test_get_all_shared_fields():
    """Test get_all_shared_fields() returns correct set"""
    shared_fields = get_all_shared_fields()
    
    assert isinstance(shared_fields, set)
    assert len(shared_fields) > 0
    assert 'medications' in shared_fields
    assert 'additional_episodes_present' in shared_fields
    assert 'vl_laterality' not in shared_fields
    
    print(f"✓ get_all_shared_fields() returns {len(shared_fields)} fields")


def test_field_counts():
    """Test field count helpers"""
    episode_count = get_episode_field_count()
    shared_count = get_shared_field_count()
    
    assert episode_count > 0
    assert shared_count > 0
    assert episode_count > shared_count  # Episode fields should outnumber shared
    
    print(f"✓ Field counts: {episode_count} episode, {shared_count} shared")


def test_no_field_overlap():
    """Test that no field appears in both episode and shared sets"""
    episode_fields = get_all_episode_fields()
    shared_fields = get_all_shared_fields()
    
    overlap = episode_fields & shared_fields
    
    assert len(overlap) == 0, f"Fields appear in both sets: {overlap}"
    
    print("✓ No overlap between episode and shared fields")


def test_all_sections_covered():
    """Test that all major sections have fields defined"""
    episode_fields = get_all_episode_fields()
    
    # Check each section has at least one field
    assert any(f.startswith('vl_') for f in episode_fields), "Vision loss section missing"
    assert any(f.startswith('h_') for f in episode_fields), "Headache section missing"
    assert any(f.startswith('ep_') for f in episode_fields), "Eye pain section missing"
    assert any(f.startswith('cp_') for f in episode_fields), "Color perception missing"
    assert any(f.startswith('vp_') for f in episode_fields), "Visual phenomena missing"
    assert any(f.startswith('dp_') for f in episode_fields), "Diplopia missing"
    assert 'hallucinations_present' in episode_fields, "Hallucinations missing"
    assert 'hc_contact_occurred' in episode_fields, "Healthcare contacts missing"
    
    print("✓ All major sections covered")


if __name__ == '__main__':
    print("\nTesting Episode Classifier...")
    print("=" * 60)
    
    test_classify_vision_loss_fields()
    test_classify_visual_disturbances_fields()
    test_classify_headache_fields()
    test_classify_eye_pain_fields()
    test_classify_follow_up_block_fields()
    test_classify_shared_fields()
    test_classify_unknown_fields()
    test_is_episode_field()
    test_is_shared_field()
    test_get_all_episode_fields()
    test_get_all_shared_fields()
    test_field_counts()
    test_no_field_overlap()
    test_all_sections_covered()
    
    print("=" * 60)
    print("All Episode Classifier tests passed!\n")