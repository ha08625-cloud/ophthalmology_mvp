"""
Integration Test - State Manager + Question Selector + Response Parser

This test simulates a real consultation with:
- Question Selector choosing questions
- Simulated patient responses
- Response Parser extracting data with real LLM calls
- State Manager tracking everything
- Medium length conversation (~15 questions)

Expected duration: 3-5 minutes (LLM calls are slow)

Usage:
    cd ~/ophthalmology_mvp
    python3 tests/test_integration.py
"""

import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

import logging
from backend.core.state_manager import StateManager
from backend.core.question_selector import QuestionSelector
from backend.core.response_parser import ResponseParser
from backend.core.json_formatter import JSONFormatter
from backend.core.summary_generator import SummaryGenerator
from backend.utils.hf_client import HuggingFaceClient

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Simulated patient responses
PATIENT_RESPONSES = {
    "chief_1": "I've been having trouble with my vision. My right eye has been really blurry.",
    "chief_2": "No, this hasn't happened before.",
    "vl_1": "It's been blurry and I can't see clearly out of it.",
    "vl_2": "Just my right eye.",
    "vl_5": "It's more in the center of my vision.",
    "vl_6": "I can see something but it's very blurred.",
    "vl_7": "I can't read fine print anymore, but I can see hand movements.",
    "vl_8": "It started about 3 months ago.",
    "vl_9": "It came on pretty suddenly, over a few hours.",
    "vl_10": "It's been constant since it started.",
    "vl_13": "Yes, it got worse over the first day or so.",
    "vl_15": "No, it hasn't gotten any better.",
    "vl_18": "No, I can recognize things fine.",
    "vd_1": "No hallucinations.",
    "vd_3": "No problems with colors.",
    "vd_8": "No flashing lights or zigzags.",
    "vd_15": "No double vision.",
    "vd_19": "No dizziness.",
    "vd_20": "No, my eyes aren't moving around.",
    "h_1": "Yes, I have been getting headaches.",
    "h_2": "It's a dull ache.",
    "h_3": "The headaches started around the same time as the vision problem.",
    "h_4": "It's mostly on the right side of my head.",
    "h_5": "It comes and goes.",
    "h_6": "No, it doesn't get worse with straining.",
    "h_7": "It's worse in the mornings.",
    # Add more as needed - this covers chief_complaint, vision_loss start, visual_disturbances start, headache
}


def print_section_header(text):
    """Print a formatted section header"""
    print("\n" + "="*70)
    print(text)
    print("="*70)


def print_dialogue_turn(turn_number, question_id, question_text, response):
    """Print a formatted dialogue turn"""
    print(f"\n--- Turn {turn_number}: {question_id} ---")
    print(f"Agent: {question_text}")
    print(f"Patient: {response}")


