# System Architecture

**Version:** 4.0  
**Last Updated:** 21 January 2026

## What This System Does

Multi-episode ophthalmology consultation system that conducts structured medical interviews. Patients can report multiple separate eye problems in one consultation. Each symptom presentation (episode) is collected independently, while demographic and background data (past medical history, medications) is shared across all episodes.

## Architecture Pattern: Orchestration

The Orchestrator module is the Dialogue Manager. The other core modules don't call each other - they're independent workers that the Dialogue Manager directs.  They would only call utility modules

**Call hierarchy:**
1. Transport Layer (Flask/Console)
   - Calls: Dialogue Manager only

2. Dialogue Manager (orchestrator)
   - Calls: State Manager, Question Selector, Response Parser, Episode Classifier, Episode Hypothesis Generator, JSON Formatter, Summary Generator
   - Called by: Transport Layer

3. Core Worker Modules
   - State Manager
   - Question Selector  
   - Response Parser
   - Episode Classifier
   - Episode Hypothesis Generator
   - JSON Formatter
   - Summary Generator
  
4. Utility Modules
   - clarification_templates.py
   - conversation_modes.py
   - display_helpers.py
   - episode_classifier.py
   - episode_hypothesis_signal.py
   - episode_safety_status.py
   - episode_narrowing_prompt.py
   - prompt_builder.py
   - prompt_formatter.py

## Core Modules

### Dialogue Manager (dialogue_manager_v2.py)
**Role:** Orchestrator - coordinates all other modules  
**Key characteristic:** Stateless per-turn transformation

- Receives user input and state snapshot
- Calls Episode Hypothesis Generator to detect episode ambiguity
- Calls prompt_builder.py to build a prompt for response parser
- Calls Response Parser with the prompt to extract clinical data
- Routes extracted fields to correct storage location
- Asks Question Selector what to ask next
- Returns both canonical state (for persistence) and clinical view (for display)
- Handles episode transitions
- No state held between turns

### State Manager (state_manager_v2.py)
**Role:** Data storage container  
**Key characteristic:** No business logic - pure data structure

- Stores episodes as array (episode 1, episode 2, etc.)
- Stores shared data separately (demographics, PMH, medications)
- Tracks operational state (questions answered, follow-up blocks triggered)
- Creates new episodes on demand
- Provides three different data exports:
  - `snapshot_state()` - complete canonical state (lossless, for persistence)
  - `export_clinical_view()` - filtered clinical data (lossy, for JSON output)
  - `export_for_summary()` - clinical data + dialogue history (for summary generation)
- Ephemeral: new instance created each turn from state snapshot

### Question Selector (question_selector_v2.py)
**Role:** Deterministic question selection using rules  
**Key characteristic:** Stateless - same input always gives same output

- Evaluates conditions in DSL (domain-specific language) against episode data
- Determines which question to ask next
- Detects when trigger conditions activate follow-up question blocks
- Checks if question blocks are complete
- Returns question dictionary or None (if episode complete)
- Configuration loaded from `ruleset_v2.json`

### Response Parser (response_parser_v2.py)
**Role:** Natural language understanding via LLM  
**Key characteristic:** Language task, not medical logic

- Takes patient's free-text response
- Calls HuggingFace LLM to extract structured fields
- Maps natural language to standardized values ("in my right eye" to "vl_laterality monocular_right")
- Returns dictionary of extracted fields plus metadata
- Handles ambiguous/unclear responses
- Best-effort: returns empty dict if extraction fails, consultation continues

### Episode Classifier (episode_classifier.py)
**Role:** Field routing  
**Key characteristic:** Pure function, no dependencies

- Determines if extracted field belongs to current episode or shared data
- Uses prefix rules (14 episode prefixes like `vl_`, `h_`, `ep_`)
- Uses special cases (12 episode fields, 8 shared fields)
- Returns: 'episode' | 'shared' | 'unknown'
- No overlap between episode and shared categories

