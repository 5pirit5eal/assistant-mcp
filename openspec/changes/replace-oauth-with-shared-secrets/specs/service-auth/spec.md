# service-auth Delta

## MODIFIED Requirements

### Requirement: Authenticated access to the HTTP service

When shared-secret authentication is activated, the system SHALL require a
valid shared secret registered for a user for every HTTP request to the
service, including tool listing and tool calls, presented in the
`Authorization: Bearer <secret>` header. Requests without a secret or with a
secret that does not match a registered, non-revoked user record MUST be
rejected. The stdio transport MUST NOT require authentication.

#### Scenario: Unauthenticated HTTP request is rejected

- **WHEN** a client sends an HTTP request to the service without a bearer token
- **THEN** the request is rejected and no toolset information or tool result is returned

#### Scenario: Invalid token is rejected

- **WHEN** a client sends an HTTP request with a bearer token that matches no registered user record
- **THEN** the request is rejected and no toolset information or tool result is returned

#### Scenario: Authenticated client can use tools

- **WHEN** a client presents the secret of a registered user and lists tools or calls a tool
- **THEN** the request is served as if the service were unauthenticated

#### Scenario: stdio transport stays local

- **WHEN** the service runs with the stdio transport
- **THEN** no authentication is required

### Requirement: Authentication activation through configuration

The system SHALL activate shared-secret authentication only when the
activation configuration value is present and set to `true`. With the value
absent, the service SHALL start and operate without authentication. With the
value present but set to anything other than a valid activation value, the
service MUST refuse to start with an error naming the configuration value.

#### Scenario: Unconfigured service runs without authentication

- **WHEN** the service starts without the activation configuration value in the environment
- **THEN** it starts successfully and serves requests without authentication

#### Scenario: Configured service enforces authentication

- **WHEN** the service starts with the activation configuration value set to `true`
- **THEN** it starts successfully and requires a valid registered secret for HTTP access

#### Scenario: Incomplete configuration fails fast

- **WHEN** the service starts with the activation configuration value set to a value other than `true` or absent
- **THEN** it fails at startup with an error naming the configuration value

### Requirement: Identity availability for tools

The system SHALL make the authenticated caller's identity available to tools
during a tool call when the HTTP transport is configured with
authentication; the identity SHALL be the registered user identifier of the
user whose secret the caller presented. Tools MAY use this identity to key
user-specific data. When no authentication is configured or the caller is not
authenticated, the system SHALL not fail tool execution solely because no
identity is available; tools decide how to handle the absent identity.

#### Scenario: Tool receives the authenticated identity

- **WHEN** a client with a valid registered secret calls a tool and the tool
  requests the caller's identity
- **THEN** the registered user identifier of the matching user record is
  available to the tool

#### Scenario: Tool runs without identity

- **WHEN** the service runs without authentication configured (for example
  the stdio transport) and a tool requests the caller's identity
- **THEN** no identity is returned and the tool call itself is not rejected
  for that reason

## ADDED Requirements

### Requirement: Per-user secret registration

The system SHALL provide an admin command that registers a user by a
user identifier with an optional display label: the command generates a
cryptographically random secret, persists a user record containing the user
identifier, the display label, a one-way hash of the secret, and the
registration time, and displays the plaintext secret exactly once in its
output. Registering a user identifier that already has a record SHALL replace
the previous record, so the previous secret stops being accepted once the
verification cache has expired.

#### Scenario: Registration issues a secret once

- **WHEN** the admin command registers a new user
- **THEN** it writes a user record and prints the generated secret exactly once, and the printed secret grants access to the service

#### Scenario: Re-registration invalidates the old secret

- **WHEN** the admin command registers a user identifier that already has a record
- **THEN** the previous record is replaced and the previously issued secret is no longer accepted once the verification cache has expired

#### Scenario: Display label is stored

- **WHEN** the admin command registers a user with a display label
- **THEN** the stored user record carries the label so the registration can be identified without exposing the secret

### Requirement: Hash-only secret storage

The system SHALL store only a one-way hash of each registered secret in the
user records. The plaintext secret MUST NOT be persisted in the user
records or any other storage. Verification of a presented secret SHALL
compare a one-way hash of the presented value against the stored hash.

#### Scenario: User record contains no plaintext secret

- **WHEN** a user is registered and the stored record is inspected
- **THEN** it contains a hash of the secret and no material from which the secret can be recovered

#### Scenario: Verification hashes the presented token

- **WHEN** a client presents a secret in the Authorization header
- **THEN** the service accepts or rejects it based on a comparison against the stored hash, not against a stored plaintext value

### Requirement: Revocation by record deletion

The system SHALL revoke a user's access when the user record is deleted. A
deleted user's secret MUST be rejected once the verification cache entry for
it has expired; the verification cache SHALL expire entries within a bounded,
short time-to-live, so a revoked secret stops working within that delay.

#### Scenario: Deleted user's access ends within the cache delay

- **WHEN** a user record is deleted and the verification cache entry for that secret has expired
- **THEN** the deleted user's secret is rejected on the next request

#### Scenario: Revocation latency is bounded

- **WHEN** a user record is deleted
- **THEN** the deleted user's secret is rejected no later than the verification cache's time-to-live after the deletion

## REMOVED Requirements

### Requirement: OAuth 2.1 authorization flow via Google

**Reason**: The OAuth 2.1 layer is replaced by per-user shared-secret bearer
authentication; there is no browser flow, no identity provider, and no
service-issued token.
**Migration**: Each user receives a secret from the admin registration
command and configures it as a static bearer token in their MCP client.

### Requirement: Account allowlist

**Reason**: Access control is expressed by the set of registered user
records in Firestore, not by an email allowlist evaluated against a
Google-authenticated identity.
**Migration**: Register each previously allowlisted user via the admin
registration command.

### Requirement: Persistent and encrypted OAuth state

**Reason**: No OAuth state (client registrations, token records) exists
anymore. The persisted auth data is the hash-only user records, which
require no encryption key because they contain no plaintext credential
material.
**Migration**: The Firestore collections holding OAuth client registrations,
token records, and refresh-grace entries can be deleted after the cutover.

### Requirement: Race-tolerant refresh token rotation

**Reason**: Shared secrets do not rotate and are not one-time-use; there are
no refresh tokens whose concurrent use needs to converge.
**Migration**: None.

### Requirement: Configurable service-issued access-token lifetime

**Reason**: The service no longer issues tokens; callers present their
registered secret directly.
**Migration**: None.
