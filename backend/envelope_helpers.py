"""
Envelope manipulation utilities.

Pure functions for working with ValueEnvelope objects.
These are mechanical operations with no domain knowledge.

Design principles:
- Pure functions (no side effects)
- No domain logic (doesn't know about episodes, fields, etc.)
- Recursive handling of nested structures
- Safe for any data type

Contents:
- strip_envelopes(): Recursively remove envelopes from data structures
- is_envelope(): Type check for ValueEnvelope
- unwrap(): Single-value unwrap (envelope or passthrough)

Usage:
    from backend.utils.envelope_helpers import strip_envelopes, unwrap
    
    # Strip all envelopes from nested structure
    clean_data = strip_envelopes(data_with_envelopes)
    
    # Unwrap single value (safe for both envelopes and raw values)
    raw_value = unwrap(possibly_enveloped_value)
"""

from typing import Any

# Flat import for server testing
# When copying to local, adjust to: from backend.contracts import ValueEnvelope
try:
    from backend.contracts import ValueEnvelope
except ImportError:
    from contracts import ValueEnvelope


def strip_envelopes(data: Any) -> Any:
    """
    Recursively strip ValueEnvelope wrappers, returning raw values.
    
    Used by State Manager at export boundaries to produce
    envelope-free output for legacy consumers (JSON Formatter,
    Summary Generator).
    
    Handles nested structures:
    - ValueEnvelope -> unwrapped value
    - dict -> recursively processed dict
    - list -> recursively processed list
    - tuple -> recursively processed tuple (preserves type)
    - set -> recursively processed set
    - Other types -> returned unchanged
    
    Args:
        data: Any data structure. Can be:
            - ValueEnvelope (will be unwrapped)
            - dict with envelope values (values will be unwrapped)
            - list/tuple/set containing envelopes (items will be unwrapped)
            - Nested combinations of the above
            - Any other type (returned unchanged)
    
    Returns:
        Same structure with all ValueEnvelope objects replaced by their .value
        
    Examples:
        >>> from contracts import ValueEnvelope
        
        # Single envelope
        >>> strip_envelopes(ValueEnvelope(value='right', source='parser'))
        'right'
        
        # Dict with envelope values
        >>> strip_envelopes({
        ...     'a': ValueEnvelope(value=1, source='x'),
        ...     'b': 2
        ... })
        {'a': 1, 'b': 2}
        
        # Nested structure
        >>> strip_envelopes({
        ...     'episodes': [
        ...         {'vl_laterality': ValueEnvelope(value='left', source='p')}
        ...     ]
        ... })
        {'episodes': [{'vl_laterality': 'left'}]}
        
        # Non-envelope data passes through unchanged
        >>> strip_envelopes({'a': 1, 'b': 'text'})
        {'a': 1, 'b': 'text'}
    
    Note:
        This function creates new containers (dict, list, etc.) rather than
        mutating the input. The input data structure is not modified.
    """
    if isinstance(data, ValueEnvelope):
        return data.value
    
    if isinstance(data, dict):
        return {k: strip_envelopes(v) for k, v in data.items()}
    
    if isinstance(data, list):
        return [strip_envelopes(item) for item in data]
    
    if isinstance(data, tuple):
        return tuple(strip_envelopes(item) for item in data)
    
    if isinstance(data, set):
        return {strip_envelopes(item) for item in data}
    
    # All other types (str, int, bool, None, etc.) pass through unchanged
    return data


def is_envelope(value: Any) -> bool:
    """
    Check if a value is a ValueEnvelope.
    
    Use this instead of isinstance() checks to keep the envelope
    type encapsulated within this module.
    
    Args:
        value: Any value to check
        
    Returns:
        True if value is a ValueEnvelope instance, False otherwise
        
    Examples:
        >>> is_envelope(ValueEnvelope(value='x', source='y'))
        True
        >>> is_envelope('x')
        False
        >>> is_envelope(None)
        False
    """
    return isinstance(value, ValueEnvelope)


def unwrap(value: Any) -> Any:
    """
    Unwrap a single value if it's an envelope, otherwise return unchanged.
    
    This is the canonical helper for code that needs to accept both
    envelopes and raw values. It provides a uniform interface regardless
    of whether the value is wrapped.
    
    Unlike strip_envelopes(), this does NOT recurse into containers.
    Use this for single values, strip_envelopes() for data structures.
    
    Args:
        value: ValueEnvelope or any other value
        
    Returns:
        envelope.value if value is an envelope, otherwise value unchanged
        
    Examples:
        >>> unwrap(ValueEnvelope(value='right', source='parser'))
        'right'
        >>> unwrap('right')
        'right'
        >>> unwrap(None)
        None
        >>> unwrap({'key': ValueEnvelope(value=1, source='x')})
        {'key': ValueEnvelope(value=1, source='x')}  # Does NOT recurse
    
    Note:
        For nested structures, use strip_envelopes() instead.
        unwrap() is intentionally non-recursive for clarity and performance
        when you know you're dealing with a single value.
    """
    if isinstance(value, ValueEnvelope):
        return value.value
    return value


def extract_envelope_metadata(value: Any) -> dict | None:
    """
    Extract metadata from a ValueEnvelope without unwrapping the value.
    
    Useful for logging or debugging when you need to inspect envelope
    properties without consuming the envelope.
    
    Args:
        value: ValueEnvelope or any other value
        
    Returns:
        dict with 'source' and 'confidence' if value is an envelope,
        None otherwise
        
    Examples:
        >>> extract_envelope_metadata(ValueEnvelope(value='x', source='parser', confidence=0.9))
        {'source': 'parser', 'confidence': 0.9}
        >>> extract_envelope_metadata('x')
        None
    """
    if isinstance(value, ValueEnvelope):
        return {
            'source': value.source,
            'confidence': value.confidence
        }
    return None
