Below is a proposal for an architectural plan for migrating the Response Parser (RP) from an LLM-centric design to an encoder-first, gated, hybrid system

### 1. Goals

Reduce latency and VRAM contention by using encoders and avoiding LLM calls on most turns
Improve determinism and observability of extraction decisions
Scale from ~10 selected potential fields for extraction to whole ruleset without linear latency growth
Preserve existing deterministic clinical logic and episode handling
Keep LLMs only where semantic interpretation is genuinely required

### 2. Conceptual reframing of the Response Parser

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

### 3. Architecture
Old architecture:
Dialogue_manager_v2.py (orchestrator) calls prompt_builder.py to create an LLM prompt from information (QuestionOutput dataclass) from the question_selector_v2.py module
Hands this to the response_parser_v2.py
Receives output

Proposed architecture:
clinical_extractor_encoder.py (signal output only, fast)
Loads ClinicalBERT
Loads the HeadMatrix (the specific field weights).
Runs BERT(text) * Matrix.
Output: RawPredictions (A dictionary or dataclass of logits/probabilities for every supported field).
clinical_extractor_llm.py (signal output only, slow)
Wraps the LLM (Mistral/HuggingFace).
Receives EscalationRequest, builds a prompt only for missing fields, calls LLM.
Output: LLMData.
Dependencies: prompt_builder.py builds prompt from QuestionOutput dataclass (from question selector), hf_client_v2.py (model loading and inference wrapper), prompt_formatter.py (Model-specific prompt formatting)
clinical_extractor_logic.py (decision logic)
Loads ruleset_v2.json (to know valid fields).
Receives RawPredictions
Applies gating logic
Applies Thresholds (e.g., "Score > 0.8 is a match").
Identifies Gaps (e.g., "Onset is complex, FastExtractor failed/was gated").
Output: ExtractionResult (High confidence data) + EscalationRequest (What is missing).
response_parser_v2.py
New responsibility: no longer signal producer, acts as the dialogue manager’s sub-orchestrator
Dialogue manager at risk of becoming very large if it has to individually call all the modules - thousands of lines and dozens of modules
response_parser_v2.py takes some of that orchestration responsibility - dialogue manager simply asks for clinical extraction output and gets it, no need to know how or which modules were involved
Old response_parser_v2.py already had an API with the dialogue_manager_v2.py which returned clinical extraction - this can be largely preserved

### 4. Field taxonomy

Before any code or training, classify every ruleset field into one of these buckets.

A. Direct encoder extraction
Fields that can be safely extracted by heads:
Boolean flags (present / absent)
Closed categorical fields (laterality, location buckets)
Simple ordinal categories (worsening / stable)
Default: encoder head only

B. Encoder-gated LLM extraction

Fields that are hard to normalize but easy to detect:
Temporal onset
Pain character (fine-grained)
Free-text qualifiers
Pattern:
Encoder head answers: “is relevant information present?”
If false → do nothing
If true → call LLM for that field only

### 5. Multi-stage inference flow

Stage 0: Pre-conditions
user utterance
current question context
allowed field set (from Question Selector)

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
Logic for gating lives in one place, the ruleset - import the gating logic from the ruleset through a new schema adapter
This avoids duplication of authority - if the ruleset logic changes, the clinical extraction gating logic does not need to be updated

Stage 4: LLM escalation decision
Evaluate gating heads: e.g. pain_character_described == True
For each gated field, call LLM (clinical_extractor_llm.py)
LLM calls are individual field-specific

Stage 5: Output assembly
encoder-extracted fields
LLM-extracted fields (if any)
Attach provenance: encoder vs LLM
gating rationale
Return to Dialogue Manager as current RP output

### 6. Model strategy

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

Fine-tuning policy
Phase 1: no fine-tuning
Phase 2: head-only fine-tuning
Phase 3 (selective): partial encoder fine-tuning of needed (possibly for ambiguity detection only)

### 7. Data strategy

Label sources
Use a cheap, high-intelligence API (e.g., GPT-4o-mini or Claude 3.5 Haiku) to process your raw logs offline and generate the "Ground Truth" labels.
Train ClinicalBERT on these high-quality synthetic labels.
Why: It costs pennies to generate 10k examples via API, and ensures your local model learns from SOTA performance, not 7B limitations.
Real/messy user data is helpful but not essential in the same way that it is for LLM fine tuning


Data quality requirements
Clinical extraction heads:
coverage > realism
Gating heads:
high recall preferred
Need for dialogue-level data is not yet established, may need experimental proof

### 8. Migration plan

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

### 9. Observability and guardrails
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

### 10. End state

Most turns incur:
1 encoder pass
10–30 head evaluations
0 LLM calls

LLM is used sparingly, intentionally and observably
RP latency is low and predictable
Adding a new field:
does not meaningfully increase latency
does not require prompt surgery


### 11. Optimisation (after completion)
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

### 12. Episode ambiguity detection (out of scope of this plan)

Short-term
Keep existing LLM ambiguity detector: episode_hypothesis_generator.py which outputs hypothesis_count (0 / 1 / >1), pivot_detected (bool) and confidence scores for both
Run it in parallel with encoder RP

Long-term target (after clinical extraction updates completed)
Create shared encoder episode ambiguity detection model
Two core heads:
hypothesis_count (0 / 1 / >1)
pivot_detected (bool)
Evaluate encoder based vs LLM based

Likely requires:
head training
partial encoder fine-tuning (top layers only) or adapters as it is a unique task
