# Dialogue Manager V2 Implementation - Session Handover

**Date:** December 3, 2025  
**Session Focus:** Multi-episode Dialogue Manager V2 + Episode Classifier  
**Status:** Complete and tested âœ“

---

## What We Built

### 1. Episode Classifier Module

File: backend/utils/episode_classifier.py
Purpose: Single source of truth for field classification (episode vs shared vs unknown)
Key Functions:
pythonclassify_field(field_name: str) -> 'episode' | 'shared' | 'unknown'
get_all_episode_prefixes() -> Set[str]
get_episode_special_cases() -> Set[str]
get_all_shared_fields() -> Set[str]
is_episode_field(field_name: str) -> bool
is_shared_field(field_name: str) -> bool
get_prefix_documentation() -> dict
Design:

Prefix-based classification (automatic sync with ruleset changes)
14 episode prefixes (vl_, h_, ep_, ac_, hc_, cp_, vp_, dp_, b1_-b6_)
12 episode special cases (fields without standard prefix: visual_loss_present, agnosia_present, hallucinations_present, vertigo_present, nystagmus_present, dry_gritty_sensation, appearance_changes_present, other_symptoms, functional_impact)
8 shared fields (additional_episodes_present, past_medical_history, medications, family_history, social_history fields)
Zero overlap between episode and shared sets

Benefits:

When you add vl_new_field to ruleset, automatically classified as episode
No manual updates needed when adding fields with existing prefixes
Scales effortlessly as schema grows
**Tests:** `tests/test_episode_classifier.py` (14 tests, all passing)

---

### 2. Dialogue Manager V2

**File:** `backend/core/dialogue_manager_v2.py`  
**Purpose:** Orchestrate multi-episode consultations with field routing and episode transitions

**Key Design Decisions:**

1. **Episode Transition Logic:**
   - Trust Response Parser with retry mechanism (no duplicate interpretation)
   - MAX_TRANSITION_RETRIES = 2
   - If unclear after retries, assume "no" (conservative)
   - Episode transition question: "Have you had any other episodes of eye-related problems you would like to discuss?"

After all V2 modules have been updated, we will go back and alter this in V2.1
In V2.1, the dialogue manager will handle multi-turn clarification
hen the episode transition question is asked, the response parser will return yes, no, ambiguous or invalid responses
If yes, the dialogue manager will proceed to create a new episode
If no, then proceed to shared fields
If ambiguous or invalid, then attempt to clarify
In V2.2, we will expand this to include all fields that have Boolean or categorical fields
In V2.3, we will upgrade the response parser to attempt to classify text field types into correct, ambiguous or invalid responses so the dialogue manager knows when to clarify and when to proceed

2. **Field Routing:**
   ```python
   classification = classify_field(field_name)
   
   if classification == 'episode':
       state.set_episode_field(current_episode_id, field_name, value)
   elif classification == 'shared':
       state.set_shared_field(field_name, value)
   else:  # unknown
       # Quarantine in dialogue metadata, not episode data
       unmapped[field_name] = value
   ```

3. **Episode Management:**
   - Episode 1 created immediately on consultation start
   - `current_episode_id` tracked as internal UI state (NOT exported to JSON)
   - New episode created immediately on "yes" response to transition question
   - Episode transitions after ALL questions complete (including follow-up blocks)

4. **Unmapped Fields:**
   - Stored in dialogue history metadata: `extracted_fields['_unmapped']`
   - NOT stored in episode data (keeps clinical records clean)
   - Logged as warnings for telemetry
   - Enables schema evolution tracking

