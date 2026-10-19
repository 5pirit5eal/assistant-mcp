"""Tests for the Cloud Run deployment configuration in the deploy workflow."""

from pathlib import Path

import yaml

from assistant_mcp.server import MCP_STATELESS_HTTP

DEPLOY_WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "deploy.yml"

EXPECTED_CHECKOUT_REF = "${{ github.event.release.tag_name || github.ref }}"


def _load_workflow() -> dict:
    return yaml.safe_load(DEPLOY_WORKFLOW_PATH.read_text())


def _triggers() -> dict:
    workflow = _load_workflow()
    return workflow.get("on", workflow.get(True))


def _cloudrun_deploy_step() -> dict:
    workflow = yaml.safe_load(DEPLOY_WORKFLOW_PATH.read_text())
    for job in workflow["jobs"].values():
        for step in job.get("steps") or []:
            if str(step.get("uses", "")).startswith("google-github-actions/deploy-cloudrun"):
                return step
    raise AssertionError("no google-github-actions/deploy-cloudrun step in deploy.yml")


def test_startup_probe_targets_healthz_on_container_port():
    flags = _cloudrun_deploy_step()["with"]["flags"]
    probe_flags = [flag for flag in flags.split() if flag.startswith("--startup-probe")]
    assert probe_flags, f"no --startup-probe flag configured in flags: {flags}"
    probe = probe_flags[0]
    assert "httpGet.path=/healthz" in probe
    assert "httpGet.port=8080" in probe
    assert "initialDelaySeconds=0" in probe
    assert "periodSeconds=1" in probe
    assert "timeoutSeconds=1" in probe
    assert "failureThreshold=60" in probe


def test_stateless_http_activation_is_delivered_as_env_var():
    env_vars = _cloudrun_deploy_step()["with"]["env_vars"]
    delivered: dict[str, str] = {}
    for pair in env_vars.split(","):
        name, _, value = pair.partition("=")
        delivered[name.strip()] = value.strip()
    assert delivered.get(MCP_STATELESS_HTTP) == "true"


def test_triggers_are_release_and_workflow_dispatch_only():
    triggers = _triggers()
    assert "push" not in triggers
    assert triggers["release"] == {"types": ["released"]}
    assert "workflow_dispatch" in triggers


def test_every_job_checks_out_the_release_tag():
    workflow = _load_workflow()
    checkouts = []
    for job in workflow["jobs"].values():
        for step in job.get("steps") or []:
            if str(step.get("uses", "")).startswith("actions/checkout"):
                checkouts.append(step)
    assert len(checkouts) == len(workflow["jobs"])
    for step in checkouts:
        assert step["with"]["ref"] == EXPECTED_CHECKOUT_REF


def test_image_is_tagged_with_release_version_and_captured_sha():
    deploy_steps = _load_workflow()["jobs"]["deploy"]["steps"]
    sha_steps = [
        step for step in deploy_steps if "git rev-parse HEAD" in str(step.get("run", ""))
    ]
    assert len(sha_steps) == 1
    sha_step = sha_steps[0]
    assert sha_step.get("id"), "SHA capture step must declare an id"
    assert "$GITHUB_OUTPUT" in sha_step["run"]

    build_step = next(
        step
        for step in deploy_steps
        if str(step.get("uses", "")).startswith("docker/build-push-action")
        and step.get("with", {}).get("push") is True
    )
    tags = build_step["with"]["tags"]
    fallback = (
        "github.event.release.tag_name || format('manual-{0}', "
        "steps." + sha_step["id"] + ".outputs.sha)"
    )
    assert "${{ env.IMAGE }}:${{ " + fallback + " }}" in tags
    assert "${{ env.IMAGE }}:${{ steps." + sha_step["id"] + ".outputs.sha }}" in tags
    assert "github.sha" not in tags


def test_deploy_job_has_no_main_branch_guard():
    deploy_job = _load_workflow()["jobs"]["deploy"]
    assert "if" not in deploy_job
