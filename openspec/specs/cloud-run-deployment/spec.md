# cloud-run-deployment Specification

## Purpose

Defines how the assistant-mcp server is deployed to Google Cloud Run automatically from `main`, using Artifact Registry for images and keyless Workload Identity Federation for authentication, so no manual gcloud steps or stored credentials are required.

## Requirements

### Requirement: Automated deployment on main and on demand

The system SHALL deploy to Google Cloud Run when a full GitHub release is published from `main` and via a manual workflow trigger. A deployment MUST check out the release tag, build the container image, publish it to the project's Artifact Registry repository in `europe-west1` under both a release version tag and a commit SHA tag, and roll it out to the Cloud Run service `assistant-mcp` in region `europe-west1` (project `rubenschulze-sandbox`) with unauthenticated ingress access allowed, `MCP_TRANSPORT=http` set, `MCP_STATELESS_HTTP=true` set, and the shared-secret authentication activation flag `MCP_SHARED_SECRET_AUTH=true` injected as a plain environment variable sourced from the deployment workflow. The deployment MUST NOT inject OAuth client credentials, OAuth storage encryption keys, or account allowlist values, and MUST NOT source any secret from Google Secret Manager. The service's registered user secrets live in Firestore and are not deployment inputs.

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

### Requirement: Deployment only after verification

A deployment MUST NOT occur unless the complete verification suite — including the in-image test run — has passed for the exact commit being deployed.

#### Scenario: Failing main blocks deployment

- **WHEN** a push to `main` fails any verification step
- **THEN** no new revision is deployed and the previously deployed revision remains serving

### Requirement: Keyless authentication to Google Cloud

The deployment workflow MUST authenticate to Google Cloud through Workload Identity Federation using the GitHub OIDC token. No long-lived service-account key MUST be stored in GitHub as a secret.

#### Scenario: Workflow authenticates without stored credentials

- **WHEN** the deployment workflow starts
- **THEN** it exchanges the runner's GitHub OIDC token for short-lived Google credentials through the configured Workload Identity Federation provider and proceeds without reading any key secret from GitHub

### Requirement: Deployment pipeline is documented

The project documentation SHALL describe the deployment pipeline, including the one-time Google Cloud setup (Artifact Registry repository, workload identity pool and provider, deploy service account with its role bindings) that the pipeline depends on.

#### Scenario: New contributor can reproduce the setup

- **WHEN** a contributor reads the project documentation
- **THEN** they find the recorded one-time setup steps and the automated pipeline description sufficient to understand how deploys reach Cloud Run

### Requirement: Startup probe gates traffic on the health endpoint

The deployment SHALL configure a Cloud Run startup probe for the service that sends HTTP GET requests to `/healthz` on the container port, with probe timing that allows a Python cold start (module imports and server bind) to complete. While an instance's startup probe has not succeeded, incoming requests SHALL be held by the platform instead of being routed to the instance.

#### Scenario: Cold start stalls the request instead of erroring

- **WHEN** a new instance is starting and a client request arrives at the service
- **THEN** the platform holds the request until the startup probe succeeds and then serves it, instead of the client receiving an error response from a non-ready instance

#### Scenario: Failing startup probe blocks the deployment

- **WHEN** a new revision's startup probe does not succeed during deployment
- **THEN** the deployment fails and the previously deployed revision keeps serving

### Requirement: Stateless HTTP activation is delivered to the deployment

The deployment SHALL deliver the stateless HTTP configuration to the service as a plain environment variable `MCP_STATELESS_HTTP` set to `true`, so the deployed service runs the HTTP transport in stateless mode by explicit configuration.

#### Scenario: Deployed service runs stateless HTTP

- **WHEN** the deployment delivers `MCP_STATELESS_HTTP=true` to the service
- **THEN** the service serves HTTP requests in stateless mode
