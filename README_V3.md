**Purpose:** AI-powered ophthalmology consultation system
**Architecture:** 7 modules + 3 config files, multi-episode structure
**Status:** V3.0 prototype - functional core with Flask transport layer

## Quick Orientation

**Project Type:** Prototype exploring architecture for future clinical product. Single developer. Not intended to aim for production-readiness

**Key Design:** 
- Deterministic medical logic (Question Selector) separate from LLM tasks (Parser, Summary Generator)
- Thin orchestration layer (Dialogue Manager)
- Functional core pattern (state transformations, no implicit accumulation)
- Episode-specific vs shared data split

## File Locations

**Claude's Files:** `/mnt/project/` (server development/testing)
**User's Local Files:** `~/projects/ophthalmology_mvp/` (Windows 10/WSL2 Ubuntu)
**Project Files:** All core modules stored in project files for reference

## Documentation Structure
- **Architecture** - High level architecture details
- **modules.md** - Detailed documentation of individual modules
- **clinical_data_documentation.md** - Config files and data structures
- **Technical_Stack** - Setup and environment
- **File_structure** - Directory layout

## Current Module Status

**Working:**
- State Manager V2: State storage, dumb container
- Question Selector V2: parses ruleset to determine next question
- Response Parser V2: extracts structured clinical information from user responses
- JSON Formatter V2: structured output
- Summary Generator V2: output in form of clinical letter
- Dialogue Manager V2 (functional core, thin orchestrator)
- Flask transport layer

**Key work for this version:**
- create intake layer that manages multi-episode ambiguity

## Core Design Principles
1. Freeze Meaning, Not Implementation
- The prototype prioritises semantic clarity over strict enforcement.
- Module responsibilities and assumptions are made explicit
- Medical protocol is deterministic (Question Selector), language tasks use LLM (Parser, Summary Generator), state manager is dumb, dialogue manager is thin
- Data meaning and lifecycle semantics are documented
- Implementations are allowed to change freely to allow iteration

2. Selective Use of Formal Contracts
- Formal contracts (e.g. schemas, strict validation) are used only where they create leverage, not everywhere.
- Contracts are appropriate when:
- A boundary crosses from probabilistic → deterministic logic
- Data corruption would silently affect clinical meaning
- Outputs are treated as durable artifacts (e.g. JSON summaries)
- Examples:
- State → JSON serialization boundary
- Response Parser → Dialogue Manager boundary
- Elsewhere, docstrings, tests, and clear interfaces are preferred over heavy validation.

3. Orchestration Is Thin and Non-Authoritative
- Dialogue Manager coordinates flow but does not interpret medical meaning, infer intent beyond declared outcomes, repair corrupted state
- Clinical and Operational separation: Clinical data or fields should not be hard coded into modules, only into datasets
- Functional core pattern: DialogueManager is ephemeral per turn, transforming state with no implicit accumulation
- Transport layers (Console/Flask) handle persistence and I/O separately from medical logic

4. Failures Are Informative, Not Hidden
- In the prototype:
- Errors are allowed to surface
- Assumptions are allowed to break
- Inconsistencies are logged, not masked

5. Production Rigor Is Deferred by Design
- Techniques such as Pydantic validation, use of ABCs and defensive programming at every boundary are deliberately deferred.
- Expected in a production rewrite, not in this prototype: architectural exploration and iterations take priority