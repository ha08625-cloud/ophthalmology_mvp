"""
Evidence span validator for multi-episode intake system.

This module provides a safety-critical validation function that verifies
whether a span of text returned by an LLM actually exists in the original
user input. This prevents hallucination-based corruption of clinical data.

Design principles:
- Dumb, mechanical, predictable
- No semantic interpretation
- No fuzzy matching
- Fail safely (return False, never raise)
"""

import unicodedata


def validate_evidence_span(span: str, raw_text: str) -> bool:
    """
    Validate that a span exists as a substring in raw text.
    
    Rules:
    - Case-insensitive matching (using casefold)
    - Unicode normalized (NFKC)
    - Literal substring matching (punctuation, internal whitespace preserved)
    - Leading/trailing whitespace trimmed from span only
    - Returns False for any invalid input (None, empty, whitespace-only)
    
    Args:
        span: The text span to validate (typically from LLM output)
        raw_text: The original user input text
        
    Returns:
        True if normalized span exists as substring in normalized raw_text
        False otherwise (including all error cases)
    """
    # Check for None inputs
    if span is None or raw_text is None:
        return False
    
    # Check for empty after strip
    if span.strip() == "" or raw_text.strip() == "":
        return False
    
    # Unicode normalization (NFKC) + case folding
    span_norm = unicodedata.normalize('NFKC', span).casefold()
    text_norm = unicodedata.normalize('NFKC', raw_text).casefold()
    
    # Trim leading/trailing whitespace from span only
    span_norm = span_norm.strip()
    
    # Guard against pathological spans that become empty after normalization
    if len(span_norm) == 0:
        return False
    
    # Length check (after normalization)
    if len(span_norm) > len(text_norm):
        return False
    
    # Substring check
    return span_norm in text_norm
```

```python
"""
Unit tests for evidence_validator.py

Tests the validate_evidence_span function exhaustively to ensure
it behaves correctly as a safety-critical validation primitive.
"""

import pytest
from evidence_validator import validate_evidence_span


# Basic matching tests
def test_exact_match():
    """Exact match should pass"""
    assert validate_evidence_span("headache", "I have a headache") is True


def test_exact_match_same_string():
    """Span equal to raw_text should pass"""
    assert validate_evidence_span("headache", "headache") is True


def test_span_not_present():
    """Span not in text should fail"""
    assert validate_evidence_span("migraine", "I have a headache") is False


def test_partial_span_match():
    """Span as substring of larger phrase should pass"""
    assert validate_evidence_span("headache six months", "headache six months ago") is True


def test_span_at_start():
    """Span at start of text should pass"""
    assert validate_evidence_span("I have", "I have a headache") is True


def test_span_at_end():
    """Span at end of text should pass"""
    assert validate_evidence_span("a headache", "I have a headache") is True


def test_multiple_occurrences():
    """Span appearing multiple times should pass"""
    text = "headache here and headache there"
    assert validate_evidence_span("headache", text) is True


# Case sensitivity tests
def test_case_insensitive_uppercase():
    """Upper/lowercase difference should pass"""
    assert validate_evidence_span("HEADACHE", "I have a headache") is True


def test_case_insensitive_mixed():
    """Mixed case should pass"""
    assert validate_evidence_span("HeAdAcHe", "I have a headache") is True


def test_case_insensitive_span_upper_text_lower():
    """Uppercase span, lowercase text should pass"""
    assert validate_evidence_span("HEADACHE", "headache") is True


# Whitespace handling tests
def test_leading_whitespace_in_span():
    """Leading whitespace in span should be trimmed"""
    assert validate_evidence_span("  headache", "I have a headache") is True


def test_trailing_whitespace_in_span():
    """Trailing whitespace in span should be trimmed"""
    assert validate_evidence_span("headache  ", "I have a headache") is True


def test_both_whitespace_in_span():
    """Leading and trailing whitespace in span should be trimmed"""
    assert validate_evidence_span("  headache  ", "I have a headache") is True


def test_internal_whitespace_preserved():
    """Internal whitespace must match exactly - double space should fail"""
    assert validate_evidence_span("six  months", "six months ago") is False


def test_whitespace_in_raw_text_preserved():
    """Whitespace in raw_text is not normalized"""
    assert validate_evidence_span("headache", "  I have a headache  ") is True


