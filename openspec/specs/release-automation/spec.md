# release-automation Specification

## Purpose

Automates project releases on `main`: deriving semantic versions from Conventional Commits, recording versions in the project metadata, maintaining a changelog, and publishing GitHub releases that gate deployments.

## Requirements

### Requirement: Versions are derived from Conventional Commits on main

The system SHALL derive release versions on `main` from Conventional Commits message types: `feat` triggers a minor bump, `fix` a patch bump, and a breaking-change marker a major bump. Commit types that do not affect the public behavior of the server (docs, style, chore, refactor, test, build, ci) SHALL NOT trigger a release. A push to `main` containing no releasable commits SHALL NOT produce a release. Version history SHALL be continuous with the pre-existing `v0.1.0` baseline tag, so the first release after the baseline is a bump relative to `v0.1.0`.

#### Scenario: Feature commit releases a minor version

- **WHEN** a commit of type `feat` merges to `main` with the latest tag being `v0.1.0`
- **THEN** the next release is published as `v0.2.0`

#### Scenario: Non-releasable history produces no release

- **WHEN** a push to `main` contains only commits of types docs, style, chore, refactor, test, build, or ci
- **THEN** no release is published and no version bump occurs

#### Scenario: Breaking change releases a major version

- **WHEN** a commit marked as a breaking change merges to `main`
- **THEN** the next release increments the major version segment

### Requirement: Release metadata is updated in the release commit

Each release SHALL update the project version in `pyproject.toml` and the lockfile so both record the released version, and SHALL update `CHANGELOG.md` with the generated release notes grouped by commit type (with non-releasable types omitted from the changelog). These updates SHALL land in a single release commit on `main` whose message marks it to skip continuous integration.

#### Scenario: Release commit records the version

- **WHEN** a release is published
- **THEN** `pyproject.toml` and the lockfile on `main` record the released version and `CHANGELOG.md` contains the release's notes

#### Scenario: Release commit does not retrigger pipelines

- **WHEN** the release commit is pushed to `main`
- **THEN** the release and deploy pipelines do not run again for that commit

### Requirement: Releases are published as a GitHub App

The release workflow SHALL authenticate to GitHub as a GitHub App, minting a short-lived token from the repository variable `RELEASE_APP_ID` and the repository secret `RELEASE_APP_PRIVATE_KEY`. The App MUST hold `contents: write` permission for the repository. Releases SHALL be published as full GitHub releases (not drafts or prereleases) with the generated release notes, and a `v<version>` git tag SHALL mark each release.

#### Scenario: Release is published under the app identity

- **WHEN** a release runs
- **THEN** a full GitHub release with a `v<version>` tag exists, created through the GitHub App's token

#### Scenario: Missing app credentials fail the release

- **WHEN** the release workflow runs without `RELEASE_APP_ID` or `RELEASE_APP_PRIVATE_KEY` being configured
- **THEN** the release workflow fails and no partial release artifacts (tag, changelog commit, or GitHub release) are left behind for that run

### Requirement: Releases are cut only after verification passes

A release SHALL NOT be published unless the automated verification suite for the triggering push to `main` has passed. A push that fails verification MUST NOT produce a release, and consequently MUST NOT trigger a deployment.

#### Scenario: Broken push to main produces no release

- **WHEN** a push to `main` fails linting, type checking, or tests
- **THEN** no release is published for that push and the previously released version remains the latest
