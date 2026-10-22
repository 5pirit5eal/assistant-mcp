# Design: replace file outputs with public GCS resource URLs

## Context

- Reference implementation: `swim-gen/backend/internal/pdf/pdf.go`
  (`UploadPDF`): creates a `storage.Client` (Application Default Credentials),
  uploads via `bucket.Object(name).NewWriter(ctx)` with `ContentType` set,
  and returns a URL. swim-gen returns a 15-minute V4 signed URL from a private
  bucket; its `models.PlanToPDFResponse` is `{ "uri": <url> }`.
- FastMCP 4.1.0 (locked in `uv.lock`) was verified empirically:
  `fastmcp.utilities.types.File.to_resource_content` always embeds the bytes
  as a base64 `BlobResourceContents` block — there is no URL-only file
  result. `fastmcp.exceptions.ToolError` remains the error channel. A
  pydantic model returned by a tool is delivered as structured content, so a
  `GenerationResult(url=...)` model is the idiomatic URL-only output.
- Cloud Run deployment (`openspec/specs/cloud-run-deployment/spec.md`):
  the runtime service account is
  `assistant-mcp-runtime@rubenschulze-sandbox.iam.gserviceaccount.com`;
  deployment is workflow-driven via `deploy-cloudrun` with `env_vars` and
  `--set-secrets`.

## Goals / Non-Goals

Goals:

- Every file-producing tool returns a public resource URL instead of an
  embedded base64 file.
- Upload mechanics equivalent to swim-gen's `UploadPDF`.
- Complete removal of the base64 output path (`File` results) — no
  opt-out flag, no dead code left behind.
- Stateless toolsets preserved: storage client builders are `lru_cache`-
  wrapped per AGENTS.md; no cross-request state.

Non-Goals:

- Changing the base64 *input* of `convert_to_pdf` or data-URI image inputs.
- Signed URLs / authenticated browser downloads (bucket is public).
- Object lifecycle policies, retention, or deletion (see Open Questions).

## Decisions

### D1: Public object URL instead of signed URL

swim-gen signs 15-minute V4 URLs because its bucket objects are private and
user-scoped. assistant-mcp documents are caller-generated artifacts with no
confidentiality model today (they were previously handed to the caller in
full), and the requested design is a *public* bucket. Therefore the tool
returns the durable public object URL
`https://storage.googleapis.com/<bucket>/<object>` (constant
`GCS_PUBLIC_URL_TEMPLATE`), not a signed URL.

**Assumption (user decision pending, timed out during proposal):** the bucket
is intentionally public. If confidentiality is later required, swapping the
helper to `bucket.sign_url` (V4, GET, short expiry) is a contained change.

### D2: Output model

```python
class GenerationResult(BaseModel):
    url: str
```

Returned as structured MCP content, consistent with
`toolset-tool-interface`'s "structured tool outputs" requirement (pydantic
model instead of file result; the file-result branch for these tools is
retired). Named constants (`_URL_TEMPLATE`, env var names) live in the module
that owns them per openspec config rule.

### D3: Upload helper module

New `src/assistant_mcp/toolsets/storage.py`, a plain helper module (not a
toolset, not registered in `TOOLSETS`):

- `GCS_BUCKET_ENV = "GCS_BUCKET_NAME"` (constant, tests import it)
- `@lru_cache`-wrapped `get_storage_client()` (ADC — on Cloud Run this uses
  the runtime service account; mirrors swim-gen's `storage.NewClient(ctx)`)
- `upload_document(data: bytes, name: str, content_type: str) -> str`:
  uploads with a 10 s deadline (matching swim-gen's timeout), sets
  `ContentType`, and returns the public object URL
- Missing/empty bucket config and upload failures raise `ToolError` with a
  meaningful message; no partial temp files persist.

### D4: Object naming

`uuid4()`-based object names per call (equivalent to swim-gen's
`GenerateFilename()` anonymous path): `<toolset>/<uuid>.<ext>` (e.g.
`pdf/<uuid>.pdf`, `docx/<uuid>.docx`). Deterministic user/plan-derived hashes
from swim-gen do not apply — assistant-mcp has no user/plan identity, and
per-call UUIDs avoid cross-request state and collisions.

### D5: Activation contract (value → delivery)

| Value | Delivery |
|---|---|
| `GCS_BUCKET_NAME` | plain env var on Cloud Run, added to `env_vars` in `.github/workflows/deploy.yml` (not a secret — it is not sensitive and appears in public URLs) |
| Bucket exists, public (uniform, `allUsers: objectViewer`), region `europe-west1` | one-time manual GCP setup documented in README (the deploy workflow itself needs no new permissions; the *runtime* service account needs `roles/storage.objectCreator` on the bucket) |

Config/workflow files are exempt from TDD per openspec config rules; the
workflow edit is validated by review/actionlint.

### D6: Dead-code cleanup (complete base64 output removal)

- `fastmcp.utilities.types.File` imports and all `File(...)` returns in
  `pdf.py` and `docx.py` are deleted.
- `binascii` import in `pdf.py` stays (it guards the base64 *input* of
  `convert_to_pdf`, which remains).
- Spec scenarios that assert "PDF bytes as a structured MCP content
  response" are reworked in the change's spec deltas to assert URL output;
  the main specs are updated at sync time.
- `tests/test_toolsets.py` output-structure checks updated: file-producing
  tools must now return a pydantic model, not `File`.
- README tool docs updated (impact enumerated in proposal.md).

## Risks / Trade-offs

- **Public bucket exposure:** generated documents are world-readable to
  anyone holding the URL (unguessable UUID path). Accepted per the design
  request; revisit via signed URLs if confidentiality becomes a requirement.
- **New runtime dependency** `google-cloud-storage` — already adjacent to the
  pinned `google-cloud-firestore`; version constraints recorded in
  `pyproject.toml` and locked.
- **Tests cannot hit real GCS** in CI. Per AGENTS.md ("verify protocol and
  path conventions against the real service — or a recorded real response"),
  the mocked client in tests mirrors the recorded response shape of
  `UploadPDF` in swim-gen (upload → object URL), and the upload helper is
  kept behind a client builder so tests can substitute it. A live smoke test
  against the real bucket is a rollout step before checking off the task.
- **Tool output is now a URL**, so callers must be able to fetch it
  (internet-reachable clients). Consistent with the public-bucket decision.

## Migration Plan

Single breaking change to three tool outputs, shipped behind a semantic
release; no dual-mode period (dual output is explicitly rejected — the
base64 path is removed, not deprecated). Cloud Run deploy runs on release
together with the new env var.

## Open Questions

- **Bucket lifecycle policy:** generated objects accumulate indefinitely.
  Propose a bucket-level age-based lifecycle rule (ops concern, outside this
  repo); not blocking the change.
- Confirm whether the user wants signed URLs instead of public URLs once the
  earlier clarification (timed out) is answered; the assumption is recorded in
  D1 and the swap is contained to `upload_document`.
