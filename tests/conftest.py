"""Shared fixtures for the assistant-mcp test suite."""

import os

import pytest
from fastmcp.server.auth import TokenVerifier

from assistant_mcp.auth import OAUTH_ENV_VARS


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    """Turn skips into failures when FORBID_SKIPPED_TESTS is set (CI in-image run)."""
    report = yield
    if (
        os.environ.get("FORBID_SKIPPED_TESTS")
        and report.skipped
        and not hasattr(report, "wasxfail")
    ):
        report.outcome = "failed"
        report.longrepr = (
            "Skipped tests fail when FORBID_SKIPPED_TESTS is set "
            f"(skip reason: {report.longrepr})"
        )
    return report


class RejectingTokenVerifier(TokenVerifier):
    """Rejects every token, so any authenticated route must refuse requests."""

    async def verify_token(self, token: str) -> None:
        return None


@pytest.fixture
def rejecting_token_verifier() -> RejectingTokenVerifier:
    return RejectingTokenVerifier()


@pytest.fixture
def cleared_oauth_env(monkeypatch) -> None:
    """Ensure no OAuth activation variables are set for the test."""
    for name in OAUTH_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return None
