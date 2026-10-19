"""Tests for the semantic-release configuration and release workflow contracts."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
RELEASE_CONFIG_PATH = REPO_ROOT / ".releaserc"
RELEASE_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "release.yml"

RELEASE_APP_ID = "${{ vars.RELEASE_APP_ID }}"
RELEASE_APP_PRIVATE_KEY = "${{ secrets.RELEASE_APP_PRIVATE_KEY }}"
PREPARE_CMD = "uv version ${nextRelease.version} --no-sync"
RELEASE_COMMIT_MESSAGE = "chore(release): ${nextRelease.version} [skip ci]"
GIT_ASSETS = ["CHANGELOG.md", "pyproject.toml", "uv.lock"]
HIDDEN_TYPES = ["docs", "style", "chore", "refactor", "test", "build", "ci"]
VISIBLE_SECTIONS = {
    "feat": "Features",
    "feature": "Features",
    "fix": "Bug Fixes",
    "perf": "Performance Improvements",
    "revert": "Reverts",
}


def _release_config() -> dict:
    return yaml.safe_load(RELEASE_CONFIG_PATH.read_text())


def _plugins() -> list[tuple[str, dict | None]]:
    plugins: list[tuple[str, dict | None]] = []
    for entry in _release_config()["plugins"]:
        if isinstance(entry, str):
            plugins.append((entry, None))
        else:
            plugins.append((entry[0], entry[1]))
    return plugins


def _plugin_config(name: str) -> dict:
    for plugin_name, config in _plugins():
        if plugin_name == name:
            assert isinstance(config, dict), f"{name} must have a config object"
            return config
    raise AssertionError(f"no {name} plugin in .releaserc")


def test_release_targets_main_branch_only():
    assert _release_config()["branches"] == ["main"]


def test_preset_hides_non_releasable_types():
    config = _release_config()
    assert config["preset"] == "conventionalcommits"
    types = {entry["type"]: entry for entry in config["presetConfig"]["types"]}
    for type_name in HIDDEN_TYPES:
        assert types[type_name]["hidden"] is True, f"{type_name} must be hidden"
    for type_name, section in VISIBLE_SECTIONS.items():
        assert types[type_name]["section"] == section
        assert types[type_name].get("hidden") is not True


def test_plugin_chain_bumps_version_and_commits_release_assets():
    names = [name for name, _ in _plugins()]
    expected_order = [
        "@semantic-release/commit-analyzer",
        "@semantic-release/release-notes-generator",
        "@semantic-release/changelog",
        "@semantic-release/exec",
        "@semantic-release/git",
        "@semantic-release/github",
    ]
    assert names == expected_order


def test_exec_plugin_bumps_version_with_uv():
    assert _plugin_config("@semantic-release/exec")["prepareCmd"] == PREPARE_CMD


def test_git_plugin_commits_changelog_and_version_files():
    git_config = _plugin_config("@semantic-release/git")
    assert git_config["assets"] == GIT_ASSETS
    assert git_config["message"].startswith(RELEASE_COMMIT_MESSAGE)


def _release_workflow() -> dict:
    return yaml.safe_load(RELEASE_WORKFLOW_PATH.read_text())


def _triggers() -> dict:
    workflow = _release_workflow()
    return workflow.get("on") or workflow.get(True)


def _release_job() -> dict:
    return _release_workflow()["jobs"]["release"]


def _steps_by_action() -> dict[str, dict]:
    steps: dict[str, dict] = {}
    for step in _release_job()["steps"]:
        if "uses" in step:
            action = step["uses"].split("@")[0]
            assert action not in steps, f"duplicate step for {action}"
            steps[action] = step
    return steps


def test_workflow_triggers_on_main_push_and_manual_dispatch():
    triggers = _triggers()
    assert triggers["push"]["branches"] == ["main"]
    dispatch = triggers["workflow_dispatch"]["inputs"]["dry_run"]
    assert dispatch["type"] == "boolean"
    assert dispatch["default"] is False


def test_release_run_serializes_and_has_no_job_level_gate():
    assert "if" not in _release_job()
    concurrency = _release_workflow()["concurrency"]
    assert concurrency["group"] == "release"
    assert concurrency["cancel-in-progress"] is False


def test_workflow_has_no_workflow_run_or_pull_request_trigger():
    triggers = _triggers()
    assert set(triggers) == {"push", "workflow_dispatch"}


def test_runner_token_is_read_only_with_actions_read():
    assert _release_workflow()["permissions"] == {"contents": "read", "actions": "read"}
    assert "permissions" not in _release_job()


def test_release_waits_for_ci_before_publishing():
    wait = next(step for step in _release_job()["steps"] if "run" in step)
    assert wait["name"] == "Wait for the CI run of this commit"
    assert wait["if"] == "github.event_name == 'push'"
    assert wait["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert wait["timeout-minutes"] == 30


def test_checkout_fetches_full_history():
    checkout = _steps_by_action()["actions/checkout"]
    assert checkout["with"]["fetch-depth"] == 0
    assert "ref" not in checkout["with"]


def test_app_token_step_mints_contents_write_token():
    token = _steps_by_action()["actions/create-github-app-token"]
    assert token["with"]["app_id"] == RELEASE_APP_ID
    assert token["with"]["private_key"] == RELEASE_APP_PRIVATE_KEY
    assert token["with"]["permissions"] == "contents: write"


def test_semantic_release_action_runs_pinned_plugin_chain():
    semantic_release = _steps_by_action()["cycjimmy/semantic-release-action"]
    assert semantic_release["uses"] == "cycjimmy/semantic-release-action@v4.1.0"
    with_config = semantic_release["with"]
    assert with_config["semantic_version"] == "24.2.9"
    assert with_config["extra_plugins"] == (
        "@semantic-release/changelog@6.0.3 "
        "@semantic-release/git@10.0.1 "
        "@semantic-release/exec@6.0.3 "
        "conventional-changelog-conventionalcommits@10.3.0"
    )
    assert with_config["dry_run"] == (
        "${{ github.event_name == 'workflow_dispatch' && inputs.dry_run }}"
    )
    assert semantic_release["env"]["GITHUB_TOKEN"] == "${{ steps.app_token.outputs.token }}"


def test_semantic_release_job_can_run_uv():
    assert "astral-sh/setup-uv" in _steps_by_action()
