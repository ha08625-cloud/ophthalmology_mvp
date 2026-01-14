"""
Episode Hypothesis Generator - Stub Implementation

Purpose:
    Detect episode multiplicity, pivoting, and ambiguity in user utterances.
    This is a STUB implementation using simple keyword matching.
    Will be replaced by LLM-driven EHG in production.
    
Responsibilities:
    - Detect potential episode pivots via abandonment phrases
    - Estimate hypothesis count (currently defaults to 1)
    - Provide low-threshold ambiguity detection
    
Does NOT:
    - Enumerate mentions (that's Clarification Parser's job)
    - Extract clinical data (that's Response Parser's job)
    - Make episode identity decisions (that's Episode Hypothesis Manager's job)
    - Reference concrete episode IDs
    
Design:
    - Conservative behavior (fail gracefully, return safe defaults)
    - Designed for future LLM integration (interface ready, logic stubbed)
    - No exceptions raised from generate_hypothesis()
    - All errors logged and converted to safe default signals
    
Future LLM Integration:
    When replacing this stub with real LLM-driven EHG:
    - Keep the same interface (method signature)
    - Add LLM error handling:
        * LLM call fails → fail fast, raise exception (system error)
        * Malformed LLM output → log error, return safe default signal
    - Add confidence calibration
    - Add access to current_episode_context for comparison
"""

import logging
from typing import Optional, Dict, Any
from backend.utils.episode_hypothesis_signal import EpisodeHypothesisSignal, ConfidenceBand

logger = logging.getLogger(__name__)


class EpisodeHypothesisGeneratorStub:
    """
    Stub implementation for episode hypothesis generation.
    
    Current Logic:
        - Pivot detection: Simple abandonment phrase matching
        - Hypothesis count: Defaults to 1 (or 0 for empty input)
        - Confidence bands: Not yet implemented (placeholder HIGH values)
        
    Abandonment Phrases:
        "actually", "forget", "wait", "no", "different"
        These suggest user is pivoting away from current episode.
        
    Future LLM Implementation Will:
        - Analyze semantic episode boundaries
        - Compare against current_episode_context
        - Provide calibrated confidence scores
        - Handle complex multi-episode narratives
    """
    
    # Abandonment phrases that suggest episode pivoting
    # Keep lowercase for case-insensitive matching
    ABANDONMENT_PHRASES = ["actually", "forget", "wait", "no", "different"]
    
    def __init__(self):
        """Initialize the stub EHG."""
        logger.info("EpisodeHypothesisGeneratorStub initialized (stub mode)")
    
    def generate_hypothesis(
        self,
        user_utterance: str,
        current_episode_context: Optional[Dict[str, Any]] = None
    ) -> EpisodeHypothesisSignal:
        """
        Generate episode hypothesis signal from user utterance.
        
        Args:
            user_utterance: Raw user input text
            current_episode_context: TODO - Will contain confirmed episode details
                for semantic comparison. Not yet implemented.
                Expected structure (future):
                    {
                        "episode_id": str,
                        "presenting_complaint": str,
                        "temporal_context": str,
                        "laterality": Optional[str],
                        ...
                    }
        
        Returns:
            EpisodeHypothesisSignal with:
                - pivot_detected: True if abandonment phrase found
                - hypothesis_count: 0 if empty input, else 1
                - confidence_band: HIGH (placeholder, not yet meaningful)
                - pivot_confidence_band: HIGH (placeholder, not yet meaningful)
        
        Error Handling:
            Never raises exceptions. All errors logged and converted to safe defaults.
            Safe default = single episode, no pivot, no ambiguity.
        
        Examples:
            >>> ehg = EpisodeHypothesisGeneratorStub()
            >>> signal = ehg.generate_hypothesis("My eye hurts")
            >>> signal.pivot_detected
            False
            >>> signal.hypothesis_count
            1
            
            >>> signal = ehg.generate_hypothesis("Actually, it's a different problem")
            >>> signal.pivot_detected
            True
            
            >>> signal = ehg.generate_hypothesis("")
            >>> signal.hypothesis_count
            0
        """
        try:
            # Input validation and normalization
            if user_utterance is None:
                logger.warning("generate_hypothesis received None input, treating as empty")
                user_utterance = ""
            
            if not isinstance(user_utterance, str):
                logger.error(
                    f"generate_hypothesis received non-string input: {type(user_utterance)}, "
                    f"returning safe default signal"
                )
                return self._safe_default_signal()
            
            # Normalize for analysis
            utterance_normalized = user_utterance.strip().lower()
            
            # Hypothesis count logic
            # 0 if empty/whitespace-only, else default to 1
            if not utterance_normalized:
                hypothesis_count = 0
            else:
                hypothesis_count = 1
                # TODO: Real EHG will use semantic analysis + temporal markers
                #       to detect multiple episode references
            
            # Pivot detection via abandonment phrase matching
            pivot_detected = self._detect_abandonment_phrase(utterance_normalized)
            
            # TODO: Access current_episode_context to determine if this is truly
            #       a pivot vs. continuation. Current stub has no context awareness.
            if current_episode_context is not None:
                logger.debug(
                    "current_episode_context provided but not yet used by stub. "
                    "Will be used by real LLM-driven EHG."
                )
            
            # Construct signal
            # Note: confidence_band and pivot_confidence_band are placeholders
            #       Real EHG will provide calibrated confidence scores
            signal = EpisodeHypothesisSignal(
                hypothesis_count=hypothesis_count,
                confidence_band=ConfidenceBand.HIGH,  # TODO: Implement confidence scoring
                pivot_detected=pivot_detected,
                pivot_confidence_band=ConfidenceBand.HIGH  # TODO: Implement pivot confidence
            )
            
            logger.debug(
                f"EHG stub generated signal: "
                f"hypothesis_count={hypothesis_count}, "
                f"pivot_detected={pivot_detected}"
            )
            
            return signal
            
        except Exception as e:
            # Unexpected internal error - log and return safe default
            logger.error(
                f"Unexpected error in generate_hypothesis: {e}",
                exc_info=True
            )
            return self._safe_default_signal()
    
    def _detect_abandonment_phrase(self, utterance_normalized: str) -> bool:
        """
        Detect if utterance contains abandonment phrases suggesting pivot.
        
        Args:
            utterance_normalized: Lowercase, stripped user utterance
            
        Returns:
            True if any abandonment phrase found (case-insensitive substring match)
        
        Notes:
            Simple substring matching - may have false positives.
            E.g., "I don't know" contains "no" and will trigger.
            Real LLM will understand context.
        """
        for phrase in self.ABANDONMENT_PHRASES:
            if phrase in utterance_normalized:
                logger.debug(f"Abandonment phrase detected: '{phrase}'")
                return True
        return False
    
    def _safe_default_signal(self) -> EpisodeHypothesisSignal:
        """
        Return safe default signal for error cases.
        
        Safe default semantics:
            - Single episode (hypothesis_count=1)
            - No pivot detected
            - No ambiguity
            
        This allows conversation to continue safely while logging the error.
        Episode Hypothesis Manager will treat this as "proceed normally".
        
        Returns:
            EpisodeHypothesisSignal with safe conservative defaults
        """
        return EpisodeHypothesisSignal(
            hypothesis_count=1,
            confidence_band=ConfidenceBand.HIGH,
            pivot_detected=False,
            pivot_confidence_band=ConfidenceBand.HIGH
        )