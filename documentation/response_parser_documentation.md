# Response Parser Documentation

**Module:** `response_parser_v2.py`  
**Role:** Natural language understanding via LLM  
**Key characteristic:** Language task, not medical logic

## Overview

The Response Parser extracts structured clinical fields from patient natural language responses using an LLM. It is a stateless module that receives a question context and user response, calls the HuggingFace model, and returns extracted fields with metadata.

The parser does not interpret medical meaning or make clinical decisions. It performs language extraction only.

## Responsibilities

- Extract structured clinical fields from patient's natural language response
- Call HuggingFace LLM to perform extraction
- Map natural language to standardised values
- Handle ambiguous or unclear responses
- Return extracted fields with provenance metadata
- Support multi-field extraction from single response (metadata window)

## Input Parameters

```python
def parse(
    question: dict,                           # Current question from Question Selector
    patient_response: str,                    # User's text input
    turn_id: str | None = None,               # Turn identifier (e.g., "turn_005")
    next_questions: list[dict] | None = None, # Next 3 questions for metadata window
    symptom_categories: list[str] | None = None,  # Gating question fields
    mode: ExtractionMode = ExtractionMode.NORMAL_EXTRACTION  # V3.1: Extraction mode
) -> ParseResult
```

### Parameter Details

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | dict | Yes | Current question dict with id, question, field, field_type, valid_values |
| `patient_response` | str | Yes | Raw user input text |
| `turn_id` | str | No | Turn identifier for provenance tracking |
| `next_questions` | list[dict] | No | Next 3 questions for metadata window |
| `symptom_categories` | list[str] | No | Symptom category fields (e.g., 'vl_present') |
| `mode` | ExtractionMode | No | Extraction mode flag (V3.1) |

### Question Dict Structure

```python
{
    'id': str,           # Question identifier (e.g., 'vl_3')
    'question': str,     # Question text shown to user
    'field': str,        # Target field name (e.g., 'vl_laterality')
    'field_type': str,   # Type: 'string', 'boolean', 'enum', etc.
    'valid_values': list # Optional: allowed values for enums
}
```

## Output Structure

```python
{
    'outcome': str,           # success | partial_success | unclear | extraction_failed | generation_failed
    'fields': dict,           # Extracted field-value pairs
    'parse_metadata': dict    # Extraction metadata and provenance
}
```

### Outcome Values

| Outcome | Meaning |
|---------|---------|
| `success` | Primary field extracted successfully |
| `partial_success` | Some fields extracted, validation warnings present |
| `unclear` | User response was unclear (early return, no LLM call) |
| `extraction_failed` | LLM output could not be parsed |
| `generation_failed` | LLM call failed (timeout, OOM, etc.) |

### Parse Metadata Structure

```python
{
    'expected_field': str,        # Primary field being extracted
    'question_id': str,           # Question identifier
    'turn_id': str | None,        # Turn identifier for provenance
    'extraction_mode': str,       # V3.1: 'normal_extraction' or 'replay_extraction'
    'timestamp': str,             # ISO format timestamp
    'raw_llm_output': str | None, # Raw LLM response
    'error_message': str | None,  # Error details if failed
    'error_type': str | None,     # Exception type if failed
    'unexpected_fields': list,    # Fields extracted not in metadata window
    'validation_warnings': list,  # Non-fatal validation issues
    'normalization_applied': list # Boolean/value normalizations applied
}
```

## Multi-Question Metadata Window (V3)

The metadata window allows the parser to extract multiple fields from a single user response when the patient mentions information relevant to upcoming questions.

### How It Works

1. Dialogue Manager passes `next_questions` (next 3 questions) and `symptom_categories` (gating fields)
2. Parser builds extended prompt with metadata for current + next 3 questions + all symptom categories
3. LLM extracts any mentioned fields, not just the primary field
4. All extracted fields are returned in the `fields` dict

### Example

```python
# User says "right eye, started yesterday" when asked about laterality
parse(
    question={'id': 'vl_5', 'field': 'vl_laterality', ...},
    patient_response='Right eye, started yesterday',
    turn_id='turn_05',
    next_questions=[
        {'id': 'vl_6', 'field': 'vl_first_onset', ...},
        {'id': 'vl_7', 'field': 'vl_pattern', ...}
    ]
)

# Returns:
{
    'outcome': 'success',
    'fields': {
        'vl_laterality': 'right',      # Primary field
        'vl_first_onset': 'yesterday'   # Extracted from metadata window
    },
    'parse_metadata': {...}
}
```

## Extraction Mode (V3.1)

The `mode` parameter supports instrumentation and provenance tracking for replay extraction.

### ExtractionMode Enum

```python
class ExtractionMode(str, Enum):
    NORMAL_EXTRACTION = "normal_extraction"   # Standard extraction from patient response
    REPLAY_EXTRACTION = "replay_extraction"   # Extraction from clarification replay transcript
```

### Behaviour

- The parser does not change behaviour based on mode
- Mode is echoed in `parse_metadata['extraction_mode']` for:
  - Logging and instrumentation
  - Provenance tracking
  - Future safeguards
- Default is `NORMAL_EXTRACTION` (backward compatible)

### Usage with RP Replay Adapter

When the `RPReplayAdapter` calls the parser after clarification resolution, it passes `mode=ExtractionMode.REPLAY_EXTRACTION`. This tags all extracted fields with replay provenance for downstream auditing.

## Value Standardisation

The parser normalises extracted values to canonical forms:

### Boolean Normalisation

| Input | Output |
|-------|--------|
| 'true', 'yes', 'y', '1', 't' | True |
| 'false', 'no', 'n', '0', 'f' | False |

### Laterality Mapping

| Natural Language | Canonical Value |
|-----------------|-----------------|
| "right eye", "right" | "monocular_right" |
| "left eye", "left" | "monocular_left" |
| "both eyes", "bilateral" | "binocular" |

## Error Handling

The parser uses a best-effort approach:

- Returns empty `fields` dict with metadata if extraction fails
- Logs errors but does not raise exceptions
- Consultation continues even if extraction fails
- Dialogue Manager may re-ask question or proceed

### Early Return for Unclear Responses

Pure unclear responses trigger early return without LLM call:

```python
UNCLEAR_PATTERNS = [
    "i don't know",
    "i'm not sure",
    "not sure",
    "unclear",
    "i can't remember",
    # etc.
]
```

## Integration Points

### Called By
- **Dialogue Manager:** During normal extraction (MODE_EPISODE_EXTRACTION)
- **RP Replay Adapter:** During clarification replay (MODE_CLARIFICATION exit)

### Dependencies
- **HuggingFace Client:** LLM inference
- **Question Selector:** Provides question metadata

### Does Not
- Write to state (stateless)
- Make clinical decisions
- Infer episode identity
- Resolve ambiguity

## Version History

| Version | Date | Changes |
|---------|------|---------|
| V2 | - | Initial multi-episode support |
| V3 | Jan 2026 | Multi-question metadata window |
| V3.1 | Jan 2026 | ExtractionMode enum, mode parameter for replay support |

## Related Modules

- `response_parser_replay.py` - Replay adapter that wraps this parser
- `rp_replay_input.py` - Boundary objects for replay input
- `dialogue_manager_v2.py` - Primary caller
- `hf_client_v2.py` - LLM client
