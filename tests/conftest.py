"""Shared fixtures for the assistant-mcp test suite."""

import pytest
from fastmcp.server.auth import TokenVerifier

from assistant_mcp.auth import OAUTH_ENV_VARS


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
