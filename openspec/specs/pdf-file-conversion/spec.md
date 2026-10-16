# pdf-file-conversion Specification

## Purpose

The MCP server's ability to convert Microsoft Office files (DOCX, XLSX, PPTX) to PDF via base64 input and return them as a structured MCP content response - suitable for remote operation without a shared filesystem.

## Requirements

### Requirement: Conversion of Office formats to PDF

The `convert_to_pdf` tool of the `pdf` toolset MUST convert a file passed as base64 in the DOCX, XLSX, and PPTX formats into a PDF and return the PDF bytes as a structured MCP content response.

#### Scenario: DOCX is converted

- **WHEN** `convert_to_pdf` is called with the base64 encoding of a valid DOCX file
- **THEN** the tool returns valid PDF bytes as a structured MCP content response that begins with `%PDF-`

#### Scenario: XLSX is converted

- **WHEN** `convert_to_pdf` is called with the base64 encoding of a valid XLSX file
- **THEN** the tool returns valid PDF bytes as a structured MCP content response

#### Scenario: PPTX is converted

- **WHEN** `convert_to_pdf` is called with the base64 encoding of a valid PPTX file
- **THEN** the tool returns valid PDF bytes as a structured MCP content response

### Requirement: Error handling for invalid input

The `convert_to_pdf` tool MUST respond to invalid inputs with meaningful errors, without crashing the server.

#### Scenario: Unsupported format

- **WHEN** `convert_to_pdf` is called with a file whose format is not DOCX, XLSX, or PPTX
- **THEN** the tool returns an error that names the unsupported format

#### Scenario: Invalid base64 input

- **WHEN** `convert_to_pdf` is called with a string that is not a valid base64 encoding
- **THEN** the tool returns an error that names the invalid encoding

#### Scenario: Corrupt file

- **WHEN** `convert_to_pdf` is called with a valid base64 encoding of a damaged DOCX/XLSX/PPTX file
- **THEN** the tool returns an error, without the server crashing

### Requirement: Temporary file handling

`convert_to_pdf` MUST process the input file only temporarily and leave no files permanently behind on the server after the conversion.

#### Scenario: No file residue

- **WHEN** `convert_to_pdf` has completed successfully
- **THEN** no temporary input or output file of the call exists any longer in the server's working directory
