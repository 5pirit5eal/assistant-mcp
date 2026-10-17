# Spec Delta

## Purpose
Lets the assistant access image files on the user's Nextcloud (Hetzner
Storage Share) via WebDAV with per-user credentials stored encrypted and
keyed by the authenticated identity.

## ADDED Requirements

### Requirement: User-specific credential storage
The system SHALL store each user's Nextcloud credentials (WebDAV URL,
username, app password) encrypted in a persistent storage backend, keyed by
the authenticated user identity. Plaintext credentials MUST NOT be written
to the storage backend. A user MUST only be able to read and overwrite
their own stored credentials.

#### Scenario: Credentials are stored encrypted
- **WHEN** a user saves their Nextcloud credentials
- **THEN** the persisted record is encrypted with the configured storage
  encryption key and no plaintext credential material is written to the
  storage backend

#### Scenario: A user reads only their own credentials
- **WHEN** two different users have saved credentials and one user calls a
  tool that needs the stored credentials
- **THEN** the tool uses only the credentials stored under that user's
  identity key, never another user's

### Requirement: Identity resolution for the storage key
The system SHALL derive the credential storage key from the authenticated
identity of the caller when one is available. When no authenticated
identity is available, the system SHALL use an explicitly supplied user
identifier as the storage key.

#### Scenario: Authenticated identity keys the record
- **WHEN** a caller with a valid OAuth access token saves or uses Nextcloud
  credentials
- **THEN** the credentials are stored and retrieved under a key derived
  from the token's email claim

#### Scenario: Explicit user identifier without authentication
- **WHEN** the service runs without an authenticated identity (for example
  the stdio transport) and the caller supplies the user identifier
  parameter
- **THEN** the credentials are stored and retrieved under that supplied
  identifier

#### Scenario: No identity and no identifier
- **WHEN** no authenticated identity is available and no user identifier is
  supplied to a tool that requires stored credentials
- **THEN** the tool call fails with a clear error telling the caller to
  authenticate or supply the user identifier

### Requirement: Validated credential setup
The system SHALL provide a tool that saves the caller's Nextcloud
credentials only after validating them against the given WebDAV endpoint.
Invalid or unreachable credentials MUST NOT be persisted, and the tool
SHALL report the validation failure to the caller.

#### Scenario: Valid credentials are saved
- **WHEN** a user calls the credential setup tool with a WebDAV URL,
  username, and app password that authenticate successfully against the
  Nextcloud instance
- **THEN** the credentials are persisted for that user and the tool reports
  success

#### Scenario: Invalid credentials are rejected
- **WHEN** a user calls the credential setup tool with credentials that the
  Nextcloud instance rejects
- **THEN** no credentials are persisted and the tool reports the validation
  failure

### Requirement: Image listing including shares
The system SHALL provide a tool that lists the image files available to the
user's Nextcloud account in a given path, including files reachable through
folders and shares mounted in that account. Entries MUST identify whether
each item is a file or a folder and expose the file name and path needed to
download it.

#### Scenario: List images in a folder
- **WHEN** a user lists a path that contains image files and subfolders
- **THEN** the tool returns the image files with name and path, marked as
  files, and the subfolders, marked as folders

#### Scenario: List images in a mounted share
- **WHEN** a user lists a path that is part of a share mounted into their
  account
- **THEN** the image files of that share are listed like files of the
  user's own storage

#### Scenario: Path is not found
- **WHEN** a user lists a path that does not exist in their Nextcloud
- **THEN** the tool call fails with a clear error that the path was not
  found

### Requirement: Image download as file result
The system SHALL provide a tool that downloads an image file from the
user's Nextcloud and returns the original, unmodified binary content as a
file result.

#### Scenario: Download an image
- **WHEN** a user downloads an image file path that exists in their
  Nextcloud
- **THEN** the tool returns the unmodified file content as a file result
  with the image's media type and file name

#### Scenario: Download a non-existent image
- **WHEN** a user downloads a path that does not exist in their Nextcloud
- **THEN** the tool call fails with a clear error that the file was not
  found

### Requirement: No stored credentials
Tools that need stored credentials SHALL fail with a clear error when no
credentials are stored for the resolved storage key.

#### Scenario: Listing without stored credentials
- **WHEN** a user calls a listing or download tool and no credentials are
  stored under their storage key
- **THEN** the tool call fails with a clear error directing the user to
  save their credentials first