def test_multiline_text():
    """Newlines in text should be preserved"""
    text = "I have a headache\nIt started yesterday"
    assert validate_evidence_span("headache", text) is True


# Empty and None tests
def test_empty_span():
    """Empty span should fail"""
    assert validate_evidence_span("", "some text") is False


def test_empty_raw_text():
    """Empty raw_text should fail"""
    assert validate_evidence_span("span", "") is False


def test_both_empty():
    """Both empty should fail"""
    assert validate_evidence_span("", "") is False


def test_none_span():
    """None span should fail"""
    assert validate_evidence_span(None, "some text") is False


def test_none_raw_text():
    """None raw_text should fail"""
    assert validate_evidence_span("span", None) is False


def test_both_none():
    """Both None should fail"""
    assert validate_evidence_span(None, None) is False


def test_whitespace_only_span():
    """Whitespace-only span should fail"""
    assert validate_evidence_span("   ", "some text") is False


def test_whitespace_only_raw_text():
    """Whitespace-only raw_text should fail"""
    assert validate_evidence_span("span", "   ") is False


def test_tabs_and_newlines_only_span():
    """Tabs and newlines only in span should fail"""
    assert validate_evidence_span("\n\t", "some text") is False


# Length tests
def test_span_longer_than_text():
    """Span longer than text should fail"""
    assert validate_evidence_span("very long span text", "short") is False


def test_span_becomes_empty_after_normalization():
    """Span that becomes empty after strip should fail"""
    # This is caught by the post-trim guard
    assert validate_evidence_span("   ", "some text") is False


# Unicode normalization tests
def test_unicode_nfc_normalization():
    """Different Unicode representations should normalize to same form"""
    # é can be represented as single char (U+00E9) or e + combining acute (U+0065 U+0301)
    span_combined = "café"  # e + combining acute
    text_precomposed = "café"  # precomposed é
    assert validate_evidence_span(span_combined, text_precomposed) is True


def test_unicode_casefold_german_sharp_s():
    """German ß should casefold to ss"""
    assert validate_evidence_span("straße", "STRASSE") is True


def test_unicode_normalization_not_accent_stripping_cafe():
    """Unicode normalization should NOT strip accents - cafe vs café should fail"""
    assert validate_evidence_span("cafe", "café") is False


def test_unicode_normalization_not_accent_stripping_resume():
    """Unicode normalization should NOT strip accents - resume vs résumé should fail"""
    assert validate_evidence_span("resume", "résumé") is False


def test_unicode_normalization_preserves_accents_when_both_have_them():
    """When both have same accents, should pass"""
    assert validate_evidence_span("café", "I went to café yesterday") is True


# Punctuation preservation tests
def test_punctuation_preserved_period():
    """Punctuation must match exactly"""
    assert validate_evidence_span("Dr. Smith", "I saw Dr. Smith") is True
    assert validate_evidence_span("Dr Smith", "I saw Dr. Smith") is False


def test_punctuation_preserved_comma():
    """Commas must match"""
    assert validate_evidence_span("pain, swelling", "I have pain, swelling") is True
    assert validate_evidence_span("pain swelling", "I have pain, swelling") is False


def test_punctuation_preserved_apostrophe():
    """Apostrophes must match"""
    assert validate_evidence_span("didn't", "I didn't see it") is True
    assert validate_evidence_span("didnt", "I didn't see it") is False


# Adversarial near-miss tests
def test_adversarial_singular_plural():
    """Singular vs plural should fail - no fuzzy matching"""
    assert validate_evidence_span("headache six month", "headache six months ago") is False


def test_adversarial_missing_letter():
    """Missing letter should fail"""
    assert validate_evidence_span("headach", "headache") is False


def test_adversarial_extra_letter():
    """Extra letter should fail"""
    assert validate_evidence_span("headaches", "headache") is False


def test_adversarial_word_order():
    """Different word order should fail"""
    assert validate_evidence_span("months six", "six months ago") is False


# Edge cases
def test_span_with_numbers():
    """Numeric content should work"""
    assert validate_evidence_span("20/20", "my vision is 20/20") is True


def test_span_with_special_characters():
    """Special characters should be preserved"""
    assert validate_evidence_span("left eye (OS)", "pain in left eye (OS)") is True


def test_very_long_text():
    """Should work with long text"""
    long_text = "word " * 1000 + "headache " + "word " * 1000
    assert validate_evidence_span("headache", long_text) is True
```