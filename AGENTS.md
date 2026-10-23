# AGENTS.md

## Project

Modular FastMCP server (`src/assistant_mcp/`). Each toolset lives in
`src/assistant_mcp/toolsets/<name>.py`, exposes `mcp = FastMCP("<name>")`,
and is registered in `TOOLSETS` (`src/assistant_mcp/toolsets/__init__.py`). Tool inputs are
flat `Annotated[type, Field(...)]` parameters; outputs are structured
(pydantic model, `Image`, or `ToolResult`), never plain strings;
if possible implement tools async (offload blocking SDK calls via
`asyncio.to_thread` so the event loop is never blocked);
toolset modules hold no cross-request state, except `lru_cache`-wrapped
client builders. Parameter descriptions, examples, output structure, and
statelessness are enforced by `tests/test_toolsets.py`; tests drive tools
via `fastmcp.Client`. Helpers exchange pydantic models, not raw dicts or
lists; use `Image` for images. Binary artifacts (generated documents) are
not embedded in tool results: they are uploaded to the public GCS document
bucket via `toolsets/storage.py` and returned as a public resource URL
(`GenerationResult.url`).

## Docs discipline

Prefer deterministic checks (test, lint, CI) over prose rules: wire the
check first, keep the doc a one-line pointer. Keep this file and the
skills (`.vibe/skills/`) minimal — load-bearing rules and navigation
pointers only.

## Commits

Commit messages use the Conventional Commits types configured in
`.releaserc` (enforced by commitlint in CI); semantic-release derives the
version and the Cloud Run
deploy runs only on a release. Ship Cloud Run changes with a releasable
type; other types deliberately stay undeployed.

## Verification

CI (`.github/workflows/ci.yml`) runs ruff, mypy, pytest, actionlint,
markdownlint, commitlint, and a
Docker build with the test suite inside the image; skipped tests fail the
in-image run. Toolsets that wrap an external service (WebDAV, S3,
third-party APIs): verify protocol and path conventions against the real
service — or a recorded real response — before the change's tasks are
checked off; a fully mocked client must mirror a recorded real response
shape, never an assumed one. Live credentials stay in ephemeral scratch
files outside the repo; committing them fails `tests/test_repo_hygiene.py`.

Project rules live in `openspec/config.yaml`; OpenSpec artifacts are
written in English.

## Deliberately deferred (pdf toolset)

- ODT/ODP input formats, Google Docs/Sheets, Mermaid and Vega-Lite
  diagrams are known follow-ups, deliberately out of scope of the
  pdf toolset change.

## Deliberately deferred (docx toolset)

- Reverse conversion (DOCX to Markdown/HTML), caller-configurable
  styling, and CJK font support are known follow-ups, deliberately out
  of scope of the add-docx-toolset change.

## Deliberately deferred (stateless startup probe)

- Validating the startup-probe timing values (60 s budget, 1 s period)
  against the first real Cloud Run cold start is a known follow-up,
  deliberately out of scope of the stateless-startup-probe change;
  adjust the deploy workflow flags together.

## Deliberately deferred (oauth refresh rotation)

- The in-flight refresh-rotation race inside a single rotation's Firestore
  roundtrip (two parallel refreshes that both pass the grace check before
  the winner writes its grace entry) remains; the service-auth grace window
  covers the common concurrent and retry cases, and eliminating the residual
  would require distributed locking.
- The post-deploy checklist item (a redeploy must not force a connector
  re-authorization) still needs its first real confirmation after the
  seamless-deploy-oauth release deploys.
