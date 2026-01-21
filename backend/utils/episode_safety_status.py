"""
Episode Safety Status - Deterministic safety assessment from probabilistic signals.

Purpose:
    This module provides a single boundary between probabilistic inference (EHG)
    and deterministic control flow (Dialogue Manager).
    
    It collapses the probabilistic EpisodeHypothesisSignal into a finite,
    deterministic safety decision that controls whether Response Parser output
    can be safely committed to state.
    
Scope:
    This module does NOT:
    - Decide episode identity
    - Resolve ambiguity
    - Ask clarification questions
    - Transition modes
    - Write state
    - Invoke Response Parser
    
    This module ONLY:
    - Interprets an EpisodeHypothesisSignal
    - Produces a single, finite safety status
    
Design Constraints:
    - Pure, total, deterministic function
    - No confidence band interpretation (intentionally conservative)
    - No episode IDs
    - No future placeholders
    - Never raises exceptions
    - No side effects, no logging
    
Integration:
    The EpisodeSafetyStatus is the sole mechanism by which ambiguity affects
    control flow in the simplified V3 architecture. No other module interprets
    EHG outputs directly.
"""

from enum import Enum
from backend.utils.episode_hypothesis_signal import EpisodeHypothesisSignal


class EpisodeSafetyStatus(Enum):
    """
    Finite safety decision output from Episode Hypothesis Signal assessment.
    
    This enum represents the deterministic interpretation of a probabilistic
    signal, used to gate whether Response Parser extraction can be committed.
    
    Values:
        SAFE_TO_EXTRACT: Single episode hypothesis, no pivot detected.
                        Safe to commit RP output to current episode.
        
        AMBIGUOUS_MULTIPLE: Multiple episode hypotheses detected.
                           Not safe to commit - clarification required.
        
        AMBIGUOUS_PIVOT: Single episode hypothesis but pivot detected.
                        Patient may have switched episodes.
                        Not safe to commit - clarification required.
    
    Design notes:
        - Semantically named (not numeric) for clarity
        - No confidence bands here - that interpretation happens upstream
        - Closed set - no future expansion without explicit decision
        - String-based enum for JSON serialization compatibility
    """
    SAFE_TO_EXTRACT = "safe_to_extract"
    AMBIGUOUS_MULTIPLE = "ambiguous_multiple"
    AMBIGUOUS_PIVOT = "ambiguous_pivot"


def assess_episode_safety(signal: EpisodeHypothesisSignal) -> EpisodeSafetyStatus:
    """
    Deterministically assess whether it is safe to commit RP extraction
    based on the Episode Hypothesis Signal.
    
    This function performs no inference and applies fixed precedence rules.
    It is a pure function with no side effects.
    
    Precedence rules (applied in order):
        1. Multiple episode hypotheses detected → AMBIGUOUS_MULTIPLE
        2. Pivot detected (single hypothesis) → AMBIGUOUS_PIVOT
        3. Otherwise → SAFE_TO_EXTRACT
    
    Args:
        signal: EpisodeHypothesisSignal from Episode Hypothesis Generator
    
    Returns:
        EpisodeSafetyStatus: One of three finite safety states
    
    Properties:
        - Pure function (same input always produces same output)
        - Total function (always returns a valid enum value)
        - Never raises exceptions
        - No side effects
        - No logging
    
    Design decisions:
        Confidence bands are intentionally ignored at this stage.
        Safety assessment is conservative by design.
        We want false positives (unnecessary clarification) rather than
        false negatives (missed ambiguity leading to clinical corruption).
        
        hypothesis_count=0 is treated as SAFE_TO_EXTRACT for now.
        This is a known limitation that will be addressed when better
        hardware and larger LLMs are available. Currently defaults to safe
        to prevent blocking the conversation on off-topic input.
    
    Examples:
        >>> signal = EpisodeHypothesisSignal(
        ...     hypothesis_count=1,
        ...     confidence_band=ConfidenceBand.HIGH,
        ...     pivot_detected=False,
        ...     pivot_confidence_band=ConfidenceBand.HIGH
        ... )
        >>> assess_episode_safety(signal)
        <EpisodeSafetyStatus.SAFE_TO_EXTRACT: 'safe_to_extract'>
        
        >>> signal = EpisodeHypothesisSignal(
        ...     hypothesis_count=2,
        ...     confidence_band=ConfidenceBand.LOW,
        ...     pivot_detected=False,
        ...     pivot_confidence_band=ConfidenceBand.LOW
        ... )
        >>> assess_episode_safety(signal)
        <EpisodeSafetyStatus.AMBIGUOUS_MULTIPLE: 'ambiguous_multiple'>
        
        >>> signal = EpisodeHypothesisSignal(
        ...     hypothesis_count=1,
        ...     confidence_band=ConfidenceBand.MEDIUM,
        ...     pivot_detected=True,
        ...     pivot_confidence_band=ConfidenceBand.MEDIUM
        ... )
        >>> assess_episode_safety(signal)
        <EpisodeSafetyStatus.AMBIGUOUS_PIVOT: 'ambiguous_pivot'>
    """
    # Confidence bands are intentionally ignored at this stage.
    # Safety assessment is conservative by design.
    
    # Rule 1: Multiple episode hypotheses → ambiguous
    if signal.hypothesis_count > 1:
        return EpisodeSafetyStatus.AMBIGUOUS_MULTIPLE
    
    # Rule 2: Single hypothesis but pivot detected → ambiguous
    if signal.pivot_detected:
        return EpisodeSafetyStatus.AMBIGUOUS_PIVOT
    
    # Rule 3: Default → safe (includes hypothesis_count=0 and hypothesis_count=1)
    # Note: hypothesis_count=0 treated as safe for now (known limitation)
    return EpisodeSafetyStatus.SAFE_TO_EXTRACT
