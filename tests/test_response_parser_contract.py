"""
Test ResponseParser V2 contract compliance

Verifies ResponseParser.parse() returns structure matching
response_parser_contract_v1.json
"""

import pytest
import json
from pathlib import Path
from datetime import datetime
from backend.core.response_parser_v2 import ResponseParser
from backend.utils.hf_client_v2 import HuggingFaceClient


class MockHFClient:
    """Mock HuggingFace client for testing"""
    
    def __init__(self, response=None, should_fail=False, fail_type='json'):
        self.response = response
        self.should_fail = should_fail
        self.fail_type = fail_type
        self.call_count = 0
    
    def is_loaded(self):
        return True
    
    def generate_json(self, prompt, max_tokens, temperature):
        self.call_count += 1
        
        if self.should_fail:
            if self.fail_type == 'json':
                return "{invalid json"
            elif self.fail_type == 'cuda':
                raise RuntimeError("CUDA out of memory")
            elif self.fail_type == 'timeout':
                raise TimeoutError("Generation timeout")
            elif self.fail_type == 'empty':
                return "{}"
        
        return self.response or '{"test_field": "test_value"}'


def validate_contract_shape(result):
    """Validate result has contract-compliant top-level shape"""
    assert isinstance(result, dict), "Result must be dict"
    assert set(result.keys()) == {'outcome', 'fields', 'metadata'}, \
        f"Result must have outcome, fields, metadata. Got: {result.keys()}"
    
    # Validate outcome
    assert isinstance(result['outcome'], str), "outcome must be string"
    valid_outcomes = {'success', 'partial_success', 'unclear', 'extraction_failed', 'generation_failed'}
    assert result['outcome'] in valid_outcomes, \
        f"outcome must be one of {valid_outcomes}, got {result['outcome']}"
    
    # Validate fields
    assert isinstance(result['fields'], dict), "fields must be dict"
    
    # Validate metadata
    assert isinstance(result['metadata'], dict), "metadata must be dict"
    required_meta_keys = {'expected_field', 'question_id', 'timestamp'}
    assert required_meta_keys.issubset(result['metadata'].keys()), \
        f"metadata missing required keys. Expected {required_meta_keys}, got {result['metadata'].keys()}"


# ========== SUCCESS Tests ==========

def test_success_basic():
    """Test basic success case"""
    mock_client = MockHFClient(response='{"vl_laterality": "right"}')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical',
        'valid_values': ['left', 'right']
    }
    
    result = parser.parse(question, "My right eye")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'success'
    assert 'vl_laterality' in result['fields']
    assert result['fields']['vl_laterality'] == 'right'
    assert result['metadata']['expected_field'] == 'vl_laterality'
    assert result['metadata']['question_id'] == 'vl_3'
    assert result['metadata']['error_message'] is None
    assert result['metadata']['error_type'] is None
    assert result['metadata']['unexpected_fields'] == []
    assert result['metadata']['validation_warnings'] == []


def test_success_with_unexpected_fields():
    """Test success with additional unexpected fields extracted"""
    mock_client = MockHFClient(response='{"vl_laterality": "right", "ac_redness": true}')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical',
        'valid_values': ['left', 'right']
    }
    
    result = parser.parse(question, "My right eye is red")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'success'  # Got expected field
    assert 'vl_laterality' in result['fields']
    assert 'ac_redness' in result['fields']
    assert result['metadata']['unexpected_fields'] == ['ac_redness']


def test_success_with_validation_warning():
    """Test success but with validation warning (invalid categorical value)"""
    mock_client = MockHFClient(response='{"vl_laterality": "right eye"}')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical',
        'valid_values': ['left', 'right']
    }
    
    result = parser.parse(question, "My right eye")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'success'  # Still success - got the field
    assert result['fields']['vl_laterality'] == 'right eye'
    
    # Check validation warning
    warnings = result['metadata']['validation_warnings']
    assert len(warnings) == 1
    assert warnings[0]['field'] == 'vl_laterality'
    assert warnings[0]['issue'] == 'not_in_valid_values'
    assert warnings[0]['value'] == 'right eye'
    assert warnings[0]['expected'] == ['left', 'right']


def test_success_with_boolean_normalization():
    """Test success with boolean normalization applied"""
    mock_client = MockHFClient(response='{"ep_present": "Yes"}')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'ep_1',
        'question': 'Do you have eye pain?',
        'field': 'ep_present',
        'field_type': 'boolean'
    }
    
    result = parser.parse(question, "Yes")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'success'
    assert result['fields']['ep_present'] is True  # Normalized
    
    # Check normalization record
    normalizations = result['metadata']['normalization_applied']
    assert len(normalizations) == 1
    assert normalizations[0]['field'] == 'ep_present'
    assert normalizations[0]['original_value'] == 'Yes'
    assert normalizations[0]['normalized_value'] is True
    assert normalizations[0]['normalization_type'] == 'boolean'


# ========== PARTIAL_SUCCESS Tests ==========

def test_partial_success():
    """Test partial success - unexpected fields only"""
    mock_client = MockHFClient(response='{"ac_redness": true}')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical'
    }
    
    result = parser.parse(question, "My eye is red")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'partial_success'
    assert 'ac_redness' in result['fields']
    assert 'vl_laterality' not in result['fields']
    assert result['metadata']['unexpected_fields'] == ['ac_redness']


