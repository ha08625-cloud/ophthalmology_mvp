"""
Episode Narrowing (Coercion) Prompt Generator

Purpose:
    When episode ambiguity is detected, this module generates prompts that
    coerce the conversation back to the current episode without attempting
    resolution or clarification.
    
    This is a conversation control move, not clarification, not extraction.
    
Design:
    - Deterministic: exactly one string per status
    - No randomization, no templates, no configuration
    - Two variants only: AMBIGUOUS_MULTIPLE and AMBIGUOUS_PIVOT
    - Fails fast on SAFE_TO_EXTRACT (caller error)
    
Integration:
    DialogueManager checks EpisodeSafetyStatus before committing RP output.
    If unsafe, DialogueManager:
        1. Calls build_episode_narrowing_prompt(status)
        2. Appends the next question
        3. Discards RP output
        4. Stays in MODE_EPISODE_EXTRACTION
        
Semantic content rules:
    - Acknowledge confusion (system-side)
    - State why (multiple problems vs change of topic)
    - Assert constraint ("I'm going to stick to X")
    - Must NOT:
        - Ask user to resolve ambiguity
        - Mention episodes explicitly
        - Introduce new clinical concepts
        - Reference "earlier" or "another" episode in detail
        - Invite freeform explanation
        
This is coercion, not negotiation.

Future expansion:
    When upgraded to 70B model with proper clarification mode, this module
    will expand to support actual episode resolution prompts.
"""

from episode_safety_status import EpisodeSafetyStatus


def build_episode_narrowing_prompt(status: EpisodeSafetyStatus) -> str:
    """
    Generate a coercion prompt for detected episode ambiguity.
    
    This function is called ONLY when:
        - ConversationMode == MODE_EPISODE_EXTRACTION
        - EpisodeSafetyStatus ∈ {AMBIGUOUS_MULTIPLE, AMBIGUOUS_PIVOT}
        
    Never called:
        - In MODE_DISCOVERY
        - During clarification mode
        - When SAFE_TO_EXTRACT
        
    Args:
        status: Must be AMBIGUOUS_MULTIPLE or AMBIGUOUS_PIVOT
        
    Returns:
        str: Complete coercion prompt (without the follow-up question)
        
    Raises:
        ValueError: If status is SAFE_TO_EXTRACT (caller error - fail fast)
        
    Design:
        - Exactly one literal string per status
        - No placeholders left unresolved
        - No randomization
        - No template registry
        - No external configuration
        
    Semantic structure:
        1. Acknowledgment: "Thank you"
        2. Detection statement: "It sounds like..."
        3. Constraint assertion: "I'm going to focus on..."
        
    Examples:
        >>> build_episode_narrowing_prompt(EpisodeSafetyStatus.AMBIGUOUS_MULTIPLE)
        "Thank you — it sounds like your last answer may have mentioned more than one problem.\\nTo avoid mixing things up, I'm going to focus on the current problem for now."
        
        >>> build_episode_narrowing_prompt(EpisodeSafetyStatus.AMBIGUOUS_PIVOT)
        "Thank you — it sounds like your last answer may have mentioned a different problem.\\nTo avoid mixing things up, I'm going to focus on the current problem for now."
        
        >>> build_episode_narrowing_prompt(EpisodeSafetyStatus.SAFE_TO_EXTRACT)
        Traceback (most recent call last):
            ...
        ValueError: build_episode_narrowing_prompt called with SAFE_TO_EXTRACT - this is a caller error
    """
    # Fail fast on caller error - this function should never be called when safe
    if status == EpisodeSafetyStatus.SAFE_TO_EXTRACT:
        raise ValueError(
            "build_episode_narrowing_prompt called with SAFE_TO_EXTRACT - "
            "this is a caller error"
        )
    
    # Variant 1: User appears to describe multiple problems simultaneously
    if status == EpisodeSafetyStatus.AMBIGUOUS_MULTIPLE:
        return (
            "Thank you — it sounds like your last answer may have mentioned more than one problem.\n"
            "To avoid mixing things up, I'm going to focus on the current problem for now."
        )
    
    # Variant 2: User appears to have changed topic mid-conversation
    if status == EpisodeSafetyStatus.AMBIGUOUS_PIVOT:
        return (
            "Thank you — it sounds like your last answer may have mentioned a different problem.\n"
            "To avoid mixing things up, I'm going to focus on the current problem for now."
        )
    
    # This should be unreachable given enum exhaustiveness, but fail fast anyway
    raise ValueError(f"Unexpected EpisodeSafetyStatus: {status}")
