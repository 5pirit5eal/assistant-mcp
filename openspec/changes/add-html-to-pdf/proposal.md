# Proposal

## Why

The pdf toolset accepts Markdown and plain text, but agents frequently produce HTML (fragments with inline CSS or full documents). Today such input either falls through the Markdown pipeline with degraded fidelity or cannot be turned into a polished PDF at all. Offering HTML rendering as part of the PDF toolset closes this gap with the print-CSS fidelity a browser-grade renderer provides, without forcing callers to rewrite HTML into Markdown.

## What Changes

- `generate_pdf` gains an optional `format` parameter (`"auto"` | `"markdown"` | `"html"`, default `"auto"`) as an escape hatch for explicit override.
- With `format="auto"`, the tool detects the input type with simple content checks: HTML document/block markup appearing before any Markdown-typical token routes to the HTML renderer; otherwise the existing Markdown pipeline runs unchanged.
- HTML input is rendered with WeasyPrint (print-CSS fidelity: colors, fonts, margins, tables, `@page` rules; no JavaScript).
- The renderer processes inline HTML/CSS only: no network access for external resources (images, stylesheets, fonts by URL), keeping results deterministic and avoiding server-side request-forgery risk. Data-URI resources embedded in the input are allowed.
- Invalid format values and empty input produce meaningful errors; the server never crashes.
- The base64 file-input tools (`convert_to_pdf`) are deliberately not extended; no follow-up is documented.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `pdf-generation`: `generate_pdf` gains HTML-to-PDF rendering: input-type detection, a `format` override, and scenarios for HTML fragments, full documents, embedded CSS, Markdown with embedded HTML snippets, error handling, and output guarantees.

## Impact

- `src/assistant_mcp/toolsets/pdf.py`: format parameter, HTML detection, WeasyPrint rendering path.
- `pyproject.toml` / `uv.lock`: new runtime dependency `weasyprint`.
- `Dockerfile`: additional system libraries required by WeasyPrint (`libpango-1.0-0`, `libpangoft2-1.0-0`, and their transitive deps such as `libharfbuzz`/`libffi`).
- `tests/test_pdf_toolset.py`, `tests/test_toolsets.py`: tests for detection, rendering, errors, and tool metadata.
- `README.md`: document the extended `generate_pdf` behavior.
- `openspec/specs/pdf-generation/spec.md`: synced at archive time.
