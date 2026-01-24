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

1. helpers.py
2. field_mappings.py
3. episode_hypothesis_signal.py
4. conversation_modes.py
5. clarification_templates.py
6. episode_hypothesis_generator.py
7. episode_safety_status.py
8. prompt_builder.py
9. hf_client_v2.py
10. episode_narrowing_prompt.py

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

# Signal interpreted by episode_safety_status.py to output AMBIGUOUS_MULTIPLE, AMBIGUOUS_PIVOT or SAFE_TO_EXTRACT
```

**Integration:**
- Produced by: Episode Hypothesis Generator
- Consumed by: Episode Safety Status
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

### Episode Hypothesis Generator (episode_hypothesis_generator.py)

**Purpose:** Detect episode multiplicity and pivoting in user utterances using LLM semantic analysis

**Role:** Analyzes patient responses to detect when multiple distinct eye problems are mentioned or when the patient pivots away from the current episode. Outputs structured signals consumed by Episode Safety Status for commit gating.

**Constructor:**
```python
def __init__(
    self,
    hf_client: HuggingFaceClient,
    temperature: float = 0.0,
    max_tokens: int = 128
)
```
- Takes shared HuggingFaceClient instance (same as ResponseParser)
- Duck typing validation (checks for `generate_json` and `is_loaded` methods)
- Raises `TypeError` if client interface invalid
- Raises `RuntimeError` if model not loaded

**Primary Method:**
```python
def generate_hypothesis(
    self,
    user_utterance: str,
    last_system_question: Optional[str] = None,
    current_episode_context: Optional[Dict[str, Any]] = None
) -> EpisodeHypothesisSignal
```

**Parameters:**
- `user_utterance`: Raw patient response text
- `last_system_question`: The question the system just asked (provides context for pivot detection)
- `current_episode_context`: Context about current episode for comparison
  ```python
  {
      "active_symptom_categories": ["vl", "cp", ...]  # Symptom prefixes with data
  }
  ```

**Returns:** `EpisodeHypothesisSignal` dataclass with:
- `hypothesis_count`: Number of distinct episodes detected (0, 1, or 2+)
- `confidence_band`: Confidence in hypothesis count (LOW/MEDIUM/HIGH)
- `pivot_detected`: Whether patient switched to different episode
- `pivot_confidence_band`: Confidence in pivot detection (LOW/MEDIUM/HIGH)

**Prompt Design:**
- Includes last system question for context
- Includes active symptom categories from current episode
- Requests JSON output with four fields
- Instructs LLM on episode semantics (distinct problems vs continuation)

**Error Handling:**

| Scenario | Behaviour |
|----------|-----------|
| Empty/None utterance | Returns `hypothesis_count=0`, no LLM call |
| LLM call fails (CUDA OOM, timeout) | Raises `RuntimeError` (fail fast) |
| LLM returns invalid JSON | Logs warning, returns safe default signal |
| Missing fields in JSON | Uses defaults (count=1, pivot=False, confidence=HIGH) |
| Negative hypothesis_count | Clamped to 0 |
| hypothesis_count > 2 | Capped to 2 (>1 is what matters) |

**Safe Default Signal:**
```python
EpisodeHypothesisSignal(
    hypothesis_count=1,
    confidence_band=ConfidenceBand.HIGH,
    pivot_detected=False,
    pivot_confidence_band=ConfidenceBand.HIGH
)
```
Allows extraction to proceed safely when parsing fails.

**Key Design Decisions:**
- Fail fast on LLM infrastructure errors (system problem, not patient input)
- Graceful handling of malformed LLM output (small models produce garbage occasionally)
- hypothesis_count capped at 2 because >1 triggers the same safety response
- Confidence bands passed through to signal even though Episode Safety Status currently ignores them (future use)

**Usage Pattern:**
```python
from episode_hypothesis_generator import EpisodeHypothesisGenerator
from hf_client_v2 import HuggingFaceClient

# Initialize (once at startup)
hf_client = HuggingFaceClient("mistralai/Mistral-7B-Instruct-v0.2", load_in_4bit=True)
ehg = EpisodeHypothesisGenerator(hf_client)

# Per-turn usage
signal = ehg.generate_hypothesis(
    user_utterance="Actually, I also have headaches with flashing lights",
    last_system_question="How long has your vision been blurry?",
    current_episode_context={"active_symptom_categories": ["vl"]}
)

