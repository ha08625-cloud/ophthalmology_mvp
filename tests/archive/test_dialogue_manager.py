"""
Unit Tests for Dialogue Manager

Tests:
1. Initialization with all modules
2. Happy path - complete consultation
3. Early exit - user quits
4. Parse error handling - continues consultation
5. Validation integration
6. Output file generation
"""

import sys
import os
import tempfile
import json
from pathlib import Path

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.core.dialogue_manager import DialogueManager, ConsultationState
from backend.core.state_manager import StateManager
from backend.utils.helpers import ConsultationValidator


# Mock modules for testing
class MockQuestionSelector:
    """Mock Question Selector that returns predefined questions"""
    
    def __init__(self, questions):
        """
        Args:
            questions (list): List of question dicts (or None to end)
        """
        self.questions = questions
        self.index = 0
    
    def get_next_question(self):
        """Return next question or None"""
        if self.index >= len(self.questions):
            return None
        
        question = self.questions[self.index]
        self.index += 1
        return question


class MockResponseParser:
    """Mock Response Parser that returns predefined extractions"""
    
    def __init__(self, extractions=None, should_fail=False):
        """
        Args:
            extractions (dict): Map of question_id -> extracted_data
            should_fail (bool): If True, raises error on parse
        """
        self.extractions = extractions or {}
        self.should_fail = should_fail
        self.call_count = 0
    
    def parse(self, question, response):
        """Parse response (mock)"""
        self.call_count += 1
        
        if self.should_fail:
            raise RuntimeError("Mock parse error")
        
        question_id = question.get('id', 'unknown')
        return self.extractions.get(question_id, {})


class MockJSONFormatter:
    """Mock JSON Formatter"""
    
    def __init__(self):
        self.to_dict_calls = 0
        self.save_calls = 0
    
    def to_dict(self, state_data, consultation_id=None):
        """Generate mock JSON"""
        self.to_dict_calls += 1
        return {
            'metadata': {
                'consultation_id': consultation_id or 'mock-id',
                'completeness_score': 0.5
            },
            'chief_complaint': {'_status': {}}
        }
    
    def save(self, json_data, output_path):
        """Save mock JSON"""
        self.save_calls += 1
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(json_data, f)
        return str(Path(output_path).absolute())


class MockSummaryGenerator:
    """Mock Summary Generator"""
    
    def __init__(self):
        self.generate_calls = 0
        self.save_calls = 0
    
    def generate(self, dialogue_history, structured_data, **kwargs):
        """Generate mock summary"""
        self.generate_calls += 1
        return "MOCK CLINICAL SUMMARY\n\nPatient presented with test symptoms."
    
    def save_summary(self, summary_text, output_path):
        """Save mock summary"""
        self.save_calls += 1
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            f.write(summary_text)


def print_test_header(test_name):
    """Print formatted test header"""
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print('='*60)


