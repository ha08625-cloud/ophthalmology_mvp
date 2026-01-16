Summary
1.1 Response Parser: multi-question metadata window
1.2. Formalise Conversation Mode enum
1.3 Episode Hypothesis Signal data structure (stub only)
2.1 Clarification Transcript Buffer (data structure only)
2.2 Deterministic Evidence-Span Validator
2.3 Field-level provenance tagging (passive)
3.1 EHG stub with pivot detection plumbing
3.2 RP commit guard
4.1 RP replay input boundary objects and adapter

Tier 1: additive changes only, non breaking

Task 1.1 Response Parser: multi-question metadata window COMPLETED 

Work
Extend RP prompt construction to accept:
next_questions: [q1, q2, q3]
symptom_categories_present
Keep output contract unchanged.

Summary of changes and decisions
Question selector:
Added new method get_next_n_questions(current_question_id, n=3) to /mnt/project/question_selector_v2.py

Returns next n questions in sequence from same symptom category
Ignores all conditions (includes conditional questions)
Returns questions in numeric order
Does NOT wrap to next symptom category
Returns fewer than n if near end of category
Returns empty list if at end or invalid input
Returns deep copies (safe to mutate)

Response parser:
1. Extended parse() signature with two new optional parameters:
next_questions: List of upcoming question dicts (for extracting fields user mentions early)
symptom_categories: List of symptom field names (for discovery phase)
Both default to None → 100% backward compatible
2. Expanded prompt to include:
PRIMARY QUESTION section
ADDITIONAL CONTEXT section (next 3 questions)
SYMPTOM CATEGORIES section (all symptom present fields)
Instruction: "You MAY extract additional fields if clearly mentioned"
3. Updated validation logic:
Builds expected_fields set from: primary field + next_questions + symptom_categories
Only flags fields as "unexpected" if NOT in this set
Fields in metadata window are silently accepted (will be visible in future debug panel)

Dialogue_manager_v2.py:
Extract SYMPTOM_CATEGORIES  containing all 9 gating question fields from ruleset
Updated _process_regular_turn() to:
Call selector.get_next_n_questions(current_question_id, n=3) before parsing
Pass next_questions and symptom_categories to parser.parse()
Updated _process_transition_turn() to:
Pass next_questions=None (transition is meta-question, no context needed)
Pass symptom_categories (user might mention new symptoms when answering transition)

Task 1.2. Formalise Conversation Mode enum (no behaviour change yet)

Created conversation_modes.py with StrEnum + invariant docstring. Three modes: discovery, extraction and clarification

Update StateManager:

Add conversation_mode field (string storage)
Validate on from_snapshot() (fail-fast)
Default to MODE_DISCOVERY for missing field (backwards compat)

Update DialogueManager:

_handle_start(): Set mode to MODE_DISCOVERY explicitly
Add _determine_next_mode() with placeholder that returns current mode unchanged
Add sticky clarification comment
Thread mode through (no transitions yet)


Update turn_metadata: Include current mode for debugging
Added ConversationMode import (line ~32)

Imports ConversationMode from conversation_modes.py
Added _determine_next_mode() method (lines ~156-208)

Central authority for all mode transitions
Currently a no-op placeholder (returns current_mode unchanged)
Includes TypeError guardrail to catch corruption
Fully documented with invariants and TODO markers
Clarification exit authority explicitly documented

Updated _initialize_new_consultation() (lines ~497-508)

Sets initial mode explicitly to MODE_DISCOVERY
Added logging of initial mode

Updated _handle_turn_impl() (lines ~410-450)

Extracts current mode from state snapshot
Calls _determine_next_mode() (currently no-op)
Updates state_manager with next mode
Passes previous_mode to all helper methods

5. Updated _build_turn_result() (lines ~540-593)

Added previous_mode parameter
Detects mode changes
Adds conversation_mode and mode_changed to turn_metadata

6. Updated helper method signatures to accept and pass previous_mode:

_get_first_question() (lines ~602-661)
_process_regular_turn() (lines ~663-808)
_process_episode_transition() (lines ~814-933)

Task 1.3 Episode Hypothesis Signal data structure (stub only)

Define EpisodeHypothesisSignal dataclass / dict:

episode_hypothesis_signal.py module  created with:

ConfidenceBand enum (LOW, MEDIUM, HIGH)
EpisodeHypothesisSignal frozen dataclass with all four fields
no_ambiguity() class method for stub usage

Validation:
Type annotations only (Python dataclass validation)
Documented but not enforced hypothesis_count >= 0 (runtime enforcement belongs in consumer)
Documented semantic meanings of each field
Design notes:

Frozen dataclass (immutable after construction)
Clean separation: signal structure only, no logic
Ready for future expansion (provenance fields, raw_text, etc.)

Task 2.1 Clarification Transcript Buffer (data structure only)

The clarification transcript buffer is temporary storage for:
what it asked during clarification
what the patient replied
Without discarding it or committing it to the clinical record yet

Add a ClarificationTranscript object to state:

[
  {system_template_id, user_text, replayable}
]

Task 2.2 Deterministic Evidence-Span Validator

This is a key safety primitive and fully independent.

Work

Implement:

def validate_evidence_span(span: str, raw_text: str) -> bool

Case-insensitive, substring-exact

Task 2.3 Field-level provenance tagging (passive)
Add fields but don’t consume them yet.

Work
Allow state writes like:
value
provenance = {source, confidence, mode}
Default provenance for existing writes.

Why
Required for Limbo episodes and forced resolution
Retro-fitting provenance later is painful
No behaviour change yet

3.1 Pivot detection plumbing (without policy)

Work
Allow EHG stub to emit pivot_detected
DialogueManager logs it only


Why
Pivot is orthogonal to episode counting
Later logic becomes a simple switch
Avoids entangling pivot logic with clarification logic

3.2 RP commit guard” refactor

Refactor where RP writes, not when.

Work

Centralise all RP → State writes behind:

commit_allowed(mode)

Initially always returns True.


Why

Later ambiguity blocking becomes a one-line change

Prevents scattered if/else logic later