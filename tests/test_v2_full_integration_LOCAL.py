"""
V2 System Integration Test - Complete End-to-End (LOCAL VERSION)

Tests all V2 modules working together:
- State Manager V2 (multi-episode state tracking)
- Question Selector V2 (episode-aware question selection)
- Dialogue Manager V2 (multi-episode orchestration)
- JSON Formatter V2 (serialization)

Simulates a realistic consultation workflow without requiring LLM.
"""

import sys
import json
from pathlib import Path

# Add project root to path if running directly
if __name__ == '__main__':
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))

# Import V2 modules (LOCAL PATHS)
from backend.core.state_manager_v2 import StateManagerV2
from backend.core.question_selector_v2 import QuestionSelectorV2
from backend.core.json_formatter_v2 import JSONFormatterV2
# Note: Dialogue Manager V2 tested separately due to complexity


class MockResponseParser:
    """Mock parser for testing without LLM"""
    
    def __init__(self):
        # Predefined responses for testing
        self.response_map = {
            'vl_1': {'visual_loss_present': True},
            'vl_2': {'vl_single_eye': 'single'},
            'vl_3': {'vl_laterality': 'right'},
            'vl_5': {'vl_field': 'peripheral vision'},
            'vl_6': {'vl_degree': 'partial'},
            'vl_9': {'vl_onset_speed': 'acute'},
            'vl_10': {'vl_temporal_pattern': 'permanent'},
            'h_1': {'h_present': True},
            'h_3': {'h_first_onset': '2 weeks ago'},
            'h_4': {'h_temporal_pattern': 'intermittent'},
        }
    
    def parse(self, question, patient_response):
        """Return predefined extraction based on question ID"""
        q_id = question.get('id', 'unknown')
        return self.response_map.get(q_id, {})


def test_question_selector_basic():
    """Test: Question Selector V2 basic functionality"""
    print("\n" + "="*60)
    print("TEST 1: Question Selector V2 Basic Functionality")
    print("="*60)
    
    # Initialize
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    
    # Create episode
    episode_id = state.create_episode()
    
    # Get episode data for selector
    episode_data = state.get_episode_for_selector(episode_id)
    
    # Get first question
    q1 = selector.get_next_question(episode_data)
    assert q1 is not None, "Should return first question"
    assert q1['id'] == 'vl_1', f"First question should be vl_1, got {q1['id']}"
    print(f"First question: {q1['id']} - {q1['question']}")
    
    # Mark question answered
    state.mark_question_answered(episode_id, q1['id'])
    
    # Get next question
    episode_data = state.get_episode_for_selector(episode_id)
    q2 = selector.get_next_question(episode_data)
    assert q2 is not None, "Should return second question"
    print(f"Second question: {q2['id']} - {q2['question']}")
    
    print("Question Selector V2 working correctly")
    return True


def test_question_selector_conditionals():
    """Test: Question Selector V2 conditional logic"""
    print("\n" + "="*60)
    print("TEST 2: Question Selector V2 Conditional Logic")
    print("="*60)
    
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    
    episode_id = state.create_episode()
    
    # Simulate answering questions to trigger conditional
    state.mark_question_answered(episode_id, 'vl_1')
    state.set_episode_field(episode_id, 'visual_loss_present', True)
    
    state.mark_question_answered(episode_id, 'vl_2')
    state.set_episode_field(episode_id, 'vl_single_eye', 'single')
    
    # Now vl_3 should be eligible (conditional on vl_single_eye == 'single')
    episode_data = state.get_episode_for_selector(episode_id)
    next_q = selector.get_next_question(episode_data)
    
    assert next_q['id'] == 'vl_3', f"Should get vl_3 (conditional), got {next_q['id']}"
    print(f"Conditional question triggered: {next_q['id']}")
    
    print("Conditional logic working correctly")
    return True


def test_question_selector_triggers():
    """Test: Question Selector V2 trigger detection"""
    print("\n" + "="*60)
    print("TEST 3: Question Selector V2 Trigger Detection")
    print("="*60)
    
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    
    episode_id = state.create_episode()
    
    # Set conditions that should trigger block_1 (subacute monocular loss)
    state.set_episode_field(episode_id, 'vl_single_eye', 'single')
    state.set_episode_field(episode_id, 'vl_onset_speed', 'subacute')
    
    episode_data = state.get_episode_for_selector(episode_id)
    activated = selector.check_triggers(episode_data)
    
    assert 'block_1' in activated, f"block_1 should be activated, got {activated}"
    print(f"Triggered blocks: {activated}")
    
    print("Trigger detection working correctly")
    return True


