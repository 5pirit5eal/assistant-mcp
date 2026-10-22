# Design

## Context

`generate_pdf` (`src/assistant_mcp/toolsets/pdf.py`) currently parses Markdown with markdown-it into ReportLab flowables. There is no HTML renderer in the project; the docx toolset accepts HTML only as pandoc input. The server image is `python:3.14-slim` plus LibreOffice/pandoc; deploys run on Cloud Run with ~32 MB request-size limits. Verification during exploration: WeasyPrint 70.0 installs and imports cleanly under Python 3.14; it fails to load only where the Pango system libraries are absent (expected in the slim base image; the Dockerfile must add them).

## Goals / Non-Goals

**Goals:**

- HTML input rendered with print-CSS fidelity (embedded `<style>`, inline styles, `@page`).
- Automatic input-type detection with a `format` override.
- Deterministic, offline rendering: no network access from the renderer.

**Non-Goals:**

- JavaScript execution, grid-level layout, or pixel-identical browser rendering (Chromium/Playwright rejected: +400-600 MB image, slower cold starts).
- Extending the base64 `convert_to_pdf` tool with HTML.
- Fetching or allowing external resources by URL.

## Decisions

### Engine: WeasyPrint

Print-CSS fidelity in a pure-Python-maintained package; needs only Pango/Freetype/Harfbuzz system libs added to the slim image. Alternatives: Chromium/Playwright (rejected: image size), LibreOffice HTML import (rejected: weak, dated CSS support), xhtml2pdf (rejected: CSS fidelity far below the "visually polished" bar).

**Empirical verification (mandatory before finalizing):** the design relies on WeasyPrint behavior against the locked version; a verification task must confirm, in the project environment (`uv` lock, Python 3.14): (1) fragments without `<html>` wrapper render correctly via `HTML(string=...)`, (2) `base_url=None`/no URL fetcher prevents network fetches, (3) German umlauts and `<style>` blocks apply as expected. Exploration already confirmed install/import under Python 3.14; the project-environment run must confirm rendering behavior.

### Detection: conservative prefix heuristic

HTML wins only when HTML-typical markup appears before the first Markdown-typical token. Concrete rule (to be implemented as a small pure function, constants named per repo rules):

- HTML indicators: `<!DOCTYPE`, `<html`, `<head`, `<body`, `<title`, `<meta`, `<style`, `<script`, `<p>`, `<p\u00a0`, `<div`, `<h1`-`<h6`, `<table`, `<ul`, `<ol`, `<br`, `<hr`.
- Markdown indicators: ATX heading lines (`#{1,6}\u00a0`), bullet/ordered list lines (`-\u00a0` / `*\u00a0` / `1.\u00a0`), fence lines, setext underlines (`===`/`---`), table pipes, blockquote lines (`>\u00a0`).
- Scan stripped, non-empty, non-fence content in order; first indicator found decides. Plain text without any indicator is Markdown (today's pipeline).

Rationale: CommonMark permits embedded HTML, so a single "contains `<p>`" check would misroute Markdown documents that embed snippets; prefix ordering makes `# Title\n\n<p>x</p>` Markdown and `<h1>Title</h1><p>x</p>` HTML. Cost: an HTML document that happens to open with Markdown-looking text inside `<style>`/`<script>` comments could misroute; `format` is the escape hatch.

### Interface: `format` parameter on `generate_pdf`

`format: Literal["auto", "markdown", "html"]` with default `"auto"` and a description plus examples, per the toolset-tool-interface conventions. Case-insensitive normalization; unknown values raise `ToolError` naming the supported values. The parameter is the documented escape hatch when detection misroutes.

### Rendering: inline-only, network-free

Render via `HTML(string=text, base_url=None).write_pdf()` with WeasyPrint's default URL fetcher restricted: no `url_fetcher` that performs network I/O; a custom fetcher that raises for any non-data-URI scheme enforces the "no external resources" requirement deterministically. Data-URIs decode locally and are allowed.

### Error handling

Empty input (`text.strip()`) raises `ToolError` on all paths (existing behavior preserved). WeasyPrint render failures are caught and surfaced as `ToolError` with the underlying reason; the server never crashes. Malformed HTML that WeasyPrint can still render yields rendered output (browsers' error recovery), matching the "fragments render" scenario.

## Risks / Trade-offs

- [Detection misroutes an exotic document] -> `format` override is the explicit escape hatch; detection rule is small and fully unit-testable.
- [WeasyPrint system libs missing in the image] -> Dockerfile gains `libpango-1.0-0`, `libpangoft2-1.0-0` (+ transitive `libharfbuzz`, `libffi` etc.); in-image test suite would fail loudly if missing.
- [Large HTML payloads vs. 32 MB request limit] -> Same constraint as existing tools; documented, no new mechanism.
- [WeasyPrint drops unsupported CSS silently] -> Acceptable: print-CSS scope is the agreed fidelity bar; scenarios only assert supported constructs.
- [Cold-start / memory impact on Cloud Run] -> WeasyPrint is a Python library (no new daemon); impact minimal versus Chromium alternative.

## Migration Plan

Additive, backward-compatible: `format` defaults to `"auto"`, existing Markdown callers unchanged. Rollout is a normal release: dependency + Dockerfile + tool change ship together in one releasable (`feat`) commit series; rollback is the previous image tag.

## Open Questions

(none)
