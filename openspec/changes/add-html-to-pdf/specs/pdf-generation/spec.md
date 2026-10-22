# Spec Delta

## ADDED Requirements

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

#### Scenario: Empty input

- **WHEN** `generate_pdf` is called with empty text input, regardless of `format`
- **THEN** the tool returns a meaningful error instead of producing an empty or invalid PDF
