# nextcloud-images Specification

## Purpose
Lets the assistant access image files on the user's Nextcloud (Hetzner
Storage Share) via WebDAV with per-user credentials stored encrypted and
keyed by the authenticated identity.

## Requirements

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
The system SHALL derive the credential storage key exclusively from the
authenticated identity of the caller. Tools MUST NOT accept any parameter
that selects or overrides the storage key. When the service runs without an
authenticated identity (for example the stdio transport), the system SHALL
instead use credentials supplied through environment configuration for a
single account.

#### Scenario: Authenticated identity keys the record
- **WHEN** a caller with a valid OAuth access token saves or uses Nextcloud
  credentials
- **THEN** the credentials are stored and retrieved under a key derived
  from the token's email claim

#### Scenario: No identity and no environment credentials
- **WHEN** the service runs without an authenticated identity and without
  the single-account environment configuration, and a caller invokes a tool
  that requires credentials
- **THEN** the tool call fails with a clear error telling the caller to
  authenticate or configure the single-account environment variables

### Requirement: Single-account fallback via environment configuration
The system SHALL support a single-account credential configuration through
environment variables (WebDAV URL, username, app password) used only when
no authenticated identity is available. This configuration MUST NOT be used
when the caller is authenticated, and it MUST NOT grant access to any
other user's stored credentials.

#### Scenario: stdio mode uses environment credentials
- **WHEN** the service runs on the stdio transport with the single-account
  environment variables set and a caller lists or downloads images
- **THEN** the tools operate against the Nextcloud account given by the
  environment configuration

#### Scenario: Environment credentials ignored when authenticated
- **WHEN** a caller with a valid OAuth access token invokes a tool while the
  single-account environment variables are also set
- **THEN** the tool uses the credentials stored under the caller's
  identity, not the environment credentials

#### Scenario: Partial environment configuration is rejected
- **WHEN** the service starts with some but not all of the single-account
  environment variables set
- **THEN** the service reports the incomplete configuration and refuses to
  use the fallback credentials

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

### Requirement: Image listing with metadata and thumbnails
The system SHALL provide a tool that lists the image files available to the
user's Nextcloud account in a given path, including files reachable through
folders and shares mounted in that account. Each entry MUST identify
whether the item is a file or a folder and SHALL expose the file's WebDAV
metadata from the PROPFIND response (file id, name, path, content type,
size, last-modified date, permissions, owner) and the delivered preview
availability: an entry's preview availability is true exactly when the
tool result includes a thumbnail for that entry. For each listed image
file with an available preview, the tool SHALL also return a thumbnail
image in the same tool result, correlated to its metadata entry by list
order. A missing or failed preview MUST NOT fail the listing.

#### Scenario: List images in a folder
- **WHEN** a user lists a path that contains image files and subfolders
- **THEN** the tool returns the image files with their metadata (file id,
  name, path, content type, size, last-modified date, permissions, owner,
  and preview availability), marked as files, and the subfolders, marked
  as folders

#### Scenario: Thumbnails accompany image entries
- **WHEN** the listing returns an image file whose preview is available on
  the Nextcloud
- **THEN** the tool result contains a thumbnail image for that file,
  correlated to the file's metadata entry by list order

#### Scenario: No preview available
- **WHEN** the listing contains a file whose preview is unavailable or
  whose preview request fails
- **THEN** the file's metadata entry is returned without a thumbnail and
  the listing succeeds

#### Scenario: List images in a mounted share
- **WHEN** a user lists a path that is part of a share mounted into their
  account
- **THEN** the image files of that share are listed like files of the
  user's own storage

#### Scenario: Path is not found
- **WHEN** a user lists a path that does not exist in their Nextcloud
- **THEN** the tool call fails with a clear error that the path was not
  found

### Requirement: Image download as image content
The system SHALL provide a tool that downloads an image file from the
user's Nextcloud and returns the original, unmodified binary content as an
image result with the image's media type.

#### Scenario: Download an image
- **WHEN** a user downloads an image file path that exists in their
  Nextcloud
- **THEN** the tool returns the unmodified file content as image content
  with the image's media type

#### Scenario: Download a non-existent image
- **WHEN** a user downloads a path that does not exist in their Nextcloud
- **THEN** the tool call fails with a clear error that the file was not
  found

### Requirement: No stored credentials
Tools that need stored credentials SHALL fail with a clear error when no
credentials are available for the resolved caller.

#### Scenario: Listing without stored credentials
- **WHEN** an authenticated user calls a listing or download tool and no
  credentials are stored under their identity key
- **THEN** the tool call fails with a clear error directing the user to
  save their credentials first
