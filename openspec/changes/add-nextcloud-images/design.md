# Design

## Context

The server assembles toolsets via `TOOLSETS` (`src/assistant_mcp/toolsets/`)
and mounts them on a FastMCP instance (`server.py`). The OAuth layer
(`auth.py`) already persists encrypted state in Google Firestore's
`(default)` database using `FernetEncryptionWrapper` over
`FirestoreStore` + `MemoryStore` cache (`build_client_storage()`). The
authenticated identity is available in-tool through FastMCP 4.1's
`get_access_token()` dependency (`fastmcp.server.dependencies`), whose
claims carry the Google email; consuming it in a tool is the previously
deferred follow-up noted in AGENTS.md. Hetzner Storage Shares expose
standard Nextcloud WebDAV; per-user auth uses an app password (not OAuth).

## Goals / Non-Goals

**Goals:**
- User-specific credential storage, encrypted, keyed by authenticated
  identity with an environment-variable fallback
- Live-validated credential setup, image listing (incl. mounted shares),
  image download as file result
- Toolset follows the repo's tool-interface contract (annotated flat
  params, structured outputs, no plain-string returns)

**Non-Goals:**
- Upload/write access to Nextcloud
- Thumbnail generation or server-side image processing
- Nextcloud OAuth or sharing management; app passwords only
- Changes to the OAuth flow itself (identity is consumed, not extended)

## Decisions

### 1. New `nextcloud` toolset, pdf-pattern structure
`src/assistant_mcp/toolsets/nextcloud.py` with `mcp = FastMCP("nextcloud")`,
registered in `TOOLSETS`. Matches the modular registry pattern and keeps
`tests/test_toolsets.py` conventions applicable.
Alternative considered: extending the pdf toolset — rejected, it would
broaden that toolset's scope against the repo's modularity.

### 2. Reuse the OAuth encrypted-storage pattern for credentials
Persist credentials through the same stack as `build_client_storage()`:
`FernetEncryptionWrapper` over `PassthroughCacheWrapper(FirestoreStore,
MemoryStore)`, reusing the existing `MCP_OAUTH_STORAGE_KEY` Fernet key. A
separate Firestore collection (constant, e.g. `nextcloud_credentials`)
isolates them from OAuth state.
Alternative considered: a second Fernet key env var — rejected, no
additional security benefit for this data class and it complicates the
activation contract.

### 3. Credential resolution order: token claim, then env-var fallback
Tools resolve credentials as: if an authenticated identity exists, load the
credentials stored under the `get_access_token()` email claim (lowercased);
otherwise use the single-account credentials from environment variables
(constants: WebDAV URL, username, app password). Tools expose no parameter
that selects or overrides the storage key — any per-call identity parameter
would allow cross-user credential access and is deliberately excluded.
Environment credentials are ignored when the caller is authenticated.
Alternative considered: explicit `user_id` parameter as storage key —
rejected by the user because it enables cross-user access.

### 3a. Single-account fallback via environment variables
For stdio (no OAuth identity), three env vars supply one account's
credentials: URL, username, app password. Partial configuration is a
startup/config error naming the missing variables (mirroring the
`create_auth_provider` all-or-nothing pattern).

### 4. `webdavclient3` as the WebDAV client
User-confirmed choice. New direct dependency; its synchronous,
requests-based API means every WebDAV call is wrapped in
`asyncio.to_thread` so the event loop of the stateless HTTP server is never
blocked. Client instances are constructed per call (username/password from
storage); no pooling needed at expected volume.
Alternative considered: raw `httpx` PROPFIND/GET — cheaper dependency-wise,
but the user preferred the library's convenience (list, check, download
primitives).

### 5. Validation before persistence
`save_nextcloud_credentials` performs a cheap authenticated WebDAV
operation (listing the root, `Depth: 0`) before writing to Firestore;
401/403 → validation error, nothing persisted. Prevents garbage entries and
gives immediate feedback.

### 6. Tool surface
- `save_nextcloud_credentials(webdav_url, username, app_password)`
  → pydantic model (status); only usable with an authenticated identity
  (env-var fallback needs no saving)
- `list_files(path)` → pydantic model (list of entries: name, path,
  is_folder, content_type, size)
- `download_image(path)` → `File` result (original bytes, image media type)
Image format filtering via a module-level constant tuple (repo rule:
cross-module strings as named constants). All parameters annotated with
`Annotated[...]` + `Field` with description and example per
`toolset-tool-interface`.

## Risks / Trade-offs

- [webdavclient3 is sync] → every call wrapped in `asyncio.to_thread`;
  documented in the module, covered by tests using mocked client
- [Thread-offload adds latency per call] → acceptable for interactive
  assistant usage; client construction is cheap
- [Fernet key shared with OAuth state] → same trust boundary (both are
  per-user secrets in the same Firestore DB); rotation re-validates by
  decryption failure like OAuth state does
- [Identity in claims depends on Google `email` scope] → already required
  by `create_auth_provider` (`openid`, `email`)
- [Hetzner WebDAV quirks (redirects, URL encoding of spaces/umlauts in
  paths)] → webdavclient3 normalizes paths; error mapping treats 404 as
  not-found ToolError, 401/403 as credential failure
- [Env-var fallback bypasses per-user isolation by design] → only for the
  explicitly single-account stdio deployment; no parameter path can combine
  an authenticated identity with foreign stored credentials

## Migration Plan

1. Add `webdavclient3` dependency (`uv add`), rebuild lockfile
2. Implement toolset + storage helper test-first (TDD per config rules)
3. Verify `docker build` succeeds (AGENTS.md rule) and run the full suite
4. Deploy: no new env vars; Firestore collection is created on first write
5. Rollback: revert the release; stored credentials are inert without the
   toolset and can be deleted from the collection

## Open Questions

- Exact Firestore collection/document layout (collection name constant)
  is decided during implementation; no spec impact.
