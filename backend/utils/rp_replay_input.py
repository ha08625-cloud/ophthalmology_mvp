"""
RP Replay Input - Boundary object for Response Parser replay

This module defines the data structures that represent the ONLY legal input
for Response Parser replay after clarification resolution.

Design principles:
- Write-once, single-use boundary object
- Authored by Dialogue Manager, consumed by RPReplayAdapter
- Enforces replay invariants at construction time
- No logic, pure data with validation

Key invariants enforced:
- RP never infers episode identity (episode_anchor is explicit)
- RP never decides resolution (resolution_status is authoritative)
- Replay cannot occur when resolution is NEGATED
- episode_id required for CONFIRMED/FORCED status
- applied_policy required (and only allowed) for FORCED status

Flat imports for server testing.
When copying to local, adjust to: from backend.state_manager_v2 import ...
"""

from dataclasses import dataclass, field
from typing import List, Optional

# Flat imports for server testing
# When copying to local, adjust to: from backend.state_manager_v2 import ClarificationResolution
# When copying to local, adjust to: from backend.clarification_templates import ForcedResolutionPolicy
from state_manager_v2 import ClarificationResolution
from clarification_templates import ForcedResolutionPolicy


@dataclass(frozen=True)
class EpisodeAnchor:
    """
    Episode binding for replay extraction.
    
    This is the authoritative episode target. The Response Parser
    cannot override, infer, or modify this binding.
    
    Fields:
        episode_id: Target episode identifier (1-indexed, user-facing).
            Required for CONFIRMED and FORCED status.
            Should be None only for UNRESOLVABLE with ISOLATION_PROTOCOL.
        resolution_status: Outcome of clarification phase.
            NEGATED is illegal for replay (blocked at RPReplayInput construction).
        applied_policy: Forced resolution policy if status is FORCED.
            Required when status is FORCED, must be None otherwise.
    """
    episode_id: Optional[str]
    resolution_status: ClarificationResolution
    applied_policy: Optional[ForcedResolutionPolicy] = None
    
    def __post_init__(self):
        """Validate anchor constraints"""
        # NEGATED should never reach here (blocked at RPReplayInput level)
        # but defend in depth
        if self.resolution_status == ClarificationResolution.NEGATED:
            raise ValueError(
                "EpisodeAnchor cannot have NEGATED resolution_status. "
                "Replay is illegal when hypothesis is negated."
            )
        
        # episode_id required for CONFIRMED and FORCED
        if self.resolution_status in (
            ClarificationResolution.CONFIRMED,
            ClarificationResolution.FORCED
        ):
            if self.episode_id is None:
                raise ValueError(
                    f"episode_id required for resolution_status={self.resolution_status.value}. "
                    f"Cannot replay without explicit episode target."
                )
        
        # applied_policy required for FORCED, forbidden otherwise
        if self.resolution_status == ClarificationResolution.FORCED:
            if self.applied_policy is None:
                raise ValueError(
                    "applied_policy required when resolution_status=FORCED. "
                    "Forced resolution must declare which policy was applied."
                )
        else:
            if self.applied_policy is not None:
                raise ValueError(
                    f"applied_policy must be None for resolution_status={self.resolution_status.value}. "
                    f"Only FORCED resolution can have applied_policy."
                )


@dataclass(frozen=True)
class ReplayTranscriptEntry:
    """
    Single entry in replay transcript.
    
    Represents one (system_prompt, user_response) pair from clarification.
    Only replayable turns should be included.
    
    Fields:
        system_prompt: The rendered question text shown to user
        user_response: The user's verbatim response
    """
    system_prompt: str
    user_response: str
    
    def __post_init__(self):
        """Validate entry fields"""
        if not self.system_prompt or not self.system_prompt.strip():
            raise ValueError("system_prompt cannot be empty")
        if not self.user_response or not self.user_response.strip():
            raise ValueError("user_response cannot be empty")


@dataclass(frozen=True)
class ExtractionDirective:
    """
    Extraction mode flags for replay.
    
    These flags are injected into the RP prompt to constrain extraction behavior.
    The RP does not interpret these flags; they are purely declarative.
    
    Fields:
        mode: Always "REPLAY" for replay extraction
        episode_blind: If True, RP cannot see/reference other episodes
        target_episode_only: If True, RP must extract only for anchored episode
    """
    mode: str = "REPLAY"
    episode_blind: bool = True
    target_episode_only: bool = True
    
    def __post_init__(self):
        """Validate directive constraints"""
        if self.mode != "REPLAY":
            raise ValueError(
                f"ExtractionDirective.mode must be 'REPLAY', got '{self.mode}'"
            )


