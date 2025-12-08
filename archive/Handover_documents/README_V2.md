# Ophthalmology Consultation System - Version 2

## Project Status

**Current Version:** V1.0 (MVP Complete ✓)  
**Next Version:** V2.0 (Expanding to multi-episode architecture)
**Last Updated:** December 03, 2025

---

## Overview

AI-powered system for conducting ophthalmology consultations. Uses LLM for natural language understanding combined with deterministic medical protocol to ensure clinical safety.

**V1 Achievement:** Complete working prototype with all 6 core modules integrated and tested.

**V2 so far:** Completed state_manager_v2.py, dialogue_manager_v2.py and created episode_classifier.py which tracks episode specific fields vs global fields

---

## Quick Start

### Reference documents within project files
- **[Technical_Stack_WSL2_HuggingFace.md](docs/Technical_Stack_WSL2_HuggingFace.md)** - Setup instructions and environment details
- **[File structure]** - Contains the existing core modules and where they are stored
- **[Module architecture]** - Reference guide for the 6 core modules including data flow, integration points, and key design patterns
- **[json_schema.json]** - The JSON schema used for the MVP
- **[ruleset.json]** - The ruleset used for the MVP
- **All the core modules are stored in the project files for reference if needed**
- **Core modules in the project files are for reference.  The system runs on user's local machine, which you do not have direct access to**
- **User is on WSL2/Ubuntu system, using VS code to modify files**
- **Note on versioning files: When updating files, keep the file name intact

## Current Capabilities (V1.0)

### What It Does ✓

1. **Structured Consultation Flow**
   - 30+ questions across 8 medical sections
   - Deterministic question selection (follows clinical protocol)
   - Conditional logic (asks follow-ups based on responses)
   - Trigger blocks for specific conditions (GCA, optic neuritis, etc.)

2. **Natural Language Understanding**
   - Extracts structured data from patient responses
   - Handles varied phrasing ("right eye" → "monocular_right")
   - Maps temporal expressions ("3 months ago", "last Tuesday")
   - Identifies implicit information

3. **Clinical Summary Generation**
   - Patient-directed format (second person: "you report...")
   - Groups negative findings logically
   - Includes relevant quotes from patient
   - Professional clinic letter style

4. **Structured Data Output**
   - JSON format compliant with schema
   - Status blocks per section (completeness tracking)
   - Metadata (consultation ID, timestamps, warnings)
   - Validation and completeness scoring

5. **Web Interface**
   - Chat-style interaction
   - Real-time question/answer display
   - Download JSON and summary at end
   - Professional medical aesthetic

### Limitations (Known Issues)

**Accuracy:**
- Response parsing: ~60-70% accuracy (base model, no fine-tuning)
- Extraction errors common with complex responses
- Some fields consistently missed (laterality specifics, temporal patterns)

**User Experience:**
- Questions sound robotic (direct from ruleset)
- No clarification questions when responses unclear
- Can't handle patient tangents or rambling
- No resume capability if interrupted

**Technical:**
- Single consultation only (no multi-episode support)
- No persistent storage (state resets on restart)
- Console-based error logging only
- Limited error recovery

---

## Architecture Overview

### Six Core Modules

```
1. State Manager (Deterministic)
   - Tracks structured data and dialogue history
   - Updates every turn
   - Exports data for JSON and Summary

2. Question Selector (Deterministic)
   - Parses ruleset and applies conditional logic
   - Returns next required question
   - Activates trigger blocks

3. Response Parser (LLM-Powered)
   - Extracts structured fields from natural language
   - Maps varied expressions to standardized values
   - Returns dict of extracted data

4. JSON Formatter (Deterministic)
   - Converts state to schema-compliant JSON
   - Adds status blocks and metadata
   - Validates completeness

5. Summary Generator (LLM-Powered)
   - Creates clinical narrative from dialogue
   - Second-person format for patient validation
   - Groups negative findings

6. Dialogue Manager (Orchestrator)
   - Coordinates all modules
   - Manages conversation loop
   - Handles I/O and error recovery
   - Generates final outputs
```

**Key Design Principle:** Medical protocol is deterministic (Question Selector), language tasks use LLM (Parser, Summary Generator).

---

## Further enhancements and versions (version are listed roughly in order of importance, but numbering is arbitrary)

**V2.0:**
- Rewrite the core modules to work on multi-episode architecture
- State Manager (complete)
- Dialogue Manager (complete)
- Episode classifier (new module classifies episode specific vs shared fields - complete)
- Question selector (complete)
- JSON formatter (to do)
- Summary generator (to do)

**V3.0:**
- Create the architecture for traceability before fine tuning
- Fine-tuning CANNOT fix: 1. Model copying state instead of extracting from response 2. Contradictions accumulating across turns 3. Lack of audit trail (who said what when?) 4. Inability to resolve references ("that eye")
- Provenance
- Confidence tracking
- Contradiction detection
- Selective state injection
- Create labelled validation set
- Error taxonomy + per-field metrics
- targeted adversarial tests to quantify the exact gap and ROI for fixes
- Confidence calibration

**V4.0:**
- Expand to full consultation with systems review, past medical history, medications, social history (NOTE: systems review is a limited series of yes/no questions for symptoms relevant to neuro-ophthalmology, NOT a full expansion into the rest of general medicine.  Past medical history and medications will largely be sourced from the referal letter NOT from the patient during the consultation, just verified)
- Allow integration of previous clinical records into the summary generator
- Integrate "diagnosis" questions: In most cases, patients will have seen a healthcare professional for one of the episodes and had a provisional diagnosis made, correctly or incorrectly

**V5.0:**
- Fine-Tuning
- Prepare training data with provenance
- Multiple fine-tuning experiments, trial different data augmentation methods, recombination strategies
- A/B testing different LoRA strategies:
- Individual LoRAs (response parser, summary generator and question naturaliser all run on same LoRA) vs specialised LoRAs (response parser, summary generator and question naturaliser trained using different fine tuning data)
- Chunked summarisation vs whole consultation summarisation, consider trialling and evaluating separately fine tuned LoRAs for ophthalmology specific summarisation vs general medical summarisation (systems review, PMH, medications etc)

**V6.0:**
- UX improvements:
- Question naturalizer
- Multi-turn clarification (ask follow ups when unclear)
- Visual aid tool to help describe visual fields and timelines

**V7.0:**
- Reconciliation workflow
- Coref resolver if necessary
- Web UI improvements

Production ready tasks (A long way in the future - only included here for future reference.  Will need a full team, no longer solo hobby project)
- Once all success metrics and variations have been trialled, final push on data augmentation including many variations of messy data for the final fine tuning runs
- Depending on accuracy, we may need to consider moving to a larger system: cloud GPU or upgraded hardware and move from 7B base model to 30B or 70B
- Improving response time (reduce output length, streaming output, prompt caching)
- Trialling with ophthalmologists
- MHRA medical device registration, audit data
- Guardrails against prompt injection, giving diagnoses or management plans
- Cyber security
- Light sense of humour
- Trialling with actual patients and feedback