"""Tests for the Cloud Run deployment configuration in the deploy workflow."""

from pathlib import Path

import yaml

from assistant_mcp.server import MCP_STATELESS_HTTP

DEPLOY_WORKFLOW_PATH = Path(__file__).parent.parent / ".github" / "workflows" / "deploy.yml"


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
