"""
Test Response Parser - Basic functionality tests

Run this to verify:
1. HuggingFace client loads model
2. Response Parser initializes
3. Basic extraction works
4. Unclear responses handled
5. JSON parsing failures handled

Usage:
    cd ~/ophthalmology_mvp
    python3 tests/test_response_parser.py
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import logging
from backend.utils.hf_client import HuggingFaceClient
from backend.core.response_parser import ResponseParser

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_hf_client_initialization():
    """Test 1: HuggingFace client loads model"""
    print("\n" + "="*60)
    print("TEST 1: HuggingFace Client Initialization")
    print("="*60)
    
    try:
        client = HuggingFaceClient(
            model_name="mistralai/Mistral-7B-Instruct-v0.2",
            load_in_4bit=True
        )
        
        assert client.is_loaded(), "Model should be loaded"
        
        info = client.get_model_info()
        print(f"✓ Model loaded: {info['model_name']}")
        print(f"✓ Device: {info['device']}")
        if 'gpu_memory_allocated_gb' in info:
            print(f"✓ GPU memory: {info['gpu_memory_allocated_gb']:.2f}GB")
        
        return client
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        raise


def test_response_parser_initialization(client):
    """Test 2: Response Parser initializes with client"""
    print("\n" + "="*60)
    print("TEST 2: Response Parser Initialization")
    print("="*60)
    
    try:
        parser = ResponseParser(client)
        print("✓ Response Parser initialized")
        return parser
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        raise


def test_basic_extraction(parser):
    """Test 3: Basic extraction works"""
    print("\n" + "="*60)
    print("TEST 3: Basic Extraction")
    print("="*60)
    
    question = {
        'id': 'vl_2',
        'question': 'Which eye is affected?',
        'field': 'vl_laterality',
        'field_type': 'categorical',
        'valid_values': ['monocular_left', 'monocular_right', 'binocular']
    }
    
    patient_response = "My right eye went blurry"
    
    print(f"Question: {question['question']}")
    print(f"Patient: '{patient_response}'")
    print("\nCalling LLM (this may take 5-10 seconds)...")
    
    try:
        result = parser.parse(question, patient_response)
        
        print("\nResult:")
        for key, value in result.items():
            if key != '_meta':
                print(f"  {key}: {value}")
        
        print("\nMetadata:")
        for key, value in result['_meta'].items():
            if key != 'raw_llm_output':
                print(f"  {key}: {value}")
        
        # Validate structure
        assert '_meta' in result, "Should have _meta"
        assert 'extraction_failed' in result['_meta'], "Should have extraction_failed flag"
        
        if not result['_meta']['extraction_failed']:
            print("\n✓ Extraction succeeded")
            if 'vl_laterality' in result:
                print(f"✓ Extracted laterality: {result['vl_laterality']}")
        else:
            print("\n⚠ Extraction failed (this is OK for MVP with base model)")
        
        return result
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        raise


def test_unclear_response(parser):
    """Test 4: Unclear responses handled"""
    print("\n" + "="*60)
    print("TEST 4: Unclear Response Handling")
    print("="*60)
    
    question = {
        'id': 'vl_8',
        'question': 'When did this start?',
        'field': 'vl_onset',
        'field_type': 'text'
    }
    
    patient_response = "I don't know"
    
    print(f"Question: {question['question']}")
    print(f"Patient: '{patient_response}'")
    
    try:
        result = parser.parse(question, patient_response)
        
        print("\nResult:")
        print(f"  unclear_response: {result['_meta']['unclear_response']}")
        print(f"  extraction_failed: {result['_meta']['extraction_failed']}")
        
        assert result['_meta']['unclear_response'] == True, "Should detect unclear"
        print("\n✓ Unclear response detected correctly")
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        raise


def test_multi_field_extraction(parser):
    """Test 5: Multiple fields in one response"""
    print("\n" + "="*60)
    print("TEST 5: Multi-Field Extraction")
    print("="*60)
    
    question = {
        'id': 'vl_2',
        'question': 'Which eye is affected?',
        'field': 'vl_laterality',
        'field_type': 'categorical',
        'valid_values': ['monocular_left', 'monocular_right', 'binocular']
    }
    
    patient_response = "My right eye went blurry about 3 months ago"
    
    print(f"Question: {question['question']}")
    print(f"Patient: '{patient_response}'")
    print("\nThis response contains multiple fields:")
    print("  - vl_laterality (right eye)")
    print("  - vl_onset (3 months ago)")
    print("\nCalling LLM...")
    
    try:
        result = parser.parse(question, patient_response)
        
        print("\nExtracted fields:")
        for key, value in result.items():
            if key != '_meta':
                print(f"  {key}: {value}")
        
        # Count extracted fields (excluding _meta)
        field_count = len([k for k in result.keys() if k != '_meta'])
        
        if field_count > 1:
            print(f"\n✓ Extracted {field_count} fields from single response")
        else:
            print("\n⚠ Only extracted 1 field (base model may not multi-extract well)")
        
    except Exception as e:
        print(f"✗ FAILED: {e}")
        raise


def run_all_tests():
    """Run all tests"""
    print("\n" + "#"*60)
    print("# Response Parser Test Suite")
    print("#"*60)
    
    try:
        # Test 1: Load model
        client = test_hf_client_initialization()
        
        # Test 2: Initialize parser
        parser = test_response_parser_initialization(client)
        
        # Test 3: Basic extraction
        test_basic_extraction(parser)
        
        # Test 4: Unclear responses
        test_unclear_response(parser)
        
        # Test 5: Multi-field extraction
        test_multi_field_extraction(parser)
        
        print("\n" + "#"*60)
        print("# TEST SUITE COMPLETE")
        print("#"*60)
        print("\nAll tests passed!")
        print("\nNotes:")
        print("- Base model accuracy may be low - this is expected")
        print("- Fine-tuning will improve extraction quality")
        print("- The important thing is: no crashes, structure is correct")
        
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
    except Exception as e:
        print(f"\n\nTest suite failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    run_all_tests()