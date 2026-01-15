---
created: 2026-01-07T21:25:23+00:00
modified: 2026-01-08T21:31:02+00:00
---

# Modules

# Module Reference

**Version:** 3.0  
**Last Updated:** January 2026

This document provides detailed information about each module in the system. For architectural overview, see `architecture.md`. For data flow patterns, see `data_flow.md`.

## Core Modules

### State Manager (state_manager_v2.py)

**Role:** Multi-episode data storage container  
**Key characteristic:** No business logic - pure data structure

#### Responsibilities
- Stores episodes as array (episode 1, episode 2, etc.)
- Stores shared data separately (demographics, PMH, medications, social history, systems review)
- Tracks operational state per episode (questions_answered, follow-up blocks)
- Tracks conversation mode (V3: discovery, clarification, extraction)
- Manages clarification transcript buffer (V3: temporary storage during MODE_CLARIFICATION)
- Creates new episodes on demand
- Provides three different data exports with different purposes

#### Conversation Mode (V3)
- **Field:** `conversation_mode` (string: "discovery" | "clarification" | "extraction")
- **Validation:** Fail-fast on invalid mode strings via `_validate_conversation_mode()`
- **Initialization:** New instances default to "discovery"
- **Persistence:** Included in `snapshot_state()`, restored by `from_snapshot()`
- **Backwards compatibility:** Old snapshots without mode default to "extraction"
- **Authority:** DialogueManager owns mode transitions; StateManager only validates data integrity

#### Clarification Context (V3)
- **Field:** `clarification_context` (Optional[ClarificationContext])
- **Lifecycle:** Only exists during MODE_CLARIFICATION; None otherwise
- **Purpose:** Temporary storage for clarification turns before episode resolution
- **Components:**
  - `transcript`: List[ClarificationTurn] - ordered turns with template_id, user_text, replayable flag
  - `entry_count`: int - number of turns (synced with transcript length)
  - `resolution_status`: Optional[ClarificationResolution] - outcome (CONFIRMED|NEGATED|FORCED|UNRESOLVABLE)
- **Persistence:** Included in `snapshot_state()`, restored by `from_snapshot()`
- **Immutability:** ClarificationTurn is frozen dataclass; resolution_status can only be set once

#### Data Exports

**1. snapshot_state()** - Canonical state (lossless)
- Purpose: Persistence between turns
- Includes: All episodes (even empty), operational fields, dialogue history, conversation_mode, clarification_context
- Used by: Transport layer for state persistence
- Round-trippable: Can be used with from_snapshot() to restore exact state

**2. export_clinical_view()** - Clinical output (lossy)
- Purpose: Final JSON output, UI display
- Includes: Non-empty episodes only, shared_data (clinical fields only)
- Excludes: Operational fields, dialogue history, empty episodes, conversation_mode, clarification_context
- Used by: JSON Formatter

**3. export_for_summary()** - Summary generation data
- Purpose: LLM narrative generation
- Includes: All episodes, shared_data, dialogue_history, operational fields
- Excludes: clarification_context (not relevant for summaries)
- Used by: Summary Generator

#### Key Methods

**Storage methods:**
```python
set_episode_field(episode_id, field_name, value)
# Stores field in specific episode, updates timestamp

set_shared_field(field_name, value)
# Stores shared field (flat structure only, no dot notation)

add_dialogue_turn(episode_id, question_id, question_text, response, extracted)
# Records turn in dialogue_history

create_episode()
# Creates new episode with auto-incremented ID
# Returns new episode_id
```

**Clarification buffer methods (V3):**
```python
init_clarification_context()
# Creates empty buffer on entry to MODE_CLARIFICATION
# Raises RuntimeError if buffer already exists

append_clarification_turn(template_id, user_text, replayable)
# Snapshots turn at time of asking (replayable flag denormalized from template)
# Raises RuntimeError if buffer not initialized

get_clarification_transcript() -> List[ClarificationTurn]
# Returns complete transcript (caller filters by replayable if needed)

set_clarification_resolution(resolution: ClarificationResolution)
# Records outcome (can only be set once)

clear_clarification_context()
# Atomic buffer clearing on mode exit (always call, regardless of outcome)
```

