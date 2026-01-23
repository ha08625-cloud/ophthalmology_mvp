"""
Semantic contracts for ophthalmology consultation system.

This module defines immutable data structures that serve as contracts
between modules. These are NOT validators - they define shape and
semantics without enforcing rules.

Design principles:
- Frozen dataclasses (immutable after creation)
- No validation logic (contracts, not validators)
- No dependencies on other modules
- Definition layer only (no enforcement)

Contents:
- ValueEnvelope: Ingress-time wrapper for extracted values with provenance
- QuestionOutput: Immutable question representation from Question Selector

Usage:
    from backend.contracts import ValueEnvelope, QuestionOutput
"""

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class ValueEnvelope:
    """
    Semantic wrapper for values entering the system.
    
    ValueEnvelope captures provenance metadata at the moment of extraction,
    before values enter the State Manager. This enables traceability without
    coupling extraction logic to storage logic.
    
    Lifecycle:
    1. Created by: Response Parser (at extraction time)
    2. Passed through: Dialogue Manager (treated as opaque payload)
    3. Consumed by: State Manager (collapsed into provenance at write time)
    4. Never seen by: Question Selector, JSON Formatter, Summary Generator
    
    The State Manager owns the responsibility for:
    - Preserving metadata (collapsed into existing provenance system)
    - Unwrapping at export boundaries (export_clinical_view, export_for_summary)
    
    Attributes:
        value: The extracted clinical value (any type: str, bool, int, list, etc.)
        source: Origin identifier indicating where this value came from.
                Standard sources: 'response_parser', 'user_explicit', 
                'clarification_parser', 'derived', 'system'
        confidence: Confidence score 0.0-1.0 (default 1.0).
                    Will be converted to confidence band (high/medium/low)
                    by State Manager at write time.
    
    Examples:
        >>> envelope = ValueEnvelope(
        ...     value='right',
        ...     source='response_parser',
        ...     confidence=0.95
        ... )
        >>> envelope.value
        'right'
        >>> envelope.source
        'response_parser'
        
        # Immutability enforced
        >>> envelope.value = 'left'  # Raises FrozenInstanceError
    
    Note:
        ValueEnvelope is intentionally minimal. Additional metadata
        (timestamps, turn_id, etc.) lives in parse_metadata or is
        added by State Manager at write time.
    """
    value: Any
    source: str
    confidence: float = 1.0


@dataclass(frozen=True)
class QuestionOutput:
    """
    Immutable question representation returned by Question Selector.
    
    QuestionOutput is the complete specification for a question, containing
    everything needed by downstream consumers (primarily Prompt Builder for
    Response Parser). The Dialogue Manager passes this through unchanged.
    
    Replaces raw dict returns for:
    - Type safety (IDE autocomplete, static analysis)
    - Immutability (prevents accidental mutation)
    - Explicit semantics (clear attribute names)
    
    This is a pure data structure with no methods or validation.
    The Question Selector is responsible for populating it correctly.
    
    Attributes:
        id: Question identifier (e.g., 'vl_3', 'h_2', 'cp_5').
            Format: {symptom_prefix}_{number}
        question: Question text shown to user.
            Example: "Is the vision loss in one eye or both eyes?"
        field: Target field name for extracted data (used as JSON key).
            Example: 'vl_laterality', 'h_duration'
        field_type: Data type hint for the field.
            Values: 'text', 'boolean', 'categorical'
            Default: 'text'
        type: Question classification.
            Values: 'probe' (always asked), 'conditional' (depends on prior answers)
            Default: 'probe'
        valid_values: Allowed values for categorical fields.
            Tuple (not list) to ensure immutability.
            None for free-text and boolean fields.
            Example: ('sudden', 'gradual', 'unsure')
        field_label: Human-readable semantic label for the field.
            Used by Prompt Builder to explain field meaning to LLM.
            Example: 'visual loss laterality'
        field_description: Detailed description of what the field captures.
            Used by Prompt Builder to guide extraction.
            Example: 'Which eye or eyes are affected by the visual loss'
        definitions: Value definitions for categorical fields.
            Maps valid_values to human-readable explanations.
            Used by Prompt Builder to help LLM understand value semantics.
            Example: {'sudden': 'seconds to minutes', 'gradual': 'hours to days'}
            None if not applicable or not provided in ruleset.
    
    Examples:
        >>> q = QuestionOutput(
        ...     id='vl_3',
        ...     question='Which eye is affected?',
        ...     field='vl_laterality',
        ...     field_type='categorical',
        ...     type='conditional',
        ...     valid_values=('left', 'right', 'both'),
        ...     field_label='visual loss laterality',
        ...     field_description='Which eye or eyes are affected by the visual loss',
        ...     definitions=None
        ... )
        >>> q.id
        'vl_3'
        >>> q.valid_values
        ('left', 'right', 'both')
        >>> q.field_label
        'visual loss laterality'
        
        # Attribute access (not dict access)
        >>> q['id']  # TypeError - not subscriptable
        >>> q.id     # Correct
        'vl_3'
    
    Note:
        - valid_values is a Tuple, not a List, to maintain immutability.
          When creating from ruleset dict, convert with tuple(list_value).
        - definitions uses Tuple[Tuple[str, str], ...] instead of Dict for
          immutability. Convert with tuple((k, v) for k, v in dict.items()).
    """
    id: str
    question: str
    field: str
    field_type: str = "text"
    type: str = "probe"
    valid_values: Optional[Tuple[str, ...]] = None
    field_label: Optional[str] = None
    field_description: Optional[str] = None
    definitions: Optional[Tuple[Tuple[str, str], ...]] = None