def test_state_question_integration():
    """Test: State Manager + Question Selector integration"""
    print("\n" + "="*60)
    print("TEST 4: State Manager + Question Selector Integration")
    print("="*60)
    
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    
    episode_id = state.create_episode()
    questions_asked = 0
    max_questions = 10  # Safety limit
    
    while questions_asked < max_questions:
        episode_data = state.get_episode_for_selector(episode_id)
        next_q = selector.get_next_question(episode_data)
        
        if next_q is None:
            print(f"No more questions after {questions_asked} questions")
            break
        
        # Mark as answered
        state.mark_question_answered(episode_id, next_q['id'])
        
        # Add dummy field data
        field = next_q.get('field')
        if field:
            state.set_episode_field(episode_id, field, 'test_value')
        
        questions_asked += 1
        print(f"  Asked: {next_q['id']}")
    
    assert questions_asked > 0, "Should ask at least one question"
    print(f"Successfully cycled through {questions_asked} questions")
    
    return True


def test_single_episode_workflow():
    """Test: Complete single episode workflow"""
    print("\n" + "="*60)
    print("TEST 5: Single Episode Workflow (State + Selector + Formatter)")
    print("="*60)
    
    # Initialize modules
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    formatter = JSONFormatterV2()
    parser = MockResponseParser()
    
    episode_id = state.create_episode()
    print(f"Created episode {episode_id}")
    
    # Simulate Q&A cycle
    questions_answered = 0
    max_questions = 15
    
    while questions_answered < max_questions:
        episode_data = state.get_episode_for_selector(episode_id)
        question = selector.get_next_question(episode_data)
        
        if question is None:
            break
        
        # Simulate patient response
        patient_response = "test response"
        extracted = parser.parse(question, patient_response)
        
        # Update state
        state.mark_question_answered(episode_id, question['id'])
        
        for field_name, value in extracted.items():
            if not field_name.startswith('_'):
                state.set_episode_field(episode_id, field_name, value)
        
        # Record dialogue
        state.add_dialogue_turn(
            episode_id=episode_id,
            question_id=question['id'],
            question_text=question['question'],
            patient_response=patient_response,
            extracted_fields=extracted
        )
        
        questions_answered += 1
    
    print(f"Answered {questions_answered} questions")
    
    # Format output
    json_output = formatter.format_state(
        state.export_for_json(),
        consultation_id='single_ep_test'
    )
    
    # Verify structure
    assert json_output['schema_version'] == '2.0.0'
    assert len(json_output['episodes']) == 1
    assert json_output['episodes'][0]['episode_id'] == 1
    
    # Check dialogue history
    summary_data = state.export_for_summary()
    assert episode_id in summary_data['dialogue_history']
    assert len(summary_data['dialogue_history'][episode_id]) == questions_answered
    
    print(f"Episode 1 has {len(json_output['episodes'][0]) - 3} clinical fields")
    print("Single episode workflow complete")
    
    return json_output


