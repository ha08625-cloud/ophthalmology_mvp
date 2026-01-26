<CONTEXT>

Below is the architectural plan for migrating the Response Parser (RP) from an LLM-centric design to an encoder-first, gated, hybrid system
1. Goals

Reduce latency and VRAM contention by using encoders and avoiding LLM calls on most turns
Improve determinism and observability of extraction decisions
Scale from ~10 selected potential fields for extraction to whole ruleset without linear latency growth
Preserve existing deterministic clinical logic and episode handling
Keep LLMs only where semantic interpretation is genuinely required
2. Conceptual reframing of the Response Parser

Current model

> “Response Parser = one LLM call that extracts a bundle of fields”

Prompt (for single field/question):
    System role  
    field_id: str          # e.g., "vl_onset_speed" (used as JSON key)
    label: str             # e.g., "visual loss onset speed" (semantic meaning)
    description: str       # e.g., "how quickly visual loss developed"
    field_type: FieldType  # categorical | boolean | text
    valid_values: Optional[List[str]] = None      # Required for categorical
    definitions: Optional[Dict[str, str]] = None  # Optional value definitions
    Question and user utterance

Current RP:
Includes the above fields for the current question and associated field, the next three fields and the symptom categories (e.g. headache_present, eye_pain_present, hallucinations_present etc)
Around 10 potential fields to extract
Every additional field included in the prompt increases latency and reduces accuracy

The question ruleset contains approximately 150 questions/fields divided across 15 symptom categories

New mental model

> “Response Parser = an execution graph of small decisions, with LLM escalation as a fallback”

3. Architecture
Old architecture:
Dialogue_manager_v2.py (orchestrator) calls prompt_builder.py to create an LLM prompt from information (QuestionOutput dataclass) from the question_selector_v2.py module
Hands this to the response_parser_v2.py
Receives output

Proposed architecture:
clinical_extractor_encoder.py (signal output only, fast)
Loads ClinicalBERT
Loads the HeadMatrix (the specific field weights).
Runs BERT(text) * Matrix.
Output: EncoderOutput (dataclass of logits/probabilities for every supported field).
clinical_extractor_llm.py (signal output only, slow)
Wraps the LLM (Mistral/HuggingFace).
Receives EscalationRequest, builds a prompt, calls LLM.
Output: LLMOutput
Dependencies: prompt_builder.py builds prompt from QuestionOutput dataclass (from question selector), hf_client_v2.py (model loading and inference wrapper), prompt_formatter.py (Model-specific prompt formatting)
clinical_extractor_logic.py (decision logic)
Loads ruleset_v2.json (to know valid fields).
Receives EncoderOutput
Applies gating logic
Applies Thresholds (e.g., "Score > 0.8 is a match").
Identifies Gaps (e.g., "Onset is complex, FastExtractor failed/was gated").
Output: ClinicalExtractionResult (High confidence data) + LLMEscalationRequest (What is missing).
response_parser_v2.py
New responsibility: no longer signal producer, acts as the dialogue manager’s sub-orchestrator
Dialogue manager at risk of becoming very large if it has to individually call all the modules - thousands of lines and dozens of modules
response_parser_v2.py takes some of that orchestration responsibility - dialogue manager simply asks for clinical extraction output and gets it, no need to know how or which modules were involved
Old response_parser_v2.py already had an API with the dialogue_manager_v2.py which returned clinical extraction - this can be largely preserved
4. Field taxonomy

Before any code or training, classify every ruleset field into one of these buckets.

A. Direct encoder extraction (default)
Fields that can be safely extracted by heads:
Boolean flags (present / absent)
Closed categorical fields (laterality, location buckets)
Simple ordinal categories (worsening / stable)

B. Encoder-gated LLM extraction (minority)
Fields that are hard to normalize but easy to detect:
Temporal onset
Pain character (fine-grained)
Free-text qualifiers
Pattern:
Encoder head answers: “is relevant information present?”
If false → do nothing
If true → call LLM for that field only
Place invariant in code: LLM-gating heads never write to state
5. Multi-stage inference flow

Stage 0: Extraction module inputs
The current response parser already has a prompt system
The question selector gives a QuestionOutput frozen dataclass that includes:
    id: str
    question: str
    field: str
    field_type: str = "text"
    type: str = "probe"
    valid_values: Optional[Tuple[str, ...]] = None
    field_label: Optional[str] = None
    field_description: Optional[str] = None
    definitions: Optional[Tuple[Tuple[str, str], ...]] = None
