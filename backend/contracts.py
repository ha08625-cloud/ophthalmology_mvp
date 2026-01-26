"""
Semantic contracts for ophthalmology consultation system.
Contents:
- ValueEnvelope: Ingress-time wrapper for extracted values with provenance
- QuestionOutput: Immutable question representation from Question Selector
- EncoderOutput: Raw output from clinical_extractor_encoder
- LLMEscalationRequest: Request for LLM extraction when encoder cannot handle field
- LLMOutput: Output from clinical_extractor_llm
- ClinicalExtractionResult: Combined output from clinical extraction pipeline
"""

from dataclasses import dataclass
from typing import Any, Optional, Dict, Tuple


@dataclass(frozen=True)
class ValueEnvelope:
    """
    ValueEnvelope captures provenance metadata at the moment of extraction,
    before values enter the State Manager. This enables traceability without
    coupling extraction logic to storage logic.
    Note:
        ValueEnvelope is intentionally minimal. Additional metadata
        (timestamps, turn_id, etc.) lives in parse_metadata or is
        added by State Manager at write time.
    """
    value: Any
    source: str
    confidence: float = 1.0


@dataclass(frozen=True)
class QuestionOutput:
    """
    Immutable question representation returned by Question Selector.
    
    QuestionOutput is the complete specification for a question, containing
    everything needed by downstream consumers (primarily Prompt Builder for
    Response Parser)
    """
    id: str
    question: str
    field: str
    field_type: str = "text"
    type: str = "probe"
    valid_values: Optional[Tuple[str, ...]] = None
    field_label: Optional[str] = None
    field_description: Optional[str] = None
    definitions: Optional[Tuple[Tuple[str, str], ...]] = None

# =============================================================================
# V5 Clinical Extraction Contracts
# =============================================================================

@dataclass(frozen=True)
class EncoderOutput:
    """
    Raw output from clinical_extractor_encoder
    """
    field_logits: Dict[str, float]
    fields_evaluated: Tuple[str, ...]
    encoder_version: str


@dataclass(frozen=True)
class LLMEscalationRequest:
    """
    Produced by ClinicalExtractorLogic when gating conditions met.
    Consumed by ClinicalExtractorLLM.
    """
    fields: Tuple[str, ...]
    reason: str
    source_head: Optional[str]
    ruleset_version: str
    field_definition_hash: str


@dataclass(frozen=True)
class LLMOutput:

    extracted_fields: Dict[str, Any]
    fields_requested: Tuple[str, ...]
    llm_metadata: Dict[str, Any]


@dataclass(frozen=True)
class ClinicalExtractionResult:
    """
    Produced by ClinicalExtractorLogic after merging encoder and LLM outputs.
    Consumed by ResponseParser which collapses to Dict[str, ValueEnvelope].
    """
    encoder_extractions: Dict[str, Any]
    llm_extractions: Dict[str, Any]
    provenance: Dict[str, str]
    confidence_scores: Dict[str, float]
    gating_decisions: Dict[str, bool]
    escalation_requests: Tuple[LLMEscalationRequest, ...]
    inference_trace: Dict[str, Any]