**Retrieval methods:**
```python
get_episode_for_selector(episode_id) -> dict
# Returns episode data including operational fields
# Used by Question Selector

from_snapshot(snapshot_dict) -> StateManager
# Class method: rehydrates StateManager from canonical snapshot
# Validates conversation_mode, restores clarification_context if present
# Defaults to "extraction" for old snapshots without mode
```

**Validation methods:**
```python
_validate_conversation_mode(mode: str)
# Fail-fast validation against VALID_MODES
# Raises ValueError on invalid mode
# Does NOT derive or repair mode (data integrity only, not business logic)
```

#### Key Constraints
- Episode IDs are 1-indexed (first episode is episode_id=1)
- Empty episodes are filtered from export_clinical_view() but retained in snapshot_state()
- Timestamps auto-generated (timestamp_started, timestamp_last_updated) in ISO 8601 UTC
- Operational fields per episode:
  - questions_answered: set[str]
  - follow_up_blocks_activated: set[str]
  - follow_up_blocks_completed: set[str]
- Conversation mode must be one of: "discovery", "clarification", "extraction"
- Clarification buffer must be initialized before use; cleared on mode exit regardless of outcome
- ClarificationTurn is immutable; resolution_status can only be set once

#### Lifecycle
- Ephemeral instances - new instance created each turn
- Rehydrated from canonical snapshot at turn start via from_snapshot()
- Clarification context lifecycle tied to MODE_CLARIFICATION (created on entry, cleared on exit)
- Never stores UI state (turn_count, awaiting_episode_transition, pending_question)
---

### Question Selector (question_selector_v2.py)

**Role:** Deterministic question selection using DSL evaluation  
**Key characteristic:** Stateless - same input always produces same output

#### Responsibilities
- Evaluates conditions in DSL (domain-specific language) against episode data
- Determines which question to ask next
- Detects when trigger conditions activate follow-up question blocks
- Checks if question blocks are complete
- Returns question dictionary or None when episode complete

#### Input: episode_data dict
Required fields:
```python
{
    'questions_answered': set[str],
    'follow_up_blocks_activated': set[str],
    'follow_up_blocks_completed': set[str],
    # ... all extracted clinical fields for the episode
}
```

#### Output: Methods

**get_next_question(episode_data) -> dict or None**
- Returns next question to ask, or None if episode complete
- Priority order:
  1. Pending follow-up blocks (activated but not completed)
  2. Main sections (if section conditions met)
- Checks questions_answered to avoid repeating questions

**get_next_n_questions(current_question_id, n=3) -> list[dict]**
- Returns the next n questions in sequence after current_question_id
- Used for multi-question metadata window in Response Parser
- Only returns questions from same symptom category (e.g., vl_1 → [vl_2, vl_3, vl_4])
- Ignores conditions - returns questions regardless of conditional logic
- Returns fewer than n questions if near end of category
- Returns empty list if current question is last in category
- Example: `get_next_n_questions('vl_5', n=3)` → `[vl_6, vl_7, vl_8]`

**check_triggers(episode_data) -> set[str]**
- Evaluates all trigger conditions against episode_data
- Returns set of block IDs that should be activated
- Called after each question answered

**is_block_complete(block_id, episode_data) -> bool**
- Checks if all questions in a block have been answered
- Used to mark blocks as completed

#### Key Behavior
- Purely functional: no internal state modified
- Episode-aware: uses episode-specific questions_answered set
- Resets per episode: new episode starts with empty questions_answered
- Configuration loaded from `ruleset_v2.json` at initialization

#### DSL Operators

**Logical:**
- `all`: All conditions must be true
- `any`: At least one condition must be true

