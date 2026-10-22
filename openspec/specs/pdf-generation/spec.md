# pdf-generation Specification

## Purpose

The MCP server's ability to produce visually polished PDF documents from structured text (plain text, Markdown, or HTML) and return them as a public GCS resource URL (see the `gcs-document-delivery` capability).

## Requirements

### Requirement: PDF generation from text

The `generate_pdf` tool of the `pdf` toolset MUST generate a valid PDF document from a text input and return the public GCS resource URL of the uploaded PDF as structured content (not as base64 in text, not as embedded file bytes, and not as a file path).

#### Scenario: Plain-text input generates a PDF

- **WHEN** `generate_pdf` is called with plain text containing paragraphs (separated by blank lines)
- **THEN** the tool returns a public resource URL whose fetched content is a valid PDF that begins with `%PDF-`

#### Scenario: Markdown input is fully rendered

- **WHEN** `generate_pdf` is called with Markdown containing headings (`#` through `###`), paragraphs, bullet lists, tables, code blocks, links, and `**bold**`/`*italic*` markup
- **THEN** the generated PDF renders all of these elements as correspondingly formatted document elements (heading hierarchy, tables with cells, code in monospace, bold/italic text)

#### Scenario: German umlauts and special characters

- **WHEN** `generate_pdf` is called with text containing German umlauts (ä, ö, ü, ß) and common special characters
- **THEN** the generated PDF contains these characters correctly (no replacement or broken-glyph rendering)

#### Scenario: Caret superscripts render raised

- **WHEN** `generate_pdf` is called with text containing caret markers as used in math notation (`x^2`, `x^{n+1}`)
- **THEN** the caret and any bracing do not appear in the output and the marked content renders as superscript (raised and in smaller glyphs than the surrounding body text)

#### Scenario: Non-superscript carets stay literal

- **WHEN** `generate_pdf` is called with text where a caret is followed by anything other than ASCII letters/digits or a braced group (punctuation, empty braces, nested or unclosed braces, non-ASCII characters), or where the caret appears inside a code span or code block
- **THEN** the caret and the following content render as literal text without superscript formatting

#### Scenario: Empty input

- **WHEN** `generate_pdf` is called with empty text input
- **THEN** the tool returns a meaningful error instead of producing an empty or invalid PDF

### Requirement: Consistent document layout

The `generate_pdf` tool MUST produce a consistent, polished document layout: A4 page format, reasonable page margins, consistent styles for headings, body text, lists, tables, and code blocks, including multi-page flow for long content.

#### Scenario: Consistent styles

- **WHEN** `generate_pdf` is called with mixed Markdown (heading, text, list, table, code block)
- **THEN** the styles of the elements are recognizably distinct (heading size/weight, monospace for code, visually separated tables)

#### Scenario: Multi-page document

- **WHEN** `generate_pdf` is called with text that clearly exceeds a single page
- **THEN** the generated PDF consists of multiple pages, without any content being lost

### Requirement: PDF generation from HTML

The `generate_pdf` tool of the `pdf` toolset MUST render HTML input (fragments or full documents with embedded CSS) into a valid PDF with print-CSS fidelity and deliver it through the public GCS resource URL output (see the `gcs-document-delivery` capability).

#### Scenario: HTML fragment generates a PDF

- **WHEN** `generate_pdf` is called with an HTML fragment containing block-level markup such as `<p>`, `<div>`, or `<h1>`-`<h6>`
- **THEN** the tool returns structured content with a single `url` field matching the public GCS URL template, whose uploaded object content is a valid PDF that begins with `%PDF-`

#### Scenario: Full HTML document with embedded CSS

- **WHEN** `generate_pdf` is called with a full HTML document containing a `<style>` element that sets colors, fonts, margins, or `@page` rules
- **THEN** the generated PDF reflects those styles (styled text colors/fonts, configured page geometry) instead of falling back to unstyled defaults

#### Scenario: German umlauts in HTML render correctly

- **WHEN** `generate_pdf` is called with HTML containing German umlauts and special characters (as text or HTML entities)
- **THEN** the generated PDF contains these characters correctly (no replacement or broken-glyph rendering)

#### Scenario: No external resource loading

- **WHEN** `generate_pdf` is called with HTML that references external resources by URL (images, stylesheets, fonts)
- **THEN** the renderer performs no network request; the referenced external resources do not appear in the PDF (data-URIs embedded in the input are allowed and render)

### Requirement: Input-type detection for generate_pdf

The `generate_pdf` tool MUST detect whether the input is HTML or Markdown/plain text using simple content checks, without requiring the caller to declare the type. HTML markup that appears before any Markdown-typical token routes the input to the HTML rendering path; otherwise the input is treated as Markdown/plain text. An optional `format` parameter (`"auto"` | `"markdown"` | `"html"`, default `"auto"`) lets the caller override detection explicitly.

#### Scenario: HTML input is detected automatically

- **WHEN** `generate_pdf` is called with HTML block markup or document markup (`<!DOCTYPE`, `<html`, `<head`, `<body`, `<style`, `<p>`, `<div>`, `<table>`, `<h1>`-`<h6>`) and without `format`, or with `format="auto"`
- **THEN** the input is rendered through the HTML rendering path with CSS applied

#### Scenario: Markdown input keeps the existing behavior

- **WHEN** `generate_pdf` is called with Markdown or plain text and without `format`, or with `format="auto"`
- **THEN** the input is rendered through the Markdown pipeline exactly as before this change

#### Scenario: Markdown with an embedded HTML snippet stays Markdown

- **WHEN** `generate_pdf` is called with Markdown whose leading content is Markdown (e.g. a `#` heading, list, or paragraphs) and that contains HTML snippets later in the text
- **THEN** the input is treated as Markdown and rendered through the Markdown pipeline

#### Scenario: Explicit format override

- **WHEN** `generate_pdf` is called with `format="html"` or `format="markdown"`
- **THEN** the input is rendered through the corresponding path regardless of what the automatic detection would have chosen

#### Scenario: Invalid format value

- **WHEN** `generate_pdf` is called with a `format` value other than `"auto"`, `"markdown"`, or `"html"`
- **THEN** the tool returns a meaningful error naming the supported values

#### Scenario: Empty input errors regardless of format

- **WHEN** `generate_pdf` is called with empty text input, regardless of `format`
- **THEN** the tool returns a meaningful error instead of producing an empty or invalid PDF
