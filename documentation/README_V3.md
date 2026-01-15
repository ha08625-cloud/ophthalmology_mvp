**Purpose:** AI-powered ophthalmology consultation system
**Architecture:** 7 modules + 3 config files, multi-episode structure
**Status:** V3.0 prototype - functional core with Flask transport layer

## Quick Orientation

**Project Type:** Prototype exploring architecture for future clinical product. Single developer. Not intended to aim for production-readiness

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
- **Invariants.md** - List of hard invariants

## Current Module Status

**Working:**
- State Manager V2: State storage
- Question Selector V2: parses ruleset to determine next question
- Response Parser V2: extracts structured clinical information from raw user responses
- JSON Formatter V2: structured clinical output
- Summary Generator V2: output in form of clinical letter
- Dialogue Manager V2: thin orchestrator
- Flask: transport layer

**Key work for this version:**
- create intake layer that manages multi-episode ambiguity

## Design Decisions
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

3. Failures Are Informative, Not Hidden
- In the prototype:
- Errors are allowed to surface
- Assumptions are allowed to break
- Inconsistencies are logged, not masked

4. Production Rigor Is Deferred by Design
- Techniques such as Pydantic validation, use of ABCs and defensive programming at every boundary are deliberately deferred.
- Expected in a production rewrite, not in this prototype: architectural exploration and iterations take priority
