# Tasks

Parallelization: each group's tasks are internally TDD-sequential (test first, then minimal implementation). Groups 2-5 depend on group 1 (environment). Groups 2, 3, and 6 are parallelizable with each other after group 1; group 4 depends on 2 and 3 (tool wiring uses detection + renderer); group 5 depends on 4 (tool-metadata tests exercise the wired tool); the final integration group depends on all.

## 1. Environment setup (not parallelizable with any group that runs tests/linters - shared uv.lock/.venv)

- [x] 1.1 Add `weasyprint` to `pyproject.toml` runtime dependencies and run `uv lock` + `uv sync`; verify `uv run python -c "import weasyprint"` succeeds in the project environment
- [x] 1.2 Add the Pango system libraries (`libpango-1.0-0`, `libpangoft2-1.0-0` plus transitive deps like libharfbuzz/libffi) to the Dockerfile apt install; verify with a Docker build (`docker build .`) - config file, validated by build and linters, exempt from TDD
- [x] 1.3 Empirically verify WeasyPrint behavior in the project environment (design.md "Empirical verification"): fragment without `<html>` wrapper renders; a URL-fetcher restriction blocks network schemes while data-URIs work; umlauts and `<style>` blocks apply. Record the observed behavior in the design's verification note; if any assumption fails, stop and revise the design before continuing

## 2. Format detection (parallelizable with 3 and 6 after group 1)

- [x] 2.1 Write the failing tests in `tests/test_pdf_toolset.py` for the detection function driven through `generate_pdf`/its public surface: HTML document input routes to the HTML path; Markdown input routes to the Markdown path; Markdown with an embedded HTML snippet stays Markdown; plain text stays Markdown. Verify by running `uv run pytest tests/test_pdf_toolset.py -k detect` and confirming the tests fail for the expected reason (no detection yet)
- [x] 2.2 Implement the minimal detection (prefix heuristic per design.md: HTML indicators vs. Markdown indicators, first indicator wins, named constants for all indicator strings) to make the tests pass; verify `uv run pytest tests/test_pdf_toolset.py -k detect` passes

## 3. HTML renderer (parallelizable with 2 and 6 after group 1)

- [x] 3.1 Write the failing tests for HTML rendering: an HTML fragment produces `%PDF-` bytes via the MCP client; a full document with an embedded `<style>` block applying color/font produces a PDF whose styled text reflects it; umlauts/entities render correctly; external-resource references do not trigger network fetches (assert via the injected fetcher restriction, no real network). Verify the tests fail for the expected reason (no HTML path yet)
- [x] 3.2 Implement the minimal renderer: `HTML(string=...)` with a URL fetcher that rejects every non-data-URI scheme, WeasyPrint exceptions wrapped in `ToolError`. Verify `uv run pytest tests/test_pdf_toolset.py -k html` passes

## 4. Tool interface wiring (blocked by 2 and 3)

- [x] 4.1 Write the failing tests for the `format` parameter through the MCP client: default `auto` uses detection; `format="html"` and `format="markdown"` override it; an invalid value returns a ToolError naming the supported values; empty text errors on all formats; existing Markdown scenarios keep passing untouched. Verify the new tests fail for the expected reason
- [x] 4.2 Add the `format` parameter to `generate_pdf` (case-insensitive, validated, documented description with examples per toolset conventions) and wire detection + renderer into the tool. Verify `uv run pytest tests/test_pdf_toolset.py` passes

## 5. Tool metadata and docs (blocked by 4)

- [x] 5.1 Update/extend the parameter-description/output-structure tests in `tests/test_toolsets.py` for the new `format` parameter (descriptions, examples present; per repo rules the tool surface is tested there). Verify `uv run pytest tests/test_toolsets.py` passes
- [x] 5.2 Update `README.md` (tool list and pdf toolset section) to document HTML input, automatic detection, the `format` escape hatch, and the inline-only resource policy. Verify `uv run npx markdownlint-cli2 README.md` passes (or the repo's documented markdownlint invocation)

## 6. Image/runtime readiness (parallelizable with 2 and 3 after group 1)

- [x] 6.1 Confirm the CI in-image test run covers WeasyPrint: the Docker image build (from 1.2) plus in-image pytest succeeds with the new tests un-skipped (skipped tests fail the in-image run per AGENTS.md). Verify via the CI workflow run or a local `docker build` + in-image `uv run pytest tests/test_pdf_toolset.py`

## 7. Integration verification (blocked by 1-6)

- [x] 7.1 Run the full suite and linters: `uv run pytest`, `uv run ruff check`, `uv run mypy`. All green before any task above is checked off as complete; report a concise summary
- [x] 7.2 Run `openspec validate --change add-html-to-pdf` and confirm the change validates with no errors
