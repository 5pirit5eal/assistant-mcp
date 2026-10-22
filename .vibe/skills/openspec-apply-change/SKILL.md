---
name: openspec-apply-change
description: Implement tasks from an OpenSpec change. Use when the user wants to start implementing, continue implementation, or work through tasks. Also use when the user says "openspec apply", "opsx apply", or "openspec implement".
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "1.14.2"
---

Implement tasks from an OpenSpec change.

**CLI basics:** Load the `openspec-cli` skill first; it covers `--store` selection, the project-root check, change selection, and `<capability-path>`.

**Steps**

1. **Select the change**

   Follow `openspec-cli`.

2. **Check status to understand the schema**
   ```bash
   openspec status --change "<name>" --json
   ```
   Parse the JSON to understand:
   - `schemaName`: The workflow being used (e.g., "spec-driven")
   - `planningHome`, `changeRoot`, and `actionContext`: planning scope and edit constraints
   - Which artifact contains the tasks (typically "tasks" for spec-driven, check status for others)

3. **Get apply instructions**

   ```bash
   openspec instructions apply --change "<name>" --json
   ```

   This returns:
   - `contextFiles`: artifact ID -> array of concrete file paths (varies by schema - could be proposal/specs/design/tasks or spec/tests/implementation/docs)
   - Progress (total, complete, remaining)
   - Task list with status, source path, and source line
   - Dynamic instruction based on current state
   - Optional `context`: current required project instruction input from the selected root
   - Optional `operationGuidance`: current advisory guidance for apply
   - `missingArtifacts` (when present): required artifact ids with no output

   **Handle states:**
   - If `state: "blocked"`: show the message and pause implementation.
     - If `missingArtifacts` is non-empty: suggest completing the missing artifacts. Run `openspec status --change "<name>" --json`, select the next `ready` artifact (not `skipped` or `blocked`), and use `openspec instructions "<artifact-id>" --change "<name>" --json` for its rules and template. Keep the selected `--store <id>` on both commands.
     - Otherwise, follow the CLI instruction to create or repair the schema-configured tracking file from existing planning artifacts. Do not assume another artifact is ready or start implementation while blocked.
   - If `state: "all_done"`: report that all tracked tasks are complete and suggest review or verification as appropriate before archiving
   - Otherwise: proceed to implementation

   Treat `context` as a required prompt-level input. Read and consider it, and
   apply relevant project facts, conventions, and constraints while implementing.
   Treat `operationGuidance` as optional additive advice. Read and consider every
   entry, and follow entries that are applicable and compatible with the built-in
   workflow.

   Keep both fields separate from CLI-returned state, missing artifacts, tasks,
   progress, `contextFiles`, and the built-in `instruction`. They are not
   evidence of task completion, do not replace the built-in instruction, and do
   not permit bypassing a blocked state. If context conflicts with the built-in
   instruction, an explicit user choice, or a CLI-controlled value, report the
   conflict and preserve the controlling value. If guidance is inapplicable or
   conflicts with those controlling inputs, do not follow it and explain why.
   These are prompt-level behavior contracts, not enforceable checks.

4. **Read context files**

   Read every file path listed under `contextFiles` from the apply instructions output.
   The files depend on the schema being used:
   - **spec-driven**: proposal, specs, design, tasks
   - Other schemas: follow the contextFiles from CLI output

   Do not copy `context` or `operationGuidance` verbatim into implementation
   files or planning artifacts unless the user separately asks for that content.

5. **Show current progress**

   Display:
   - Schema being used
   - Progress: "N/M tasks complete"
   - Remaining tasks overview
   - Dynamic instruction from CLI

6. **Implement tasks (loop until done or blocked)**
   First, read the tasks file and derive the execution waves:
   - The tasks file declares which tasks are parallelizable and which tasks
     block which (per the tasks rules in `openspec/config.yaml`). If the
     declaration is missing, derive the dependencies yourself from real
     coupling (shared files, interfaces other tasks consume, ordering the
     spec demands) and tell the user your derivation.
   - **Wave 1**: every task whose blocking tasks are all complete. If several
     such tasks are independent of each other, run them **in parallel**:
     dispatch one subagent per parallelizable task, each with a fresh session,
     the task description, the relevant spec/design context, the TDD rules,
     and the instruction to implement test-first and mark its own task
     checkbox when done. Do not run tasks in the same wave if they touch the
     same files.
   - Wait for the whole wave to finish before starting the next: a wave is
     done when every subagent has completed or reported a blocker.
   - **Next wave**: tasks whose blockers are now complete, again in parallel
     where independent. Repeat until no tasks remain.
   - Re-run `openspec instructions apply --change "<name>" --json` after each
     wave to refresh progress and task locations.
   If subagents are not available in the current environment, fall back to
   executing wave by wave sequentially and say so.

   For each pending task:
   - Show which task is being worked on
   - Make the code changes required
   - Keep changes minimal and focused
   - Before editing, confirm the checkbox at the returned `sourcePath` and `line` still matches the task description; if it does not, rerun the apply instructions and use the refreshed location
   - Mark the task complete at its returned `sourcePath` and `line`: `- [ ]` → `- [x]`
   - Rerun the apply instructions and confirm that task is now done and progress changed
   - Continue to next task

   **Pause if:**
   - Task is unclear → ask for clarification
   - Implementation reveals a design issue → suggest updating artifacts
   - A **hard bug or performance regression** is encountered → enter the `openspec-diagnose` loop before attempting a fix; never patch blind
   - A task needs work beyond what the spec and tasks describe, or you are tempted to drop, narrow, defer, or accept exceptions to specified behavior to make it fit → surface the added scope and ask; do not absorb it silently
   - Error or blocker encountered → report and wait for guidance
   - User interrupts

