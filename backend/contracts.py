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
        field: Target field name for extracted data.
            Example: 'vl_laterality', 'h_duration'
        field_type: Data type hint for the field.
            Values: 'text', 'string', 'boolean', 'enum', 'integer', 'float'
            Default: 'text'
        type: Question classification.
            Values: 'probe' (always asked), 'conditional' (depends on prior answers)
            Default: 'probe'
        valid_values: Allowed values for enum/categorical fields.
            Tuple (not list) to ensure immutability.
            None for free-text fields.
            Example: ('sudden', 'gradual', 'unsure')
    
    Examples:
        >>> q = QuestionOutput(
        ...     id='vl_3',
        ...     question='Which eye is affected?',
        ...     field='vl_laterality',
        ...     field_type='enum',
        ...     type='conditional',
        ...     valid_values=('left', 'right', 'both')
        ... )
        >>> q.id
        'vl_3'
        >>> q.valid_values
        ('left', 'right', 'both')
        
        # Attribute access (not dict access)
        >>> q['id']  # TypeError - not subscriptable
        >>> q.id     # Correct
        'vl_3'
    
    Note:
        valid_values is a Tuple, not a List, to maintain immutability.
        When creating from ruleset dict, convert with tuple(list_value).
    """
    id: str
    question: str
    field: str
    field_type: str = "text"
    type: str = "probe"
    valid_values: Optional[Tuple[str, ...]] = None