**Comparison:**
- `eq`: Equal to
- `ne`: Not equal to
- `gte`: Greater than or equal
- `gt`: Greater than
- `lte`: Less than or equal
- `lt`: Less than

**Boolean:**
- `is_true`: Field value is true
- `is_false`: Field value is false

**Existence:**
- `exists`: Field is present and not None

**String:**
- `contains_lower`: Case-insensitive substring match

#### DSL Example
```json
{
  "sudden_loss_trigger": {
    "all": [
      {"eq": ["vl_onset_timeline", "sudden"]},
      {"is_true": "vl_present"}
    ]
  }
}
```

---

### Response Parser (response_parser_v2.py)

**Role:** Natural language understanding via LLM  
**Key characteristic:** Language task, not medical logic

#### Responsibilities
- Extracts structured clinical fields from patient's natural language response
- Calls HuggingFace LLM to perform extraction
- Maps natural language to standardized values
- Handles ambiguous or unclear responses
- Returns extracted fields with metadata

#### Input
```python
question: dict  # Current question from Question Selector
patient_response: str  # User's text input
turn_id: str  # Turn identifier (e.g., "turn_005")
next_questions: list[dict] | None  # Next 3 questions for metadata window (optional)
symptom_categories: list[str] | None  # Gating question fields (optional)
```

**Multi-question metadata window** (V3 enhancement):
- `next_questions`: Provides context about upcoming questions so parser can extract fields mentioned early
- `symptom_categories`: List of symptom category fields (e.g., ['vl_present', 'cp_present', ...]) extracted from ruleset
- Parser builds extended prompt with metadata for current + next 3 questions + all symptom categories
- Enables extraction of multiple fields from single user response
- Example: User says "right eye, started yesterday" → parser extracts both laterality (current) and onset (upcoming)

#### Output
```python
{
    'outcome': 'EXTRACTED' | 'NO_ANSWER' | 'PARSE_ERROR',
    'fields': {
        'field_name': value,  # May contain multiple fields if mentioned
        # ... additional extracted fields from metadata window
    },
    'parse_metadata': {
        'turn_id': str,
        'question_id': str,
        'timestamp': str,
        'raw_llm_output': str,
        'validation_warnings': list[str]
    }
}
```

**Multi-field extraction:**
- `fields` dict may contain the primary question field plus additional fields from metadata window
- Additional fields extracted only if clearly mentioned by patient
- Validation warnings logged for unexpected fields (but extraction still succeeds)
- All fields undergo type checking and boolean normalization

#### Value Standardization
Uses `field_mappings.py` to map natural language variations to canonical values:
- "right eye" â†’ "monocular_right"
- "both eyes" â†’ "binocular"
- "yes" / "present" / "true" â†’ True
- "no" / "absent" / "false" â†’ False

#### Error Handling
- Best-effort approach: returns empty dict `{}` with _meta if extraction fails
- Logs error but does not raise exception
- Consultation continues even if extraction fails
- Dialogue Manager may re-ask question or move on

#### Version Notes
- V3 implementation with multi-question metadata window (January 2026)
- Supports extraction of multiple fields from single user response
- Backward compatible - works with or without next_questions/symptom_categories parameters
- Uses prompt engineering to guide LLM extraction with extended context

---

### Dialogue Manager (dialogue_manager_v2.py)

**Role:** Orchestrator coordinating all modules  
**Key characteristic:** Stateless per-turn transformation

#### V3 Mode Integration (No Behavior Change)

**Mode Authority:**
- DialogueManager owns all mode transitions via `_determine_next_mode()`
- Currently no-op placeholder - mode never changes (sticky)
- Prepared for future EHG and EHM integration

**Mode Threading:**
- Extracts current mode from state snapshot on each turn
- Calls `_determine_next_mode()` (returns unchanged mode in V3)
- Updates StateManager with next mode
- Tracks mode changes via `turn_metadata['mode_changed']`

