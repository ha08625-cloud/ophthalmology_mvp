"""
Test Suite for Question Selector V2

TDD approach: tests written before implementation.
Run with: python test_question_selector_v2.py
"""

import unittest
import json
import tempfile
import os


# =============================================================================
# PART 1: DSL Evaluator Tests
# =============================================================================

class TestDSLEvaluator(unittest.TestCase):
    """Test the DSL condition evaluation logic."""
    
    def setUp(self):
        """Create minimal valid ruleset for testing."""
        self.minimal_ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},
            "trigger_conditions": {},
            "sections": {
                "vision_loss": []
            },
            "follow_up_blocks": {}
        }
        
        # Create temp ruleset file
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.minimal_ruleset, self.temp_file)
        self.temp_file.close()
        
        # Import after creating file (deferred import for TDD)
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        """Clean up temp file."""
        os.unlink(self.temp_file.name)
    
    # -------------------------------------------------------------------------
    # eq operator
    # -------------------------------------------------------------------------
    
    def test_eq_string_match(self):
        """eq operator returns True when field equals expected string."""
        dsl = {"eq": ["vl_single_eye", "single"]}
        episode_data = {"vl_single_eye": "single"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_eq_string_no_match(self):
        """eq operator returns False when field does not equal expected."""
        dsl = {"eq": ["vl_single_eye", "single"]}
        episode_data = {"vl_single_eye": "both"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_eq_missing_field(self):
        """eq operator returns False when field is missing."""
        dsl = {"eq": ["vl_single_eye", "single"]}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # ne operator
    # -------------------------------------------------------------------------
    
    def test_ne_different_values(self):
        """ne operator returns True when field differs from expected."""
        dsl = {"ne": ["vl_degree", "total"]}
        episode_data = {"vl_degree": "partial"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_ne_same_values(self):
        """ne operator returns False when field equals expected."""
        dsl = {"ne": ["vl_degree", "total"]}
        episode_data = {"vl_degree": "total"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_ne_missing_field(self):
        """ne operator returns True when field is missing (None != value)."""
        dsl = {"ne": ["vl_degree", "total"]}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    # -------------------------------------------------------------------------
    # is_true operator
    # -------------------------------------------------------------------------
    
    def test_is_true_when_true(self):
        """is_true returns True when field is boolean True."""
        dsl = {"is_true": "h_present"}
        episode_data = {"h_present": True}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_is_true_when_false(self):
        """is_true returns False when field is boolean False."""
        dsl = {"is_true": "h_present"}
        episode_data = {"h_present": False}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_is_true_when_truthy_string(self):
        """is_true returns False for truthy non-boolean (strict check)."""
        dsl = {"is_true": "h_present"}
        episode_data = {"h_present": "yes"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_is_true_missing_field(self):
        """is_true returns False when field is missing."""
        dsl = {"is_true": "h_present"}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # is_false operator
    # -------------------------------------------------------------------------
    
    def test_is_false_when_false(self):
        """is_false returns True when field is boolean False."""
        dsl = {"is_false": "h_present"}
        episode_data = {"h_present": False}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_is_false_when_true(self):
        """is_false returns False when field is boolean True."""
        dsl = {"is_false": "h_present"}
        episode_data = {"h_present": True}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_is_false_missing_field(self):
        """is_false returns False when field is missing (not strictly False)."""
        dsl = {"is_false": "h_present"}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # exists operator
    # -------------------------------------------------------------------------
    
    def test_exists_when_present(self):
        """exists returns True when field is present and not None."""
        dsl = {"exists": "vl_field"}
        episode_data = {"vl_field": "upper half"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_exists_when_none(self):
        """exists returns False when field is None."""
        dsl = {"exists": "vl_field"}
        episode_data = {"vl_field": None}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_exists_when_missing(self):
        """exists returns False when field is not in dict."""
        dsl = {"exists": "vl_field"}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_exists_empty_string(self):
        """exists returns True for empty string (present but empty)."""
        dsl = {"exists": "vl_field"}
        episode_data = {"vl_field": ""}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    # -------------------------------------------------------------------------
    # contains_lower operator
    # -------------------------------------------------------------------------
    
    def test_contains_lower_match(self):
        """contains_lower returns True when substring found (case-insensitive)."""
        dsl = {"contains_lower": ["vl_field", "upper half"]}
        episode_data = {"vl_field": "The UPPER HALF of my vision"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_contains_lower_no_match(self):
        """contains_lower returns False when substring not found."""
        dsl = {"contains_lower": ["vl_field", "upper half"]}
        episode_data = {"vl_field": "peripheral vision"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_contains_lower_missing_field(self):
        """contains_lower returns False when field is missing."""
        dsl = {"contains_lower": ["vl_field", "upper half"]}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_contains_lower_non_string_field(self):
        """contains_lower returns False when field is not a string."""
        dsl = {"contains_lower": ["vl_field", "upper half"]}
        episode_data = {"vl_field": 123}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # all operator (AND)
    # -------------------------------------------------------------------------
    
    def test_all_both_true(self):
        """all returns True when all conditions are true."""
        dsl = {
            "all": [
                {"eq": ["vl_single_eye", "single"]},
                {"eq": ["vl_onset_speed", "subacute"]}
            ]
        }
        episode_data = {
            "vl_single_eye": "single",
            "vl_onset_speed": "subacute"
        }
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_all_one_false(self):
        """all returns False when any condition is false."""
        dsl = {
            "all": [
                {"eq": ["vl_single_eye", "single"]},
                {"eq": ["vl_onset_speed", "subacute"]}
            ]
        }
        episode_data = {
            "vl_single_eye": "single",
            "vl_onset_speed": "acute"
        }
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_all_empty_list(self):
        """all returns True for empty list (vacuous truth)."""
        dsl = {"all": []}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    # -------------------------------------------------------------------------
    # any operator (OR)
    # -------------------------------------------------------------------------
    
    def test_any_one_true(self):
        """any returns True when at least one condition is true."""
        dsl = {
            "any": [
                {"contains_lower": ["vl_field", "upper half"]},
                {"contains_lower": ["vl_field", "lower half"]}
            ]
        }
        episode_data = {"vl_field": "lower half of vision"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_any_all_false(self):
        """any returns False when all conditions are false."""
        dsl = {
            "any": [
                {"contains_lower": ["vl_field", "upper half"]},
                {"contains_lower": ["vl_field", "lower half"]}
            ]
        }
        episode_data = {"vl_field": "peripheral"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_any_empty_list(self):
        """any returns False for empty list (no conditions met)."""
        dsl = {"any": []}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # Nested conditions
    # -------------------------------------------------------------------------
    
    def test_nested_all_any(self):
        """Complex nested condition: all containing any."""
        # Represents: exists(vl_field) AND (contains "upper half" OR contains "lower half")
        dsl = {
            "all": [
                {"exists": "vl_field"},
                {"any": [
                    {"contains_lower": ["vl_field", "upper half"]},
                    {"contains_lower": ["vl_field", "lower half"]}
                ]}
            ]
        }
        episode_data = {"vl_field": "My LOWER HALF vision is gone"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_nested_fails_outer(self):
        """Nested condition fails when outer condition fails."""
        dsl = {
            "all": [
                {"exists": "vl_field"},
                {"any": [
                    {"contains_lower": ["vl_field", "upper half"]},
                    {"contains_lower": ["vl_field", "lower half"]}
                ]}
            ]
        }
        episode_data = {}  # vl_field doesn't exist
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # Unknown operator
    # -------------------------------------------------------------------------
    
    def test_unknown_operator_returns_false(self):
        """Unknown DSL operator returns False and logs warning."""
        dsl = {"unknown_op": ["field", "value"]}
        episode_data = {"field": "value"}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    # -------------------------------------------------------------------------
    # Numeric comparison operators
    # -------------------------------------------------------------------------
    
    def test_gte_when_greater(self):
        """gte returns True when field > threshold."""
        dsl = {"gte": ["h_onset_weeks", 6]}
        episode_data = {"h_onset_weeks": 8}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_gte_when_equal(self):
        """gte returns True when field == threshold."""
        dsl = {"gte": ["h_onset_weeks", 6]}
        episode_data = {"h_onset_weeks": 6}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertTrue(result)
    
    def test_gte_when_less(self):
        """gte returns False when field < threshold."""
        dsl = {"gte": ["h_onset_weeks", 6]}
        episode_data = {"h_onset_weeks": 4}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_gte_missing_field(self):
        """gte returns False when field is missing."""
        dsl = {"gte": ["h_onset_weeks", 6]}
        episode_data = {}
        
        result = self.selector._evaluate_dsl(dsl, episode_data)
        
        self.assertFalse(result)
    
    def test_gt_operator(self):
        """gt returns True only when strictly greater."""
        dsl = {"gt": ["count", 5]}
        
        self.assertTrue(self.selector._evaluate_dsl(dsl, {"count": 6}))
        self.assertFalse(self.selector._evaluate_dsl(dsl, {"count": 5}))
        self.assertFalse(self.selector._evaluate_dsl(dsl, {"count": 4}))
    
    def test_lte_operator(self):
        """lte returns True when less than or equal."""
        dsl = {"lte": ["count", 5]}
        
        self.assertTrue(self.selector._evaluate_dsl(dsl, {"count": 4}))
        self.assertTrue(self.selector._evaluate_dsl(dsl, {"count": 5}))
        self.assertFalse(self.selector._evaluate_dsl(dsl, {"count": 6}))
    
    def test_lt_operator(self):
        """lt returns True only when strictly less."""
        dsl = {"lt": ["count", 5]}
        
        self.assertTrue(self.selector._evaluate_dsl(dsl, {"count": 4}))
        self.assertFalse(self.selector._evaluate_dsl(dsl, {"count": 5}))
        self.assertFalse(self.selector._evaluate_dsl(dsl, {"count": 6}))


# =============================================================================
# PART 2: Named Condition Evaluation Tests
# =============================================================================

class TestConditionEvaluation(unittest.TestCase):
    """Test evaluation of named conditions from ruleset."""
    
    def setUp(self):
        """Create ruleset with named conditions."""
        self.ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {
                "vl_single_eye_is_single": {
                    "all": [
                        {"eq": ["vl_single_eye", "single"]}
                    ]
                },
                "headache": {
                    "all": [
                        {"is_true": "h_present"}
                    ]
                },
                "partial_monocular_loss": {
                    "all": [
                        {"eq": ["vl_single_eye", "single"]},
                        {"ne": ["vl_degree", "total"]}
                    ]
                }
            },
            "trigger_conditions": {},
            "sections": {
                "vision_loss": []
            },
            "follow_up_blocks": {}
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_named_condition_true(self):
        """Named condition returns True when met."""
        episode_data = {"vl_single_eye": "single"}
        
        result = self.selector._evaluate_condition("vl_single_eye_is_single", episode_data)
        
        self.assertTrue(result)
    
    def test_named_condition_false(self):
        """Named condition returns False when not met."""
        episode_data = {"vl_single_eye": "both"}
        
        result = self.selector._evaluate_condition("vl_single_eye_is_single", episode_data)
        
        self.assertFalse(result)
    
    def test_unknown_condition_returns_false(self):
        """Unknown condition name returns False."""
        episode_data = {"vl_single_eye": "single"}
        
        result = self.selector._evaluate_condition("nonexistent_condition", episode_data)
        
        self.assertFalse(result)
    
    def test_complex_named_condition(self):
        """Complex named condition with multiple clauses."""
        episode_data = {
            "vl_single_eye": "single",
            "vl_degree": "partial"
        }
        
        result = self.selector._evaluate_condition("partial_monocular_loss", episode_data)
        
        self.assertTrue(result)


# =============================================================================
# PART 3: Question Eligibility Tests
# =============================================================================

class TestQuestionEligibility(unittest.TestCase):
    """Test question eligibility determination."""
    
    def setUp(self):
        """Create ruleset with probe and conditional questions."""
        self.ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {
                "vl_single_eye_is_single": {
                    "all": [{"eq": ["vl_single_eye", "single"]}]
                }
            },
            "trigger_conditions": {},
            "sections": {
                "vision_loss": [
                    {
                        "id": "vl_1",
                        "type": "probe",
                        "question": "Have you experienced visual loss?",
                        "field": "visual_loss_present",
                        "field_type": "boolean"
                    },
                    {
                        "id": "vl_2",
                        "type": "probe",
                        "question": "Is it one eye or both?",
                        "field": "vl_single_eye",
                        "field_type": "categorical"
                    },
                    {
                        "id": "vl_3",
                        "type": "conditional",
                        "question": "Which eye is affected?",
                        "condition": "vl_single_eye_is_single",
                        "field": "vl_laterality",
                        "field_type": "categorical"
                    }
                ]
            },
            "follow_up_blocks": {}
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_probe_always_eligible(self):
        """Probe questions are always eligible."""
        question = self.ruleset["sections"]["vision_loss"][0]  # vl_1
        episode_data = {}
        
        result = self.selector._is_eligible(question, episode_data)
        
        self.assertTrue(result)
    
    def test_conditional_eligible_when_condition_met(self):
        """Conditional question eligible when condition is true."""
        question = self.ruleset["sections"]["vision_loss"][2]  # vl_3
        episode_data = {"vl_single_eye": "single"}
        
        result = self.selector._is_eligible(question, episode_data)
        
        self.assertTrue(result)
    
    def test_conditional_not_eligible_when_condition_not_met(self):
        """Conditional question not eligible when condition is false."""
        question = self.ruleset["sections"]["vision_loss"][2]  # vl_3
        episode_data = {"vl_single_eye": "both"}
        
        result = self.selector._is_eligible(question, episode_data)
        
        self.assertFalse(result)
    
    def test_question_without_type_treated_as_probe(self):
        """Question missing 'type' field is treated as probe."""
        question = {
            "id": "test_q",
            "question": "Test question?",
            "field": "test_field"
            # No 'type' key
        }
        episode_data = {}
        
        result = self.selector._is_eligible(question, episode_data)
        
        self.assertTrue(result)
    
    def test_question_without_condition_treated_as_probe(self):
        """Conditional question missing 'condition' is treated as probe."""
        question = {
            "id": "test_q",
            "type": "conditional",
            "question": "Test question?",
            "field": "test_field"
            # No 'condition' key
        }
        episode_data = {}
        
        result = self.selector._is_eligible(question, episode_data)
        
        self.assertTrue(result)


# =============================================================================
# PART 4: Section Traversal Tests
# =============================================================================

class TestSectionTraversal(unittest.TestCase):
    """Test correct ordering and traversal of sections."""
    
    def setUp(self):
        """Create ruleset with multiple sections."""
        self.ruleset = {
            "section_order": ["vision_loss", "headache", "eye_pain"],
            "conditions": {},
            "trigger_conditions": {},
            "sections": {
                "vision_loss": [
                    {"id": "vl_1", "type": "probe", "question": "VL Q1?", "field": "vl_field1"},
                    {"id": "vl_2", "type": "probe", "question": "VL Q2?", "field": "vl_field2"}
                ],
                "headache": [
                    {"id": "h_1", "type": "probe", "question": "H Q1?", "field": "h_field1"}
                ],
                "eye_pain": [
                    {"id": "ep_1", "type": "probe", "question": "EP Q1?", "field": "ep_field1"}
                ]
            },
            "follow_up_blocks": {}
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_returns_first_question_initially(self):
        """First call returns first question of first section."""
        episode_data = {
            "questions_answered": set(),
            "follow_up_blocks_activated": set(),
            "follow_up_blocks_completed": set()
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertEqual(result["id"], "vl_1")
    
    def test_respects_section_order(self):
        """Questions follow section_order from ruleset."""
        episode_data = {
            "questions_answered": {"vl_1", "vl_2"},  # vision_loss complete
            "follow_up_blocks_activated": set(),
            "follow_up_blocks_completed": set()
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertEqual(result["id"], "h_1")  # headache is next
    
    def test_skips_answered_questions(self):
        """Already answered questions are skipped."""
        episode_data = {
            "questions_answered": {"vl_1"},
            "follow_up_blocks_activated": set(),
            "follow_up_blocks_completed": set()
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertEqual(result["id"], "vl_2")
    
    def test_returns_none_when_all_complete(self):
        """Returns None when all sections exhausted."""
        episode_data = {
            "questions_answered": {"vl_1", "vl_2", "h_1", "ep_1"},
            "follow_up_blocks_activated": set(),
            "follow_up_blocks_completed": set()
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertIsNone(result)


# =============================================================================
# PART 5: Follow-up Block Tests
# =============================================================================

class TestFollowUpBlocks(unittest.TestCase):
    """Test follow-up block question handling."""
    
    def setUp(self):
        """Create ruleset with follow-up blocks."""
        self.ruleset = {
            "section_order": ["vision_loss", "headache"],
            "conditions": {
                "block1_cond": {"all": [{"is_true": "b1_trigger"}]}
            },
            "trigger_conditions": {
                "trigger_block_1": {
                    "condition": {"all": [{"eq": ["vl_onset_speed", "subacute"]}]},
                    "activates": "block_1"
                }
            },
            "sections": {
                "vision_loss": [
                    {"id": "vl_1", "type": "probe", "question": "VL Q1?", "field": "vl_field1"},
                    {"id": "vl_2", "type": "probe", "question": "VL Q2?", "field": "vl_onset_speed"}
                ],
                "headache": [
                    {"id": "h_1", "type": "probe", "question": "H Q1?", "field": "h_field1"}
                ]
            },
            "follow_up_blocks": {
                "block_1": {
                    "name": "Test Block",
                    "questions": [
                        {"id": "b1_1", "type": "probe", "question": "Block Q1?", "field": "b1_field1"},
                        {"id": "b1_2", "type": "probe", "question": "Block Q2?", "field": "b1_field2"}
                    ]
                }
            }
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_block_questions_take_priority(self):
        """Activated block questions come before next section."""
        episode_data = {
            "questions_answered": {"vl_1", "vl_2"},  # vision_loss complete
            "follow_up_blocks_activated": {"block_1"},
            "follow_up_blocks_completed": set(),
            "vl_onset_speed": "subacute"
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertEqual(result["id"], "b1_1")
    
    def test_block_questions_in_order(self):
        """Block questions follow array order."""
        episode_data = {
            "questions_answered": {"vl_1", "vl_2", "b1_1"},
            "follow_up_blocks_activated": {"block_1"},
            "follow_up_blocks_completed": set()
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertEqual(result["id"], "b1_2")
    
    def test_completed_block_skipped(self):
        """Completed blocks are not revisited."""
        episode_data = {
            "questions_answered": {"vl_1", "vl_2", "b1_1", "b1_2"},
            "follow_up_blocks_activated": {"block_1"},
            "follow_up_blocks_completed": {"block_1"}
        }
        
        result = self.selector.get_next_question(episode_data)
        
        self.assertEqual(result["id"], "h_1")  # Moves to next section
    
    def test_multiple_blocks_in_deterministic_order(self):
        """Multiple activated blocks processed in sorted order."""
        ruleset = self.ruleset.copy()
        ruleset["follow_up_blocks"]["block_3"] = {
            "name": "Block Three",
            "questions": [
                {"id": "b3_1", "type": "probe", "question": "B3 Q1?", "field": "b3_field1"}
            ]
        }
        
        # Recreate selector with updated ruleset
        with open(self.temp_file.name, 'w') as f:
            json.dump(ruleset, f)
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        selector = QuestionSelectorV2(self.temp_file.name)
        
        episode_data = {
            "questions_answered": {"vl_1", "vl_2"},
            "follow_up_blocks_activated": {"block_3", "block_1"},  # block_3 added first
            "follow_up_blocks_completed": set()
        }
        
        result = selector.get_next_question(episode_data)
        
        # block_1 should come before block_3 (sorted order)
        self.assertEqual(result["id"], "b1_1")


# =============================================================================
# PART 6: Trigger Detection Tests
# =============================================================================

class TestTriggerDetection(unittest.TestCase):
    """Test trigger condition checking."""
    
    def setUp(self):
        """Create ruleset with trigger conditions."""
        self.ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},
            "trigger_conditions": {
                "subacute_monocular": {
                    "condition": {
                        "all": [
                            {"eq": ["vl_single_eye", "single"]},
                            {"eq": ["vl_onset_speed", "subacute"]}
                        ]
                    },
                    "activates": "block_1"
                },
                "chronic_loss": {
                    "condition": {
                        "all": [
                            {"is_true": "visual_loss_present"},
                            {"eq": ["vl_onset_speed", "chronic"]}
                        ]
                    },
                    "activates": ["block_3", "block_4"]
                }
            },
            "sections": {
                "vision_loss": []
            },
            "follow_up_blocks": {
                "block_1": {"name": "B1", "questions": [
                    {"id": "b1_1", "type": "probe", "question": "B1 Q1?", "field": "b1_f1"}
                ]},
                "block_3": {"name": "B3", "questions": [
                    {"id": "b3_1", "type": "probe", "question": "B3 Q1?", "field": "b3_f1"}
                ]},
                "block_4": {"name": "B4", "questions": [
                    {"id": "b4_1", "type": "probe", "question": "B4 Q1?", "field": "b4_f1"}
                ]}
            }
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_trigger_not_met(self):
        """check_triggers returns empty set when no triggers met."""
        episode_data = {
            "vl_single_eye": "both",
            "vl_onset_speed": "acute"
        }
        
        result = self.selector.check_triggers(episode_data)
        
        self.assertEqual(result, set())
    
    def test_single_trigger_met(self):
        """check_triggers returns block ID when single trigger met."""
        episode_data = {
            "vl_single_eye": "single",
            "vl_onset_speed": "subacute"
        }
        
        result = self.selector.check_triggers(episode_data)
        
        self.assertEqual(result, {"block_1"})
    
    def test_trigger_activates_multiple_blocks(self):
        """Trigger can activate multiple blocks."""
        episode_data = {
            "visual_loss_present": True,
            "vl_onset_speed": "chronic"
        }
        
        result = self.selector.check_triggers(episode_data)
        
        self.assertEqual(result, {"block_3", "block_4"})
    
    def test_multiple_triggers_met(self):
        """Multiple triggers can fire simultaneously."""
        # Modify ruleset to have conditions that can both be true
        self.ruleset["trigger_conditions"]["another_trigger"] = {
            "condition": {"all": [{"is_true": "visual_loss_present"}]},
            "activates": "block_1"
        }
        
        with open(self.temp_file.name, 'w') as f:
            json.dump(self.ruleset, f)
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        selector = QuestionSelectorV2(self.temp_file.name)
        
        episode_data = {
            "visual_loss_present": True,
            "vl_onset_speed": "chronic"
        }
        
        result = selector.check_triggers(episode_data)
        
        # Both triggers fire: chronic_loss (block_3, block_4) and another_trigger (block_1)
        self.assertEqual(result, {"block_1", "block_3", "block_4"})


# =============================================================================
# PART 7: Block Completion Tests
# =============================================================================

class TestBlockCompletion(unittest.TestCase):
    """Test block completion detection."""
    
    def setUp(self):
        """Create ruleset with block containing conditional questions."""
        self.ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {
                "alexia": {"all": [{"is_true": "difficulty_reading"}]}
            },
            "trigger_conditions": {},
            "sections": {
                "vision_loss": []
            },
            "follow_up_blocks": {
                "block_6": {
                    "name": "Higher Visual Processing",
                    "questions": [
                        {"id": "b6_1", "type": "probe", "question": "Difficulty reading?", "field": "difficulty_reading"},
                        {"id": "b6_2", "type": "conditional", "condition": "alexia", "question": "Can spell?", "field": "can_spell"},
                        {"id": "b6_3", "type": "probe", "question": "Trouble navigating?", "field": "trouble_navigating"}
                    ]
                }
            }
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        self.selector = QuestionSelectorV2(self.temp_file.name)
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_block_not_complete_unanswered_probe(self):
        """Block not complete when probe question unanswered."""
        episode_data = {
            "questions_answered": {"b6_1"},
            "difficulty_reading": False
        }
        
        result = self.selector.is_block_complete("block_6", episode_data)
        
        self.assertFalse(result)
    
    def test_block_complete_all_answered(self):
        """Block complete when all questions answered."""
        episode_data = {
            "questions_answered": {"b6_1", "b6_2", "b6_3"},
            "difficulty_reading": True
        }
        
        result = self.selector.is_block_complete("block_6", episode_data)
        
        self.assertTrue(result)
    
    def test_block_complete_conditional_skipped(self):
        """Block complete when conditional question skipped (condition not met)."""
        episode_data = {
            "questions_answered": {"b6_1", "b6_3"},  # b6_2 not answered
            "difficulty_reading": False  # Condition for b6_2 not met
        }
        
        result = self.selector.is_block_complete("block_6", episode_data)
        
        self.assertTrue(result)
    
    def test_block_not_complete_eligible_conditional_unanswered(self):
        """Block not complete when eligible conditional is unanswered."""
        episode_data = {
            "questions_answered": {"b6_1", "b6_3"},  # b6_2 not answered
            "difficulty_reading": True  # Condition for b6_2 IS met
        }
        
        result = self.selector.is_block_complete("block_6", episode_data)
        
        self.assertFalse(result)


# =============================================================================
# PART 8: Validation Tests
# =============================================================================

class TestRulesetValidation(unittest.TestCase):
    """Test ruleset validation on initialization."""
    
    def test_missing_section_order_raises(self):
        """Missing section_order raises ValueError."""
        ruleset = {
            "conditions": {},
            "trigger_conditions": {},
            "sections": {"vision_loss": []},
            "follow_up_blocks": {}
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("section_order", str(context.exception))
        os.unlink(temp_file.name)
    
    def test_section_in_order_not_defined_raises(self):
        """Section in section_order but not in sections raises ValueError."""
        ruleset = {
            "section_order": ["vision_loss", "nonexistent_section"],
            "conditions": {},
            "trigger_conditions": {},
            "sections": {"vision_loss": []},
            "follow_up_blocks": {}
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("nonexistent_section", str(context.exception))
        os.unlink(temp_file.name)
    
    def test_question_references_nonexistent_condition_raises(self):
        """Question referencing undefined condition raises ValueError."""
        ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},  # Empty - no conditions defined
            "trigger_conditions": {},
            "sections": {
                "vision_loss": [
                    {
                        "id": "vl_1",
                        "type": "conditional",
                        "condition": "undefined_condition",
                        "question": "Test?",
                        "field": "test"
                    }
                ]
            },
            "follow_up_blocks": {}
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("undefined_condition", str(context.exception))
        os.unlink(temp_file.name)
    
    def test_trigger_references_nonexistent_block_raises(self):
        """Trigger activating undefined block raises ValueError."""
        ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},
            "trigger_conditions": {
                "test_trigger": {
                    "condition": {"all": [{"is_true": "test"}]},
                    "activates": "nonexistent_block"
                }
            },
            "sections": {"vision_loss": []},
            "follow_up_blocks": {}  # Empty - block doesn't exist
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("nonexistent_block", str(context.exception))
        os.unlink(temp_file.name)
    
    def test_duplicate_question_id_in_block_raises(self):
        """Duplicate question ID within a block raises ValueError."""
        ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},
            "trigger_conditions": {},
            "sections": {"vision_loss": []},
            "follow_up_blocks": {
                "block_1": {
                    "name": "Test",
                    "questions": [
                        {"id": "b1_1", "type": "probe", "question": "Q1?", "field": "f1"},
                        {"id": "b1_1", "type": "probe", "question": "Q2?", "field": "f2"}  # Duplicate
                    ]
                }
            }
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("duplicate", str(context.exception).lower())
        os.unlink(temp_file.name)
    
    def test_empty_block_questions_raises(self):
        """Block with empty questions array raises ValueError."""
        ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},
            "trigger_conditions": {
                "test_trigger": {
                    "condition": {"all": [{"is_true": "test"}]},
                    "activates": "block_1"
                }
            },
            "sections": {"vision_loss": []},
            "follow_up_blocks": {
                "block_1": {
                    "name": "Empty Block",
                    "questions": []  # Empty
                }
            }
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("empty", str(context.exception).lower())
        os.unlink(temp_file.name)
    
    def test_question_missing_id_raises(self):
        """Question without 'id' field raises ValueError."""
        ruleset = {
            "section_order": ["vision_loss"],
            "conditions": {},
            "trigger_conditions": {},
            "sections": {
                "vision_loss": [
                    {"type": "probe", "question": "Test?", "field": "test"}  # No 'id'
                ]
            },
            "follow_up_blocks": {}
        }
        
        temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(ruleset, temp_file)
        temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        
        with self.assertRaises(ValueError) as context:
            QuestionSelectorV2(temp_file.name)
        
        self.assertIn("id", str(context.exception).lower())
        os.unlink(temp_file.name)


# =============================================================================
# PART 9: Integration Tests with State Manager V2
# =============================================================================

class TestIntegrationWithStateManager(unittest.TestCase):
    """Integration tests with real State Manager V2."""
    
    def setUp(self):
        """Create ruleset and state manager."""
        self.ruleset = {
            "section_order": ["vision_loss", "headache"],
            "conditions": {
                "vl_single_eye_is_single": {
                    "all": [{"eq": ["vl_single_eye", "single"]}]
                },
                "headache": {
                    "all": [{"is_true": "h_present"}]
                }
            },
            "trigger_conditions": {
                "trigger_block_1": {
                    "condition": {
                        "all": [
                            {"eq": ["vl_single_eye", "single"]},
                            {"eq": ["vl_onset_speed", "subacute"]}
                        ]
                    },
                    "activates": "block_1"
                }
            },
            "sections": {
                "vision_loss": [
                    {"id": "vl_1", "type": "probe", "question": "Visual loss?", "field": "visual_loss_present"},
                    {"id": "vl_2", "type": "probe", "question": "One eye or both?", "field": "vl_single_eye"},
                    {"id": "vl_3", "type": "conditional", "condition": "vl_single_eye_is_single", 
                     "question": "Which eye?", "field": "vl_laterality"},
                    {"id": "vl_4", "type": "probe", "question": "How quickly?", "field": "vl_onset_speed"}
                ],
                "headache": [
                    {"id": "h_1", "type": "probe", "question": "Headache?", "field": "h_present"},
                    {"id": "h_2", "type": "conditional", "condition": "headache",
                     "question": "Describe headache", "field": "h_description"}
                ]
            },
            "follow_up_blocks": {
                "block_1": {
                    "name": "Optic Neuritis Screen",
                    "questions": [
                        {"id": "b1_1", "type": "probe", "question": "Worse with heat?", "field": "b1_uhthoff"},
                        {"id": "b1_2", "type": "probe", "question": "Depth perception issues?", "field": "b1_pulfrich"}
                    ]
                }
            }
        }
        
        self.temp_file = tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        )
        json.dump(self.ruleset, self.temp_file)
        self.temp_file.close()
        
        from backend.core.question_selector_v2 import QuestionSelectorV2
        from backend.core.state_manager_v2 import StateManagerV2
        
        self.selector = QuestionSelectorV2(self.temp_file.name)
        self.state = StateManagerV2()
    
    def tearDown(self):
        os.unlink(self.temp_file.name)
    
    def test_full_episode_workflow(self):
        """Test complete episode with question tracking and triggers."""
        # Create episode
        episode_id = self.state.create_episode()
        
        # Get first question
        episode_data = self.state.get_episode_for_selector(episode_id)
        q1 = self.selector.get_next_question(episode_data)
        self.assertEqual(q1["id"], "vl_1")
        
        # Simulate answering vl_1
        self.state.mark_question_answered(episode_id, "vl_1")
        self.state.set_episode_field(episode_id, "visual_loss_present", True)
        
        # Get next question
        episode_data = self.state.get_episode_for_selector(episode_id)
        q2 = self.selector.get_next_question(episode_data)
        self.assertEqual(q2["id"], "vl_2")
        
        # Answer vl_2 with "single"
        self.state.mark_question_answered(episode_id, "vl_2")
        self.state.set_episode_field(episode_id, "vl_single_eye", "single")
        
        # Now vl_3 (conditional) should be eligible
        episode_data = self.state.get_episode_for_selector(episode_id)
        q3 = self.selector.get_next_question(episode_data)
        self.assertEqual(q3["id"], "vl_3")
        
        # Answer vl_3
        self.state.mark_question_answered(episode_id, "vl_3")
        self.state.set_episode_field(episode_id, "vl_laterality", "right")
        
        # Get vl_4
        episode_data = self.state.get_episode_for_selector(episode_id)
        q4 = self.selector.get_next_question(episode_data)
        self.assertEqual(q4["id"], "vl_4")
        
        # Answer vl_4 with "subacute" - this should trigger block_1
        self.state.mark_question_answered(episode_id, "vl_4")
        self.state.set_episode_field(episode_id, "vl_onset_speed", "subacute")
        
        # Check triggers
        episode_data = self.state.get_episode_for_selector(episode_id)
        triggered = self.selector.check_triggers(episode_data)
        self.assertEqual(triggered, {"block_1"})
        
        # Activate the block
        self.state.activate_follow_up_block(episode_id, "block_1")
        
        # Next question should be from block_1, not headache section
        episode_data = self.state.get_episode_for_selector(episode_id)
        q5 = self.selector.get_next_question(episode_data)
        self.assertEqual(q5["id"], "b1_1")
        
        # Answer block questions
        self.state.mark_question_answered(episode_id, "b1_1")
        self.state.set_episode_field(episode_id, "b1_uhthoff", False)
        
        episode_data = self.state.get_episode_for_selector(episode_id)
        q6 = self.selector.get_next_question(episode_data)
        self.assertEqual(q6["id"], "b1_2")
        
        self.state.mark_question_answered(episode_id, "b1_2")
        self.state.set_episode_field(episode_id, "b1_pulfrich", False)
        
        # Check if block is complete
        episode_data = self.state.get_episode_for_selector(episode_id)
        self.assertTrue(self.selector.is_block_complete("block_1", episode_data))
        
        # Mark block complete
        self.state.complete_follow_up_block(episode_id, "block_1")
        
        # Now should move to headache section
        episode_data = self.state.get_episode_for_selector(episode_id)
        q7 = self.selector.get_next_question(episode_data)
        self.assertEqual(q7["id"], "h_1")
    
    def test_conditional_skipped_when_condition_not_met(self):
        """Test that conditional questions are skipped correctly."""
        episode_id = self.state.create_episode()
        
        # Answer first two questions
        self.state.mark_question_answered(episode_id, "vl_1")
        self.state.set_episode_field(episode_id, "visual_loss_present", True)
        
        # Answer vl_2 with "both" - vl_3 should be skipped
        self.state.mark_question_answered(episode_id, "vl_2")
        self.state.set_episode_field(episode_id, "vl_single_eye", "both")
        
        # Next should be vl_4, skipping vl_3
        episode_data = self.state.get_episode_for_selector(episode_id)
        q = self.selector.get_next_question(episode_data)
        self.assertEqual(q["id"], "vl_4")
    
    def test_multiple_episodes_independent(self):
        """Test that multiple episodes have independent question tracking."""
        # Episode 1
        ep1_id = self.state.create_episode()
        self.state.mark_question_answered(ep1_id, "vl_1")
        self.state.mark_question_answered(ep1_id, "vl_2")
        
        # Episode 2 - should start fresh
        ep2_id = self.state.create_episode()
        
        ep2_data = self.state.get_episode_for_selector(ep2_id)
        q = self.selector.get_next_question(ep2_data)
        
        # Episode 2 should start from vl_1
        self.assertEqual(q["id"], "vl_1")
        
        # Episode 1 should continue from where it was
        ep1_data = self.state.get_episode_for_selector(ep1_id)
        ep1_data["vl_single_eye"] = "single"  # Set field for conditional
        q = self.selector.get_next_question(ep1_data)
        self.assertEqual(q["id"], "vl_3")


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)