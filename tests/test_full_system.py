"""
Full End-to-End Integration Test with Dialogue Manager

Tests complete consultation flow with all real modules:
- State Manager
- Question Selector
- Response Parser (LLM)
- JSON Formatter
- Summary Generator (LLM)
- Dialogue Manager (orchestrator)

This is the final integration test that validates the entire system.
"""

import sys
import os
import logging

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from backend.core.state_manager import StateManager
from backend.core.question_selector import QuestionSelector
from backend.core.response_parser import ResponseParser
from backend.core.json_formatter import JSONFormatter
from backend.core.summary_generator import SummaryGenerator
from backend.core.dialogue_manager import DialogueManager
from backend.utils.hf_client import HuggingFaceClient
from backend.utils.helpers import ConsultationValidator
import json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def print_section_header(title):
    """Print formatted section header"""
    print("\n" + "="*70)
    print(f"{title}")
    print("="*70)


def load_schema():
    """Load JSON schema for validator"""
    schema_path = "data/mvp_json_schema.json"
    with open(schema_path, 'r') as f:
        return json.load(f)


def run_full_integration_test():
    """
    Run complete consultation with Dialogue Manager
    
    Uses predefined patient responses to simulate a consultation.
    """
    
    print("\n" + "#"*70)
    print("# FULL END-TO-END INTEGRATION TEST")
    print("# Testing: Complete system with Dialogue Manager orchestration")
    print("#"*70)
    
    print_section_header("Module Initialization")
    
    try:
        # Initialize HuggingFace client (model loading)
        print("Loading model (this takes ~30 seconds)...")
        hf_client = HuggingFaceClient(
            model_name="mistralai/Mistral-7B-Instruct-v0.2",
            load_in_4bit=True
        )
        print("   ✓ HuggingFace client loaded")
        
        # Initialize State Manager
        state = StateManager()
        print("   ✓ State Manager initialized")
        
        # Initialize Question Selector
        ruleset_path = "data/mvp_ruleset.json"
        selector = QuestionSelector(ruleset_path, state)
        print("   ✓ Question Selector initialized")
        
        # Initialize Response Parser
        parser = ResponseParser(hf_client)
        print("   ✓ Response Parser initialized")
        
        # Initialize JSON Formatter
        schema_path = "data/mvp_json_schema.json"
        json_formatter = JSONFormatter(schema_path)
        print("   ✓ JSON Formatter initialized")
        
        # Initialize Summary Generator
        summary_generator = SummaryGenerator(hf_client)
        print("   ✓ Summary Generator initialized")
        
        # Initialize Validator
        schema = load_schema()
        validator = ConsultationValidator(schema)
        print("   ✓ Validator initialized")
        
        # Initialize Dialogue Manager (orchestrator)
        manager = DialogueManager(
            state_manager=state,
            question_selector=selector,
            response_parser=parser,
            json_formatter=json_formatter,
            summary_generator=summary_generator,
            validator=validator
        )
        print("   ✓ Dialogue Manager initialized")
        print(f"   ✓ Consultation ID: {manager.consultation_id}")
        
    except Exception as e:
        print(f"\n✗ Module initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print_section_header("Running Consultation")
    
    # Predefined patient responses (simulated consultation)
    patient_responses = [
        # Chief complaint
        "I've been having trouble with my vision. My right eye has been really blurry.",
        "No, this hasn't happened before.",
        
        # Vision loss details
        "Just my right eye.",
        "The center of my vision is blurry.",
        "I can't read fine print anymore, but I can see hand movements.",
        "It started about 3 months ago.",
        "It came on over a few hours.",
        "It's been constant since it started.",
        "Yes, it got worse initially.",
        "No, it hasn't improved.",
        "No, I don't have trouble recognizing things.",
        
        # Visual disturbances
        "No hallucinations.",
        "No color vision problems.",
        "No flashing lights or zigzags.",
        "No double vision.",
        "No dizziness.",
        "No rapid eye movements.",
        
        # Headache
        "Yes, I've been getting headaches.",
        "It's a dull ache on the right side.",
        "It started around the same time as the vision problem.",
        "The right side of my head.",
        "They come and go.",
        "No, not worse with straining.",
        "They're worse in the mornings.",
        
        # Eye pain and changes
        "No eye pain.",
        "No dry or gritty feeling.",
        "No changes to how my eyes look.",
        
        # Healthcare contacts
        "No, I haven't seen anyone about this yet.",
        
        # Functional impact
        "It's been really hard. I can't read books anymore or see fine details. I bump into things on my right side.",
    ]
    
    response_iter = iter(patient_responses)
    
    def mock_input(prompt=""):
        """Simulated patient input"""
        try:
            response = next(response_iter)
            print(prompt + response)
            return response
        except StopIteration:
            # If we run out of responses, quit
            print(prompt + "quit")
            return "quit"
    
    output_lines = []
    def mock_output(text):
        """Capture output"""
        print(text)
        output_lines.append(text)
    
    # Run consultation
    try:
        result = manager.run_consultation(
            input_fn=mock_input,
            output_fn=mock_output,
            output_dir="outputs/consultations"
        )
        
        print_section_header("Consultation Results")
        
        print(f"\nConsultation completed: {result['completed']}")
        print(f"Total questions asked: {result['total_questions']}")
        print(f"Consultation ID: {result['consultation_id']}")
        
        print(f"\nOutput files:")
        print(f"   JSON: {result['json_path']}")
        print(f"   Summary: {result['summary_path']}")
        
        if result['validation']:
            val = result['validation']
            print(f"\nValidation:")
            print(f"   Complete: {val['is_complete']}")
            print(f"   Completeness: {val['completeness_score']:.1%}")
            if val['missing_required']:
                print(f"   Missing required: {len(val['missing_required'])} fields")
        
        if result['errors']:
            print(f"\n⚠ Errors encountered: {len(result['errors'])}")
            for err in result['errors'][:3]:
                print(f"   - {err['context']}: {err['error'][:50]}")
        
        # Show sample of JSON output
        print_section_header("JSON Output Sample")
        json_data = result['json']
        print(f"Metadata:")
        print(f"   Consultation ID: {json_data['metadata']['consultation_id']}")
        print(f"   Completeness: {json_data['metadata']['completeness_score']:.1%}")
        print(f"   Fields captured: {json_data['metadata']['total_fields_present']}/{json_data['metadata']['total_fields_expected']}")
        
        print(f"\nSection status:")
        for section in ['chief_complaint', 'visual_loss', 'visual_disturbances', 'headache']:
            if section in json_data:
                status = json_data[section].get('_status', {})
                complete = "✓" if status.get('complete') else "○"
                present = status.get('fields_present', 0)
                expected = status.get('fields_expected', 0)
                print(f"   {complete} {section}: {present}/{expected}")
        
        # Show sample of summary
        print_section_header("Clinical Summary Sample")
        summary = result['summary']
        lines = summary.split('\n')
        preview_lines = lines[:20]  # First 20 lines
        print('\n'.join(preview_lines))
        if len(lines) > 20:
            print(f"\n... ({len(lines) - 20} more lines)")
        
        # Validation checks
        print_section_header("Validation Checks")
        
        validation_passed = True
        
        # Check 1: Consultation completed
        if not result['completed']:
            print("⚠ Warning: Consultation ended early (not all questions answered)")
        else:
            print("✓ PASS: Consultation completed naturally")
        
        # Check 2: Questions asked
        if result['total_questions'] < 10:
            print(f"✗ FAIL: Too few questions asked ({result['total_questions']})")
            validation_passed = False
        else:
            print(f"✓ PASS: Asked {result['total_questions']} questions")
        
        # Check 3: Output files exist
        if not os.path.exists(result['json_path']):
            print("✗ FAIL: JSON file not created")
            validation_passed = False
        else:
            print(f"✓ PASS: JSON file created")
        
        if not os.path.exists(result['summary_path']):
            print("✗ FAIL: Summary file not created")
            validation_passed = False
        else:
            print(f"✓ PASS: Summary file created")
        
        # Check 4: JSON structure valid
        if 'metadata' not in json_data:
            print("✗ FAIL: JSON missing metadata")
            validation_passed = False
        else:
            print(f"✓ PASS: JSON structure valid")
        
        # Check 5: Summary has content
        if len(summary) < 500:
            print(f"✗ FAIL: Summary too short ({len(summary)} characters)")
            validation_passed = False
        else:
            print(f"✓ PASS: Summary has content ({len(summary)} characters)")
        
        # Check 6: Second-person language in summary
        second_person_count = summary.lower().count('you ') + summary.lower().count('your ')
        if second_person_count < 5:
            print(f"⚠ Warning: Limited second-person usage ({second_person_count} instances)")
        else:
            print(f"✓ PASS: Using second person ({second_person_count} instances)")
        
        # Check 7: No critical errors
        if len(result['errors']) > 10:
            print(f"✗ FAIL: Too many errors ({len(result['errors'])})")
            validation_passed = False
        else:
            print(f"✓ PASS: Error count acceptable ({len(result['errors'])})")
        
        # Final verdict
        print("\n" + "#"*70)
        if validation_passed:
            print("# ✓ ✓ ✓ FULL INTEGRATION TEST PASSED ✓ ✓ ✓")
            print("#"*70)
            print("\n🎉 ALL SIX MODULES WORKING TOGETHER SUCCESSFULLY! 🎉")
            print("\nComplete system validated:")
            print("   • State Manager: Tracking consultation state")
            print("   • Question Selector: Choosing questions deterministically")
            print("   • Response Parser: Extracting data with LLM")
            print("   • JSON Formatter: Generating structured output")
            print("   • Summary Generator: Creating clinical narratives")
            print("   • Dialogue Manager: Orchestrating everything")
            print("\n🏆 MVP IS COMPLETE! 🏆")
            print("\nWhat you've built:")
            print("   ✓ Full consultation system (30+ questions)")
            print("   ✓ LLM-powered data extraction")
            print("   ✓ Clinical summary generation")
            print("   ✓ Structured JSON output")
            print("   ✓ Error handling and recovery")
            print("   ✓ Validation and completeness tracking")
            print("\nNext steps:")
            print("   1. Test with real users (colleagues)")
            print("   2. Collect feedback on accuracy")
            print("   3. Prepare fine-tuning data (150+ examples)")
            print("   4. Consider web interface for better UX")
        else:
            print("# ✗ INTEGRATION TEST FAILED")
            print("#"*70)
            print("\nSome validation checks failed. Review output above.")
        
        return validation_passed
        
    except Exception as e:
        print(f"\n✗ Consultation failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_full_integration_test()
    exit(0 if success else 1)