# Signal consumed by Episode Safety Status
from episode_safety_status import assess_episode_safety
safety = assess_episode_safety(signal)  # SAFE_TO_EXTRACT | AMBIGUOUS_MULTIPLE | AMBIGUOUS_PIVOT
```

**Integration:**
- Instantiated by: Flask app (app.py) during startup
- Injected into: DialogueManager constructor
- Called by: DialogueManager._process_regular_turn()
- Context built by: DialogueManager._build_episode_context_for_ehg()
- Output consumed by: episode_safety_status.assess_episode_safety()
- Shares HuggingFaceClient with: ResponseParser, SummaryGenerator

---

### Episode Safety Status (episode_safety_status.py)

**Purpose:** Deterministic safety assessment from probabilistic Episode Hypothesis Generator signals

**Role:** Provides the sole boundary between probabilistic inference (EHG) and deterministic control flow (Dialogue Manager). Collapses probabilistic EpisodeHypothesisSignal into a finite safety decision that gates whether Response Parser output can be committed to state.

**Enum: EpisodeSafetyStatus**

Three mutually exclusive outcomes:
- `SAFE_TO_EXTRACT`: Single episode hypothesis, no pivot detected → safe to commit RP output
- `AMBIGUOUS_MULTIPLE`: Multiple episode hypotheses detected → clarification/coercion required
- `AMBIGUOUS_PIVOT`: Single hypothesis but pivot detected → clarification/coercion required

**Primary Function:**
```python
def assess_episode_safety(
    signal: EpisodeHypothesisSignal
) -> EpisodeSafetyStatus
```

**Parameters:**
- `signal`: EpisodeHypothesisSignal from Episode Hypothesis Generator containing:
  - `hypothesis_count`: Number of episodes detected (0, 1, or 2+)
  - `confidence_band`: Confidence level (LOW/MEDIUM/HIGH)
  - `pivot_detected`: Boolean indicating potential episode switch
  - `pivot_confidence_band`: Confidence in pivot detection

**Returns:** `EpisodeSafetyStatus` enum value

**Precedence Rules (applied in order):**
1. If `hypothesis_count > 1` → `AMBIGUOUS_MULTIPLE`
2. If `pivot_detected == True` → `AMBIGUOUS_PIVOT`
3. Otherwise → `SAFE_TO_EXTRACT`

**Key Design Decisions:**
- **Pure function**: No side effects, no logging, no state modification
- **Total function**: Always returns valid enum value, never raises exceptions
- **Deterministic**: Same input always produces same output
- **Conservative by design**: Confidence bands intentionally ignored
  - Better false positives (unnecessary clarification) than false negatives (clinical corruption)
  - Safety assessment gates clinical data commits, so err on side of caution
- **Closed set**: Only three outcomes, no future expansion without explicit architectural decision
- **Scope limited**: Does NOT decide episode identity, resolve ambiguity, ask questions, transition modes, or write state

**Edge Cases:**

| Scenario | Behaviour | Rationale |
|----------|-----------|-----------|
| `hypothesis_count = 0` | Returns `SAFE_TO_EXTRACT` | Known limitation - treated as safe to avoid blocking conversation on off-topic input. Will be addressed with better hardware/models. |
| `hypothesis_count = 100` | Returns `AMBIGUOUS_MULTIPLE` | Any count >1 triggers same safety response |
| Both `hypothesis_count > 1` AND `pivot_detected = True` | Returns `AMBIGUOUS_MULTIPLE` | Multiple hypotheses takes precedence (established hierarchy) |
| Low confidence but valid structure | Ignores confidence, applies rules | Conservative - trust structural signal over confidence calibration |

**Usage Pattern:**
```python
from episode_hypothesis_signal import EpisodeHypothesisSignal, ConfidenceBand
from episode_safety_status import EpisodeSafetyStatus, assess_episode_safety

# Receive signal from EHG
signal = EpisodeHypothesisSignal(
    hypothesis_count=2,
    confidence_band=ConfidenceBand.MEDIUM,
    pivot_detected=False,
    pivot_confidence_band=ConfidenceBand.LOW
)

# Assess safety
safety_status = assess_episode_safety(signal)

