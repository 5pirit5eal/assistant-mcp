# Spec Delta

## ADDED Requirements

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
