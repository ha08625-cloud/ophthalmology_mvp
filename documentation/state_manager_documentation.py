# State Manager V2 Documentation

## Overview
**File:** `state_manager_v2.py`  
**Role:** Multi-episode data storage container  
**Key characteristic:** No business logic - pure data structure

---

## Core Responsibilities
- Stores episodes as array (episode 1, episode 2, etc.)
- Stores shared data separately (demographics, PMH, medications, social history, systems review)
- Tracks operational state per episode (questions_answered, questions_satisfied, follow-up blocks)
- Tracks conversation mode (V3: discovery, clarification, extraction)
- Manages clarification transcript buffer (V3: temporary storage during MODE_CLARIFICATION)
- Tracks field-level provenance (V3: source, confidence, mode for all clinical fields)
- Creates new episodes on demand
- Provides three different data exports with different purposes

---

## Conversation Mode (V3)
- **Field:** `conversation_mode` (ConversationMode enum: MODE_DISCOVERY | MODE_CLARIFICATION | MODE_EPISODE_EXTRACTION)
- **Storage:** Enum stored internally; serialized to string only at JSON boundaries
- **Validation:** Fail-fast on invalid mode via `_validate_conversation_mode()` (accepts both enum and string for migration)
- **Initialization:** New instances default to ConversationMode.MODE_DISCOVERY
- **Persistence:** Serialized to string in `snapshot_state()`, deserialized back to enum by `from_snapshot()`
- **Backwards compatibility:** Old snapshots without mode default to MODE_EPISODE_EXTRACTION
- **Authority:** DialogueManager owns mode transitions; StateManager only validates data integrity

---

## Question Satisfaction Tracking (V4)

### Concept: Question Satisfaction
A question is **satisfied** when we have data for its primary field, regardless of whether we explicitly asked that question.

### Semantic Distinction
- **questions_answered:** We explicitly asked this question (provenance: direct interaction)
- **questions_satisfied:** We have data for this question's intent (may be volunteered or inferred)

### Relationship
```
questions_answered ⊆ questions_satisfied
```
Every answered question is satisfied, but not every satisfied question was answered.

### Storage
Both sets stored per episode in operational fields:
```python
episode = {
    'episode_id': 1,
    'questions_answered': set(),      # Explicitly asked
    'questions_satisfied': set(),     # Data obtained (asked OR volunteered)
    'follow_up_blocks_activated': set(),
    'follow_up_blocks_completed': set(),
    # ... clinical fields ...
}
```

### Use Case
Enables multi-field extraction from single answers:
- User says: "one eye, the right one"
- Parser extracts: `vl_single_eye = "single"` AND `vl_laterality = "right"`
- System marks: `vl_2` answered, `vl_2` and `vl_3` satisfied
- Next question skips laterality question (already satisfied)

### Methods
```python
mark_question_answered(episode_id: int, question_id: str) -> None
# Mark question as explicitly asked
# Updates: questions_answered set

mark_question_satisfied(episode_id: int, question_id: str) -> None
# Mark question as satisfied (data obtained, whether asked or volunteered)
# Updates: questions_satisfied set

get_questions_answered(episode_id: int) -> set[str]
# Returns copy of questions_answered set

get_questions_satisfied(episode_id: int) -> set[str]
# Returns copy of questions_satisfied set
```

### Backward Compatibility
Old snapshots missing `questions_satisfied`:
- Automatically hydrated during `from_snapshot()`
- Rule: `questions_satisfied = questions_answered` for legacy sessions
- Location: Applied in `from_snapshot()` after episode restoration
- Logged at DEBUG level for transparency

---

## Field-Level Provenance (V3)
- **Storage:** Parallel structure in `_provenance` dict (episode and shared_data)
- **Schema:** Each field has provenance record with:
  - `source`: str (response_parser | clarification_parser | forced_resolution | user_explicit | derived | clarification_replay | system | default)
  - `confidence`: str (high | medium | low) - qualitative bands, not calibrated probabilities
  - `mode`: ConversationMode enum (NOT string internally)
