"""
Unit Tests for Summary Generator

Tests:
1. Basic initialization
2. Simple summary generation with mock data
3. Dialogue formatting
4. Structured data formatting
5. Summary cleaning
6. File saving
7. Integration with real LLM (optional - slow)
"""

import sys
import os
import tempfile
from pathlib import Path

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.core.summary_generator import SummaryGenerator
from backend.utils.hf_client import HuggingFaceClient


def print_test_header(test_name):
    """Print formatted test header"""
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print('='*60)


def test_initialization():
    """Test 1: Summary Generator initializes with HF client"""
    print_test_header("Initialization")
    
    try:
        # Load model (this takes time)
        print("Loading model (this takes ~30 seconds)...")
        hf_client = HuggingFaceClient(
            model_name="mistralai/Mistral-7B-Instruct-v0.2",
            load_in_4bit=True
        )
        
        # Initialize generator
        generator = SummaryGenerator(hf_client)
        
        print(f"✓ Summary Generator initialized")
        print(f"✓ Generation mode: {generator.generation_mode}")
        print(f"✓ Section order: {len(generator.SECTION_ORDER)} sections")
        
        return generator
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_dialogue_formatting(generator):
    """Test 2: Dialogue formatting"""
    print_test_header("Dialogue Formatting")
    
    # Sample dialogue
    dialogue = [
        {
            'question': 'What brings you to the clinic?',
            'response': 'My right eye has been blurry',
            'extracted': {'presenting_complaint_description': 'blurry right eye'}
        },
        {
            'question': 'When did this start?',
            'response': '3 months ago',
            'extracted': {'vl_onset': '3 months ago'}
        }
    ]
    
    try:
        formatted = generator._format_dialogue(dialogue)
        
        print("Formatted dialogue:")
        print(formatted[:200] + "..." if len(formatted) > 200 else formatted)
        
        # Verify structure
        assert 'Turn 1:' in formatted, "Should have turn numbers"
        assert 'Question:' in formatted, "Should have questions"
        assert 'Patient:' in formatted, "Should have patient responses"
        assert 'blurry' in formatted, "Should contain actual content"
        
        print("\n✓ PASS: Dialogue formatted correctly")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_structured_data_formatting(generator):
    """Test 3: Structured data formatting"""
    print_test_header("Structured Data Formatting")
    
    # Sample structured data
    data = {
        'vl_laterality': 'monocular_right',
        'vl_onset': '3 months ago',
        'h_present': True,
        'h_location': 'right-sided',
        'presenting_complaint_description': 'Blurry vision'
    }
    
    try:
        formatted = generator._format_structured_data(data)
        
        print("Formatted structured data:")
        print(formatted)
        
        # Verify grouping by section
        assert 'Vision Loss:' in formatted, "Should group vision loss fields"
        assert 'Headache:' in formatted, "Should group headache fields"
        assert 'vl_laterality' in formatted, "Should include field names"
        
        print("\n✓ PASS: Structured data formatted correctly")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_summary_cleaning(generator):
    """Test 4: Summary text cleaning"""
    print_test_header("Summary Cleaning")
    
    # Test cases with various formatting issues
    test_cases = [
        (
            "```\nOVERVIEW\nSummary text\n```",
            "OVERVIEW\nSummary text"
        ),
        (
            "Normal text\n\n\n\n\nToo many blank lines",
            "Normal text\n\nToo many blank lines"
        ),
        (
            "   Leading and trailing spaces   ",
            "Leading and trailing spaces"
        )
    ]
    
    try:
        for input_text, expected_output in test_cases:
            cleaned = generator._clean_summary(input_text)
            assert cleaned == expected_output, f"Expected '{expected_output}', got '{cleaned}'"
            print(f"✓ Cleaned: '{input_text[:30]}...' → '{cleaned[:30]}...'")
        
        print("\n✓ PASS: Summary cleaning working")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_file_saving(generator):
    """Test 5: Save summary to file"""
    print_test_header("File Saving")
    
    summary_text = """OVERVIEW

This is a test summary.

PRESENTING COMPLAINT

Patient reports test symptoms.
"""
    
    try:
        # Use temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            temp_path = f.name
        
        # Save summary
        generator.save_summary(summary_text, temp_path)
        
        # Verify file exists
        assert Path(temp_path).exists(), "File should exist"
        print(f"✓ File created: {temp_path}")
        
        # Read back and verify
        with open(temp_path, 'r') as f:
            content = f.read()
        
        assert content == summary_text, "Content should match"
        print(f"✓ Content verified")
        
        # Clean up
        Path(temp_path).unlink()
        
        print("\n✓ PASS: File saving working")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_real_summary_generation(generator):
    """Test 6: Generate real summary with LLM (slow test)"""
    print_test_header("Real Summary Generation")
    
    # Realistic consultation data
    dialogue = [
        {
            'question': 'What brings you to the clinic today?',
            'response': "I've been having trouble with my vision. My right eye has been really blurry.",
            'extracted': {'presenting_complaint_description': 'blurry right eye vision'}
        },
        {
            'question': 'When did this start?',
            'response': 'About 3 months ago',
            'extracted': {'vl_onset': '3 months ago'}
        },
        {
            'question': 'Which eye is affected?',
            'response': 'Just my right eye',
            'extracted': {'vl_laterality': 'monocular_right'}
        },
        {
            'question': 'How quickly did it develop?',
            'response': 'It came on over a few hours',
            'extracted': {'vl_onset_speed': 'subacute'}
        },
        {
            'question': 'Are you experiencing headaches?',
            'response': 'Yes, I have been getting headaches',
            'extracted': {'h_present': True}
        }
    ]
    
    structured_data = {
        'presenting_complaint_description': 'blurry right eye vision',
        'vl_laterality': 'monocular_right',
        'vl_onset': '3 months ago',
        'vl_onset_speed': 'subacute',
        'h_present': True,
        'cp_present': False,
        'vp_present': False,
        'dp_present': False
    }
    
    try:
        print("Generating summary with LLM (this takes ~10-15 seconds)...")
        
        summary = generator.generate(
            dialogue_history=dialogue,
            structured_data=structured_data,
            temperature=0.1,
            target_length="medium"
        )
        
        print(f"\n{'='*60}")
        print("GENERATED SUMMARY:")
        print('='*60)
        print(summary)
        print('='*60)
        
        # Basic validation
        assert len(summary) > 100, "Summary should have substantial content"
        assert 'OVERVIEW' in summary.upper() or 'overview' in summary.lower(), "Should have overview"
        print(f"\n✓ Summary length: {len(summary)} characters")
        
        # Check for second-person language
        second_person_count = summary.lower().count('you ') + summary.lower().count('your ')
        print(f"✓ Second-person usage: {second_person_count} instances")
        
        if second_person_count > 0:
            print("✓ Using second person ('you') as requested")
        else:
            print("⚠ Warning: Not using second person - prompt may need adjustment")
        
        print("\n✓ PASS: Real summary generated")
        
        return summary
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def run_all_tests():
    """Run all Summary Generator tests"""
    print("\n" + "#"*60)
    print("# Summary Generator Test Suite")
    print("#"*60)
    
    try:
        # Test 1: Initialization (loads model)
        generator = test_initialization()
        
        # Test 2: Dialogue formatting
        test_dialogue_formatting(generator)
        
        # Test 3: Structured data formatting
        test_structured_data_formatting(generator)
        
        # Test 4: Summary cleaning
        test_summary_cleaning(generator)
        
        # Test 5: File saving
        test_file_saving(generator)
        
        # Test 6: Real generation (slow but important)
        print("\n" + "!"*60)
        print("! Starting LLM-based test (this will take ~15 seconds)")
        print("!"*60)
        test_real_summary_generation(generator)
        
        # Summary
        print("\n" + "#"*60)
        print("# ALL TESTS PASSED")
        print("#"*60)
        print("\n✓ ✓ ✓ Summary Generator module working correctly ✓ ✓ ✓")
        print("\nKey features validated:")
        print("  • HuggingFace client integration")
        print("  • Dialogue formatting")
        print("  • Structured data formatting")
        print("  • Summary text cleaning")
        print("  • File saving")
        print("  • Real LLM-based summary generation")
        print("\nNext step: Integrate with full system")
        
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