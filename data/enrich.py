#!/usr/bin/env python3
"""
Enrich Ruleset with Field Labels and Descriptions

This script:
1. Extracts field descriptions from json_schema.json
2. Generates field labels by expanding prefixes (e.g., vl_ -> visual loss)
3. Inserts both into matching questions in ruleset_v2.json
4. Outputs a new ruleset file: ruleset_v3_enriched.json

Usage:
    python enrich_ruleset_with_descriptions.py
"""

import json
from typing import Dict, Optional, Tuple


# Prefix expansion mappings
PREFIX_EXPANSIONS = {
    'vl_': 'visual loss',
    'cp_': 'color perception',
    'vp_': 'visual phenomena',
    'dp_': 'diplopia',
    'dz_': 'dizziness',
    'hall_': 'hallucinations',
    'h_': 'headache',
    'ep_': 'eye pain',
    'ac_': 'appearance changes',
    'hc_': 'healthcare contacts',
    'os_': 'other symptoms',
    'func_': 'functional impact',
}


def expand_field_name(field_name: str) -> str:
    """
    Expand abbreviated field name to human-readable label.
    
    Examples:
        'vl_present' -> 'visual loss present'
        'h_laterality' -> 'headache laterality'
        'vl_onset_speed' -> 'visual loss onset speed'
    
    Args:
        field_name: Abbreviated field name (e.g., 'vl_present')
        
    Returns:
        Expanded field label (e.g., 'visual loss present')
    """
    # Check each prefix
    for prefix, expansion in PREFIX_EXPANSIONS.items():
        if field_name.startswith(prefix):
            # Replace prefix with expansion
            # e.g., 'vl_present' -> 'present', then prepend 'visual loss'
            suffix = field_name[len(prefix):]
            
            # Replace underscores with spaces in suffix
            suffix = suffix.replace('_', ' ')
            
            # Combine expansion + suffix
            return f"{expansion} {suffix}"
    
    # No prefix match - just replace underscores
    return field_name.replace('_', ' ')


def extract_descriptions_from_schema(schema_path: str) -> Dict[str, str]:
    """
    Extract field descriptions from JSON schema.
    
    Recursively traverses the schema structure to find all fields
    with 'description' properties.
    
    Args:
        schema_path: Path to json_schema.json
        
    Returns:
        Dict mapping field names to their descriptions
        
    Example:
        {
            'vl_present': 'Is vision loss present in this episode?',
            'vl_laterality': 'Which eye is affected (only asked if vl_single_eye is single)',
            ...
        }
    """
    with open(schema_path, 'r') as f:
        schema = json.load(f)
    
    descriptions = {}
    
    def recurse_extract(obj, path=''):
        """Recursively extract descriptions from nested dicts"""
        if isinstance(obj, dict):
            # Check if this is a field definition with description
            if 'description' in obj:
                # Path is the field name (last component)
                # We need to extract just the field name from the path
                # For nested structures like vision_loss.vl_present, 
                # we want just 'vl_present'
                if path:
                    field_name = path.split('.')[-1]
                    descriptions[field_name] = obj['description']
            
            # Recurse into nested objects
            for key, value in obj.items():
                new_path = f"{path}.{key}" if path else key
                recurse_extract(value, new_path)
        
        elif isinstance(obj, list):
            # Recurse into lists
            for item in obj:
                recurse_extract(item, path)
    
    recurse_extract(schema)
    
    return descriptions


