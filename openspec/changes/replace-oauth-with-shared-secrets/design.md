# Design: Replace OAuth 2.1 with Firestore-backed shared-secret authentication

## Context

`src/assistant_mcp/auth.py` currently implements OAuth 2.1: a Google
`GoogleProvider` subclass with an email allowlist, Fernet-encrypted Firestore
persistence (via the locked `py-key-value-aio` 0.4.6 FirestoreStore +
PassthroughCacheWrapper + FernetEncryptionWrapper), and refresh-grace replay
machinery. `server.py` wires it through `build_server(auth=...)`; `tests/test_auth.py`
and `tests/test_server_auth.py` cover the factory contract, the storage
layers, and the HTTP surface via `fastmcp.Client(..., auth=<token>)`.
Deployment injects three Secret Manager secrets plus `MCP_BASE_URL` and
`MCP_ALLOWED_EMAILS` repository variables (see proposal for motivation).

The sibling project `math-mcp-learning-server` proves the target shape: a
`fastmcp.server.auth.TokenVerifier` subclass whose `verify_token` compares the
presented bearer token and returns a pseudo `AccessToken`. This repo locks
fastmcp 4.1.1 (sibling: 4.1.3); `TokenVerifier` is already imported and
subclassed in this repo's code and tests, so the verifier pattern is verified
against the locked version. The `key_value` stores/wrappers the design reuses
are already exercised in production by the current auth layer against the
locked version.

## Goals / Non-Goals

**Goals:**

- Bearer authentication for the HTTP transport where each registered user has
  an individual secret, verified against hash-only records in Firestore.
- Reuse the existing storage stack (FirestoreStore, PassthroughCacheWrapper,
  MemoryStore, PydanticAdapter) so no new dependency is introduced.
- Preserve the activation contract shape (absent config -> unauthenticated;
  invalid config -> fail-fast `AuthConfigError`) and the stateless service
  model.
- An offline admin command that registers users and prints each secret
  exactly once.

**Non-Goals:**

- Per-device secrets, enabled flags, secret expiry, or rotation (delete and
  re-register instead).
- A revoke subcommand in the admin CLI; revocation is deleting the Firestore
  document (the collection is small and inspectable in the console).
- Rate limiting or brute-force protection: secrets carry 256-bit entropy,
  making guessing infeasible; Cloud Run already fronts the service.
- Recovering a lost secret: re-register the user, which replaces the record.

## Decisions

### Verifier shape and comparison

`SharedSecretTokenVerifier(TokenVerifier)` with `async verify_token(token)`:
hash the presented token with SHA-256, look that hash up as a document key,
and on a hit return `AccessToken(token=..., client_id=<user_id>,
claims={"user_id": <user_id>, "label": <label>})`. There is no secret-material
comparison anywhere — the presented value is transformed before any lookup,
so the constant-time-compare concern from the single-env-secret design does
not apply. Alternative rejected: comparing against secrets loaded into memory
(eager load, revocation lag, startup coupling to Firestore).

### Storage model

Collection `mcp-users` (constant in `auth.py`) in Firestore's `(default)`
database, resolved via Application Default Credentials — the same backend the
current OAuth layer uses. Document id = hex SHA-256 of the secret. Document
fields: `user_id`, `label`, `created_at`. Access through
`PydanticAdapter[UserRecord]` over `FirestoreStore` wrapped in
`PassthroughCacheWrapper(MemoryStore)` with a 60-second TTL constant
(`AUTH_CACHE_TTL_SECONDS`, overridable only via the test seam). A miss is an
unauthenticated request, same as today's `None` verifier result.

SHA-256 without a salt is sufficient here: the secrets are random
`secrets.token_urlsafe(32)` values with 256-bit entropy, so rainbow tables
and dictionary attacks do not apply. bcrypt/argon2 would add a dependency and
CPU cost for no security gain on high-entropy inputs.

Re-registration must find the previous hash document to delete it, and the
keyed-only stores offer no enumeration. A small index document keyed by
user id (collection `mcp-user-index`, model `UserIndexEntry` with the
current `secret_hash`) provides that lookup; the registration command is
its only writer and the verification path never reads it.

### Activation contract

