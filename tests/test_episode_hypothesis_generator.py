"""
Test Episode Hypothesis Generator

Tests the LLM-powered Episode Hypothesis Generator module.

Run from project root:
    python -m tests.test_episode_hypothesis_generator

Requires:
    - HuggingFace model loaded (CUDA GPU recommended)
    - episode_hypothesis_generator.py
    - episode_hypothesis_signal.py
    - hf_client_v2.py
"""

import pytest
import logging
from unittest.mock import Mock, patch

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)

# Import the module under test
from backend.core.episode_hypothesis_generator import EpisodeHypothesisGenerator
from backend.utils.episode_hypothesis_signal import EpisodeHypothesisSignal, ConfidenceBand


class TestEpisodeHypothesisGeneratorUnit:
    """Unit tests with mocked HF client"""
    
    @pytest.fixture
    def mock_hf_client(self):
        """Create a mock HuggingFace client"""
        mock = Mock()
        mock.is_loaded.return_value = True
        mock.generate_json = Mock()
        return mock
    
    @pytest.fixture
    def ehg(self, mock_hf_client):
        """Create EHG with mock client"""
        return EpisodeHypothesisGenerator(mock_hf_client)
    
    def test_init_validates_hf_client_interface(self):
        """Should reject objects without required methods"""
        # Object without generate_json method
        bad_client = Mock(spec=[])  # Empty spec - no methods
        with pytest.raises(TypeError, match="generate_json"):
            EpisodeHypothesisGenerator(bad_client)
        
        # Object with generate_json but without is_loaded
        partial_client = Mock()
        partial_client.generate_json = Mock()
        del partial_client.is_loaded  # Remove the auto-created attribute
        # Note: Mock auto-creates attributes, so we need spec to prevent this
        partial_client2 = Mock(spec=['generate_json'])
        partial_client2.generate_json = Mock()
        with pytest.raises(TypeError, match="is_loaded"):
            EpisodeHypothesisGenerator(partial_client2)
    
    def test_init_validates_model_loaded(self, mock_hf_client):
        """Should reject client with unloaded model"""
        mock_hf_client.is_loaded.return_value = False
        with pytest.raises(RuntimeError, match="not loaded"):
            EpisodeHypothesisGenerator(mock_hf_client)
    
    def test_empty_utterance_returns_zero_hypothesis(self, ehg, mock_hf_client):
        """Empty input should return hypothesis_count=0 without calling LLM"""
        signal = ehg.generate_hypothesis("")
        
        assert signal.hypothesis_count == 0
        assert signal.pivot_detected == False
        assert signal.confidence_band == ConfidenceBand.HIGH
        mock_hf_client.generate_json.assert_not_called()
    
    def test_none_utterance_returns_zero_hypothesis(self, ehg, mock_hf_client):
        """None input should return hypothesis_count=0 without calling LLM"""
        signal = ehg.generate_hypothesis(None)
        
        assert signal.hypothesis_count == 0
        mock_hf_client.generate_json.assert_not_called()
    
    def test_valid_json_response_single_episode(self, ehg, mock_hf_client):
        """Valid JSON with single episode should be parsed correctly"""
        mock_hf_client.generate_json.return_value = '''
        {"hypothesis_count": 1, "hypothesis_confidence": "high", "pivot_detected": false, "pivot_confidence": "high"}
        '''
        
        signal = ehg.generate_hypothesis("My right eye hurts")
        
        assert signal.hypothesis_count == 1
        assert signal.confidence_band == ConfidenceBand.HIGH
        assert signal.pivot_detected == False
        assert signal.pivot_confidence_band == ConfidenceBand.HIGH
    
    def test_valid_json_response_multiple_episodes(self, ehg, mock_hf_client):
        """Valid JSON with multiple episodes should be parsed correctly"""
        mock_hf_client.generate_json.return_value = '''
        {"hypothesis_count": 2, "hypothesis_confidence": "medium", "pivot_detected": false, "pivot_confidence": "low"}
        '''
        
        signal = ehg.generate_hypothesis("My right eye hurts and I also have headaches")
        
        assert signal.hypothesis_count == 2
        assert signal.confidence_band == ConfidenceBand.MEDIUM
        assert signal.pivot_detected == False
        assert signal.pivot_confidence_band == ConfidenceBand.LOW
    
    def test_valid_json_response_pivot_detected(self, ehg, mock_hf_client):
        """Valid JSON with pivot should be parsed correctly"""
        mock_hf_client.generate_json.return_value = '''
        {"hypothesis_count": 1, "hypothesis_confidence": "high", "pivot_detected": true, "pivot_confidence": "medium"}
        '''
        
        signal = ehg.generate_hypothesis("Actually, forget about my eye, I want to talk about headaches")
        
        assert signal.hypothesis_count == 1
        assert signal.pivot_detected == True
        assert signal.pivot_confidence_band == ConfidenceBand.MEDIUM
    
    def test_invalid_json_returns_safe_default(self, ehg, mock_hf_client):
        """Invalid JSON should return safe default signal"""
        mock_hf_client.generate_json.return_value = "not valid json"
        
        signal = ehg.generate_hypothesis("My eye hurts")
        
        assert signal.hypothesis_count == 1
        assert signal.pivot_detected == False
        assert signal.confidence_band == ConfidenceBand.HIGH
    
    def test_missing_fields_use_defaults(self, ehg, mock_hf_client):
        """Missing fields should use defaults"""
        mock_hf_client.generate_json.return_value = '{"hypothesis_count": 2}'
        
        signal = ehg.generate_hypothesis("My eye hurts")
        
        assert signal.hypothesis_count == 2
        # Missing fields should use defaults
        assert signal.confidence_band == ConfidenceBand.HIGH
        assert signal.pivot_detected == False
        assert signal.pivot_confidence_band == ConfidenceBand.HIGH
    
    def test_negative_hypothesis_count_clamped_to_zero(self, ehg, mock_hf_client):
        """Negative hypothesis count should be clamped to 0"""
        mock_hf_client.generate_json.return_value = '{"hypothesis_count": -1}'
        
        signal = ehg.generate_hypothesis("My eye hurts")
        
        assert signal.hypothesis_count == 0
    
    def test_high_hypothesis_count_capped_at_two(self, ehg, mock_hf_client):
        """High hypothesis count should be capped at 2"""
        mock_hf_client.generate_json.return_value = '{"hypothesis_count": 5}'
        
        signal = ehg.generate_hypothesis("My eye hurts")
        
        assert signal.hypothesis_count == 2
    
    def test_llm_call_failure_raises_runtime_error(self, ehg, mock_hf_client):
        """LLM call failure should raise RuntimeError"""
        mock_hf_client.generate_json.side_effect = Exception("CUDA OOM")
        
        with pytest.raises(RuntimeError, match="EHG LLM call failed"):
            ehg.generate_hypothesis("My eye hurts")
    
    def test_prompt_includes_system_question(self, ehg, mock_hf_client):
        """Prompt should include last system question when provided"""
        mock_hf_client.generate_json.return_value = '{"hypothesis_count": 1}'
        
        ehg.generate_hypothesis(
            "Both eyes",
            last_system_question="Which eye is affected?"
        )
        
        # Check the prompt was built with the question
        call_args = mock_hf_client.generate_json.call_args
        prompt = call_args.kwargs.get('prompt') or call_args.args[0]
        assert "Which eye is affected?" in prompt
    
    def test_prompt_includes_episode_context(self, ehg, mock_hf_client):
        """Prompt should include episode context when provided"""
        mock_hf_client.generate_json.return_value = '{"hypothesis_count": 1}'
        
        context = {"active_symptom_categories": ["visual_loss", "headache"]}
        ehg.generate_hypothesis(
            "It's getting worse",
            current_episode_context=context
        )
        
        # Check the prompt includes context
        call_args = mock_hf_client.generate_json.call_args
        prompt = call_args.kwargs.get('prompt') or call_args.args[0]
        assert "visual_loss" in prompt
        assert "headache" in prompt


