"""Property-based tests for rsync configuration validation.

Feature: file-storage-replication, Property 5: Rsync configuration validation

For any rsync configuration request, if the ``standby_ssh_host`` is empty
the request SHALL be rejected, and if the ``sync_interval_minutes`` is
outside the range [1, 1440] the request SHALL be rejected. Configurations
with non-empty host and valid interval SHALL be accepted.

**Validates: Requirement 4.2**

Uses Hypothesis to generate random config values (empty/non-empty hosts,
intervals from -100 to 2000), then verifies validation behaviour of
``VolumeSyncService.save_config()`` against a real database.
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings as app_settings

# Import ORM models so SQLAlchemy can resolve relationships
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.branding import models as _branding_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401

from app.modules.ha.volume_sync_schemas import VolumeSyncConfigRequest
from app.modules.ha.volume_sync_service import VolumeSyncService

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Empty host strategies: empty string, whitespace-only strings
empty_host_strategy = st.one_of(
    st.just(""),
    st.text(alphabet=" \t\n\r", min_size=1, max_size=10),
)

# Non-empty host strategies: realistic hostnames / IPs
non_empty_host_strategy = st.one_of(
    st.from_regex(r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}", fullmatch=True),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            min_codepoint=48,
            max_codepoint=122,
        ),
        min_size=1,
        max_size=50,
    ).filter(lambda s: s.strip() != ""),
)

# Interval strategies covering invalid and valid ranges
invalid_low_interval_strategy = st.integers(min_value=-100, max_value=0)
invalid_high_interval_strategy = st.integers(min_value=1441, max_value=2000)
invalid_interval_strategy = st.one_of(
    invalid_low_interval_strategy,
    invalid_high_interval_strategy,
)
valid_interval_strategy = st.integers(min_value=1, max_value=1440)

# SSH port and key path (valid defaults for all tests)
ssh_port_strategy = st.integers(min_value=1, max_value=65535)
ssh_key_path_strategy = st.just("/root/.ssh/id_rsa")


# ---------------------------------------------------------------------------
# Per-test engine/session factory
# ---------------------------------------------------------------------------

async def _make_session() -> tuple[AsyncSession, object]:
    """Create a fresh engine + session for each test run."""
    test_engine = create_async_engine(
        app_settings.database_url,
        echo=False,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
    )
    factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False,
    )
    session = factory()
    return session, test_engine


async def _cleanup_config(session: AsyncSession) -> None:
    """Delete all test config rows."""
    await session.execute(text("DELETE FROM volume_sync_config"))
    await session.commit()


# ---------------------------------------------------------------------------
# Property 5: Rsync configuration validation
# Feature: file-storage-replication, Property 5: Rsync configuration validation
# **Validates: Requirement 4.2**
# ---------------------------------------------------------------------------


class TestRsyncConfigValidationProperty:
    """Property 5 — For any rsync configuration request, if the
    standby_ssh_host is empty the request SHALL be rejected, and if
    the sync_interval_minutes is outside the range [1, 1440] the
    request SHALL be rejected. Configurations with non-empty host
    and valid interval SHALL be accepted."""

    @PBT_SETTINGS
    @given(
        host=empty_host_strategy,
        interval=valid_interval_strategy,
        ssh_port=ssh_port_strategy,
    )
    def test_empty_host_rejected(self, host, interval, ssh_port):
        """Configurations with empty or whitespace-only hosts SHALL be
        rejected with ValueError.

        **Validates: Requirement 4.2**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            try:
                async with session.begin():
                    await _cleanup_config(session)

                req = VolumeSyncConfigRequest(
                    standby_ssh_host=host,
                    ssh_port=ssh_port,
                    ssh_key_path="/root/.ssh/id_rsa",
                    sync_interval_minutes=interval,
                    enabled=False,
                )

                svc = VolumeSyncService()

                async with session.begin():
                    with pytest.raises(ValueError, match="standby_ssh_host"):
                        await svc.save_config(session, req)

            finally:
                try:
                    async with session.begin():
                        await _cleanup_config(session)
                except Exception:
                    pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())

    @PBT_SETTINGS
    @given(
        host=non_empty_host_strategy,
        interval=invalid_interval_strategy,
        ssh_port=ssh_port_strategy,
    )
    def test_invalid_interval_rejected(self, host, interval, ssh_port):
        """Configurations with sync_interval_minutes outside [1, 1440]
        SHALL be rejected with ValueError.

        **Validates: Requirement 4.2**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            try:
                async with session.begin():
                    await _cleanup_config(session)

                # Build the request manually to bypass Pydantic's own
                # ge/le validation — we want to test the service layer.
                req = VolumeSyncConfigRequest.model_construct(
                    standby_ssh_host=host,
                    ssh_port=ssh_port,
                    ssh_key_path="/root/.ssh/id_rsa",
                    remote_upload_path="/app/uploads/",
                    remote_compliance_path="/app/compliance_files/",
                    sync_interval_minutes=interval,
                    enabled=False,
                )

                svc = VolumeSyncService()

                async with session.begin():
                    with pytest.raises(ValueError, match="sync_interval_minutes"):
                        await svc.save_config(session, req)

            finally:
                try:
                    async with session.begin():
                        await _cleanup_config(session)
                except Exception:
                    pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())

    @PBT_SETTINGS
    @given(
        host=non_empty_host_strategy,
        interval=valid_interval_strategy,
        ssh_port=ssh_port_strategy,
    )
    def test_valid_config_accepted_and_persisted(self, host, interval, ssh_port):
        """Configurations with non-empty host and valid interval SHALL
        be accepted and persisted to the database.

        **Validates: Requirement 4.2**
        """
        import asyncio

        async def _run():
            session, engine = await _make_session()
            try:
                async with session.begin():
                    await _cleanup_config(session)

                req = VolumeSyncConfigRequest(
                    standby_ssh_host=host,
                    ssh_port=ssh_port,
                    ssh_key_path="/root/.ssh/id_rsa",
                    sync_interval_minutes=interval,
                    enabled=False,
                )

                svc = VolumeSyncService()

                async with session.begin():
                    cfg = await svc.save_config(session, req)

                    # Config should be returned with correct values
                    assert cfg is not None, "save_config returned None"
                    assert cfg.standby_ssh_host == host.strip(), (
                        f"Host mismatch: expected {host.strip()!r}, "
                        f"got {cfg.standby_ssh_host!r}"
                    )
                    assert cfg.sync_interval_minutes == interval, (
                        f"Interval mismatch: expected {interval}, "
                        f"got {cfg.sync_interval_minutes}"
                    )
                    assert cfg.ssh_port == ssh_port, (
                        f"Port mismatch: expected {ssh_port}, "
                        f"got {cfg.ssh_port}"
                    )

                # Verify persistence: read back from DB in a new transaction
                async with session.begin():
                    persisted = await svc.get_config(session)
                    assert persisted is not None, (
                        "Config not found in DB after save"
                    )
                    assert persisted.standby_ssh_host == host.strip()
                    assert persisted.sync_interval_minutes == interval

            finally:
                try:
                    async with session.begin():
                        await _cleanup_config(session)
                except Exception:
                    pass
                await session.close()
                await engine.dispose()

        asyncio.get_event_loop().run_until_complete(_run())
