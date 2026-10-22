## Proposal

### Change

Replace the embedded binary file output (FastMCP `File`, which the client
receives as a base64 blob inside the tool result) of all file-producing tools
with resource URLs into a public Google Cloud Storage bucket. Discard the
base64 output option completely and remove the resulting dead code.

Affected tools:

- `generate_pdf` (pdf toolset)
- `convert_to_pdf` (pdf toolset)
- `convert_to_docx` (docx toolset)

Each tool generates its document exactly as before, then uploads the bytes to
GCS and returns a structured result containing the public resource URL of the
uploaded object. The upload mechanics mirror the proven Go implementation in
`swim-gen/backend` (`internal/pdf/pdf.go`, `UploadPDF`): a storage client from
Application Default Credentials, a content-typed object writer, and a
deterministic object path. Instead of the 15-minute V4 signed URL used there,
the tool returns the durable public object URL
(`https://storage.googleapis.com/<bucket>/<object>`) because this bucket is
intentionally public (assumption recorded in design.md).

### Motivation

- MCP tool results that embed the document as a base64 blob waste tokens and
  payload on every call and are limited by the transport response size
  (~32 MB on Cloud Run); a short resource URL is cheap and unbounded by
  document size.
- swim-gen already stores generated PDFs in GCS and returns a URI; aligning
  assistant-mcp on the same delivery model keeps the services consistent.
- With URLs as the only output path, the `File` result branch becomes dead
  code and must be removed rather than kept behind a flag.

### Impact

Affected code:

- `src/assistant_mcp/toolsets/pdf.py` — `generate_pdf`, `convert_to_pdf`
  return URLs instead of `File`
- `src/assistant_mcp/toolsets/docx.py` — `convert_to_docx` returns a URL
  instead of `File`
- new `src/assistant_mcp/toolsets/storage.py` (or equivalent) — shared GCS
  upload helper
- `tests/test_pdf_toolset.py`, `tests/test_docx_toolset.py`,
  `tests/test_toolsets.py` — tests driven via `fastmcp.Client` against the new
  URL outputs
- `pyproject.toml` / `uv.lock` — add `google-cloud-storage`
- `.github/workflows/deploy.yml` — deliver the bucket env var to Cloud Run

Affected documentation surfaces:

- `README.md` — tool descriptions that promise file downloads must describe
  the URL output instead
- `openspec/specs/pdf-generation/spec.md`,
  `openspec/specs/pdf-file-conversion/spec.md`,
  `openspec/specs/docx-generation/spec.md`,
  `openspec/specs/toolset-tool-interface/spec.md` — updated during sync when
  the change is applied

### What Does Not Change

- The base64 *input* of `convert_to_pdf` (Office document passed as base64 in
  the request) stays; only the base64 *output* is discarded.
- Base64 data-URI images inside DOCX input content remain supported input;
  this is unrelated to the output path.
- Document rendering, styling, Markdown/HTML conversion behavior, and error
  handling for invalid input are untouched.
