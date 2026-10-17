# Tasks

## 1. Dependency setup (not parallelizable with test-running tasks: mutates uv.lock/.venv)
- [ ] 1.1 Add `webdavclient3` as a direct dependency via `uv add webdavclient3` and verify `uv run python -c "import webdav3.client"` succeeds
- [ ] 1.2 Verify `uv run pytest`, `uv run ruff check .`, and `uv run mypy src` still pass on the unchanged codebase
- [ ] 1.3 Verify `docker build` succeeds with the new lockfile

## 2. Encrypted credential storage (parallelizable within the group after 1.x)
- [ ] 2.1 Write failing tests for a credential storage helper that stores/loads Nextcloud credentials encrypted under an identity key (use an in-memory backend), including the "no credentials stored" and "other user's credentials not readable" cases; verify the tests fail for the expected reason
- [ ] 2.2 Implement the credential storage helper (Fernet-wrapped Firestore-compatible store, separate collection constant, reusing the `build_client_storage` pattern) and verify the tests from 2.1 pass

## 3. Identity resolution
- [ ] 3.1 Write failing tests for the identity resolution order (token email claim wins, then explicit `user_id`, else ToolError) via the public tool interface with a mocked auth context; verify they fail for the expected reason
- [ ] 3.2 Implement identity resolution in the nextcloud toolset module and verify the tests from 3.1 pass

## 4. Credential setup tool
- [ ] 4.1 Write failing tests through `fastmcp.Client` for `save_nextcloud_credentials`: valid credentials (mocked WebDAV accepts) are stored and reported; invalid credentials (mocked 401) are not stored and reported as failure; verify they fail for the expected reason
- [ ] 4.2 Implement `save_nextcloud_credentials` (validation listing before persistence, pydantic model output, annotated parameters with examples) and verify the tests from 4.1 pass

## 5. Listing and download tools
- [ ] 5.1 Write failing tests through `fastmcp.Client` for `list_files`: lists image files and folders with name/path/is_folder, includes mounted-share files, 404 path yields a clear error, no stored credentials yields a clear error; verify they fail for the expected reason
- [ ] 5.2 Write failing tests through `fastmcp.Client` for `download_image`: returns the original bytes as a file result with the image media type and file name, 404 yields a clear error; verify they fail for the expected reason
- [ ] 5.3 Implement `list_files` and `download_image` (WebDAV calls via `asyncio.to_thread`, image-format constant, annotated parameters, structured/file outputs) and verify the tests from 5.1 and 5.2 pass

## 6. Toolset registration and integration
- [ ] 6.1 Register the nextcloud toolset in `TOOLSETS` and verify `tests/test_toolsets.py` passes for the new toolset (annotated inputs, structured outputs, no bootstrap regressions)
- [ ] 6.2 Verify the full suite (`uv run pytest`), `uv run ruff check .`, and `uv run mypy src` pass with the new toolset mounted

## 7. Documentation
- [ ] 7.1 Document the nextcloud toolset in `README.md` (tools overview, credential setup flow with Hetzner Storage Share app-password instructions, identity/user_id behavior) and verify documented steps match the implemented tools
- [ ] 7.2 Update `AGENTS.md`: remove the "in-tool use of the authenticated identity" deferred note for the parts this change delivers and verify the statement matches the implementation

## Workflow follow-up
- Run the apply-phase gap-analysis review and present findings for approval.
- Archive the change after the review is approved.
