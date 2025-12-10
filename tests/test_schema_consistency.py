"""
Schema Consistency Validation Tests

Purpose: Ensure all four configuration files remain synchronized
- ruleset.json: Question flow and conversation logic
- json_schema.json: Output structure and validation
- episode_classifier.py: Field routing (episode vs shared)
- clinical_data_model.json: Initialization templates

This test suite prevents schema drift and catches mismatches early.

Run with: pytest test_schema_consistency.py -v
"""

import json
from pathlib import Path
import sys

# Add project root to Python path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.utils.episode_classifier import (
    EPISODE_FIELDS,
    SHARED_FIELDS,
    classify_field,
    get_all_episode_fields,
    get_all_shared_fields
)

# Defer pytest import until test class is used
try:
    import pytest
    PYTEST_AVAILABLE = True
except ImportError:
    PYTEST_AVAILABLE = False
    # Define dummy pytest functions for report generation
    class pytest:
        @staticmethod
        def skip(msg):
            pass


class TestSchemaConsistency:
    """Validates consistency across all configuration files"""
    
    @classmethod
    def setup_class(cls):
        """Load all configuration files once"""
        # Get project root (parent of tests directory)
        project_root = Path(__file__).parent.parent
        
        # Load ruleset (try v2 first, fallback to v1)
        ruleset_path = project_root / "data" / "ruleset_v2.json"
        if not ruleset_path.exists():
            ruleset_path = project_root / "data" / "ruleset.json"
        if not ruleset_path.exists():
            pytest.skip(f"ruleset not found at {ruleset_path}")
        with open(ruleset_path, 'r') as f:
            cls.ruleset = json.load(f)
        
        # Load JSON schema
        schema_path = project_root / "data" / "json_schema.json"
        if not schema_path.exists():
            pytest.skip(f"json_schema not found at {schema_path}")
        with open(schema_path, 'r') as f:
            cls.schema = json.load(f)
        
        # Load clinical data model
        data_model_path = project_root / "data" / "clinical_data_model.json"
        if not data_model_path.exists():
            pytest.skip(f"clinical_data_model not found at {data_model_path}")
        with open(data_model_path, 'r') as f:
            cls.data_model = json.load(f)
        
        # Episode classifier fields (already imported)
        cls.episode_fields = get_all_episode_fields()
        cls.shared_fields = get_all_shared_fields()
    
    def test_no_overlap_between_episode_and_shared(self):
        """
        CRITICAL: Episode and shared fields must be completely separate
        
        If a field appears in both, routing becomes ambiguous.
        """
        overlap = self.episode_fields & self.shared_fields
        
        assert len(overlap) == 0, (
            f"Found {len(overlap)} fields in BOTH episode and shared:\n"
            f"{sorted(overlap)}\n\n"
            f"FIX: Remove these from either EPISODE_FIELDS or SHARED_FIELDS in episode_classifier.py"
        )
    
    def test_ruleset_fields_exist_in_classifier(self):
        """
        All fields mentioned in ruleset must exist in episode_classifier.py
        
        This ensures Dialogue Manager can route extracted fields correctly.
        """
        ruleset_fields = self._extract_ruleset_fields()
        all_classified_fields = self.episode_fields | self.shared_fields
        
        missing = ruleset_fields - all_classified_fields
        
        assert len(missing) == 0, (
            f"Found {len(missing)} fields in ruleset.json but missing from episode_classifier.py:\n"
            f"{sorted(missing)}\n\n"
            f"FIX: Add these fields to either EPISODE_FIELDS or SHARED_FIELDS in episode_classifier.py\n"
            f"Decision guide:\n"
            f"  - Episode-specific symptoms (vision loss, headache) → EPISODE_FIELDS\n"
            f"  - Patient background (PMH, medications, social history) → SHARED_FIELDS"
        )
    
    def test_ruleset_fields_exist_in_schema(self):
        """
        All fields mentioned in ruleset must be defined in json_schema.json
        
        This ensures JSON Formatter can validate and structure output correctly.
        """
        ruleset_fields = self._extract_ruleset_fields()
        schema_fields = self._extract_schema_fields()
        
        missing = ruleset_fields - schema_fields
        
        assert len(missing) == 0, (
            f"Found {len(missing)} fields in ruleset.json but missing from json_schema.json:\n"
            f"{sorted(missing)}\n\n"
            f"FIX: Add these fields to appropriate section in json_schema.json\n"
            f"Sections:\n"
            f"  - episodes[].vision_loss for vl_* fields\n"
            f"  - episodes[].headache for h_* fields\n"
            f"  - shared_data.social_history for social history fields\n"
            f"  - etc."
        )
    
    def test_episode_classifier_fields_exist_in_schema(self):
        """
        All fields in episode_classifier.py must be defined in json_schema.json
        
        This catches orphaned fields in classifier that have no schema definition.
        """
        all_classified_fields = self.episode_fields | self.shared_fields
        schema_fields = self._extract_schema_fields()
        
        missing = all_classified_fields - schema_fields
        
        assert len(missing) == 0, (
            f"Found {len(missing)} fields in episode_classifier.py but missing from json_schema.json:\n"
            f"{sorted(missing)}\n\n"
            f"FIX: Either:\n"
            f"  1. Add these fields to json_schema.json if they're valid\n"
            f"  2. Remove them from episode_classifier.py if they're obsolete"
        )
    
    def test_clinical_data_model_matches_schema_shared_fields(self):
        """
        Clinical data model structure must match schema's shared_data section
        
        This ensures State Manager initializes with correct structure.
        """
        # Extract nested paths from data model
        data_model_fields = self._extract_data_model_fields()
        
        # Extract shared fields from schema (not episode fields)
        schema_shared_fields = self._extract_schema_shared_fields()
        
        # Check: every field in data model should be in schema
        missing_from_schema = data_model_fields - schema_shared_fields
        
        # Check: every nested field in schema should be in data model
        # (excluding episode fields)
        missing_from_data_model = schema_shared_fields - data_model_fields
        
        errors = []
        
        if missing_from_schema:
            errors.append(
                f"Fields in clinical_data_model.json but missing from json_schema.json shared_data:\n"
                f"{sorted(missing_from_schema)}\n"
            )
        
        if missing_from_data_model:
            errors.append(
                f"Fields in json_schema.json shared_data but missing from clinical_data_model.json:\n"
                f"{sorted(missing_from_data_model)}\n"
            )
        
        assert len(errors) == 0, (
            "\n".join(errors) + "\n"
            f"FIX: Ensure clinical_data_model.json shared_data_template matches "
            f"json_schema.json shared_data structure exactly"
        )
    
    def test_shared_fields_in_classifier_match_data_model(self):
        """
        Shared fields in classifier should align with data model structure
        
        This ensures routing logic matches initialization structure.
        """
        data_model_fields = self._extract_data_model_fields()
        
        # Shared fields that should be in data model (excluding arrays)
        shared_structural_fields = {
            f for f in self.shared_fields 
            if '.' in f  # Nested fields like social_history.smoking.status
        }
        
        missing_from_data_model = shared_structural_fields - data_model_fields
        
        # We expect some shared fields like 'medications', 'past_medical_history'
        # to NOT be in data model fields because they're arrays, not nested objects
        # Filter these out
        array_fields = {'medications', 'past_medical_history', 'family_history', 'allergies'}
        missing_from_data_model = {
            f for f in missing_from_data_model 
            if not any(f.startswith(af) for af in array_fields)
        }
        
        assert len(missing_from_data_model) == 0, (
            f"Found {len(missing_from_data_model)} nested shared fields in classifier "
            f"but missing from clinical_data_model.json:\n"
            f"{sorted(missing_from_data_model)}\n\n"
            f"FIX: Add these nested fields to clinical_data_model.json shared_data_template"
        )
    
    def test_episode_transition_field_is_shared(self):
        """
        CRITICAL: additional_episodes_present must be classified as shared
        
        This field controls episode transitions and must not be episode-specific.
        """
        assert 'additional_episodes_present' in self.shared_fields, (
            "Field 'additional_episodes_present' must be in SHARED_FIELDS\n"
            "This field controls episode transitions and is not episode-specific"
        )
        
        assert 'additional_episodes_present' not in self.episode_fields, (
            "Field 'additional_episodes_present' must NOT be in EPISODE_FIELDS"
        )
    
    def test_operational_fields_excluded_from_all_configs(self):
        """
        Operational fields should NOT appear in ruleset, schema, or data model
        
        These fields are State Manager internals:
        - questions_answered
        - follow_up_blocks_activated
        - follow_up_blocks_completed
        """
        operational_fields = {
            'questions_answered',
            'follow_up_blocks_activated', 
            'follow_up_blocks_completed'
        }
        
        ruleset_fields = self._extract_ruleset_fields()
        schema_fields = self._extract_schema_fields()
        data_model_fields = self._extract_data_model_fields()
        
        # Check they don't appear anywhere
        in_ruleset = operational_fields & ruleset_fields
        in_schema = operational_fields & schema_fields
        in_data_model = operational_fields & data_model_fields
        in_classifier = operational_fields & (self.episode_fields | self.shared_fields)
        
        errors = []
        if in_ruleset:
            errors.append(f"Operational fields in ruleset: {in_ruleset}")
        if in_schema:
            errors.append(f"Operational fields in schema: {in_schema}")
        if in_data_model:
            errors.append(f"Operational fields in data model: {in_data_model}")
        if in_classifier:
            errors.append(f"Operational fields in classifier: {in_classifier}")
        
        assert len(errors) == 0, (
            "Operational fields should NOT appear in config files:\n" +
            "\n".join(errors) + "\n\n"
            "These are State Manager internals and should only exist in state_manager_v2.py"
        )
    
    def test_follow_up_block_fields_are_episode_specific(self):
        """
        Follow-up block fields (b1_*, b2_*, etc.) must be episode-specific
        
        Follow-up blocks are triggered by episode-specific conditions.
        """
        # Extract all fields that start with b1_ through b6_
        follow_up_prefixes = {f'b{i}_' for i in range(1, 7)}
        
        all_fields = self.episode_fields | self.shared_fields
        follow_up_fields = {
            f for f in all_fields 
            if any(f.startswith(prefix) for prefix in follow_up_prefixes)
        }
        
        # Check they're all in episode fields
        follow_up_in_shared = follow_up_fields & self.shared_fields
        
        assert len(follow_up_in_shared) == 0, (
            f"Found {len(follow_up_in_shared)} follow-up block fields incorrectly "
            f"classified as shared:\n"
            f"{sorted(follow_up_in_shared)}\n\n"
            f"FIX: Move these from SHARED_FIELDS to appropriate FOLLOW_UP_BLOCK_X_FIELDS "
            f"in episode_classifier.py"
        )
    
    # ========================================
    # Helper Methods
    # ========================================
    
    def _extract_ruleset_fields(self):
        """Extract all field names mentioned in ruleset.json"""
        fields = set()
        
        # Extract from main sections
        for section_name, questions in self.ruleset.get('sections', {}).items():
            if not isinstance(questions, list):
                continue
            for question in questions:
                if not isinstance(question, dict):
                    continue
                field = question.get('field')
                if field:
                    fields.add(field)
        
        # Extract from follow-up blocks
        for block_id, block_data in self.ruleset.get('follow_up_blocks', {}).items():
            if not isinstance(block_data, dict):
                continue
            for question in block_data.get('questions', []):
                if not isinstance(question, dict):
                    continue
                field = question.get('field')
                if field:
                    fields.add(field)
        
        # Extract from shared data sections
        for section_name, questions in self.ruleset.get('shared_data_sections', {}).items():
            if not isinstance(questions, list):
                continue
            for question in questions:
                if not isinstance(question, dict):
                    continue
                field = question.get('field')
                if field:
                    fields.add(field)
        
        return fields
    
    def _extract_schema_fields(self):
        """Extract all field names defined in json_schema.json"""
        fields = set()
        
        # Extract from episode sections
        episodes_structure = self.schema.get('episodes', {})
        if isinstance(episodes_structure, dict) and 'items' in episodes_structure:
            items = episodes_structure['items']
            if isinstance(items, dict) and 'properties' in items:
                properties = items['properties']
                
                # Process each section (vision_loss, headache, etc.)
                for section_name, section_content in properties.items():
                    # Skip metadata fields
                    if section_name in ['episode_id', 'timestamp_started', 'timestamp_last_updated']:
                        fields.add(section_name)
                        continue
                    
                    # Extract fields from section
                    if isinstance(section_content, dict):
                        # Use flat extraction for follow_up_blocks (no prefixes)
                        # Use nested extraction for others (preserves dot notation)
                        use_flat = (section_name == 'follow_up_blocks')
                        self._extract_fields_from_section(section_content, fields, use_flat_extraction=use_flat)
        
        # Extract from shared_data (uses dot notation for nested structures)
        shared_data = self.schema.get('shared_data', {})
        # Process each top-level shared field
        for key, value in shared_data.items():
            if key in ['type', 'description']:
                continue
            
            if isinstance(value, dict):
                # Check if it has nested structure
                has_nested = any(
                    isinstance(v, dict) 
                    for k, v in value.items()
                    if k not in ['type', 'description', 'items']
                )
                
                if has_nested:
                    # Nested structure - extract with prefix
                    self._extract_nested_fields(value, fields, prefix=key)
                else:
                    # Simple field or array
                    fields.add(key)
            else:
                fields.add(key)
        
        return fields
    
    def _extract_fields_from_section(self, section, fields, use_flat_extraction=False):
        """
        Extract field names from a section, handling nested structures
        
        Args:
            section: Dict containing field definitions
            fields: Set to add field names to
            use_flat_extraction: If True, extract leaf fields without prefixes
                                (for follow_up_blocks). If False, use dot notation
                                for nested fields (for social_history)
        """
        if not isinstance(section, dict):
            return
        
        for key, value in section.items():
            # Skip metadata keys
            if key in ['type', 'description', 'required', 'items', 'properties',
                      'valid_values', 'valid_range', 'format', 'definitions',
                      'comment', 'field_type', 'name']:
                continue
            
            if isinstance(value, dict):
                value_type = value.get('type')
                
                # Check if this is a container (has nested fields) or a leaf field
                has_nested_fields = any(
                    k not in ['type', 'description', 'required', 'items', 'properties',
                             'valid_values', 'valid_range', 'format', 'definitions',
                             'comment', 'field_type', 'name'] 
                    and isinstance(v, dict) 
                    for k, v in value.items()
                )
                
                if value_type == 'object' or has_nested_fields:
                    # This is a container
                    if use_flat_extraction:
                        # For follow_up_blocks: recurse but don't add prefix
                        self._extract_fields_from_section(value, fields, use_flat_extraction=True)
                    else:
                        # For social_history: recurse with dot notation
                        self._extract_nested_fields(value, fields, prefix=key)
                else:
                    # This is a leaf field - add it
                    fields.add(key)
            else:
                # Non-dict value means this is a leaf field
                fields.add(key)
    
    def _extract_nested_fields(self, obj, fields, prefix=''):
        """Extract nested fields with dot notation (for social_history, etc.)"""
        if not isinstance(obj, dict):
            return
        
        for key, value in obj.items():
            # Skip metadata keys
            if key in ['type', 'description', 'required', 'items', 'properties',
                      'valid_values', 'valid_range', 'format', 'definitions',
                      'comment', 'field_type', 'name']:
                continue
            
            if isinstance(value, dict):
                # Check if this dict contains nested fields or is a field definition
                has_nested_fields = any(
                    k not in ['type', 'description', 'required', 'items', 'properties',
                             'valid_values', 'valid_range', 'format', 'definitions',
                             'comment', 'field_type', 'name']
                    and isinstance(v, dict)
                    for k, v in value.items()
                )
                
                if has_nested_fields:
                    # Container - keep recursing
                    new_prefix = f"{prefix}.{key}" if prefix else key
                    self._extract_nested_fields(value, fields, prefix=new_prefix)
                else:
                    # Leaf field - add with full path
                    full_key = f"{prefix}.{key}" if prefix else key
                    fields.add(full_key)
            else:
                # Non-dict value is a leaf field
                full_key = f"{prefix}.{key}" if prefix else key
                fields.add(full_key)
    
    def _extract_schema_shared_fields(self):
        """Extract only shared_data fields from json_schema.json"""
        fields = set()
        shared_data = self.schema.get('shared_data', {})
        self._extract_fields_from_section(shared_data, fields)
        return fields
    
    def _extract_data_model_fields(self):
        """Extract all nested field paths from clinical_data_model.json"""
        fields = set()
        shared_template = self.data_model.get('shared_data_template', {})
        self._extract_data_model_recursive(shared_template, fields, prefix='')
        return fields
    
    def _extract_data_model_recursive(self, obj, fields, prefix=''):
        """Recursively extract field paths from nested data model structure"""
        if not isinstance(obj, dict):
            return
        
        for key, value in obj.items():
            # Build full field path
            full_key = f"{prefix}.{key}" if prefix else key
            fields.add(full_key)
            
            # Recurse into nested dicts (but not arrays)
            if isinstance(value, dict):
                self._extract_data_model_recursive(value, fields, prefix=full_key)


