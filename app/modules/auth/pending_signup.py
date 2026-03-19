"""Pending signup storage in Redis.

Stores validated signup form data in Redis while the user completes
Stripe payment.  Each pending signup has a 30-minute TTL and an email
index key so we can enforce one-pending-signup-per-email.

Redis keys
----------
- ``pending_signup:{uuid}``  – JSON blob with form data + password hash
- ``pending_email:{sha256(email)}`` – maps to the ``pending_signup_id``
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid

from app.core.redis import redis_pool
from app.modules.auth.password import hash_password

logger = logging.getLogger(__name__)

PENDING_SIGNUP_TTL = 1800  # 30 minutes


def _signup_key(pending_id: str) -> str:
    return f"pending_signup:{pending_id}"


def _email_index_key(email: str) -> str:
    digest = hashlib.sha256(email.lower().strip().encode()).hexdigest()
    return f"pending_email:{digest}"


async def create_pending_signup(data: dict) -> str:
    """Store a pending signup in Redis and return the generated ID.

    The plaintext ``password`` field is hashed with bcrypt before storage.
    Both the signup key and the email index key share the same TTL.
    """
    pending_id = str(uuid.uuid4())

    # Hash password before storing
    stored = dict(data)
    if "password" in stored:
        stored["password_hash"] = hash_password(stored.pop("password"))

    payload = json.dumps(stored, default=str)

    pipe = redis_pool.pipeline()
    pipe.setex(_signup_key(pending_id), PENDING_SIGNUP_TTL, payload)
    pipe.setex(_email_index_key(stored["admin_email"]), PENDING_SIGNUP_TTL, pending_id)
    await pipe.execute()

    logger.info("Created pending signup %s for %s", pending_id, stored["admin_email"])
    return pending_id


async def get_pending_signup(pending_signup_id: str) -> dict | None:
    """Retrieve a pending signup from Redis, or ``None`` if expired/missing."""
    raw = await redis_pool.get(_signup_key(pending_signup_id))
    if raw is None:
        return None
    return json.loads(raw)


async def delete_pending_signup(pending_signup_id: str) -> None:
    """Delete both the signup key and its email index key from Redis."""
    data = await get_pending_signup(pending_signup_id)
    keys_to_delete = [_signup_key(pending_signup_id)]
    if data and "admin_email" in data:
        keys_to_delete.append(_email_index_key(data["admin_email"]))
    await redis_pool.delete(*keys_to_delete)
    logger.info("Deleted pending signup %s", pending_signup_id)


async def replace_pending_signup_for_email(email: str, data: dict) -> str:
    """Replace any existing pending signup for *email* and create a new one.

    Looks up the email index to find an existing pending signup.  If one
    exists it is deleted first, then a fresh signup is created.
    """
    existing_id = await redis_pool.get(_email_index_key(email))
    if existing_id:
        logger.info("Replacing existing pending signup %s for %s", existing_id, email)
        await delete_pending_signup(existing_id)

    return await create_pending_signup(data)
