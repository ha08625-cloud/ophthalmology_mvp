"""
Response Parser V2 - Clinical extraction sub-orchestrator
"""

import json
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from backend.contracts import (
    ValueEnvelope,
    QuestionOutput,
    EncoderOutput,
    LLMExtractionResult,
    LLMEscalationRequest,
    ClinicalExtractionResult
)
from backend.clinical_extractor_encoder import ClinicalExtractorEncoder
from backend.clinical_extractor_logic import ClinicalExtractorLogic
from backend.clinical_extractor_llm import ClinicalExtractorLLM
from backend.utils.hf_client_v2 import HuggingFaceClient

logger = logging.getLogger(__name__)


# Type alias for V4 return structure
ParseResult = Dict[str, Any]

# Valid outcome values (V4 contract)
OUTCOME_SUCCESS = "success"
OUTCOME_PARTIAL = "partial_success"
OUTCOME_UNCLEAR = "unclear"
OUTCOME_EXTRACTION_FAILED = "extraction_failed"
OUTCOME_GENERATION_FAILED = "generation_failed"

# Boolean normalization mappings
TRUE_VALUES = {'true', 'yes', 'y', '1', 't'}
FALSE_VALUES = {'false', 'no', 'n', '0', 'f'}


class ResponseParserV2:
    
    def __init__(
        self,
        hf_client: Optional[HuggingFaceClient] = None,
        encoder: Optional[ClinicalExtractorEncoder] = None,
        logic: Optional[ClinicalExtractorLogic] = None,
        llm_extractor: Optional[ClinicalExtractorLLM] = None,
        temperature: float = 0.0,
        max_tokens: int = 256
    ) -> None:
        """
        Two modes of initialization:
        V4 (legacy): Pass hf_client only
            ResponseParserV2(hf_client=client)
        V5 (new): Pass encoder, logic, llm_extractor
            ResponseParserV2(
                encoder=encoder,
                logic=logic,
                llm_extractor=llm_extractor
            )
            
        Mixed mode: Pass all (uses V5 for extract(), V4 for parse())
        """
        # Store V4 dependencies
        self.hf_client = hf_client
        self.temperature = temperature
        self.max_tokens = max_tokens
        
        # Store V5 dependencies
        self.encoder = encoder
        self.logic = logic
        self.llm_extractor = llm_extractor
        
        # Determine available modes
        self._v4_available = hf_client is not None
        self._v5_available = all([encoder, logic, llm_extractor])
        
        if not self._v4_available and not self._v5_available:
            raise ValueError(
                "ResponseParserV2 requires either hf_client (V4) or "
                "encoder+logic+llm_extractor (V5)"
            )
        
        # Validate V4 dependencies if provided
        if self._v4_available:
            self._validate_v4_client(hf_client)
        
        # Log initialization mode
        modes = []
        if self._v4_available:
            modes.append("V4-legacy")
        if self._v5_available:
            modes.append("V5-orchestrator")
        
        logger.info(
            f"ResponseParserV2 initialized (modes: {', '.join(modes)}, "
            f"temp={temperature}, max_tokens={max_tokens})"
        )
    
    def _validate_v4_client(self, hf_client: HuggingFaceClient) -> None:
        """Validate V4 HuggingFace client."""
        if not isinstance(hf_client, HuggingFaceClient):
            raise TypeError("hf_client must be HuggingFaceClient instance")
        
        if not hasattr(hf_client, 'generate_json') or not callable(hf_client.generate_json):
            raise TypeError("hf_client must have callable generate_json() method")
        
        if not hf_client.is_loaded():
            raise RuntimeError("HuggingFace client model not loaded")
    
    # =========================================================================
    # V5 Interface - New orchestrator mode
    # =========================================================================
    
    def extract(
        self,
        question: QuestionOutput,
        user_text: str,
        turn_id: Optional[str] = None
    ) -> Dict[str, ValueEnvelope]:
        """
        This is the new primary entry point. Dialogue Manager calls this
        with QuestionOutput and user text, receives ValueEnvelopes.
        """
        if not self._v5_available:
            raise RuntimeError(
                "V5 extract() requires encoder, logic, and llm_extractor. "
                "Initialize with these dependencies or use V4 parse() method."
            )
        
        # Validate inputs
        if not isinstance(question, QuestionOutput):
            raise TypeError(
                f"question must be QuestionOutput, got {type(question).__name__}"
            )
        
        if not isinstance(user_text, str):
            raise TypeError(
                f"user_text must be string, got {type(user_text).__name__}"
            )
        
        logger.debug(f"[{turn_id}] V5 extract called for field: {question.field}")
        
        # Step 1: Run encoder
        encoder_output = self.encoder.extract(
            user_text=user_text,
            fields_to_evaluate=(question.field,)
        )
        
        # Step 2: Evaluate encoder output, get extractions and escalations
        encoder_extractions, escalation_requests = self.logic.evaluate_encoder_output(
            encoder_output=encoder_output,
            primary_field=question.field
        )
        
        # Step 3: Run LLM for escalated fields
        llm_results = []
        for escalation in escalation_requests:
            llm_result = self.llm_extractor.extract(
                user_text=user_text,
                escalation_request=escalation,
                question_context=question.question
            )
            llm_results.append(llm_result)
        
        # Step 4: Merge outputs
        extraction_result = self.logic.merge_outputs(
            encoder_extractions=encoder_extractions,
            llm_results=tuple(llm_results),
            escalation_requests=escalation_requests
        )
        
        # Step 5: Collapse to ValueEnvelopes
        envelopes = self._collapse_to_envelopes(extraction_result)
        
        logger.debug(
            f"[{turn_id}] V5 extraction complete: {len(envelopes)} fields extracted"
        )
        
        return envelopes
    
    def _collapse_to_envelopes(
        self,
        result: ClinicalExtractionResult
    ) -> Dict[str, ValueEnvelope]:
        """
        Collapse ClinicalExtractionResult to Dict[str, ValueEnvelope].
        This is the boundary crossing point. Only ValueEnvelopes
        leave Response Parser. Dialogue Manager never sees
        ClinicalExtractionResult.
        """
        envelopes = {}
        
        # Process encoder extractions
        for field_id, value in result.encoder_extractions.items():
            confidence = result.confidence_scores.get(field_id, 1.0)
            envelopes[field_id] = ValueEnvelope(
                value=value,
                source='encoder',
                confidence=confidence
            )
            logger.debug(
                f"Collapsed encoder extraction: {field_id}={value} "
                f"(confidence={confidence})"
            )
        
        # Process LLM extractions (may override encoder if both present)
        for field_id, value in result.llm_extractions.items():
            confidence = result.confidence_scores.get(field_id, 1.0)
            envelopes[field_id] = ValueEnvelope(
                value=value,
                source='llm',
                confidence=confidence
            )
            logger.debug(
                f"Collapsed LLM extraction: {field_id}={value} "
                f"(confidence={confidence})"
            )
        
        return envelopes
    
    # =========================================================================
    # V4 Interface - Legacy mode (preserved for backward compatibility)
    # =========================================================================
    
    def parse(
        self,
        prompt_text: str,
        patient_response: str,
        expected_field: Optional[str] = None,
        turn_id: Optional[str] = None
    ) -> ParseResult:
        """
        Extract structured fields from patient response using pre-built prompt.
        V4 LEGACY INTERFACE - Preserved for backward compatibility.
        New code should use extract() method instead.
        """
        if not self._v4_available:
            raise RuntimeError(
                "V4 parse() requires hf_client. "
                "Initialize with hf_client or use V5 extract() method."
            )
        
        # Validate inputs
        if not isinstance(prompt_text, str):
            raise TypeError(
                f"prompt_text must be string, got {type(prompt_text).__name__}"
            )
        
        if not isinstance(patient_response, str):
            raise TypeError(
                f"patient_response must be string, got {type(patient_response).__name__}"
            )
        
        # Initialize parse_metadata
        timestamp = datetime.now(timezone.utc).isoformat()
        parse_metadata = {
            'expected_field': expected_field,
            'turn_id': turn_id,
            'timestamp': timestamp,
            'raw_llm_output': None,
            'error_message': None,
            'error_type': None,
            'validation_warnings': [],
            'normalization_applied': [],
            'extraction_mode': 'v4_legacy'  # V5: Added mode indicator
        }
        
        logger.debug(f"[{turn_id}] V4 parse calling LLM with prompt")
        
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
        
        # Wrap extracted fields in ValueEnvelope for provenance tracking
        enveloped_fields = self._wrap_in_envelopes_v4(extracted_fields)
        
        # Determine outcome based on what was extracted
        if expected_field and expected_field in extracted_fields and extracted_fields[expected_field] is not None:
            outcome = OUTCOME_SUCCESS
            logger.info(
                f"[{turn_id}] SUCCESS: {expected_field} = "
                f"{extracted_fields[expected_field]}"
            )
            
        elif len(extracted_fields) > 0:
            if expected_field:
                outcome = OUTCOME_PARTIAL
                logger.info(
                    f"[{turn_id}] PARTIAL: got {list(extracted_fields.keys())}, "
                    f"expected {expected_field}"
                )
            else:
                outcome = OUTCOME_SUCCESS
                logger.info(
                    f"[{turn_id}] SUCCESS: got {list(extracted_fields.keys())}"
                )
            
        else:
            logger.warning(
                f"[{turn_id}] Unexpected: parsed non-empty but extracted nothing"
            )
            parse_metadata['error_message'] = (
                "Extraction logic error - parsed non-empty but extracted nothing"
            )
            outcome = OUTCOME_EXTRACTION_FAILED
        
        return {
            'outcome': outcome,
            'fields': enveloped_fields,
            'parse_metadata': parse_metadata
        }
    
    # =========================================================================
    # Shared helpers
    # =========================================================================
    
    def _validate_and_normalize_extraction(
        self,
        parsed: Dict[str, Any],
        parse_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate and normalize fields from LLM output.
        Used by V4 parse() method. V5 extract() has its own normalization
        in the logic module.
        """
        extracted_fields = {}
        
        for key, value in parsed.items():
            # Skip internal fields
            if key.startswith('_'):
                continue
            
            # Apply normalization if applicable
            original_value = value
            normalized_value = value
            
            # Boolean normalization
            if isinstance(value, str):
                potential_bool = self._normalize_boolean(value)
                
                if potential_bool is not None and potential_bool != value:
                    normalized_value = potential_bool
                    
                    parse_metadata['normalization_applied'].append({
                        'field': key,
                        'original_value': original_value,
                        'normalized_value': normalized_value,
                        'normalization_type': 'boolean'
                    })
                    logger.debug(
                        f"Field '{key}': normalized '{original_value}' -> {normalized_value}"
                    )
            
            elif isinstance(value, bool):
                normalized_value = value
            
            extracted_fields[key] = normalized_value
            logger.debug(f"Extracted '{key}': {normalized_value}")
        
        return extracted_fields
    
    def _normalize_boolean(self, value: Any) -> Optional[bool]:
        """
        Normalize string boolean values to Python bool.
        
        Recognizes true/false/yes/no/y/n/1/0/t/f (case-insensitive)
        
        Args:
            value: Value that might represent a boolean
            
        Returns:
            True, False, or None if cannot normalize
        """
        if isinstance(value, bool):
            return value
        
        if not isinstance(value, str):
            return None
        
        value_lower = value.lower().strip()
        
        if value_lower in TRUE_VALUES:
            return True
        elif value_lower in FALSE_VALUES:
            return False
        else:
            return None
    
    def _wrap_in_envelopes_v4(
        self,
        extracted_fields: Dict[str, Any]
    ) -> Dict[str, ValueEnvelope]:
        """
        Wrap extracted field values in ValueEnvelope objects (V4 mode).
        
        V4 envelopes use source='response_parser' to indicate legacy mode.
        V5 envelopes use source='encoder' or source='llm'.
        
        Args:
            extracted_fields: Dict of field_name -> raw value
            
        Returns:
            Dict of field_name -> ValueEnvelope
        """
        enveloped = {}
        
        for field_name, value in extracted_fields.items():
            enveloped[field_name] = ValueEnvelope(
                value=value,
                source='response_parser',  # V4 legacy source identifier
                confidence=1.0
            )
            logger.debug(
                f"V4 wrapped '{field_name}' in envelope: "
                f"value={value}, source=response_parser"
            )
        
        return enveloped
    
    # =========================================================================
    # Introspection
    # =========================================================================
    
    def get_available_modes(self) -> Dict[str, bool]:
        """
        Return which extraction modes are available.
        
        Returns:
            Dict with 'v4_legacy' and 'v5_orchestrator' availability
        """
        return {
            'v4_legacy': self._v4_available,
            'v5_orchestrator': self._v5_available
        }