- **Semantics:**
  - Last-writer-wins: Each write overwrites provenance completely (no history)
  - Cannot write provenance without value (no separate set_provenance API)
  - Weakest-link for collections: Confidence degrades on update, never improves
- **Collection fields:** medications, allergies, past_medical_history, family_history
- **Default provenance:** Legacy writes without explicit provenance get {source: 'default', confidence: 'low', mode: current_mode}
- **API:** Optional provenance parameter on `set_episode_field()` and `set_shared_field()`

---

## Clarification Context (V3)
- **Field:** `clarification_context` (Optional[ClarificationContext])
- **Lifecycle:** Only exists during MODE_CLARIFICATION; None otherwise
- **Purpose:** Temporary storage for clarification turns before episode resolution
- **Components:**
  - `transcript`: List[ClarificationTurn] - ordered turns with template_id, user_text, replayable flag, rendered_text
  - `entry_count`: int - number of turns (synced with transcript length)
  - `resolution_status`: Optional[ClarificationResolution] - outcome (CONFIRMED|NEGATED|FORCED|UNRESOLVABLE)
- **Persistence:** Included in `snapshot_state()`, restored by `from_snapshot()`
- **Immutability:** ClarificationTurn is frozen dataclass; resolution_status can only be set once

### ClarificationTurn Fields (V3.1)
```python
@dataclass(frozen=True)
class ClarificationTurn:
    template_id: str      # Template ID from clarification_templates.py
    user_text: str        # Raw user response (verbatim)
    replayable: bool      # Whether eligible for RP replay (denormalized from template)
    rendered_text: Optional[str] = None  # V3.1: Actual question text shown to user
```

**rendered_text field (V3.1):**
- Stores the actual question text shown to user (with placeholders filled)
- Required for Response Parser replay after clarification resolution
- Optional for backward compatibility with pre-V3.1 snapshots
- If None, replay adapter will fail loudly if replay is attempted
- Not reconstructed from template_id at deserialization (preserves historical meaning)

### ClarificationTurn Serialization
```python
# to_dict() output
{
    'template_id': 'clarify_location',
    'user_text': 'on the right side',
    'replayable': True,
    'rendered_text': 'Where exactly was the headache located?'
}

# from_dict() backward compatibility
# Old snapshots without rendered_text: field set to None
# Replay adapter validates rendered_text presence when needed
```

---

## Data Exports

### 1. snapshot_state() - Canonical State (Lossless)
- **Purpose:** Persistence between turns
- **Includes:** All episodes (even empty), operational fields (questions_answered, questions_satisfied, follow-up blocks), dialogue history, conversation_mode, clarification_context, **full provenance**
- **Provenance handling:** Enum mode serialized to string for JSON
- **Used by:** Transport layer for state persistence
- **Round-trippable:** Can be used with from_snapshot() to restore exact state

### 2. export_clinical_view() - Clinical Output (Lossy)
- **Purpose:** Final JSON output, UI display
- **Includes:** Non-empty episodes only, shared_data (clinical fields only)
- **Excludes:** Operational fields (questions_answered, questions_satisfied, follow-up blocks), dialogue history, empty episodes, conversation_mode, clarification_context, **provenance (completely stripped)**
- **Used by:** JSON Formatter

### 3. export_for_summary() - Summary Generation Data
- **Purpose:** LLM narrative generation
- **Includes:** All episodes, shared_data, dialogue_history, operational fields (questions_answered, questions_satisfied), **filtered provenance (source + confidence only)**
- **Excludes:** clarification_context, **provenance mode field** (orchestration internal)
- **Provenance filtering:** Enables phrasing like "The patient reports..." vs "It is unclear whether..."
- **Mutation-safe:** Deep-copies before filtering to prevent state corruption
- **Used by:** Summary Generator

---

## Key Methods