**Initialization:**
- New consultations start in `MODE_DISCOVERY` (explicit policy decision)
- StateManager validation ensures mode integrity (fail-fast)

**Guardrails:**
- TypeError raised if current_mode is not ConversationMode enum
- Prevents silent corruption during refactors

#### Responsibilities
- Receives user input and state snapshot
- Rehydrates StateManager from snapshot
- **V3:** Extracts and validates conversation mode, determines next mode
- Calls ResponseParser with multi-question metadata window:
  - Fetches next 3 questions from QuestionSelector
  - Extracts symptom categories from ruleset at initialization
  - Passes extended context to parser for multi-field extraction
- Routes extracted fields using EpisodeClassifier
- Stores fields via StateManager
- Calls QuestionSelector to determine next question
- Handles episode transitions
- Returns TurnResult with both canonical and clinical views
- Generates final outputs (JSON and summary) at consultation end

#### Initialization
- Extracts symptom category fields from `selector.ruleset['sections']['gating_questions']`
- Caches symptom categories as instance variable for all parse calls
- Fails fast with ValueError if:
  - Gating questions section is empty
  - Gating questions have no 'field' attributes
  - Ruleset structure is invalid
- Decouples clinical data from orchestrator - changes to ruleset automatically picked up

#### Core Method

**handle_turn(user_input: str, state_snapshot: dict) -> dict**

Returns TurnResult:
```python
{
    'system_output': str,  # Question text or message
    'state_snapshot': dict,  # Canonical state (for persistence)
    'clinical_output': dict,  # Clinical view (for display)
    'debug': {
        'parser_output': dict,
        'errors': list
    },
    'turn_metadata': {
        'turn_count': int,
        'episode_id': int,
        'consultation_id': str,
        'awaiting_episode_transition': bool,  # UI state
        'pending_question': str,  # UI state
        'conversation_mode': str,  # V3: Current mode
        'mode_changed': bool  # V3: Mode transition flag
    },
    'consultation_complete': bool
}
```

#### Turn Type Detection
1. **first_question:** state_snapshot is None (new consultation)
2. **episode_transition:** awaiting_episode_transition=True in state
3. **regular_turn:** Standard question answering

#### Episode Transitions
- When Question Selector returns None (episode complete)
- Asks: "Do you have another eye problem to discuss?"
- Sets awaiting_episode_transition=True in turn metadata
- Next turn processes transition response
- Uses retry logic (max 2 retries) for ambiguous answers
- Defaults to "no more episodes" if max retries reached

#### Field Routing
For each extracted field:
1. Call EpisodeClassifier.classify_field(field_name)
2. Route based on classification:
   - 'episode' → StateManager.set_episode_field()
   - 'shared' → StateManager.set_shared_field()
   - 'unknown' → Log and quarantine in turn metadata

#### Error Handling
- Best-effort continuation: logs errors, doesn't crash
- Errors accumulated in self.errors list
- Returned in TurnResult.debug
- Consultation continues even with errors

#### State Management
- No consultation state held between turns
- current_episode_id tracked internally during turn processing but not exported
- UI state (turn_count, awaiting_*) stored in turn metadata, not in State Manager
- **V3:** conversation_mode stored in StateManager, threaded through all turn processing
- Explicit parameter passing (no hidden state)

---

### Episode Classifier (episode_classifier.py)

**Role:** Field routing  
**Key characteristic:** Pure function, no dependencies

#### Responsibilities
- Determines if an extracted field belongs to current episode or shared data
- Returns classification string: 'episode' | 'shared' | 'unknown'
- Zero overlap between episode and shared categories

#### Classification Rules

**14 Episode Prefixes:**
- vl_ (visual loss)
- h_ (headache)
- ep_ (eye pain)
- ac_ (appearance changes)
- hc_ (head changes)
- cp_ (cranial palsies)
- vp_ (visual phenomena)
- dp_ (diplopia)
- b1_ through b6_ (follow-up blocks)

