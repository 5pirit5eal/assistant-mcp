# Tasks: Replace OAuth 2.1 with Firestore-backed shared-secret authentication

## 1. Shared-secret auth core

Sequential batch: all three tasks edit `src/assistant_mcp/auth.py` (shared
file), in dependency order. No dependency-environment changes are involved.

- [x] 1.1 Implement the activation contract test-first: write failing tests
  in `tests/test_auth.py` for `create_token_verifier` driven by the
  `MCP_SHARED_SECRET_AUTH` constant — absent/blank returns `None`
  (unauthenticated), `"true"` returns a verifier, any other value raises
  `AuthConfigError` naming the variable; then add the constant and the
  factory with the invalid-value fail-fast. Verify: the new tests pass and
  the constant is imported (not duplicated as a literal) in the tests.
- [x] 1.2 Implement the hash-only user record store test-first: write failing
  tests for the user-record model and its store builder (injected
  in-memory backend) covering: the record persists `user_id`, `label`,
  `created_at`; the document key is the SHA-256 of the secret; the stored
  record contains no material from which the secret can be recovered; then
  implement the pydantic record model and the store builder (Firestore
  backend default, in-process cache with the TTL constant, backend injectable
  for tests). Verify: the new tests pass.
- [x] 1.3 Implement the verifier test-first: write failing tests for
  `verify_token` covering: a registered secret is accepted and the returned
  access token carries the registered user identifier as its identity; an
  unknown secret and an empty token are rejected; a record deleted from the
  backend stops authorizing once the cache entry has expired (fault
  injection on the TTL is allowed; the assertion targets acceptance/rejection
  behavior); then implement the verifier on top of the record store and wire
  it into the factory from 1.1. Verify: the new tests pass.

## 2. Admin registration CLI

Blocked by 1.2 (consumes the record model and hashing). Parallelizable with
groups 3 and 5.

- [x] 2.1 Implement `scripts/register_user.py` test-first: write failing tests
  invoking the script's entry point with an injected backend covering: a new
  registration persists a hash-only record and prints the generated secret
  exactly once with a warning that it cannot be displayed again;
  re-registering an existing user id replaces the record so the previous
  secret stops authorizing after cache expiry; then implement the script
  (secret generation, record write, one-time output). Verify: the new tests
  pass and `uv run python scripts/register_user.py --help` prints usage.

## 3. Server and HTTP integration

Blocked by 1.3 (verifier wired into the server).

- [x] 3.1 Rewire `build_server` to the new factory and rewrite the HTTP-level
  tests in `tests/test_server_auth.py` test-first: failing tests against the
  real HTTP transport covering: an unauthenticated request is rejected; an
  unknown bearer secret is rejected; a registered secret can list tools and
  call a tool; `healthz` answers without authentication; the stdio
  transport serves without authentication; then update `server.py` and the
  fixtures, deleting the OAuth-flow fixtures and flow-specific tests (their
  requirements are removed by the delta). Verify: the rewritten suite
  passes and no OAuth-specific test remains.

## 4. OAuth removal

Blocked by 3.1 (integration must be green before deletion).

- [x] 4.1 Remove the OAuth implementation: delete the Google provider
  subclass, allowlist verifier, refresh-grace machinery, Fernet storage
  wrapper, and the obsolete environment-variable constants from
  `src/assistant_mcp/auth.py`, together with their unit tests in
  `tests/test_auth.py` (allowlist, grace, TTL, encrypted-state, base-URL
  validation). Verify: the full test suite, ruff, and mypy all pass with no
  references to the removed symbols anywhere in the repo.

## 5. Deployment and documentation

Parallelizable batch (three independent files), blocked by 1.1 for the
`MCP_SHARED_SECRET_AUTH` constant name. Exempt from TDD per project rules;
validated by review and the repo's automated linters.

- [x] 5.1 Update `.github/workflows/deploy.yml`: remove the
  `--set-secrets` line and the `MCP_BASE_URL`/`MCP_ALLOWED_EMAILS`
  env-var wiring, add `MCP_SHARED_SECRET_AUTH=true` to the plain env vars,
  and remove the now-obsolete base-URL preflight check. Verify: actionlint
  passes and the workflow's env vars match the activation contract table in
  design.md.
- [x] 5.2 Rewrite the README authentication surfaces: replace the OAuth
  setup (consent screen, OAuth client, Secret Manager steps,
  `MCP_ALLOWED_EMAILS`/`MCP_BASE_URL` docs) with the shared-secret flow —
  the activation flag table, user registration via the admin script, client
  configuration with the bearer secret, and revocation by record deletion.
  Verify: markdownlint passes and no OAuth/Secret Manager instructions
  remain in the setup path.
- [x] 5.3 Update `AGENTS.md`: remove the "Deliberately deferred (oauth
  refresh rotation)" section, whose residual race and post-deploy checklist
  item are both superseded by this change. Verify: markdownlint passes and
  the file no longer references OAuth deferrals.

## 6. Final verification

Blocked by all groups above.

- [x] 6.1 Run the complete verification suite (pytest, ruff, mypy,
  actionlint, markdownlint) and confirm it is green, then create a draft PR
  and let CI verify the branch. Verify: CI passes on the PR; work ends
  there — the post-deploy cutover steps in proposal.md are manual
  post-merge checks for the user, not tasks.