7. **On completion or pause, show status**

   Display:
   - Tasks completed this session
   - Overall progress: "N/M tasks complete"
   - If all done: report that tracked tasks are complete and suggest review or verification as appropriate before archiving
   - If paused: explain why and wait for guidance

8. **Gap analysis review (on completion, before archiving)**
   When all tasks are complete, run a fresh-eyes review before suggesting the
   archive. Do NOT review inline with your own session context - your context
   is saturated with the implementation and will miss its own blind spots.

   Dispatch a subagent with a fresh session (no conversation history, no prior
   tool results) and give it exactly this mission:
   - Read the change's specs (requirements and scenarios) and the main specs
     it touches, then read the actual implementation (code and tests).
   - Gap analysis: does the implementation satisfy every requirement and every
     scenario? List each gap as requirement/scenario -> what the spec demands
     -> what the code does -> the concrete evidence (file and line).
   - Standards: does the code follow the repo's documented standards
     (AGENTS.md, openspec/config.yaml rules, conventions visible in the
     surrounding codebase)? Each standards finding names the standard and the
     evidence. Judgement calls, never hard violations; a documented repo
     convention always wins over a generic heuristic.
   - Engineering improvements: identify concrete improvement opportunities in
     the touched code (simplification, error handling, missing test coverage,
     naming, consistency with the rest of the codebase). No speculative
     refactoring, no style bikeshedding - each finding needs evidence.
   The subagent MUST NOT modify any files. It returns findings only.

   Present the findings to the user for approval, grouped as "Spec gaps",
   "Standards findings", and "Engineering improvements", each with evidence.
   Wait for the user's decision before doing anything with them.

9. **Retro recommendation (on completion)**
   After the user has ruled on the review findings, assess - inline, no
   subagent - whether this session revealed anything that should change the
   project's operative surfaces (`AGENTS.md`, `openspec/config.yaml`, or the
   OpenSpec skills). Examples: a convention future agents should follow, a
   rule that would have prevented a finding, a skill gap the change exposed.

   Give the user a one-line recommendation: `Retro empfohlen` (name the 1-3
   candidates) or `Kein Retro notwendig` (one sentence why). Do NOT run the
   retro yourself and do NOT dispatch a subagent for it - the retro is a
   separate, user-invoked workflow: the user triggers the `openspec-retro`
   skill manually when they want the proposals.

   Approved spec gaps and approved engineering improvements remain actionable
   items of this apply session (fix now or as a follow-up change); the retro
   covers only the operative surfaces.

   Then proceed to the archive suggestion.

**Output During Implementation**

```
## Implementing: <change-name> (schema: <schema-name>)

Working on task 3/7: <task description>
[...implementation happening...]
✓ Task complete

Working on task 4/7: <task description>
[...implementation happening...]
✓ Task complete
```

**Output On Completion**

```
## Implementation Complete

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 7/7 tasks complete ✓

### Completed This Session
- [x] Task 1
- [x] Task 2
...

All tracked tasks are complete. Review or verify the change as appropriate
before archiving. You can archive this change with `/openspec-archive-change`.
```

**Output On Pause (Issue Encountered)**

```
## Implementation Paused

**Change:** <change-name>
**Schema:** <schema-name>
**Progress:** 4/7 tasks complete

### Issue Encountered
<description of the issue>

**Options:**
1. <option 1>
2. <option 2>
3. Other approach

What would you like to do?
```

**Guardrails**
- Keep going through tasks until done or blocked
- Always read context files before starting (from the apply instructions output)
- If task is ambiguous, pause and ask before implementing
- If implementation reveals issues, pause and suggest artifact updates
- Keep code changes minimal and scoped to each task
- Update task checkbox immediately after completing each task
- Pause on errors, blockers, or unclear requirements - don't guess
- When a task needs work beyond what the spec describes, surface the added scope and pause - never silently narrow, defer, or simplify away specified behavior
- Only mark a task `- [x]` when its specified behavior is fully implemented, not when it is partially done or deferred
- Use contextFiles from CLI output, don't assume specific file names
- Use each task's sourcePath and line to update its exact checkbox
- Do not use context or operation guidance as proof that a task is complete
- Apply relevant project context; report conflicts with controlling workflow inputs
- Consider every guidance entry; explain any inapplicable or conflicting advice
- Do not copy runtime context or operation guidance into implementation files or planning artifacts
- Preserve CLI-controlled blocked/ready/all-done behavior and completion criteria

**Fluid Workflow Integration**

This skill supports the "actions on a change" model:

- **Can be invoked anytime**: Before all artifacts are done (if tasks exist), after partial implementation, interleaved with other actions
- **Allows artifact updates**: If implementation reveals design issues, suggest updating artifacts - not phase-locked, work fluidly
