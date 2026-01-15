**V3 Provenance Status:** Passive infrastructure complete. Provenance tracking exists but is not yet actively consumed by Response Parser, Clarification Parser, or forced resolution logic.

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
