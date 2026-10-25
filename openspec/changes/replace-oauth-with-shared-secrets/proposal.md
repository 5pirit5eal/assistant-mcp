# Proposal: Replace OAuth 2.1 with Firestore-backed shared-secret authentication

## Why

The OAuth 2.1 layer (Google identity provider, PKCE, dynamic client
registration, refresh-grace replay machinery) is heavy operational surface for
what is in practice a small, personally known set of users: three Secret
Manager secrets, a consent screen, an email allowlist, and a series of
workarounds for upstream refresh-token rotation races (the remaining deferred
race in AGENTS.md). A shared-secret bearer model — as proven in the sibling
project `math-mcp-learning-server` — provides the same guarantee (only known
callers get access) with a fraction of the moving parts; storing one secret
hash per user in Firestore adds per-user registration and revocation that a
single shared env secret cannot offer, without reintroducing Secret Manager.

## What Changes

- **BREAKING**: The OAuth 2.1 layer is removed entirely. The Google provider,
  PKCE authorization-code flow, dynamic client registration, OAuth 2.1
  metadata endpoints, refresh-token rotation with its grace-replay machinery,
  the email allowlist, and the Fernet-encrypted OAuth state storage are all
  deleted. Existing callers authenticated via Google OAuth stop working; each
  registered user must configure a bearer secret in their client once.
- HTTP requests authenticate with a per-user shared secret in the
  `Authorization: Bearer <secret>` header. The verifier hashes the presented
  token, looks the hash up in a Firestore collection (one keyed read, served
  from a short in-process cache), and maps a hit to the registered user id.
- Secrets are stored **hash-only** (SHA-256) in Firestore; the database never
  holds usable credential material. Losing a secret means re-issuing it, not
  recovering it.
- An **admin CLI script** registers users: it generates a random secret,
  writes the Firestore record (user id, display label, secret hash,
  created-at), and prints the secret exactly once. Revocation is deleting the
  record; the cache TTL bounds how long a revoked secret keeps working.
- The authenticated caller's user id is carried into the request context, so
  tools may key user-specific data later.
- Authentication activates via a single environment flag (present → auth on,
  absent → unauthenticated), preserving the existing activation contract and
  fail-fast `AuthConfigError` style; stdio transport remains unauthenticated.
- Deployment drops the three Secret Manager secrets (`google-client-id`,
  `google-client-secret`, `mcp-oauth-storage-key`) and the `MCP_ALLOWED_EMAILS`
  repository variable; it gains the auth activation flag.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `service-auth`: All eight requirements are replaced. The capability keeps its
  purpose (who may use the HTTP service and how callers prove identity) but
  switches from OAuth 2.1 with Google to per-user shared secrets verified
  against Firestore, and adds the user-registration lifecycle (issue via admin
  CLI, revoke by deletion, hash-only storage) as new requirements.
- `cloud-run-deployment`: The deployment requirement changes: instead of
  injecting the OAuth configuration (client credentials and storage key from
  Secret Manager, base URL, and email allowlist), the deployment injects the
  shared-secret auth activation flag as a plain environment variable.

## Impact

- **Code**: `src/assistant_mcp/auth.py` (rewritten: OAuth provider, grace
  machinery, and encrypted storage replaced by the shared-secret verifier and
  Firestore user store), `src/assistant_mcp/server.py` (wiring unchanged in
  shape), new admin CLI script under `scripts/`.
- **Tests**: `tests/test_auth.py` and `tests/test_server_auth.py` largely
  rewritten for the new verifier; new tests for the admin CLI and the
  hash-only storage contract; existing identity-availability tests adapted to
  the user-id-based identity.
- **Dependencies**: `key_value` Firestore/cache/encryption wrappers remain in
  use for the keyed user lookup (FirestoreStore + passthrough cache);
  `fastmcp` Google provider imports and `cryptography` Fernet usage for OAuth
  state are removed.
- **Deployment**: `.github/workflows/deploy.yml` drops the `--set-secrets`
  line and the `MCP_ALLOWED_EMAILS` variable; the Cloud Run service gains the
  auth activation flag. After rollout, the three Secret Manager secrets and
  the `MCP_ALLOWED_EMAILS` GitHub variable become unused (manual cleanup by
  the user).
- **Documentation (affected surfaces)**: `README.md` (authentication section,
  environment variable table, setup instructions — OAuth consent screen and
  Secret Manager steps replaced by user registration instructions),
  `AGENTS.md` (the "Deliberately deferred (oauth refresh rotation)" section
  becomes moot and is removed; the deferred post-deploy checklist item is
  superseded by this change's own post-deploy check).
- **Manual post-merge checks performed by the user** (not tasks): after the
  release deploys, register each user via the admin CLI and confirm their
  client works with the bearer secret; delete the unused Secret Manager
  secrets and GitHub variable; confirm a redeploy does not require user
  re-registration (secrets live in Firestore, outside the deployment).
