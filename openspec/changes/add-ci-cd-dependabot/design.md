## Context

See proposal.md - Why. Today the project has no `.github/` directory: tests, lint, type-check, Docker builds, and Cloud Run deploys all run manually on a developer machine. The container image (`python:3.12-slim` + LibreOffice) is the deploy artifact; `uv.lock` is the dependency source of truth; the test suite skips Office-to-PDF tests when `soffice` is missing. Deployment currently uses legacy `gcr.io` with manual `gcloud` commands (README), and `pyproject.toml` declares `requires-python >= 3.11`.

## Goals / Non-Goals

**Goals:**

- One verified path from pull request to production: green CI on PRs, deploy on green pushes to `main`, manual trigger as escape hatch.
- The Python 3.14 bump lands as the first phase so CI verifies exactly what ships.
- No long-lived cloud credentials stored in GitHub.

**Non-Goals:**

- No staging environment, canary releases, or multi-region deployment — single Cloud Run service in `europe-west1`.
- No publishing to PyPI or any other deployment target.
- No changes to the toolsets, their tools, or their specs — this change only touches the toolchain around them.
- No version-tag/release automation (deploy is trunk-based, not tag-based — explicitly decided during exploration).

## Decisions

### D1 - Python 3.14 everywhere, no version matrix

`requires-python = ">=3.14"`, `python:3.14-slim` base image, ruff `target-version = "py314"`, mypy `python_version = "3.14"` (only if mypy supports 3.14 as a target at the locked version — verify empirically, see Risks). CI runs one host job on Python 3.14; the Docker image is also 3.14, so there is exactly one baseline to verify. A matrix over 3.11-3.14 was rejected: this is an application, not a library, and a single deploy artifact means a matrix would verify versions that are never shipped.

### D2 - Re-lock with `uv lock --upgrade` as the first implementation task

Bumping `requires-python` forces re-resolution anyway; upgrading all dependencies in the same step (explicitly chosen during exploration) avoids a second re-lock churn when Dependabot starts running. This is the riskiest step of the change, so it lands first and is verified empirically before any workflow is written: `uv lock --upgrade`, then `uv run pytest`, `uv run ruff check .`, `uv run mypy src` on Python 3.14, plus a local `docker build` and in-image test run. A dependency that fails on 3.14 pins back to its newest working version rather than blocking the change.

### D3 - Two workflow files with split triggers: CI on PRs, deploy pipeline on main

- `.github/workflows/ci.yml` — triggers: `pull_request` (targeting main) plus `push` to `main` and `workflow_dispatch` so branch protection can require a check that also exists for direct pushes.
- `.github/workflows/deploy.yml` — triggers: `push` to `main`, `workflow_dispatch`.

`deploy.yml` is self-contained: it runs the full verification (host lint/types/tests, Docker build, in-image test run) as prerequisite jobs, then pushes the image and deploys only if all of them pass (`needs`), which satisfies the "deployment only after verification" requirement for the exact deployed commit without cross-workflow `workflow_run` bookkeeping. Alternative rejected: gating deploy on `ci.yml` via `workflow_run` — adds ordering races and head-SHA plumbing for no benefit. Cost: pushes to main that skip CI still get re-verified inside deploy; with branch protection this duplication is rare.

CI jobs:

1. **host**: `astral-sh/setup-uv` (cache enabled, Python 3.14, `--frozen` sync) → `ruff check .`, `mypy src`, `pytest`. The soffice-gated tests may skip here; that is acceptable because job 2 covers them.
2. **docker**: `docker/setup-buildx-action` + `docker/build-push-action` (layer cache via the GitHub Actions cache backend, image loaded locally, never pushed), then run the full suite inside the image with `docker run ... uv run --no-sync pytest` (the pattern AGENTS.md prescribes), so Office-to-PDF tests execute against the image's LibreOffice rather than skipping. PR runs never push the image (per the ci-pipeline spec); image push happens only in `deploy.yml`. The same buildx/GHA-cache mechanism is used in `deploy.yml`'s verification and deploy jobs so the LibreOffice apt layer is rebuilt only when it changes.

### D4 - Artifact Registry + `deploy-cloudrun` action + WIF/OIDC

