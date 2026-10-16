# AGENTS.md

## Project

Modular FastMCP server (`src/assistant_mcp/`). Toolsets live in
`src/assistant_mcp/toolsets/<name>.py`, expose `mcp = FastMCP("<name>")`,
and are registered in `src/assistant_mcp/toolsets/__init__.py`
(`TOOLSETS`). Tools declare their inputs as flat parameters annotated
with `Annotated[type, Field(...)]` carrying a non-empty description and
at least one example (plus constraints where applicable), preserving the
callable interface. Tools return structured outputs: a pydantic model as
structured content, or a `File` result for binary content; plain-string
returns are forbidden (enforced by `tests/test_toolsets.py`). Prefer pydantic models over raw iterables/dicts
for helper functions and intermediaries exchanging structured data;
pass primitives (str, int, float) directly. Tests drive tools through
the public MCP interface via `fastmcp.Client`. Run with `uv run pytest`, lint with `uv run ruff check .`
and `uv run mypy src`.

## Verification

- Dockerfile or dependency changes: `docker build` must succeed before the
  task is marked done. Run container-dependent scenarios inside the built
  image (`docker run ... uv run --no-sync python`).
- Tests gated on system tools (soffice) skip on machines without the tool;
  they are only verified when actually run (locally or in the Docker image).
  Never treat a skip as passing.
- Project rules live in `openspec/config.yaml`; OpenSpec artifacts are
  written in English.

## Deliberately deferred (pdf toolset)

- ODT/ODP input formats, Google Docs/Sheets, Mermaid and Vega-Lite
  diagrams are known follow-ups, deliberately out of scope of the
  pdf toolset change.
