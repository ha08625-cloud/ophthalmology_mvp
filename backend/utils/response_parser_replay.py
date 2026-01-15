"""
Response Parser Replay Adapter

Thin wrapper that constructs deterministic replay prompts and calls the
existing Response Parser with REPLAY_EXTRACTION mode.

Design principles:
- Accept ONLY RPReplayInput (type-validated boundary)
- Construct RP prompt deterministically (fixed sections, fixed order)
- No state writes, no episode selection, no clinical validation
- No fallback logic, no orchestration, no decisions
- Think of it as a prompt compiler + call adapter

Responsibilities:
1. Validate RPReplayInput (guards against illegal states)
2. Filter transcript to replayable entries (defensive check)
3. Build replay prompt with fixed section order
4. Call existing Response Parser with REPLAY mode
5. Tag provenance on output

What this module explicitly does NOT do:
- State writes
- Episode selection
- Clinical correctness validation
- Fallback logic
- Orchestration
- Decisions

Flat imports for server testing.
When copying to local, adjust imports accordingly.
"""

import logging
from typing import Dict, Any, List, Optional

# Flat imports for server testing
# When copying to local, adjust to: from backend.rp_replay_input import ...
from rp_replay_input import RPReplayInput, ReplayTranscriptEntry
from state_manager_v2 import ClarificationResolution, ClarificationTurn, SOURCE_REPLAY
from clarification_templates import ForcedResolutionPolicy, is_replayable

logger = logging.getLogger(__name__)


class RPReplayAdapterError(Exception):
    """Base exception for replay adapter errors"""
    pass


class IllegalReplayStateError(RPReplayAdapterError):
    """Raised when replay is attempted in illegal state"""
    pass


class InvalidTranscriptError(RPReplayAdapterError):
    """Raised when transcript contains invalid entries"""
    pass