- Image: `europe-west1-docker.pkg.dev/rubenschulze-sandbox/assistant-mcp/server` (colocated with the service region; `gcr.io` is legacy).
- Auth: `google-github-actions/auth@v3` with `workload_identity_provider` + `service_account` (`github-actions-deploy@rubenschulze-sandbox.iam.gserviceaccount.com`), permissions `id-token: write` on the job. The provider path embeds the GCP project number, which becomes known only after the one-time setup; the workflow therefore reads it from the repository variable `WORKLOAD_IDENTITY_PROVIDER` (set during setup, documented in the README) and fails fast with the fix command when it is unset. A provider path is not a credential — no long-lived secret is stored in GitHub.
- Roles for that service account: `roles/artifactregistry.writer` on the repository, `roles/run.admin` on the service, `roles/iam.serviceAccountUser` on the Cloud Run runtime service account.
- Deploy: `google-github-actions/deploy-cloudrun@v3` with service `assistant-mcp`, region `europe-west1`, `--allow-unauthenticated`, env `MCP_TRANSPORT=http`, image digest-pinned from the build step.
- Alternatives rejected: base64 service-account key secret (long-lived credential in GitHub); raw `gcloud run deploy` in `run:` steps (more boilerplate, no advantage over the maintained action, and the action is covered by the `github-actions` Dependabot ecosystem).

### D5 - Dependabot: three ecosystems, auto-merge for patch/minor via a small workflow

`.github/dependabot.yml` with:

- `uv` (directory `/`, schedule weekly) — updates `pyproject.toml` + `uv.lock` together; Dependabot's `uv` ecosystem understands uv.lock, while the `pip` ecosystem cannot regenerate it (a pip PR would bump `pyproject.toml` and leave the frozen lockfile stale, failing CI permanently)
- `github-actions` (directory `/`) — keeps action versions current
- `docker` (directory `/`) — base image bumps for `python:3.14-slim`

Dependabot has no native auto-merge. A small workflow (`pull_request_target` triggered only for Dependabot PRs, with the Dependabot metadata exposed by the PR body) enables GitHub auto-merge with squash when the update type is `semver:patch` or `semver:minor`; major updates are left for manual review. This requires branch protection with the CI check required on `main` (manual GitHub step, documented in README), which is also what makes the auto-merge safe.

### D6 - Test and verification interfaces

Per the project's testing rules, the tests this change relies on drive the public MCP interface only:

- **Existing pytest suite** (via `fastmcp.Client`): covers tool behavior, registry compliance, and the Office-to-PDF conversion inside the image — this is the behavioral gate for the Python 3.14 + re-lock bump (D2) and every later Dependabot PR. It does not cover workflow YAML, GCP wiring, or deploy correctness.
- **Pipeline self-verification**: the CI/CD workflows are exercised by landing them on a PR — the first real run of `ci.yml` is its own test (the PR that adds the workflows is verified by them). Structural workflow validation uses `actionlint` locally before commit. Deploy wiring is verified by the first `deploy.yml` run on the merge commit; it cannot be meaningfully unit-tested.
- **In-image test run**: covered by the docker job; verifies the Dockerfile (AGENTS.md mandates `docker build` success for Dockerfile changes and in-image runs for skip-gated tests).

## Risks / Trade-offs

- [A dependency has no Python 3.14-compatible release yet] → Mitigation: D2 makes the re-lock the first, empirically verified task; incompatible pins drop back to the newest working version instead of stalling the change.
- [mypy's locked version may not accept `python_version = "3.14"`] → Mitigation: verify empirically during D2; if unsupported, omit the mypy target pin (mypy then follows the interpreter) rather than pinning an older version.
- [LibreOffice makes the Docker build slow (~4-5 min layer)] → Mitigation: Docker layer caching (GHA cache backend) so unchanged apt layers are not rebuilt; acceptable for a trunk-based personal project.
- [WIF/Cloud IAM misconfiguration only surfaces at first deploy] → Mitigation: the one-time `gcloud` setup is scripted/documented in the README and executed before the first merge to main; first deploy run acts as the verification.
- [Auto-merge of a patch release breaks runtime despite green CI] → Mitigation: suite runs in-image; residual risk (untested runtime paths) accepted — major bumps stay manual.
- [Direct push to main re-runs everything in deploy.yml (duplicate CI)] → Mitigation: branch protection makes direct pushes impossible; duplication only affects repo admins bypassing protection.

## Migration Plan

1. Land the Python 3.14 bump + re-lock on a PR (verified by the existing suite run on 3.14, locally and in-image).
2. Add `ci.yml`, `deploy.yml`, `dependabot.yml`, auto-merge workflow; validate with `actionlint`; the adding-PR is verified by `ci.yml` itself.
3. One-time GCP setup (documented, run by the owner): Artifact Registry repository `assistant-mcp` in `europe-west1`; WIF pool `github-actions` + OIDC provider `github-com` (audience-restricted to repo `5pirit5eal/assistant-mcp`); deploy service account with roles from D4.
4. Enable branch protection on `main`: require the `ci` and `docker` checks, PR-only merges — also enables Dependabot auto-merge.
5. Merge to main: `deploy.yml` runs end-to-end and serves the new revision.
6. Rollback strategy: every main deploy keeps its commit-SHA image tag in Artifact Registry; roll back with `gcloud run services update-traffic` to the previous revision, or point the service at an older SHA-tagged image via `gcloud run deploy --image`.

## Open Questions

(none)
