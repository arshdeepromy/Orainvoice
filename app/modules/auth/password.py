"""Password hashing and verification using bcrypt directly.

Uses the ``bcrypt`` library for password hashing without the passlib
wrapper, avoiding compatibility issues with newer bcrypt releases.

Both an async and a sync API are exposed:

- ``verify_password`` / ``hash_password`` are **async** and run bcrypt
  inside ``asyncio.to_thread`` so they do not block the FastAPI event
  loop on hot paths (login / password reset / invitation accept).
  Bcrypt is intentionally CPU-expensive (~80–300 ms per call); running
  it on the event loop caps logins-per-second-per-worker to single
  digits. PERFORMANCE_AUDIT.md §B-H2 / §1 quick win #2.
- ``verify_password_sync`` / ``hash_password_sync`` are escape hatches
  for code paths that genuinely cannot be async (e.g. blocking call
  sites inside a sync helper). New code should use the async versions.
"""

import asyncio

import bcrypt


def hash_password_sync(plain: str) -> str:
    """Sync bcrypt hash. Prefer ``hash_password`` in async code."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password_sync(plain: str, hashed: str) -> bool:
    """Sync bcrypt verify. Prefer ``verify_password`` in async code."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


async def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*, off the event loop."""
    return await asyncio.to_thread(hash_password_sync, plain)


async def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` if *plain* matches *hashed*, off the event loop."""
    return await asyncio.to_thread(verify_password_sync, plain, hashed)
