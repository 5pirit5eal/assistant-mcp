# gcs-document-delivery Specification (delta)

## ADDED Requirements

### Requirement: Public GCS resource URL output

The file-producing tools of the server - `generate_pdf`, `convert_to_pdf`
(pdf toolset), and `convert_to_docx` (docx toolset) - MUST upload the
generated document to a public Google Cloud Storage bucket and return a
structured MCP content response containing the public resource URL of the
uploaded object. The tools MUST NOT return the document bytes (base64
file result or base64 text) to the caller; the resource URL is the only
output option.

#### Scenario: generate_pdf returns a resource URL

- **WHEN** `generate_pdf` is called with Markdown or plain text
- **THEN** the tool returns structured content with a single `url` field
  pointing to the uploaded object, matching the public GCS URL template
  `https://storage.googleapis.com/<bucket>/<object>` with a `.pdf` object

#### Scenario: convert_to_pdf returns a resource URL

- **WHEN** `convert_to_pdf` is called with the base64 encoding of a valid
  DOCX, XLSX, or PPTX file
- **THEN** the tool returns structured content with a single `url` field
  pointing to the uploaded converted PDF

#### Scenario: convert_to_docx returns a resource URL

- **WHEN** `convert_to_docx` is called with Markdown or HTML content
- **THEN** the tool returns structured content with a single `url` field
  pointing to the uploaded object with a `.docx` object

#### Scenario: Returned URL content matches the generated document

- **WHEN** the URL returned by any of the three tools is fetched
- **THEN** the response body is the generated document, served with the
  correct content type (`application/pdf` or
  `application/vnd.openxmlformats-officedocument.wordprocessingml.document`)

### Requirement: Upload behavior and object naming

The upload MUST use the storage client built from Application Default
Credentials, MUST set the object's content type to the document's MIME
type, and MUST name objects uniquely per call under a toolset-derived
prefix, so no call overwrites another call's object and no cross-request
state is held by the toolsets.

#### Scenario: Objects are unique per call

- **WHEN** `generate_pdf` is called twice with identical input
- **THEN** the two returned URLs reference two distinct object paths

#### Scenario: Content type is set on upload

- **WHEN** `generate_pdf` uploads a document
- **THEN** the stored object carries the content type `application/pdf`

### Requirement: Storage configuration and failure handling

The upload target MUST be configurable via a single environment variable
(`GCS_BUCKET_NAME`) owned as a named constant by the storage helper module.
If the variable is missing or empty, or the upload fails, the tool MUST
return a meaningful error and MUST NOT crash the server.

#### Scenario: Missing bucket configuration

- **WHEN** any file-producing tool is called without `GCS_BUCKET_NAME` set
- **THEN** the tool returns an error stating that the storage bucket is not
  configured

#### Scenario: Upload failure surfaces as a tool error

- **WHEN** the storage backend rejects the upload
- **THEN** the tool returns an error naming the failed upload, and the
  server keeps serving subsequent requests

### Requirement: Removal of embedded file results

The `pdf` and `docx` toolsets MUST NOT produce embedded base64 file results
(`File` content) for their outputs, and no unused file-result code paths
shall remain in the toolset modules.

#### Scenario: No file result is returned

- **WHEN** a client calls `generate_pdf`, `convert_to_pdf`, or
  `convert_to_docx` and inspects the tool result content blocks
- **THEN** no embedded resource/blob content block carrying the document
  bytes is present; the result is the structured URL response

## MODIFIED Requirements

### Requirement: `MODIFIED: Binary outputs returned as file results`

The `toolset-tool-interface` requirement "Structured tool outputs" is
modified for this change: binary-producing tools return the public GCS
resource URL as a pydantic model (`url` field) instead of a file result.
The requirement that tools MUST NOT return a plain unstructured string
remains unchanged.

#### Scenario: URL outputs returned as structured content

- **WHEN** a client calls a tool that produces binary content, such as
  `generate_pdf`
- **THEN** the response contains structured content with a `url` field, and
  no embedded binary file result

## Notes

- The base64 *input* of `convert_to_pdf` and base64 data-URI image inputs of
  `convert_to_docx` are out of scope of this change and remain as specified
  in `pdf-file-conversion` and `docx-generation`.
- The `pdf-generation` purpose ("return them as a structured MCP content
  response" for bytes) is superseded by the URL output for the delivery part;
  rendering requirements are untouched. Main specs are updated at sync time.
