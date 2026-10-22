---
name: openspec-retro
description: Review a completed or in-flight OpenSpec session and propose operative improvements to the project's steering surfaces - AGENTS.md, openspec/config.yaml, and the OpenSpec skills. Use when the user asks for a retrospective, says "openspec retro" or "opsx retro", or wants to improve how the project and its agents work together based on lessons from a change.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: openspec
  version: "1.0"
  generatedBy: "custom"
---

Conduct a retrospective on an OpenSpec session. You are proposing improvements to the project's **operative surfaces** - the instructions, rules, and workflows that steer future agents - not to the product code.

**This skill runs inline, in the current session, with your own context.** Do not dispatch subagents. Your session context is the primary source here: you experienced the friction first-hand. Only read files to verify facts, never to re-derive what you already know happened.

**Trigger:** This skill is invoked manually by the user when needed. It is never auto-run as part of apply or archive. After `openspec apply`, the apply workflow only reports whether a retro appears necessary and points here; the user decides.

## Project principles

The project's standing principles for its operative surfaces. Check AGENTS.md, `openspec/config.yaml`, and the skills against them - for session findings and as a proactive scan - and hold every proposed edit to them:

- **Fewest words.** Load-bearing rules and navigation pointers only, each in the fewest full readable sentences.
- **No restated enforcement.** A rule that code, tests, lint, or CI already enforces deterministically does not belong in the docs: remove the prose, leave a one-line pointer to the check.
- **Checks before prose.** A new rule becomes a deterministic check (test, lint, CI) whenever possible, never markdown.
- **Single source of truth.** Content shared by several skills lives in exactly one place; other skills point at it with one lightweight line. Cross-skill and cross-file references stay sparse.

## Steps

1. **Establish scope**
   If the user names a change or session, use it. Otherwise:
   - Run `openspec list --json` and `openspec list --specs` to see active and recent changes
   - Default to the change the conversation has been working on
   If no change exists at all, the retro covers the OpenSpec setup and steering surfaces themselves.

2. **Collect findings from the session**
   Review what happened during the session and look for candidates in these categories, in this order of value:
   - **AGENTS.md**: conventions and constraints the session revealed that future agents should follow but that are written nowhere. Navigation pointers to important files.
   - **openspec/config.yaml**: rule gaps - would a `context`, `rules`, or `operations` entry have prevented a problem the session hit? Would an existing rule have been better worded? Are there no-op rules that modify nothing?
   - **Skills (.vibe/skills/)**: workflow gaps - did a skill guide the session into friction, miss a step, or produce an output that did not help? Only propose skill edits that would change future behavior.
   - **Automated checks before prose**: if the session made a mistake an automated check (lint, test, validation) could catch, propose wiring the check instead of writing a rule.
   Classify every finding: **mechanical** (deterministic check can enforce it) or **judgement** (needs a human/agent rule in AGENTS.md or config.yaml).

3. **Assess necessity and present candidates**
   Present the candidates to the user, ordered by severity, each with:
   - **Finding**: what happened in the session (evidence: what you did, what went wrong or took long)
   - **Proposal**: the concrete edit - as a before/after block or diff - and which surface it targets (AGENTS.md, config.yaml, skill)
   - **Recommendation**: one of `Notwendig` (will prevent a recurring problem), `Empfohlen` (clear value, not urgent), `Optional` (nice to have), `Nicht empfohlen` (considered and rejected - state why)
   End with an overall verdict: does the steering setup need changes at all, and which single candidate to tackle first if any.

4. **Apply approved proposals**
   Apply only what the user approves, exactly as approved:
   - Create `AGENTS.md` lazily if it does not exist
   - Keep `openspec/config.yaml` valid: after editing, run `openspec validate --all`
   - For skill edits, keep the existing skill structure and wording style
   Re-check that no proposal contradicts another approved proposal or the project principles.

5. **Summarize**
   Report what was applied, what was rejected, and what was deferred to a future change (deferred items can become their own OpenSpec change via `/openspec-propose`).

## Notes

- Never propose product-code refactors here; those belong in a change created via `/openspec-propose` or in the apply workflow's gap analysis.
- One retro covers one session or change. Do not batch multiple unrelated sessions.
- If the session went smoothly and nothing surfaced, say so and recommend no changes. An empty retro is a valid outcome.