The prompt_builder.py module turns this into a prompt for the LLM
We can repurpose most of this system for clinical_extractor_encoder.py and clinical_extractor_llm.py

Stage 1: Shared encoder pass
Run encoder once on the user utterance
Cache representation for the turn

Stage 2: Primary heads (always-on, run in parallel)
Current question’s primary field head
All field heads for the current symptom category
Global symptom category heads (e.g. headache_present, eye_pain_present)
Outputs: Candidate extractions, gating signals, confidence scores

Stage 3: Conditional fan-out (secondary heads)
For each symptom category detected as present:
Trigger a symptom-specific head group
Example:
if headache_present == True:
    run headache_location
    run headache_duration
    run headache_severity
    etc
Logic for symptom category gating lives in one place, the ruleset - import the symptom category gating logic from the ruleset through a new schema adapter
Avoids duplication of authority - if the ruleset logic changes, the clinical extraction gating logic does not need to be updated
Test: if symptom category present == False, no secondary heads should be run

Stage 4: LLM escalation decision
Evaluate LLM-gating heads: e.g. pain_character_described == True
For each LLM-gated field, call LLM (clinical_extractor_llm.py)
LLM calls are narrower than previous design: single field by default, a small number of semantically closely related fields in certain specific cases
For example: pain character, pain radiation, pain modifiers may all be extracted in one LLM call - latency cost minimal, accuracy cost minimal
Will need to add schema-driven bundles to ruleset e.g.
"extraction_group": "pain_complex",
"fields": ["pain_character", "pain_radiation", "pain_severity", "pain_aggravating_factors"]
Members of one group should ONLY be LLM-gated, no encoder-extracted fields should be mixed in

Stage 5: Output assembly
encoder-extracted fields
LLM-extracted fields (if any)
Attach provenance: encoder vs LLM
gating rationale
Return to Dialogue Manager as current RP output

6. Model strategy

Encoder choice
Start with Bio_ClinicalBERT
Base size only
FP16 inference
Single encoder instance per RP

Head strategy
One head per field
No multi-field heads

Head types:
binary (sigmoid)
categorical (softmax)
Note: prevent head explosion through software entropy - consider strict typing through code e.g.
class HeadType(Enum):
    BINARY_EXISTENCE = "binary_existence"  # Sigmoid, threshold > X
    CATEGORICAL = "categorical"            # Softmax over N classes
    # No other types allowed

Ontology drift
Rulesets evolve semantically, not just structurally.
Encoder heads will silently learn an older meaning of a field
Heads MUST:
declare which ruleset version they were trained against
Field_definition_hash
Code runtime compatibility check now but disable while still prototyping
Runtime compatibility check: If current ruleset field definition hash ≠ head hash → head auto-disabled → escalate to LLM

Fine-tuning policy
Phase 1: no fine-tuning
Phase 2: head-only fine-tuning
Phase 3 (selective): partial encoder fine-tuning of needed (possibly for ambiguity detection only)
7. Data strategy

Label sources
Use a cheap, high-intelligence API (e.g., GPT-4o-mini or Claude 3.5 Haiku) to process your raw logs offline and generate the "Ground Truth" labels.
Train ClinicalBERT on these high-quality synthetic labels.
Why: It costs pennies to generate 10k examples via API, and ensures your local model learns from SOTA performance, not 7B limitations
However, LLM hallucination is a known risk
Adversarial negative sampling and cross-model disagreement checks will be necessary
Explicit “unknown / unextractable” labels should be included
Real/messy user data is helpful but not essential in the same way that it is for LLM fine tuning

Data quality requirements
Clinical extraction heads:
coverage > realism
Gating heads:
high recall preferred
8. Migration plan

Phase 1 — Shadow encoder RP
Implement encoder RP in parallel
Do not write state from it
Compare and evaluate outputs with LLM RP
unnecessary LLM calls avoided

Phase 2 — Encoder takes primary role
Encoder RP becomes authoritative for:
Boolean fields
categorical fields
LLM used only when gated

