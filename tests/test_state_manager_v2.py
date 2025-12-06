"""
Test State Manager V2 - Multi-episode state management

Run with: python3 tests/test_state_manager_v2.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.state_manager_v2 import StateManagerV2


def test_create_episode():
    """Test episode creation"""
    state = StateManagerV2()
    
    # Create first episode
    ep1_id = state.create_episode("visual_loss")
    assert ep1_id == 1, f"Expected episode_id=1, got {ep1_id}"
    assert state.get_episode_count() == 1
    
    # Create second episode
    ep2_id = state.create_episode("headache")
    assert ep2_id == 2, f"Expected episode_id=2, got {ep2_id}"
    assert state.get_episode_count() == 2
    
    # Check episode list
    ids = state.list_episode_ids()
    assert ids == [1, 2], f"Expected [1, 2], got {ids}"
    
    print("✓ Episode creation test passed")


def test_set_and_get_episode_fields():
    """Test setting and retrieving episode fields"""
    state = StateManagerV2()
    episode_id = state.create_episode("visual_loss")
    
    # Set various field types
    state.set_episode_field(episode_id, 'vl_laterality', 'monocular_right')
    state.set_episode_field(episode_id, 'vl_first_onset', '3 months ago')
    state.set_episode_field(episode_id, 'visual_loss_present', True)
    state.set_episode_field(episode_id, 'currently_active', True)
    
    # Get fields back
    assert state.get_episode_field(episode_id, 'vl_laterality') == 'monocular_right'
    assert state.get_episode_field(episode_id, 'vl_first_onset') == '3 months ago'
    assert state.get_episode_field(episode_id, 'visual_loss_present') == True
    
    # Get entire episode
    episode = state.get_episode(episode_id)
    assert episode['episode_id'] == 1
    assert episode['symptom_type'] == 'visual_loss'
    assert episode['vl_laterality'] == 'monocular_right'
    
    # Test default value
    missing = state.get_episode_field(episode_id, 'nonexistent', default='default_val')
    assert missing == 'default_val'
    
    # Test has_field
    assert state.has_episode_field(episode_id, 'vl_laterality') == True
    assert state.has_episode_field(episode_id, 'nonexistent') == False
    
    print("✓ Episode field operations test passed")


def test_invalid_episode_id():
    """Test error handling for invalid episode IDs"""
    state = StateManagerV2()
    state.create_episode()
    
    # Try to access non-existent episode
    try:
        state.get_episode(999)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "does not exist" in str(e)
    
    try:
        state.set_episode_field(0, 'field', 'value')
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    
    try:
        state.get_episode_field(3, 'field')
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    
    print("✓ Invalid episode ID handling test passed")


def test_multiple_episodes():
    """Test managing multiple episodes with different data"""
    state = StateManagerV2()
    
    # Episode 1: Vision loss in right eye
    ep1 = state.create_episode("visual_loss")
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_right')
    state.set_episode_field(ep1, 'vl_first_onset', '6 months ago')
    state.set_episode_field(ep1, 'currently_active', False)
    state.set_episode_field(ep1, 'completely_resolved', True)
    
    # Episode 2: Vision loss in left eye
    ep2 = state.create_episode("visual_loss")
    state.set_episode_field(ep2, 'vl_laterality', 'monocular_left')
    state.set_episode_field(ep2, 'vl_first_onset', '2 weeks ago')
    state.set_episode_field(ep2, 'currently_active', True)
    state.set_episode_field(ep2, 'completely_resolved', False)
    
    # Episode 3: Headache
    ep3 = state.create_episode("headache")
    state.set_episode_field(ep3, 'h_present', True)
    state.set_episode_field(ep3, 'h_first_onset', 'same time as vision loss')
    
    # Verify isolation between episodes
    assert state.get_episode_field(ep1, 'vl_laterality') == 'monocular_right'
    assert state.get_episode_field(ep2, 'vl_laterality') == 'monocular_left'
    assert state.get_episode_field(ep1, 'currently_active') == False
    assert state.get_episode_field(ep2, 'currently_active') == True
    
    # Episode 3 shouldn't have vision loss fields
    assert state.has_episode_field(ep3, 'vl_laterality') == False
    assert state.has_episode_field(ep3, 'h_present') == True
    
    # Check count
    assert state.get_episode_count() == 3
    
    print("✓ Multiple episodes test passed")


def test_shared_data():
    """Test shared data management"""
    state = StateManagerV2()
    
    # Set simple shared fields
    state.set_shared_field('social_history.smoking_status', 'never')
    state.set_shared_field('social_history.occupation', 'teacher')
    
    # Get shared fields
    smoking = state.get_shared_field('social_history.smoking_status')
    assert smoking == 'never', f"Expected 'never', got {smoking}"
    
    occupation = state.get_shared_field('social_history.occupation')
    assert occupation == 'teacher', f"Expected 'teacher', got {occupation}"
    
    # Test default value
    missing = state.get_shared_field('social_history.nonexistent', default='default')
    assert missing == 'default'
    
    # Append to array fields
    state.append_shared_array('medications', {
        'medication_name': 'aspirin',
        'dose': '75mg',
        'frequency': 'daily'
    })
    
    state.append_shared_array('medications', {
        'medication_name': 'metformin',
        'dose': '500mg',
        'frequency': 'twice daily'
    })
    
    state.append_shared_array('past_medical_history', {
        'condition': 'hypertension',
        'diagnosed_when': '10 years ago',
        'current_status': 'controlled'
    })
    
    # Get shared data
    shared = state.get_shared_data()
    assert len(shared['medications']) == 2
    assert len(shared['past_medical_history']) == 1
    assert shared['medications'][0]['medication_name'] == 'aspirin'
    
    print("✓ Shared data test passed")


def test_dialogue_history():
    """Test dialogue history tracking per episode"""
    state = StateManagerV2()
    
    # Create two episodes
    ep1 = state.create_episode("visual_loss")
    ep2 = state.create_episode("headache")
    
    # Add dialogue turns to episode 1
    state.add_dialogue_turn(
        episode_id=ep1,
        question_id='vl_1',
        question_text='Which eye is affected?',
        patient_response='My right eye',
        extracted_fields={'vl_laterality': 'monocular_right'}
    )
    
    state.add_dialogue_turn(
        episode_id=ep1,
        question_id='vl_2',
        question_text='When did it start?',
        patient_response='About 3 months ago',
        extracted_fields={'vl_first_onset': '3 months ago'}
    )
    
    # Add dialogue turn to episode 2
    state.add_dialogue_turn(
        episode_id=ep2,
        question_id='h_1',
        question_text='Do you have a headache?',
        patient_response='Yes, constant throbbing',
        extracted_fields={'h_present': True, 'h_description': 'constant throbbing'}
    )
    
    # Get dialogue history for episode 1
    ep1_dialogue = state.get_dialogue_history(ep1)
    assert len(ep1_dialogue) == 2
    assert ep1_dialogue[0]['question_id'] == 'vl_1'
    assert ep1_dialogue[1]['question_id'] == 'vl_2'
    
    # Get dialogue history for episode 2
    ep2_dialogue = state.get_dialogue_history(ep2)
    assert len(ep2_dialogue) == 1
    assert ep2_dialogue[0]['question_id'] == 'h_1'
    
    # Get all dialogue history
    all_dialogue = state.get_all_dialogue_history()
    assert len(all_dialogue) == 2
    assert len(all_dialogue[ep1]) == 2
    assert len(all_dialogue[ep2]) == 1
    
    print("✓ Dialogue history test passed")


def test_export_for_json():
    """Test export format for JSON formatter"""
    state = StateManagerV2()
    
    # Create episode with data
    ep1 = state.create_episode("visual_loss")
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_right')
    state.set_episode_field(ep1, 'vl_first_onset', '3 months ago')
    state.set_episode_field(ep1, 'visual_loss_present', True)
    
    # Add shared data
    state.set_shared_field('social_history.smoking_status', 'never')
    state.append_shared_array('medications', {
        'medication_name': 'aspirin',
        'dose': '75mg'
    })
    
    # Export
    exported = state.export_for_json()
    
    # Check structure
    assert 'episodes' in exported
    assert 'shared_data' in exported
    assert 'dialogue_history' not in exported  # Should NOT include dialogue
    
    # Check episodes
    assert len(exported['episodes']) == 1
    assert exported['episodes'][0]['episode_id'] == 1
    assert exported['episodes'][0]['vl_laterality'] == 'monocular_right'
    
    # Check shared data
    assert 'medications' in exported['shared_data']
    assert len(exported['shared_data']['medications']) == 1
    
    # Verify no UI state
    assert 'current_episode_id' not in exported
    
    print("✓ Export for JSON test passed")


def test_export_for_summary():
    """Test export format for summary generator"""
    state = StateManagerV2()
    
    # Create episode with dialogue
    ep1 = state.create_episode("visual_loss")
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_right')
    
    state.add_dialogue_turn(
        episode_id=ep1,
        question_id='vl_1',
        question_text='Which eye?',
        patient_response='Right eye',
        extracted_fields={'vl_laterality': 'monocular_right'}
    )
    
    # Export
    exported = state.export_for_summary()
    
    # Check structure
    assert 'episodes' in exported
    assert 'shared_data' in exported
    assert 'dialogue_history' in exported  # SHOULD include dialogue
    
    # Check dialogue history included
    assert ep1 in exported['dialogue_history']
    assert len(exported['dialogue_history'][ep1]) == 1
    assert exported['dialogue_history'][ep1][0]['question_id'] == 'vl_1'
    
    print("✓ Export for summary test passed")


def test_reset():
    """Test reset functionality"""
    state = StateManagerV2()
    
    # Add data
    ep1 = state.create_episode("visual_loss")
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_right')
    state.add_dialogue_turn(ep1, 'vl_1', 'Question?', 'Answer', {})
    state.set_shared_field('social_history.smoking_status', 'never')
    
    # Verify data exists
    assert state.get_episode_count() == 1
    assert len(state.get_dialogue_history(ep1)) == 1
    
    # Reset
    state.reset()
    
    # Verify everything cleared
    assert state.get_episode_count() == 0
    assert state.list_episode_ids() == []
    shared = state.get_shared_data()
    assert len(shared['medications']) == 0
    assert len(shared['past_medical_history']) == 0
    
    print("✓ Reset test passed")


def test_summary_stats():
    """Test summary statistics"""
    state = StateManagerV2()
    
    # Create episodes with data
    ep1 = state.create_episode("visual_loss")
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_right')
    state.set_episode_field(ep1, 'vl_first_onset', '3 months ago')
    state.add_dialogue_turn(ep1, 'vl_1', 'Q?', 'A', {})
    state.add_dialogue_turn(ep1, 'vl_2', 'Q?', 'A', {})
    
    ep2 = state.create_episode("headache")
    state.set_episode_field(ep2, 'h_present', True)
    state.add_dialogue_turn(ep2, 'h_1', 'Q?', 'A', {})
    
    # Get stats
    stats = state.get_summary_stats()
    
    assert stats['total_episodes'] == 2
    assert stats['episode_ids'] == [1, 2]
    assert stats['total_dialogue_turns'] == 3
    assert stats['total_fields'] > 0
    
    print("✓ Summary stats test passed")


def test_field_overwrite():
    """Test that setting same field twice overwrites (last value wins)"""
    state = StateManagerV2()
    ep1 = state.create_episode("visual_loss")
    
    # Set field
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_right')
    assert state.get_episode_field(ep1, 'vl_laterality') == 'monocular_right'
    
    # Overwrite field
    state.set_episode_field(ep1, 'vl_laterality', 'monocular_left')
    assert state.get_episode_field(ep1, 'vl_laterality') == 'monocular_left'
    
    # Episode should still only have one vl_laterality field
    episode = state.get_episode(ep1)
    laterality_count = sum(1 for k in episode.keys() if k == 'vl_laterality')
    assert laterality_count == 1
    
    print("✓ Field overwrite test passed")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("TESTING STATE MANAGER V2")
    print("="*60 + "\n")
    
    test_create_episode()
    test_set_and_get_episode_fields()
    test_invalid_episode_id()
    test_multiple_episodes()
    test_shared_data()
    test_dialogue_history()
    test_export_for_json()
    test_export_for_summary()
    test_reset()
    test_summary_stats()
    test_field_overwrite()
    
    print("\n" + "="*60)
    print("ALL STATE MANAGER V2 TESTS PASSED ✓")
    print("="*60 + "\n")