---
name: openspec-diagnose
description: Diagnosis loop for hard bugs and performance regressions encountered during an OpenSpec change. Use when the user says "openspec diagnose" or "opsx diagnose", or when apply reports something broken, throwing, failing, or slow. Complements, not replaces, the test-first implementation cycle.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "custom"
---

A discipline for hard bugs - inspired by Matt Pocock's diagnosing-bugs skill, adapted to OpenSpec. Skip phases only when explicitly justified.

**Redact.** This skill has you show commands, outputs, and captured artifacts. Redact every secret first: write `<REDACTED>` in its place. Build loops against env vars, so the credential stays in the environment rather than in what you show.

## Phase 1: Build a feedback loop

**This is the skill.** Everything else is mechanical. If you have a tight pass/fail signal for the bug (one that goes red on _this_ bug), you will find the cause. If you don't, no amount of staring at code will save it.

Spend disproportionate effort here. Be aggressive, be creative, refuse to give up. Ways to construct one, in roughly this order:

1. **Failing test** at whatever public interface reaches the bug (fits the TDD rules in `openspec/config.yaml`).
2. **HTTP script** against a running local server (e.g., the MCP server under `/mcp`).
3. **CLI invocation** with a fixture input, diffing stdout against a known-good snapshot.
4. **Replay a captured trace**: save a real request / payload / event log to disk; replay it through the code path in isolation.
5. **Throwaway harness**: spin up a minimal subset of the system (one toolset, mocked dependencies) that exercises the bug code path with a single function call.
6. **Property / fuzz loop**: if the bug is "sometimes wrong output", run 1000 random inputs and look for the failure mode.
7. **Bisection harness**: if the bug appeared between two known states, automate "boot at state X, check, repeat" so you can `git bisect run` it.
8. **Differential loop**: run the same input through old-version vs new-version and diff outputs.

Treat the loop as a product. Once you have _a_ loop, tighten it:

- Can I make it faster? (Cache setup, skip unrelated init, narrow the test scope.)
- Can I make the signal sharper? (Assert on the specific symptom, not "didn't crash".)
- Can I make it more deterministic? (Pin time, seed RNG, isolate filesystem, freeze network.)

A 30-second flaky loop is barely better than no loop; a 2-second deterministic one is tight.

### Non-deterministic bugs

The goal is not a clean repro but a **higher reproduction rate**. Loop the trigger 100x, parallelise, add stress, narrow timing windows, inject sleeps. A 50%-flake bug is debuggable; 1% is not.

### When you genuinely cannot build a loop

Stop and say so explicitly. List what you tried. Ask the user for: (a) access to whatever environment reproduces it, (b) a redacted captured artifact, or (c) permission to add temporary instrumentation. Do **not** proceed to hypothesise without a loop.

### Completion criterion: a tight loop that goes red

Phase 1 is done when you can name **one command** (a script path, a test invocation, a HTTP call) that you have **already run at least once** (show the invocation and its output, redacted), and that is:

- [ ] **Red-capable**: it drives the actual bug code path and asserts the **user's exact symptom**, so it can go red on this bug and green once fixed.
- [ ] **Deterministic**: same verdict every run (flaky bugs: a pinned, high reproduction rate).
- [ ] **Fast**: seconds, not minutes.
- [ ] **Agent-runnable**: you can run it unattended.

If you catch yourself reading code to build a theory before this command exists, **stop: jumping straight to a hypothesis is the exact failure this skill prevents.** No red-capable command, no Phase 2.

## Phase 2: Reproduce + minimise

Run the loop. Watch it go red as the bug appears. Confirm:

- [ ] The loop produces the failure mode the **user** described, not a different failure that happens to be nearby.
- [ ] The failure is reproducible across multiple runs.
- [ ] You have captured the exact symptom (error message, wrong output, slow timing) so later phases can verify the fix addresses it.

Once red, shrink the repro to the **smallest scenario that still goes red**. Cut inputs, callers, config, data, and steps one at a time, re-running the loop after each cut. Done when every remaining element is load-bearing: removing any one of them makes the loop go green.

## Phase 3: Hypothesise

Generate **3-5 ranked hypotheses** before testing any of them; single-hypothesis generation anchors on the first plausible idea. Each hypothesis must be **falsifiable**: state the prediction it makes.

> Format: "If <X> is the cause, then <changing Y> will make the bug disappear / <changing Z> will make it worse."

**Show the ranked list to the user before testing**, using the built-in `ask_user_question` tool (this is a decision point for them, like the clarification questions in explore): offer your ranking as the leading option so choosing it confirms the order, and rely on the free-text option for re-ranking or corrections. They often have domain knowledge that re-ranks instantly. Don't block: proceed with your ranking if the user is away.

## Phase 4: Instrument

Each probe must map to a specific prediction from Phase 3. Change **one variable at a time**. Tool preference:

1. Debugger / REPL inspection if the environment supports it. One breakpoint beats ten logs.
2. Targeted logs at the boundaries that distinguish hypotheses. Never "log everything and grep".
3. Tag every debug log with a unique prefix, e.g. `[DEBUG-a4f2]`. Cleanup becomes a single grep.

**Performance branch.** For performance regressions, logs are usually wrong: establish a baseline measurement first, then bisect. Measure first, fix second.

## Phase 5: Fix + regression test

This phase is the TDD red-green cycle from `openspec/config.yaml`, applied to the bug:

1. Turn the minimised repro into a **failing regression test** at a suitable public interface - one where the test exercises the **real bug pattern** as it occurs at the call site. If every available interface is too shallow to replicate the triggering chain, note that as a finding (the architecture prevents locking this bug down) and discuss with the user.
2. Watch it fail. If you forced the red by mutating code or a fixture, diff against a pristine copy to prove the mutation landed.
3. Apply the fix.
4. Watch it pass.
5. Re-run the Phase 1 feedback loop against the original, un-minimised scenario.

## Phase 6: Cleanup

Required before declaring done:

- [ ] Original repro no longer reproduces (re-run the Phase 1 loop)
- [ ] Regression test passes (or the missing suitable interface is documented)
- [ ] All `[DEBUG-...]` instrumentation removed (grep the prefix)
- [ ] Throwaway prototypes deleted
- [ ] The confirmed hypothesis stated in the commit message, so the next debugger learns

## Relation to OpenSpec

- **During apply:** a bug blocking a task enters this loop; the regression test becomes part of the change's tests, and the task stays incomplete until the loop finishes.
- **Spec gaps:** if the root cause is that the spec allowed the buggy behavior (a missing requirement or scenario), surface it - the fix for the spec goes through `/openspec-update-change`, not silently into code.
- **No silent scope expansion:** if the bug is outside the change's spec, report it and let the user decide: fix within this change (update the spec), or a follow-up change via `/openspec-propose`.
