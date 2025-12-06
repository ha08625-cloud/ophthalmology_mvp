"""
State Manager - Core module for tracking consultation state

Responsibilities:
- Store structured data extracted from patient responses
- Store dialogue history (question-response pairs)
- Track which questions have been answered
- Provide exports for JSON Formatter and Summary Generator

Design principles:
- Fail fast: Raise exceptions for invalid inputs
- Simple overwrite: Last value wins for duplicate fields
- In-memory only: No persistence between sessions
"""


class StateManager:
    """Manages consultation state across dialogue turns"""
    
    def __init__(self):
        """Initialize empty state"""
        self.structured_data = {}
        self.dialogue_history = []
        self.questions_answered = set()
    
    def update(self, question_id, question_text, patient_response, extracted_fields):
        """
        Update state after each dialogue turn
        
        Args:
            question_id (str): Unique identifier for the question
            question_text (str): The question that was asked
            patient_response (str): Raw patient response
            extracted_fields (dict): Structured data extracted from response
            
        Raises:
            ValueError: If any required parameter is invalid
            TypeError: If extracted_fields is not a dict
        """
        # Fail fast validation
        if not question_id or not isinstance(question_id, str):
            raise ValueError(f"Invalid question_id: {question_id}")
        
        if not question_text or not isinstance(question_text, str):
            raise ValueError(f"Invalid question_text: {question_text}")
        
        if patient_response is None or not isinstance(patient_response, str):
            raise ValueError(f"Invalid patient_response: {patient_response}")
        
        if extracted_fields is None:
            raise TypeError("extracted_fields cannot be None (use empty dict if no data extracted)")
        
        if not isinstance(extracted_fields, dict):
            raise TypeError(f"extracted_fields must be dict, got {type(extracted_fields)}")
        
        # Update structured data (last value wins)
        self.structured_data.update(extracted_fields)
        
        # Record dialogue turn
        self.dialogue_history.append({
            'question_id': question_id,
            'question': question_text,
            'response': patient_response,
            'extracted': extracted_fields
        })
        
        # Mark question as answered
        self.questions_answered.add(question_id)
    
    def export_for_json(self):
        """
        Export structured data for JSON Formatter
        
        Returns:
            dict: Copy of structured data (modifications won't affect state)
        """
        return self.structured_data.copy()
    
    def export_for_summary(self, include_structured=True):
        """
        Export data for Summary Generator
        
        Args:
            include_structured (bool): If True, includes validated structured data
                                      If False, dialogue history only
        
        Returns:
            dict: Contains 'dialogue' and optionally 'structured' keys
        """
        export = {
            'dialogue': self.dialogue_history.copy()
        }
        
        if include_structured:
            export['structured'] = self.structured_data.copy()
        
        return export
    
    def get_answered_questions(self):
        """
        Get set of answered question IDs
        
        Returns:
            set: Question IDs that have been answered
        """
        return self.questions_answered.copy()
    
    def has_field(self, field_name):
        """
        Check if a structured field has been collected
        
        Args:
            field_name (str): Field name to check
            
        Returns:
            bool: True if field exists in structured_data
        """
        return field_name in self.structured_data
    
    def get_field(self, field_name, default=None):
        """
        Get value of a structured field
        
        Args:
            field_name (str): Field name to retrieve
            default: Value to return if field doesn't exist
            
        Returns:
            Field value or default
        """
        return self.structured_data.get(field_name, default)
    
    def get_dialogue_length(self):
        """
        Get number of dialogue turns
        
        Returns:
            int: Number of turns in conversation
        """
        return len(self.dialogue_history)
    
    def reset(self):
        """
        Clear all state (useful for starting new consultation)
        
        Warning: This erases all data. Use with caution.
        """
        self.structured_data.clear()
        self.dialogue_history.clear()
        self.questions_answered.clear()
