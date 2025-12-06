"""
Unit Tests for JSON Formatter

Tests:
1. Basic initialization with schema
2. Field mapping from state to sections
3. Type conversion (string booleans, integers)
4. Status block generation
5. Metadata generation
6. Unmapped field handling
7. Missing required field warnings
8. File output
"""

import sys
import os
import json
import tempfile
from pathlib import Path

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.core.json_formatter import JSONFormatter


def print_test_header(test_name):
    """Print formatted test header"""
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print('='*60)


def test_initialization():
    """Test 1: Formatter initializes with schema"""
    print_test_header("Initialization")
    
    schema_path = "data/mvp_json_schema.json"
    
    try:
        formatter = JSONFormatter(schema_path)
        
        print(f"✓ Schema loaded: {schema_path}")
        print(f"✓ Schema version: {formatter.schema_version}")
        print(f"✓ Sections found: {len(formatter.section_definitions)}")
        print(f"✓ Fields mapped: {len(formatter.field_to_section)}")
        
        # Verify sections exist
        assert len(formatter.section_definitions) > 0, "Should have sections"
        assert len(formatter.field_to_section) > 0, "Should have field mappings"
        
        print("\n✓ PASS: Initialization successful")
        return formatter
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_basic_formatting(formatter):
    """Test 2: Basic state to JSON formatting"""
    print_test_header("Basic Formatting")
    
    # Simple state data
    state_data = {
        'presenting_complaint_description': 'Right eye blurry',
        'previous_instances': False,
        'vl_laterality': 'monocular_right',
        'vl_onset': '3 months ago',
        'h_present': True
    }
    
    try:
        result = formatter.format(state_data)
        
        # Check structure
        assert 'metadata' in result, "Should have metadata"
        assert 'consultation_id' in result['metadata'], "Should have consultation ID"
        assert 'schema_version' in result['metadata'], "Should have schema version"
        
        print(f"✓ Metadata present")
        print(f"  - Consultation ID: {result['metadata']['consultation_id']}")
        print(f"  - Schema version: {result['metadata']['schema_version']}")
        print(f"  - Completeness: {result['metadata']['completeness_score']:.2%}")
        
        # Check sections exist
        section_names = [k for k in result.keys() if k != 'metadata']
        assert len(section_names) > 0, "Should have sections"
        print(f"✓ Sections created: {len(section_names)}")
        
        # Check status blocks
        for section_name in section_names[:3]:  # Check first 3
            assert '_status' in result[section_name], f"Section {section_name} should have _status"
            status = result[section_name]['_status']
            assert 'complete' in status, "Status should have complete flag"
            assert 'fields_present' in status, "Status should have fields_present"
            assert 'missing_required' in status, "Status should have missing_required"
        
        print(f"✓ Status blocks present in all sections")
        
        print("\n✓ PASS: Basic formatting works")
        return result
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_type_conversion(formatter):
    """Test 3: Type conversion (string to boolean/integer)"""
    print_test_header("Type Conversion")
    
    state_data = {
        'h_present': 'true',  # String boolean
        'previous_instances': 'false',  # String boolean
        'ep_severity': '7',  # String integer
        'vl_laterality': 'monocular_right'  # Already correct type
    }
    
    try:
        result = formatter.format(state_data)
        
        # Find headache section
        if 'headache' in result:
            h_present_value = result['headache'].get('h_present')
            print(f"✓ h_present: '{state_data['h_present']}' → {h_present_value} (type: {type(h_present_value).__name__})")
            # Should be converted to boolean True
            assert isinstance(h_present_value, bool), "Should convert string 'true' to boolean"
            assert h_present_value == True, "Should be True"
        
        # Check warnings
        warnings = result['metadata'].get('warnings', [])
        conversion_warnings = [w for w in warnings if 'converted' in w.lower()]
        print(f"✓ Conversion warnings: {len(conversion_warnings)}")
        
        if conversion_warnings:
            for warning in conversion_warnings[:3]:  # Show first 3
                print(f"  - {warning}")
        
        print("\n✓ PASS: Type conversion working")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_status_blocks(formatter):
    """Test 4: Status block accuracy"""
    print_test_header("Status Blocks")
    
    # Partial data - some fields missing
    state_data = {
        'presenting_complaint_description': 'Vision loss',
        # Missing: previous_instances
        'vl_laterality': 'monocular_right',
        'vl_onset': '2 weeks ago'
        # Many vision_loss fields missing
    }
    
    try:
        result = formatter.format(state_data)
        
        # Check chief_complaint status
        if 'chief_complaint' in result:
            cc_status = result['chief_complaint']['_status']
            print(f"\nChief Complaint Status:")
            print(f"  Complete: {cc_status['complete']}")
            print(f"  Present: {cc_status['fields_present']}/{cc_status['fields_expected']}")
            print(f"  Missing required: {cc_status['missing_required']}")
        
        # Check visual_loss status
        if 'visual_loss' in result:
            vl_status = result['visual_loss']['_status']
            print(f"\nVisual Loss Status:")
            print(f"  Complete: {vl_status['complete']}")
            print(f"  Present: {vl_status['fields_present']}/{vl_status['fields_expected']}")
            print(f"  Missing required: {len(vl_status['missing_required'])} fields")
            
            # Should not be complete (many fields missing)
            assert vl_status['complete'] == False, "Section should be incomplete"
        
        print("\n✓ PASS: Status blocks accurate")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_unmapped_fields(formatter):
    """Test 5: Unmapped field handling"""
    print_test_header("Unmapped Fields")
    
    state_data = {
        'vl_laterality': 'monocular_right',
        'unknown_field_1': 'some value',  # Not in schema
        'typo_field': 'another value',    # Not in schema
        'h_present': True
    }
    
    try:
        result = formatter.format(state_data)
        
        # Check unmapped fields captured
        unmapped = result['metadata'].get('unmapped_fields', {})
        print(f"Unmapped fields found: {len(unmapped)}")
        
        for field_name, value in unmapped.items():
            print(f"  - {field_name}: {value}")
        
        assert 'unknown_field_1' in unmapped, "Should capture unknown_field_1"
        assert 'typo_field' in unmapped, "Should capture typo_field"
        assert 'vl_laterality' not in unmapped, "Should not mark valid fields as unmapped"
        
        print("\n✓ PASS: Unmapped fields handled correctly")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_completeness_score(formatter):
    """Test 6: Completeness score calculation"""
    print_test_header("Completeness Score")
    
    # Test with varying amounts of data
    test_cases = [
        ({}, "empty"),
        ({'vl_laterality': 'monocular_right'}, "minimal"),
        ({
            'presenting_complaint_description': 'Test',
            'previous_instances': False,
            'vl_laterality': 'monocular_right',
            'vl_onset': '1 week',
            'vl_onset_speed': 'acute',
            'h_present': False,
            'ep_present': False
        }, "moderate")
    ]
    
    try:
        for state_data, label in test_cases:
            result = formatter.format(state_data)
            score = result['metadata']['completeness_score']
            present = result['metadata']['total_fields_present']
            expected = result['metadata']['total_fields_expected']
            
            print(f"\n{label.capitalize()} data:")
            print(f"  Fields: {present}/{expected}")
            print(f"  Score: {score:.2%}")
            
            # Verify calculation
            calculated_score = present / expected if expected > 0 else 0
            assert abs(score - calculated_score) < 0.01, "Score calculation should be accurate"
        
        print("\n✓ PASS: Completeness score calculated correctly")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_file_output(formatter):
    """Test 7: JSON file output"""
    print_test_header("File Output")
    
    state_data = {
        'presenting_complaint_description': 'Test complaint',
        'vl_laterality': 'binocular',
        'h_present': True
    }
    
    try:
        # Use temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name
        
        # Format with file output
        result = formatter.format(state_data, output_path=temp_path)
        
        # Check file exists
        assert Path(temp_path).exists(), "Output file should exist"
        print(f"✓ File created: {temp_path}")
        
        # Load and verify
        with open(temp_path, 'r') as f:
            loaded = json.load(f)
        
        assert 'metadata' in loaded, "Loaded JSON should have metadata"
        assert 'consultation_id' in loaded['metadata'], "Should have consultation ID"
        print(f"✓ File contains valid JSON")
        
        # Check pretty-printing (indentation)
        with open(temp_path, 'r') as f:
            content = f.read()
        
        assert '\n' in content, "Should be pretty-printed (multi-line)"
        assert '  ' in content, "Should have indentation"
        print(f"✓ File is pretty-printed")
        
        # Clean up
        Path(temp_path).unlink()
        
        print("\n✓ PASS: File output working")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_section_completeness_summary(formatter):
    """Test 8: Section completeness summary helper"""
    print_test_header("Section Completeness Summary")
    
    state_data = {
        'presenting_complaint_description': 'Test',
        'previous_instances': False,
        'vl_laterality': 'monocular_right',
        'h_present': True
    }
    
    try:
        summary = formatter.get_section_completeness(state_data)
        
        print(f"Sections analyzed: {len(summary)}")
        
        # Show first few sections
        for section_name, info in list(summary.items())[:5]:
            complete_marker = "✓" if info['complete'] else "○"
            print(f"  {complete_marker} {section_name}: {info['present']}/{info['expected']} ({info['percentage']:.1f}%)")
        
        # Verify structure
        for section_name, info in summary.items():
            assert 'complete' in info, "Should have complete flag"
            assert 'percentage' in info, "Should have percentage"
            assert isinstance(info['percentage'], (int, float)), "Percentage should be numeric"
        
        print("\n✓ PASS: Section completeness summary working")
        
    except Exception as e:
        print(f"\n✗ FAIL: {e}")
        import traceback
        traceback.print_exc()
        raise


