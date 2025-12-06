#!/usr/bin/env python3
"""
Convert raw consultation transcripts to instruction-tuning format for LoRA training.

Input: data/raw/CVST.txt (12 consultations)
Output: 
  - data/training/training_data.jsonl (85% of examples)
  - data/training/validation_data.jsonl (15% of examples)

Format per line:
{
  "instruction": "Extract structured ophthalmic data from patient response.",
  "input": "Context: [question]\nPatient: '[response]'",
  "output": "{\"field_name\": value}"
}
"""

import json
import re
import random
from pathlib import Path


def parse_consultations(file_path):
    """
    Parse consultation file into structured format.
    
    Returns:
        list of dicts: [
            {
                'consultation_id': 1,
                'turns': [
                    {
                        'agent': 'question text',
                        'patient': 'response text',
                        'extracted': {'field_name': value, ...}
                    },
                    ...
                ]
            },
            ...
        ]
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    consultations = []
    
    # Split by consultation markers
    consultation_blocks = re.split(r'Consultation \d+', content)
    
    # Remove empty first element (before first consultation)
    consultation_blocks = [block.strip() for block in consultation_blocks if block.strip()]
    
    for idx, block in enumerate(consultation_blocks, 1):
        turns = parse_consultation_turns(block)
        if turns:  # Only add if we extracted turns
            consultations.append({
                'consultation_id': idx,
                'turns': turns
            })
    
    return consultations


def parse_consultation_turns(consultation_text):
    """
    Parse individual consultation into turns.
    
    Each turn consists of:
    - Agent: question
    - Patient: response
    - { JSON extraction }
    
    Returns list of turn dicts.
    """
    turns = []
    lines = consultation_text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Look for Agent line
        if line.startswith('Agent:'):
            agent_text = line[6:].strip()  # Remove "Agent:" prefix
            
            # Look for Patient line (should be next non-empty line)
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            
            if i >= len(lines) or not lines[i].strip().startswith('Patient:'):
                # No patient response found, skip
                i += 1
                continue
            
            patient_text = lines[i].strip()[8:].strip()  # Remove "Patient:" prefix
            
            # Look for JSON extraction (should be next non-empty line)
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            
            if i >= len(lines) or not lines[i].strip().startswith('{'):
                # No JSON found, skip this turn
                i += 1
                continue
            
            json_line = lines[i].strip()
            
            # Parse JSON extraction
            extracted = parse_json_extraction(json_line)
            
            if extracted:  # Only add turn if we successfully extracted fields
                turns.append({
                    'agent': agent_text,
                    'patient': patient_text,
                    'extracted': extracted
                })
            
            i += 1
        else:
            i += 1
    
    return turns


def parse_json_extraction(json_line):
    """
    Parse the JSON extraction line and extract field-value pairs.
    
    Input format: { "field_name": { "value": ..., "required": ... } }
    or: { "field_name": { "value": ..., "required": ... } }, { "field_name2": ... }
    
    Returns: dict of {field_name: value}
    """
    extracted = {}
    
    # Handle multiple JSON objects on one line (separated by commas)
    # Split by }, { pattern
    json_objects = re.split(r'\}\s*,\s*\{', json_line)
    
    for json_obj in json_objects:
        # Add back braces if they were removed by split
        if not json_obj.startswith('{'):
            json_obj = '{' + json_obj
        if not json_obj.endswith('}'):
            json_obj = json_obj + '}'
        
        try:
            # Parse JSON
            data = json.loads(json_obj)
            
            # Extract field names and values
            for field_name, field_data in data.items():
                if isinstance(field_data, dict) and 'value' in field_data:
                    # Standard format: {"field": {"value": ..., "required": ...}}
                    extracted[field_name] = field_data['value']
                else:
                    # Direct value format: {"field": value}
                    extracted[field_name] = field_data
        
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse JSON: {json_obj}")
            print(f"Error: {e}")
            continue
    
    return extracted


def create_training_examples(consultations):
    """
    Convert parsed consultations into instruction-tuning format.
    
    Returns list of training examples.
    """
    examples = []
    
    for consultation in consultations:
        for turn in consultation['turns']:
            # Build input context
            input_text = f"Context: {turn['agent']}\nPatient: '{turn['patient']}'"
            
            # Build output (JSON string of extracted fields)
            output_json = json.dumps(turn['extracted'], ensure_ascii=False)
            
            # Create training example
            example = {
                "instruction": "Extract structured ophthalmic data from patient response.",
                "input": input_text,
                "output": output_json
            }
            
            examples.append(example)
    
    return examples


def split_train_val(examples, train_ratio=0.85, seed=42):
    """
    Split examples into train and validation sets.
    
    Args:
        examples: List of training examples
        train_ratio: Proportion for training (default 0.85)
        seed: Random seed for reproducibility
    
    Returns:
        train_examples, val_examples
    """
    random.seed(seed)
    shuffled = examples.copy()
    random.shuffle(shuffled)
    
    split_idx = int(len(shuffled) * train_ratio)
    
    train_examples = shuffled[:split_idx]
    val_examples = shuffled[split_idx:]
    
    return train_examples, val_examples


def save_jsonl(examples, output_path):
    """
    Save examples to JSONL file (one JSON object per line).
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for example in examples:
            f.write(json.dumps(example, ensure_ascii=False) + '\n')
    
    print(f"Saved {len(examples)} examples to {output_path}")


def main():
    """Main conversion pipeline"""
    
    # Paths
    input_file = Path(__file__).parent.parent / "raw" / "CVST.txt"
    train_output = Path(__file__).parent / "training_data.jsonl"
    val_output = Path(__file__).parent / "validation_data.jsonl"
    
    print("="*60)
    print("CONSULTATION DATA CONVERSION")
    print("="*60)
    print(f"Input: {input_file}")
    print(f"Output: {train_output.parent}")
    print()
    
    # Check input exists
    if not input_file.exists():
        print(f"ERROR: Input file not found: {input_file}")
        print("Please ensure CVST.txt is in data/raw/")
        return
    
    # Parse consultations
    print("Step 1: Parsing consultations...")
    consultations = parse_consultations(input_file)
    print(f"  Parsed {len(consultations)} consultations")
    
    # Count total turns
    total_turns = sum(len(c['turns']) for c in consultations)
    print(f"  Extracted {total_turns} question-answer turns")
    print()
    
    # Create training examples
    print("Step 2: Creating training examples...")
    examples = create_training_examples(consultations)
    print(f"  Created {len(examples)} training examples")
    print()
    
    # Split train/val
    print("Step 3: Splitting train/validation (85/15)...")
    train_examples, val_examples = split_train_val(examples, train_ratio=0.85)
    print(f"  Training: {len(train_examples)} examples")
    print(f"  Validation: {len(val_examples)} examples")
    print()
    
    # Save files
    print("Step 4: Saving JSONL files...")
    save_jsonl(train_examples, train_output)
    save_jsonl(val_examples, val_output)
    print()
    
    # Show example
    print("="*60)
    print("SAMPLE TRAINING EXAMPLE")
    print("="*60)
    if train_examples:
        example = train_examples[0]
        print(json.dumps(example, indent=2, ensure_ascii=False))
    print()
    
    print("="*60)
    print("CONVERSION COMPLETE")
    print("="*60)
    print(f"Next steps:")
    print(f"  1. Review {train_output.name}")
    print(f"  2. Check {val_output.name}")
    print(f"  3. Run fine-tuning script with these files")
    print()


if __name__ == '__main__':
    main()