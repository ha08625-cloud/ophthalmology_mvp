"""
Tests for Episode Classifier V3

Test categories:
1. Prefix routing (episode vs shared)
2. Collection routing
3. Ambiguity detection
4. Unknown field handling
5. Configuration validation
"""

import pytest
from backend.utils.episode_classifier import (
    classify_field,
    is_episode_field,
    is_shared_field,
    is_collection_field,
    set_strict_mode,
    EPISODE_PREFIXES,
    SHARED_PREFIXES,
    COLLECTION_FIELDS,
)


class TestPrefixRouting:
    """Test prefix-based field routing"""
    
    def test_episode_vision_loss(self):
        assert classify_field('vl_laterality') == 'episode'
        assert classify_field('vl_present') == 'episode'
        assert classify_field('vl_field') == 'episode'
    
    def test_episode_headache(self):
        assert classify_field('h_present') == 'episode'
        assert classify_field('h_severity') == 'episode'
    
    def test_episode_eye_pain(self):
        assert classify_field('ep_present') == 'episode'
        assert classify_field('ep_laterality') == 'episode'
    
    def test_episode_follow_up_blocks(self):
        assert classify_field('b1_uhthoff_phenomenon') == 'episode'
        assert classify_field('b2_jaw_claudication') == 'episode'
        assert classify_field('b6_can_see_moving_water') == 'episode'
    
    def test_shared_social_history(self):
        assert classify_field('sh_smoking_status') == 'shared'
        assert classify_field('sh_smoking_pack_years') == 'shared'
        assert classify_field('sh_alcohol_units') == 'shared'
    
    def test_shared_systems_review(self):
        assert classify_field('sr_gen_chills') == 'shared'
        assert classify_field('sr_gen_chills_details') == 'shared'
        assert classify_field('sr_neuro_weakness') == 'shared'
        assert classify_field('sr_cardio_chest_pain') == 'shared'
    
    def test_all_episode_prefixes_route_correctly(self):
        """Ensure all registered episode prefixes work"""
        for prefix in EPISODE_PREFIXES:
            test_field = f"{prefix}test_field"
            assert classify_field(test_field) == 'episode', \
                f"Prefix '{prefix}' failed to route as episode"
    
    def test_all_shared_prefixes_route_correctly(self):
        """Ensure all registered shared prefixes work"""
        for prefix in SHARED_PREFIXES:
            test_field = f"{prefix}test_field"
            assert classify_field(test_field) == 'shared', \
                f"Prefix '{prefix}' failed to route as shared"


class TestCollectionRouting:
    """Test collection field routing"""
    
    def test_medications_is_shared(self):
        assert classify_field('medications') == 'shared'
        assert is_collection_field('medications')
    
    def test_past_medical_history_is_shared(self):
        assert classify_field('past_medical_history') == 'shared'
        assert is_collection_field('past_medical_history')
    
    def test_family_history_is_shared(self):
        assert classify_field('family_history') == 'shared'
        assert is_collection_field('family_history')
    
    def test_allergies_is_shared(self):
        assert classify_field('allergies') == 'shared'
        assert is_collection_field('allergies')
    
    def test_all_collections_route_correctly(self):
        """Ensure all registered collections work"""
        for collection in COLLECTION_FIELDS:
            assert classify_field(collection) == 'shared', \
                f"Collection '{collection}' failed to route as shared"
            assert is_collection_field(collection), \
                f"Collection '{collection}' not recognized by is_collection_field()"


class TestUnknownFields:
    """Test unknown field handling"""
    
    def test_unknown_field_returns_unknown_in_permissive_mode(self):
        set_strict_mode(False)
        assert classify_field('random_unknown_field') == 'unknown'
    
    def test_unknown_field_raises_in_strict_mode(self):
        set_strict_mode(True)
        with pytest.raises(ValueError, match="Unknown field"):
            classify_field('random_unknown_field')
        set_strict_mode(False)  # Reset
    
    def test_partial_prefix_match_is_unknown(self):
        # 'vl' without underscore should not match 'vl_'
        assert classify_field('vltest') == 'unknown'
        assert classify_field('shtest') == 'unknown'
    
    def test_suffix_match_is_unknown(self):
        # Field ending with prefix should not match
        assert classify_field('test_vl_') == 'unknown'
        assert classify_field('test_sh_') == 'unknown'


class TestAmbiguityDetection:
    """Test ambiguity detection and fail-fast behavior"""
    
    def test_no_ambiguity_in_current_config(self):
        """Ensure current configuration has no ambiguous fields"""
        # This should never raise - validates our registries are clean
        test_fields = [
            'vl_laterality',
            'sh_smoking_status',
            'medications',
            'sr_gen_chills',
            'h_present',
        ]
        for field in test_fields:
            try:
                classify_field(field)
            except ValueError as e:
                pytest.fail(f"Field '{field}' raised ambiguity error: {e}")
    
    def test_config_validation_catches_prefix_overlap(self):
        """Test that overlapping prefixes would be caught at import"""
        # This test documents the behavior - actual validation happens at import
        # If we add 'vl_' to both EPISODE_PREFIXES and SHARED_PREFIXES, import fails
        
        # We can't easily test this without dynamic imports, but document it:
        overlap = EPISODE_PREFIXES & SHARED_PREFIXES
        assert len(overlap) == 0, \
            "Prefix overlap detected - should have been caught at import"


class TestHelperFunctions:
    """Test helper functions for backward compatibility"""
    
    def test_is_episode_field(self):
        assert is_episode_field('vl_laterality') is True
        assert is_episode_field('sh_smoking_status') is False
        assert is_episode_field('medications') is False
    
    def test_is_shared_field(self):
        assert is_shared_field('sh_smoking_status') is True
        assert is_shared_field('medications') is True
        assert is_shared_field('vl_laterality') is False
    
    def test_is_collection_field(self):
        assert is_collection_field('medications') is True
        assert is_collection_field('sh_smoking_status') is False
        assert is_collection_field('vl_laterality') is False


class TestEdgeCases:
    """Test edge cases and boundary conditions"""
    
    def test_empty_string(self):
        assert classify_field('') == 'unknown'
    
    def test_single_character(self):
        assert classify_field('v') == 'unknown'
    
    def test_underscore_only(self):
        assert classify_field('_') == 'unknown'
    
    def test_prefix_without_field_name(self):
        # Just the prefix with nothing after
        assert classify_field('vl_') == 'episode'  # Still matches prefix
        assert classify_field('sh_') == 'shared'
    
    def test_case_sensitivity(self):
        # Prefixes are lowercase - uppercase should not match
        assert classify_field('VL_laterality') == 'unknown'
        assert classify_field('SH_smoking') == 'unknown'
    
    def test_numeric_suffix(self):
        assert classify_field('vl_123') == 'episode'
        assert classify_field('sh_456') == 'shared'


class TestStrictMode:
    """Test strict mode configuration"""
    
    def test_strict_mode_toggle(self):
        # Start in permissive
        set_strict_mode(False)
        assert classify_field('unknown') == 'unknown'
        
        # Enable strict
        set_strict_mode(True)
        with pytest.raises(ValueError):
            classify_field('unknown')
        
        # Disable strict
        set_strict_mode(False)
        assert classify_field('unknown') == 'unknown'
    
    def test_strict_mode_does_not_affect_valid_fields(self):
        set_strict_mode(True)
        assert classify_field('vl_laterality') == 'episode'
        assert classify_field('sh_smoking_status') == 'shared'
        set_strict_mode(False)