class TestEpisodeHypothesisGeneratorIntegration:
    """
    Integration tests with real HF client.
    
    These tests require a GPU and will be slow.
    Mark with @pytest.mark.slow for optional skipping.
    """
    
    @pytest.fixture(scope="class")
    def real_hf_client(self):
        """Load real HuggingFace client (expensive - once per class)"""
        from backend.utils.hf_client_v2 import HuggingFaceClient
        
        try:
            client = HuggingFaceClient(
                model_name="mistralai/Mistral-7B-Instruct-v0.2",
                load_in_4bit=True
            )
            return client
        except Exception as e:
            pytest.skip(f"Could not load HF client: {e}")
    
    @pytest.fixture
    def ehg(self, real_hf_client):
        """Create EHG with real client"""
        return EpisodeHypothesisGenerator(real_hf_client)
    
    @pytest.mark.slow
    def test_single_episode_response(self, ehg):
        """Real model should detect single episode"""
        signal = ehg.generate_hypothesis(
            "My right eye has been hurting for the past week",
            last_system_question="Can you tell me about your eye problem?"
        )
        
        assert signal.hypothesis_count == 1
        assert signal.pivot_detected == False
    
    @pytest.mark.slow
    def test_multiple_episode_response(self, ehg):
        """Real model should detect multiple episodes"""
        signal = ehg.generate_hypothesis(
            "I have two problems - my right eye is blurry and I also get terrible headaches with flashing lights",
            last_system_question="Can you tell me about your eye problem?"
        )
        
        assert signal.hypothesis_count >= 2
    
    @pytest.mark.slow
    def test_pivot_detection(self, ehg):
        """Real model should detect pivot"""
        signal = ehg.generate_hypothesis(
            "Actually, forget about my blurry vision. I want to talk about a different problem - I've been seeing flashing lights.",
            last_system_question="How long has your vision been blurry?",
            current_episode_context={"active_symptom_categories": ["visual_loss"]}
        )
        
        assert signal.pivot_detected == True
    
    @pytest.mark.slow
    def test_off_topic_response(self, ehg):
        """Real model should handle off-topic responses"""
        signal = ehg.generate_hypothesis(
            "Hello, how are you today?",
            last_system_question="Can you tell me about your eye problem?"
        )
        
        # Off-topic could be 0 or 1 depending on model interpretation
        assert signal.hypothesis_count in [0, 1]


if __name__ == "__main__":
    # Run unit tests only (no GPU required)
    pytest.main([__file__, "-v", "-m", "not slow"])