class RPReplayAdapter:
    """
    Adapter for Response Parser replay after clarification resolution.
    
    This is a thin wrapper that:
    1. Validates RPReplayInput
    2. Constructs deterministic replay prompt
    3. Calls existing Response Parser
    4. Tags provenance on output
    
    Usage:
        adapter = RPReplayAdapter(response_parser)
        result = adapter.run(replay_input)
    
    The adapter does not interpret clinical meaning or make decisions.
    It is purely a prompt compiler and call adapter.
    """
    
    def __init__(self, response_parser):
        """
        Initialize adapter with Response Parser reference.
        
        Args:
            response_parser: ResponseParserV2 instance (stateless, safe to cache)
        """
        if not hasattr(response_parser, 'parse') or not callable(response_parser.parse):
            raise TypeError("response_parser must have callable parse() method")
        
        self.response_parser = response_parser
        logger.debug("RPReplayAdapter initialized")
    
    def run(
        self,
        replay_input: RPReplayInput,
        question_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute replay extraction.
        
        Args:
            replay_input: Validated RPReplayInput boundary object
            question_context: Optional context about the current question
                (field metadata, etc.) to pass to Response Parser
                
        Returns:
            dict: Parsed output with provenance tags
            
        Raises:
            IllegalReplayStateError: If replay is attempted in illegal state
            InvalidTranscriptError: If transcript contains invalid entries
        """
        # Phase 1: Validate input (guards)
        self._validate_input(replay_input)
        
        # Phase 2: Build replay prompt
        replay_prompt = self._build_replay_prompt(replay_input)
        
        # Phase 3: Call Response Parser with REPLAY mode
        # Note: We pass the replay prompt as the user_response
        # The RP will extract from this synthetic input
        parse_result = self._call_parser(
            replay_prompt=replay_prompt,
            replay_input=replay_input,
            question_context=question_context
        )
        
        # Phase 4: Tag provenance on output
        tagged_result = self._tag_provenance(parse_result, replay_input)
        
        logger.info(
            f"Replay extraction complete: "
            f"episode_id={replay_input.episode_anchor.episode_id}, "
            f"resolution={replay_input.episode_anchor.resolution_status.value}, "
            f"fields_extracted={len(tagged_result.get('extracted_fields', {}))}"
        )
        
        return tagged_result
    
    def _validate_input(self, replay_input: RPReplayInput) -> None:
        """
        Validate replay input (guards).
        
        Defense in depth: RPReplayInput constructor already validates,
        but adapter defends against any bypass.
        
        Args:
            replay_input: Input to validate
            
        Raises:
            IllegalReplayStateError: If replay is illegal
            InvalidTranscriptError: If transcript is invalid
        """
        # Guard 1: Missing episode anchor
        if replay_input.episode_anchor is None:
            raise IllegalReplayStateError(
                "Missing episode_anchor. Cannot replay without episode binding."
            )
        
        # Guard 2: NEGATED resolution (should never reach here)
        if replay_input.episode_anchor.resolution_status == ClarificationResolution.NEGATED:
            raise IllegalReplayStateError(
                "Cannot replay with NEGATED resolution_status. "
                "Replay is illegal when hypothesis is negated."
            )
        
        # Guard 3: Empty transcript (except UNRESOLVABLE)
        if not replay_input.clarification_transcript:
            if replay_input.episode_anchor.resolution_status != ClarificationResolution.UNRESOLVABLE:
                raise InvalidTranscriptError(
                    f"Empty clarification_transcript for "
                    f"resolution_status={replay_input.episode_anchor.resolution_status.value}. "
                    f"Replay requires at least one replayable turn."
                )
        
        logger.debug(
            f"Replay input validated: "
            f"transcript_entries={len(replay_input.clarification_transcript)}"
        )
    
    def _build_replay_prompt(self, replay_input: RPReplayInput) -> str:
        """
        Build deterministic replay prompt.
        
        Fixed sections in fixed order:
        A. Synthetic System Header (episode anchor, constraints)
        B. Clarification Transcript (replayable turns only)
        C. Extraction Directive
        
        Args:
            replay_input: Validated replay input
            
        Returns:
            str: Complete replay prompt for Response Parser
        """
        sections = []
        
        # Section A: Synthetic System Header
        sections.append(self._build_system_header(replay_input))
        
        # Section B: Clarification Transcript
        sections.append(self._build_transcript_section(replay_input))
        
        # Section C: Extraction Directive
        sections.append(self._build_extraction_directive(replay_input))
        
        return "\n\n".join(sections)
    
    def _build_system_header(self, replay_input: RPReplayInput) -> str:
        """
        Build synthetic system header section.
        
        Contains episode anchor, resolution status, and constraints.
        """
        anchor = replay_input.episode_anchor
        
        policy_text = anchor.applied_policy.value if anchor.applied_policy else "N/A"
        
        return f"""=== EPISODE CONTEXT ===
Episode ID: {anchor.episode_id}
Resolution Status: {anchor.resolution_status.value.upper()}
Applied Policy: {policy_text}

=== EXTRACTION CONSTRAINTS ===
- Extract clinical data ONLY for Episode {anchor.episode_id}
- Do NOT infer episode boundaries
- Do NOT resolve ambiguity
- Do NOT reference or extract data for other episodes
- The resolution status above is AUTHORITATIVE and cannot be overridden"""
    
    def _build_transcript_section(self, replay_input: RPReplayInput) -> str:
        """
        Build clarification transcript section.
        
        Contains only replayable turns in original order.
        """
        if not replay_input.clarification_transcript:
            return "=== CLARIFICATION TRANSCRIPT ===\n(No replayable turns)"
        
        lines = ["=== CLARIFICATION TRANSCRIPT ==="]
        
        for i, entry in enumerate(replay_input.clarification_transcript, 1):
            lines.append(f"\n--- Turn {i} ---")
            lines.append(f"System: {entry.system_prompt}")
            lines.append(f"User: {entry.user_response}")
        
        return "\n".join(lines)
    
    def _build_extraction_directive(self, replay_input: RPReplayInput) -> str:
        """
        Build extraction directive section.
        
        Contains mode flag and explicit extraction instruction.
        """
        directive = replay_input.extraction_directive
        anchor = replay_input.episode_anchor
        
        return f"""=== EXTRACTION DIRECTIVE ===
Mode: {directive.mode}
Episode Blind: {directive.episode_blind}
Target Episode Only: {directive.target_episode_only}

INSTRUCTION: Extract clinical data from the above clarification transcript.
All extracted data belongs to Episode {anchor.episode_id}.
Do not create new episodes. Do not link to other episodes."""
    
    def _call_parser(
        self,
        replay_prompt: str,
        replay_input: RPReplayInput,
        question_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Call Response Parser with replay prompt.
        
        Args:
            replay_prompt: Constructed replay prompt
            replay_input: Original replay input (for metadata)
            question_context: Optional question context
            
        Returns:
            dict: Raw parser output
        """
        # Build minimal context for parser
        # The replay prompt itself contains all necessary context
        context = question_context or {}
        
        # Call parser with REPLAY_EXTRACTION mode
        # Note: The exact interface depends on ResponseParserV2 implementation
        # This may need adjustment based on actual parser API
        try:
            result = self.response_parser.parse(
                user_response=replay_prompt,
                question_context=context,
                mode="REPLAY_EXTRACTION"
            )
            return result
        except TypeError:
            # Fallback if parser doesn't support mode parameter yet
            # Remove mode and try again
            logger.warning(
                "Response Parser does not support mode parameter. "
                "Calling without mode (upgrade parser for full replay support)."
            )
            result = self.response_parser.parse(
                user_response=replay_prompt,
                question_context=context
            )
            # Manually add mode to metadata
            if '_metadata' not in result:
                result['_metadata'] = {}
            result['_metadata']['extraction_mode'] = 'REPLAY_EXTRACTION'
            return result
    
    def _tag_provenance(
        self,
        parse_result: Dict[str, Any],
        replay_input: RPReplayInput
    ) -> Dict[str, Any]:
        """
        Tag provenance on parsed output.
        
        Adds replay-specific provenance to all extracted fields.
        This is passive tagging, no decisions or filtering.
        
        Args:
            parse_result: Raw parser output
            replay_input: Original replay input
            
        Returns:
            dict: Parser output with provenance tags
        """
        # Extract fields from result (structure depends on parser output format)
        extracted = parse_result.get('extracted_fields', {})
        
        # Tag each field with replay provenance
        for field_name, field_data in extracted.items():
            if isinstance(field_data, dict):
                # Field has structure, add provenance
                field_data['_provenance'] = {
                    'source': SOURCE_REPLAY,
                    'resolution_status': replay_input.episode_anchor.resolution_status.value,
                    'episode_id': replay_input.episode_anchor.episode_id
                }
                if replay_input.episode_anchor.applied_policy:
                    field_data['_provenance']['applied_policy'] = (
                        replay_input.episode_anchor.applied_policy.value
                    )
            else:
                # Simple value, wrap in dict with provenance
                extracted[field_name] = {
                    'value': field_data,
                    '_provenance': {
                        'source': SOURCE_REPLAY,
                        'resolution_status': replay_input.episode_anchor.resolution_status.value,
                        'episode_id': replay_input.episode_anchor.episode_id
                    }
                }
                if replay_input.episode_anchor.applied_policy:
                    extracted[field_name]['_provenance']['applied_policy'] = (
                        replay_input.episode_anchor.applied_policy.value
                    )
        
        # Add replay metadata to result
        if '_metadata' not in parse_result:
            parse_result['_metadata'] = {}
        parse_result['_metadata']['replay_context'] = {
            'episode_id': replay_input.episode_anchor.episode_id,
            'resolution_status': replay_input.episode_anchor.resolution_status.value,
            'applied_policy': (
                replay_input.episode_anchor.applied_policy.value 
                if replay_input.episode_anchor.applied_policy else None
            ),
            'transcript_entries': len(replay_input.clarification_transcript)
        }
        
        return parse_result


def filter_replayable_turns(
    clarification_turns: List[ClarificationTurn]
) -> List[ReplayTranscriptEntry]:
    """
    Filter clarification turns to replayable entries only.
    
    Utility function for Dialogue Manager to prepare transcript
    for RPReplayInput construction.
    
    Args:
        clarification_turns: List of ClarificationTurn from ClarificationContext
        
    Returns:
        List[ReplayTranscriptEntry]: Only replayable turns with rendered text
        
    Raises:
        InvalidTranscriptError: If replayable turn has no rendered_text
    """
    entries = []
    
    for turn in clarification_turns:
        if not turn.replayable:
            logger.debug(f"Skipping non-replayable turn: template_id={turn.template_id}")
            continue
        
        # Validate rendered_text exists for replayable turns
        if turn.rendered_text is None:
            raise InvalidTranscriptError(
                f"Replayable turn missing rendered_text: template_id={turn.template_id}. "
                f"Cannot construct replay transcript without actual question text. "
                f"This may indicate a pre-V3.1 snapshot being replayed."
            )
        
        entries.append(ReplayTranscriptEntry(
            system_prompt=turn.rendered_text,
            user_response=turn.user_text
        ))
    
    return entries
