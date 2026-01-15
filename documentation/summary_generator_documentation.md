### Summary Generator (summary_generator_v2.py)

**Role:** Clinical narrative generation  
**Key characteristic:** LLM-based text generation

#### Responsibilities
- Generates readable clinical summary from structured data
- Creates one summary per episode
- Lists shared data without narrativizing
- Tracks token usage with warnings
- Combines episode summaries deterministically

#### Input
From StateManager.export_for_summary():
```python
{
    'episodes': [all episodes including empty],
    'shared_data': {...},
    'dialogue_history': {
        'episode_id': [list of turns],
        # ...
    }
}
```

#### Process
1. For each episode:
   - Build prompt with episode data + dialogue history
   - Call HuggingFace LLM
   - Generate narrative summary
   - Track token count

2. Combine summaries:
   - Episode summaries (narrativized)
   - Shared data (listed, not narrativized)
   - Completeness warnings if applicable

3. Save to text file

#### Token Management
- Tracks cumulative context window usage
- Warns at 32k token threshold
- Each episode processed independently to manage context

#### Output Format
```text
EPISODE 1 SUMMARY
[Narrative summary of presenting complaint and history]

EPISODE 2 SUMMARY
[Narrative summary...]

SHARED CLINICAL DATA
Past Medical History:
- [Items listed]

Medications:
- [Items listed]

[etc.]
```