### Storage Methods
```python
set_episode_field(episode_id, field_name, value, provenance=None)
# V3: Optional provenance parameter (defaults to {source: 'default', confidence: 'low', mode: current_mode})
# Stores field in specific episode, updates timestamp
# Episode fields do NOT apply weakest-link (not collections)

set_shared_field(field_name, value, provenance=None)
# V3: Optional provenance parameter
# Stores shared field (flat structure only, no dot notation)
# Collection fields (medications, allergies, PMH, family_history) apply weakest-link confidence

add_dialogue_turn(episode_id, question_id, question_text, response, extracted)
# Records turn in dialogue_history

create_episode()
# Creates new episode with auto-incremented ID
# V3: Initializes empty _provenance dict
# V4: Initializes empty questions_satisfied set
# Returns new episode_id
```

### Question Tracking Methods (V4)
```python
mark_question_answered(episode_id, question_id)
# Add question_id to questions_answered set
# Semantic: We explicitly asked this question

mark_question_satisfied(episode_id, question_id)
# Add question_id to questions_satisfied set
# Semantic: We have data for this question's intent (asked OR volunteered)

get_questions_answered(episode_id) -> set
# Returns copy of questions_answered set

get_questions_satisfied(episode_id) -> set
# Returns copy of questions_satisfied set
```

### Clarification Buffer Methods (V3)
```python
init_clarification_context()
# Creates empty buffer on entry to MODE_CLARIFICATION
# Raises RuntimeError if buffer already exists

append_clarification_turn(template_id, user_text, replayable, rendered_text=None)
# Snapshots turn at time of asking (replayable flag denormalized from template)
# V3.1: rendered_text stores actual question shown to user (required for replay)
# Raises RuntimeError if buffer not initialized

get_clarification_transcript() -> List[ClarificationTurn]
# Returns complete transcript (caller filters by replayable if needed)

set_clarification_resolution(resolution: ClarificationResolution)
# Records outcome (can only be set once)

clear_clarification_context()
# Atomic buffer clearing on mode exit (always call, regardless of outcome)
```

### Retrieval Methods
```python
get_episode_for_selector(episode_id) -> dict
# Returns episode data including operational fields (questions_answered, 
# questions_satisfied, follow-up blocks) and full provenance
# Used by Question Selector

from_snapshot(snapshot_dict) -> StateManager
# Class method: rehydrates StateManager from canonical snapshot
# V3: Deserializes provenance (converts mode string back to enum)
# V4: Backward compatibility for questions_satisfied (hydrates from questions_answered if missing)
# Validates conversation_mode (accepts both enum and string for migration)
# Restores clarification_context if present
# Defaults to MODE_EPISODE_EXTRACTION for old snapshots without mode
```

### Provenance Helper Methods (V3, Internal)
```python
_validate_provenance(provenance)
# Validates schema (source, confidence, mode keys)
# Enforces mode is ConversationMode enum (NOT string)

_default_provenance() -> ProvenanceRecord
# Generates default: {source: 'default', confidence: 'low', mode: current_mode}

_apply_weakest_link_confidence(existing, new) -> ProvenanceRecord
# Degrades confidence for collection updates (never improves)

_store_provenance(provenance_dict, field_name, provenance, is_collection)
# Last-writer-wins storage with weakest-link for collections

_serialize_provenance_dict(provenance_dict) -> dict
# Converts enum mode → string for JSON serialization

_deserialize_provenance_dict(provenance_dict) -> dict
# Converts string mode → enum for restoration

_filter_provenance_for_summary(data) -> dict
# Strips mode field, keeps source + confidence
# CRITICAL: Deep-copies input before mutation (prevents state corruption)
```

### Validation Methods
```python
_validate_conversation_mode(mode)
# Fail-fast validation against VALID_MODES
# V3: Accepts both ConversationMode enum and string for migration
# Raises ValueError on invalid mode
# Does NOT derive or repair mode (data integrity only, not business logic)
```

---