# Branch on outcome
if safety_status == EpisodeSafetyStatus.SAFE_TO_EXTRACT:
    # Commit Response Parser output to state
    state_manager.commit_fields(parse_result['fields'])
else:
    # Block commit, display coercion prompt
    # safety_status is either AMBIGUOUS_MULTIPLE or AMBIGUOUS_PIVOT
    return coercion_prompt
```

**Integration:**
- Called by: DialogueManager (Step C integration point marked with comment)
- Consumes: EpisodeHypothesisSignal from EpisodeHypothesisGenerator
- Gates: Response Parser commit to StateManager
- Triggers: Coercion prompt generation (Step B) when unsafe

---

### Prompt Builder (prompt_builder.py)

**Purpose:** Translate structured extraction intent into deterministic LLM prompt text with semantic field context

**Role:** Compiles ruleset metadata (field labels, descriptions, valid values) into complete extraction prompts. Ensures LLM understands what fields mean (e.g., "visual loss onset speed") while outputting technical field IDs (e.g., "vl_onset_speed"). Separates prompt construction (medical logic) from prompt execution (ResponseParser).

**Core Types:**

**`PromptMode` (Enum):**
```python
class PromptMode(Enum):
    PRIMARY = "primary"                    # Normal extraction
    REPLAY = "replay"                      # Clarification exit replay (future)
    CLARIFICATION_EXIT = "clarification_exit"  # Post-disambiguation (future)
```
- Internal control signal, not serialized
- Determines prompt framing strategy

**`FieldType` (str, Enum):**
```python
class FieldType(str, Enum):
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    TEXT = "text"
```
- Canonical field types for this system
- New types added deliberately (e.g., date not yet supported)

**`FieldSpec` (frozen dataclass):**
```python
@dataclass(frozen=True)
class FieldSpec:
    field_id: str          # Technical name: "vl_onset_speed"
    label: str             # Semantic meaning: "visual loss onset speed"
    description: str       # What it represents: "how quickly visual loss developed"
    field_type: FieldType  # categorical | boolean | text
    valid_values: Optional[List[str]] = None      # Required for categorical
    definitions: Optional[Dict[str, str]] = None  # Value definitions (optional)
```
- Compiled from ruleset entry
- Validates on construction (`__post_init__`)
- Fail-fast if incomplete or inconsistent

**`PromptSpec` (frozen dataclass):**
```python
@dataclass(frozen=True)
class PromptSpec:
    mode: PromptMode
    primary_field: FieldSpec
    question_text: str
    additional_fields: List[FieldSpec] = None     # Metadata window
    episode_anchor: Optional[EpisodeAnchor] = None  # Future: episode context
    constraints: Optional[Dict[str, Any]] = None    # Future: extraction rules
```
- Contract object representing compiled intent
- Not a convenience dict - explicit structure enforced
- Consumed by PromptBuilder to generate prompt text

**`EpisodeAnchor` (stub dataclass):**
```python
@dataclass(frozen=True)
class EpisodeAnchor:
    episode_id: Optional[str] = None
    resolution_status: Optional[str] = None
```
- Placeholder for future episode-scoped extraction
- Reserves authority in PromptSpec contract
- Currently unused

**Class: PromptBuilder**

**Primary Method:**
```python
def build(self, spec: PromptSpec, patient_response: str) -> str
```

**Parameters:**
- `spec`: Complete PromptSpec (mode, fields, question text)
- `patient_response`: Patient's actual response text

**Returns:** Complete prompt text ready for LLM (string)

**Raises:**
- `TypeError`: If inputs wrong type
- `PromptBuildError`: If spec invalid or mode not implemented
- `NotImplementedError`: If mode is REPLAY or CLARIFICATION_EXIT (future)

**Prompt Structure (PRIMARY mode):**
```
You are a medical data extractor for ophthalmology consultations.

PRIMARY FIELD
Field ID: vl_onset_speed
Meaning: visual loss onset speed
Description: how quickly visual loss developed
Type: categorical
Valid values:
  - acute (seconds to minutes)
  - subacute (hours to days)
  - chronic (weeks or longer)

ADDITIONAL CONTEXT - You may also extract these fields if clearly mentioned:
  - Field ID: vl_pattern
    Meaning: visual loss pattern
    Type: categorical
    Valid values: constant, fluctuating, progressive

