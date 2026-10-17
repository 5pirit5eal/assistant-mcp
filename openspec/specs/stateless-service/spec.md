# stateless-service Specification

## Purpose

Defines the assistant-mcp service's runtime contract as a stateless service: an unauthenticated health endpoint for platform startup probes, stateless HTTP operation by design and configuration, persistent state kept in Firestore with an in-process cache, and toolsets that hold no cross-request state.

## Requirements

### Requirement: Health endpoint for platform probes

The system SHALL expose an HTTP GET endpoint at `/healthz` that returns status 200 once the HTTP application is serving. The endpoint SHALL be reachable without authentication when OAuth is configured, in both stateful and stateless HTTP modes. The endpoint SHALL NOT check dependency health (no database connectivity check).

#### Scenario: Probe succeeds once the application serves

- **WHEN** the platform sends a GET request to `/healthz` on a running instance
- **THEN** the endpoint responds with status 200

#### Scenario: Health endpoint is exempt from authentication

- **WHEN** OAuth is configured and a client requests `/healthz` without an access token
- **THEN** the endpoint responds with status 200 while an unauthenticated request to the MCP endpoint is rejected

#### Scenario: Health endpoint is available in stateless mode

- **WHEN** the service runs the HTTP transport in stateless mode and a client requests `/healthz`
- **THEN** the endpoint responds with status 200

### Requirement: Stateless HTTP by design and configuration

When the HTTP transport is used, the system SHALL serve each request independently without retaining session state across requests, by default. The default SHALL be overridable by setting the environment variable `MCP_STATELESS_HTTP` to `false`, which restores stateful behavior. The stdio transport SHALL NOT be affected by this setting.

#### Scenario: HTTP transport is stateless by default

- **WHEN** the service starts with `MCP_TRANSPORT=http` and no `MCP_STATELESS_HTTP` override
- **THEN** each request is served independently: the MCP endpoint does not serve the GET server-initiated message stream, and no session state is retained across requests

#### Scenario: Override restores stateful behavior

- **WHEN** the service starts with `MCP_TRANSPORT=http` and `MCP_STATELESS_HTTP=false`
- **THEN** the HTTP transport retains its stateful behavior, including the GET server-initiated message stream on the MCP endpoint

#### Scenario: stdio transport is unaffected

- **WHEN** the service runs with the stdio transport
- **THEN** tools are served as before, regardless of `MCP_STATELESS_HTTP`

### Requirement: Persistent state in the database with in-process caching

State that must survive requests or restarts SHALL be stored in the Firestore-backed storage. Reads SHALL be served from an in-process cache while a cached entry has not expired, to minimize database operations. Values SHALL be encrypted before they are cached, so the cache never holds plaintext token material. Writes SHALL invalidate the cached entry and persist to the database.

#### Scenario: Repeated reads avoid database operations

- **WHEN** a stored value is read repeatedly within the cache lifetime
- **THEN** the storage backend is read at most once; subsequent reads are served from the in-process cache

#### Scenario: Writes persist to the database

- **WHEN** a value is written to the storage
- **THEN** the write is persisted to the database, the cached entry is invalidated, and a subsequent read returns the new value

#### Scenario: Cache holds no plaintext secrets

- **WHEN** a value is cached
- **THEN** the cached representation is encrypted and contains no plaintext token material

### Requirement: No cross-request state in process memory

The system SHALL NOT retain per-request or per-user state in process memory. Toolset modules SHALL NOT use `global` statements and SHALL NOT mutate module-level state. State that must survive requests or restarts SHALL use the Firestore-backed storage with in-process caching.

#### Scenario: Behavior is identical across instances

- **WHEN** two requests with the same input are served by different service instances
- **THEN** both produce the same result, because no state is held in process memory

#### Scenario: Toolset modules hold no mutable state

- **WHEN** the toolset modules are inspected
- **THEN** no toolset module uses `global` statements or mutates module-level state
