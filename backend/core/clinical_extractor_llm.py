"""
Clinical Extractor LLM - LLM-based field extraction for escalated fields (STUB)
"""

import logging
from typing import Optional

# Flat import for server, adjust for local
try:
    from backend.contracts import LLMEscalationRequest, LLMExtractionResult
except ImportError:
    from contracts import LLMEscalationRequest, LLMExtractionResult

logger = logging.getLogger(__name__)


class ClinicalExtractorLLM:
    
    def __init__(self, hf_client=None) -> None:
        """
        Initialize LLM extractor.
        
        Args:
            hf_client: HuggingFaceClient instance (ignored in stub)
        """
        self.hf_client = hf_client
        logger.info("ClinicalExtractorLLM initialized (STUB)")
    
    def extract(
        self,
        user_text: str,
        escalation_request: LLMEscalationRequest,
        question_context: Optional[str] = None
    ) -> LLMExtractionResult:
        """
        Run LLM extraction for escalated fields.
      
        Phase 1: Returns LLMExtractionResult with empty extractions
        """
        logger.debug(
            f"[STUB] LLM extract called for fields: {escalation_request.fields}"
        )
        
        return LLMExtractionResult(
            extracted_fields={},
            fields_requested=escalation_request.fields,
            llm_metadata={
                'stub': True,
                'reason': 'Phase 1 stub implementation'
            }
        )
