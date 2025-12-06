"""
Response Parser - Extract structured data from patient responses

Responsibilities:
- Build extraction prompts from question context
- Call LLM to extract structured fields
- Parse and validate LLM output
- Map natural language to standardized values
- Handle unclear responses and extraction failures

Design principles:
- Early return for clearly unclear responses
- Fail gracefully (return empty dict, not crash)
- Simple flat output structure (compatible with State Manager)
- Let CUDA errors raise (don't hide critical failures)
"""

import json
import logging
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.utils.hf_client import HuggingFaceClient
from backend.utils.field_mappings import map_field_value, validate_against_schema

logger = logging.getLogger(__name__)

# Pure unclear response patterns (early return)
UNCLEAR_PATTERNS = [
    "i don't know",
    "i'm not sure",
    "not sure",
    "unclear",
    "i can't remember",
    "i don't remember",
    "maybe",
    "unsure",
]


class ResponseParser:
    """Extract structured medical data from patient responses"""
    
    def __init__(self, hf_client):
        """
        Initialize parser with HuggingFace client
        
        Args:
            hf_client (HuggingFaceClient): Initialized model client
        """
        if not isinstance(hf_client, HuggingFaceClient):
            raise TypeError("hf_client must be HuggingFaceClient instance")
        
        if not hf_client.is_loaded():
            raise RuntimeError("HuggingFace client model not loaded")
        
        self.hf_client = hf_client
        logger.info("Response Parser initialized")
    
    def parse(self, question, patient_response):
        """
        Extract structured fields from patient response
        
        Args:
            question (dict): Question dict from Question Selector
                Must contain: 'question', 'field', 'field_type'
                Optional: 'valid_values', 'definitions'
            patient_response (str): What patient said
            
        Returns:
            dict: Extracted fields with metadata
                Format: {
                    'field_name': 'value',
                    '_meta': {
                        'unclear_response': bool,
                        'extraction_failed': bool,
                        'raw_llm_output': str
                    }
                }
                
        Examples:
            >>> parse(
                    {'question': 'Which eye?', 'field': 'vl_laterality', 'field_type': 'categorical'},
                    'My right eye went blurry'
                )
            {'vl_laterality': 'monocular_right', '_meta': {...}}
            
            >>> parse(question, "I don't know")
            {'_meta': {'unclear_response': True, ...}}
        """
        # Validate inputs
        if not isinstance(question, dict):
            raise TypeError("question must be dict")
        if 'question' not in question or 'field' not in question:
            raise ValueError("question dict must contain 'question' and 'field' keys")
        if not isinstance(patient_response, str):
            raise TypeError("patient_response must be string")
        
        # Check for pure unclear responses (early return)
        if self._is_pure_unclear(patient_response):
            logger.info(f"Pure unclear response detected: '{patient_response}'")
            return {
                '_meta': {
                    'unclear_response': True,
                    'extraction_failed': False,
                    'raw_llm_output': None
                }
            }
        
        # Build extraction prompt
        prompt = self._build_prompt(question, patient_response)
        logger.debug(f"Built prompt for field '{question['field']}'")
        
        # Call LLM
        try:
            llm_output = self.hf_client.generate_json(
                prompt=prompt,
                max_tokens=256,
                temperature=0.0
            )
            logger.debug(f"LLM output: {llm_output[:200]}...")  # Log first 200 chars
            
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return {
                '_meta': {
                    'unclear_response': False,
                    'extraction_failed': True,
                    'raw_llm_output': None,
                    'error': str(e)
                }
            }
        
        # Parse JSON output
        try:
            parsed = json.loads(llm_output)
        except json.JSONDecodeError as e:
            logger.warning(f"LLM returned invalid JSON: {e}")
            logger.warning(f"Raw output: {llm_output}")
            return {
                '_meta': {
                    'unclear_response': False,
                    'extraction_failed': True,
                    'raw_llm_output': llm_output
                }
            }
        
        # Extract and standardize fields
        extracted_fields = self._process_extraction(
            parsed=parsed,
            question=question
        )
        
        # Add metadata
        extracted_fields['_meta'] = {
            'unclear_response': False,
            'extraction_failed': False,
            'raw_llm_output': llm_output
        }
        
        # Check if extraction is empty (might indicate unclear response)
        if len(extracted_fields) == 1:  # Only _meta present
            logger.info("Empty extraction - possible unclear response")
            extracted_fields['_meta']['unclear_response'] = True
        
        return extracted_fields
    
    def _is_pure_unclear(self, response):
        """
        Check if response is purely unclear (no extractable data)
        
        Args:
            response (str): Patient response
            
        Returns:
            bool: True if pure unclear pattern
        """
        normalized = response.lower().strip()
        
        # Check for exact matches
        if normalized in UNCLEAR_PATTERNS:
            return True
        
        # Check for very short unclear responses
        if len(normalized) < 20:
            for pattern in UNCLEAR_PATTERNS:
                if normalized == pattern or normalized.startswith(pattern):
                    return True
        
        return False
    
    def _build_prompt(self, question, patient_response):
        """
        Build extraction prompt for LLM
        
        Args:
            question (dict): Question context
            patient_response (str): Patient's answer
            
        Returns:
            str: Formatted prompt
        """
        field_name = question['field']
        field_type = question.get('field_type', 'text')
        question_text = question['question']
        
        # Base prompt template
        prompt = f"""You are a medical data extractor for ophthalmology consultations.

Question asked: "{question_text}"
Expected field: {field_name}
Field type: {field_type}
"""
        
        # Add valid values if categorical
        if field_type == 'categorical' and 'valid_values' in question:
            valid_values = question['valid_values']
            prompt += f"Valid values: {', '.join(valid_values)}\n"
        
        # Add definitions if present
        if 'definitions' in question:
            prompt += "\nDefinitions:\n"
            for key, defn in question['definitions'].items():
                prompt += f"  - {key}: {defn}\n"
        
        # Add patient response
        prompt += f"""
Patient response: "{patient_response}"

Extract the {field_name} field from the patient's response.
Return ONLY valid JSON in this format:
{{"{field_name}": "extracted_value"}}

Rules:
- If the patient's response clearly contains the information, extract it
- If unclear or the patient doesn't know, return: {{}}
- Use the exact field name: {field_name}
- For categorical fields, use one of the valid values if possible
"""
        
        return prompt
    
    def _process_extraction(self, parsed, question):
        """
        Process parsed LLM output and standardize values
        
        Args:
            parsed (dict): Parsed JSON from LLM
            question (dict): Question context
            
        Returns:
            dict: Standardized field extractions
        """
        field_name = question['field']
        valid_values = question.get('valid_values')
        
        result = {}
        
        # Check if LLM returned the expected field
        if field_name in parsed:
            raw_value = parsed[field_name]
            
            # Map to standardized value
            standardized = map_field_value(
                field_name=field_name,
                raw_value=raw_value,
                valid_values=valid_values
            )
            
            # Validate against schema if categorical
            if valid_values:
                is_valid = validate_against_schema(field_name, standardized, valid_values)
                if not is_valid:
                    logger.warning(f"Extracted value '{standardized}' not in valid_values: {valid_values}")
                    logger.warning(f"Using it anyway (best effort)")
            
            result[field_name] = standardized
            logger.info(f"Extracted {field_name}: '{raw_value}' -> '{standardized}'")
        
        # Check for additional fields LLM might have extracted
        # (patient mentioned multiple things in one response)
        for key, value in parsed.items():
            if key != field_name and not key.startswith('_'):
                # Map and include
                standardized = map_field_value(
                    field_name=key,
                    raw_value=value,
                    valid_values=None
                )
                result[key] = standardized
                logger.info(f"Additional field extracted {key}: '{value}' -> '{standardized}'")
        
        return result