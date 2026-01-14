# System Architecture

**Version:** 3.0  
**Last Updated:** January 2026

## What This System Does

Multi-episode ophthalmology consultation system that conducts structured medical interviews. Patients can report multiple separate eye problems in one consultation. Each symptom presentation (episode) is collected independently, while demographic and background data (past medical history, medications) is shared across all episodes.

## Architecture Pattern: Orchestration

The Orchestrator module is the Dialogue Manager. The other 6 modules don't call each other - they're independent workers that the Dialogue Manager directs.

**Call hierarchy:**
1. Transport Layer (Flask/Console)
   - Calls: Dialogue Manager only

2. Dialogue Manager (orchestrator)
   - Calls: State Manager, Question Selector, Response Parser, Episode Classifier, Episode Hypothesis Generator, JSON Formatter, Summary Generator
   - Called by: Transport Layer

3. Worker Modules
   - State Manager
   - Question Selector  
   - Response Parser
   - Episode Classifier
   - Episode Hypothesis Generator (stub)
   - JSON Formatter
   - Summary Generator

## Core Modules

### Dialogue Manager (dialogue_manager_v2.py)
**Role:** Orchestrator - coordinates all other modules  
**Key characteristic:** Stateless per-turn transformation

- Receives user input and state snapshot
- Calls Response Parser to extract clinical data
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
- Maps natural language to standardized values ("right eye" â†’ "monocular_right")
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

### Episode Hypothesis Generator (episode_hypothesis_generator_stub.py)
**Role:** Episode ambiguity detection  
**Key characteristic:** Stateless signal generation (stub implementation)
**Status:** Stub - will be replaced by LLM-driven implementation

- Detects potential episode pivots via abandonment phrase matching
- Keywords: "actually", "forget", "wait", "no", "different"
- Estimates hypothesis count (currently defaults to 1, or 0 for empty input)
- Returns EpisodeHypothesisSignal with:
  - `hypothesis_count`: Number of episode hypotheses detected (0, 1, or >1)
  - `pivot_detected`: Boolean indicating potential episode switch
  - `confidence_band`: Confidence level (currently placeholder HIGH)
  - `pivot_confidence_band`: Pivot confidence (currently placeholder HIGH)
- Called every turn in extraction mode
- Signal generated but not yet acted upon (awaiting Episode Hypothesis Manager)
- Future: Will use LLM semantic analysis and current_episode_context for comparison
- Never raises exceptions (returns safe defaults on error)

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

## Critical Data Flows

### Per-Turn Flow (Simplified)

1. **Transport Layer** passes user input + state snapshot to Dialogue Manager
2. **Dialogue Manager** rehydrates State Manager from snapshot
3. **Episode Hypothesis Generator** analyzes user input for episode ambiguity (signal logged but not yet acted upon)
4. **Response Parser** extracts fields from user's text
5. **Episode Classifier** determines where each field belongs
6. **Dialogue Manager** stores fields via State Manager
7. **Question Selector** determines next question based on episode data
8. **Dialogue Manager** builds TurnResult containing:
   - Canonical state snapshot (for next turn)
   - Clinical output (for display)
   - Next question or completion message
9. **Transport Layer** persists state snapshot, shows question to user

### Episode Transition Flow

When Question Selector returns None (episode complete):
1. System asks: "Do you have another eye problem to discuss?"
2. If yes: State Manager creates new episode, loop continues
3. If no: Consultation ends, outputs generated

### Output Generation Flow (End of Consultation)

Two parallel outputs generated:

**JSON Output:**
```
State Manager â†’ export_clinical_view() 
              â†’ JSON Formatter 
              â†’ schema-compliant JSON file
```

**Summary Output:**
```
State Manager â†’ export_for_summary()
              â†’ Summary Generator (LLM)
              â†’ clinical narrative text file
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
Response Parser             â†’ (no dependencies)
Episode Classifier          â†’ (no dependencies)
Episode Hypothesis Generator â†’ episode_hypothesis_signal (dataclass contract)
State Manager               â†’ clinical_data_model.json
Question Selector           â†’ ruleset_v2.json
JSON Formatter              â†’ json_schema.json, State Manager export
Summary Generator           â†’ State Manager export
Dialogue Manager            â†’ All above modules
Flask/Console               â†’ Dialogue Manager only
```

