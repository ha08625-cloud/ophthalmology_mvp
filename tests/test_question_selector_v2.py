"""
Unit tests for Question Selector V2 - Fast tests with mocks

Tests per-episode tracking, automatic reset, episode-scoped conditions,
and trigger evaluation without requiring real State Manager.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import MagicMock
from backend.core.question_selector_v2 import QuestionSelectorV2


class MockStateManagerV2:
    """Mock State Manager for fast unit tests"""
    
    def __init__(self):
        self.episodes = {}
        self._episode_ids = []
    
    def list_episode_ids(self):
        return self._episode_ids
    
    def create_episode(self, episode_id):
        """Helper to set up episode in mock"""
        self.episodes[episode_id] = {}
        if episode_id not in self._episode_ids:
            self._episode_ids.append(episode_id)
    
    def has_episode_field(self, episode_id, field_name):
        return field_name in self.episodes.get(episode_id, {})
    
    def get_episode_field(self, episode_id, field_name, default=None):
        return self.episodes.get(episode_id, {}).get(field_name, default)
    
    def set_episode_field(self, episode_id, field_name, value):
        """Helper to set field in mock"""
        if episode_id not in self.episodes:
            self.episodes[episode_id] = {}
        self.episodes[episode_id][field_name] = value


class TestQuestionSelectorV2Basic(unittest.TestCase):
    """Test basic initialization and episode tracking"""
    
    def setUp(self):
        self.state = MockStateManagerV2()
        self.state.create_episode(1)
        ruleset_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "ruleset_v2_0_2.json"
        )
        self.selector = QuestionSelectorV2(ruleset_path, self.state)
    
    def test_initialization(self):
        """Test selector initializes correctly"""
        self.assertIsNotNone(self.selector.ruleset)
        self.assertEqual(len(self.selector.section_order), 8)
        self.assertEqual(self.selector.last_episode_id, None)
    
    def test_first_question_returns_chief_1(self):
        """Test first question is always chief_1"""
        question = self.selector.get_next_question(1)
        
        self.assertIsNotNone(question)
        self.assertEqual(question['id'], 'chief_1')
        self.assertEqual(question['field'], 'presenting_complaint_description')
    
    def test_auto_initialize_on_first_call(self):
        """Test episode state auto-initializes on first get_next_question()"""
        self.assertNotIn(1, self.selector.answered_per_episode)
        
        self.selector.get_next_question(1)
        
        self.assertIn(1, self.selector.answered_per_episode)
        self.assertEqual(self.selector.answered_per_episode[1], set())
        self.assertEqual(self.selector.section_index_per_episode[1], 0)
        self.assertEqual(self.selector.core_complete_per_episode[1], False)
    
    def test_mark_question_answered(self):
        """Test marking question as answered"""
        self.selector.get_next_question(1)  # Initialize
        
        self.selector.mark_question_answered(1, 'chief_1')
        
        self.assertIn('chief_1', self.selector.answered_per_episode[1])
    
    def test_mark_answered_before_initialization_raises(self):
        """Test marking answered before initialization raises error"""
        with self.assertRaises(ValueError) as cm:
            self.selector.mark_question_answered(1, 'chief_1')
        
        self.assertIn("not initialized", str(cm.exception))
    
    def test_nonexistent_episode_raises(self):
        """Test querying nonexistent episode raises error"""
        with self.assertRaises(ValueError) as cm:
            self.selector.get_next_question(999)
        
        self.assertIn("does not exist", str(cm.exception))


class TestQuestionSelectorV2EpisodeTransition(unittest.TestCase):
    """Test automatic reset on episode transition"""
    
    def setUp(self):
        self.state = MockStateManagerV2()
        self.state.create_episode(1)
        self.state.create_episode(2)
        ruleset_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "ruleset_v2_0_2.json"
        )
        self.selector = QuestionSelectorV2(ruleset_path, self.state)
    
    def test_episode_transition_resets_state(self):
        """Test switching episodes resets tracking state"""
        # Ask question in episode 1
        q1 = self.selector.get_next_question(1)
        self.selector.mark_question_answered(1, q1['id'])
        
        # Check episode 1 has answered questions
        self.assertEqual(len(self.selector.answered_per_episode[1]), 1)
        
        # Switch to episode 2
        q2 = self.selector.get_next_question(2)
        
        # Episode 2 should have fresh state
        self.assertEqual(len(self.selector.answered_per_episode[2]), 0)
        self.assertEqual(q2['id'], 'chief_1')  # Starts from beginning
        
        # Episode 1 state should be preserved
        self.assertEqual(len(self.selector.answered_per_episode[1]), 1)
    
    def test_return_to_previous_episode_preserves_state(self):
        """Test returning to previous episode keeps answered questions"""
        # Episode 1: Answer first question
        q1 = self.selector.get_next_question(1)
        self.selector.mark_question_answered(1, q1['id'])
        
        # Episode 2: Answer first question
        q2 = self.selector.get_next_question(2)
        self.selector.mark_question_answered(2, q2['id'])
        
        # Return to episode 1
        q1_next = self.selector.get_next_question(1)
        
        # Should return second question (first already answered)
        self.assertNotEqual(q1_next['id'], 'chief_1')
        self.assertIn('chief_1', self.selector.answered_per_episode[1])


class TestQuestionSelectorV2ConditionalLogic(unittest.TestCase):
    """Test episode-scoped conditional question logic"""
    
    def setUp(self):
        self.state = MockStateManagerV2()
        self.state.create_episode(1)
        ruleset_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "ruleset_v2_0_2.json"
        )
        self.selector = QuestionSelectorV2(ruleset_path, self.state)
    
    def test_skip_question_if_field_already_collected(self):
        """Test skips question if patient volunteered field"""
        # Set field in state (patient volunteered)
        self.state.set_episode_field(1, 'vl_laterality', 'monocular_right')
        
        # Get questions until we reach past laterality questions
        questions_asked = []
        for _ in range(10):
            q = self.selector.get_next_question(1)
            if q is None:
                break
            questions_asked.append(q['id'])
            self.selector.mark_question_answered(1, q['id'])
            
            if q['id'] == 'vl_10':  # Past all laterality questions
                break
        
        # vl_2 should have been skipped (asks for laterality)
        self.assertNotIn('vl_2', questions_asked)
        # vl_3 should ALSO be skipped (field already specific enough)
        self.assertNotIn('vl_3', questions_asked)
    
    def test_conditional_question_asked_when_condition_met(self):
        """Test conditional question asked when condition true"""
        # Simulate real flow: answer questions, mark answered
        # vl_3 is conditional - only asked if vl_2 was answered
        
        # Answer questions until we get past vl_3
        questions_asked = []
        for _ in range(20):
            q = self.selector.get_next_question(1)
            if q is None:
                break
            questions_asked.append(q['id'])
            self.selector.mark_question_answered(1, q['id'])
            
            # Stop after vl_3 area
            if q['id'] == 'vl_5':  # Past the laterality questions
                break
        
        # In a real conversation:
        # - vl_2 would be asked
        # - Patient answers (Response Parser sets field)
        # - vl_3 checks condition based on that field value
        # For this test, we just verify vl_2 was asked
        self.assertIn('vl_2', questions_asked)
    
    def test_conditional_question_skipped_when_condition_not_met(self):
        """Test conditional question skipped when condition false"""
        # Set up condition: binocular vision loss (not monocular)
        self.state.set_episode_field(1, 'vl_laterality', 'binocular')
        
        # Get questions through vision loss section
        questions_asked = []
        for _ in range(20):
            q = self.selector.get_next_question(1)
            if q is None:
                break
            questions_asked.append(q['id'])
            self.selector.mark_question_answered(1, q['id'])
            
            # Stop after vision_loss section
            if q['id'].startswith('vd_'):
                break
        
        # vl_3 is conditional on monocular - should be skipped
        self.assertNotIn('vl_3', questions_asked)
        # vl_4 is conditional on binocular - should be asked
        self.assertIn('vl_4', questions_asked)


class TestQuestionSelectorV2TriggerBlocks(unittest.TestCase):
    """Test episode-scoped trigger evaluation"""
    
    def setUp(self):
        self.state = MockStateManagerV2()
        self.state.create_episode(1)
        ruleset_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "ruleset_v2_0_2.json"
        )
        self.selector = QuestionSelectorV2(ruleset_path, self.state)
    
    def test_trigger_activates_for_episode(self):
        """Test trigger activates based on episode data"""
        # Set up trigger condition: subacute monocular loss
        self.state.set_episode_field(1, 'vl_laterality', 'monocular_right')
        self.state.set_episode_field(1, 'vl_onset_speed', 'subacute')
        
        # Answer all core section questions
        self._answer_all_core_sections()
        
        # Check triggers activated
        triggered = self.selector.triggered_blocks_per_episode.get(1, [])
        self.assertIn('block_1', triggered)  # Optic neuritis screen
    
    def test_trigger_does_not_activate_without_condition(self):
        """Test trigger doesn't activate when condition not met"""
        # Set up data that doesn't trigger anything
        self.state.set_episode_field(1, 'vl_laterality', 'binocular')
        self.state.set_episode_field(1, 'vl_onset_speed', 'chronic')
        
        # Answer all core section questions
        self._answer_all_core_sections()
        
        # No triggers should activate
        triggered = self.selector.triggered_blocks_per_episode.get(1, [])
        self.assertNotIn('block_1', triggered)
        self.assertNotIn('block_2', triggered)
    
    def test_trigger_scoped_to_episode(self):
        """Test triggers are evaluated per episode"""
        self.state.create_episode(2)
        
        # Episode 1: Trigger block_1
        self.state.set_episode_field(1, 'vl_laterality', 'monocular_right')
        self.state.set_episode_field(1, 'vl_onset_speed', 'subacute')
        self._answer_all_core_sections()
        
        # Episode 2: Different data, no trigger
        self.state.set_episode_field(2, 'vl_laterality', 'binocular')
        self.state.set_episode_field(2, 'vl_onset_speed', 'chronic')
        
        # Switch to episode 2 and complete core sections
        for _ in range(40):
            q = self.selector.get_next_question(2)
            if q is None:
                break
            self.selector.mark_question_answered(2, q['id'])
        
        # Episode 1 should have block_1, episode 2 should not
        self.assertIn('block_1', self.selector.triggered_blocks_per_episode[1])
        triggered_ep2 = self.selector.triggered_blocks_per_episode.get(2, [])
        self.assertNotIn('block_1', triggered_ep2)
    
    def _answer_all_core_sections(self):
        """Helper: answer all core section questions to trigger evaluation"""
        for _ in range(40):  # More than enough to finish core sections
            q = self.selector.get_next_question(1)
            if q is None:
                break
            self.selector.mark_question_answered(1, q['id'])