**12 Episode Special Cases:**
- visual_loss_present
- agnosia_present
- hallucinations_present
- vertigo_present
- nystagmus_present
- dry_gritty_sensation
- appearance_changes_present
- other_symptoms
- functional_impact
- (plus 3 others)

**8 Shared Fields:**
- additional_episodes_present
- past_medical_history
- medications
- family_history
- allergies
- social_history.* (all nested fields)
- systems_review.* (all nested fields)
- (plus 1 other)

#### Usage
```python
from episode_classifier import classify_field

classification = classify_field('vl_onset_timeline')
# Returns: 'episode'

classification = classify_field('past_medical_history')
# Returns: 'shared'

classification = classify_field('unknown_field')
# Returns: 'unknown'
```

#### Guarantees
- Pure function: same input always produces same output
- No state maintained
- No dependencies on other modules
- No overlaps: field is either episode OR shared, never both

---

### JSON Formatter (json_formatter_v2.py)

**Role:** Serialization to standard medical format  
**Key characteristic:** Output-only, never used for persistence

#### Responsibilities
- Transforms State Manager clinical output to schema-compliant JSON
- Adds metadata (consultation_id, generated_at, total_episodes)
- Validates structure against `json_schema.json`
- Only called once at end of consultation

#### Input
From StateManager.export_clinical_view():
```python
{
    'episodes': [list of episode dicts],
    'shared_data': {shared data dict}
}
```

#### Output
Schema-compliant dict:
```python
{
    'schema_version': '2.1.0',
    'metadata': {
        'consultation_id': str,
        'generated_at': str,  # ISO 8601 UTC
        'total_episodes': int
    },
    'episodes': [
        {
            'episode_id': int,
            'metadata': {
                'timestamp_started': str,
                'timestamp_last_updated': str,
                'completeness_percentage': float
            },
            'presenting_complaint': {...},
            # ... other grouped fields
        }
    ],
    'shared_data': {
        'past_medical_history': [...],
        'medications': [...],
        # ... etc
    },
    'audit_metadata': {}
}
```

#### Validation Strategy
- **Strict:** Required structure must be present (raises ValueError if missing)
- **Permissive:** Extra fields logged but accepted
- No type conversion (State Manager provides correct types)
- No completeness calculation in V2 (removed from formatter)

#### Key Constraints
- NEVER called during turn processing
- NEVER used for persistence or state rehydration
- Only called by DialogueManager.generate_outputs()
- Reads from State Manager, doesn't write back

---

### Summary Generator (summary_generator_v2.py)

**Role:** Clinical narrative generation  
**Key characteristic:** LLM-based text generation

#### Responsibilities
- Generates readable clinical summary from structured data
- Creates one summary per episode
- Lists shared data without narrativizing
- Tracks token usage with warnings
- Combines episode summaries deterministically

#### Input
From StateManager.export_for_summary():
```python
{
    'episodes': [all episodes including empty],
    'shared_data': {...},
    'dialogue_history': {
        'episode_id': [list of turns],
        # ...
    }
}
```

#### Process
1. For each episode:
   - Build prompt with episode data + dialogue history
   - Call HuggingFace LLM
   - Generate narrative summary
   - Track token count

2. Combine summaries:
   - Episode summaries (narrativized)
   - Shared data (listed, not narrativized)
   - Completeness warnings if applicable

3. Save to text file

#### Token Management
- Tracks cumulative context window usage
- Warns at 32k token threshold
- Each episode processed independently to manage context

#### Output Format
```text
EPISODE 1 SUMMARY
[Narrative summary of presenting complaint and history]

EPISODE 2 SUMMARY
[Narrative summary...]

SHARED CLINICAL DATA
Past Medical History:
- [Items listed]

Medications:
- [Items listed]

[etc.]
```

---

## Utility Modules

