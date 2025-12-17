"""
Flask Web Application for Ophthalmology Consultation System

Simple web interface to replace console-based interaction.
"""

from flask import Flask, render_template, request, jsonify, send_file
import logging
import os
import json
from datetime import datetime

from backend.core.state_manager import StateManager
from backend.core.question_selector import QuestionSelector
from backend.core.response_parser import ResponseParser
from ophthalmology_mvp.archive.json_formatter import JSONFormatter
from backend.core.summary_generator import SummaryGenerator
from backend.core.dialogue_manager import DialogueManager
from backend.utils.hf_client import HuggingFaceClient
from backend.utils.helpers import ConsultationValidator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'ophthalmology-mvp-secret-key'

# Global state for current consultation
current_consultation = {
    'manager': None,
    'state': None,
    'selector': None,
    'question_buffer': None,  # Stores current question
    'is_active': False,
    'result': None
}

# Initialize models once at startup (expensive operation)
hf_client = None


def initialize_models():
    """Initialize HuggingFace model (called once at startup)"""
    global hf_client
    
    if hf_client is None:
        logger.info("Initializing HuggingFace model (this takes ~30 seconds)...")
        hf_client = HuggingFaceClient(
            model_name="mistralai/Mistral-7B-Instruct-v0.2",
            load_in_4bit=True
        )
        logger.info("Model loaded successfully")


def create_new_consultation():
    """Create new consultation session"""
    global current_consultation
    
    # Initialize all modules
    state = StateManager()
    selector = QuestionSelector("data/mvp_ruleset.json", state)
    parser = ResponseParser(hf_client)
    formatter = JSONFormatter("data/mvp_json_schema.json")
    generator = SummaryGenerator(hf_client)
    
    # Load schema for validator
    with open("data/mvp_json_schema.json", 'r') as f:
        schema = json.load(f)
    validator = ConsultationValidator(schema)
    
    # Create dialogue manager
    manager = DialogueManager(
        state_manager=state,
        question_selector=selector,
        response_parser=parser,
        json_formatter=formatter,
        summary_generator=generator,
        validator=validator
    )
    
    current_consultation = {
        'manager': manager,
        'state': state,
        'selector': selector,
        'question_buffer': None,
        'is_active': True,
        'result': None
    }
    
    logger.info(f"New consultation created: {manager.consultation_id}")
    return manager.consultation_id


@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')


@app.route('/api/start', methods=['POST'])
def start_consultation():
    """Start new consultation"""
    try:
        consultation_id = create_new_consultation()
        
        # Get first question
        question_dict = current_consultation['selector'].get_next_question()
        current_consultation['question_buffer'] = question_dict
        
        return jsonify({
            'success': True,
            'consultation_id': consultation_id,
            'question': question_dict['question'] if question_dict else None
        })
        
    except Exception as e:
        logger.error(f"Error starting consultation: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/answer', methods=['POST'])
def submit_answer():
    """Submit patient answer and get next question"""
    try:
        data = request.json
        patient_response = data.get('answer', '').strip()
        
        if not current_consultation['is_active']:
            return jsonify({
                'success': False,
                'error': 'No active consultation'
            }), 400
        
        # Check for exit command
        if patient_response.lower() in ['quit', 'exit', 'stop']:
            return jsonify({
                'success': True,
                'finished': True,
                'message': 'Consultation ended early by user'
            })
        
        manager = current_consultation['manager']
        state = current_consultation['state']
        selector = current_consultation['selector']
        question_dict = current_consultation['question_buffer']
        
        if question_dict is None:
            return jsonify({
                'success': False,
                'error': 'No question to answer'
            }), 400
        
        # Parse response
        parser = ResponseParser(hf_client)
        extracted = parser.parse(
            question=question_dict,
            patient_response=patient_response
        )
        
        # Update state
        state.update(
            question_id=question_dict['id'],
            question_text=question_dict['question'],
            patient_response=patient_response,
            extracted_fields=extracted
        )
        
        # Get next question
        next_question = selector.get_next_question()
        current_consultation['question_buffer'] = next_question
        
        if next_question is None:
            # Consultation complete
            return jsonify({
                'success': True,
                'finished': True,
                'message': 'All questions answered'
            })
        
        return jsonify({
            'success': True,
            'finished': False,
            'question': next_question['question']
        })
        
    except Exception as e:
        logger.error(f"Error processing answer: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/finalize', methods=['POST'])
def finalize_consultation():
    """Generate final outputs (JSON + Summary)"""
    try:
        if not current_consultation['is_active']:
            return jsonify({
                'success': False,
                'error': 'No active consultation'
            }), 400
        
        manager = current_consultation['manager']
        state = current_consultation['state']
        
        # Generate JSON
        json_formatter = JSONFormatter("data/mvp_json_schema.json")
        state_data = state.export_for_json()
        json_data = json_formatter.to_dict(state_data, consultation_id=manager.consultation_id)
        
        # Save JSON
        from backend.utils.helpers import generate_consultation_filename
        json_filename = generate_consultation_filename(prefix="consultation", extension="json")
        json_path = os.path.join("outputs/consultations", json_filename)
        json_formatter.save(json_data, json_path)
        
        # Generate summary
        summary_generator = SummaryGenerator(hf_client)
        summary_data = state.export_for_summary()
        summary_text = summary_generator.generate(
            dialogue_history=summary_data['dialogue'],
            structured_data=summary_data['structured'],
            temperature=0.1,
            target_length="medium"
        )
        
        # Save summary
        summary_filename = generate_consultation_filename(prefix="summary", extension="txt")
        summary_path = os.path.join("outputs/consultations", summary_filename)
        summary_generator.save_summary(summary_text, summary_path)
        
        # Mark consultation complete
        current_consultation['is_active'] = False
        current_consultation['result'] = {
            'json_path': json_path,
            'summary_path': summary_path,
            'completeness': json_data['metadata']['completeness_score']
        }
        
        logger.info(f"Consultation finalized: {manager.consultation_id}")
        
        return jsonify({
            'success': True,
            'json_filename': json_filename,
            'summary_filename': summary_filename,
            'completeness': json_data['metadata']['completeness_score'],
            'summary_preview': summary_text[:500] + "..." if len(summary_text) > 500 else summary_text
        })
        
    except Exception as e:
        logger.error(f"Error finalizing consultation: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/download/<file_type>/<filename>')
def download_file(file_type, filename):
    """Download output file"""
    try:
        file_path = os.path.join("outputs/consultations", filename)
        
        if not os.path.exists(file_path):
            return jsonify({
                'success': False,
                'error': 'File not found'
            }), 404
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


if __name__ == '__main__':
    # Initialize models before starting server
    initialize_models()
    
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
    
    app.run(debug=True, host='0.0.0.0', port=5000)