### Episode Hypothesis Generator (episode_hypothesis_generator.py)
**Role:** Episode ambiguity detection  
**Key characteristic:** Stateless signal generation
**Status:** Basic LLM-driven implementation (limited by 7B model on 12GB GPU, will be upgraded when better hardware available)

- Detects potential episode pivots (user switched to different problem)
- Estimates hypothesis count (0, 1, or >1 episodes mentioned)
- Uses LLM semantic analysis with context about current episode
- Receives last system question and current episode context for comparison
- Returns EpisodeHypothesisSignal with:

hypothesis_count: Number of episode hypotheses detected (0, 1, or >1)
pivot_detected: Boolean indicating potential episode switch
confidence_band: Confidence level (low, medium, high)
pivot_confidence_band: Pivot confidence (low, medium, high)

- Called every turn in extraction mode
- Signal interpreted by episode_safety_status.py which outputs AMBIGUOUS_MULTIPLE, AMBIGUOUS_PIVOT or SAFE_TO_EXTRACT (to be replaced by full Episode Hypothesis Manager when EHG upgraded)
- LLM call failures raise exceptions (fail fast); malformed LLM output returns safe defaults

### JSON Formatter (json_formatter_v2.py)
**Role:** Serialization to standard medical format  
**Key characteristic:** Output-only, never used for persistence

- Transforms clinical data to schema-compliant JSON
- Adds metadata (timestamps, consultation ID)
- Validates structure against `json_schema.json`
- Only called once at end of consultation
- Never used to rehydrate state

### Summary Generator (summary_generator_v2.py)
**Role:** Clinical narrative generation  
**Key characteristic:** LLM-based text generation

- Generates readable clinical summary from structured data + dialogue history
- One summary per episode
- Shared data listed, not summarized
- Tracks token usage (warns at 32k context)

### Semantic contracts and envelopes

**Purpose:** Type-safe contracts and provenance tracking at module boundaries.

### Core Concepts

**Definition Layer vs Enforcement Layer:** Semantic contracts that define expected shapes and meanings, but do not enforce validation. This allows architectural clarity while preserving iteration flexibility.

**Envelope Pattern:** Values extracted by Response Parser from patient responses are wrapped in `ValueEnvelope` objects that carry provenance and confidence metadata. Envelopes flow through the system and are collapsed at storage time by the state manager

### Components

**Contracts Module** (contracts.py)
   - `ValueEnvelope`: Frozen dataclass wrapping extracted values with source and confidence
   - `QuestionOutput`: Frozen dataclass representing questions from Question Selector
   - No validation logic, no dependencies on other modules
   - Pure definition layer

### QuestionOutput Contract

Question Selector returns `QuestionOutput` frozen dataclass instead of raw dicts:

```python
@dataclass(frozen=True)
class QuestionOutput:
    id: str                    # 'vl_3'
    question: str              # 'Which eye is affected?'
    field: str                 # 'vl_laterality'
    field_type: str            # 'categorical'
    type: str                  # 'probe' | 'conditional'
    valid_values: Tuple[str]   # ('left', 'right', 'both')
    field_label: str           # 'visual loss laterality'
    field_description: str     # 'Which eye or eyes are affected'
    definitions: Tuple[Tuple]  # (('left', 'left eye only'), ...)
```

**Consumers:**
- Dialogue Manager: Accesses `.id`, `.question`, `.field` (attribute access, not dict access)
- Prompt Builder: Uses `.field_label`, `.field_description`, `.valid_values`, `.definitions` to construct extraction prompts

### Runtime Assertions

Question Selector entry points include permanent assertions that fail loudly on invariant violations:

```python
def get_next_question(self, episode_data: dict) -> Optional[QuestionOutput]:
    if 'questions_answered' not in episode_data:
        raise AssertionError("episode_data missing required key: questions_answered")
    # ... additional assertions
```

**Error Handling Policy:**
- Question Selector raises `AssertionError` on invariant violations
- Dialogue Manager does not catch (failures propagate)
- Flask routes catch at top level with critical logging, then re-raise (fail loud)

