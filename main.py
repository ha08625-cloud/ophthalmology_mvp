"""
Console Test Harness for DialogueManagerV2 (Functional Core)

Simple console loop to test handle_turn() before adding Flask complexity.
"""

import logging
import sys

# Flat imports for server testing
from backend.core.state_manager_v2 import StateManagerV2
from backend.core.question_selector_v2 import QuestionSelectorV2
from backend.core.response_parser_v2 import ResponseParserV2
from backend.core.json_formatter_v2 import JSONFormatterV2
from backend.core.summary_generator_v2 import SummaryGeneratorV2
from backend.core.dialogue_manager_v2 import DialogueManagerV2
from backend.utils.hf_client_v2 import HuggingFaceClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_separator(char="=", length=60):
    """Print a separator line"""
    print(char * length)


def print_debug_info(turn_result):
    """Print debug information from TurnResult"""
    print("\n" + "-" * 60)
    print("DEBUG INFO:")
    print("-" * 60)
    
    debug = turn_result.debug
    
    # Parser output
    if 'parser_output' in debug:
        parser = debug['parser_output']
        print(f"Parser outcome: {parser.get('outcome', 'N/A')}")
        print(f"Fields extracted: {parser.get('fields', {})}")
        
        if parser.get('parse_metadata', {}).get('unexpected_fields'):
            print(f"Unexpected fields: {parser['parse_metadata']['unexpected_fields']}")
        
        if parser.get('parse_metadata', {}).get('validation_warnings'):
            print(f"Validation warnings: {parser['parse_metadata']['validation_warnings']}")
        
        if parser.get('parse_metadata', {}).get('normalization_applied'):
            print(f"Normalization applied: {parser['parse_metadata']['normalization_applied']}")
    
    # Other debug info
    if 'episode_complete' in debug:
        print(f"Episode complete: {debug['episode_complete']}")
    
    if 'new_episode' in debug:
        print(f"New episode created: {debug['new_episode']}")
    
    if 'error' in debug:
        print(f"ERROR: {debug['error']}")
    
    print("-" * 60)


def main():
    """Run console test"""
    print_separator()
    print("DIALOGUE MANAGER V2 - CONSOLE TEST")
    print_separator()
    print("\nInitializing modules (this may take 30 seconds)...")
    
    try:
        # Initialize HuggingFace client (expensive - only once)
        hf_client = HuggingFaceClient(
            model_name="mistralai/Mistral-7B-Instruct-v0.2",
            load_in_4bit=True
        )
        
        # Initialize stateless modules (cached in DM)
        selector = QuestionSelectorV2("data/ruleset_v2.json")
        parser = ResponseParserV2(hf_client)
        formatter = JSONFormatterV2()
        generator = SummaryGeneratorV2(hf_client)
        
        # Create DialogueManager (ephemeral, no state)
        dm = DialogueManagerV2(
            state_manager_class=StateManagerV2,
            question_selector=selector,
            response_parser=parser,
            json_formatter=formatter,
            summary_generator=generator
        )
        
        print("\nModules initialized successfully!")
        
    except Exception as e:
        print(f"\nFailed to initialize: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Consultation loop
    print_separator()
    print("STARTING CONSULTATION")
    print_separator()
    print("Type 'quit', 'exit', or 'stop' to end early\n")
    
    # State is external - we hold it in this loop
    state_snapshot = None
    question_count = 0
    
    while True:
        try:
            # First turn gets no user input (just returns first question)
            if state_snapshot is None:
                user_input = ""  # Empty for initialization
                print("Initializing consultation...")
            else:
                # Get user input
                user_input = input("> ").strip()
                
                if not user_input:
                    print("Please enter a response.\n")
                    continue
            
            # Process turn through DialogueManager
            turn_result = dm.handle_turn(
                user_input=user_input,
                state_snapshot=state_snapshot
            )
            
            # Update state for next turn
            state_snapshot = turn_result.state_snapshot
            
            # Display system output
            print(f"\nSystem: {turn_result.system_output}\n")
            
            # Display turn metadata
            metadata = turn_result.turn_metadata
            print(f"[Turn {metadata['turn_count']}, Episode {metadata['current_episode_id']}]")
            
            # Display debug info (parser output)
            if turn_result.debug and turn_result.debug.get('parser_output'):
                print_debug_info(turn_result)
            
            question_count += 1
            
            # Check if consultation complete
            if turn_result.consultation_complete:
                print_separator()
                print("CONSULTATION COMPLETE")
                print_separator()
                
                # Generate outputs
                print("\nGenerating final outputs...")
                outputs = dm.generate_outputs(state_snapshot)
                
                print(f"\nOutputs generated:")
                print(f"  - JSON: {outputs['json_filename']}")
                print(f"  - Summary: {outputs['summary_filename']}")
                print(f"  - Consultation ID: {outputs['consultation_id']}")
                print(f"  - Total episodes: {outputs['total_episodes']}")
                print(f"  - Questions asked: {question_count}")
                
                break
                
        except KeyboardInterrupt:
            print("\n\nConsultation interrupted by user (Ctrl+C)")
            break
            
        except Exception as e:
            print(f"\nERROR: {e}")
            import traceback
            traceback.print_exc()
            
            # Ask if user wants to continue
            try:
                cont = input("\nContinue consultation? (y/n): ").strip().lower()
                if cont != 'y':
                    break
            except KeyboardInterrupt:
                break
    
    print_separator()
    print("Console test complete")
    print_separator()
    return 0


if __name__ == '__main__':
    sys.exit(main())