# ========== UNCLEAR Tests ==========

def test_unclear():
    """Test unclear outcome (pure unclear pattern)"""
    parser = ResponseParser(MockHFClient())
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical'
    }
    
    result = parser.parse(question, "I don't know")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'unclear'
    assert result['fields'] == {}
    assert result['metadata']['error_message'] is None
    assert result['metadata']['raw_llm_output'] is None  # No LLM call made


# ========== EXTRACTION_FAILED Tests ==========

def test_extraction_failed_invalid_json():
    """Test extraction_failed due to invalid JSON"""
    mock_client = MockHFClient(should_fail=True, fail_type='json')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical'
    }
    
    result = parser.parse(question, "My right eye")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'extraction_failed'
    assert result['fields'] == {}
    assert result['metadata']['error_message'] is not None
    assert 'Invalid JSON' in result['metadata']['error_message']
    assert result['metadata']['error_type'] == 'JSONDecodeError'
    assert result['metadata']['raw_llm_output'] == "{invalid json"


def test_extraction_failed_empty_dict():
    """Test extraction_failed when LLM returns empty dict"""
    mock_client = MockHFClient(should_fail=True, fail_type='empty')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical'
    }
    
    result = parser.parse(question, "My right eye")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'extraction_failed'
    assert result['fields'] == {}
    assert result['metadata']['error_message'] == "LLM returned empty extraction"
    assert result['metadata']['error_type'] is None  # Not an exception
    assert result['metadata']['raw_llm_output'] == "{}"


# ========== GENERATION_FAILED Tests ==========

def test_generation_failed_cuda():
    """Test generation_failed due to CUDA error"""
    mock_client = MockHFClient(should_fail=True, fail_type='cuda')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical'
    }
    
    result = parser.parse(question, "My right eye")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'generation_failed'
    assert result['fields'] == {}
    assert result['metadata']['error_message'] == "CUDA out of memory"
    assert result['metadata']['error_type'] == 'RuntimeError'
    assert result['metadata']['raw_llm_output'] is None  # Generation never completed


def test_generation_failed_timeout():
    """Test generation_failed due to timeout"""
    mock_client = MockHFClient(should_fail=True, fail_type='timeout')
    parser = ResponseParser(mock_client)
    
    question = {
        'id': 'vl_3',
        'question': 'Which eye?',
        'field': 'vl_laterality',
        'field_type': 'categorical'
    }
    
    result = parser.parse(question, "My right eye")
    
    validate_contract_shape(result)
    assert result['outcome'] == 'generation_failed'
    assert result['metadata']['error_type'] == 'TimeoutError'


# ========== Metadata Tests ==========

def test_all_outcomes_have_timestamp():
    """Test that all outcomes include valid timestamp"""
    test_cases = [
        ('success', '{"vl_laterality": "right"}', False, None, "right eye"),
        ('unclear', None, False, None, "I don't know"),
        ('extraction_failed', None, True, 'json', "right eye"),
        ('extraction_failed', None, True, 'empty', "right eye"),
        ('generation_failed', None, True, 'cuda', "right eye")
    ]
    
    question = {
        'id': 'test',
        'question': 'Test?',
        'field': 'test_field',
        'field_type': 'text'
    }
    
    for expected_outcome, response, should_fail, fail_type, patient_response in test_cases:
        mock_client = MockHFClient(
            response=response,
            should_fail=should_fail,
            fail_type=fail_type
        )
        parser = ResponseParser(mock_client)
        
        result = parser.parse(question, patient_response)
        
        assert 'timestamp' in result['metadata']
        timestamp = result['metadata']['timestamp']
        assert timestamp is not None
        assert isinstance(timestamp, str)
        # Validate ISO 8601 format
        datetime.fromisoformat(timestamp.replace('Z', '+00:00'))


# ========== Input Validation Tests ==========

def test_invalid_question_type():
    """Test that invalid question type raises TypeError"""
    parser = ResponseParser(MockHFClient())
    
    with pytest.raises(TypeError, match="question must be dict"):
        parser.parse("not a dict", "response")


def test_missing_question_keys():
    """Test that missing required keys raises ValueError"""
    parser = ResponseParser(MockHFClient())
    
    with pytest.raises(ValueError, match="missing required keys"):
        parser.parse({'id': 'test'}, "response")


def test_invalid_response_type():
    """Test that invalid response type raises TypeError"""
    parser = ResponseParser(MockHFClient())
    
    question = {
        'id': 'test',
        'question': 'Test?',
        'field': 'test_field',
        'field_type': 'text'
    }
    
    with pytest.raises(TypeError, match="patient_response must be string"):
        parser.parse(question, 123)


def test_invalid_valid_values_type():
    """Test that invalid valid_values type raises ValueError"""
    parser = ResponseParser(MockHFClient())
    
    question = {
        'id': 'test',
        'question': 'Test?',
        'field': 'test_field',
        'field_type': 'categorical',
        'valid_values': "not a list"  # Should be list
    }
    
    with pytest.raises(ValueError, match="valid_values must be list"):
        parser.parse(question, "test")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])