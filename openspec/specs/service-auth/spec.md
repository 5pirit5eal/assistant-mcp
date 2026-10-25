# service-auth Specification

## Purpose

Defines who may use the HTTP-exposed assistant-mcp service and how callers prove
their identity: per-user shared secrets presented as bearer tokens and verified
against hash-only user records in Firestore, a registration lifecycle that
issues each user an individual secret and revokes by record deletion, and a
configuration contract that activates authentication only when explicitly
enabled.

## Requirements

### Requirement: Authenticated access to the HTTP service

When OAuth configuration is present, the system SHALL require a valid access
token issued by the service's OAuth layer for every HTTP request to the service,
including tool listing and tool calls. Requests without a token or with an
invalid or expired token MUST be rejected. The stdio transport MUST NOT require
authentication.

#### Scenario: Unauthenticated HTTP request is rejected

- **WHEN** a client sends an HTTP request to the service without an access token
- **THEN** the request is rejected and no toolset information or tool result is returned

#### Scenario: Invalid token is rejected

- **WHEN** a client sends an HTTP request with a malformed, invalid, or expired token
- **THEN** the request is rejected and no toolset information or tool result is returned

#### Scenario: Authenticated client can use tools

- **WHEN** a client presents a valid access token and lists tools or calls a tool
- **THEN** the request is served as if the service were unauthenticated

#### Scenario: stdio transport stays local

- **WHEN** the service runs with the stdio transport
- **THEN** no authentication is required

### Requirement: OAuth 2.1 authorization flow via Google

The system SHALL expose the OAuth 2.1 endpoints required by the Model Context
Protocol for protected resources: protected-resource metadata, authorization,
token, and dynamic client registration. The authorization flow SHALL use the
authorization-code grant with PKCE and SHALL delegate user authentication to
Google, returning tokens that grant access to the service. An interactive client
MUST be able to complete the flow with a browser login against a Google account.

#### Scenario: Client completes browser login

- **WHEN** an interactive MCP client connects, follows the advertised authorization flow, and the user signs in with a Google account
- **THEN** the client receives a token that is accepted by the service

#### Scenario: OAuth metadata is discoverable

- **WHEN** a client requests the service's OAuth 2.1 metadata endpoints
- **THEN** the service advertises the authorization, token, and registration endpoints it serves

### Requirement: Account allowlist

The system SHALL grant access only to Google accounts explicitly listed in the
allowlist configuration. The identity of the authenticated Google account MUST be
checked against the allowlist before access is granted. A user who authenticates
successfully with Google but whose account is not on the allowlist MUST NOT
receive a usable token for the service.

#### Scenario: Allowlisted account gets access

- **WHEN** a user completes the authorization flow with an allowlisted Google account
- **THEN** the issued token is accepted by the service

#### Scenario: Non-allowlisted account is denied

- **WHEN** a user completes the authorization flow with a Google account that is not on the allowlist
- **THEN** no usable token is issued for the service and access is denied

### Requirement: Persistent and encrypted OAuth state

The system SHALL persist the OAuth state (client registrations and token
records) in a storage backend that survives service restarts and cold starts,
using the configured storage encryption key. Persisted state MUST be encrypted
before it is written to the storage backend; plaintext token material MUST NOT
be written to the backend. A client that has completed authentication MUST NOT
be forced to re-authenticate because the service restarted.

#### Scenario: Login survives a restart

- **WHEN** a client has completed the authorization flow and the service restarts with access to the same storage and the same storage encryption key
- **THEN** the client's existing token remains accepted without a new login

#### Scenario: Persisted state is encrypted at rest

- **WHEN** OAuth state is written to the storage backend
- **THEN** the stored values are encrypted with the configured key and contain no plaintext token material

#### Scenario: State without the key is unusable

- **WHEN** persisted state is read without the storage encryption key
- **THEN** it cannot be decrypted and is treated as absent, forcing re-registration rather than exposing token material

### Requirement: Authentication activation through configuration

The system SHALL activate the OAuth layer only when its required configuration
values (client credentials, public base URL, account allowlist, and storage
encryption key) are present in the environment. With the configuration absent,
the service SHALL start and operate without authentication. With the
configuration present but incomplete, the service MUST refuse to start.

#### Scenario: Unconfigured service runs without authentication

