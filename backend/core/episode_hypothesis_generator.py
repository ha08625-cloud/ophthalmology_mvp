"""
Episode Hypothesis Generator - LLM-Powered Implementation

Purpose:
    Detect episode multiplicity, pivoting, and ambiguity in user utterances
    using LLM semantic analysis.
    
Responsibilities:
    - Detect potential episode pivots (user switched to different problem)
    - Estimate hypothesis count (how many distinct episodes mentioned)
    - Provide confidence bands for both detections
    
Does NOT:
    - Enumerate specific mentions (that's Clarification Parser's job)
    - Extract clinical data (that's Response Parser's job)
    - Make episode identity decisions (that's Episode Hypothesis Manager's job)
    - Reference concrete episode IDs
    
Design:
    - LLM-powered semantic analysis
    - Compares user utterance against current episode context
    - Returns structured EpisodeHypothesisSignal
    - Fail fast on LLM errors, graceful handling of malformed output
    
Error Handling:
    - LLM call fails (CUDA OOM, timeout) -> raise exception (fail fast)
    - LLM returns invalid JSON -> log warning, return safe default signal
    - LLM returns unexpected values -> coerce to valid values with logging
"""

import json
import logging
from typing import Optional, Dict, Any, List

from hf_client_v2 import HuggingFaceClient
from episode_hypothesis_signal import EpisodeHypothesisSignal, ConfidenceBand

logger = logging.getLogger(__name__)


# Valid confidence band strings (lowercase for matching)
VALID_CONFIDENCE_BANDS = {"low", "medium", "high"}

# Mapping from string to enum
CONFIDENCE_BAND_MAP = {
    "low": ConfidenceBand.LOW,
    "medium": ConfidenceBand.MEDIUM,
    "high": ConfidenceBand.HIGH
}


class EpisodeHypothesisGenerator:
    """
    LLM-powered episode hypothesis generation.
    
    Analyzes user utterances to detect:
    - Multiple episode references (hypothesis_count > 1)
    - Episode pivoting (user switched to different problem)
    
    Uses semantic analysis via LLM rather than keyword matching.
    """
    
    def __init__(
        self,
        hf_client: HuggingFaceClient,
        temperature: float = 0.0,
        max_tokens: int = 128
    ) -> None:
        """
        Initialize EHG with HuggingFace client.
        
        Args:
            hf_client: Initialized HuggingFace client (shared with Response Parser)
            temperature: LLM sampling temperature (default 0.0 for consistency)
            max_tokens: Max tokens to generate (default 128 - output is small JSON)
            
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
            f"EpisodeHypothesisGenerator initialized "
            f"(temp={temperature}, max_tokens={max_tokens})"
        )
    
    def generate_hypothesis(
        self,
        user_utterance: str,
        last_system_question: Optional[str] = None,
        current_episode_context: Optional[Dict[str, Any]] = None
    ) -> EpisodeHypothesisSignal:
        """
        Generate episode hypothesis signal from user utterance.
        
        Args:
            user_utterance: Raw user input text
            last_system_question: The question the system just asked
            current_episode_context: Context about the current episode being discussed.
                Expected structure:
                {
                    "active_symptom_categories": ["visual_loss", "headache", ...]
                }
                
        Returns:
            EpisodeHypothesisSignal with:
                - hypothesis_count: Number of episode hypotheses (0, 1, or >1)
                - confidence_band: Confidence in hypothesis count
                - pivot_detected: Whether user pivoted to different episode
                - pivot_confidence_band: Confidence in pivot detection
                
        Raises:
            RuntimeError: If LLM call fails (CUDA OOM, timeout, etc.)
            
        Note:
            Malformed LLM output is handled gracefully with safe defaults.
        """
        # Handle empty/None input
        if user_utterance is None or not user_utterance.strip():
            logger.debug("Empty user utterance, returning zero-hypothesis signal")
            return EpisodeHypothesisSignal(
                hypothesis_count=0,
                confidence_band=ConfidenceBand.HIGH,
                pivot_detected=False,
                pivot_confidence_band=ConfidenceBand.HIGH
            )
        
        # Build the prompt
        prompt = self._build_prompt(
            user_utterance=user_utterance,
            last_system_question=last_system_question,
            current_episode_context=current_episode_context
        )
        
        # Call LLM - let exceptions propagate (fail fast)
        logger.debug("Calling LLM for episode hypothesis generation")
        try:
            llm_output = self.hf_client.generate_json(
                prompt=prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
        except Exception as e:
            # LLM call failed - fail fast, raise exception
            logger.error(f"EHG LLM call failed: {type(e).__name__} - {e}")
            raise RuntimeError(f"EHG LLM call failed: {e}") from e
        
        logger.debug(f"EHG raw LLM output: {llm_output}")
        
        # Parse and validate LLM output
        signal = self._parse_llm_output(llm_output)
        
        logger.info(
            f"EHG signal: hypothesis_count={signal.hypothesis_count}, "
            f"confidence={signal.confidence_band.value}, "
            f"pivot_detected={signal.pivot_detected}, "
            f"pivot_confidence={signal.pivot_confidence_band.value}"
        )
        
        return signal
    
    def _build_prompt(
        self,
        user_utterance: str,
        last_system_question: Optional[str],
        current_episode_context: Optional[Dict[str, Any]]
    ) -> str:
        """
        Build the LLM prompt for episode hypothesis generation.
        
        Args:
            user_utterance: What the patient said
            last_system_question: What the system asked
            current_episode_context: Context about current episode
            
        Returns:
            Formatted prompt string
        """
        # Build context section
        context_section = ""
        if current_episode_context:
            active_categories = current_episode_context.get("active_symptom_categories", [])
            if active_categories:
                context_section = f"""
