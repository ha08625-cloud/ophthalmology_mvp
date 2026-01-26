"""
Clinical Extractor Logic - Gating and extraction decision logic (STUB)
"""

import logging
from typing import Dict, Any, Tuple

from backend.contracts import (
        EncoderOutput,
        LLMExtractionResult,
        LLMEscalationRequest,
        ClinicalExtractionResult
    )

logger = logging.getLogger(__name__)

STUB_RULESET_VERSION = "stub_v1"
STUB_FIELD_HASH = "stub_hash"


class ClinicalExtractorLogic:
    
    def __init__(self, ruleset_path: str = None) -> None:
        """
        Initialize logic module.
        
        Args:
            ruleset_path: Path to ruleset JSON (ignored in stub)
        """
        self.ruleset_path = ruleset_path
        logger.info("ClinicalExtractorLogic initialized (STUB)")
    
    def evaluate_encoder_output(
        self,
        encoder_output: EncoderOutput,
        primary_field: str
    ) -> Tuple[Dict[str, Any], Tuple[LLMEscalationRequest, ...]]:
        """
        Evaluate encoder output and determine extractions/escalations (empty for stub)
        """
        logger.debug(f"[STUB] Evaluating encoder output for: {primary_field}")
        
        # Stub: no extractions, no escalations
        extractions: Dict[str, Any] = {}
        escalations: Tuple[LLMEscalationRequest, ...] = ()
        
        return extractions, escalations
    
    def merge_outputs(
        self,
        encoder_extractions: Dict[str, Any],
        llm_results: Tuple[LLMExtractionResult, ...],
        escalation_requests: Tuple[LLMEscalationRequest, ...]
    ) -> ClinicalExtractionResult:
        """
        Merge encoder and LLM outputs into final result (empty for stub)
        """
        logger.debug("[STUB] Merging outputs")
        
        # Stub: empty result with empty trace
        return ClinicalExtractionResult(
            encoder_extractions={},
            llm_extractions={},
            provenance={},
            confidence_scores={},
            gating_decisions={},
            escalation_requests=escalation_requests,
            inference_trace={
                'stub': True,
                'phase': 1
            }
        )