Phase 3 — Expand field coverage
Gradually add more heads
Add secondary fan-out per symptom
Monitor latency and failure modes
9. Observability and guardrails
Add:
Per-turn inference trace:
which heads ran
which gates fired
why LLM was or wasn’t called
Provenance tags on every extracted field

Hard invariants to test:
category false → subordinate fields suppressed
gating heads never write state

Without this, the system will become opaque very quickly.

10. Output contract
Current response parser output contract is the dataclass ValueEnvelope defined in contracts.py which currently includes:
    value: Any
    source: str
    confidence: float = 1.0 (default as response parser currently does not output confidence score)
This will need to be updated.  May need to include:
Field value
Confidence
Source (encoder / LLM)
Gating rationale
Episode safety status
Ruleset version
Head version
11. Proposed Failure Policy:
Encoder Failure (Runtime): If ClinicalBERT fails (rare, but possible with VRAM issues), Fail Open. Log the error, and route the entire turn to the LLM (legacy mode). It's slower, but the consultation continues.
LLM Failure (API/Network): Fail Soft. If the LLM times out, return an empty extraction for those fields. The QuestionSelector will likely just ask the question again or move on. Do not crash the app.
Gating Failure: If the gating logic is ambiguous (e.g., confidence 0.49 vs threshold 0.50), Escalate. Bias towards triggering the LLM rather than missing data
12. End state

Most turns incur:
1 encoder pass
10–30 head evaluations
0 LLM calls

LLM is used sparingly, intentionally and observably
RP latency is low and predictable
Adding a new field:
does not meaningfully increase latency
does not require prompt surgery

13. Optimisation (after completion)
At inference time:
instead of calling each head individually
stack weight vectors into a single matrix
and do one matrix multiply
Mathematically:
embedding:        [1, 768]
head_weights:     [768, N]
logits:           [1, N]
Equivalent to running N independent linear heads, provided:
heads are linear (no hidden layers)
no head-specific preprocessing
no head-specific postprocessing beyond sigmoid/softmax
Big latency win
One matmul instead of 150 Python calls
GPU stays hot
Kernel launch overhead amortized
CPU–GPU synchronization minimized
One [1,768] × [768,150] matmul is essentially free
Cost difference vs one head is negligible
You do not lose gradient isolation if:
heads are trained independently
stacking happens only at inference
each head still has its own loss
gradients do not interact
Heterogeneity issue
Some heads are sigmoid, some softmax
Some heads have 2 classes, some have 4
Some heads are gating-only, others write state
We’ll need:
metadata per head:
activation type
thresholding rules
whether output is authoritative or gating


a mask over the logits vector
a list of “active heads” per turn
a way to gather their weights
a way to scatter the results back
Instead of one [768, 150] matrix, you may want:
one matrix for Boolean heads
one matrix for 3-class heads
one matrix for 4-class heads
Two-tier batching (recommended)
Given your architecture, the cleanest approach is:
Tier 1: Conceptual API
Each head is an object:
name
type
Threshold
Semantics
Training and testing happen per-head
Tier 2: Execution engine
At inference:
collect active heads
group by compatible type
batch matmul
scatter outputs back to head objects
14. Episode ambiguity detection experimentation (out of scope of this plan)

Short-term
Keep existing LLM ambiguity detector: episode_hypothesis_generator.py which outputs hypothesis_count (0 / 1 / >1), pivot_detected (bool) and confidence scores for both
Episode_safety_status.py interprets signal and outputs SAFE_TO_EXTRACT, AMBIGUOUS_MULTIPLE or AMBIGUOUS_PIVOT
Response parser output is written or discarded depending on safety signal
When the new plan is implemented, the output from the clinical_extractor_encoder.py and clinical_extractor_llm.py should be treated in the same way: discarded if AMBIGUOUS and written if SAFE

Long-term target (after clinical extraction updates completed)
Create shared encoder episode ambiguity detection model
Two core heads:
hypothesis_count (0 / 1 / >1)
pivot_detected (bool)
Evaluate encoder based vs LLM based

Likely requires:
head training
partial encoder fine-tuning (top layers only) or adapters as it is a unique task

