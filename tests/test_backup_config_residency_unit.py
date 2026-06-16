"""Unit tests for config / residency examples and edge cases (Task 13.7).

Example-based (NOT property-based) coverage for the backup-config, residency,
dry-run schema-compatibility, and key-status logic:

  - schema-compatibility decisions older / newer / equal (and the missing /
    unrecognised refuse cases) — example pairs (Req 10.3, 10.4);
  - empty-backup listing empty-state — ``list_destinations`` empty +
    ``get_config`` defaulting (Req 9.1);
  - residency-notice derivation examples — concrete provider/config → residency
    + disclosure notice (Req 20.2, 20.8, 20.9);
  - RPO/RTO warning thresholds — ``update_config`` attaches a warning when the
    schedule interval exceeds the RPO, none when within (Req 25.2);
  - exactly-one-primary invariant on ``set_primary`` AND ``edit_destination``
    never changing ``is_primary`` (Req 30.7);
  - notification recipient resolution incl. explicit lists, the global_admin
    email fallback, and the no-recipient delivery-failure (Req 18.11);
  - key-status reporting: has_active_key / active_version / setup_complete
    (Req 16.12).

Per the project test rule the async DB session, encrypt/decrypt, and audit
writer are lightweight in-memory stand-ins (no mock framework), modelled on the
fakes in ``tests/test_backup_audit_writer_unit.py`` /
``tests/test_backup_job_lifecycle_unit.py``.
"""

from __future__ import annotations

import json
import uuid

import pytest

# Import the full set of ORM model modules so SQLAlchemy can resolve
# string-based relationship references (e.g. User → Organisation) before any
# select() statement triggers mapper configuration. Mirrors the import block in
# app/main.py / tests/test_integration_backup_restore_compat.py.
from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.admin import models as _admin_models  # noqa: F401
from app.modules.organisations import models as _org_models  # noqa: F401
from app.modules.customers import models as _customer_models  # noqa: F401
from app.modules.suppliers import models as _supplier_models  # noqa: F401
from app.modules.catalogue import models as _catalogue_models  # noqa: F401
from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
from app.modules.inventory import models as _inventory_models  # noqa: F401
from app.modules.invoices import models as _invoice_models  # noqa: F401
from app.modules.invoices import attachment_models as _invoice_attachment_models  # noqa: F401
from app.modules.vehicles import models as _vehicle_models  # noqa: F401
from app.modules.billing import models as _billing_models  # noqa: F401
from app.modules.job_cards import models as _job_card_models  # noqa: F401
from app.modules.service_types import models as _service_type_models  # noqa: F401
from app.modules.staff import models as _staff_models  # noqa: F401
from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
from app.modules.ha import models as _ha_models  # noqa: F401
from app.modules.ha import volume_sync_models as _volume_sync_models  # noqa: F401
from app.modules.stock import models as _stock_models  # noqa: F401
from app.modules.quotes import models as _quote_models  # noqa: F401
from app.modules.payments import models as _payment_models  # noqa: F401
from app.modules.platform_settings import models as _platform_settings_models  # noqa: F401
from app.modules.ledger import models as _ledger_models  # noqa: F401
from app.modules.banking import models as _banking_models  # noqa: F401
from app.modules.tax_wallets import models as _tax_wallet_models  # noqa: F401
from app.modules.ird import models as _ird_models  # noqa: F401
from app.modules.in_app_notifications import models as _in_app_notif_models  # noqa: F401
from app.modules.fleet_portal import models as _fleet_portal_models  # noqa: F401
from app.modules.notifications import models as _notif_models  # noqa: F401

from sqlalchemy.orm import configure_mappers

configure_mappers()

from app.core.encryption import envelope_encrypt
from app.modules.auth.models import User
from app.modules.auth.rbac import GLOBAL_ADMIN
from app.modules.backup_restore.config_service import (
    BackupConfigService,
    SOURCE_EXPLICIT,
    SOURCE_GLOBAL_ADMIN_FALLBACK,
    SOURCE_NONE,
)
from app.modules.backup_restore.keys.key_service import (
    BackupKeyService,
    KDF_ALGO,
    compute_kcv,
    default_kdf_params,
)
from app.modules.backup_restore.models import (
    BackupConfig,
    BackupDestination,
    BackupKeyVersion,
)
from app.modules.backup_restore.residency import (
    ONSHORE,
    OFFSHORE,
    UNKNOWN,
    build_disclosure_notice,
    derive_residency,
)
from app.modules.backup_restore.restore.dry_run import (
    COMPARE_EQUAL,
    COMPARE_MISSING,
    COMPARE_NEWER,
    COMPARE_OLDER,
    COMPARE_UNKNOWN,
    DECISION_CONFIRM_REQUIRED,
    DECISION_PROCEED,
    DECISION_REFUSED,
    compare_schema_versions,
)


