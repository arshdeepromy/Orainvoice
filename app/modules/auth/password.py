"""Password hashing and verification using bcrypt directly.

Uses the ``bcrypt`` library for password hashing without the passlib
wrapper, avoiding compatibility issues with newer bcrypt releases.
"""

import bcrypt


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches the bcrypt *hashed* value."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
