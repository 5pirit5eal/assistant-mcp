## Why

Every verification step (tests, lint, type-check, Docker build) is manual today, deployments to Cloud Run are run by hand from README commands, and nothing keeps dependencies or the Python baseline current. As the server grows and main becomes the deploy source, unverified code can reach production and dependencies silently age.

## What Changes

- Bump the Python baseline to 3.14 across the project: `requires-python = ">=3.14"` in `pyproject.toml`, `python:3.14-slim` in the Dockerfile, ruff/mypy targets updated to py314, and `uv lock --upgrade` to re-lock all dependencies at their latest resolvable versions.
- Add a CI workflow (GitHub Actions) that runs `ruff check`, `mypy src`, and `pytest` with uv on Python 3.14, builds the Docker image, and runs the full test suite inside the built image so the soffice-gated Office-to-PDF tests are genuinely executed (not skipped).
- Add a CD workflow (GitHub Actions) that, on push to main and via manual `workflow_dispatch`, builds and pushes the image to Artifact Registry (`europe-west1-docker.pkg.dev/rubenschulze-sandbox/assistant-mcp/server`) and deploys it to Cloud Run, authenticating via Workload Identity Federation (GitHub OIDC) — no service-account key secret stored in GitHub.
- Add Dependabot configuration for three ecosystems: pip (pyproject.toml + uv.lock), github-actions, and docker — with patch and minor pip updates auto-merging once CI passes; major bumps always require manual review.
- Document the one-time GCP prerequisites (WIF provider, pool, deploy service account, Artifact Registry repository) and the manual GitHub branch-protection setup (required CI checks on main, PR-only merges), which enable the auto-merge policy.
- Update the README's deployment section to reflect the new automated pipeline and Artifact Registry.

## Capabilities

### New Capabilities

- `ci-pipeline`: Automated verification of every pull request and push — lint, type-check, unit tests on Python 3.14, Docker image build, and full test-suite execution inside the built image so system-tool-gated tests always run.
- `cloud-run-deployment`: Automated deployment of main to Google Cloud Run via Artifact Registry and Workload Identity Federation, with a manual trigger as an escape hatch.
- `dependency-updates`: Dependabot-driven dependency updates for pip, GitHub Actions, and Docker, with a defined auto-merge policy for patch/minor Python bumps.

### Modified Capabilities

(none — the existing specs `pdf-file-conversion`, `pdf-generation`, and `toolset-tool-interface` are unaffected; their behavior does not change.)

## Impact

- **Code / tooling**: `pyproject.toml` (`requires-python`, ruff `target-version`, mypy target), `uv.lock` (full re-lock with upgrades), `Dockerfile` (base image `python:3.14-slim`), new `.github/workflows/ci.yml`, new `.github/workflows/deploy.yml`, new `.github/dependabot.yml`.
- **Documentation surfaces**: `README.md` — local development and deployment sections change (Python 3.14 baseline, Artifact Registry, automated pipeline replacing manual gcloud commands); the GCP one-time setup steps are documented there or in the design.
- **External systems (one-time, outside the repo)**: Google Cloud — Artifact Registry repository, WIF pool/provider, deploy service account and role bindings; GitHub — branch protection on main (required checks, PR-only).
- **Dependencies**: all runtime and dev dependencies re-resolved to latest compatible versions on Python 3.14 via `uv lock --upgrade`.
