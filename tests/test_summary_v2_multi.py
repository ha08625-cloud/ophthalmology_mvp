"""
Test Summary Generator V2 - Multi Episode

Test summary generation with multiple episodes.
"""

import sys

# Mock HuggingFace client BEFORE importing summary_generator
class MockHFClient:
    """Mock HuggingFace client that returns canned responses based on episode"""
    
    def __init__(self):
        self._loaded = True
        self.call_count = 0
    
    def is_loaded(self):
        return self._loaded
    
    def generate(self, prompt, max_tokens=256, temperature=0.3):
        """Return different responses for different episodes"""
        self.call_count += 1
        
        if "EPISODE 1" in prompt:
            return """In this episode, you report sudden vision loss in your right eye that started 3 months ago. The vision loss developed acutely and has been permanent. You describe peripheral field loss with partial vision remaining."""
        elif "EPISODE 2" in prompt:
            return """In this episode, you report severe frontal headache that started 2 weeks ago. The headache is constant and worsens with straining. You rate the pain as 8 out of 10 at its worst. In this episode, you report no visual disturbances."""
        elif "EPISODE 3" in prompt:
            return """In this episode, you report eye pain in your left eye that started 1 week ago. The pain is worse with eye movements and you rate it as 6 out of 10. In this episode, you report no visual loss or headache."""
        else:
            return "In this episode, symptoms as described."


# Mock the hf_client module
class MockHFModule:
    HuggingFaceClient = MockHFClient

sys.modules['hf_client'] = MockHFModule()


def test_multi_episode():
    """Test summary generation with three episodes"""
    print("\n" + "="*60)
    print("TEST: Summary Generator V2 - Multi Episode")
    print("="*60)
    
    from backend.core.summary_generator_v2 import SummaryGeneratorV2
    
    mock_client = MockHFClient()
    generator = SummaryGeneratorV2(mock_client)
    print("✓ Generator initialized")
    
    # Create test data with 3 episodes
    consultation_data = {
        'episodes': [
            {
                'episode_id': 1,
                'timestamp_started': '2024-09-10T10:00:00Z',
                'visual_loss_present': True,
                'vl_laterality': 'right',
                'vl_onset_speed': 'acute'
            },
            {
                'episode_id': 2,
                'timestamp_started': '2024-11-25T14:00:00Z',
                'h_present': True,
                'h_location': 'frontal',
                'h_temporal_pattern': 'permanent',
                'h_worst_severity': 8
            },
            {
                'episode_id': 3,
                'timestamp_started': '2024-12-01T09:00:00Z',
                'ep_present': True,
                'ep_laterality': 'left',
                'ep_worse_on_eye_movements': True,
                'ep_severity': 6
            }
        ],
        'shared_data': {
            'past_medical_history': [
                {'condition': 'Type 2 Diabetes', 'diagnosed_when': '2018', 'current_status': 'managed'}
            ],
            'medications': [
                {'medication_name': 'Metformin', 'dose': '500mg', 'frequency': 'twice daily'}
            ],
            'family_history': [
                {'condition': 'Glaucoma', 'relationship': 'Mother'}
            ],
            'allergies': [
                {'allergen': 'Penicillin', 'reaction': 'rash'}
            ],
            'social_history': {
                'smoking': {'status': 'former', 'pack_years': 10},
                'alcohol': {'units_per_week': 7, 'type': 'wine'},
                'illicit_drugs': {'status': 'never'},
                'occupation': {'current': 'Retired', 'past': 'Engineer'}
            }
        },
        'dialogue_history': {
            1: [
                {
                    'turn_id': 1,
                    'timestamp': '2024-12-08T10:01:00Z',
                    'question_id': 'vl_1',
                    'question': 'Have you experienced visual loss?',
                    'response': 'Yes, my right eye went blurry 3 months ago',
                    'extracted': {}
                }
            ],
            2: [
                {
                    'turn_id': 1,
                    'timestamp': '2024-12-08T10:10:00Z',
                    'question_id': 'h_1',
                    'question': 'Are you experiencing headache?',
                    'response': 'Yes, terrible frontal headache for 2 weeks',
                    'extracted': {}
                }
            ],
            3: [
                {
                    'turn_id': 1,
                    'timestamp': '2024-12-08T10:20:00Z',
                    'question_id': 'ep_1',
                    'question': 'Do you have eye pain?',
                    'response': 'Yes, my left eye hurts especially when I move it',
                    'extracted': {}
                }
            ]
        }
    }
    
    print("✓ Test data created (3 episodes)")
    
    # Generate summary
    print("\nGenerating summary...")
    summary = generator.generate(consultation_data, temperature=0.1)
    
    print(f"✓ Summary generated")
    print(f"  Length: {len(summary)} characters")
    print(f"  LLM called {mock_client.call_count} times")
    
    # Display summary
    print("\n" + "="*60)
    print("GENERATED SUMMARY")
    print("="*60)
    print(summary)
    print("="*60)
    
    # Verify structure
    episode_count = summary.count("In this episode")
    assert episode_count >= 3, f"Expected at least 3 'In this episode' phrases, found {episode_count}"
    
    # Count episodes by paragraph separation (double newlines between episodes)
    # Episodes end before the shared data section (triple newlines)
    episode_section = summary.split("\n\n\n")[0]  # Everything before shared data
    episodes_found = episode_section.split("\n\n")
    print(f"  Found {len(episodes_found)} episode paragraphs")
    
    assert "Past Medical History" in summary
    assert "Diabetes" in summary
    assert "Metformin" in summary
    assert "Glaucoma" in summary
    assert "Penicillin" in summary
    assert "Former smoker (10 pack-years)" in summary
    assert "7 units per week" in summary
    assert "Retired" in summary
    
    # Check episodes are separate
    assert "vision loss" in summary.lower()
    assert "headache" in summary.lower()
    assert "eye pain" in summary.lower()
    
    print("\n✓ All structure checks passed")
    print(f"✓ Found 3 distinct episodes with {episode_count} total episode framings")
    print("✓ All shared data sections present")
    
    # Save to file
    output_path = "/tmp/test_summary_multi_episode.txt"
    generator.save_summary(summary, output_path)
    print(f"✓ Summary saved to {output_path}")
    
    print("\n" + "="*60)
    print("TEST PASSED")
    print("="*60)


if __name__ == '__main__':
    try:
        test_multi_episode()
        print("\n✓ Summary Generator V2 multi-episode test PASSED")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)