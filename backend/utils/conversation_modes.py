"""
Conversation mode enum for multi-episode dialogue flow.

Invariants:
- Exactly one mode is active per turn
- Mode changes are explicit and authoritative
- MODE_CLARIFICATION cannot be exited implicitly
- MODE_CLARIFICATION is sticky until explicit resolution signal

Design:
- ConversationMode is a string-based enum for JSON serialization
- StateManager validates mode strings against VALID_MODES
- DialogueManager owns all mode transitions
- Episode Hypothesis Generator (EHG) can signal but not change mode
- Episode Hypothesis Management (EHM) signals resolution, DM executes transition
"""

from enum import Enum


class ConversationMode(str, Enum):
    """
    Explicit conversation mode tracking for multi-episode intake.
    
    MODE_DISCOVERY:
        Open-ended questioning, no confirmed episodes yet.
        Episode Hypothesis Generator (EHG) detects potential episodes.
        Question Selector provides non-episode-specific questions.
        
        Entry: Consultation start, or pivot away from active episode
        Exit: EHG signals high-confidence episode â†’ MODE_EPISODE_EXTRACTION
              EHG signals ambiguity â†’ MODE_CLARIFICATION
        
    MODE_CLARIFICATION:
        Active episode disambiguation in progress.
        STICKY: Cannot exit until explicit resolution from EHM.
        Clarification Parser (CP) extracts Mention Objects.
        Episode Hypothesis Management (EHM) signals resolution sufficiency.
        
        Entry: EHG detects episode ambiguity
        Exit: EHM signals RESOLVED â†’ MODE_EPISODE_EXTRACTION
              EHM signals NEGATED â†’ MODE_DISCOVERY
              (Never via implicit recomputation or timeout)
        
    MODE_EPISODE_EXTRACTION:
        Deterministic clinical questioning within confirmed episode.
        Response Parser (RP) commits data to active episode.
        Question Selector provides episode-specific protocol questions.
        
        Entry: Episode confirmed (from discovery or clarification)
        Exit: EHG signals pivot â†’ MODE_DISCOVERY
              EHG signals new ambiguity â†’ MODE_CLARIFICATION
              Episode complete â†’ remains in EXTRACTION for next episode
    """
    MODE_DISCOVERY = "discovery"
    MODE_CLARIFICATION = "clarification"
    MODE_EPISODE_EXTRACTION = "extraction"


# Single source of truth for valid mode strings
# Used by StateManager for validation (fail-fast on corruption)
VALID_MODES = {mode.value for mode in ConversationMode}