### Helpers (helpers.py)

**Purpose:** Utility functions for consultation management

**Functions:**

**generate_consultation_id() -> str**
- Creates unique consultation ID for tracking
- Format: Timestamp-based unique identifier
- Used for: File naming, consultation tracking

**generate_consultation_filename(consultation_id: str) -> str**
- Creates timestamped filename from consultation ID
- Format: `consultation_{id}_{timestamp}.json`
- Used for: Saving consultation outputs

**ConsultationValidator class** - Completeness checking
- Validates consultation data structure
- Checks required fields are present
- Used for: Pre-export validation

**Usage:**
```python
from helpers import (
    generate_consultation_id,
    generate_consultation_filename
)

consult_id = generate_consultation_id()
filename = generate_consultation_filename(consult_id)
```

---

### Field Mappings (field_mappings.py)

**Purpose:** Value standardization lookup tables for Response Parser

**Role:** Maps natural language variations to canonical database values

**Mapping Categories:**

**Laterality mappings:**
- "right eye" -> "monocular_right"
- "left eye" -> "monocular_left"  
- "both eyes" -> "binocular"

**Boolean mappings:**
- "yes" / "present" / "true" -> True
- "no" / "absent" / "false" -> False

**Onset mappings:**
- "came on suddenly" / "all of a sudden" -> "sudden"
- "came on gradually" / "slowly got worse" -> "gradual"

**Usage:**
```python
from field_mappings import LATERALITY_MAP, BOOLEAN_MAP

# Standardize user input
raw_value = "right eye"
canonical = LATERALITY_MAP.get(raw_value.lower(), raw_value)
# canonical = "monocular_right"
```

**Design Properties:**
- Case-insensitive matching (all keys lowercase)
- Returns original value if no mapping found
- No side effects, pure lookup
- Used exclusively by Response Parser

**Integration:**
- Used by: Response Parser (value standardization)
- Not used by: Question Selector (uses canonical values only)

---

### Episode Hypothesis Signal (episode_hypothesis_signal.py)

**Purpose:** Structured signal contract between Episode Hypothesis Generator (EHG) and Episode Hypothesis Manager

**Role:** Cross-cutting data structure for episode ambiguity detection and pivot detection

**Components:**

**ConfidenceBand enum** - Confidence levels for probabilistic outputs
- `LOW` - Low confidence in detection
- `MEDIUM` - Medium confidence in detection  
- `HIGH` - High confidence in detection

**EpisodeHypothesisSignal dataclass** - Structured signal with four fields:
```python
@dataclass(frozen=True)
class EpisodeHypothesisSignal:
    hypothesis_count: int           # 0, 1, or >1 episode hypotheses
    confidence_band: ConfidenceBand # Confidence in hypothesis count
    pivot_detected: bool            # Whether user switched episodes
    pivot_confidence_band: ConfidenceBand  # Confidence in pivot
```

**Factory Methods:**
- `no_ambiguity()` - Returns hardcoded "no ambiguity" signal (hypothesis_count=1, high confidence, no pivot)

**Design Properties:**
- Immutable (frozen dataclass)
- Type-safe via enums
- No business logic (pure data structure)
- Ready for future expansion (provenance, calibration metadata)

**Status:** Stub implementation. Real EHG module not yet built.

**Usage Pattern:**
```python
from episode_hypothesis_signal import (
    EpisodeHypothesisSignal,
    ConfidenceBand
)

# EHG would produce:
signal = EpisodeHypothesisSignal(
    hypothesis_count=2,
    confidence_band=ConfidenceBand.HIGH,
    pivot_detected=False,
    pivot_confidence_band=ConfidenceBand.HIGH
)

# Stub usage (current):
signal = EpisodeHypothesisSignal.no_ambiguity()
```

**Integration:**
- Produced by: Episode Hypothesis Generator (future)
- Consumed by: Episode Hypothesis Manager (for mode transition logic)
- Referenced by: DialogueManager (for orchestration)