# ========================================
# Test Report Generator
# ========================================

def generate_consistency_report():
    """
    Generate a comprehensive consistency report (for manual debugging)
    
    Run with: python test_schema_consistency.py
    """
    print("="*70)
    print("SCHEMA CONSISTENCY REPORT")
    print("="*70)
    
    # Get project root (parent of tests directory if in tests, otherwise current dir)
    script_path = Path(__file__).resolve()
    if script_path.parent.name == 'tests':
        project_root = script_path.parent.parent
    else:
        project_root = script_path.parent
    
    # Load files (try v2 first, fallback to v1)
    ruleset_path = project_root / "data" / "ruleset_v2.json"
    if not ruleset_path.exists():
        ruleset_path = project_root / "data" / "ruleset.json"
    
    with open(ruleset_path, 'r') as f:
        ruleset = json.load(f)
    with open(project_root / "data" / "json_schema.json", 'r') as f:
        schema = json.load(f)
    with open(project_root / "data" / "clinical_data_model.json", 'r') as f:
        data_model = json.load(f)
    
    # Get field sets
    episode_fields = get_all_episode_fields()
    shared_fields = get_all_shared_fields()
    
    # Extract fields
    test = TestSchemaConsistency()
    test.setup_class()
    ruleset_fields = test._extract_ruleset_fields()
    schema_fields = test._extract_schema_fields()
    data_model_fields = test._extract_data_model_fields()
    
    # Print summary
    print(f"\nField Counts:")
    print(f"  Ruleset:           {len(ruleset_fields)} fields")
    print(f"  JSON Schema:       {len(schema_fields)} fields")
    print(f"  Episode Classifier (episode): {len(episode_fields)} fields")
    print(f"  Episode Classifier (shared):  {len(shared_fields)} fields")
    print(f"  Clinical Data Model: {len(data_model_fields)} fields")
    
    # Check overlaps
    print(f"\n{'='*70}")
    print("OVERLAP ANALYSIS")
    print("="*70)
    
    overlap = episode_fields & shared_fields
    if overlap:
        print(f"\n⚠️  CRITICAL: {len(overlap)} fields in BOTH episode and shared:")
        for field in sorted(overlap):
            print(f"  - {field}")
    else:
        print("\n✓ No overlap between episode and shared fields")
    
    # Check missing from classifier
    print(f"\n{'='*70}")
    print("RULESET → CLASSIFIER")
    print("="*70)
    
    all_classified = episode_fields | shared_fields
    missing = ruleset_fields - all_classified
    if missing:
        print(f"\n⚠️  {len(missing)} fields in ruleset but missing from classifier:")
        for field in sorted(missing):
            print(f"  - {field}")
    else:
        print("\n✓ All ruleset fields present in classifier")
    
    # Check missing from schema
    print(f"\n{'='*70}")
    print("RULESET → SCHEMA")
    print("="*70)
    
    missing = ruleset_fields - schema_fields
    if missing:
        print(f"\n⚠️  {len(missing)} fields in ruleset but missing from schema:")
        for field in sorted(missing):
            print(f"  - {field}")
    else:
        print("\n✓ All ruleset fields defined in schema")
    
    # Check orphaned classifier fields
    print(f"\n{'='*70}")
    print("CLASSIFIER → SCHEMA")
    print("="*70)
    
    missing = all_classified - schema_fields
    if missing:
        print(f"\n⚠️  {len(missing)} fields in classifier but missing from schema:")
        for field in sorted(missing):
            print(f"  - {field}")
    else:
        print("\n✓ All classifier fields defined in schema")
    
    # Check data model vs schema
    print(f"\n{'='*70}")
    print("DATA MODEL ↔ SCHEMA (shared fields)")
    print("="*70)
    
    schema_shared = test._extract_schema_shared_fields()
    missing_from_schema = data_model_fields - schema_shared
    missing_from_data_model = schema_shared - data_model_fields
    
    if missing_from_schema:
        print(f"\n⚠️  {len(missing_from_schema)} fields in data model but missing from schema:")
        for field in sorted(missing_from_schema):
            print(f"  - {field}")
    
    if missing_from_data_model:
        print(f"\n⚠️  {len(missing_from_data_model)} fields in schema but missing from data model:")
        for field in sorted(missing_from_data_model):
            print(f"  - {field}")
    
    if not missing_from_schema and not missing_from_data_model:
        print("\n✓ Data model and schema shared fields match")
    
    print(f"\n{'='*70}")
    print("END REPORT")
    print("="*70)


if __name__ == '__main__':
    # Run report generator if executed directly
    generate_consistency_report()