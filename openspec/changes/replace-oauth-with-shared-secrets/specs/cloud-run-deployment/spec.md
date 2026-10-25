# cloud-run-deployment Delta

## MODIFIED Requirements

### Requirement: Automated deployment on main and on demand

The system SHALL deploy to Google Cloud Run when a full GitHub release is
published from `main` and via a manual workflow trigger. A deployment MUST
check out the release tag, build the container image, publish it to the
project's Artifact Registry repository in `europe-west1` under both a release
version tag and a commit SHA tag, and roll it out to the Cloud Run service
`assistant-mcp` in region `europe-west1` (project `rubenschulze-sandbox`) with
unauthenticated ingress access allowed, `MCP_TRANSPORT=http` set,
`MCP_STATELESS_HTTP=true` set, and the shared-secret authentication
activation flag `MCP_SHARED_SECRET_AUTH=true` injected as a plain environment
variable sourced from the deployment workflow. The deployment MUST NOT inject
OAuth client credentials, OAuth storage encryption keys, or account allowlist
values, and MUST NOT source any secret from Google Secret Manager. The
service's registered user secrets live in Firestore and are not deployment
inputs.

#### Scenario: Green push to main deploys

- **WHEN** a push to `main` passes the full verification suite and its release is published
- **THEN** the released revision's container image is published to Artifact Registry under both its version tag and commit SHA tag and deployed as a new Cloud Run revision that receives the shared-secret authentication activation flag as a plain environment variable

#### Scenario: Manual trigger deploys the current main

- **WHEN** a deployment is triggered manually with no code changes
- **THEN** the workflow builds, publishes, and deploys the current state of `main`

#### Scenario: Base URL is stable across deploys

- **WHEN** two consecutive deployments deliver the authentication configuration
- **THEN** both revisions receive the identical literal `MCP_SHARED_SECRET_AUTH=true` value, so the service's authentication activation state never changes between deploys

#### Scenario: Missing base URL variable blocks the deployment

- **WHEN** a deployment runs and a repository variable the workflow requires (such as `GCS_BUCKET_NAME`) is unset or empty
- **THEN** the workflow fails before deploying anything and names the missing variable and how to set it

#### Scenario: Deployment carries no secrets

- **WHEN** a deployment completes and the deployed revision's environment is inspected
- **THEN** it contains no Secret Manager-sourced values and no OAuth configuration values

#### Scenario: Redeploy does not affect registered users

- **WHEN** two consecutive deployments roll out new revisions
- **THEN** users registered in Firestore are unaffected by either deployment and their secrets keep working without re-registration