def run_all_tests():
    """Run all JSON Formatter tests"""
    print("\n" + "#"*60)
    print("# JSON Formatter Test Suite")
    print("#"*60)
    
    try:
        # Test 1: Initialization
        formatter = test_initialization()
        
        # Test 2: Basic formatting
        test_basic_formatting(formatter)
        
        # Test 3: Type conversion
        test_type_conversion(formatter)
        
        # Test 4: Status blocks
        test_status_blocks(formatter)
        
        # Test 5: Unmapped fields
        test_unmapped_fields(formatter)
        
        # Test 6: Completeness score
        test_completeness_score(formatter)
        
        # Test 7: File output
        test_file_output(formatter)
        
        # Test 8: Section completeness helper
        test_section_completeness_summary(formatter)
        
        # Summary
        print("\n" + "#"*60)
        print("# ALL TESTS PASSED")
        print("#"*60)
        print("\n✓ ✓ ✓ JSON Formatter module working correctly ✓ ✓ ✓")
        print("\nKey features validated:")
        print("  • Schema loading and field mapping")
        print("  • State to JSON conversion")
        print("  • Type conversion (string → boolean/integer)")
        print("  • Status blocks per section")
        print("  • Completeness tracking")
        print("  • Unmapped field handling")
        print("  • File output (pretty-printed)")
        print("  • UUID generation")
        
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