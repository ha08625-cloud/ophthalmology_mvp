"""
Flask Web Application for Ophthalmology Consultation System

Command-based architecture - Transport layer only.
No business logic. No state inspection. Commands only.
"""

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import logging
import os

from backend.core.state_manager_v2 import StateManagerV2
from backend.core.question_selector_v2 import QuestionSelectorV2
from backend.core.response_parser_v2 import ResponseParserV2
from backend.core.json_formatter_v2 import JSONFormatterV2
from backend.core.summary_generator_v2 import SummaryGeneratorV2
from backend.core.dialogue_manager_v2 import DialogueManagerV2
from backend.utils.hf_client_v2 import HuggingFaceClient

from backend.commands import StartConsultation, UserTurn, FinalizeConsultation
from backend.results import TurnResult, FinalReport, IllegalCommand
from backend.persistence import ConsultationPersistence

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Global persistence layer
persistence = ConsultationPersistence()

# Global DM instance (cached configs, ephemeral per turn)
dialogue_manager = None


def initialize_dialogue_manager():
    """
    Initialize DM once at startup (expensive).
    
    Loads HF model and creates stateless DialogueManager instance.
    """
    global dialogue_manager
    
    logger.info("Initializing DialogueManager (loading models...)")
    
    # Load HF model (expensive - once only)
    hf_client = HuggingFaceClient(
        model_name="mistralai/Mistral-7B-Instruct-v0.2",
        load_in_4bit=True
    )
    
    # Initialize stateless modules
    selector = QuestionSelectorV2("data/ruleset_v2.json")
    parser = ResponseParserV2(hf_client)
    formatter = JSONFormatterV2()
    generator = SummaryGeneratorV2(hf_client)
    
    # Create DM (stateless - state comes from commands)
    dialogue_manager = DialogueManagerV2(
        state_manager_class=StateManagerV2,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator
    )
    
    logger.info("DialogueManager initialized successfully")


# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    """
    Landing page - start new consultation.
    
    Clears any existing session.
    """
    session.clear()
    return render_template('index.html')


@app.route('/start', methods=['POST'])
def start_consultation():
    """
    Start new consultation.
    
    Issues StartConsultation command.
    Saves turn-0 to disk.
    Stores result in session for display.
    Redirects to /consult.
    """
    # Issue command
    command = StartConsultation()
    result = dialogue_manager.handle(command)
    
    # Should always succeed
    if isinstance(result, IllegalCommand):
        logger.error(f"StartConsultation failed: {result.reason}")
        return jsonify({'error': result.reason}), 400
    
    # Extract consultation_id from metadata
    consultation_id = result.turn_metadata['consultation_id']
    
    # Save initial state to disk
    try:
        persistence.save_turn(consultation_id, result.state)
    except Exception as e:
        logger.error(f"Failed to save initial turn: {e}")
        return jsonify({'error': f'Persistence error: {str(e)}'}), 500
    
    # Store consultation_id in session (only this!)
    session['consultation_id'] = consultation_id
    
    # Store last result in session for display (acceptable for prototype)
    # Alternative: also persist TurnResult to disk
    session['last_result'] = {
        'system_output': result.system_output,
        'debug': result.debug,
        'turn_metadata': result.turn_metadata,
        'consultation_complete': result.consultation_complete
    }
    
    logger.info(f"Started consultation {consultation_id}")
    
    # Redirect to consultation page
    return redirect(url_for('consult'))


@app.route('/consult')
def consult():
    """
    Main consultation interface.
    
    Displays last question + debug panel.
    Loads state from disk, display info from session.
    """
    consultation_id = session.get('consultation_id')
    
    if not consultation_id:
        # No active consultation
        return redirect(url_for('index'))
    
    # Get last result from session
    last_result = session.get('last_result')
    
    if not last_result:
        # Session lost (Flask restart) - need to reload
        # For prototype: redirect to home
        logger.warning(f"Session lost for consultation {consultation_id}")
        session.clear()
        return redirect(url_for('index'))
    
    # Render consultation page
    return render_template(
        'consult.html',
        consultation_id=consultation_id,
        turn_count=last_result['turn_metadata']['turn_count'],
        system_output=last_result['system_output'],
        debug=last_result['debug'],
        turn_metadata=last_result['turn_metadata'],
        consultation_complete=last_result['consultation_complete']
    )


@app.route('/turn', methods=['POST'])
def submit_turn():
    """
    Process user input turn.
    
    Loads state from disk, issues UserTurn command, saves result.
    Returns JSON with system_output + debug.
    """
    consultation_id = session.get('consultation_id')
    
    if not consultation_id:
        return jsonify({'error': 'No active consultation'}), 400
    
    # Get user input
    user_input = request.json.get('input', '').strip()
    
    if not user_input:
        return jsonify({'error': 'Empty input'}), 400
    
    # Load latest state from disk
    state = persistence.load_latest_turn(consultation_id)
    
    if state is None:
        return jsonify({'error': 'Consultation not found on disk'}), 404
    
    # Issue command
    command = UserTurn(user_input=user_input, state=state)
    result = dialogue_manager.handle(command)

# TEMPORARY DEBUG
    logger.info(f"DEBUG: result.debug keys: {result.debug.keys()}")
    if 'state_view' in result.debug:
        logger.info(f"DEBUG: state_view episodes: {len(result.debug['state_view'].get('episodes', []))}")
        # ADD THIS:
        for i, ep in enumerate(result.debug['state_view'].get('episodes', [])):
            logger.info(f"DEBUG: Episode {i+1} has {len(ep.get('fields', []))} fields: {ep.get('fields', [])}")
    else:
        logger.error("DEBUG: state_view NOT in result.debug!")
    
    if isinstance(result, IllegalCommand):
        return jsonify({'error': result.reason}), 400
    
    # Save new state to disk
    try:
        persistence.save_turn(consultation_id, result.state)
    except FileExistsError as e:
        # Double-submit detected
        logger.error(f"Double-submit detected: {e}")
        return jsonify({'error': 'Duplicate turn submission'}), 409
    except Exception as e:
        logger.error(f"Failed to save turn: {e}")
        return jsonify({'error': f'Persistence error: {str(e)}'}), 500
    
    # Update session with new result
    session['last_result'] = {
        'system_output': result.system_output,
        'debug': result.debug,
        'turn_metadata': result.turn_metadata,
        'consultation_complete': result.consultation_complete
    }
    
    # Return result
    return jsonify({
        'system_output': result.system_output,
        'debug': result.debug,
        'turn_metadata': result.turn_metadata,
        'consultation_complete': result.consultation_complete
    })


@app.route('/finalize', methods=['POST'])
def finalize_consultation():
    """
    Generate final outputs.
    
    Only valid if consultation_complete=True.
    Issues FinalizeConsultation command.
    """
    consultation_id = session.get('consultation_id')
    
    if not consultation_id:
        return jsonify({'error': 'No active consultation'}), 400
    
    # Load latest state from disk
    state = persistence.load_latest_turn(consultation_id)
    
    if state is None:
        return jsonify({'error': 'Consultation not found on disk'}), 404
    
    # Issue command
    command = FinalizeConsultation(state=state)
    result = dialogue_manager.handle(command)
    
    if isinstance(result, IllegalCommand):
        return jsonify({'error': result.reason}), 400
    
    # Clear session
    session.clear()
    
    logger.info(f"Finalized consultation {consultation_id}")
    
    # Return file paths
    return jsonify({
        'json_filename': result.json_filename,
        'summary_filename': result.summary_filename,
        'consultation_id': result.consultation_id,
        'total_episodes': result.total_episodes
    })


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    # Ensure output directory exists
    os.makedirs("outputs/consultations", exist_ok=True)
    
    # Start Flask server
    print("\n" + "="*60)
    print("OPHTHALMOLOGY CONSULTATION SYSTEM - WEB INTERFACE")
    print("="*60)
    print("\nServer starting...")
    print("Open your browser and go to: http://localhost:5000")
    print("\nPress Ctrl+C to stop the server")
    print("="*60 + "\n")
    
    # Initialize DialogueManager (expensive - loads model)
    initialize_dialogue_manager()
    
    app.run(debug=True, host='0.0.0.0', port=5000)