Current Episode Context:
The patient is currently being asked about symptoms related to: {', '.join(active_categories)}
"""
            else:
                context_section = """
Current Episode Context:
This is a new episode - no symptom categories have been confirmed yet.
"""
        else:
            context_section = """
Current Episode Context:
No episode context available.
"""
        
        # Build question section
        question_section = ""
        if last_system_question:
            question_section = f"""
Last System Question:
"{last_system_question}"
"""
        
        prompt = f"""You are analyzing a patient's response in an ophthalmology consultation to detect episode ambiguity.

An "episode" is a distinct eye problem or symptom presentation. Patients may:
1. Talk about multiple different eye problems in one response (multiple episodes)
2. Start answering about one problem but then switch to a different problem (pivot)
{context_section}
{question_section}
Patient Response:
"{user_utterance}"

Analyze the patient's response and determine:

1. hypothesis_count: How many distinct eye problems/episodes are mentioned?
   - 0 = No eye problem mentioned (off-topic, greeting, or unclear)
   - 1 = Exactly one eye problem discussed
   - 2 or more = Multiple distinct eye problems mentioned

2. hypothesis_confidence: How confident are you in the hypothesis count?
   - "low" = Very uncertain, ambiguous language
   - "medium" = Somewhat confident but some ambiguity
   - "high" = Very confident in the count

3. pivot_detected: Did the patient start talking about one problem but then switch to a different one mid-response?
   - true = Yes, they pivoted to a different episode
   - false = No pivot detected

4. pivot_confidence: How confident are you in the pivot detection?
   - "low" = Very uncertain
   - "medium" = Somewhat confident
   - "high" = Very confident