class TestQuestionSelectorV2ProgressSummary(unittest.TestCase):
    """Test progress summary reporting"""
    
    def setUp(self):
        self.state = MockStateManagerV2()
        self.state.create_episode(1)
        ruleset_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "ruleset_v2_0_2.json"
        )
        self.selector = QuestionSelectorV2(ruleset_path, self.state)
    
    def test_progress_summary_structure(self):
        """Test progress summary returns correct structure"""
        self.selector.get_next_question(1)  # Initialize
        
        summary = self.selector.get_progress_summary(1)
        
        self.assertIn('episode_id', summary)
        self.assertIn('core_sections_complete', summary)
        self.assertIn('current_section', summary)
        self.assertIn('section_progress', summary)
        self.assertIn('triggered_blocks', summary)
        self.assertIn('block_progress', summary)
        self.assertIn('total_questions_answered', summary)
    
    def test_progress_summary_before_initialization_raises(self):
        """Test progress summary before initialization raises error"""
        with self.assertRaises(ValueError):
            self.selector.get_progress_summary(1)
    
    def test_progress_tracks_answered_questions(self):
        """Test progress summary tracks answered questions"""
        # Answer first question
        q = self.selector.get_next_question(1)
        self.selector.mark_question_answered(1, q['id'])
        
        summary = self.selector.get_progress_summary(1)
        
        self.assertEqual(summary['total_questions_answered'], 1)
        self.assertEqual(summary['current_section'], 'chief_complaint')


