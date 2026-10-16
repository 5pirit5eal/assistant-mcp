## Purpose

Defines how the project's dependencies — Python packages, GitHub Actions workflows, and the Docker base image — are kept current through automated update proposals with a defined merge policy.

## ADDED Requirements

### Requirement: Automated dependency monitoring

The system SHALL monitor three dependency ecosystems for newer versions: Python dependencies (project metadata and lockfile), GitHub Actions used by the workflows, and the container base image. When an update is available, an update proposal MUST be raised automatically and periodically.

#### Scenario: New Python dependency version triggers an update

- **WHEN** a newer version of a Python dependency becomes available
- **THEN** an automated update proposal is raised that updates both the project metadata and the lockfile consistently

#### Scenario: Outdated workflow action triggers an update

- **WHEN** a GitHub Action referenced by a workflow has a newer release
- **THEN** an automated update proposal is raised that bumps the action reference

### Requirement: Update proposals run the same verification

Every automated dependency update proposal MUST be subject to the same verification suite as any other change to `main`, and that verification MUST be a precondition for merging.

#### Scenario: Breaking update is caught by verification

- **WHEN** an update proposal introduces a regression detected by the verification suite
- **THEN** the proposal stays unmerged and red until it is updated or dismissed

### Requirement: Merge policy by update severity

Patch and minor Python dependency updates MUST merge automatically once verification passes. Major version updates MUST wait for manual review.

#### Scenario: Compatible minor update auto-merges

- **WHEN** a patch or minor Python dependency update passes the verification suite
- **THEN** the update merges into `main` without manual intervention, triggering the deployment pipeline

#### Scenario: Major update requires review

- **WHEN** a major version update proposal is raised
- **THEN** it remains open for manual review regardless of verification status