## V3: Multi-Episode Architecture (In Progress)

**Goal:** Handle realistic patient narratives where multiple episodes are mentioned or switched mid-conversation.

### Current Implementation Status

**Completed:**
1. **Conversation Mode Enum** (conversation_modes.py)
   - MODE_DISCOVERY: Initial patient input, determining what they want to discuss
   - MODE_CLARIFICATION: Resolving episode ambiguity
   - MODE_EPISODE_EXTRACTION: Structured questioning for confirmed episode
   - Threaded through State Manager and Dialogue Manager

2. **Episode Hypothesis Signal** (episode_hypothesis_signal.py)
   - Structured contract between EHG and Dialogue Manager
   - Fields: hypothesis_count, pivot_detected, confidence_band, pivot_confidence_band
   - Immutable dataclass with enum-based confidence levels

3. **Episode Hypothesis Generator Stub** (episode_hypothesis_generator_stub.py)
   - Simple abandonment phrase detection: "actually", "forget", "wait", "no", "different"
   - Generates signals but Episode Hypothesis Manager not yet implemented
   - Signals logged but not acted upon
   - Interface ready for future LLM replacement

4. **Clarification Transcript Buffer** (clarification_transcript_buffer.py)
   - Records clarification questions and responses
   - Marks which entries are replayable for clinical extraction
   - Not yet active in dialogue flow

5. **Evidence Span Validator** (evidence_span_validator.py)
   - Deterministic validation of mention objects against source text
   - Guards against LLM hallucination
   - Not yet active

6. **Field-Level Provenance Tagging** (state_manager_v2.py)
   - Tracks which turn/utterance each field came from
   - Passive tracking - not yet used for replay or validation

**In Progress:**
- Episode Hypothesis Manager (deterministic mode transition logic)
- Clarification Parser (mention object extraction)
- Acting on EHG signals for mode transitions
- Passing current_episode_context to EHG

**Not Started:**
- Real LLM-driven Episode Hypothesis Generator
- Clarification question generation
- Clarification replay semantics
- Multi-episode clarification flow

### V3 Architecture Principles

1. **Immediate Validation Policy:** Episode hypotheses must be confirmed or negated before clinical questioning continues. No floating or long-lived hypotheses.

2. **Safety Over Smoothness:** Silent episode mixing is unsafe. Ambiguity must be resolved even if it interrupts conversational flow.

3. **Evidence-Based Extraction:** Every mention object must include verbatim evidence span from user's original text. Deterministic validation guards against hallucination.

4. **Bounded Clarification:** System may attempt clarification a bounded number of times. If patient cannot resolve, default to safer interpretation and proceed.

5. **Parallelism for Latency:** In extraction mode, EHG and Response Parser run in parallel to avoid UX degradation.

### V3 Mode Transition Logic (Planned)

**Discovery Mode:**
- hypothesis_count = 0 â†’ stay in discovery
- hypothesis_count > 1 â†’ clarification mode
- hypothesis_count = 1, high confidence â†’ extraction mode
- hypothesis_count = 1, low/medium confidence â†’ clarification mode

**Extraction Mode:**
- hypothesis_count = 0 â†’ discovery mode
- hypothesis_count > 1 â†’ clarification mode
- hypothesis_count = 1, low/medium confidence â†’ clarification mode
- hypothesis_count = 1, high confidence, pivot_detected = true â†’ clarification mode
- hypothesis_count = 1, high confidence, pivot_detected = false â†’ stay in extraction

**Clarification Mode:**
- Entered via multiple paths (low confidence, >1 hypothesis, pivot detected)
- Only explicit user confirmation exits clarification
- Emergency escape if patient unable to disambiguate
- EHG passive during clarification

### V3 Known Limitations

1. EHG stub uses simple keyword matching - may have false positives (e.g., "I don't know" contains "no")
2. Confidence bands not yet meaningful (hardcoded to HIGH)
3. No access to current_episode_context for semantic comparison
4. Mode transitions wired but not yet driving conversation flow
5. Clarification questions not yet implemented