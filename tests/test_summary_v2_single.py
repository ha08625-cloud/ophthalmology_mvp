"""
Test Summary Generator V2 - Single Episode

Basic test to verify the module works with one episode.
"""

import sys
import json
from datetime import datetime, timezone

# Mock HuggingFace client BEFORE importing summary_generator
class MockHFClient:
    """Mock HuggingFace client that returns canned responses"""
    
    def __init__(self):
        self._loaded = True
    
    def is_loaded(self):
        return self._loaded
    
    def generate(self, prompt, max_tokens=256, temperature=0.3):
        """Return a simple test response"""
        return """In this episode, you report sudden vision loss in your right eye that started 3 weeks ago. The vision loss developed acutely over seconds to minutes and has been permanent since onset. You describe the loss affecting the peripheral field of vision, with partial rather than total loss. You can still count fingers but cannot read fine print.

In this episode, you report no visual disturbances: no hallucinations, colour vision problems, flashing lights, zigzags, double vision, dizziness, or abnormal eye movements.

In this episode, you report no headache.

In this episode, you report no eye pain, dry sensation, or gritty sensation.

In this episode, you report no changes to eye appearance: no redness, discharge, bulging, drooping eyelids, pupillary changes, or rashes."""


# Mock the hf_client module to avoid torch dependency
class MockHFModule:
    HuggingFaceClient = MockHFClient

sys.modules['hf_client'] = MockHFModule()


def test_single_episode():
    """Test summary generation with single episode"""
    print("\n" + "="*60)
    print("TEST: Summary Generator V2 - Single Episode")
    print("="*60)
    
    # Import module (after mocking)
    from backend.core.summary_generator_v2 import SummaryGeneratorV2
    
    # Create mock HF client
    mock_client = MockHFClient()
    
    # Initialize generator
    generator = SummaryGeneratorV2(mock_client)
    print("✓ Generator initialized")
    
    # Create test consultation data
    consultation_data = {
        'episodes': [
            {
                'episode_id': 1,
                'timestamp_started': '2024-12-08T10:00:00Z',
                'timestamp_last_updated': '2024-12-08T10:15:00Z',
                'visual_loss_present': True,
                'vl_single_eye': 'single',
                'vl_laterality': 'right',
                'vl_field': 'peripheral',
                'vl_degree': 'partial',
                'vl_onset_speed': 'acute',
                'vl_temporal_pattern': 'permanent'
            }
        ],
        'shared_data': {
            'past_medical_history': [
                {
                    'condition': 'Hypertension',
                    'diagnosed_when': '2020',
                    'current_status': 'well controlled'
                }
            ],
            'medications': [
                {
                    'medication_name': 'Amlodipine',
                    'dose': '5mg',
                    'frequency': 'once daily',
                    'indication': 'hypertension'
                }
            ],
            'family_history': [],
            'allergies': [],
            'social_history': {
                'smoking': {
                    'status': 'never',
                    'pack_years': None
                },
                'alcohol': {
                    'units_per_week': 0,
                    'type': None
                },
                'illicit_drugs': {
                    'status': 'never',
                    'type': None,
                    'frequency': None
                },
                'occupation': {
                    'current': 'Teacher',
                    'past': None
                }
            }
        },
        'dialogue_history': {
            1: [
                {
                    'turn_id': 1,
                    'timestamp': '2024-12-08T10:01:00Z',
                    'question_id': 'vl_1',
                    'question': 'Have you experienced visual loss in this episode?',
                    'response': 'Yes, in my right eye',
                    'extracted': {'visual_loss_present': True}
                },
                {
                    'turn_id': 2,
                    'timestamp': '2024-12-08T10:02:00Z',
                    'question_id': 'vl_2',
                    'question': 'Which eye is affected?',
                    'response': 'My right eye',
                    'extracted': {'vl_laterality': 'right'}
                },
                {
                    'turn_id': 3,
                    'timestamp': '2024-12-08T10:03:00Z',
                    'question_id': 'vl_3',
                    'question': 'Which part of your vision is affected?',
                    'response': 'The sides, like peripheral vision',
                    'extracted': {'vl_field': 'peripheral'}
                }
            ]
        }
    }
    
    print("✓ Test data created")
    
    # Generate summary
    print("\nGenerating summary...")
    summary = generator.generate(consultation_data, temperature=0.1)
    
    print("✓ Summary generated")
    print(f"  Length: {len(summary)} characters")
    
    # Display summary
    print("\n" + "="*60)
    print("GENERATED SUMMARY")
    print("="*60)
    print(summary)
    print("="*60)
    
    # Verify structure
    assert "In this episode" in summary, "Missing episode framing"
    assert "Past Medical History" in summary, "Missing PMH section"
    assert "Medications" in summary, "Missing medications section"
    assert "Social History" in summary, "Missing social history section"
    assert "Hypertension" in summary, "Missing PMH data"
    assert "Amlodipine" in summary, "Missing medication data"
    assert "Never smoked" in summary, "Missing smoking status"
    assert "Teacher" in summary, "Missing occupation"
    
    print("\n✓ All structure checks passed")
    
    # Save to file
    output_path = "/tmp/test_summary_single_episode.txt"
    generator.save_summary(summary, output_path)
    print(f"✓ Summary saved to {output_path}")
    
    print("\n" + "="*60)
    print("TEST PASSED")
    print("="*60)


if __name__ == '__main__':
    try:
        test_single_episode()
        print("\n✓ Summary Generator V2 single episode test PASSED")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)