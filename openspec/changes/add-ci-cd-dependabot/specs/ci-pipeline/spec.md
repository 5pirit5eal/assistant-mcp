## Purpose

Defines the automated verification pipeline that gates every change to the assistant-mcp server: lint, type-check, tests on the supported Python version, and a container-image build whose interior test run exercises system-tool-gated tests.

## ADDED Requirements

### Requirement: Automated verification for every change to main

The system SHALL run automated verification — linting (`ruff`), static type checking (`mypy`), and the full unit test suite (`pytest`) — for every pull request targeting `main` and every push to `main`. Verification failures MUST block the change from being considered green.

#### Scenario: Broken pull request is flagged

- **WHEN** a pull request introduces a lint error, a type error, or a failing test
- **THEN** the pull request's verification run fails and the change is reported red

#### Scenario: Clean pull request passes

- **WHEN** a pull request leaves lint, types, and tests in a passing state
- **THEN** the pull request's verification run completes successfully and the change is reported green

### Requirement: Python 3.14 baseline

The project SHALL declare Python 3.14 as its supported baseline: `requires-python >= 3.14`, a matching container base image, and lint/type targets set to Python 3.14. Continuous integration MUST execute on Python 3.14 so the declared baseline is actually verified.

#### Scenario: Project metadata declares the baseline

- **WHEN** a developer inspects the project metadata and container image
- **THEN** both require Python 3.14 or newer, and the container base image is a Python 3.14 image

#### Scenario: Dependency incompatible with the baseline fails CI

- **WHEN** a dependency version resolved into the lockfile does not work on Python 3.14
- **THEN** the continuous integration run on Python 3.14 fails, surfacing the incompatibility before deploy

### Requirement: Full test suite runs inside the built container image

Continuous integration MUST build the project's container image and run the complete test suite inside the built image. Tests gated on system tools (such as LibreOffice `soffice` for Office-to-PDF conversion) MUST execute inside the image rather than being skipped. The image build MUST succeed for the run to pass.

#### Scenario: System-tool-gated tests execute

- **WHEN** the in-image test job runs the Office-to-PDF conversion tests
- **THEN** the tests execute against the LibreOffice installation inside the image instead of being skipped

#### Scenario: Container regression fails CI

- **WHEN** a change breaks the container image build or a test that depends on the image's system tools
- **THEN** the in-image job fails, blocking the change

### Requirement: Container image published only on main

The pipeline SHALL push the built container image to the project's container registry only for commits on `main`; pull-request runs MUST build the image for verification without publishing it.

#### Scenario: Pull request build is not published

- **WHEN** verification runs for a pull request
- **THEN** the container image is built and tested but never pushed to the registry