Patient response: "It happened really quickly, over a few seconds"

Extract any relevant fields from the patient's response.
Return ONLY valid JSON using the Field ID as the key:
{
  "vl_onset_speed": "value",
  "other_field_id": "value"
}

Rules:
- PRIMARY focus on vl_onset_speed
- You MAY extract additional fields if clearly mentioned
- If the patient response does not clearly contain extractable information for the listed fields, return {}
- Do not guess. Do not infer.
- Use exact Field IDs as JSON keys
- For categorical fields, use exact valid values
- For boolean fields, use true or false (lowercase, no quotes)
```

**Factory Function:**
```python
def create_prompt_spec(
    question: Dict[str, Any],
    mode: PromptMode = PromptMode.PRIMARY,
    next_questions: Optional[List[Dict[str, Any]]] = None,
    episode_anchor: Optional[EpisodeAnchor] = None
) -> PromptSpec
```

**Parameters:**
- `question`: Primary question dict from ruleset
  - Required keys: `field`, `field_type`, `field_label`, `field_description`, `question`
  - Conditional: `valid_values` (if categorical)
  - Optional: `definitions`
- `mode`: Extraction mode (default PRIMARY)
- `next_questions`: Optional list of question dicts for metadata window
- `episode_anchor`: Optional episode context (future use)

**Returns:** Validated PromptSpec ready for PromptBuilder

**Raises:** `PromptBuildError` if any question missing required fields or invalid

**Validation (Fail-Fast):**

| Check | Enforcement |
|-------|-------------|
| `field_label` present and non-empty | Hard error (PromptBuildError) |
| `field_description` present and non-empty | Hard error (PromptBuildError) |
| `field_type` in FieldType enum | Hard error (PromptBuildError) |
| Categorical fields have `valid_values` | Hard error (PromptBuildError) |
| `valid_values` non-empty list | Hard error (PromptBuildError) |
| `definitions` cover all `valid_values` | Hard error (PromptBuildError) |
| `question_text` non-empty | Hard error (PromptBuildError) |

**Key Design Decisions:**
- Fail-fast validation (no warnings, no partial builds)
- Does not repair or guess missing metadata
- PromptSpec is frozen (immutable contract)
- Field IDs used as JSON keys, labels provide semantic meaning
- "Do not guess. Do not infer" instruction prevents hallucination
- Patient response included in prompt (not added later by ResponseParser)
- PromptBuilder is stateless (same PromptSpec → same prompt text)
- Validation happens at PromptSpec creation, not during build()

**Custom Exception:**
```python
class PromptBuildError(Exception):
    """Raised when prompt cannot be built due to invalid/incomplete spec"""
```
- Used for all validation failures
- Signals configuration/ruleset errors (not runtime issues)
- Should be caught by DialogueManager and logged

**Usage Pattern:**
```python
from prompt_builder import (
    PromptBuilder, 
    create_prompt_spec, 
    PromptMode,
    PromptBuildError
)

# Get question from ruleset
question = {
    'field': 'vl_onset_speed',
    'field_type': 'categorical',
    'field_label': 'visual loss onset speed',
    'field_description': 'how quickly visual loss developed',
    'question': 'How quickly did it develop?',
    'valid_values': ['acute', 'subacute', 'chronic'],
    'definitions': {...}
}

# Create PromptSpec
try:
    spec = create_prompt_spec(
        question=question,
        mode=PromptMode.PRIMARY,
        next_questions=[...]  # Optional metadata window
    )
except PromptBuildError as e:
    # Ruleset configuration error - log and fail
    logger.error(f"Invalid question metadata: {e}")
    raise

# Build prompt
builder = PromptBuilder()
patient_response = "It happened really quickly"
prompt_text = builder.build(spec, patient_response)