### V4 Architecture Principles

1. **Envelopes are ingress-time, not storage-time:** ValueEnvelope exists before values enter State Manager, not inside it.
2. **Collapse, don't store:** Envelopes are collapsed into existing provenance system at write time, preserving metadata without changing storage structure.
3. **Defense in depth:** Export methods call `strip_envelopes()` even though envelopes should already be collapsed, preventing leakage to legacy consumers.
4. **Immutability for contracts:** Both `ValueEnvelope` and `QuestionOutput` are frozen dataclasses. Consumers cannot accidentally mutate shared data.
5. **Assertions are permanent:** Runtime assertions in Question Selector are guards, not dev-only checks. They survive into production.

## Critical Data Flows

### Core Extraction Data Flow Per Turn (Simplified)

1. **Transport Layer** passes user input + state snapshot to Dialogue Manager
2. **Dialogue Manager** rehydrates State Manager from snapshot
3. **Episode Hypothesis Generator** analyzes user input for episode ambiguity.  If safe, then response parser output is not blocked
4. **Response Parser** returns:
{'vl_laterality': ValueEnvelope(value='right', source='response_parser', confidence=0.95)}
5. **Episode Classifier** determines where each field belongs
6. **Dialogue Manager** passes ValueEnvelope to State Manager. State Manager collapses envelope on write:
    │   - Stores value: episode['vl_laterality'] = 'right'
    │   - Stores provenance: episode['_provenance']['vl_laterality'] = {source, confidence_band, mode}
7. **Question Selector** determines next question based on episode data, exports QuestionOutput
8. **Dialogue Manager** builds TurnResult containing:
   - Canonical state snapshot (for next turn)
   - Clinical output (for display)
   - Next question or completion message
9. **Transport Layer** persists state snapshot, shows question to user

### Episode Ambiguity Data Flow

1. **Transport Layer** passes user input + state snapshot to Dialogue Manager
2. **Dialogue Manager** rehydrates State Manager from snapshot
3. **Episode Hypothesis Generator** analyzes user input for episode ambiguity
4. **episode_safety_status.py** determines AMBIGUOUS or SAFE depending on Episode Hypothesis Generator signal
5.  **episode_narrowing_prompt.py** If AMBIGUOUS, then response parser output is discarded and prompt appears asking patient to return to current episode
6. **Dialogue Manager** appends the pending question to the episode narrowing prompt and the system returns to the core extraction data flow

### Episode Transition Flow

When Question Selector returns None (episode complete):
1. System asks: "Do you have another eye problem to discuss?"
2. If yes: State Manager creates new episode, loop continues
3. If no: Consultation ends, outputs generated

### Output Generation Flow (End of Consultation)

Two parallel outputs generated:

**JSON Output:**
```
State Manager export_clinical_view() 
              JSON Formatter 
              schema-compliant JSON file
```

**Summary Output:**
```
State Manager export_for_summary()
              Summary Generator (LLM)
              clinical narrative text file
```

## Key Design Principles

1. **Orchestration not delegation:** Only Dialogue Manager calls other modules; modules never call each other
2. **Stateless where possible:** Question Selector and Episode Classifier are pure functions
3. **Single responsibility:** Each module has one job with clear boundaries
4. **Medical logic in config:** Question flow defined in `ruleset_v2.json`, not hardcoded
5. **Best-effort continuation:** System logs errors but doesn't crash mid-consultation
6. **Ephemeral state:** State Manager recreated each turn; canonical snapshot is source of truth

## Two State Views: Critical Distinction

### Canonical State (state_snapshot)
- **Lossless** - includes everything
- Includes empty episodes
- Includes operational fields (questions_answered, follow_up_blocks)
- **Only** source of truth for persistence
- Round-trip serializable
- Passed between turns

### Clinical Output (clinical_output)
- **Lossy** - filtered for clinical relevance
- Excludes empty episodes
- Excludes operational fields
- For display and final JSON export only

