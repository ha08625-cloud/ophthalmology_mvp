### Phase 4: Question Selector V2

**Goal:** Make Question Selector episode-aware

**Requirements:**
1. Accept episode context (which episode are we asking about?)
2. Reset state per episode (don't carry over answered questions)
3. Track answered questions per episode, not globally
4. Return episode-appropriate questions only

**Design points already discussed**
1. **Restart for V2 or build on top of V1?**
   - Restart.  Reduces likelihood of technical debt.  Significant restructuring required for V2 multi-episode architecture

2. **Interface:** How to pass episode context?**
   - Pass entire episode data
   - Use a single, explicit dependency boundary
   - Treat the selector as a pure decision engine
   - Require callers to provide the full, authoritative context the selector needs
   - Selector receives one object: episode_data. It must be the full, authoritative context - no additional parameters such as questions_answered should be passed separately
   - Keep all state ownership inside the state manager
   - Minimizes hidden coupling
   - Avoids partial-context ambiguities that will appear immediately in multi-episode logic
   - Maximizes determinism of the selector. Deterministic modules should not depend on external I/O or implicit state. They take structured context in, produce a single structured output, and remain stateless
   - Ensures reproducibility and debuggability. If the selector runs on a frozen JSON snapshot of episode_data, you can reproduce a test run exactly. This matters once you introduce contradiction-detection, provenance weighting, and multi-episode summarization
   - Enables stable versioning. If your selector accepts structured episode_data along with a ruleset, you can evolve the state manager’s internals without rewriting the selector each time

3. **Decouple clinical logic from core modules completely**
   - Previous V1 question selector included:
        self.section_order = [
            "chief_complaint",
            "vision_loss",
            ...
            "functional_impact"
        ]
   - Any change to ruleset or JSON schema required updates to this section - messy
   - Let's remove this and add an explicit section_order array at top level in ruleset.json instead

4. **Answered Questions Tracking - Per-episode or global? Current V1 behavior: Global set questions_answered tracks all questions ever asked**
   - Both answered questions and episode tracking should be the sole responsibility of State Manager, do not allow state ownership to bleed into other core modules unless absolutely necessary
   - Selector must remain stateless and reproducible.
   - Internal tracking inside the selector becomes hidden state. Hidden state breaks determinism and complicates resets, rewinds, and provenance reconstruction.
   - Dialogue Manager already depends on authoritative state.
   - Routing, episode switching, and multi-episode summarization all depend on knowing which questions were asked in each episode. Centralizing this avoids multiple interpretations.
   - Persistence and debugging become straightforward.
   - Storing this inside the state manager means a single serialized snapshot describes the full consultation, including question history per episode.
   - Multi-episode logic requires symmetric visibility.
   - Once you add contradiction detection or provenance weighting, you will need historical question traces for every episode. Keeping this in one place prevents diverging histories.

5. **State Reset:** When to reset answered questions?
   - Reset only when state ownership demands it, not inside the selector
   - Never reset automatically on episode transition
   - Automatic resets hide state changes and create non-deterministic flows. Episode transitions must not trigger silent mutations
   - Provide an explicit reset path in the state manager
   - Example: state.reset_questions_answered(episode_id)
   - Dialogue manager decides when to call it
   - Default behaviour: do not reset previous episode's history when creating further episodes during a multi-episode consultation.
   - Each episode’s question history remains intact unless the dialogue manager has a defined reason to wipe it
   - Each new episode starts with an empty questions_answered set automatically because it is a new episode object and each episode has its own isolated question namespace

6. **Question Tracking:**
   - Use per-episode sets. Avoid any global structure with prefixes.
   - Episodes are logical partitions.
   - Each episode is an independent history container. Forcing a global namespace and prefixing episode IDs onto question IDs collapses that partition and creates unnecessary coupling.
   - Global sets become brittle.
   - Prefix-based tracking leaks implementation detail into every consumer. Any change to prefix format breaks downstream logic.
   - Per-episode sets preserve clean invariants.
   - episode.questions_answered expresses exactly one thing: what was asked in that episode. No encoding tricks, no cross-contamination.
   - Cross-episode reasoning remains explicit.
   - If you need global queries later (“has this question ever been asked across all episodes?”), compute it from the per-episode sets. Derived, not stored.
   - Implementation:
episode.questions_answered -> set[str]
   - State manager holds one set per episode. Selector consumes it through episode_data



## Testing Strategy ##

**Question Selector V2:**
1. Unit tests with mock state (fast)
2. Integration test with real State Manager V2
3. Test with Dialogue Manager V2

---

## Critical Reminders for Next Session

1. **Decouple clinical data from core modules
2. **Episode transition happens AFTER all questions:** Including follow-up blocks
3. **Unmapped fields in dialogue metadata:** Not in episode data
4. **current_episode_id is UI state:** Never exported to JSON
5. **Trust parser with retry:** Don't duplicate interpretation logic
6. **Core modules should retain separate functions

---

## Notes for planning question selector V2
 - Ask questions before planning
 - Write a comprehensive plan before coding
 - Feel free to question any design decisions: Problems are easier to fix before coding than after
 - Good software design principles are more important than speed