A single environment variable `MCP_SHARED_SECRET_AUTH` (named constant in
`auth.py`, alongside the existing env-var style): absent/blank ->
`create_token_verifier()` returns `None` (unauthenticated, stdio unaffected);
`"true"` (case-insensitive) -> the Firestore-backed verifier; any other value
-> `AuthConfigError` naming the variable. This mirrors the current
all-or-nothing contract with one knob instead of five. The Firestore backend
and collection are not configurable via environment: they follow the
service's existing Firestore conventions, and tests inject the backend
directly.

### Admin registration command

`scripts/register_user.py`, run via
`uv run python scripts/register_user.py --user-id <id> [--label <text>]` with
ADC on the operator's machine. It generates the secret, writes the record
through the same record model, and prints the secret exactly once with an
explicit warning that it cannot be displayed again. Re-registering an
existing user id overwrites the record (the previous hash document is deleted
and the new one written), which supersedes the old secret after cache expiry.
The script shares the record model and hashing with `auth.py` through the
package import; the backend is injectable for tests the same way.

### Configuration delivery (value -> source)

| Value | Delivery |
| --- | --- |
| `MCP_SHARED_SECRET_AUTH=true` | plain env var, literal in `deploy.yml` `env_vars` |
| `MCP_TRANSPORT=http` | plain env var, literal in `deploy.yml` (unchanged) |
| `MCP_STATELESS_HTTP=true` | plain env var, literal in `deploy.yml` (unchanged) |
| `GCS_BUCKET_NAME` | plain env var from repo variable (unchanged) |

Removed from delivery: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`MCP_OAUTH_STORAGE_KEY` (Secret Manager), `MCP_BASE_URL` and
`MCP_ALLOWED_EMAILS` (repository variables). The rollout delivers the
complete activation contract: the flag alone activates authentication.

### Test surface (public interfaces targeted)

- `assistant_mcp.auth.create_token_verifier(env, backend)` — unit level:
  activation contract (absent/true/invalid), verifier accept/reject against an
  injected `MemoryStore` backend, cache expiry behavior, identity claims.
- `build_server(auth=...)` over HTTP via `fastmcp.Client(url, auth=<token>)` —
  server level: unauthenticated request rejected, unknown secret rejected,
  registered secret lists and calls tools, `healthz` stays unauthenticated,
  stdio stays unauthenticated. Mirrors the existing `test_server_auth.py`
  fixtures; the OAuth-flow fixtures and tests are deleted.
- `scripts/register_user.py` `main()` with an injected backend — prints the
  secret exactly once, persists a hash-only record, re-registration replaces
  the record.
- Record-model level: the persisted document contains no recoverable secret
  material.

Not covered by tests: the real Firestore roundtrip (same stance as the
current OAuth layer — the backend is injected, the FirestoreStore adapter is
exercised only live), and the deploy workflow's literal env vars (validated
by review, per the project's config exemption from TDD).

## Risks / Trade-offs

- [Revocation takes effect up to 60 s late] -> accepted by spec (bounded
  delay); the TTL constant can be lowered at the cost of more Firestore reads.
- [Lost secret is unrecoverable] -> re-register the user; the old record is
  replaced, so a leaked-then-lost secret is also invalidated.
- [Auth flag missing in a deploy would run unauthenticated] -> the deploy
  workflow always injects it and the spec forbids secret-sourced values;
  CI-level protection is out of scope.
- [Rollback to a pre-change release needs the old OAuth secrets] -> delete the
  Secret Manager secrets and the `MCP_ALLOWED_EMAILS`/`MCP_BASE_URL` repo
  variables only after the cutover is confirmed working.
- [Existing Firestore OAuth collections linger] -> delete them during cutover;
  they are inert once no code reads them.

## Migration Plan

1. Implement and verify on the branch (tests, lint, mypy; CI runs in-image).
2. Ship as a releasable commit type so semantic-release triggers the Cloud Run
   deploy with the new flag.
3. Post-deploy (manual, by the user): register each user via the admin
   command, have each user switch their client config to the bearer secret,
   confirm tool calls succeed, then clean up — delete the Firestore OAuth
   collections, the three Secret Manager secrets, and the `MCP_BASE_URL` /
   `MCP_ALLOWED_EMAILS` repository variables.

## Open Questions

None — remaining details (exact README wording, secret string format in the
client docs) settle during implementation without changing the specs.