def enrich_ruleset(
    ruleset_path: str,
    schema_descriptions: Dict[str, str],
    output_path: str
) -> Tuple[int, int, int]:
    """
    Enrich ruleset questions with field_label and field_description.
    
    Args:
        ruleset_path: Path to ruleset_v2.json
        schema_descriptions: Dict of field_name -> description
        output_path: Where to write enriched ruleset
        
    Returns:
        Tuple of (total_questions, enriched_count, missing_description_count)
    """
    with open(ruleset_path, 'r') as f:
        ruleset = json.load(f)
    
    total_questions = 0
    enriched_count = 0
    missing_description_count = 0
    
    # Track which fields we couldn't find descriptions for
    missing_descriptions = set()
    
    def enrich_question(question: dict) -> dict:
        """Enrich a single question dict with field_label and field_description"""
        nonlocal enriched_count, missing_description_count
        
        # Check if question has 'field' key
        if 'field' not in question:
            return question
        
        field_name = question['field']
        
        # Generate field_label by expanding prefix
        field_label = expand_field_name(field_name)
        question['field_label'] = field_label
        
        # Add field_description if available in schema
        if field_name in schema_descriptions:
            question['field_description'] = schema_descriptions[field_name]
            enriched_count += 1
        else:
            # No description found - leave field_description absent
            # (We'll report these at the end)
            missing_descriptions.add(field_name)
            missing_description_count += 1
        
        return question
    
    # Process all sections
    # Note: sections can be either arrays of questions OR objects with follow_up_blocks
    for section_name, section_content in ruleset.get('sections', {}).items():
        # Case 1: section_content is a list of questions (e.g., gating_questions)
        if isinstance(section_content, list):
            for i, question in enumerate(section_content):
                total_questions += 1
                section_content[i] = enrich_question(question)
        
        # Case 2: section_content is an object with 'questions' key
        elif isinstance(section_content, dict):
            if 'questions' in section_content:
                questions = section_content['questions']
                for i, question in enumerate(questions):
                    total_questions += 1
                    section_content['questions'][i] = enrich_question(question)
            
            # Handle follow-up blocks (nested questions)
            if 'follow_up_blocks' in section_content:
                for block_id, block in section_content['follow_up_blocks'].items():
                    if 'questions' in block:
                        for i, question in enumerate(block['questions']):
                            total_questions += 1
                            block['questions'][i] = enrich_question(question)
    
    # Process top-level follow_up_blocks (where most questions are)
    if 'follow_up_blocks' in ruleset:
        for block_id, block in ruleset['follow_up_blocks'].items():
            if 'questions' in block:
                for i, question in enumerate(block['questions']):
                    total_questions += 1
                    block['questions'][i] = enrich_question(question)
    
    # Write enriched ruleset
    with open(output_path, 'w') as f:
        json.dump(ruleset, f, indent=2)
    
    # Print report of missing descriptions
    if missing_descriptions:
        print("\nFields without descriptions in schema (will need manual descriptions):")
        for field in sorted(missing_descriptions):
            print(f"  - {field}")
    
    return total_questions, enriched_count, missing_description_count


def main():
    """Main execution"""
    schema_path = '/mnt/project/json_schema.json'
    ruleset_path = '/mnt/project/ruleset_v2.json'
    output_path = '/mnt/project/ruleset_v3_enriched.json'
    
    print("=" * 80)
    print("RULESET ENRICHMENT SCRIPT")
    print("=" * 80)
    
    # Step 1: Extract descriptions from schema
    print("\nStep 1: Extracting descriptions from json_schema.json...")
    schema_descriptions = extract_descriptions_from_schema(schema_path)
    print(f"Found {len(schema_descriptions)} field descriptions in schema")
    
    # Show some examples
    print("\nExample descriptions found:")
    for field_name in list(schema_descriptions.keys())[:5]:
        print(f"  {field_name}: {schema_descriptions[field_name][:60]}...")
    
    # Step 2: Enrich ruleset
    print("\nStep 2: Enriching ruleset with labels and descriptions...")
    total, enriched, missing = enrich_ruleset(
        ruleset_path,
        schema_descriptions,
        output_path
    )
    
    # Summary
    print("\n" + "=" * 80)
    print("ENRICHMENT COMPLETE")
    print("=" * 80)
    print(f"Total questions processed: {total}")
    print(f"Questions enriched with descriptions: {enriched}")
    print(f"Questions with labels only (no description in schema): {missing}")
    print(f"\nEnriched ruleset written to: {output_path}")
    print("\nNext steps:")
    print("1. Review the enriched ruleset")
    print("2. Manually add descriptions for fields that were missing")
    print("3. Update response_parser_v2.py to use field_label and field_description in prompts")
    print("=" * 80)


if __name__ == '__main__':
    main()