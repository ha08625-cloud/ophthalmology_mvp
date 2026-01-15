"""
Response Parser V2 - Extract structured data from patient responses

Responsibilities:
- Build extraction prompts from question context
- Call LLM to extract structured fields
- Parse and validate LLM output with normalization
- Handle unclear responses and extraction failures
- Return contract-compliant structure

Contract: response_parser_contract_v1.json

Design principles:
- Explicit return contract (outcome, fields, parse_metadata)
- Early return for clearly unclear responses
- Boolean normalization with auditability
- Validation warnings (not failures)
- Fail gracefully with structured errors
"""

import json
import logging
from enum import Enum
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from hf_client import HuggingFaceClient

logger = logging.getLogger(__name__)


# Extraction mode (V3.1)
# Used for instrumentation and provenance tracking.
# The parser does not change behavior based on mode.
class ExtractionMode(str, Enum):
    """
    Extraction mode flag for Response Parser.
    
    This is a parser-internal contract flag, not conversation-level state.
    The parser does not interpret the mode; it only echoes it in metadata
    for instrumentation, logging, and provenance tracking.
    
    Values:
        NORMAL_EXTRACTION: Standard extraction from patient response
        REPLAY_EXTRACTION: Extraction from clarification replay transcript
    """
    NORMAL_EXTRACTION = "normal_extraction"
    REPLAY_EXTRACTION = "replay_extraction"


# Type alias for return structure (contract v1.0.0)
ParseResult = Dict[str, Any]

# Valid outcome values (contract v1.0.0)
OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL = "partial_success"
OUTCOME_UNCLEAR = "unclear"
OUTCOME_EXTRACTION_FAILED = "extraction_failed"
OUTCOME_GENERATION_FAILED = "generation_failed"

# Pure unclear response patterns (early return, no LLM call)
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

# Boolean normalization mappings (contract v1.0.0)
TRUE_VALUES = {'true', 'yes', 'y', '1', 't'}
FALSE_VALUES = {'false', 'no', 'n', '0', 'f'}