@dataclass(frozen=True)
class RPReplayInput:
    """
    Boundary object for Response Parser replay.
    
    This is a write-once, single-use object authored by the Dialogue Manager
    and consumed exclusively by RPReplayAdapter.
    
    Construction invariants (fail early):
    - resolution_status cannot be NEGATED (replay illegal for negation)
    - episode_id required for CONFIRMED/FORCED status
    - applied_policy required for FORCED, forbidden otherwise
    - clarification_transcript must not be empty (unless UNRESOLVABLE)
    
    Usage:
        # Dialogue Manager constructs after clarification resolution
        replay_input = RPReplayInput(
            episode_anchor=EpisodeAnchor(
                episode_id="1",
                resolution_status=ClarificationResolution.CONFIRMED,
                applied_policy=None
            ),
            clarification_transcript=[
                ReplayTranscriptEntry(
                    system_prompt="Where was the headache located?",
                    user_response="On the right side"
                )
            ],
            extraction_directive=ExtractionDirective()
        )
        
        # RPReplayAdapter consumes
        result = adapter.run(replay_input)
    
    Fields:
        episode_anchor: Authoritative episode binding
        clarification_transcript: Replayable turns only
        extraction_directive: Extraction mode flags
    """
    episode_anchor: EpisodeAnchor
    clarification_transcript: List[ReplayTranscriptEntry]
    extraction_directive: ExtractionDirective = field(default_factory=ExtractionDirective)
    
    def __post_init__(self):
        """Validate replay input constraints"""
        # Primary guard: NEGATED blocks replay entirely
        if self.episode_anchor.resolution_status == ClarificationResolution.NEGATED:
            raise ValueError(
                "Cannot construct RPReplayInput with NEGATED resolution_status. "
                "Replay is illegal when hypothesis is negated. "
                "System should return to MODE_DISCOVERY without replay."
            )
        
        # Transcript validation
        # Empty transcript is allowed only for UNRESOLVABLE (edge case)
        if not self.clarification_transcript:
            if self.episode_anchor.resolution_status != ClarificationResolution.UNRESOLVABLE:
                raise ValueError(
                    f"clarification_transcript cannot be empty for "
                    f"resolution_status={self.episode_anchor.resolution_status.value}. "
                    f"Replay requires at least one replayable turn."
                )
    
    def get_transcript_text(self) -> str:
        """
        Format transcript as text for prompt injection.
        
        Returns formatted transcript with clear turn boundaries.
        Used by RPReplayAdapter for prompt construction.
        
        Returns:
            str: Formatted transcript text
        """
        if not self.clarification_transcript:
            return "(No replayable turns)"
        
        lines = []
        for i, entry in enumerate(self.clarification_transcript, 1):
            lines.append(f"--- Turn {i} ---")
            lines.append(f"System: {entry.system_prompt}")
            lines.append(f"User: {entry.user_response}")
        
        return "\n".join(lines)


def create_replay_input_from_context(
    episode_id: str,
    resolution_status: ClarificationResolution,
    transcript_entries: List[tuple],
    applied_policy: Optional[ForcedResolutionPolicy] = None
) -> RPReplayInput:
    """
    Factory function to create RPReplayInput from raw data.
    
    Convenience function for Dialogue Manager to construct replay input
    without manually building nested dataclasses.
    
    Args:
        episode_id: Target episode ID (1-indexed string)
        resolution_status: Clarification outcome
        transcript_entries: List of (system_prompt, user_response) tuples
        applied_policy: Forced resolution policy (required if status is FORCED)
        
    Returns:
        RPReplayInput: Validated replay input object
        
    Raises:
        ValueError: If construction invariants are violated
    """
    anchor = EpisodeAnchor(
        episode_id=episode_id,
        resolution_status=resolution_status,
        applied_policy=applied_policy
    )
    
    transcript = [
        ReplayTranscriptEntry(system_prompt=sp, user_response=ur)
        for sp, ur in transcript_entries
    ]
    
    return RPReplayInput(
        episode_anchor=anchor,
        clarification_transcript=transcript,
        extraction_directive=ExtractionDirective()
    )