15. Known deferred issues
In the prototype stage where we are building features for a high level proof of concept, we will note certain issues but defer solving them.  This will be a step by step process - the decision is not whether to include these changes (they must be included) but WHEN to include them in the refactor
Explicit confidence calibration strategy
Encoder logits are not calibrated by default.
Head-only fine-tuning worsens calibration.
Temperature scaling or Platt scaling per head.
Stored calibration metadata alongside head weights.
Otherwise thresholds are arbitrary and brittle
Future version updates
See planned_updates.md
Selective state injection and contradiction detection were already planned updates
Selective state injection beyond the immediate questions and answer may be necessary for certain heads to extract information reliably
This will be a multi-stage process with varying levels of difficulty: previous question and previous extracted value is easy to inject, co-reference resolution will require major work
Contradiction detection will require the ValueEnvelope to contain derivation = EXPLICIT | NORMALIZED | INFERRED
</CONTEXT>

Implementation plan
Phase 1 — Structural scaffolding
Goal: Build the new execution graph without real models.
Introduce module skeletons (empty implementations) COMPLETE
clinical_extractor_encoder.py
clinical_extractor_logic.py
clinical_extractor_llm.py
Each returns deterministic fake outputs.
Define core dataclasses COMPLETE
EncoderOutput
ClinicalExtractionResult
LLMEscalationRequest
Extend (not replace) ValueEnvelope usage.
Move orchestration into Response Parser COMPLETE
response_parser_v2.py now:
Calls encoder stub
Calls logic stub
Optionally calls LLM stub
Dialogue Manager calls to prompt builder removed.

Add per-turn inference trace (logging only)
Which “heads” ran (fake)
Which gates fired (fake)
No metrics, no dashboards, just structured logs.
Phase 2 — Ruleset-driven field taxonomy
Goal: Make extraction decisions data-driven, not prompt-driven.
Annotate ruleset with extraction metadata
For each field:
extraction_mode: encoder | llm_gated | llm_only
Optional extraction_group
Symptom category membership (already exists implicitly)
Write a schema adapter
Converts ruleset_v2.json → internal extraction config.
Single source of truth for:
Which heads exist
Which heads are gated
Which heads fan-out conditionally
Hard-fail on schema violations
Field marked encoder but has free text → error.
Field in extraction_group but mixed encoder/LLM → error.
Still no ML. Just configuration correctness.

Phase 3 — Encoder integration (read-only, shadow mode)
Goal: Introduce ClinicalBERT without risk.
Load encoder once per turn
FP16
Cache embedding for the turn.
Implement head registry
One object per field:
name
type
threshold
writes_state: bool
ruleset_version_hash
Run encoder heads in shadow
Compute logits
Do not write to state
Compare encoder vs LLM outputs offline.
Add compatibility guard
If ruleset hash ≠ head hash → auto-disable head → escalate.
This phase produces data, not behavior change.

Phase 4 — Gating logic goes live
Goal: Let encoders make real decisions for safe fields.
Enable encoder authority for
Boolean fields
Closed categorical fields
Simple ordinal fields
Keep LLM as fallback
Gating ambiguity
Disabled heads
Encoder runtime failure
Provenance tagging
Every field tagged:
encoder / llm
head version
gating rationale
At this point, latency and VRAM pressure drop immediately.

Phase 5 — Conditional fan-out and LLM narrowing
Goal: Stop paying for unused fields.
Implement symptom category fan-out
Category heads run first.
Secondary heads only run if category present.
Logic imported from ruleset adapter, not duplicated.
Introduce LLM extraction groups
Pain complex
Temporal onset
Other semantically coupled bundles
Reduce LLM prompt scope
Single field or tight group only.
No global symptom fishing.

Phase 6 — Performance consolidation
Goal: Make encoder inference essentially free.
Batch heads by type
Boolean sigmoid heads
3-class softmax heads
4-class softmax heads
Implement matrix stacking at inference
Gather active heads
Single matmul per head type
Scatter results back
Preserve per-head training isolation
Training remains independent.
Stacking is inference-only.

Phase 7 — Calibration and safety hardening
Goal: Make thresholds meaningful.
Add per-head calibration metadata
Temperature / Platt parameters
Stored with weights
Bias failure modes
Borderline → escalate
Missing → ask again
Never silently drop data

Phase 8 — Cleanup and deprecation
Goal: Remove architectural debt.
Delete prompt-based multi-field extraction
Simplify prompt_builder
Used only for LLM escalation paths.
Shrink Dialogue Manager
No conditional logic leaks upward.