# Pass to ResponseParser
result = response_parser.parse(
    prompt_text=prompt_text,
    patient_response=patient_response,
    expected_field='vl_onset_speed',
    turn_id='turn_09'
)
```

**Integration:**
- Called by: DialogueManager (after question selection, before extraction)
- Input from: QuestionSelector (question dicts from ruleset)
- Output to: ResponseParser (pre-built prompt text)
- Shares nothing with: Other modules (pure function)

---

**HuggingFace Client (hf_client_v2.py)**

**Purpose:** Centralized model loading and inference wrapper with 4-bit quantization, JSON generation, and error handling

**Role:** Provides unified interface for loading HuggingFace models and generating completions. Handles CUDA memory management, prompt formatting, and JSON repair. Shared instance injected into all LLM-consuming components (ResponseParser, SummaryGenerator, EpisodeHypothesisGenerator) to avoid loading multiple model copies.

**Class:** `HuggingFaceClient`

**Constructor:**
```python
def __init__(
    self,
    model_name: str,
    load_in_4bit: bool = True,
    device: str = "cuda",
    auto_format: bool = True
) -> None
```

**Parameters:**
- `model_name`: HuggingFace model identifier (e.g., "mistralai/Mistral-7B-Instruct-v0.2")
- `load_in_4bit`: Use NF4 quantization with bfloat16 compute (reduces VRAM by ~75%)
- `device`: "cuda" or "cpu"
- `auto_format`: Auto-detect and apply model-specific prompt formatting via PromptFormatter

**Initialization:**
- Validates CUDA availability if requested
- Loads tokenizer with pad_token fallback (sets to eos_token or adds [PAD])
- Configures BitsAndBytesConfig for 4-bit quantization if enabled
- Loads model with quantization and device mapping
- Initializes optional PromptFormatter for model-specific templates
- Logs GPU memory usage after loading
- Raises RuntimeError if CUDA requested but unavailable
- Raises torch.cuda.OutOfMemoryError if insufficient VRAM
- Sets model to eval mode

**Primary Methods:**

**1. Text Generation:**
```python
def generate(
    self,
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.3,
    return_diagnostics: bool = False,
    apply_formatting: bool = True
) -> Union[str, Dict[str, Any]]
```

**Returns:**
- `str`: Generated text (when `return_diagnostics=False`)
- `dict`: `{'text': str, 'diagnostics': {...}}` (when `return_diagnostics=True`)

**Diagnostics include:**
- `prompt_tokens`: Input token count
- `completion_tokens`: Output token count (excluding pad tokens)
- `total_tokens`: Sum of prompt and completion
- `latency_ms`: Generation time in milliseconds
- `formatting_applied`: Whether prompt formatting was used

**Process:**
1. Applies prompt formatting if `auto_format=True` and `apply_formatting=True`
2. Tokenizes input and moves to device
3. Logs GPU memory before generation
4. Generates with temperature-based sampling (deterministic if temperature=0.0)
5. Logs GPU memory after generation
6. Decodes output excluding prompt tokens
7. Filters pad tokens from completion count

**2. JSON Generation:**
```python
def generate_json(
    self,
    prompt: str,
    max_tokens: int = 256,
    temperature: float = 0.0,
    return_diagnostics: bool = False,
    apply_formatting: bool = True
) -> Union[str, Dict[str, Any]]
```

**Specialization:** Optimized for structured output:
- Uses `temperature=0.0` by default for deterministic JSON
- Strips markdown code blocks (```json, ```)
- Extracts content between first { and last }
- Performs basic brace balancing (adds missing } or removes extra })
- Returns JSON string (caller must `json.loads()`)
- Adds `json_repair_applied` flag to diagnostics if repairs made

**Note:** Basic repair only handles dict output (not arrays). Production systems should use jsonrepair library.

**3. Model Status:**
```python
def is_loaded(self) -> bool
```
Returns True if model and tokenizer are loaded and ready.

```python
def get_model_info(self) -> Dict[str, Any]
```
Returns metadata:
- `model_name`, `device`, `is_loaded`, `auto_format`
- `formatter`: PromptFormatter info if enabled
- GPU memory stats (allocated, reserved, peak) if CUDA

**Error Handling:**

| Scenario | Behaviour |
|----------|-----------|
| CUDA requested but unavailable | Raises RuntimeError during __init__ |
| Model loading fails | Raises original exception with logging |
| CUDA OOM during loading | Logs diagnostic advice, raises torch.cuda.OutOfMemoryError |
| CUDA OOM during generation | Logs prompt/max_tokens, raises torch.cuda.OutOfMemoryError |
| Model not loaded when calling generate | Raises RuntimeError |
| No braces in JSON repair | Logs warning, returns text as-is (will fail parse downstream) |

**Key Design Decisions:**
- **Dependency injection**: No singleton pattern, allows testing with multiple instances
- **Fail fast**: Infrastructure errors (CUDA OOM, model load failures) raise immediately
- **Duck typing contract**: Consumers check for `generate_json()` and `is_loaded()` methods
- **Model-agnostic**: No hardcoded prompt templates (delegated to PromptFormatter)
- **Shared instance pattern**: Single client injected into all LLM consumers to avoid loading model multiple times
- **Conservative JSON repair**: Only handles basic dict cleanup, doesn't risk corrupting valid output
- **Diagnostics optional**: Zero overhead when not needed

**Usage Pattern:**
```python
from hf_client_v2 import HuggingFaceClient

