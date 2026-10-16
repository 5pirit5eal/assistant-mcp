## Purpose

Defines how the assistant-mcp server is deployed to Google Cloud Run automatically from `main`, using Artifact Registry for images and keyless Workload Identity Federation for authentication, so no manual gcloud steps or stored credentials are required.

## ADDED Requirements

### Requirement: Automated deployment on main and on demand

The system SHALL deploy to Google Cloud Run on every push to `main` and via a manual workflow trigger. A deployment MUST build the container image, publish it to the project's Artifact Registry repository in `europe-west1`, and roll it out to the Cloud Run service `assistant-mcp` in region `europe-west1` (project `rubenschulze-sandbox`) with unauthenticated access allowed and `MCP_TRANSPORT=http` set.

#### Scenario: Green push to main deploys

- **WHEN** a push to `main` passes the full verification suite
- **THEN** a new container image is published to Artifact Registry and deployed as a new Cloud Run revision

#### Scenario: Manual trigger deploys the current main

- **WHEN** a deployment is triggered manually with no code changes
- **THEN** the workflow builds, publishes, and deploys the current state of `main`

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