- **WHEN** the service starts without OAuth configuration in the environment
- **THEN** it starts successfully and serves requests without authentication

#### Scenario: Configured service enforces authentication

- **WHEN** the service starts with complete OAuth configuration in the environment
- **THEN** it starts successfully and requires valid tokens for HTTP access

#### Scenario: Incomplete configuration fails fast

- **WHEN** the service starts with only some of the required OAuth configuration values present
- **THEN** it fails at startup with an error naming the missing configuration

### Requirement: Identity availability for tools

The system SHALL make the authenticated caller's identity available to
tools during a tool call when the HTTP transport is configured with
authentication. Tools MAY use this identity to key user-specific data.
When no authentication is configured or the caller is not authenticated,
the system SHALL not fail tool execution solely because no identity is
available; tools decide how to handle the absent identity.

#### Scenario: Tool receives the authenticated identity

- **WHEN** a client with a valid access token calls a tool and the tool
  requests the caller's identity
- **THEN** the identity derived from the token (including its email claim)
  is available to the tool

#### Scenario: Tool runs without identity

- **WHEN** the service runs without authentication configured (for example
  the stdio transport) and a tool requests the caller's identity
- **THEN** no identity is returned and the tool call itself is not rejected
  for that reason

### Requirement: Race-tolerant refresh token rotation

When a refresh token has already been consumed by a previous successful refresh,
the system SHALL, for a configurable grace period after that refresh (default
60 seconds), respond to a further refresh request presenting the consumed token
with the same token response the previous refresh issued, instead of rejecting
it. The replayed response SHALL be identical for all concurrent refreshes
presenting the same consumed token within the grace period, so parallel client
sessions converge on one token set. After the grace period has elapsed, the
system MUST reject a refresh presenting the consumed token with an
authorization error that forces re-authentication. The grace mapping MUST be
persisted in the same encrypted OAuth state storage as the token records and
MUST expire with the grace period; replay beyond the grace period or of tokens
that were never issued by the service MUST NOT succeed.

#### Scenario: Concurrent refreshes converge on one token set

- **WHEN** two refresh requests presenting the same refresh token arrive while the first one is being processed or shortly after it completed
- **THEN** both requests succeed and the second one receives the same token response the first one issued, so both client sessions hold the same valid token set

#### Scenario: Late refresh beyond the grace period is rejected

- **WHEN** a refresh request presents a refresh token that was consumed more than the grace period ago
- **THEN** the request is rejected with an error that forces re-authentication

#### Scenario: Unknown tokens never succeed

- **WHEN** a refresh request presents a token string the service never issued
- **THEN** the request is rejected with an error that forces re-authentication

#### Scenario: Grace mapping survives a restart within its window

- **WHEN** a refresh token was consumed and the service restarts within the grace period with access to the same OAuth state storage
- **THEN** a refresh presenting the consumed token still receives the replayed response until the grace period elapses

#### Scenario: Invalid grace period fails fast

- **WHEN** the service starts with a grace period configuration that is not a positive integer number of seconds
- **THEN** it fails at startup with an error naming the invalid configuration value

### Requirement: Configurable service-issued access-token lifetime

The system SHALL support an optional configuration value for the lifetime of
the access tokens it issues to clients, decoupled from the upstream identity
provider's access-token lifetime. When the value is configured, issued access
tokens MUST carry that lifetime; when it is absent, the service MUST fall back
to its built-in default (12 hours). The value MUST NOT affect the lifetime of
upstream identity-provider tokens, which the service refreshes independently.
The activation contract of the OAuth layer SHALL remain unchanged: the
lifetime value is optional and neither activates nor deactivates
authentication.

#### Scenario: Configured lifetime is issued

- **WHEN** the access-token lifetime configuration is set to a valid number of seconds and a client completes a token exchange
- **THEN** the issued access token expires after the configured number of seconds

#### Scenario: Default lifetime without configuration

- **WHEN** no access-token lifetime configuration is present and a client completes a token exchange
- **THEN** the issued access token expires after the built-in default lifetime

#### Scenario: Invalid lifetime fails fast

- **WHEN** the service starts with an access-token lifetime configuration that is not a positive integer number of seconds
- **THEN** it fails at startup with an error naming the invalid configuration value