# ===========================================================================
# In-memory test doubles
# ===========================================================================


class _ScalarResult:
    """Stand-in for an ``execute`` result usable as both Result and ScalarResult."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        return self._rows[0] if self._rows else None


class _NestedBegin:
    """Async context manager standing in for ``session.begin_nested()``."""

    async def __aenter__(self) -> "_NestedBegin":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _where_id(statement) -> object | None:
    """Extract the bound id from ``select(...).where(Model.id == x)``."""
    try:
        crit = list(statement._where_criteria)[0]
        return crit.right.value
    except Exception:  # pragma: no cover - defensive
        return None


class FakeConfigSession:
    """In-memory async session for ``BackupConfigService``.

    Routes ``execute`` by the selected entity: the single ``BackupConfig`` row,
    the ``BackupDestination`` list (or a single id lookup), and the
    ``select(User.email)`` global-admin fallback query.
    """

    def __init__(
        self,
        *,
        config: BackupConfig | None = None,
        destinations: list[BackupDestination] | None = None,
        admin_emails: list[str] | None = None,
    ) -> None:
        self.config = config
        self.destinations = list(destinations or [])
        self.admin_emails = list(admin_emails or [])
        self.flushes = 0
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)
        if isinstance(obj, BackupConfig):
            self.config = obj
        elif isinstance(obj, BackupDestination):
            self.destinations.append(obj)

    async def flush(self) -> None:
        self.flushes += 1

    async def refresh(self, obj: object) -> None:
        return None

    def begin_nested(self) -> _NestedBegin:
        return _NestedBegin()

    async def execute(self, statement):
        desc = statement.column_descriptions[0]
        entity = desc["entity"]
        expr = desc["expr"]

        # Column-select on User.email → the global_admin fallback query.
        if entity is User and expr is not entity:
            return _ScalarResult(self.admin_emails)

        if entity is BackupConfig:
            return _ScalarResult([self.config] if self.config is not None else [])

        if entity is BackupDestination:
            wanted = _where_id(statement)
            if wanted is not None:
                rows = [d for d in self.destinations if d.id == wanted]
            else:
                # list_destinations orders primary-first; mirror that.
                rows = sorted(self.destinations, key=lambda d: (not d.is_primary,))
            return _ScalarResult(rows)

        return _ScalarResult([])


class FakeAuditWriter:
    """Captures audit ``write_completion`` calls without touching the DB."""

    def __init__(self) -> None:
        self.completions: list[dict] = []

    async def write_completion(self, **kwargs) -> None:
        self.completions.append(kwargs)
        return None


class FakeKeySession:
    """Minimal async session answering ``select(BackupKeyVersion)`` only."""

    def __init__(self, versions: list[BackupKeyVersion] | None = None) -> None:
        self._versions = list(versions or [])

    async def execute(self, statement):
        return _ScalarResult(sorted(self._versions, key=lambda v: v.version))


def _fake_encrypt(config) -> bytes:
    return json.dumps(dict(config), default=str).encode("utf-8")


def _fake_decrypt(blob) -> dict:
    if not blob:
        return {}
    return json.loads(blob.decode("utf-8"))


def _config_service(session: FakeConfigSession) -> BackupConfigService:
    return BackupConfigService(
        session,
        encrypt_config=_fake_encrypt,
        decrypt_config=_fake_decrypt,
        audit_writer=FakeAuditWriter(),
    )


def _backup_config(**overrides) -> BackupConfig:
    """A BackupConfig with explicit Python-side defaults (server defaults do not
    apply to a transient instance)."""
    fields = {
        "id": uuid.uuid4(),
        "schedule_cron": None,
        "rpo_seconds": 86400,
        "rto_seconds": 14400,
        "webhook_url": None,
        "notification_emails": [],
        "notification_sms_numbers": [],
    }
    fields.update(overrides)
    return BackupConfig(**fields)


def _destination(is_primary: bool, *, provider_type: str = "s3") -> BackupDestination:
    return BackupDestination(
        id=uuid.uuid4(),
        provider_type=provider_type,
        display_name="dest",
        is_primary=is_primary,
    )


# ===========================================================================
# Schema-compatibility decisions: older / newer / equal (Req 10.3, 10.4)
# ===========================================================================


def test_compare_schema_equal_proceeds():
    result = compare_schema_versions("0194", "0194")
    assert result.outcome == COMPARE_EQUAL
    assert result.decision == DECISION_PROCEED
    assert result.older_schema is False
    assert result.is_blocking_incompatibility is False


def test_compare_schema_equal_by_numeric_order_when_ids_differ():
    # Same numeric order, different id strings → still equal/compatible.
    result = compare_schema_versions("194", "0194")
    assert result.outcome == COMPARE_EQUAL
    assert result.decision == DECISION_PROCEED


def test_compare_schema_older_is_warning_needing_confirmation():
    result = compare_schema_versions("0190", "0194")
    assert result.outcome == COMPARE_OLDER
    assert result.older_schema is True
    assert result.decision == DECISION_CONFIRM_REQUIRED
    # Older is NOT a hard FAIL — it surfaces the confirmation gate.
    assert result.is_blocking_incompatibility is False
    # Names both versions (Req 10.5).
    assert "0190" in result.message and "0194" in result.message


def test_compare_schema_newer_is_refused_and_blocking():
    result = compare_schema_versions("0200", "0194")
    assert result.outcome == COMPARE_NEWER
    assert result.older_schema is False
    assert result.decision == DECISION_REFUSED
    assert result.is_blocking_incompatibility is True
    assert "0200" in result.message and "0194" in result.message


def test_compare_schema_missing_version_is_refused():
    result = compare_schema_versions(None, "0194")
    assert result.outcome == COMPARE_MISSING
    assert result.decision == DECISION_REFUSED
    assert result.is_blocking_incompatibility is True


def test_compare_schema_unknown_revision_is_refused():
    result = compare_schema_versions(
        "0999", "0194", known_revisions={"0190", "0194"}
    )
    assert result.outcome == COMPARE_UNKNOWN
    assert result.decision == DECISION_REFUSED
    assert result.is_blocking_incompatibility is True


# ===========================================================================
# Empty-backup / empty-state listing (Req 9.1)
# ===========================================================================


@pytest.mark.asyncio
async def test_list_destinations_empty_when_none_configured():
    svc = _config_service(FakeConfigSession())
    assert await svc.list_destinations() == []


@pytest.mark.asyncio
async def test_get_config_creates_default_row_when_absent():
    session = FakeConfigSession()
    svc = _config_service(session)

    config = await svc.get_config()

    assert isinstance(config, BackupConfig)
    # The default row was added + flushed into the session.
    assert session.config is config
    assert session.flushes >= 1
    # A second call returns the same persisted row rather than creating another.
    again = await svc.get_config()
    assert again is config
    assert sum(isinstance(o, BackupConfig) for o in session.added) == 1


# ===========================================================================
# Residency-notice derivation examples (Req 20.2, 20.8, 20.9)
# ===========================================================================


@pytest.mark.parametrize(
    "provider, config, expected",
    [
        ("google_drive", {}, OFFSHORE),
        ("onedrive", {}, OFFSHORE),
        ("s3", {"region": "ap-southeast-6"}, ONSHORE),  # AWS Auckland (NZ)
        ("s3", {"region": "us-east-1"}, OFFSHORE),
        ("s3", {}, UNKNOWN),  # self-hosted, region undeclared (Req 20.9)
        ("nas", {}, UNKNOWN),
        ("nas", {"onshore": True}, ONSHORE),  # operator declaration
        ("s3", {"residency": "onshore"}, ONSHORE),  # explicit declaration wins
    ],
)
def test_derive_residency_examples(provider, config, expected):
    assert derive_residency(provider, config) == expected


def test_onshore_notice_has_no_offshore_warning():
    notice = build_disclosure_notice("s3", {"region": "ap-southeast-6"})
    assert notice.residency == ONSHORE
    assert notice.offshore_warning is False
    assert notice.requires_acknowledgement is False
    assert "Onshore" in notice.headline
    # Biometric clock-in-photo statement always present (Req 20.6).
    assert "clock_photos" in notice.text


def test_offshore_notice_warns_and_requires_acknowledgement():
    notice = build_disclosure_notice("google_drive", {})
    assert notice.residency == OFFSHORE
    assert notice.offshore_warning is True
    assert notice.requires_acknowledgement is True
    assert "Offshore" in notice.headline
    assert "clock_photos" in notice.text


def test_unknown_residency_is_treated_as_offshore_in_notice():
    notice = build_disclosure_notice("s3", {})  # no region → unknown
    assert notice.residency == UNKNOWN
    assert notice.offshore_warning is True
    assert notice.requires_acknowledgement is True
    assert "could not be reliably determined" in notice.body


# ===========================================================================
# RPO/RTO warning thresholds (Req 25.2)
# ===========================================================================


@pytest.mark.asyncio
async def test_update_config_attaches_rpo_warning_when_interval_exceeds_rpo():
    # Weekly schedule (worst-case ~7-day interval) against a 24 h RPO → warn.
    config = _backup_config(schedule_cron=None, rpo_seconds=86400)
    svc = _config_service(FakeConfigSession(config=config))

    result = await svc.update_config({"schedule_cron": "0 0 * * 0"})

    assert result.rpo_validation.satisfied is False
    assert result.warnings  # warning surfaced (but the save still applied)
    assert result.config.schedule_cron == "0 0 * * 0"


@pytest.mark.asyncio
async def test_update_config_no_warning_when_schedule_within_rpo():
    # Hourly schedule (1 h interval) against a 24 h RPO → no warning.
    config = _backup_config(schedule_cron=None, rpo_seconds=86400)
    svc = _config_service(FakeConfigSession(config=config))

    result = await svc.update_config({"schedule_cron": "0 * * * *"})

    assert result.rpo_validation.satisfied is True
    assert result.warnings == []


@pytest.mark.asyncio
async def test_update_config_warns_when_no_schedule_configured():
    config = _backup_config(schedule_cron=None, rpo_seconds=86400)
    svc = _config_service(FakeConfigSession(config=config))

    # Update something unrelated; with no schedule the RPO cannot be met.
    result = await svc.update_config({"rto_seconds": 7200})

    assert result.rpo_validation.satisfied is False
    assert result.warnings


# ===========================================================================
# Exactly-one-primary invariant (Req 30.7)
# ===========================================================================


@pytest.mark.asyncio
async def test_set_primary_clears_prior_and_sets_exactly_one():
    d0 = _destination(is_primary=True)
    d1 = _destination(is_primary=False)
    d2 = _destination(is_primary=False)
    session = FakeConfigSession(destinations=[d0, d1, d2])
    svc = _config_service(session)

    result = await svc.set_primary(d2.id, actor_id=uuid.uuid4())

    primaries = [d for d in result if d.is_primary]
    assert len(primaries) == 1
    assert primaries[0].id == d2.id
    # The prior primary was cleared.
    assert d0.is_primary is False
    assert d1.is_primary is False
    assert d2.is_primary is True


@pytest.mark.asyncio
async def test_edit_destination_never_changes_is_primary():
    primary = _destination(is_primary=True)
    session = FakeConfigSession(destinations=[primary])
    svc = _config_service(session)

    # Even when the payload tries to flip is_primary, it must be ignored.
    edited = await svc.edit_destination(
        primary.id,
        {"display_name": "Renamed", "is_primary": False, "config": {"region": "us-east-1"}},
        actor_id=uuid.uuid4(),
    )

    assert edited.is_primary is True  # unchanged (Req 30.7)
    assert edited.display_name == "Renamed"


@pytest.mark.asyncio
async def test_edit_destination_preserves_masked_credential():
    # Pre-store a real secret; submit the masked placeholder back unchanged.
    dest = _destination(is_primary=True)
    dest.config_encrypted = _fake_encrypt(
        {"region": "us-east-1", "secret_access_key": "REALSECRETVALUE"}
    )
    session = FakeConfigSession(destinations=[dest])
    svc = _config_service(session)

    await svc.edit_destination(
        dest.id,
        {"config": {"secret_access_key": "se****clue"}},  # masked → keep existing
        actor_id=uuid.uuid4(),
    )

    stored = _fake_decrypt(dest.config_encrypted)
    assert stored["secret_access_key"] == "REALSECRETVALUE"


# ===========================================================================
# Notification recipient resolution (Req 18.11)
# ===========================================================================


@pytest.mark.asyncio
async def test_email_recipients_use_explicit_list():
    config = _backup_config(notification_emails=["ops@example.com"])
    svc = _config_service(FakeConfigSession(config=config))

    resolution = await svc.resolve_notification_recipients("email", config=config)

    assert resolution.recipients == ["ops@example.com"]
    assert resolution.source == SOURCE_EXPLICIT
    assert resolution.delivery_failure is False


@pytest.mark.asyncio
async def test_email_recipients_fall_back_to_global_admins():
    config = _backup_config(notification_emails=[])
    session = FakeConfigSession(config=config, admin_emails=["admin@example.com"])
    svc = _config_service(session)

    resolution = await svc.resolve_notification_recipients("email", config=config)

    assert resolution.recipients == ["admin@example.com"]
    assert resolution.source == SOURCE_GLOBAL_ADMIN_FALLBACK
    assert resolution.delivery_failure is False


@pytest.mark.asyncio
async def test_email_no_recipient_is_a_delivery_failure():
    config = _backup_config(notification_emails=[])
    session = FakeConfigSession(config=config, admin_emails=[])  # no fallback either
    svc = _config_service(session)

    resolution = await svc.resolve_notification_recipients("email", config=config)

    assert resolution.recipients == []
    assert resolution.source == SOURCE_NONE
    assert resolution.delivery_failure is True
    assert resolution.reason


@pytest.mark.asyncio
async def test_sms_recipients_have_no_global_admin_fallback():
    explicit = _backup_config(notification_sms_numbers=["+6421000000"])
    svc = _config_service(FakeConfigSession(config=explicit))
    ok = await svc.resolve_notification_recipients("sms", config=explicit)
    assert ok.recipients == ["+6421000000"]
    assert ok.source == SOURCE_EXPLICIT
    assert ok.delivery_failure is False

    empty = _backup_config(notification_sms_numbers=[])
    svc2 = _config_service(FakeConfigSession(config=empty, admin_emails=["a@b.com"]))
    fail = await svc2.resolve_notification_recipients("sms", config=empty)
    assert fail.recipients == []
    assert fail.delivery_failure is True  # no SMS fallback


@pytest.mark.asyncio
async def test_webhook_recipient_resolution_and_failure():
    configured = _backup_config(webhook_url="https://hooks.example.com/x")
    svc = _config_service(FakeConfigSession(config=configured))
    ok = await svc.resolve_notification_recipients("webhook", config=configured)
    assert ok.recipients == ["https://hooks.example.com/x"]
    assert ok.delivery_failure is False

    missing = _backup_config(webhook_url=None)
    svc2 = _config_service(FakeConfigSession(config=missing))
    fail = await svc2.resolve_notification_recipients("webhook", config=missing)
    assert fail.recipients == []
    assert fail.delivery_failure is True


# ===========================================================================
# Key-status reporting (Req 16.12)
# ===========================================================================


def _active_key_version(version: int) -> BackupKeyVersion:
    """Build a usable active key version with real ``wrapped_bmk_env`` + KCV.

    ``get_key_status`` reports ``has_active_key`` only when the active
    ``wrapped_bmk_env`` unwraps under this deployment's master key AND its KCV
    verifies, so the row carries genuine envelope-encrypted material.
    """
    import os

    bmk = os.urandom(32)
    return BackupKeyVersion(
        id=uuid.uuid4(),
        version=version,
        is_active=True,
        kdf_algo=KDF_ALGO,
        kdf_params=default_kdf_params(),
        kdf_salt=os.urandom(16),
        wrapped_bmk_passphrase=b"unused-for-status",
        wrapped_bmk_env=envelope_encrypt(bmk),
        wrapped_bdk=b"unused-for-status",
        bmk_kcv=compute_kcv(bmk),
    )


@pytest.mark.asyncio
async def test_key_status_when_no_setup():
    svc = BackupKeyService(FakeKeySession(versions=[]))
    status = await svc.get_key_status()
    assert status == {
        "has_active_key": False,
        "active_version": None,
        "setup_complete": False,
    }


@pytest.mark.asyncio
async def test_key_status_reports_usable_active_key():
    version = _active_key_version(3)
    svc = BackupKeyService(FakeKeySession(versions=[version]))

    status = await svc.get_key_status()

    assert status["setup_complete"] is True
    assert status["has_active_key"] is True
    assert status["active_version"] == 3


@pytest.mark.asyncio
async def test_key_status_active_key_present_but_unusable_master_key():
    # A surviving DB row whose wrapped_bmk_env cannot be unwrapped on this box
    # (e.g. a fresh deployment that lost ENCRYPTION_MASTER_KEY) → not usable.
    import os

    unusable = BackupKeyVersion(
        id=uuid.uuid4(),
        version=1,
        is_active=True,
        kdf_algo=KDF_ALGO,
        kdf_params=default_kdf_params(),
        kdf_salt=os.urandom(16),
        wrapped_bmk_passphrase=b"x",
        wrapped_bmk_env=b"\x00\x00\x00\x10garbage-not-decryptable",
        wrapped_bdk=b"x",
        bmk_kcv=b"x",
    )
    svc = BackupKeyService(FakeKeySession(versions=[unusable]))

    status = await svc.get_key_status()

    assert status["setup_complete"] is True  # a row exists
    assert status["has_active_key"] is False  # but it is not usable here
    assert status["active_version"] is None
