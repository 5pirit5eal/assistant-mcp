# pdf-generation Specification

## Purpose

The MCP server's ability to produce visually polished PDF documents from structured text (plain text or Markdown) and return them as a structured MCP content response.

## Requirements

### Requirement: PDF generation from text

The `generate_pdf` tool of the `pdf` toolset MUST generate a valid PDF document from a text input and return the PDF bytes as a structured MCP content response (not as base64 in text and not as a file path).

#### Scenario: Plain-text input generates a PDF

- **WHEN** `generate_pdf` is called with plain text containing paragraphs (separated by blank lines)
- **THEN** the tool returns valid PDF bytes as a structured MCP content response that begins with `%PDF-`

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