5. **Error Handling:**
   - Best-effort continuation (log errors, don't crash consultation)
   - Centralized `_handle_error()` method
   - All errors tracked in `self.errors` list for audit

**Key Methods:**

```python
# Main entry point
run_consultation(input_fn, output_fn, output_dir, on_finish) -> dict

# Internal workflow
_conversation_loop_v2(input_fn, output_fn) -> (completed, total_questions, total_episodes)
_ask_episode_questions(input_fn, output_fn, question_offset) -> (episode_complete, questions_asked)
_ask_episode_transition_question(input_fn, output_fn) -> bool
_route_extracted_fields(episode_id, extracted) -> dict (unmapped)
_create_first_episode() -> int
```

**Integration Points:**

- **State Manager V2:** Uses all episode management methods (`create_episode`, `set_episode_field`, `set_shared_field`, `add_dialogue_turn`)
- **Question Selector V1:** Currently uses without episode context (returns questions sequentially until None)
- **Response Parser:** Unchanged from V1
- **JSON Formatter V1:** Placeholder only (V2 needs episode array support)
- **Summary Generator V1:** Placeholder only (V2 needs multi-episode narrative)

**Tests:** `tests/test_dialogue_manager_v2.py` (12 unit tests, all passing)

---

### 3. Integration Test

**File:** `tests/test_dialogue_manager_v2_integration.py`  
**Purpose:** End-to-end test with real State Manager V2

**Test Scenario:**
- Episode 1: 3 vision loss questions (laterality, onset, speed)
- Episode 2: 2 headache questions (present, location)
- Total: 5 questions, 2 episodes

**Verification:**
- Episode data correctly stored and separated
- Dialogue history tracked per episode
- Export methods work (export_for_json, export_for_summary)
- Statistics accurate

**Result:** âœ“ All checks passing

---

## Test Summary

**Total Tests:** 13  
**Passing:** 13 (100%)  
**Fast Tests:** 12 (unit tests with mocks, <1 second)  
**Integration Test:** 1 (with real State Manager V2, <1 second)

**Test Coverage:**
- Episode field routing âœ“
- Shared field routing âœ“
- Unmapped field quarantine âœ“
- Episode creation âœ“
- Episode transitions (yes/no/unclear/retry/max retries) âœ“
- Multiple episodes (3 episodes tested) âœ“
- Early exit commands âœ“
- Dialogue history separation âœ“
- State Manager V2 integration âœ“

---

## Known Limitations (By Design)

1. **Question Selector V1 Used:**
   - Does NOT receive episode context
   - Returns questions sequentially without episode awareness
   - Does NOT reset state between episodes
   - **Consequence:** Will ask same questions across episodes unless manually managed
   - **Fix Required:** Question Selector V2 (next phase)

2. **JSON Formatter V1 Used:**
   - Does NOT handle episode array structure
   - Placeholder output only
   - **Fix Required:** JSON Formatter V2

3. **Summary Generator V1 Used:**
   - Does NOT handle multiple episodes
   - Placeholder output only
   - **Fix Required:** Summary Generator V2

These are expected and intentional - Dialogue Manager V2 is designed to work with V1 modules temporarily while V2 versions are built.

---

## Architecture Patterns Implemented

### 1. Separation of Concerns

**Episode Classifier:** Field classification logic (pure functions, no state)  
**Dialogue Manager:** Flow control and orchestration (thin layer)  
**State Manager V2:** Data storage (no business logic)  
**Question Selector:** Medical protocol (not yet episode-aware)

### 2. Trust Parser, Add Validation

Instead of duplicate interpretation logic:
```python
# WRONG (duplicate interpretation):
if "yes" in response.lower():
    create_episode = True

# RIGHT (trust parser, add retry):
extracted = parser.parse(question, response)
if 'additional_episodes_present' not in extracted:
    # Unclear - retry
```

### 3. Quarantine Unknown Data

Unknown fields go to dialogue metadata, not episode data:
```python
# In add_dialogue_turn():
extracted_fields={
    **extracted,
    '_unmapped': unmapped_fields  # Telemetry, not clinical data
}
```

### 4. Internal UI State

`current_episode_id` tracks active episode but is NOT exported:
```python
# Internal tracking
self.current_episode_id = 2

# Export (no current_episode_id)
state.export_for_json() -> {'episodes': [...], 'shared_data': {...}}
```

---

## Key Decision Points & Rationale

### Decision 1: Episode Transition Control Logic

**OptionA:** Dialogue Manager performs "tightly constrained interpretation" with parser as "supporting signal"

**Option B:** Trust parser with retry logic

**Final Decision:** Trust parser with retry“

**Rationale:**
- Single source of truth for interpretation (Response Parser)
- Retry logic handles ambiguity without duplicate interpretation
- When parser improves, transition logic improves automatically
- Avoids technical debt of parallel interpretation systems

**Implementation:**
```python
MAX_TRANSITION_RETRIES = 2

for retry in range(MAX_TRANSITION_RETRIES):
    extracted = parser.parse(question, response)
    
    if 'additional_episodes_present' in extracted:
        return extracted['additional_episodes_present']
    
    if retry < MAX_TRANSITION_RETRIES - 1:
        output_fn("I didn't quite catch that. Please answer yes or no.")
    else:
        output_fn("I'll assume that's a no.")
        return False
```

### Decision 2: Unmapped Field Storage

**User's Original Approach:** Store in episode data: `episode["unmapped_fields"]["parser"]`

**My Counter-Proposal:** Store in dialogue metadata, not episode data

**Final Decision:** Dialogue metadata âœ“

**Rationale:**
- Episode object stays clean (only valid clinical fields)
- Unmapped fields still logged and traceable via dialogue history
- When exporting for JSON, unmapped fields go in metadata section
- Telemetry works without polluting clinical records

**Implementation:**
```python
# In _route_extracted_fields():
unmapped = {k: v for k, v in extracted.items() if classify_field(k) == 'unknown'}

# In _ask_episode_questions():
state.add_dialogue_turn(
    episode_id=current_episode_id,
    question_id=question_id,
    question_text=question_text,
    patient_response=response,
    extracted_fields={
        **extracted,
        '_unmapped': unmapped  # Quarantine here
    }
)
```

### Decision 3: Follow-up Block Classification

**Clarification Needed:** Are follow-up blocks episode-specific or shared?

**Resolution:** Episode-specific âœ“

**Rationale:**
- Schema shows follow-up blocks nested inside episode objects
- Triggers based on episode-specific data
- Different episodes can trigger different blocks
- Makes clinical sense (GCA screening for one episode, not globally)

## Future enhancements ##

- We will plan to upgrade the system to handle multi-turn classifications
- This will happen in two phases: strictly defined JSON fields and free text JSON fields
- For strictly defined fields (e.g. Boolean and categorical fields), the response parser will return either a valid response (e.g. yes, no or one of the valid categories), ambiguous or invalid
- Dialogue manager will decide on whether to continue or clarify based on these responses
- Will need smarter response parser design for the free text fields - discuss in more detail at later date