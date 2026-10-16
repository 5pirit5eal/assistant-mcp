# AGENTS.md

## Project

Modular FastMCP server (`src/assistant_mcp/`). Toolsets live in
`src/assistant_mcp/toolsets/<name>.py`, expose `mcp = FastMCP("<name>")`,
and are registered in `src/assistant_mcp/toolsets/__init__.py`
(`TOOLSETS`). Tests drive tools through the public MCP interface via
`fastmcp.Client`. Run with `uv run pytest`, lint with `uv run ruff check .`
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
