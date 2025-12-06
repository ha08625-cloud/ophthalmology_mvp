"""
Integration test for Dialogue Manager V2

Tests with real State Manager V2, mocked other modules
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.dialogue_manager_v2 import DialogueManagerV2
from backend.core.state_manager_v2 import StateManagerV2


# ========================
# Mock Modules (from unit tests)
# ========================

class MockQuestionSelector:
    """Mock Question Selector with episode-aware questioning"""
    
    def __init__(self):
        self.episode = 1
        self.questions_per_episode = {
            1: [
                {'id': 'vl_1', 'question': 'Which eye is affected?', 'field': 'vl_laterality'},
                {'id': 'vl_2', 'question': 'When did it start?', 'field': 'vl_first_onset'},
                {'id': 'vl_3', 'question': 'How quickly did it develop?', 'field': 'vl_onset_speed'}
            ],
            2: [
                {'id': 'h_1', 'question': 'Do you have a headache?', 'field': 'h_present'},
                {'id': 'h_2', 'question': 'Where is the headache located?', 'field': 'h_location'}
            ]
        }
        self.current_index = 0
    
    def get_next_question(self):
        """Return next question for current episode"""
        if self.episode not in self.questions_per_episode:
            return None
        
        questions = self.questions_per_episode[self.episode]
        
        if self.current_index >= len(questions):
            return None  # Episode complete
        
        question = questions[self.current_index]
        self.current_index += 1
        return question
    
    def advance_to_episode(self, episode_id):
        """Move to next episode"""
        self.episode = episode_id
        self.current_index = 0


class MockResponseParser:
    """Mock Response Parser with realistic extractions"""
    
    def parse(self, question, patient_response):
        """Extract fields based on question and response"""
        question_id = question.get('id')
        response_lower = patient_response.lower()
        
        # Handle episode transition
        if question_id == 'episode_transition':
            if any(word in response_lower for word in ['yes', 'yeah', 'yep']):
                return {'additional_episodes_present': True}
            elif any(word in response_lower for word in ['no', 'nope', 'nah']):
                return {'additional_episodes_present': False}
            return {}  # Unclear
        
        # Vision loss questions
        if question_id == 'vl_1':
            if 'right' in response_lower:
                return {'vl_laterality': 'monocular_right'}
            elif 'left' in response_lower:
                return {'vl_laterality': 'monocular_left'}
            elif 'both' in response_lower:
                return {'vl_laterality': 'binocular'}
        
        elif question_id == 'vl_2':
            # Extract onset time
            return {'vl_first_onset': patient_response}
        
        elif question_id == 'vl_3':
            if 'sudden' in response_lower:
                return {'vl_onset_speed': 'acute'}
            elif 'gradual' in response_lower or 'slowly' in response_lower:
                return {'vl_onset_speed': 'chronic'}
            return {'vl_onset_speed': 'subacute'}
        
        # Headache questions
        elif question_id == 'h_1':
            if 'yes' in response_lower:
                return {'h_present': True}
            elif 'no' in response_lower:
                return {'h_present': False}
        
        elif question_id == 'h_2':
            return {'h_location': patient_response}
        
        return {}


class MockJSONFormatter:
    """Mock JSON Formatter"""
    
    def to_dict(self, state_data, consultation_id=None):
        return {
            'metadata': {'consultation_id': consultation_id},
            'episodes': state_data.get('episodes', []),
            'shared_data': state_data.get('shared_data', {})
        }


class MockSummaryGenerator:
    """Mock Summary Generator"""
    
    def generate(self, dialogue_history, structured_data, **kwargs):
        return "Mock multi-episode clinical summary"


# ========================
# Integration Test
# ========================

def test_two_episode_consultation_with_real_state():
    """
    Full 2-episode flow with real State Manager V2
    
    Episode 1: Vision loss (3 questions)
    Episode 2: Headache (2 questions)
    
    Verifies:
    - Episodes created correctly in real state manager
    - Fields routed to correct episode
    - Dialogue history per episode
    - Export methods work
    """
    print("\nIntegration Test: Two-Episode Consultation")
    print("=" * 60)
    
    # Create REAL State Manager V2
    state = StateManagerV2()
    
    # Create mock selector
    selector = MockQuestionSelector()
    
    # Hook state creation to notify selector
    original_create = state.create_episode
    def create_with_selector_update(symptom_type="visual_loss"):
        episode_id = original_create(symptom_type)
        if episode_id > 1:
            selector.advance_to_episode(episode_id)
        return episode_id
    state.create_episode = create_with_selector_update
    
    # Create other mocks
    parser = MockResponseParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    # Create Dialogue Manager V2
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Simulate patient responses
    responses = [
        'My right eye',  # vl_1 - laterality
        '3 months ago',  # vl_2 - onset
        'It was sudden',  # vl_3 - speed
        'yes',  # Episode transition - create episode 2
        'Yes I do',  # h_1 - headache present
        'Front of my head',  # h_2 - location
        'no'  # Final transition - no more episodes
    ]
    
    # Create input function
    responses_iter = iter(responses)
    def mock_input(prompt=""):
        return next(responses_iter)
    
    # Collect output
    output_log = []
    def mock_output(text):
        output_log.append(str(text))
    
    # Run consultation
    result = manager.run_consultation(
        input_fn=mock_input,
        output_fn=mock_output,
        output_dir="/tmp"
    )
    
    # Verify results
    print("\n1. Checking consultation completion...")
    assert result['completed'] == True, "Consultation should complete naturally"
    assert result['total_episodes'] == 2, f"Expected 2 episodes, got {result['total_episodes']}"
    assert result['total_questions'] == 5, f"Expected 5 questions, got {result['total_questions']}"
    print("   ✓ Consultation completed with 2 episodes, 5 questions")
    
    print("\n2. Checking Episode 1 data...")
    episode1 = state.get_episode(1)
    assert episode1['vl_laterality'] == 'monocular_right', f"Wrong laterality: {episode1.get('vl_laterality')}"
    assert episode1['vl_first_onset'] == '3 months ago', f"Wrong onset: {episode1.get('vl_first_onset')}"
    assert episode1['vl_onset_speed'] == 'acute', f"Wrong speed: {episode1.get('vl_onset_speed')}"
    print("   ✓ Episode 1 fields correct (vision loss)")
    
    print("\n3. Checking Episode 2 data...")
    episode2 = state.get_episode(2)
    assert episode2['h_present'] == True, f"Wrong h_present: {episode2.get('h_present')}"
    assert episode2['h_location'] == 'Front of my head', f"Wrong location: {episode2.get('h_location')}"
    print("   ✓ Episode 2 fields correct (headache)")
    
    print("\n4. Checking dialogue history separation...")
    dialogue1 = state.get_dialogue_history(1)
    dialogue2 = state.get_dialogue_history(2)
    assert len(dialogue1) == 3, f"Episode 1 should have 3 turns, got {len(dialogue1)}"
    assert len(dialogue2) == 2, f"Episode 2 should have 2 turns, got {len(dialogue2)}"
    assert dialogue1[0]['response'] == 'My right eye', "First response wrong"
    assert dialogue2[0]['response'] == 'Yes I do', "Episode 2 first response wrong"
    print("   ✓ Dialogue history correctly separated by episode")
    
    print("\n5. Checking export methods...")
    json_export = state.export_for_json()
    assert 'episodes' in json_export, "JSON export missing episodes"
    assert 'shared_data' in json_export, "JSON export missing shared_data"
    assert len(json_export['episodes']) == 2, f"JSON export has {len(json_export['episodes'])} episodes"
    print("   ✓ export_for_json() works correctly")
    
    summary_export = state.export_for_summary()
    assert 'episodes' in summary_export, "Summary export missing episodes"
    assert 'dialogue_history' in summary_export, "Summary export missing dialogue_history"
    assert len(summary_export['dialogue_history']) == 2, "Should have dialogue for 2 episodes"
    print("   ✓ export_for_summary() works correctly")
    
    print("\n6. Checking state summary stats...")
    stats = state.get_summary_stats()
    assert stats['total_episodes'] == 2
    assert stats['total_dialogue_turns'] == 5
    print(f"   ✓ Stats: {stats['total_episodes']} episodes, {stats['total_dialogue_turns']} turns")
    
    print("\n" + "=" * 60)
    print("Integration test PASSED!\n")


if __name__ == '__main__':
    test_two_episode_consultation_with_real_state()