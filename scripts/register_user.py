"""Register a user for shared-secret bearer authentication.

Generates a random secret, writes the hash-only user record (and the
user-id index entry) to Google Firestore's (default) database, and prints
the secret exactly once. Re-registering an existing user id replaces the
record, so the previous secret stops authorizing after the auth cache
expires. A lost secret cannot be recovered; re-register the user instead.

Dev/admin script; not part of the shipped package. Requires Application
Default Credentials for Firestore. Run from the repo root:
uv run python scripts/register_user.py --user-id <id> [--label <text>]
"""

import argparse
import asyncio
import secrets
from collections.abc import Sequence
from datetime import UTC, datetime

from key_value.aio.protocols import AsyncKeyValue

from assistant_mcp.auth import (
    UserIndexEntry,
    UserRecord,
    build_user_index_store,
    build_user_record_store,
    secret_hash,
)


async def register_user(
    user_id: str,
    label: str | None,
    backend: AsyncKeyValue | None = None,
) -> str:
    """Register a user and print the generated secret exactly once.

    A previous registration of the same user id is replaced: its hash-keyed
    record is deleted before the new one is written, so the old secret stops
    authorizing once the auth cache has expired. ``backend`` overrides the
    Firestore default for tests. Returns the generated secret.
    """
    resolved_label = user_id if label is None else label
    records = build_user_record_store(backend=backend)
    index = build_user_index_store(backend=backend)
    secret = secrets.token_urlsafe(32)
    digest = secret_hash(secret)
    previous = await index.get(key=user_id)
    if previous is not None:
        await records.delete(key=previous.secret_hash)
    await records.put(
        key=digest,
        value=UserRecord(
            user_id=user_id,
            label=resolved_label,
            created_at=datetime.now(UTC),
        ),
    )
    await index.put(key=user_id, value=UserIndexEntry(secret_hash=digest))
    print(f"Shared secret for user {user_id!r} (label {resolved_label!r}):")
    print(secret)
    print(
        "WARNING: this secret cannot be displayed again. "
        "If it is lost, re-register the user to issue a new one."
    )
    return secret


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Register a user for shared-secret bearer authentication.",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="id of the user to register; re-registering replaces the record",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="display label for the user; defaults to the user id",
    )
    return parser.parse_args(argv)


async def main(argv: Sequence[str] | None = None, backend: AsyncKeyValue | None = None) -> str:
    """Run the registration CLI; returns the generated secret."""
    args = parse_args(argv)
    return await register_user(args.user_id, args.label, backend=backend)


if __name__ == "__main__":
    asyncio.run(main())