Respond with ONLY a JSON object in this exact format:
{{"hypothesis_count": <number>, "hypothesis_confidence": "<low|medium|high>", "pivot_detected": <true|false>, "pivot_confidence": "<low|medium|high>"}}"""

        return prompt
    
    def _parse_llm_output(self, llm_output: str) -> EpisodeHypothesisSignal:
        """
        Parse LLM output into EpisodeHypothesisSignal.
        
        Handles malformed output gracefully by returning safe defaults.
        
        Args:
            llm_output: Raw string output from LLM
            
        Returns:
            EpisodeHypothesisSignal (safe default if parsing fails)
        """
        # Try to parse JSON
        try:
            parsed = json.loads(llm_output)
        except json.JSONDecodeError as e:
            logger.warning(f"EHG: Invalid JSON from LLM: {e}")
            logger.warning(f"EHG: Raw output was: {llm_output[:200]}")
            return self._safe_default_signal()
        
        # Validate and extract fields with coercion
        hypothesis_count = self._extract_hypothesis_count(parsed)
        hypothesis_confidence = self._extract_confidence(
            parsed, "hypothesis_confidence", "hypothesis count"
        )
        pivot_detected = self._extract_pivot_detected(parsed)
        pivot_confidence = self._extract_confidence(
            parsed, "pivot_confidence", "pivot detection"
        )
        
        return EpisodeHypothesisSignal(
            hypothesis_count=hypothesis_count,
            confidence_band=hypothesis_confidence,
            pivot_detected=pivot_detected,
            pivot_confidence_band=pivot_confidence
        )
    
    def _extract_hypothesis_count(self, parsed: Dict[str, Any]) -> int:
        """
        Extract and validate hypothesis_count from parsed JSON.
        
        Args:
            parsed: Parsed JSON dict
            
        Returns:
            int: Valid hypothesis count (0, 1, or clamped to 2 for >1)
        """
        raw_value = parsed.get("hypothesis_count")
        
        if raw_value is None:
            logger.warning("EHG: Missing hypothesis_count, defaulting to 1")
            return 1
        
        # Try to convert to int
        try:
            count = int(raw_value)
        except (ValueError, TypeError):
            logger.warning(
                f"EHG: Invalid hypothesis_count '{raw_value}', defaulting to 1"
            )
            return 1
        
        # Validate range
        if count < 0:
            logger.warning(f"EHG: Negative hypothesis_count {count}, clamping to 0")
            return 0
        
        # Cap at 2 for simplicity (>1 is what matters)
        if count > 2:
            logger.debug(f"EHG: hypothesis_count {count} capped to 2 (>1 indicator)")
            return 2
        
        return count
    
    def _extract_confidence(
        self,
        parsed: Dict[str, Any],
        field_name: str,
        description: str
    ) -> ConfidenceBand:
        """
        Extract and validate confidence band from parsed JSON.
        
        Args:
            parsed: Parsed JSON dict
            field_name: Key to extract (e.g., "hypothesis_confidence")
            description: Human-readable description for logging
            
        Returns:
            ConfidenceBand enum value
        """
        raw_value = parsed.get(field_name)
        
        if raw_value is None:
            logger.warning(f"EHG: Missing {field_name}, defaulting to HIGH")
            return ConfidenceBand.HIGH
        
        # Normalize to lowercase string
        if not isinstance(raw_value, str):
            raw_value = str(raw_value)
        
        normalized = raw_value.lower().strip()
        
        if normalized in VALID_CONFIDENCE_BANDS:
            return CONFIDENCE_BAND_MAP[normalized]
        else:
            logger.warning(
                f"EHG: Invalid {field_name} '{raw_value}' for {description}, "
                f"defaulting to HIGH"
            )
            return ConfidenceBand.HIGH
    
    def _extract_pivot_detected(self, parsed: Dict[str, Any]) -> bool:
        """
        Extract and validate pivot_detected from parsed JSON.
        
        Args:
            parsed: Parsed JSON dict
            
        Returns:
            bool: Whether pivot was detected
        """
        raw_value = parsed.get("pivot_detected")
        
        if raw_value is None:
            logger.warning("EHG: Missing pivot_detected, defaulting to False")
            return False
        
        # Handle various boolean representations
        if isinstance(raw_value, bool):
            return raw_value
        
        if isinstance(raw_value, str):
            normalized = raw_value.lower().strip()
            if normalized in {"true", "yes", "1"}:
                return True
            elif normalized in {"false", "no", "0"}:
                return False
            else:
                logger.warning(
                    f"EHG: Invalid pivot_detected string '{raw_value}', "
                    f"defaulting to False"
                )
                return False
        
        # Try truthiness for other types
        logger.warning(
            f"EHG: Unexpected pivot_detected type {type(raw_value)}, "
            f"using truthiness"
        )
        return bool(raw_value)
    
    def _safe_default_signal(self) -> EpisodeHypothesisSignal:
        """
        Return safe default signal for error cases.
        
        Safe default semantics:
            - Single episode (hypothesis_count=1)
            - No pivot detected
            - High confidence (conservative - allows extraction to proceed)
            
        This allows conversation to continue safely while logging the error.
        
        Returns:
            EpisodeHypothesisSignal with safe conservative defaults
        """
        logger.warning("EHG: Returning safe default signal due to parse error")
        return EpisodeHypothesisSignal(
            hypothesis_count=1,
            confidence_band=ConfidenceBand.HIGH,
            pivot_detected=False,
            pivot_confidence_band=ConfidenceBand.HIGH
        )