## Key Constraints
- Episode IDs are 1-indexed (first episode is episode_id=1)
- Empty episodes are filtered from export_clinical_view() but retained in snapshot_state()
- Timestamps auto-generated (timestamp_started, timestamp_last_updated) in ISO 8601 UTC
- **Operational fields per episode:**
  - `questions_answered`: set[str] - explicitly asked questions
  - `questions_satisfied`: set[str] - questions with data obtained (V4)
  - `follow_up_blocks_activated`: set[str]
  - `follow_up_blocks_completed`: set[str]
  - `_provenance`: dict[str, ProvenanceRecord] (V3)
- Shared data also has _provenance dict (V3)
- Conversation mode stored as ConversationMode enum internally (string only at JSON boundary)
- Provenance mode must be ConversationMode enum (TypeError if string)
- Confidence is qualitative band (high|medium|low), not calibrated probability
- Weakest-link applies only to collection fields (medications, allergies, PMH, family_history)
- Clarification buffer must be initialized before use; cleared on mode exit regardless of outcome
- ClarificationTurn is immutable; resolution_status can only be set once
- **Satisfaction invariant (V4):** questions_answered ⊆ questions_satisfied at all times

---

## Provenance Invariants (V3)
- **No behavior changes:** All existing code works unchanged
- **Backwards compatible:** Legacy calls get default provenance
- **Last-writer-wins:** No provenance history
- **Type safety:** Mode is ALWAYS ConversationMode enum internally
- **Serialization safety:** Mode becomes string only at JSON boundary
- **Mutation safety:** Export methods don't corrupt live state
- **Passive infrastructure:** Provenance fields exist but not yet consumed by logic

---

## Question Satisfaction Invariants (V4)
- **Subset relationship:** questions_answered ⊆ questions_satisfied (always)
- **Backward compatibility:** Old snapshots automatically hydrated (questions_satisfied = questions_answered)
- **No breaking changes:** All existing code works unchanged
- **Separation of concerns:** StateManager stores sets; DialogueManager determines what to mark satisfied
- **Passive infrastructure:** Sets exist but Question Selector consumes them for skip logic

---

## Lifecycle
- Ephemeral instances - new instance created each turn
- Rehydrated from canonical snapshot at turn start via from_snapshot()
- V3: Provenance fully restored with enum mode deserialization
- V4: questions_satisfied backward compatibility applied during from_snapshot()
- Clarification context lifecycle tied to MODE_CLARIFICATION (created on entry, cleared on exit)
- Never stores UI state (turn_count, awaiting_episode_transition, pending_question)

---

## Version History

### V4 (Current) - Question Satisfaction Model
- Added `questions_satisfied` set to episode operational fields
- Added `mark_question_satisfied()` and `get_questions_satisfied()` methods
- Updated `get_episode_for_selector()` to include questions_satisfied
- Added backward compatibility in `from_snapshot()` for old sessions
- Added questions_satisfied to OPERATIONAL_FIELDS
- Updated all data export methods to handle questions_satisfied

### V3.1 - Replay Infrastructure
- Added `rendered_text` field to ClarificationTurn (stores actual question text shown to user)
- Added `ClarificationTurn.from_dict()` class method for backward-compatible deserialization
- Updated `ClarificationContext.from_dict()` to use `ClarificationTurn.from_dict()`
- Backward compatibility: old snapshots without rendered_text deserialize with None value

### V3 - Provenance & Clarification Infrastructure
- Added conversation_mode tracking (discovery, clarification, extraction)
- Added field-level provenance (source, confidence, mode)
- Added clarification context buffer
- Added provenance-aware data exports

### V2 - Multi-episode Foundation
- Episode array storage with 1-indexed IDs
- Shared data separation
- Operational field tracking (questions_answered, follow-up blocks)
- Multiple export formats (snapshot, clinical, summary)

---

**Status:** Passive infrastructure complete. Question satisfaction tracking exists and is consumed by Question Selector V2 for skip logic. Provenance tracking exists but is not yet actively consumed by Response Parser, Clarification Parser, or forced resolution logic. V3.1 replay infrastructure (rendered_text) exists but replay adapter integration pending.