# Initialize once at startup
hf_client = HuggingFaceClient(
    "mistralai/Mistral-7B-Instruct-v0.2",
    load_in_4bit=True,
    auto_format=True
)

# Inject into all LLM consumers
response_parser = ResponseParser(hf_client)
summary_gen = SummaryGenerator(hf_client)
ehg = EpisodeHypothesisGenerator(hf_client)

# Generate text
result = hf_client.generate(
    "Explain cataracts in simple terms",
    max_tokens=128,
    temperature=0.3
)

# Generate JSON
json_str = hf_client.generate_json(
    "Return JSON: {\"symptom\": \"blur\", \"duration\": \"2 weeks\"}",
    max_tokens=64,
    temperature=0.0
)
data = json.loads(json_str)  # Caller parses
```

**Integration:**
- **Instantiated by:** Flask app (app.py) during startup
- **Injected into:** ResponseParser, SummaryGenerator, EpisodeHypothesisGenerator constructors
- **Used by:** Any component requiring LLM inference
- **Shares resources with:** All LLM-consuming modules (single model instance in memory)

---

### Episode Narrowing Prompt (episode_narrowing_prompt.py)
**Purpose:** Generate deterministic coercion prompts to force conversation back to current episode when ambiguity is detected
**Role:** When Episode Safety Status indicates ambiguity (AMBIGUOUS_MULTIPLE or AMBIGUOUS_PIVOT), generates a polite but firm prompt that acknowledges the ambiguity and redirects focus to the current episode. This is coercion, not clarification - no attempt to resolve which episode the user meant.

**Primary Function:**
def build_episode_narrowing_prompt(status: EpisodeSafetyStatus) -> str

**Parameters:**
status: Must be AMBIGUOUS_MULTIPLE or AMBIGUOUS_PIVOT
 (Never called with SAFE_TO_EXTRACT - that's a caller error)

Returns: Complete coercion prompt string (without follow-up question)

**Prompt Variants:**

Variant 1 - AMBIGUOUS_MULTIPLE (multiple problems mentioned):
"Thank you — it sounds like your last answer may have mentioned more than one problem.
To avoid mixing things up, I'm going to focus on the current problem for now."

Variant 2 - AMBIGUOUS_PIVOT (different problem mentioned):
"Thank you — it sounds like your last answer may have mentioned a different problem.
To avoid mixing things up, I'm going to focus on the current problem for now."

**Semantic Structure:**
1. Acknowledgment: "Thank you"
2. Detection statement: "It sounds like..."
3. Constraint assertion: "I'm going to focus on..."

**Error Handling:**
Scenario                          Behaviour
status = SAFE_TO_EXTRACT          Raises ValueError (fail fast - caller error)
status = AMBIGUOUS_MULTIPLE       Returns variant 1 string
status = AMBIGUOUS_PIVOT          Returns variant 2 string
Unexpected EpisodeSafetyStatus    Raises ValueError (unreachable given enum exhaustiveness)

**Key Design Decisions:**
- Deterministic - exactly one literal string per status, no randomization, no templates
- No placeholders - returned string is complete (DialogueManager appends question separately)
- Fails fast on caller error - if called with SAFE_TO_EXTRACT, raises immediately
- No clinical concepts - does not mention "episode", "earlier problem", or specific symptoms
- No resolution attempt - does not ask user to clarify or choose between options
- String literals in code - obvious in code review, no hidden configuration files
- Coercion, not negotiation - asserts what system will do, not what user should do

**Usage Pattern:**
from episode_narrowing_prompt import build_episode_narrowing_prompt
from episode_safety_status import EpisodeSafetyStatus, assess_episode_safety
from episode_hypothesis_signal import EpisodeHypothesisSignal

# DialogueManager flow
ehg_signal = episode_hypothesis_generator.generate_hypothesis(user_input, ...)
safety_status = assess_episode_safety(ehg_signal)

if safety_status != EpisodeSafetyStatus.SAFE_TO_EXTRACT:
    # Generate coercion prompt
    coercion = build_episode_narrowing_prompt(safety_status)
    
    # DialogueManager appends the pending question
    system_output = f"{coercion}\n\nFor the current problem, {pending_question['question']}"
    
    # Return early - skip Parser, skip commit, re-ask same question
    return turn_result(system_output, same_pending_question, ...)

**Integration:**
- Called by: DialogueManager._process_clinical_turn()
- Input from: episode_safety_status.assess_episode_safety()
- Output used by: DialogueManager (composed with pending question)
- Trigger condition: safety_status ∈ {AMBIGUOUS_MULTIPLE, AMBIGUOUS_PIVOT}
- Integration point: After EHG signal assessed, before Response Parser called

**Current Limitations (by design):**
- Only two prompt variants (sufficient for hardware-constrained coercion strategy)
- No support for actual clarification (deferred until 70B model available)
- No tracking of which problems were mentioned (no attempt to enumerate)
- No preservation of clinical data from ambiguous turns (discarded entirely)

---

### Contracts (contracts.py)

**Purpose:** Immutable data structures serving as semantic contracts between modules

**Role:** Definition layer for cross-module data exchange - shapes and semantics without enforcement

**Design Principles:**
- Frozen dataclasses (immutable after creation)
- No validation logic (contracts, not validators)
- No dependencies on other modules
- Definition layer only (no enforcement)

**Components:**

**ValueEnvelope dataclass** - Ingress-time wrapper for extracted values with provenance
```python
@dataclass(frozen=True)
class ValueEnvelope:
    value: Any          # The extracted clinical value
    source: str         # Origin: 'response_parser', 'user_explicit', etc.
    confidence: float   # 0.0-1.0, converted to band at write time