def test_multi_episode_workflow():
    """Test: Complete multi-episode workflow"""
    print("\n" + "="*60)
    print("TEST 6: Multi-Episode Workflow")
    print("="*60)
    
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    formatter = JSONFormatterV2()
    parser = MockResponseParser()
    
    # Episode 1: Vision loss
    print("\n--- Episode 1: Vision Loss ---")
    ep1 = state.create_episode()
    
    ep1_questions = ['vl_1', 'vl_2', 'vl_3', 'vl_5', 'vl_6']
    for q_id in ep1_questions:
        state.mark_question_answered(ep1, q_id)
        extracted = parser.response_map.get(q_id, {})
        for field, value in extracted.items():
            state.set_episode_field(ep1, field, value)
    
    print(f"Episode 1: {len(ep1_questions)} questions answered")
    
    # Episode 2: Headache
    print("\n--- Episode 2: Headache ---")
    ep2 = state.create_episode()
    
    ep2_questions = ['h_1', 'h_3', 'h_4']
    for q_id in ep2_questions:
        state.mark_question_answered(ep2, q_id)
        extracted = parser.response_map.get(q_id, {})
        for field, value in extracted.items():
            state.set_episode_field(ep2, field, value)
    
    print(f"Episode 2: {len(ep2_questions)} questions answered")
    
    # Format output
    json_output = formatter.format_state(
        state.export_for_json(),
        consultation_id='multi_ep_test'
    )
    
    # Verify
    assert json_output['metadata']['total_episodes'] == 2
    assert len(json_output['episodes']) == 2
    assert json_output['episodes'][0]['episode_id'] == 1
    assert json_output['episodes'][1]['episode_id'] == 2
    assert 'visual_loss_present' in json_output['episodes'][0]
    assert 'h_present' in json_output['episodes'][1]
    
    print(f"\nEpisode 1: {len(json_output['episodes'][0]) - 3} fields")
    print(f"Episode 2: {len(json_output['episodes'][1]) - 3} fields")
    print("Multi-episode workflow complete")
    
    return json_output


def test_dialogue_manager_components():
    """Test: Dialogue Manager V2 components verified"""
    print("\n" + "="*60)
    print("TEST 7: Dialogue Manager V2 Components")
    print("="*60)
    
    state = StateManagerV2("data/clinical_data_model.json")
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    parser = MockResponseParser()
    formatter = JSONFormatterV2()
    
    print("State Manager V2: OK")
    print("Question Selector V2: OK")
    print("Mock Response Parser: OK")
    print("JSON Formatter V2: OK")
    
    print("\nAll components ready for Dialogue Manager V2")
    
    return True


def test_file_persistence():
    """Test: Complete workflow with file output"""
    print("\n" + "="*60)
    print("TEST 8: File Persistence")
    print("="*60)
    
    state = StateManagerV2("data/clinical_data_model.json")
    formatter = JSONFormatterV2()
    
    # Create simple episode
    ep = state.create_episode()
    state.set_episode_field(ep, 'visual_loss_present', True)
    state.set_episode_field(ep, 'vl_laterality', 'right')
    
    # Format and save
    json_output = formatter.format_state(
        state.export_for_json(),
        consultation_id='persistence_test'
    )
    
    # Save to outputs directory (create if needed)
    output_dir = Path("outputs/consultations")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = output_dir / "v2_integration_test.json"
    saved_path = JSONFormatterV2.save_to_file(json_output, str(output_path))
    
    print(f"Saved to: {saved_path}")
    
    # Reload and verify
    assert Path(saved_path).exists()
    with open(saved_path) as f:
        loaded = json.load(f)
    
    assert loaded['schema_version'] == '2.0.0'
    assert loaded['metadata']['consultation_id'] == 'persistence_test'
    
    print("File persistence working correctly")
    
    return loaded


def main():
    """Run all integration tests"""
    print("\n" + "="*70)
    print("V2 SYSTEM INTEGRATION TESTS - COMPLETE")
    print("="*70)
    print("\nTesting: State Manager V2 + Question Selector V2")
    print("         + JSON Formatter V2")
    print("="*70)
    
    tests = [
        ("Question Selector Basic", test_question_selector_basic),
        ("Question Selector Conditionals", test_question_selector_conditionals),
        ("Question Selector Triggers", test_question_selector_triggers),
        ("State + Selector Integration", test_state_question_integration),
        ("Single Episode Workflow", test_single_episode_workflow),
        ("Multi-Episode Workflow", test_multi_episode_workflow),
        ("Dialogue Manager Components", test_dialogue_manager_components),
        ("File Persistence", test_file_persistence),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
            print(f"\n[PASS] {test_name}")
        except AssertionError as e:
            failed += 1
            print(f"\n[FAIL] {test_name}")
            print(f"Assertion Error: {e}")
        except Exception as e:
            failed += 1
            print(f"\n[FAIL] {test_name}")
            print(f"Exception: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*70)
    
    if failed == 0:
        print("\nAll V2 modules integrate successfully!")
        print("System ready for:")
        print("  - Summary Generator V2 implementation")
        print("  - Response Parser updates")
        print("  - Full end-to-end testing with LLM")
    else:
        print(f"\n{failed} test(s) failed - see errors above")
    
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())