---

### Conversation Modes (conversation_modes.py)

**Purpose:** Explicit mode tracking for multi-episode intake architecture

**Exports:**
- `ConversationMode` - String-based enum for mode tracking
  - `MODE_DISCOVERY` - Open-ended questioning, no confirmed episodes
  - `MODE_CLARIFICATION` - Active episode disambiguation (sticky until resolved)
  - `MODE_EPISODE_EXTRACTION` - Deterministic clinical questioning
- `VALID_MODES` - Set of valid mode strings for validation

**Key Design Decisions:**
- String-based enum for JSON serialization compatibility
- Single source of truth for valid modes (used by StateManager validation)
- Mode transitions are explicit and authoritative (never implicit recomputation)
- MODE_CLARIFICATION cannot be exited implicitly - requires explicit resolution signal

**Usage:**
```python
from conversation_modes import ConversationMode, VALID_MODES

# Mode assignment
state.conversation_mode = ConversationMode.MODE_CLARIFICATION.value

# Validation
if mode not in VALID_MODES:
    raise ValueError(f"Invalid mode: {mode}")
```

---

### Clarification Templates (clarification_templates.py)

**Purpose:** Template registry for clarification questions with replay policy

**Role:** Defines which clarification questions are eligible for Response Parser replay after episode resolution

**Components:**

**ClarificationTemplateID enum** - Template identifiers
- `CLARIFY_EPISODE_SAME_OR_DIFFERENT` - Episode-structural
- `CLARIFY_TEMPORAL_RELATION` - Episode-structural  
- `CLARIFY_LOCATION` - Clinically referential
- `CLARIFY_LATERALITY` - Clinically referential

**TEMPLATE_METADATA dict** - Maps template_id -> replayable flag
- Episode-structural templates: `replayable=False`
  - Questions about episode identity/relation
  - Example: "Are these the same episode or different?"
  - Not replayed because they don't contain extractable clinical data
- Clinically referential templates: `replayable=True`
  - Questions extracting episode-specific details
  - Example: "Which eye was affected?"
  - Replayed to Response Parser after episode resolution

**Helper Functions:**
```python
is_replayable(template_id: str) -> bool
# Check if template is replayable
# Raises KeyError if template_id not found

validate_template_id(template_id: str) -> None
# Validate template exists in registry
# Raises ValueError if invalid
```

**Key Design Decisions:**
- Replayability is a property of the template, not the turn
- Denormalized into ClarificationTurn at snapshot time for stability
- Template changes don't affect already-recorded turns
- Single source of truth for replay policy

**Usage Pattern:**
```python
from clarification_templates import (
    ClarificationTemplateID,
    TEMPLATE_METADATA,
    is_replayable
)

# Check replayability
template_id = ClarificationTemplateID.CLARIFY_LOCATION
replayable = is_replayable(template_id)  # True

# Snapshot turn with denormalized flag
state.append_clarification_turn(
    template_id=template_id,
    user_text=user_response,
    replayable=replayable  # Captured at time of asking
)
```

**Integration:**
- Used by: DialogueManager (during clarification phase)
- Consumed by: StateManager (for turn snapshotting)
- Referenced by: Episode Hypothesis Manager (for replay construction)

---

### Evidence Validator (evidence_validator.py)

**Purpose:** Safety-critical validation primitive that verifies LLM-generated text spans actually exist in original user input

**Role:** Prevents hallucination-based corruption of clinical data by ensuring extracted evidence is verbatim from user input

**Core Function:**

**validate_evidence_span(span: str, raw_text: str) -> bool**
- Returns `True` if span exists as substring in raw_text
- Returns `False` for all invalid/error cases (never raises exceptions)
- Unicode NFKC normalization + case-insensitive matching (casefold)
- Literal substring matching (punctuation and internal whitespace preserved)
- Leading/trailing whitespace trimmed from span only
- No fuzzy matching, no semantic interpretation

