# Test script: test_state_export.py

from backend.core.state_manager_v2 import StateManagerV2

# Create state
state = StateManagerV2()

# Episode 1: Vision Loss
ep1 = state.create_episode()
state.set_episode_field(ep1, 'visual_loss_present', True)
state.set_episode_field(ep1, 'vl_laterality', 'right')
state.set_episode_field(ep1, 'vl_onset_speed', 'acute')

state.add_dialogue_turn(
    episode_id=ep1,
    question_id='vl_2',
    question_text='Which eye is affected?',
    patient_response='My right eye',
    extracted_fields={'vl_laterality': 'right'}
)

# Episode 2: Headache
ep2 = state.create_episode()
state.set_episode_field(ep2, 'h_present', True)
state.set_episode_field(ep2, 'h_location', 'frontal')

state.add_dialogue_turn(
    episode_id=ep2,
    question_id='h_1',
    question_text='Do you have a headache?',
    patient_response='Yes, frontal',
    extracted_fields={'h_present': True, 'h_location': 'frontal'}
)

# Shared data
state.set_shared_field('smoking_status', 'never')

# Export both formats
json_export = state.export_for_json()
summary_export = state.export_for_summary()

print("=== EXPORT FOR JSON ===")
import json
print(json.dumps(json_export, indent=2))

print("\n=== EXPORT FOR SUMMARY ===")
print(json.dumps(summary_export, indent=2))