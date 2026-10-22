# Tasks: replace file outputs with public GCS resource URLs

## 1. Storage helper module

- [x] 1.1 Write failing tests for the storage helper: `GCS_BUCKET_NAME`
  constant is importable; `upload_document` returns the public URL
  `https://storage.googleapis.com/<bucket>/<object>` for given bytes and
  object name; missing/empty bucket env raises `ToolError`; upload failure
  (mocked client error, mirroring the recorded swim-gen `UploadPDF` response
  shape) raises `ToolError`. (parallelizable with 1.2 within batch 1)
- [x] 1.2 Write failing tests asserting per-call unique object names
  (toolset prefix + UUID extension pattern) and that the content type
  passed to the writer equals the document MIME type. (parallelizable with
  1.1 within batch 1)
- [x] 1.3 Implement `src/assistant_mcp/toolsets/storage.py`: named constants
  (`GCS_BUCKET_ENV`, public URL template), `lru_cache`-wrapped
  `get_storage_client()` on ADC, `upload_document(data, name, content_type)`
  with a 10 s upload deadline modeled on swim-gen `UploadPDF`; return the
  public object URL. (blocked by 1.1, 1.2)
- [x] 1.4 Add `google-cloud-storage` to `pyproject.toml` and refresh
  `uv.lock`. Not parallelizable with any task that runs tests or linters
  (shared environment).

## 2. Toolset changes (blocked by batch 1)

- [x] 2.1 Write failing tests: `generate_pdf` returns structured content
  with a single `url` field (public GCS URL template, `.pdf` object) and no
  embedded file/blob content block; upload errors surface as tool errors
  while the server keeps serving. (parallelizable with 2.2, 2.3 within
  batch 2)
- [x] 2.2 Write failing tests: `convert_to_pdf` returns the `url` field for
  DOCX/XLSX/PPTX inputs and no embedded file/blob content; existing input
  validation errors (invalid base64, unsupported format, corrupt file,
  empty content) are unchanged. (parallelizable with 2.1, 2.3)
- [x] 2.3 Write failing tests: `convert_to_docx` returns the `url` field
  (`.docx` object) and no embedded file/blob content; existing error
  scenarios unchanged. (parallelizable with 2.1, 2.2)
- [x] 2.4 Implement the output model (`GenerationResult` with `url: str`)
  and rewire `generate_pdf`, `convert_to_pdf`, `convert_to_docx` to upload
  via the storage helper and return the model. Blocked by 1.3, 2.1-2.3.
- [x] 2.5 Dead-code cleanup: remove all `File` usage and `File` imports from
  `pdf.py` and `docx.py`; remove now-unused constants (e.g.
  `_OUTPUT_FILENAME` where applicable); keep `binascii`/base64 *input*
  handling. Update `tests/test_toolsets.py` output-structure checks
  accordingly. Blocked by 2.4.

## 3. Configuration and rollout (blocked by batch 2)

- [x] 3.1 Deliver `GCS_BUCKET_NAME` from the repository variable
  `vars.GCS_BUCKET_NAME` via the Cloud Run `env_vars` in
  `.github/workflows/deploy.yml`, including a workflow check step for the
  missing variable mirroring the `MCP_ALLOWED_EMAILS` pattern (exempt from
  TDD; validated by review and actionlint). Run `uv run ruff check .`,
  `uv run mypy src`, `uv run pytest`.
- [x] 3.2 Create the public bucket (`europe-west1`, uniform access,
  `allUsers: objectViewer`, lifecycle rule deleting objects after 30 days)
  and grant
  `assistant-mcp-runtime@rubenschulze-sandbox.iam.gserviceaccount.com`
  `roles/storage.objectCreator` on it; document the one-time setup including
  the deletion policy in README.md. Exempt from TDD (ops + doc step).
- [x] 3.3 Update README.md tool documentation: outputs are public resource
  URLs from an ephemeral bucket (objects auto-deleted after one month), not
  file downloads; enumerate `GCS_BUCKET_NAME` as the activation env var.
  Exempt from TDD (doc step).
- [ ] 3.4 Live smoke test against the real bucket (per AGENTS.md real-
  service verification): call `generate_pdf` on a deployed/local instance
  with real credentials, fetch the returned URL, and verify the downloaded
  bytes are a valid PDF with content type `application/pdf`. Blocked by
  3.1, 3.2. Note: task 3.2 documents the one-time setup in README; the
  bucket/permissions themselves must be created in GCP and the smoke test
  run with real credentials — not possible from this development
  sandbox, so this task stays open for the operator.