```

**Lifecycle:**
1. Created by: Response Parser (at extraction)
2. Passed through: Dialogue Manager (opaque, no unwrapping)
3. Consumed by: State Manager (collapsed into provenance at write time)
4. Never seen by: Question Selector, JSON Formatter, Summary Generator

**QuestionOutput dataclass** - Complete question specification from Question Selector
```python
@dataclass(frozen=True)
class QuestionOutput:
    id: str                    # e.g., 'vl_3', 'h_2'
    question: str              # Question text shown to user
    field: str                 # Target field name (JSON key)
    field_type: str            # 'text', 'boolean', 'categorical'
    type: str                  # 'probe' or 'conditional'
    valid_values: Optional[Tuple[str, ...]]           # For categorical
    field_label: Optional[str]                        # Semantic label for LLM
    field_description: Optional[str]                  # Extraction guidance
    definitions: Optional[Tuple[Tuple[str, str], ...]] # Value explanations
```

**Note on immutability:**
- `valid_values` uses Tuple, not List
- `definitions` uses Tuple of Tuples, not Dict
- Convert at creation: `tuple(list_value)`, `tuple((k,v) for k,v in dict.items())`

**Usage Pattern:**
```python
from backend.contracts import ValueEnvelope, QuestionOutput

# Response Parser produces envelopes:
envelope = ValueEnvelope(
    value='right',
    source='response_parser',
    confidence=0.95
)

# Question Selector produces questions:
question = QuestionOutput(
    id='vl_3',
    question='Which eye is affected?',
    field='vl_laterality',
    field_type='categorical',
    valid_values=('left', 'right', 'both'),
    field_label='visual loss laterality',
    field_description='Which eye or eyes are affected',
    definitions=(('left', 'left eye only'), ('right', 'right eye only'))
)

# Convert definitions back to dict when needed:
defs_dict = dict(question.definitions) if question.definitions else None
```

**Integration:**

| Contract | Produced by | Consumed by |
|----------|-------------|-------------|
| ValueEnvelope | Response Parser | State Manager |
| QuestionOutput | Question Selector | Prompt Builder, Dialogue Manager (passthrough) |

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
