"""
Episode Hypothesis Signal - Contract between EHG and Dialogue Manager

Purpose:
    Structured output from Episode Hypothesis Generator (EHG) consumed by:
    - DialogueManager (orchestration)
    - Episode Hypothesis Manager (mode transition logic)
    
    This is a cross-cutting contract, not a mode-specific concern.
    
Design:
    - Immutable signal (frozen dataclass)
    - Type-safe via enums for confidence bands
    - Semantic documentation, minimal runtime validation
    - Ready for future expansion (provenance, raw text, calibration metadata)
    
Current Status:
    Stub only. Real EHG not yet implemented.
    Use EpisodeHypothesisSignal.no_ambiguity() for hardcoded passthrough.
    
Future Expansion Points:
    - Provenance tracking (which turn, which utterance span)
    - Confidence calibration metadata
    - Raw LLM output for audit trails
    - Multi-turn confidence evolution
"""

from dataclasses import dataclass
from enum import Enum


class ConfidenceBand(Enum):
    """
    Confidence level for EHG probabilistic outputs.
    
    Used for both hypothesis detection and pivot detection.
    
    Values:
        LOW: Weak signal, high uncertainty
        MEDIUM: Moderate signal, some uncertainty remains
        HIGH: Strong signal, minimal uncertainty
        
    Design notes:
        - String values for clean JSON serialization
        - Enum prevents silent drift ("High", "hi", "medium ")
        - Marks deterministic/probabilistic boundary
        - Used as gate in mode transition logic
    """
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class EpisodeHypothesisSignal:
    """
    Structured signal from Episode Hypothesis Generator (EHG).
    
    Attributes:
        hypothesis_count (int): Number of episode hypotheses detected in user input.
            Semantic meanings:
                0 = no episode referenced (off-topic, system question, input error)
                1 = exactly one episode referenced (may be new or existing)
                >1 = multiple distinct episode hypotheses present
            
            Validation: Must be >= 0. Negative values are nonsensical.
            Note: Consumer (EHM) interprets counts, not this class.
            
        confidence_band (ConfidenceBand): Confidence in hypothesis_count detection.
            Used as gate in mode transitions:
                HIGH + count=1 → may proceed to extraction
                LOW/MEDIUM → triggers clarification
                
        pivot_detected (bool): Whether user pivoted away from current episode context.
            Only meaningful when hypothesis_count = 1.
            
            True = user started talking about a different episode
            False = user continuing discussion of current episode
            
            Ignored when hypothesis_count != 1.
            
        pivot_confidence_band (ConfidenceBand): Confidence in pivot detection.
            Gates whether pivot signal triggers clarification.
            Only meaningful when pivot_detected = True.
    
    Design invariants:
        - Immutable (frozen=True)
        - Type-safe via enums
        - Serializable (all fields are primitives or string-valued enums)
        
    Future expansion surface:
        - provenance metadata (turn index, utterance span)
        - raw LLM output for audit trails
        - confidence calibration scores
        - multi-turn hypothesis tracking
        
    Example usage:
        # Hardcoded stub (current)
        signal = EpisodeHypothesisSignal.no_ambiguity()
        
        # Future real EHG output
        signal = EpisodeHypothesisSignal(
            hypothesis_count=2,
            confidence_band=ConfidenceBand.HIGH,
            pivot_detected=False,
            pivot_confidence_band=ConfidenceBand.HIGH
        )
    """
    hypothesis_count: int
    confidence_band: ConfidenceBand
    pivot_detected: bool
    pivot_confidence_band: ConfidenceBand
    
    @classmethod
    def no_ambiguity(cls) -> "EpisodeHypothesisSignal":
        """
        Factory for hardcoded "no ambiguity" signal.
        
        Semantics:
            - Exactly one episode hypothesis
            - High confidence in detection
            - No pivot detected
            - High confidence in pivot absence
            
        Use case:
            Stub implementation while EHG is not yet built.
            Allows incremental integration with DialogueManager.
            
        Returns:
            EpisodeHypothesisSignal: Safe default signal indicating no ambiguity
            
        Example:
            signal = EpisodeHypothesisSignal.no_ambiguity()
            # DialogueManager can depend on this contract immediately
        """
        return cls(
            hypothesis_count=1,
            confidence_band=ConfidenceBand.HIGH,
            pivot_detected=False,
            pivot_confidence_band=ConfidenceBand.HIGH
        )