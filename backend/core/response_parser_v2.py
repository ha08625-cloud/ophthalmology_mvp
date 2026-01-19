"""
Response Parser V2 - Extract structured data from patient responses

Responsibilities:
- Execute extraction given pre-built prompt text
- Call LLM to extract structured fields
- Parse and validate LLM output with normalization
- Return contract-compliant structure

Contract: response_parser_contract_v1.json

Design principles:
- Explicit return contract (outcome, fields, parse_metadata)
- Boolean normalization with auditability
- Validation warnings (not failures)
- Fail gracefully with structured errors
- Pure executor - does not build prompts or make extraction decisions
"""

import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from hf_client_v2 import HuggingFaceClient

logger = logging.getLogger(__name__)


# Type alias for return structure (contract v1.0.0)
ParseResult = Dict[str, Any]

# Valid outcome values (contract v1.0.0)
OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL = "partial_success"
OUTCOME_UNCLEAR = "unclear"
OUTCOME_EXTRACTION_FAILED = "extraction_failed"
OUTCOME_GENERATION_FAILED = "generation_failed"

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
        prompt_text: str,
        patient_response: str,
        expected_field: Optional[str] = None,
        turn_id: Optional[str] = None
    ) -> ParseResult:
        """
        Extract structured fields from patient response using pre-built prompt.
        
        Contract: response_parser_contract_v1.json
        
        Args:
            prompt_text: Pre-built extraction prompt from PromptBuilder
            patient_response: What patient said (for metadata only)
            expected_field: Primary field being extracted (for outcome determination)
            turn_id: Dialogue turn identifier (e.g., 'turn_05') for provenance
            
        Returns:
            ParseResult: {
                'outcome': str (success|partial_success|unclear|extraction_failed|generation_failed),
                'fields': dict,
                'parse_metadata': dict
            }
            
        Raises:
            TypeError: If inputs have wrong type
            
        Examples:
            >>> prompt = builder.build(spec, "My right eye")
            >>> parse(prompt, "My right eye", expected_field='vl_laterality', turn_id='turn_05')
            {
                'outcome': 'success',
                'fields': {'vl_laterality': 'right'},
                'parse_metadata': {'turn_id': 'turn_05', ...}
            }
        """
        # Validate inputs
        if not isinstance(prompt_text, str):
            raise TypeError(
                f"prompt_text must be string, got {type(prompt_text).__name__}"
            )
        
        if not isinstance(patient_response, str):
            raise TypeError(
                f"patient_response must be string, got {type(patient_response).__name__}"
            )
        
        # Initialize parse_metadata (CONTRACT: renamed from 'metadata')
        timestamp = datetime.now(timezone.utc).isoformat()
        parse_metadata = {
            'expected_field': expected_field,
            'turn_id': turn_id,
            'timestamp': timestamp,
            'raw_llm_output': None,
            'error_message': None,
            'error_type': None,
            'validation_warnings': [],
            'normalization_applied': []
        }
        
        logger.debug(f"[{turn_id}] Calling LLM with prompt")
        
        # Call LLM
        try:
            llm_output = self.hf_client.generate_json(
                prompt=prompt_text,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            parse_metadata['raw_llm_output'] = llm_output
            logger.debug(f"[{turn_id}] LLM output: {llm_output[:200]}...")
            
        except Exception as e:
            # Generation failed (CUDA OOM, timeout, etc)
            logger.error(
                f"[{turn_id}] LLM generation failed: {type(e).__name__} - {e}"
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
            logger.warning(f"[{turn_id}] Invalid JSON: {e}")
            parse_metadata['error_message'] = f"Invalid JSON: {str(e)}"
            parse_metadata['error_type'] = 'JSONDecodeError'
            
            return {
                'outcome': OUTCOME_EXTRACTION_FAILED,
                'fields': {},
                'parse_metadata': parse_metadata
            }
        
        # Check if LLM returned empty dict (unclear response)
        if not parsed or len(parsed) == 0:
            logger.info(f"[{turn_id}] LLM returned empty extraction (unclear response)")
            
            return {
                'outcome': OUTCOME_UNCLEAR,
                'fields': {},
                'parse_metadata': parse_metadata
            }
        
        # Validate and normalize extracted fields
        extracted_fields = self._validate_and_normalize_extraction(
            parsed=parsed,
            parse_metadata=parse_metadata  # Passed by reference, will be mutated
        )
        
        # Determine outcome based on what was extracted
        if expected_field and expected_field in extracted_fields and extracted_fields[expected_field] is not None:
            # Got the expected field - SUCCESS
            outcome = OUTCOME_SUCCESS
            logger.info(
                f"[{turn_id}] SUCCESS: {expected_field} = "
                f"{extracted_fields[expected_field]}"
            )
            
        elif len(extracted_fields) > 0:
            # Got some fields, but not the expected one (or no expected field specified)
            if expected_field:
                outcome = OUTCOME_PARTIAL
                logger.info(
                    f"[{turn_id}] PARTIAL: got {list(extracted_fields.keys())}, "
                    f"expected {expected_field}"
                )
            else:
                # No expected field specified, but we got data
                outcome = OUTCOME_SUCCESS
                logger.info(
                    f"[{turn_id}] SUCCESS: got {list(extracted_fields.keys())}"
                )
            
        else:
            # This should not happen (we checked empty dict above)
            # But handle defensively
            logger.warning(
                f"[{turn_id}] Unexpected: parsed non-empty but extracted nothing"
            )
            parse_metadata['error_message'] = (
                "Extraction logic error - parsed non-empty but extracted nothing"
            )
            outcome = OUTCOME_EXTRACTION_FAILED
        
        return {
            'outcome': outcome,
            'fields': extracted_fields,
            'parse_metadata': parse_metadata
        }
    
    def _validate_and_normalize_extraction(
        self,
        parsed: Dict[str, Any],
        parse_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate and normalize fields from LLM output.
        
        Mutates parse_metadata to add:
        - validation_warnings
        - normalization_applied
        
        Args:
            parsed: Parsed JSON from LLM
            parse_metadata: Metadata dict (mutated in place)
            
        Returns:
            dict: Extracted fields with normalization applied
        """
        extracted_fields = {}
        
        for key, value in parsed.items():
            # Skip internal fields
            if key.startswith('_'):
                continue
            
            # Apply normalization if applicable
            original_value = value
            normalized_value = value
            
            # Boolean normalization (contract v1.0.0)
            # Check if value looks like a boolean string
            if isinstance(value, str):
                potential_bool = self._normalize_boolean(value)
                
                if potential_bool is not None and potential_bool != value:
                    # Successfully normalized a boolean
                    normalized_value = potential_bool
                    
                    # Record normalization for auditability
                    parse_metadata['normalization_applied'].append({
                        'field': key,
                        'original_value': original_value,
                        'normalized_value': normalized_value,
                        'normalization_type': 'boolean'
                    })
                    logger.debug(
                        f"Field '{key}': normalized '{original_value}' → {normalized_value}"
                    )
            
            # Already a boolean - pass through
            elif isinstance(value, bool):
                normalized_value = value
            
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