def test_initialization():
    """Test 1: Dialogue Manager initializes with all modules"""
    print_test_header("Initialization")
    
    try:
        state = StateManager()
        selector = MockQuestionSelector([])
        parser = MockResponseParser()
        formatter = MockJSONFormatter()
        generator = MockSummaryGenerator()
        
        manager = DialogueManager(
            state_manager=state,
            question_selector=selector,
            response_parser=parser,
            json_formatter=formatter,
            summary_generator=generator
        )
        
        print(f"✓ Dialogue Manager initialized")
        print(f"✓ Initial state: {manager.consultation_state}")
        print(f"✓ Consultation ID: {manager.consultation_id}")
        
        assert manager.consultation_state == ConsultationState.INITIALIZING
        assert len(manager.consultation_id) == 8  # Short ID
        assert len(manager.errors) == 0
        
        print("\n✓ PASS: Initialization successful")
        return manager
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_happy_path():
    """Test 2: Complete consultation - happy path"""
    print_test_header("Happy Path - Complete Consultation")
    
    try:
        # Setup modules
        state = StateManager()
        
        questions = [
            {'id': 'q1', 'question': 'What brings you here?', 'field': 'chief_complaint'},
            {'id': 'q2', 'question': 'When did it start?', 'field': 'onset'},
            {'id': 'q3', 'question': 'How severe is it?', 'field': 'severity'}
        ]
        selector = MockQuestionSelector(questions)
        
        extractions = {
            'q1': {'chief_complaint': 'blurry vision'},
            'q2': {'onset': '3 months ago'},
            'q3': {'severity': 'moderate'}
        }
        parser = MockResponseParser(extractions)
        
        formatter = MockJSONFormatter()
        generator = MockSummaryGenerator()
        
        manager = DialogueManager(state, selector, parser, formatter, generator)
        
        # Mock I/O
        responses = ['blurry vision', '3 months ago', 'moderate']
        response_iter = iter(responses)
        
        def mock_input(prompt=""):
            return next(response_iter)
        
        outputs = []
        def mock_output(text):
            outputs.append(text)
        
        # Create temp output dir
        with tempfile.TemporaryDirectory() as tmpdir:
            # Run consultation
            result = manager.run_consultation(
                input_fn=mock_input,
                output_fn=mock_output,
                output_dir=tmpdir
            )
            
            # Validate results
            assert result['completed'] == True, "Should complete naturally"
            assert result['total_questions'] == 3, "Should ask 3 questions"
            assert parser.call_count == 3, "Should parse 3 responses"
            
            print(f"\n✓ Completed: {result['completed']}")
            print(f"✓ Questions asked: {result['total_questions']}")
            print(f"✓ JSON path: {result['json_path']}")
            print(f"✓ Summary path: {result['summary_path']}")
            
            # Check files exist
            assert os.path.exists(result['json_path']), "JSON file should exist"
            assert os.path.exists(result['summary_path']), "Summary file should exist"
            print(f"✓ Output files created")
            
            # Check state
            state_data = state.export_for_json()
            assert 'chief_complaint' in state_data, "Should have chief complaint"
            assert 'onset' in state_data, "Should have onset"
            assert 'severity' in state_data, "Should have severity"
            print(f"✓ State contains {len(state_data)} fields")
            
            print("\n✓ PASS: Happy path successful")
            return result
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_early_exit():
    """Test 3: User exits early"""
    print_test_header("Early Exit - User Quits")
    
    try:
        # Setup modules
        state = StateManager()
        
        questions = [
            {'id': 'q1', 'question': 'Question 1?', 'field': 'f1'},
            {'id': 'q2', 'question': 'Question 2?', 'field': 'f2'},
            {'id': 'q3', 'question': 'Question 3?', 'field': 'f3'}
        ]
        selector = MockQuestionSelector(questions)
        
        parser = MockResponseParser({'q1': {'f1': 'value1'}})
        formatter = MockJSONFormatter()
        generator = MockSummaryGenerator()
        
        manager = DialogueManager(state, selector, parser, formatter, generator)
        
        # Mock I/O - quit after first question
        responses = ['answer1', 'quit']
        response_iter = iter(responses)
        
        def mock_input(prompt=""):
            return next(response_iter)
        
        def mock_output(text):
            pass  # Suppress output
        
        # Create temp output dir
        with tempfile.TemporaryDirectory() as tmpdir:
            # Run consultation
            result = manager.run_consultation(
                input_fn=mock_input,
                output_fn=mock_output,
                output_dir=tmpdir
            )
            
            # Validate results
            assert result['completed'] == False, "Should not complete (early exit)"
            assert result['total_questions'] == 1, "Should only ask 1 question before quit"
            assert parser.call_count == 1, "Should only parse 1 response"
            
            print(f"\n✓ Completed: {result['completed']}")
            print(f"✓ Questions before quit: {result['total_questions']}")
            
            # Outputs should still be generated
            assert os.path.exists(result['json_path']), "JSON should still be generated"
            assert os.path.exists(result['summary_path']), "Summary should still be generated"
            print(f"✓ Outputs generated despite early exit")
            
            print("\n✓ PASS: Early exit handled correctly")
            return result
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_parse_error_handling():
    """Test 4: Parse error - consultation continues"""
    print_test_header("Parse Error Handling")
    
    try:
        # Setup modules
        state = StateManager()
        
        questions = [
            {'id': 'q1', 'question': 'Question 1?', 'field': 'f1'},
            {'id': 'q2', 'question': 'Question 2?', 'field': 'f2'}
        ]
        selector = MockQuestionSelector(questions)
        
        # Parser that fails on first call
        parser = MockResponseParser(should_fail=True)
        
        formatter = MockJSONFormatter()
        generator = MockSummaryGenerator()
        
        manager = DialogueManager(state, selector, parser, formatter, generator)
        
        # Mock I/O
        responses = ['answer1', 'answer2']
        response_iter = iter(responses)
        
        def mock_input(prompt=""):
            return next(response_iter)
        
        def mock_output(text):
            pass  # Suppress output
        
        # Create temp output dir
        with tempfile.TemporaryDirectory() as tmpdir:
            # Run consultation
            result = manager.run_consultation(
                input_fn=mock_input,
                output_fn=mock_output,
                output_dir=tmpdir
            )
            
            # Validate results
            assert result['completed'] == True, "Should complete despite errors"
            assert result['total_questions'] == 2, "Should ask both questions"
            assert len(result['errors']) >= 2, "Should record parse errors"
            
            print(f"\n✓ Completed: {result['completed']}")
            print(f"✓ Questions asked: {result['total_questions']}")
            print(f"✓ Errors recorded: {len(result['errors'])}")
            
            # Outputs should still be generated
            assert os.path.exists(result['json_path']), "JSON should be generated"
            assert os.path.exists(result['summary_path']), "Summary should be generated"
            print(f"✓ Outputs generated despite parse errors")
            
            print("\n✓ PASS: Parse errors handled gracefully")
            return result
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def run_all_tests():
    """Run all Dialogue Manager tests"""
    print("\n" + "#"*60)
    print("# Dialogue Manager Test Suite")
    print("#"*60)
    
    try:
        # Test 1: Initialization
        test_initialization()
        
        # Test 2: Happy path
        test_happy_path()
        
        # Test 3: Early exit
        test_early_exit()
        
        # Test 4: Parse error handling
        test_parse_error_handling()
        
        # Summary
        print("\n" + "#"*60)
        print("# ALL TESTS PASSED")
        print("#"*60)
        print("\n✓ ✓ ✓ Dialogue Manager module working correctly ✓ ✓ ✓")
        print("\nKey features validated:")
        print("  • Module initialization and dependency injection")
        print("  • Complete consultation flow (happy path)")
        print("  • Early exit handling (user quits)")
        print("  • Parse error handling (continues consultation)")
        print("  • Output generation (JSON + summary)")
        print("  • Error tracking and logging")
        print("\nNext step: Integration test with real modules")
        
        return True
        
    except Exception as e:
        print("\n" + "#"*60)
        print("# TEST SUITE FAILED")
        print("#"*60)
        print(f"\nError: {e}")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    exit(0 if success else 1)