class ResponseParserV2:
    """Extract structured medical data from patient responses"""
    
    def __init__(
        self,
        hf_client: HuggingFaceClient,
        temperature: float = 0.0,
        max_tokens: int = 256
    ) -> None:
        """
        Initialize parser with HuggingFace client
        
        Args:
            hf_client: Initialized model client
            temperature: LLM sampling temperature (default 0.0)
            max_tokens: Max tokens to generate (default 256)
            
        Raises:
            TypeError: If hf_client wrong type or missing methods
            RuntimeError: If hf_client model not loaded
        """
        if not isinstance(hf_client, HuggingFaceClient):
            raise TypeError("hf_client must be HuggingFaceClient instance")
        
        if not hasattr(hf_client, 'generate_json') or not callable(hf_client.generate_json):
            raise TypeError("hf_client must have callable generate_json() method")
        
        if not hf_client.is_loaded():
            raise RuntimeError("HuggingFace client model not loaded")
        
        self.hf_client = hf_client
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        logger.info(
            f"Response Parser V2 initialized "
            f"(temp={temperature}, max_tokens={max_tokens})"
        )
    
    def parse(
        self,
        question: Dict[str, Any],
        patient_response: str,
        turn_id: Optional[str] = None,
        next_questions: Optional[List[Dict[str, Any]]] = None,
        symptom_categories: Optional[List[str]] = None,
        mode: ExtractionMode = ExtractionMode.NORMAL_EXTRACTION
    ) -> ParseResult:
        """
        Extract structured fields from patient response.
        
        Contract: response_parser_contract_v1.json
        
        Args:
            question: Question dict from Question Selector
                Must contain: 'id', 'question', 'field', 'field_type'
                Optional: 'valid_values', 'definitions'
            patient_response: What patient said
            turn_id: Dialogue turn identifier (e.g., 'turn_05') for provenance
            next_questions: List of upcoming question dicts (for metadata window).
                Parser may extract fields from these if patient mentions them.
                Default None (single-question mode, backward compatible).
            symptom_categories: List of symptom category field names (e.g., 'vl_present').
                Parser may extract these if patient mentions new symptoms.
                Default None (no symptom categories).
            mode: Extraction mode flag for instrumentation (V3.1).
                Does not change parser behavior. Echoed in metadata for
                logging, provenance tracking, and future safeguards.
                Default NORMAL_EXTRACTION.
            
        Returns:
            ParseResult: {
                'outcome': str (success|partial_success|unclear|extraction_failed|generation_failed),
                'fields': dict,
                'parse_metadata': dict
            }
            
        Raises:
            TypeError: If inputs have wrong type
            ValueError: If question dict missing required keys or has invalid structure
            
        Examples:
            >>> parse({'id': 'vl_3', 'field': 'vl_laterality', ...}, 'My right eye', 'turn_05')
            {
                'outcome': 'success',
                'fields': {'vl_laterality': 'right'},
                'parse_metadata': {'turn_id': 'turn_05', ...}
            }
            
            >>> parse(question, "I don't know", 'turn_06')
            {
                'outcome': 'unclear',
                'fields': {},
                'parse_metadata': {'turn_id': 'turn_06', ...}
            }
            
            >>> # Multi-question window
            >>> parse(
            ...     question={'id': 'vl_5', 'field': 'vl_laterality', ...},
            ...     patient_response='Right eye, started yesterday',
            ...     turn_id='turn_05',
            ...     next_questions=[
            ...         {'id': 'vl_6', 'field': 'vl_first_onset', ...},
            ...         {'id': 'vl_7', 'field': 'vl_pattern', ...}
            ...     ]
            ... )
            {
                'outcome': 'success',
                'fields': {'vl_laterality': 'right', 'vl_first_onset': 'yesterday'},
                'parse_metadata': {...}
            }
        """
        # Validate inputs
        if not isinstance(question, dict):
            raise TypeError(f"question must be dict, got {type(question).__name__}")
        
        required_keys = {'id', 'question', 'field', 'field_type'}
        missing_keys = required_keys - set(question.keys())
        if missing_keys:
            raise ValueError(f"question dict missing required keys: {missing_keys}")
        
        if not isinstance(patient_response, str):
            raise TypeError(
                f"patient_response must be string, got {type(patient_response).__name__}"
            )
        
        # Validate next_questions if provided
        if next_questions is not None:
            if not isinstance(next_questions, list):
                raise TypeError(
                    f"next_questions must be list, got {type(next_questions).__name__}"
                )
            for i, nq in enumerate(next_questions):
                if not isinstance(nq, dict):
                    raise TypeError(
                        f"next_questions[{i}] must be dict, got {type(nq).__name__}"
                    )
                # Verify required keys (same as main question)
                missing_nq_keys = required_keys - set(nq.keys())
                if missing_nq_keys:
                    raise ValueError(
                        f"next_questions[{i}] missing required keys: {missing_nq_keys}"
                    )
        
        # Validate symptom_categories if provided
        if symptom_categories is not None:
            if not isinstance(symptom_categories, list):
                raise TypeError(
                    f"symptom_categories must be list, got {type(symptom_categories).__name__}"
                )
            for i, sc in enumerate(symptom_categories):
                if not isinstance(sc, str):
                    raise TypeError(
                        f"symptom_categories[{i}] must be str, got {type(sc).__name__}"
                    )
        
        # Extract question metadata
        expected_field = question['field']
        question_id = question['id']
        field_type = question['field_type']
        valid_values = question.get('valid_values', [])
        
        # Validate valid_values if present
        if valid_values and not isinstance(valid_values, list):
            raise ValueError(
                f"valid_values must be list, got {type(valid_values).__name__}"
            )
        
        # Initialize parse_metadata (CONTRACT: renamed from 'metadata')
        timestamp = datetime.now(timezone.utc).isoformat()
        parse_metadata = {
            'expected_field': expected_field,
            'question_id': question_id,
            'turn_id': turn_id,  # CONTRACT: Added for provenance
            'extraction_mode': mode.value,  # V3.1: Extraction mode for instrumentation
            'timestamp': timestamp,
            'raw_llm_output': None,
            'error_message': None,
            'error_type': None,
            'unexpected_fields': [],
            'validation_warnings': [],
            'normalization_applied': []
        }
        
        # Check for pure unclear responses (early return, no LLM call)
        # FIX: Removed magic number 20 length check
        if self._is_pure_unclear(patient_response):
            logger.info(f"[{question_id}] Pure unclear response: '{patient_response}'")
            return {
                'outcome': OUTCOME_UNCLEAR,
                'fields': {},
                'parse_metadata': parse_metadata
            }
        
        # Build extraction prompt
        prompt = self._build_prompt(
            question=question,
            patient_response=patient_response,
            next_questions=next_questions,
            symptom_categories=symptom_categories
        )
        logger.debug(f"[{question_id}] Built prompt for field '{expected_field}'")
        
        # Call LLM
        try:
            llm_output = self.hf_client.generate_json(
                prompt=prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            parse_metadata['raw_llm_output'] = llm_output
            logger.debug(f"[{question_id}] LLM output: {llm_output[:200]}...")
            
        except Exception as e:
            # Generation failed (CUDA OOM, timeout, etc)
            logger.error(
                f"[{question_id}] LLM generation failed: {type(e).__name__} - {e}"
            )
            parse_metadata['error_message'] = str(e)
            parse_metadata['error_type'] = type(e).__name__
            
            return {
                'outcome': OUTCOME_GENERATION_FAILED,
                'fields': {},
                'parse_metadata': parse_metadata
            }
        
        # Parse JSON output
        try:
            parsed = json.loads(llm_output)
        except json.JSONDecodeError as e:
            # Extraction failed - invalid JSON
            logger.warning(f"[{question_id}] Invalid JSON: {e}")
            parse_metadata['error_message'] = f"Invalid JSON: {str(e)}"
            parse_metadata['error_type'] = 'JSONDecodeError'
            
            return {
                'outcome': OUTCOME_EXTRACTION_FAILED,
                'fields': {},
                'parse_metadata': parse_metadata
            }
        
        # Check if LLM returned empty dict
        if not parsed or len(parsed) == 0:
            logger.info(f"[{question_id}] LLM returned empty extraction")
            parse_metadata['error_message'] = "LLM returned empty extraction"
            
            return {
                'outcome': OUTCOME_EXTRACTION_FAILED,
                'fields': {},
                'parse_metadata': parse_metadata
            }
        
        # Validate and normalize extracted fields
        extracted_fields = self._validate_and_normalize_extraction(
            parsed=parsed,
            question=question,
            expected_field=expected_field,
            field_type=field_type,
            valid_values=valid_values,
            parse_metadata=parse_metadata,  # Passed by reference, will be mutated
            next_questions=next_questions,
            symptom_categories=symptom_categories
        )
        
        # Determine outcome based on what was extracted
        if expected_field in extracted_fields and extracted_fields[expected_field] is not None:
            # Got the expected field - SUCCESS
            outcome = OUTCOME_SUCCESS
            logger.info(
                f"[{question_id}] SUCCESS: {expected_field} = "
                f"{extracted_fields[expected_field]}"
            )
            
        elif len(extracted_fields) > 0:
            # Got some fields, but not the expected one - PARTIAL_SUCCESS
            outcome = OUTCOME_PARTIAL
            logger.info(
                f"[{question_id}] PARTIAL: got {list(extracted_fields.keys())}, "
                f"expected {expected_field}"
            )
            
        else:
            # This should not happen (we checked empty dict above)
            # But handle defensively
            logger.warning(
                f"[{question_id}] Unexpected: parsed non-empty but extracted nothing"
            )
            parse_metadata['error_message'] = (
                "Extraction logic error - parsed non-empty but extracted nothing"
            )
            outcome = OUTCOME_EXTRACTION_FAILED
        
        return {
            'outcome': outcome,
            'fields': extracted_fields,
            'parse_metadata': parse_metadata  # CONTRACT: renamed from 'metadata'
        }
    
    def _is_pure_unclear(self, response: str) -> bool:
        """
        Check if response is purely unclear (no extractable data)
        
        FIX: Removed magic number 20 length check - just match patterns directly
        
        Args:
            response: Patient response
            
        Returns:
            bool: True if pure unclear pattern
        """
        normalized = response.lower().strip()
        
        # Direct pattern matching - no length heuristic
        for pattern in UNCLEAR_PATTERNS:
            if pattern in normalized:
                return True
        
        return False
    
    def _validate_and_normalize_extraction(
        self,
        parsed: Dict[str, Any],
        question: Dict[str, Any],
        expected_field: str,
        field_type: str,
        valid_values: List[str],
        parse_metadata: Dict[str, Any],
        next_questions: Optional[List[Dict[str, Any]]] = None,
        symptom_categories: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Validate, normalize, and extract fields from LLM output.
        
        Mutates parse_metadata to add:
        - unexpected_fields
        - validation_warnings
        - normalization_applied
        
        Args:
            parsed: Parsed JSON from LLM
            question: Question context
            expected_field: Primary field we're looking for
            field_type: Type of expected field
            valid_values: Valid values for categorical fields
            parse_metadata: Metadata dict (mutated in place)
            next_questions: Optional list of upcoming questions (for metadata window)
            symptom_categories: Optional list of symptom category field names
            
        Returns:
            dict: Extracted fields with normalization applied
        """
        # Build set of expected field names (fields that should NOT generate warnings)
        expected_fields = {expected_field}
        
        # Add fields from next_questions
        if next_questions:
            for nq in next_questions:
                expected_fields.add(nq['field'])
        
        # Add symptom categories
        if symptom_categories:
            expected_fields.update(symptom_categories)
        
        extracted_fields = {}
        
        for key, value in parsed.items():
            # Skip internal fields
            if key.startswith('_'):
                continue
            
            # Track if this was expected (only flag unexpected if not in our window)
            if key not in expected_fields:
                parse_metadata['unexpected_fields'].append(key)
            
            # Apply normalization if applicable
            original_value = value
            normalized_value = value
            
            # Boolean normalization (contract v1.0.0)
            if field_type == 'boolean' or (key == expected_field and field_type == 'boolean'):
                normalized_value = self._normalize_boolean(value)
                
                if normalized_value is None:
                    # Could not normalize - validation warning
                    parse_metadata['validation_warnings'].append({
                        'field': key,
                        'value': value,
                        'issue': 'invalid_boolean',
                        'expected': [True, False]
                    })
                    logger.warning(
                        f"Field '{key}': could not normalize '{value}' to boolean"
                    )
                    # Keep original value
                    normalized_value = value
                    
                elif normalized_value != original_value:
                    # Normalization applied - record for auditability
                    parse_metadata['normalization_applied'].append({
                        'field': key,
                        'original_value': original_value,
                        'normalized_value': normalized_value,
                        'normalization_type': 'boolean'
                    })
                    logger.debug(
                        f"Field '{key}': normalized '{original_value}' Ã¢â€ â€™ {normalized_value}"
                    )
            
            # Validate categorical values (but still use them - flag warning only)
            if key == expected_field and valid_values and normalized_value not in valid_values:
                parse_metadata['validation_warnings'].append({
                    'field': key,
                    'value': normalized_value,
                    'issue': 'not_in_valid_values',
                    'expected': valid_values
                })
                logger.warning(
                    f"Field '{key}': value '{normalized_value}' not in "
                    f"valid_values {valid_values}"
                )
            
            extracted_fields[key] = normalized_value
            logger.debug(f"Extracted '{key}': {normalized_value}")
        
        return extracted_fields
    
    def _normalize_boolean(self, value: Any) -> Optional[bool]:
        """
        Normalize string boolean values to Python bool.
        
        Contract: Recognizes true/false/yes/no/y/n/1/0/t/f (case-insensitive)
        
        Args:
            value: Value that might represent a boolean
            
        Returns:
            True, False, or None if cannot normalize
        """
        # Already boolean - pass through
        if isinstance(value, bool):
            return value
        
        # Try string normalization
        if not isinstance(value, str):
            return None
        
        value_lower = value.lower().strip()
        
        if value_lower in TRUE_VALUES:
            return True
        elif value_lower in FALSE_VALUES:
            return False
        else:
            return None
    
    def _build_prompt(
        self,
        question: Dict[str, Any],
        patient_response: str,
        next_questions: Optional[List[Dict[str, Any]]] = None,
        symptom_categories: Optional[List[str]] = None
    ) -> str:
        """
        Build extraction prompt for LLM
        
        NOTE: Prompt formatting (e.g., [INST] tags) is now handled by
        HuggingFaceClient/PromptFormatter, not here. This method just
        builds the content.
        
        Args:
            question: Question context (primary question)
            patient_response: Patient's answer
            next_questions: Optional list of upcoming questions (metadata window)
            symptom_categories: Optional list of symptom category field names
            
        Returns:
            str: Plain text prompt (formatting applied by HF client)
        """
        field_name = question['field']
        field_type = question.get('field_type', 'text')
        question_text = question['question']
        
        # Base prompt template
        prompt = f"""You are a medical data extractor for ophthalmology consultations.

PRIMARY QUESTION:
Question asked: "{question_text}"
Expected field: {field_name}
Field type: {field_type}
"""
        
        # Add valid values if categorical
        if field_type == 'categorical' and 'valid_values' in question:
            valid_values = question['valid_values']
            prompt += f"Valid values: {', '.join(valid_values)}\n"
            prompt += "IMPORTANT: You MUST use one of these exact valid values.\n"
        
        # Add definitions if present
        if 'definitions' in question:
            prompt += "\nDefinitions:\n"
            for key, defn in question['definitions'].items():
                prompt += f"  - {key}: {defn}\n"
        
        # Add metadata window for next questions
        if next_questions and len(next_questions) > 0:
            prompt += "\nADDITIONAL CONTEXT - You may also extract these fields if clearly mentioned:\n"
            for nq in next_questions:
                nq_field = nq['field']
                nq_type = nq.get('field_type', 'text')
                
                # Format based on field type
                if nq_type == 'categorical' and 'valid_values' in nq:
                    nq_valid = ', '.join(nq['valid_values'])
                    prompt += f"  - Field: {nq_field}, Type: {nq_type}, Valid values: {nq_valid}\n"
                else:
                    prompt += f"  - Field: {nq_field}, Type: {nq_type}\n"
        
        # Add symptom categories
        if symptom_categories and len(symptom_categories) > 0:
            prompt += "\nSYMPTOM CATEGORIES - You may extract these if patient mentions new symptoms:\n"
            symptom_list = ', '.join(symptom_categories)
            prompt += f"  - {symptom_list}\n"
        
        # Add patient response
        prompt += f"""
Patient response: "{patient_response}"

Extract any relevant fields from the patient's response.
Return ONLY valid JSON in this format:
{{
  "{field_name}": "value",     # PRIMARY field - focus on this
  "other_field": "value"       # any additional fields from context
}}

Rules:
- PRIMARY focus on {field_name}
- You MAY extract additional fields listed in "ADDITIONAL CONTEXT" if clearly mentioned
- You MAY extract symptom category fields if patient mentions new symptoms
- If the patient's response is unclear or doesn't contain information, return: {{}}
- Use exact field names as listed above
- For categorical fields, use exact valid values as listed
- For boolean fields, use true or false (lowercase, no quotes around the boolean)
"""
        
        # No more model-specific formatting here!
        return prompt
