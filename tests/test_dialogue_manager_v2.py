"""
Unit tests for Dialogue Manager V2 (Multi-Episode)

Tests orchestration logic with mocked dependencies
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.dialogue_manager_v2 import DialogueManagerV2, ConsultationState


# ========================
# Mock Modules
# ========================

class MockStateManagerV2:
    """Mock State Manager V2 for testing"""
    
    def __init__(self):
        self.episodes = []
        self.shared_data = {}
        self.dialogue_history = {}
    
    def create_episode(self):
        """Create new episode, return ID"""
        episode_id = len(self.episodes) + 1
        self.episodes.append({'episode_id': episode_id})
        self.dialogue_history[episode_id] = []
        return episode_id
    
    def set_episode_field(self, episode_id, field_name, value):
        """Set episode field"""
        self.episodes[episode_id - 1][field_name] = value
    
    def set_shared_field(self, field_name, value):
        """Set shared field"""
        self.shared_data[field_name] = value
    
    def add_dialogue_turn(self, episode_id, question_id, question_text, 
                         patient_response, extracted_fields):
        """Add dialogue turn"""
        self.dialogue_history[episode_id].append({
            'question_id': question_id,
            'question': question_text,
            'response': patient_response,
            'extracted': extracted_fields
        })
    
    def get_episode_count(self):
        """Get number of episodes"""
        return len(self.episodes)
    
    def get_episode(self, episode_id):
        """Get episode data"""
        return self.episodes[episode_id - 1].copy()


class MockQuestionSelector:
    """Mock Question Selector that returns predefined questions"""
    
    def __init__(self, questions):
        """
        Args:
            questions: List of question dicts to return in sequence
        """
        self.questions = questions
        self.index = 0
    
    def get_next_question(self):
        """Return next question or None if complete"""
        if self.index >= len(self.questions):
            return None
        
        question = self.questions[self.index]
        self.index += 1
        return question


class MockResponseParser:
    """Mock Response Parser with controlled extraction"""
    
    def __init__(self, extractions=None):
        """
        Args:
            extractions: Dict mapping question_id -> extracted fields
                        If None, returns empty dict for all questions
        """
        self.extractions = extractions or {}
    
    def parse(self, question, patient_response):
        """Return predefined extraction for question_id"""
        question_id = question.get('id')
        
        # Check for special responses
        if patient_response.lower() in ['quit', 'exit', 'stop']:
            return {}
        
        # Return predefined extraction
        return self.extractions.get(question_id, {})


class MockJSONFormatter:
    """Mock JSON Formatter"""
    
    def to_dict(self, state_data, consultation_id=None):
        """Return dummy JSON dict"""
        return {
            'metadata': {'consultation_id': consultation_id},
            'episodes': state_data.get('episodes', []),
            'shared_data': state_data.get('shared_data', {})
        }


class MockSummaryGenerator:
    """Mock Summary Generator"""
    
    def generate(self, dialogue_history, structured_data, **kwargs):
        """Return dummy summary"""
        return "Mock clinical summary"


# ========================
# Test Utilities
# ========================

def create_mock_manager(question_list, extractions):
    """
    Create DialogueManagerV2 with mocked dependencies
    
    Args:
        question_list: List of question dicts for QuestionSelector
        extractions: Dict of extractions for ResponseParser
        
    Returns:
        DialogueManagerV2 instance with mocks
    """
    state = MockStateManagerV2()
    selector = MockQuestionSelector(question_list)
    parser = MockResponseParser(extractions)
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    return manager


def create_input_function(responses):
    """
    Create input function that returns responses in sequence
    
    Args:
        responses: List of strings to return
        
    Returns:
        Function that acts like input()
    """
    responses_iter = iter(responses)
    
    def mock_input(prompt=""):
        try:
            return next(responses_iter)
        except StopIteration:
            raise EOFError("No more responses")
    
    return mock_input


def create_output_collector():
    """
    Create output function that collects output
    
    Returns:
        tuple: (output_function, list_to_collect_output)
    """
    collected = []
    
    def mock_output(text):
        collected.append(str(text))
    
    return mock_output, collected


# ========================
# Tests
# ========================

def test_initialization():
    """Test Dialogue Manager V2 initializes correctly"""
    state = MockStateManagerV2()
    selector = MockQuestionSelector([])
    parser = MockResponseParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    assert manager.current_episode_id is None
    assert manager.consultation_state == ConsultationState.INITIALIZING
    assert len(manager.errors) == 0
    assert manager.consultation_id is not None
    
    print("✓ Initialization test passed")


def test_field_routing_episode_fields():
    """Test episode-specific fields route to correct episode"""
    questions = [
        {'id': 'vl_1', 'question': 'Which eye?', 'field': 'vl_laterality'}
    ]
    
    extractions = {
        'vl_1': {'vl_laterality': 'monocular_right'}
    }
    
    manager = create_mock_manager(questions, extractions)
    
    # Mock I/O
    input_fn = create_input_function(['Right eye', 'no'])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check field routed to episode
    episode = manager.state.get_episode(1)
    assert 'vl_laterality' in episode
    assert episode['vl_laterality'] == 'monocular_right'
    
    print("✓ Episode field routing test passed")


def test_field_routing_shared_fields():
    """Test shared fields route to shared data"""
    questions = [
        {'id': 'meds_1', 'question': 'Medications?', 'field': 'medications'}
    ]
    
    extractions = {
        'meds_1': {'medications': 'aspirin'}
    }
    
    manager = create_mock_manager(questions, extractions)
    
    # Mock I/O
    input_fn = create_input_function(['Aspirin', 'no'])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check field routed to shared data
    assert 'medications' in manager.state.shared_data
    assert manager.state.shared_data['medications'] == 'aspirin'
    
    print("✓ Shared field routing test passed")


def test_unmapped_fields_quarantined():
    """Test unmapped fields stored in dialogue metadata"""
    questions = [
        {'id': 'q1', 'question': 'Test?', 'field': 'test_field'}
    ]
    
    extractions = {
        'q1': {
            'vl_laterality': 'monocular_right',  # Known field
            'unknown_field': 'some_value'  # Unknown field
        }
    }
    
    manager = create_mock_manager(questions, extractions)
    
    # Mock I/O
    input_fn = create_input_function(['Test response', 'no'])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check unmapped field in dialogue metadata
    dialogue = manager.state.dialogue_history[1][0]
    assert '_unmapped' in dialogue['extracted']
    assert 'unknown_field' in dialogue['extracted']['_unmapped']
    
    # Check unmapped field NOT in episode data
    episode = manager.state.get_episode(1)
    assert 'unknown_field' not in episode
    
    print("✓ Unmapped field quarantine test passed")


def test_episode_creation_first_episode():
    """Test Episode 1 created at start"""
    questions = [
        {'id': 'q1', 'question': 'Test?', 'field': 'test'}
    ]
    
    manager = create_mock_manager(questions, {})
    
    # Mock I/O
    input_fn = create_input_function(['Response', 'no'])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check Episode 1 created
    assert manager.state.get_episode_count() == 1
    episode = manager.state.get_episode(1)
    assert episode['episode_id'] == 1
    
    print("✓ First episode creation test passed")


def test_episode_transition_clear_yes():
    """Test new episode created on clear 'yes' response"""
    
    # Create custom selector that respects episode boundaries
    class TwoEpisodeSelector:
        def __init__(self):
            self.episode = 1
            self.ep1_index = 0
            self.ep2_index = 0
            self.ep1_questions = [
                {'id': 'q1', 'question': 'Question 1?', 'field': 'field1'}
            ]
            self.ep2_questions = [
                {'id': 'q2', 'question': 'Question 2?', 'field': 'field2'}
            ]
        
        def get_next_question(self):
            if self.episode == 1:
                if self.ep1_index < len(self.ep1_questions):
                    q = self.ep1_questions[self.ep1_index]
                    self.ep1_index += 1
                    return q
                return None  # Episode 1 complete
            elif self.episode == 2:
                if self.ep2_index < len(self.ep2_questions):
                    q = self.ep2_questions[self.ep2_index]
                    self.ep2_index += 1
                    return q
                return None  # Episode 2 complete
        
        def start_episode_2(self):
            self.episode = 2
    
    # Create smart parser that looks at actual response text for transitions
    class SmartParser:
        def __init__(self):
            self.extractions = {
                'q1': {'vl_laterality': 'monocular_right'},
                'q2': {'h_present': True}
            }
        
        def parse(self, question, patient_response):
            question_id = question.get('id')
            
            # Handle episode transition specially
            if question_id == 'episode_transition':
                response_lower = patient_response.lower().strip()
                if response_lower in ['yes', 'y', 'yeah', 'yep']:
                    return {'additional_episodes_present': True}
                elif response_lower in ['no', 'n', 'nope']:
                    return {'additional_episodes_present': False}
                else:
                    return {}  # Unclear
            
            # Regular question
            return self.extractions.get(question_id, {})
    
    # Create manager
    state = MockStateManagerV2()
    selector = TwoEpisodeSelector()
    parser = SmartParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    # Hook create_episode to notify selector
    original_create = state.create_episode
    def create_with_notification():
        episode_id = original_create()
        if episode_id == 2:
            selector.start_episode_2()
        return episode_id
    state.create_episode = create_with_notification
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Mock I/O: answer episode 1, say yes to transition, answer episode 2, say no
    input_fn = create_input_function([
        'Right eye',  # Q1
        'yes',  # Episode transition (create episode 2)
        'Yes I have headaches',  # Q2
        'no'  # Final transition (no episode 3)
    ])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check 2 episodes created
    assert state.get_episode_count() == 2, f"Expected 2 episodes, got {state.get_episode_count()}"
    assert result['total_episodes'] == 2
    
    print("✓ Episode transition (yes) test passed")


def test_episode_transition_clear_no():
    """Test no new episode on clear 'no' response"""
    questions = [
        {'id': 'q1', 'question': 'Question 1?', 'field': 'field1'}
    ]
    
    # Smart parser that handles yes/no for transitions
    class SmartParser:
        def parse(self, question, patient_response):
            question_id = question.get('id')
            
            if question_id == 'episode_transition':
                response_lower = patient_response.lower().strip()
                if response_lower in ['no', 'n', 'nope']:
                    return {'additional_episodes_present': False}
                return {}
            
            return {'vl_laterality': 'monocular_right'}
    
    state = MockStateManagerV2()
    selector = MockQuestionSelector(questions)
    parser = SmartParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Mock I/O
    input_fn = create_input_function(['Right eye', 'no'])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check only 1 episode
    assert state.get_episode_count() == 1
    assert result['total_episodes'] == 1
    
    print("✓ Episode transition (no) test passed")


def test_episode_transition_unclear_retry():
    """Test retry logic on unclear transition response"""
    questions = [
        {'id': 'q1', 'question': 'Question 1?', 'field': 'field1'}
    ]
    
    # First transition response unclear, second clear
    call_count = {'value': 0}
    
    def custom_parser_parse(question, patient_response):
        question_id = question.get('id')
        
        if question_id == 'episode_transition':
            call_count['value'] += 1
            if call_count['value'] == 1:
                # First call: unclear (return empty)
                return {}
            else:
                # Second call: clear no
                return {'additional_episodes_present': False}
        
        return {'vl_laterality': 'monocular_right'}
    
    # Create manager with custom parser
    state = MockStateManagerV2()
    selector = MockQuestionSelector(questions)
    
    class CustomParser:
        def parse(self, question, patient_response):
            return custom_parser_parse(question, patient_response)
    
    parser = CustomParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Mock I/O: first response unclear, second clear
    input_fn = create_input_function([
        'Right eye',  # Q1
        'maybe',  # Unclear transition response
        'no'  # Clear transition response
    ])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check retry happened (only 1 episode created)
    assert state.get_episode_count() == 1
    
    # Check retry message in output
    output_text = ' '.join(output)
    assert "didn't quite catch that" in output_text.lower()
    
    print("✓ Episode transition retry test passed")


def test_episode_transition_max_retries():
    """Test assumes 'no' after max retries"""
    questions = [
        {'id': 'q1', 'question': 'Question 1?', 'field': 'field1'}
    ]
    
    # Always return unclear
    def always_unclear_parser(question, patient_response):
        question_id = question.get('id')
        if question_id == 'episode_transition':
            return {}  # Always unclear
        return {'vl_laterality': 'monocular_right'}
    
    # Create manager
    state = MockStateManagerV2()
    selector = MockQuestionSelector(questions)
    
    class UnclearParser:
        def parse(self, question, patient_response):
            return always_unclear_parser(question, patient_response)
    
    parser = UnclearParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Mock I/O: unclear responses
    input_fn = create_input_function([
        'Right eye',  # Q1
        'unclear1',  # First unclear
        'unclear2'  # Second unclear (max retries)
    ])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check assumed 'no' after max retries (only 1 episode)
    assert state.get_episode_count() == 1
    
    # Check assumption message in output
    output_text = ' '.join(output)
    assert "assume" in output_text.lower()
    
    print("✓ Max retries test passed")


def test_multiple_episodes_flow():
    """Test 3-episode consultation flow"""
    # Episode 1: 2 questions
    # Episode 2: 1 question
    # Episode 3: 1 question
    
    questions_ep1 = [
        {'id': 'ep1_q1', 'question': 'E1 Q1?', 'field': 'f1'},
        {'id': 'ep1_q2', 'question': 'E1 Q2?', 'field': 'f2'}
    ]
    questions_ep2 = [
        {'id': 'ep2_q1', 'question': 'E2 Q1?', 'field': 'f3'}
    ]
    questions_ep3 = [
        {'id': 'ep3_q1', 'question': 'E3 Q1?', 'field': 'f4'}
    ]
    
    # Mock selector that tracks episode boundaries
    class MultiEpisodeSelector:
        def __init__(self):
            self.episode = 1
            self.ep1_index = 0
            self.ep2_index = 0
            self.ep3_index = 0
        
        def get_next_question(self):
            if self.episode == 1:
                if self.ep1_index < len(questions_ep1):
                    q = questions_ep1[self.ep1_index]
                    self.ep1_index += 1
                    return q
                return None
            elif self.episode == 2:
                if self.ep2_index < len(questions_ep2):
                    q = questions_ep2[self.ep2_index]
                    self.ep2_index += 1
                    return q
                return None
            elif self.episode == 3:
                if self.ep3_index < len(questions_ep3):
                    q = questions_ep3[self.ep3_index]
                    self.ep3_index += 1
                    return q
                return None
        
        def advance_episode(self):
            self.episode += 1
    
    # Smart parser
    class SmartParser:
        def parse(self, question, patient_response):
            question_id = question.get('id')
            
            if question_id == 'episode_transition':
                response_lower = patient_response.lower().strip()
                if response_lower in ['yes', 'y']:
                    return {'additional_episodes_present': True}
                elif response_lower in ['no', 'n']:
                    return {'additional_episodes_present': False}
                return {}
            
            # Regular questions
            extractions = {
                'ep1_q1': {'vl_laterality': 'monocular_right'},
                'ep1_q2': {'vl_onset_speed': 'acute'},
                'ep2_q1': {'h_present': True},
                'ep3_q1': {'ep_present': True}
            }
            return extractions.get(question_id, {})
    
    # Create manager
    state = MockStateManagerV2()
    selector = MultiEpisodeSelector()
    parser = SmartParser()
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    # Hook create_episode
    original_create = state.create_episode
    def create_with_notification():
        episode_id = original_create()
        if episode_id > 1:
            selector.advance_episode()
        return episode_id
    state.create_episode = create_with_notification
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Mock I/O
    input_fn = create_input_function([
        'Response E1Q1',  # Episode 1, Q1
        'Response E1Q2',  # Episode 1, Q2
        'yes',  # Transition to Episode 2
        'Response E2Q1',  # Episode 2, Q1
        'yes',  # Transition to Episode 3
        'Response E3Q1',  # Episode 3, Q1
        'no'  # No more episodes
    ])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check 3 episodes created
    assert state.get_episode_count() == 3, f"Expected 3 episodes, got {state.get_episode_count()}"
    assert result['total_episodes'] == 3
    assert result['completed'] == True
    
    print("✓ Multiple episodes flow test passed")


def test_early_exit_command():
    """Test early exit via 'quit' command"""
    questions = [
        {'id': 'q1', 'question': 'Question 1?', 'field': 'field1'},
        {'id': 'q2', 'question': 'Question 2?', 'field': 'field2'}
    ]
    
    manager = create_mock_manager(questions, {})
    
    # Mock I/O: quit after first question
    input_fn = create_input_function(['Response 1', 'quit'])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check early exit
    assert result['completed'] == False
    assert result['total_questions'] < 2
    
    print("✓ Early exit test passed")


def test_dialogue_history_per_episode():
    """Test dialogue history tracked per episode"""
    questions = [
        {'id': 'ep1_q1', 'question': 'E1 Q1?', 'field': 'f1'},
        {'id': 'ep2_q1', 'question': 'E2 Q1?', 'field': 'f2'}
    ]
    
    extractions = {
        'ep1_q1': {'vl_laterality': 'monocular_right'},
        'episode_transition': {'additional_episodes_present': True},
        'ep2_q1': {'h_present': True}
    }
    
    # Create multi-episode selector
    class TwoEpisodeSelector:
        def __init__(self):
            self.index = 0
            self.episode = 1
        
        def get_next_question(self):
            if self.episode == 1 and self.index == 0:
                self.index += 1
                return questions[0]
            elif self.episode == 2 and self.index == 1:
                self.index += 1
                return questions[1]
            return None
        
        def start_episode_2(self):
            self.episode = 2
    
    state = MockStateManagerV2()
    selector = TwoEpisodeSelector()
    parser = MockResponseParser(extractions)
    formatter = MockJSONFormatter()
    generator = MockSummaryGenerator()
    
    # Monkey-patch create_episode
    original_create = state.create_episode
    
    def create_with_selector_update():
        episode_id = original_create()
        if episode_id == 2:
            selector.start_episode_2()
        return episode_id
    
    state.create_episode = create_with_selector_update
    
    manager = DialogueManagerV2(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    # Mock I/O
    input_fn = create_input_function([
        'E1 Response',  # Episode 1
        'yes',  # Transition
        'E2 Response',  # Episode 2
        'no'  # End
    ])
    output_fn, output = create_output_collector()
    
    # Run consultation
    result = manager.run_consultation(input_fn, output_fn, output_dir="/tmp")
    
    # Check dialogue history separated by episode
    assert 1 in state.dialogue_history
    assert 2 in state.dialogue_history
    assert len(state.dialogue_history[1]) == 1
    assert len(state.dialogue_history[2]) == 1
    assert state.dialogue_history[1][0]['response'] == 'E1 Response'
    assert state.dialogue_history[2][0]['response'] == 'E2 Response'
    
    print("✓ Dialogue history per episode test passed")


if __name__ == '__main__':
    print("\nTesting Dialogue Manager V2...")
    print("=" * 60)
    
    test_initialization()
    test_field_routing_episode_fields()
    test_field_routing_shared_fields()
    test_unmapped_fields_quarantined()
    test_episode_creation_first_episode()
    test_episode_transition_clear_yes()
    test_episode_transition_clear_no()
    test_episode_transition_unclear_retry()
    test_episode_transition_max_retries()
    test_multiple_episodes_flow()
    test_early_exit_command()
    test_dialogue_history_per_episode()
    
    print("=" * 60)
    print("All Dialogue Manager V2 tests passed!\n")