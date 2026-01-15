# Module Reference

This document provides signposting or detailed information about each module in the system. For architectural overview, see `architecture.md`. For data flow patterns, see `data_flow.md`.

## Core Modules have their own individual documentation which can be found in the project files:
state_manager_documentation.md
dialogue_manager_documentation.md
response_parser_documentation.md
question_selector_documentation.md
JSON_formatter_documentation.md
summary_generator_documentation.md

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

**Purpose:** Template registry for clarification questions with replay policy and forced resolution policies

**Role:** Defines which clarification questions are eligible for Response Parser replay after episode resolution, provides template text patterns, and declares forced resolution policy options

**Components:**

**ClarificationTemplateID enum** - Template identifiers
- `CLARIFY_EPISODE_SAME_OR_DIFFERENT` - Episode-structural
- `CLARIFY_TEMPORAL_RELATION` - Episode-structural  
- `CLARIFY_LOCATION` - Clinically referential
- `CLARIFY_LATERALITY` - Clinically referential

**ForcedResolutionPolicy enum** - Policies for forced resolution (V3.1)
- `SEPARATION_PROTOCOL` - Treat input as new, distinct episode
- `CONTINUITY_PROTOCOL` - Merge input into existing active episode
- `ISOLATION_PROTOCOL` - Extract data into Limbo episode with low confidence

**TEMPLATE_METADATA dict** - Maps template_id -> replayable flag
- Episode-structural templates: `replayable=False`
  - Questions about episode identity/relation
  - Example: "Are these the same episode or different?"
  - Not replayed because they don't contain extractable clinical data
- Clinically referential templates: `replayable=True`
  - Questions extracting episode-specific details
  - Example: "Which eye was affected?"
  - Replayed to Response Parser after episode resolution

**TEMPLATE_TEXT dict** - Maps template_id -> question pattern with placeholders (V3.1)
- Placeholders use `{placeholder_name}` format
- Rendered text (with placeholders filled) stored in `ClarificationTurn.rendered_text`
- Replay adapter uses rendered_text, not template patterns

**Helper Functions:**
```python
is_replayable(template_id: str) -> bool
# Check if template is replayable
# Raises KeyError if template_id not found

get_template_text(template_id: str) -> str
# Get template text pattern for a template ID
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
- ForcedResolutionPolicy values injected verbatim into RP prompts (no interpretation)

**Usage Pattern:**
```python
from clarification_templates import (
    ClarificationTemplateID,
    ForcedResolutionPolicy,
    TEMPLATE_METADATA,
    TEMPLATE_TEXT,
    is_replayable,
    get_template_text
)

# Check replayability
template_id = ClarificationTemplateID.CLARIFY_LOCATION
replayable = is_replayable(template_id)  # True

# Get template text and render
pattern = get_template_text(template_id)
rendered = pattern.format(mention_1="the headache")

# Snapshot turn with denormalized flag and rendered text
state.append_clarification_turn(
    template_id=template_id,
    user_text=user_response,
    replayable=replayable,
    rendered_text=rendered
)
```

**Integration:**
- Used by: DialogueManager (during clarification phase)
- Consumed by: StateManager (for turn snapshotting)
- Referenced by: RPReplayAdapter (for prompt construction)
- Referenced by: Episode Hypothesis Manager (for replay construction)

---

### RP Replay Input (rp_replay_input.py)

**Purpose:** Boundary object for Response Parser replay after clarification resolution

**Role:** Defines the ONLY legal input structure for RP replay, enforcing replay invariants at construction time

**Components:**

**EpisodeAnchor dataclass** - Authoritative episode binding for replay
```python
@dataclass(frozen=True)
class EpisodeAnchor:
    episode_id: Optional[str]           # Target episode (1-indexed)
    resolution_status: ClarificationResolution  # CONFIRMED/FORCED/UNRESOLVABLE
    applied_policy: Optional[ForcedResolutionPolicy]  # Required for FORCED
```

**ReplayTranscriptEntry dataclass** - Single (system_prompt, user_response) pair
```python
@dataclass(frozen=True)
class ReplayTranscriptEntry:
    system_prompt: str   # Rendered question text shown to user
    user_response: str   # User's verbatim response
```

**ExtractionDirective dataclass** - Extraction mode flags
```python
@dataclass(frozen=True)
class ExtractionDirective:
    mode: str = "REPLAY"
    episode_blind: bool = True
    target_episode_only: bool = True
```

**RPReplayInput dataclass** - Complete replay boundary object
```python
@dataclass(frozen=True)
class RPReplayInput:
    episode_anchor: EpisodeAnchor
    clarification_transcript: List[ReplayTranscriptEntry]
    extraction_directive: ExtractionDirective
```

**Factory Function:**
```python
create_replay_input_from_context(
    episode_id: str,
    resolution_status: ClarificationResolution,
    transcript_entries: List[tuple],
    applied_policy: Optional[ForcedResolutionPolicy] = None
) -> RPReplayInput
```

**Construction Invariants (fail early):**
- `resolution_status` cannot be `NEGATED` (replay illegal for negation)
- `episode_id` required for `CONFIRMED` and `FORCED` status
- `applied_policy` required for `FORCED`, forbidden otherwise
- `clarification_transcript` cannot be empty (except `UNRESOLVABLE`)

**Key Design Decisions:**
- Write-once, single-use boundary object
- Authored by Dialogue Manager, consumed by RPReplayAdapter
- Immutable (frozen dataclasses)
- Validation at construction prevents illegal states reaching adapter
- RP never infers episode identity (anchor is authoritative)

**Usage Pattern:**
```python
from rp_replay_input import (
    RPReplayInput,
    EpisodeAnchor,
    ReplayTranscriptEntry,
    ExtractionDirective,
    create_replay_input_from_context
)
from state_manager_v2 import ClarificationResolution

