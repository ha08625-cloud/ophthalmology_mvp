"""
Clinical Extractor Encoder - ClinicalBERT-based field extraction (STUB)
"""

import logging
from typing import Dict

backend.contracts import EncoderOutput

logger = logging.getLogger(__name__)

STUB_ENCODER_VERSION = "stub_v1"

class ClinicalExtractorEncoder:
    
    def __init__(self) -> None:
        """Initialize encoder (stub - no model loading)."""
        logger.info("ClinicalExtractorEncoder initialized (STUB)")
        self._is_loaded = True  # Stub is always "loaded"
    
    def is_loaded(self) -> bool:
        """Check if encoder is ready."""
        return self._is_loaded
    
    def extract(
        self,
        user_text: str,
        fields_to_evaluate: Tuple[str, ...] = ()
    ) -> EncoderOutput:
        """
        Run encoder extraction on user text.
        
        Phase 1: Returns EncoderOutput with empty logits
        """
        logger.debug(f"[STUB] Encoder extract called: '{user_text[:50]}...'")
        
        return EncoderOutput(
            field_logits={},
            fields_evaluated=fields_to_evaluate,
            encoder_version=STUB_ENCODER_VERSION
        )
