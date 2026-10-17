"""Toolset registry: hier werden neue Toolsets registriert."""

import os
from collections.abc import Mapping

from fastmcp import FastMCP

from . import docx, nextcloud, pdf

TOOLSETS: dict[str, FastMCP] = {
    "pdf": pdf.mcp,
    "docx": docx.mcp,
    "nextcloud": nextcloud.mcp,
}

# Single-account environment-variable groups. Each group is all-or-none:
# a partially configured group fails server startup. Extend this tuple
# when a new toolset adds a single-account environment configuration.
ENV_VAR_GROUPS: tuple[tuple[str, ...], ...] = (nextcloud.NEXTCLOUD_ENV_VARS,)


class ToolsetConfigError(RuntimeError):
    """Raised at startup when a toolset configuration is incomplete."""


def validate_env_config(env: Mapping[str, str] | None = None) -> None:
    """Reject partial single-account configurations (each group is all or none).

    Mirrors the ``create_auth_provider`` all-or-nothing pattern per group in
    ``ENV_VAR_GROUPS``: a subset of a group's variables is a configuration
    error, an empty group disables that fallback. Called at server startup;
    ``env`` overrides the environment for tests.
    """
    env_map = os.environ if env is None else env
    for group in ENV_VAR_GROUPS:
        present = [name for name in group if env_map.get(name, "").strip()]
        if not present:
            continue
        missing = [name for name in group if not env_map.get(name, "").strip()]
        if missing:
            raise ToolsetConfigError(
                f"Incomplete toolset configuration, missing: {', '.join(missing)}. "
                f"Set all of {', '.join(group)} or none of them."
            )


__all__ = ["ENV_VAR_GROUPS", "TOOLSETS", "ToolsetConfigError", "validate_env_config"]
