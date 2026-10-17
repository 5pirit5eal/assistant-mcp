# Proposal

## Why

The assistant MCP currently cannot access the user's images stored on their
Hetzner Storage Share Nextcloud. Assistants need to list and retrieve those
images to view, reference, or reason about them, and access must be
user-specific: each authenticated caller must only reach their own Nextcloud
account, with credentials never exposed in tool parameters or logs.

## What Changes

- Add a new `nextcloud` toolset (`src/assistant_mcp/toolsets/nextcloud.py`)
  registered in `TOOLSETS`, following the existing toolset pattern.
- Add three tools:
  - `save_nextcloud_credentials(webdav_url, username, app_password)`:
    validates the credentials against the Nextcloud WebDAV endpoint and
    persists them only on success.
  - `list_files(path)`: lists image files in a path, including files in
    mounted shares/folders of the account.
  - `download_image(path)`: downloads an image file and returns it as a
    `File` result (original, unmodified).
- Store per-user Nextcloud credentials encrypted (Fernet) in Google Firestore
  `(default)` database, keyed by the authenticated Google identity (email
  claim from `get_access_token()`), reusing the encrypted-storage pattern
  from the OAuth layer.
- Support an explicit `user_id` parameter as the storage key when no
  authenticated identity is available (e.g. stdio transport without OAuth).
- Add `webdavclient3` as a direct dependency; WebDAV calls run in a thread
  because the library is synchronous.
- No changes to existing toolsets or the auth layer itself; the toolset only
  consumes the authenticated identity.

## Capabilities

### New Capabilities
- `nextcloud-images`: Per-user, credential-protected access to image files on
  a Nextcloud (Hetzner Storage Share) instance via WebDAV: user-specific
  encrypted credential storage keyed by the authenticated identity, validated
  credential setup, image listing including mounted shares, and image
  download as file results.

### Modified Capabilities

- `service-auth`: A new requirement extends the spec: the service SHALL make
  the authenticated identity available to tools so user-specific data can be
  keyed per caller. The existing requirements are unchanged.

## Impact

- **Code**: new `src/assistant_mcp/toolsets/nextcloud.py`; registration in
  `src/assistant_mcp/toolsets/__init__.py`; possibly a small shared helper
  for encrypted per-user storage derived from `auth.py`'s
  `build_client_storage`.
- **Dependencies**: `webdavclient3` added to `pyproject.toml` and `uv.lock`;
  Docker build must be re-verified per AGENTS.md.
- **Systems**: Google Firestore `(default)` database gains a new collection
  for encrypted Nextcloud credentials; no new environment variables required
  (existing `MCP_OAUTH_STORAGE_KEY` Fernet key is reused for encryption).
- **Documentation surfaces**: `README.md` (new toolset section, credential
  setup guide, Hetzner Storage Share app-password instructions), `AGENTS.md`
  (remove the "in-tool use of the authenticated identity" deferred note once
  implemented).
- **Tests**: new toolset tests via `fastmcp.Client` with a mocked WebDAV
  client; existing `tests/test_toolsets.py` conventions apply to the new
  toolset.
