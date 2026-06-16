"""Property-based test: fresh-deployment key-unwrap chain works w/o ENCRYPTION_MASTER_KEY.

# Feature: cloud-backup-restore, Property 3: Fresh-deployment key-unwrap chain works without ENCRYPTION_MASTER_KEY

**Validates: Requirements 16.5, 16.6, 16.7**

For any valid recovery passphrase and any artifact content:

  1. ``setup(passphrase)`` mints the escrowed BMK + BDK v1 and produces a
     Recovery Kit (the wrapped material an operator stores offline).
  2. An artifact is encrypted under the **active** Backup_Data_Key obtained via
     the seamless (``ENCRYPTION_MASTER_KEY``) path on the original deployment.
  3. A **fresh deployment** — empty DB and *no usable* ``ENCRYPTION_MASTER_KEY``
     — runs ``bootstrap(kit, passphrase, persist=False)`` to recover the BDK
     using **only** the kit + passphrase (PWK → BMK → BDK), and decrypts the
     artifact back to the original content.

The unwrap chain must succeed without the deployment master key. To prove the
fresh-deployment path never touches ``ENCRYPTION_MASTER_KEY``, the module-level
``envelope_decrypt`` used by the seamless path is patched to raise during the
bootstrap + decrypt phase; the round-trip must still succeed.

Per project PBT rules the database is mocked (a fake ``AsyncSession``) and no
storage adapters are involved. Argon2id is intentionally run with cheap KDF
parameters here so 100+ iterations complete quickly — the recorded params flow
through the kit, so bootstrap derives the PWK with the same (cheap) cost.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.keys import key_service
from app.modules.backup_restore.keys.key_service import (
    BackupKeyService,
    MIN_PASSPHRASE_LENGTH,
    backup_envelope_decrypt,
    backup_envelope_encrypt,
)
from app.modules.backup_restore.keys.passphrase_words import WORDS

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — cheap KDF keeps this fast.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@pytest.fixture(autouse=True)
def cheap_kdf(monkeypatch):
    """Override Argon2id cost so the property runs 100+ iterations quickly.

    ``default_kdf_params()`` (used by ``setup``) reads these module-level
    constants, and the resulting params are recorded in the Recovery Kit, so
    ``bootstrap`` derives the PWK with the identical (cheap) cost — the unwrap
    chain under test is unchanged, only the work factor is reduced.
    """
    monkeypatch.setattr(key_service, "ARGON2_MEMORY_KIB", 64)
    monkeypatch.setattr(key_service, "ARGON2_TIME_COST", 1)
    monkeypatch.setattr(key_service, "ARGON2_PARALLELISM", 1)


# ---------------------------------------------------------------------------
# Fake AsyncSession (DB mocked per project PBT rules)
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for a SQLAlchemy ``Result`` over key-version rows."""

    def __init__(self, versions: list):
        self._versions = versions

    def scalars(self):  # noqa: D401 - tiny shim
        return self

    def all(self):
        return list(sorted(self._versions, key=lambda v: v.version))

    def scalar_one_or_none(self):
        # The only ``scalar_one_or_none`` query exercised in this test is
        # ``get_active_bdk``'s ``where(is_active is True)`` lookup.
        active = [v for v in self._versions if getattr(v, "is_active", False)]
        return active[0] if active else None


class FakeAsyncSession:
    """In-memory fake of an ``AsyncSession`` for the key service.

    Supports the narrow surface the service uses: ``execute`` (for
    ``_load_versions`` / ``get_active_bdk``), ``add``, ``flush`` and ``refresh``.
    No real database, no event loop dependency beyond awaiting these coroutines.
    """

    def __init__(self) -> None:
        self.versions: list = []

    async def execute(self, _stmt):
        return _FakeResult(self.versions)

    def add(self, obj) -> None:
        self.versions.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj) -> None:
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Diceware-style passphrases built from the embedded word list. Joining 6-10
# words with "-" yields a phrase that passes the strength rules (length >= 16
# and a high strength score). Filter guards the lower length bound.
passphrases = (
    st.lists(st.sampled_from(WORDS), min_size=6, max_size=10)
    .map(lambda ws: "-".join(ws))
    .filter(lambda p: len(p) >= MIN_PASSPHRASE_LENGTH)
)

# Arbitrary artifact content (bytes), including empty.
contents = st.binary(min_size=0, max_size=2048)


# ---------------------------------------------------------------------------
# The async chain under test
# ---------------------------------------------------------------------------


def _no_master_key(*_args, **_kwargs):
    """Stand-in for the seamless unwrap on a box with no usable master key."""
    raise RuntimeError("ENCRYPTION_MASTER_KEY is unavailable on this deployment")


async def _run_chain(passphrase: str, content: bytes) -> None:
    # 1. Original deployment: first-run setup mints BMK + BDK v1 and the kit.
    original_db = FakeAsyncSession()
    original_svc = BackupKeyService(original_db)
    kit = await original_svc.setup(passphrase)

    # 2. Encrypt an artifact under the ACTIVE BDK via the seamless path
    #    (the original box still holds ENCRYPTION_MASTER_KEY).
    active_version, active_bdk = await original_svc.get_active_bdk()
    artifact = backup_envelope_encrypt(content, active_bdk)

    # 3. Fresh deployment: empty DB and NO usable ENCRYPTION_MASTER_KEY.
    #    Break the seamless path for the duration of the bootstrap + decrypt to
    #    prove that path is never used during recovery (Req 16.7). Restore it
    #    afterwards so the next Hypothesis example starts clean.
    original_env_decrypt = key_service.envelope_decrypt
    key_service.envelope_decrypt = _no_master_key
    try:
        fresh_db = FakeAsyncSession()
        fresh_svc = BackupKeyService(fresh_db)

        recovered_bdk = await fresh_svc.bootstrap(kit, passphrase, persist=False)

        # The recovered BDK is exactly the active BDK (Req 16.5, 16.6).
        assert recovered_bdk == active_bdk
        # persist=False writes nothing to the fresh deployment's DB.
        assert fresh_db.versions == []

        # 4. The artifact decrypts under the recovered BDK — round-trip holds
        #    with only kit + passphrase, no ENCRYPTION_MASTER_KEY (Req 16.7).
        recovered = backup_envelope_decrypt(artifact, recovered_bdk)
    finally:
        key_service.envelope_decrypt = original_env_decrypt

    assert recovered == content, (
        f"fresh-deployment round-trip mismatch: {recovered!r} != {content!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Fresh-deployment key-unwrap chain works without ENCRYPTION_MASTER_KEY
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(passphrase=passphrases, content=contents)
def test_fresh_deployment_unwrap_chain(passphrase: str, content: bytes):
    """PWK→BMK→BDK unwrap + artifact decrypt succeed from kit + passphrase alone.

    **Validates: Requirements 16.5, 16.6, 16.7**
    """
    asyncio.run(_run_chain(passphrase, content))