**Usage:**
```python
from evidence_validator import validate_evidence_span

user_input = "I had sudden vision loss in my right eye"
llm_span = "sudden vision loss"

is_valid = validate_evidence_span(llm_span, user_input)
# is_valid = True (span exists in input)

hallucinated_span = "gradual vision loss"
is_valid = validate_evidence_span(hallucinated_span, user_input)
# is_valid = False (span not in input)
```

**Design Principles:**
- Dumb, mechanical, predictable
- Fail safely (return False, never raise)
- Zero dependencies beyond standard library
- No business logic or interpretation

**Integration:**
- Used by: Clarification Parser (future - for Mention Object validation)
- Used by: Any module that needs evidence verification
- Not used by: Response Parser (assumes LLM output is trustworthy within episode)

**Safety Properties:**
- Deterministic fallback for failed validation
- Never allows unverified spans to proceed
- Logging of validation failures for auditing

---

## Configuration Files

### ruleset_v2.json
- Question text
- Field mappings
- DSL conditions
- Trigger conditions
- Defines conversation flow logic
- Loaded by Question Selector at initialization

### json_schema.json (v2.1.0)
- Output structure validation
- Episode array schema
- Shared data structure
- Field types and constraints
- Used by JSON Formatter for validation

### clinical_data_model.json (v2.0.0)
- Initialization templates for shared data
- Defines nested structure for social_history, systems_review
- Empty arrays for PMH/medications/family history
- Loaded by State Manager at initialization

### state_manager_formatter_contract_v1.json
- Frozen interface contract
- Defines StateManager.export_clinical_view() output structure
- Episodes array with metadata
- Shared_data object
- Operational fields explicitly excluded
- See handover document for full specification

---

## Module Dependencies

```
Response Parser      â†’ (no dependencies)
Episode Classifier   â†’ (no dependencies)
State Manager        â†’ clinical_data_model.json
Question Selector    â†’ ruleset_v2.json
JSON Formatter       â†’ json_schema.json, State Manager export
Summary Generator    â†’ State Manager export
Dialogue Manager     â†’ All above modules (orchestrator)
Flask/Console        â†’ Dialogue Manager only
```

**Key insight:** Only Dialogue Manager depends on other modules. All other modules are independent workers with no cross-dependencies.

---

## Critical Contracts

### State Manager â†” JSON Formatter Contract (v1.1.0)

**Top-level structure:**
- `episodes`: array (never dict)
- Episode objects with episode_id (1-indexed)
- Timestamps in ISO 8601 UTC
- `shared_data`: dict with arrays and nested objects

**Guarantees:**
- Episode IDs strictly increasing, contiguous (no gaps in export)
- Operational fields always excluded from export_clinical_view()
- Empty episodes filtered before export
- Timestamps always present and valid

See: `state_manager_formatter_contract_v1.json` for full specification

### Question Selector â†” Ruleset DSL

**DSL Structure:**
- Conditions defined using nested operators
- Triggers map conditions to block activations
- Sections have entry conditions

**Evaluation:**
- Pure function evaluation
- No side effects
- Same episode_data always produces same result

See: `ruleset_v2.json` for full specification

---

## Design Principles Applied to Modules

**Single Responsibility**
- Each module has one clear job
- No overlapping authority between modules

**Stateless Where Possible**
- Question Selector: pure function
- Episode Classifier: pure function
- Response Parser: no consultation state
- Only State Manager holds consultation data

**Explicit Dependencies**
- Modules receive all inputs as parameters
- No hidden state in dictionaries
- Configuration files loaded explicitly

**Best-Effort Continuation**
- Modules log errors but don't crash
- Return error indicators in output
- Allow consultation to continue when possible

**Testability**
- Pure functions easy to test
- Explicit inputs/outputs
- No hidden dependencies
- Stateless modules can be tested in isolation