def test_integration():
    """Run full integration test"""
    
    print_section_header("INTEGRATION TEST: Full Consultation Simulation")
    
    # Initialize components
    print("\n1. Initializing components...")
    
    try:
        # HuggingFace Client
        print("   Loading model (this takes ~30 seconds)...")
        hf_client = HuggingFaceClient(
            model_name="mistralai/Mistral-7B-Instruct-v0.2",
            load_in_4bit=True
        )
        print("   ✓ HuggingFace Client loaded")
        
        # State Manager
        state = StateManager()
        print("   ✓ State Manager initialized")
        
        # Question Selector
        ruleset_path = "data/mvp_ruleset.json"
        selector = QuestionSelector(ruleset_path, state)
        print("   ✓ Question Selector initialized")
        
        # Response Parser
        parser = ResponseParser(hf_client)
        print("   ✓ Response Parser initialized")
        
        # JSON Formatter
        schema_path = "data/mvp_json_schema.json"
        json_formatter = JSONFormatter(schema_path)
        print("   ✓ JSON Formatter initialized")
        
        # Summary Generator
        summary_generator = SummaryGenerator(hf_client)
        print("   ✓ Summary Generator initialized")
        
    except Exception as e:
        print(f"\n✗ FAILED during initialization: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Run consultation
    print_section_header("2. Running Consultation")
    
    turn_number = 0
    questions_asked = 0
    max_questions = 30  # Safety limit
    
    try:
        while questions_asked < max_questions:
            # Get next question
            question = selector.get_next_question()
            
            if question is None:
                print("\n✓ Consultation complete - no more questions")
                break
            
            turn_number += 1
            questions_asked += 1
            question_id = question['id']
            question_text = question['question']
            
            # Get simulated patient response
            if question_id in PATIENT_RESPONSES:
                patient_response = PATIENT_RESPONSES[question_id]
            else:
                # Default response for questions we didn't script
                patient_response = "No, I don't have that."
            
            print_dialogue_turn(turn_number, question_id, question_text, patient_response)
            
            # Extract data with LLM
            print("   Extracting data with LLM...", end=" ", flush=True)
            extracted = parser.parse(question, patient_response)
            
            # Remove _meta for cleaner display
            extracted_fields = {k: v for k, v in extracted.items() if k != '_meta'}
            
            # Check for extraction issues
            if extracted['_meta']['extraction_failed']:
                print("⚠ Extraction failed")
                extracted_fields = {}
            elif extracted['_meta']['unclear_response']:
                print("⚠ Unclear response")
                extracted_fields = {}
            else:
                print("✓")
            
            if extracted_fields:
                print(f"   Extracted: {extracted_fields}")
            
            # Update state
            state.update(
                question_id=question_id,
                question_text=question_text,
                patient_response=patient_response,
                extracted_fields=extracted_fields
            )
            
            # Show progress every 5 questions
            if turn_number % 5 == 0:
                progress = selector.get_progress_summary()
                print(f"\n   Progress: {progress['total_questions_answered']} questions answered")
                print(f"   Current section: {progress['current_section']}")
    
    except KeyboardInterrupt:
        print("\n\n⚠ Test interrupted by user")
    except Exception as e:
        print(f"\n\n✗ FAILED during conversation: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Display results
    print_section_header("3. Consultation Results")
    
    # State summary
    structured_data = state.export_for_json()
    print(f"\nStructured data collected: {len(structured_data)} fields")
    print("\nKey fields:")
    
    important_fields = [
        'presenting_complaint_description',
        'vl_laterality',
        'vl_onset',
        'vl_onset_speed',
        'vl_temporal_pattern',
        'vl_degree',
        'h_present'
    ]
    
    for field in important_fields:
        if field in structured_data:
            print(f"   {field}: {structured_data[field]}")
    
    # Progress summary
    print("\nProgress Summary:")
    progress = selector.get_progress_summary()
    print(f"   Total questions answered: {progress['total_questions_answered']}")
    print(f"   Core sections complete: {progress['core_sections_complete']}")
    
    print("\nSection completion:")
    for section_name, section_data in progress['section_progress'].items():
        status = "✓" if section_data['complete'] else "○"
        print(f"   {status} {section_name}: {section_data['answered']}/{section_data['total']}")
    
    if progress['triggered_blocks']:
        print(f"\nTriggered blocks: {progress['triggered_blocks']}")
    
    # Dialogue history
    dialogue_data = state.export_for_summary()
    print(f"\nDialogue history: {len(dialogue_data['dialogue'])} turns")
    
    # Show sample of dialogue
    print("\nSample dialogue (first 3 turns):")
    for i, turn in enumerate(dialogue_data['dialogue'][:3], 1):
        print(f"\n   Turn {i}:")
        print(f"      Q: {turn['question']}")
        print(f"      A: {turn['response']}")
        if turn['extracted']:
            print(f"      Extracted: {turn['extracted']}")
    
    # Generate JSON output
    print_section_header("JSON Output Generation")
    
    try:
        # Get state data
        json_state_data = state.export_for_json()
        
        # Generate output file path with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"outputs/consultations/consultation_{timestamp}.json"
        
        # Format and save
        print(f"Generating JSON output...")
        json_output = json_formatter.format(
            json_state_data,
            output_path=output_path
        )
        
        print(f"✓ JSON saved to: {output_path}")
        print(f"\nJSON Summary:")
        print(f"   Schema version: {json_output['metadata']['schema_version']}")
        print(f"   Consultation ID: {json_output['metadata']['consultation_id']}")
        print(f"   Completeness: {json_output['metadata']['completeness_score']:.1%}")
        print(f"   Fields present: {json_output['metadata']['total_fields_present']}/{json_output['metadata']['total_fields_expected']}")
        
        # Show section completeness
        print(f"\nSection completeness:")
        for section_name in list(json_output.keys())[:8]:  # Show first 8 sections
            if section_name == 'metadata':
                continue
            status = json_output[section_name]['_status']
            complete_marker = "✓" if status['complete'] else "○"
            print(f"   {complete_marker} {section_name}: {status['fields_present']}/{status['fields_expected']}")
        
        # Show warnings if any
        warnings = json_output['metadata'].get('warnings', [])
        if warnings:
            print(f"\nWarnings: {len(warnings)}")
            for warning in warnings[:5]:  # Show first 5
                print(f"   - {warning}")
        
    except Exception as e:
        print(f"✗ JSON generation failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Generate Clinical Summary
    print_section_header("Clinical Summary Generation")
    
    try:
        # Get dialogue and structured data
        summary_data = state.export_for_summary()
        
        print(f"Generating clinical summary...")
        print(f"   Input: {len(summary_data['dialogue'])} dialogue turns")
        print(f"   Input: {len(summary_data['structured'])} structured fields")
        
        # Generate summary
        clinical_summary = summary_generator.generate(
            dialogue_history=summary_data['dialogue'],
            structured_data=summary_data['structured'],
            temperature=0.1,
            target_length="medium"
        )
        
        print(f"✓ Summary generated: {len(clinical_summary)} characters")
        
        # Save to file
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        summary_path = f"outputs/consultations/summary_{timestamp}.txt"
        
        summary_generator.save_summary(clinical_summary, summary_path)
        print(f"✓ Summary saved to: {summary_path}")
        
        # Show preview
        print(f"\nSummary Preview (first 500 characters):")
        print("-" * 60)
        print(clinical_summary[:500] + "..." if len(clinical_summary) > 500 else clinical_summary)
        print("-" * 60)
        
        # Check for second-person usage
        second_person_count = clinical_summary.lower().count('you ') + clinical_summary.lower().count('your ')
        if second_person_count > 0:
            print(f"✓ Using second person: {second_person_count} instances of 'you/your'")
        else:
            print(f"⚠ Warning: No second-person language detected")
        
        # Check for section headers
        sections_found = []
        for section in ["OVERVIEW", "PRESENTING COMPLAINT", "VISION LOSS", "VISUAL DISTURBANCES"]:
            if section in clinical_summary.upper():
                sections_found.append(section)
        
        if sections_found:
            print(f"✓ Sections found: {', '.join(sections_found)}")
        else:
            print(f"⚠ Warning: No section headers detected")
        
    except Exception as e:
        print(f"✗ Summary generation failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Validation
    print_section_header("4. Validation")
    
    validation_passed = True
    
    # Check 1: State has data
    if len(structured_data) == 0:
        print("✗ FAIL: No structured data collected")
        validation_passed = False
    else:
        print(f"✓ PASS: Collected {len(structured_data)} fields")
    
    # Check 2: Dialogue recorded
    if len(dialogue_data['dialogue']) == 0:
        print("✗ FAIL: No dialogue history recorded")
        validation_passed = False
    else:
        print(f"✓ PASS: Recorded {len(dialogue_data['dialogue'])} dialogue turns")
    
    # Check 3: Key fields present
    if 'vl_laterality' not in structured_data:
        print("✗ FAIL: Critical field 'vl_laterality' not extracted")
        validation_passed = False
    else:
        print(f"✓ PASS: Critical field 'vl_laterality' = {structured_data['vl_laterality']}")
    
    # Check 4: Question selection working
    if progress['total_questions_answered'] < 5:
        print("✗ FAIL: Too few questions asked")
        validation_passed = False
    else:
        print(f"✓ PASS: Asked {progress['total_questions_answered']} questions")
    
    # Check 5: JSON output created
    if not os.path.exists(output_path):
        print("✗ FAIL: JSON output file not created")
        validation_passed = False
    else:
        print(f"✓ PASS: JSON output file created: {output_path}")
    
    # Check 6: Summary output created
    if not os.path.exists(summary_path):
        print("✗ FAIL: Summary output file not created")
        validation_passed = False
    else:
        print(f"✓ PASS: Summary output file created: {summary_path}")
    
    # Check 7: Summary has content
    if len(clinical_summary) < 200:
        print("✗ FAIL: Summary too short")
        validation_passed = False
    else:
        print(f"✓ PASS: Summary has substantial content ({len(clinical_summary)} characters)")
    
    # Final result
    print_section_header("FINAL RESULT")
    
    if validation_passed:
        print("\n✓ ✓ ✓ INTEGRATION TEST PASSED ✓ ✓ ✓")
        print("\nAll five modules working together successfully:")
        print("   • Question Selector: Choosing questions correctly")
        print("   • Response Parser: Extracting data with LLM")
        print("   • State Manager: Tracking state properly")
        print("   • JSON Formatter: Generating structured output")
        print("   • Summary Generator: Creating clinical narratives")
        print("\nOutput files created:")
        print(f"   • JSON: {output_path}")
        print(f"   • Summary: {summary_path}")
        print("\nNext steps:")
        print("   1. Build Dialogue Manager to orchestrate everything")
        print("   2. Create simple web interface")
        print("   3. Prepare fine-tuning data")
    else:
        print("\n✗ ✗ ✗ INTEGRATION TEST FAILED ✗ ✗ ✗")
        print("\nSome checks failed - review output above")
    
    return validation_passed


if __name__ == '__main__':
    print("\n" + "#"*70)
    print("# INTEGRATION TEST")
    print("# Testing: State Manager + Question Selector + Response Parser +")
    print("#          JSON Formatter + Summary Generator")
    print("#"*70)
    
    try:
        success = test_integration()
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)