**Critical:** State Manager is rehydrated from canonical snapshot only. Clinical output is for humans/systems consuming the data, never for state restoration.

## Module Dependencies

```
Response Parser:             hf_client_v2.py (LLM loading and inference wrapper), prompt_builder.py (builds input prompt for response parser)
Episode Classifier:          (no dependencies)
Episode Hypothesis Generator: episode_hypothesis_signal (dataclass contract), hf_client_v2.py
State Manager:               clinical_data_model.json
Question Selector:           ruleset_v2.json
JSON Formatter:              json_schema.json, State Manager export
Summary Generator:           State Manager export
Dialogue Manager:            All above modules
Flask/Console               Dialogue Manager only
```

## V3: Multiple Episode Ambiguity Handling Architecture

**Purpose:** Handle realistic patient narratives where multiple episodes are mentioned or switched mid-conversation.

**Implementation**

1. **Conversation Mode Enum** (conversation_modes.py)
   - MODE_DISCOVERY: Initial patient input, determining what they want to discuss
   - MODE_CLARIFICATION: Resolving episode ambiguity
   - MODE_EPISODE_EXTRACTION: Structured questioning for confirmed episode
   - Threaded through State Manager and Dialogue Manager

2. **Episode Hypothesis Signal** (episode_hypothesis_signal.py)
   - Structured contract between EHG and Dialogue Manager
   - Fields: hypothesis_count, pivot_detected, confidence_band, pivot_confidence_band
   - Immutable dataclass with enum-based confidence levels

3. **Episode Hypothesis Generator** (episode_hypothesis_generator.py)
   - LLM driven module that detects hypothesis count and pivot (change to different topic)
   - Currently low quality 7B model - accepted flaw which is dependent on hardware limitations
   - Will be replaced with larger model and episode resolution mechanics once hardware is available

4. **Field-Level Provenance Tagging** (state_manager_v2.py)
   - Tracks which turn/utterance each field came from
   - Passive tracking - not yet used for replay or validation

5. **Episode Safety Status** (episode_safety_status.py)
   - Deterministic interpretation of probabilistic EHG signals
   - Pure function: assess_episode_safety() collapses EpisodeHypothesisSignal into finite safety enum
   - Three outcomes: SAFE_TO_EXTRACT, AMBIGUOUS_MULTIPLE, AMBIGUOUS_PIVOT
   - Intentionally conservative - ignores confidence bands
   - Boundary between probabilistic inference (EHG) and deterministic control (Dialogue Manager)
  
6. **Coercion prompt generation** (episode_narrowing_prompt.py)
   - Creates statements that acknowledge ambiguity and redirect patient back to the current episode
   - If episode_safety_status.py returns AMBIGUOUS_MULTIPLE or AMBIGUOUS_PIVOT, then RP output discarded and episode_narrowing_prompt.py called
   - pending_question is appended to the end of the question by the dialogue manager

### V3 Architecture Principles

1. **Immediate Validation Policy:** Episode hypotheses must be confirmed or negated before clinical questioning continues. No floating or long-lived hypotheses.
2. **Safety Over Smoothness:** Silent episode mixing is unsafe. Ambiguity must be resolved even if it interrupts conversational flow.
3. **Parallelism for Latency:** In extraction mode, EHG and Response Parser run in parallel to avoid UX degradation.

### V3 Known Limitations

1. Aim of V3 is to create an episode ambiguity handling layer that simply detects episode ambiguity and then coerces the patient back to talking about the current episode
2. This aim is chosen at the cost of UX because we are working with very limited resources (12GB GPU and maximum 7B size model), so the natural language processing layer will never be robust enough to truly resolve episode ambiguity
3. Once out of proof of concept and towards a production ready medical system, we will have access to higher grade hardware (2x32GB 5090 Geforce GPUs that can run a 70B size model)
4. That will allow us to create a much more robust episode ambiguity layer which actually resolves episode ambiguity, for example creating new episodes and switching between them

