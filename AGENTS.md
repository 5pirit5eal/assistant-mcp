# AGENTS.md

## Project

Modular FastMCP server (`src/assistant_mcp/`). Each toolset lives in
`src/assistant_mcp/toolsets/<name>.py`, exposes `mcp = FastMCP("<name>")`,
and is registered in `TOOLSETS` (`toolsets/__init__.py`). Tool inputs are
flat `Annotated[type, Field(...)]` parameters with a non-empty description
and at least one example. Tool outputs are structured: a pydantic model,
`Image` for image content, `File` for binary content, or a `ToolResult`
combining both; plain strings are forbidden (enforced by
`tests/test_toolsets.py`). `File.format` maps to `application/<format>`
outside a small text table — use `Image` for images. Helpers exchange
pydantic models, not raw dicts or lists; pass primitives directly. Toolset
modules hold no cross-request state, except `lru_cache`-wrapped client
builders keyed by complete credentials. Tests
drive tools via `fastmcp.Client`. Verify with `uv run pytest`,
`uv run ruff check .`, and `uv run mypy src`.

## Verification

- Dockerfile or dependency changes: `docker build` must succeed before the
  task is marked done. Run container-dependent scenarios inside the built
  image (`docker run ... uv run --no-sync python`).
- Tests gated on system tools (soffice) skip on machines without the tool;
  they are only verified when actually run (locally or in the Docker image).
  Never treat a skip as passing.
- Toolsets that wrap an external service (WebDAV, S3, third-party APIs):
  verify protocol and path conventions against the real service — or a
  recorded real response — before the change's tasks are checked off. A
  fully mocked client must mirror a recorded real response shape, never an
  assumed one.
- Credentials used for live verification runs never go into repo files,
  tests, or fixtures: keep them in ephemeral scratch files outside the repo
  and delete them after use.
- Project rules live in `openspec/config.yaml`; OpenSpec artifacts are
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
  adjust the deploy workflow flags and the pinned deploy-config test
  together.