# Construct via factory (simpler)
replay_input = create_replay_input_from_context(
    episode_id="1",
    resolution_status=ClarificationResolution.CONFIRMED,
    transcript_entries=[
        ("Where was the headache?", "On the right side")
    ]
)

# Or construct directly
replay_input = RPReplayInput(
    episode_anchor=EpisodeAnchor(
        episode_id="1",
        resolution_status=ClarificationResolution.CONFIRMED,
        applied_policy=None
    ),
    clarification_transcript=[
        ReplayTranscriptEntry(
            system_prompt="Where was the headache?",
            user_response="On the right side"
        )
    ],
    extraction_directive=ExtractionDirective()
)

# Get formatted transcript for debugging
print(replay_input.get_transcript_text())
```

**Integration:**
- Produced by: Dialogue Manager (on clarification exit)
- Consumed by: RPReplayAdapter (exclusively)
- Depends on: ClarificationResolution (from state_manager_v2), ForcedResolutionPolicy (from clarification_templates)

---

### Response Parser Replay Adapter (response_parser_replay.py)

**Purpose:** Thin wrapper that constructs deterministic replay prompts and calls Response Parser

**Role:** Isolates replay semantics from Dialogue Manager and Response Parser, acts as prompt compiler + call adapter

**Components:**

**Exception Classes:**
- `RPReplayAdapterError` - Base exception for adapter errors
- `IllegalReplayStateError` - Raised when replay attempted in illegal state
- `InvalidTranscriptError` - Raised when transcript contains invalid entries

**RPReplayAdapter class** - Main adapter
```python
class RPReplayAdapter:
    def __init__(self, response_parser):
        """Initialize with Response Parser reference"""
    
    def run(self, replay_input: RPReplayInput, 
            question_context: Optional[Dict] = None) -> Dict[str, Any]:
        """Execute replay extraction"""
```

**Prompt Assembly (fixed sections, fixed order):**

Section A: Synthetic System Header
- Episode anchor (ID, resolution status, applied policy)
- Extraction constraints (no cross-episode inference, no ambiguity resolution)

Section B: Clarification Transcript
- Replayable turns only, in original order
- Format: `System: {rendered_text}` / `User: {response}`

Section C: Extraction Directive
- Mode flag, episode binding, explicit instruction

**Helper Function:**
```python
filter_replayable_turns(
    clarification_turns: List[ClarificationTurn]
) -> List[ReplayTranscriptEntry]
# Filters to replayable turns, validates rendered_text exists
# Raises InvalidTranscriptError if replayable turn missing rendered_text
```

**What the adapter explicitly does NOT do:**
- State writes
- Episode selection
- Clinical correctness validation
- Fallback logic
- Orchestration
- Decisions

**Guard Checks:**
- Missing episode anchor raises `IllegalReplayStateError`
- NEGATED resolution raises `IllegalReplayStateError`
- Empty transcript (except UNRESOLVABLE) raises `InvalidTranscriptError`

**Provenance Tagging:**
- All extracted fields tagged with `source: 'clarification_replay'`
- Resolution status and applied policy included in provenance
- Metadata includes replay context (episode_id, transcript entry count)

**Usage Pattern:**
```python
from response_parser_replay import RPReplayAdapter, filter_replayable_turns
from rp_replay_input import create_replay_input_from_context

# Initialize adapter
adapter = RPReplayAdapter(response_parser)

# Prepare transcript from ClarificationContext
replayable_entries = filter_replayable_turns(
    clarification_context.transcript
)

# Create replay input
replay_input = create_replay_input_from_context(
    episode_id="1",
    resolution_status=ClarificationResolution.CONFIRMED,
    transcript_entries=[
        (entry.system_prompt, entry.user_response)
        for entry in replayable_entries
    ]
)

# Execute replay
result = adapter.run(replay_input)
# result contains extracted fields with replay provenance
```

**Integration:**
- Depends on: RPReplayInput, Response Parser, ClarificationTurn
- Called by: Dialogue Manager (on clarification exit, replacing direct RP call)
- Calls: Response Parser with REPLAY_EXTRACTION mode

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
State Manager        â†’ clinical_data_model.json, conversation_modes.py
Question Selector    â†’ ruleset_v2.json
JSON Formatter       â†’ json_schema.json, State Manager export
Summary Generator    â†’ State Manager export
RP Replay Input      â†’ state_manager_v2 (ClarificationResolution), clarification_templates (ForcedResolutionPolicy)
RP Replay Adapter    â†’ rp_replay_input, Response Parser, state_manager_v2
Dialogue Manager     â†’ All above modules (orchestrator)
Flask/Console        â†’ Dialogue Manager only
```

**Key insight:** Only Dialogue Manager depends on other modules. All other modules are independent workers with no cross-dependencies. The RP Replay Adapter is a thin boundary layer that depends on RP Replay Input and Response Parser but makes no decisions.

---

## Critical Contracts

### State Manager â†’ JSON Formatter Contract (v1.1.0)

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

### Question Selector â†’ Ruleset DSL

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