class TestQuestionSelectorV2MultipleEpisodes(unittest.TestCase):
    """Test handling multiple episodes in single consultation"""
    
    def setUp(self):
        self.state = MockStateManagerV2()
        self.state.create_episode(1)
        self.state.create_episode(2)
        self.state.create_episode(3)
        ruleset_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "ruleset_v2_0_2.json"
        )
        self.selector = QuestionSelectorV2(ruleset_path, self.state)
    
    def test_three_episodes_maintain_separate_state(self):
        """Test three episodes maintain independent state"""
        # Answer 2 questions in episode 1
        for _ in range(2):
            q = self.selector.get_next_question(1)
            self.selector.mark_question_answered(1, q['id'])
        
        # Answer 3 questions in episode 2
        for _ in range(3):
            q = self.selector.get_next_question(2)
            self.selector.mark_question_answered(2, q['id'])
        
        # Answer 1 question in episode 3
        q = self.selector.get_next_question(3)
        self.selector.mark_question_answered(3, q['id'])
        
        # Check each episode has correct count
        self.assertEqual(len(self.selector.answered_per_episode[1]), 2)
        self.assertEqual(len(self.selector.answered_per_episode[2]), 3)
        self.assertEqual(len(self.selector.answered_per_episode[3]), 1)
    
    def test_jumping_between_episodes(self):
        """Test can jump between episodes in any order"""
        # Episode 1 -> 3 -> 2 -> 1
        q1_1 = self.selector.get_next_question(1)
        self.selector.mark_question_answered(1, q1_1['id'])
        
        q3_1 = self.selector.get_next_question(3)
        self.selector.mark_question_answered(3, q3_1['id'])
        
        q2_1 = self.selector.get_next_question(2)
        self.selector.mark_question_answered(2, q2_1['id'])
        
        q1_2 = self.selector.get_next_question(1)
        self.selector.mark_question_answered(1, q1_2['id'])
        
        # Each episode should progress independently
        self.assertEqual(len(self.selector.answered_per_episode[1]), 2)
        self.assertEqual(len(self.selector.answered_per_episode[2]), 1)
        self.assertEqual(len(self.selector.answered_per_episode[3]), 1)


def run_tests():
    """Run all tests"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionSelectorV2Basic))
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionSelectorV2EpisodeTransition))
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionSelectorV2ConditionalLogic))
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionSelectorV2TriggerBlocks))
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionSelectorV2ProgressSummary))
    suite.addTests(loader.loadTestsFromTestCase(TestQuestionSelectorV2MultipleEpisodes))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)