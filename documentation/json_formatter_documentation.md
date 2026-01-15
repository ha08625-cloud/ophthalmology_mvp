### JSON Formatter (json_formatter_v2.py)

**Role:** Serialization to standard medical format  
**Key characteristic:** Output-only, never used for persistence

#### Responsibilities
- Transforms State Manager clinical output to schema-compliant JSON
- Adds metadata (consultation_id, generated_at, total_episodes)
- Validates structure against `json_schema.json`
- Only called once at end of consultation

#### Input
From StateManager.export_clinical_view():
```python
{
    'episodes': [list of episode dicts],
    'shared_data': {shared data dict}
}
```

#### Output
Schema-compliant dict:
```python
{
    'schema_version': '2.1.0',
    'metadata': {
        'consultation_id': str,
        'generated_at': str,  # ISO 8601 UTC
        'total_episodes': int
    },
    'episodes': [
        {
            'episode_id': int,
            'metadata': {
                'timestamp_started': str,
                'timestamp_last_updated': str,
                'completeness_percentage': float
            },
            'presenting_complaint': {...},
            # ... other grouped fields
        }
    ],
    'shared_data': {
        'past_medical_history': [...],
        'medications': [...],
        # ... etc
    },
    'audit_metadata': {}
}
```

#### Validation Strategy
- **Strict:** Required structure must be present (raises ValueError if missing)
- **Permissive:** Extra fields logged but accepted
- No type conversion (State Manager provides correct types)
- No completeness calculation in V2 (removed from formatter)

#### Key Constraints
- NEVER called during turn processing
- NEVER used for persistence or state rehydration
- Only called by DialogueManager.generate_outputs()
- Reads from State Manager, doesn't write back
