# service-auth Specification

## Purpose
Defines who may use the HTTP-exposed assistant-mcp service and how callers prove
their identity: an OAuth 2.1 layer in front of all tools, with Google as the
identity provider, an explicit account allowlist enforced by the service itself,
encrypted persistence of the OAuth state that survives restarts, and a
configuration contract that activates authentication only when fully configured.

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
