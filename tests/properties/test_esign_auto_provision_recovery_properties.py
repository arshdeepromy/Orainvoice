"""Property-based test: failed auto-provisioning never leaves a broken state
and preserves the manual path (task 14.11).

The function under test is
:func:`app.modules.esignatures.connection_service.auto_provision_connection`. It
orchestrates the optional :class:`ProvisioningAdapter`
(``create_team`` → ``mint_team_token`` → ``ensure_webhook``), persisting
progress at each step, then runs the connection test to set ``is_verified``.
On **any** failure at **any** step (a ``ProvisioningError`` *or* an arbitrary
exception) it must catch the failure, return a humanized ``{status: 'partial'}``
result **without raising**, preserve whatever artefacts succeeded before the
failure, leave the connection row valid + manually-completable
(``is_verified=False``), and never corrupt or block the manual save/test path.

# Feature: esignature-integration, Property 28: Failed auto-provisioning never leaves a broken state and preserves the manual path

**Validates: Requirements 20.3, 20.4 (and 20.1/20.5 as applicable)**

Property 28: for an adapter that fails at ANY step, raising a
``ProvisioningError`` or an arbitrary exception —

  * ``auto_provision_connection`` does **not** raise (returns a result dict);
  * ``status == 'partial'`` with a humanized, non-empty error + code
    ``auto_provision_failed`` that leaks no raw internals;
  * artefacts created BEFORE the failing step are persisted (team id retained
    when the failure is after ``create_team``; token retained when it is after
    ``mint_team_token``) and nothing later is set;
  * the connection row stays valid/manually-completable (``is_verified`` False;
    a masked connection is returned with no plaintext secrets);
  * the manual path is preserved — the same row can still be saved and tested.

Plus controls: a fully-successful adapter → ``provisioned``; mode off →
``unavailable``.

Reuses the lightweight fakes from ``tests/test_esign_auto_provision_unit.py``
(task 14.9): a recording adapter, a routing fake async session, and real
envelope encryption — no real DB or Documenso. The model graph is pre-loaded
via ``app.main`` so SQLAlchemy can resolve the ``Organisation`` mapper the
service queries.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Import the full app so SQLAlchemy can configure the Organisation mapper (its
# relationships reference models registered only once the whole graph imports).
# The service queries Organisation by id.
import app.main  # noqa: F401,E402

from app.core.encryption import envelope_decrypt_str  # noqa: E402
from app.integrations.documenso_provisioning import (  # noqa: E402
    ProvisionedTeam,
    ProvisionedToken,
    ProvisioningError,
)
from app.modules.esignatures import connection_service as cs  # noqa: E402
from app.modules.esignatures.errors import (  # noqa: E402
    CODE_AUTO_PROVISION_FAILED,
    CODE_AUTO_PROVISION_UNAVAILABLE,
)
from app.modules.esignatures.models import EsignOrgConnection  # noqa: E402

PBT_SETTINGS = settings(max_examples=120, deadline=None)

#: A distinctive marker embedded in every raw adapter failure so the test can
#: assert it NEVER appears in the humanized error message returned to callers.
RAW_LEAK_MARKER = "RAW_INTERNAL_LEAK_MARKER_xyzzy"

#: The team id / token the recording adapter returns on a successful step.
TEAM_ID = "team-xyz"
RAW_TOKEN = "raw-token-123"

#: The provisioning steps and exception classes the property ranges over.
FAIL_STEPS = ("create_team", "mint_team_token", "ensure_webhook")
EXC_TYPES = (ProvisioningError, RuntimeError)


# ---------------------------------------------------------------------------
# Fakes (mirrors tests/test_esign_auto_provision_unit.py — task 14.9)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Routes ``execute`` to the connection row or org row by target table."""

    def __init__(self, conn_row, org_row):
        self.conn_row = conn_row
        self.org_row = org_row
        self.added: list = []

    async def execute(self, stmt):
        text = str(stmt)
        if "esign_org_connections" in text:
            return _FakeResult(self.conn_row)
        if "organisations" in text:
            return _FakeResult(self.org_row)
        return _FakeResult(None)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        if isinstance(obj, EsignOrgConnection):
            self.conn_row = obj

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def refresh(self, _obj):
        return None


class _FailingAdapter:
    """Recording adapter that fails at ``fail_on`` raising ``exc_type``.

    Steps that run before ``fail_on`` succeed and return their artefacts so the
    test can assert that earlier progress is persisted; the failing step raises
    an exception carrying :data:`RAW_LEAK_MARKER` so leak-freedom is checkable.
    """

    def __init__(self, *, fail_on: str, exc_type: type[BaseException]):
        self.calls: list = []
        self._fail_on = fail_on
        self._exc_type = exc_type

    def _boom(self, step: str):
        raise self._exc_type(f"{RAW_LEAK_MARKER} at {step}")

    async def create_team(self, *, org):
        self.calls.append("create_team")
        if self._fail_on == "create_team":
            self._boom("create_team")
        return ProvisionedTeam(team_id=TEAM_ID)

    async def mint_team_token(self, *, team_id):
        self.calls.append(("mint_team_token", team_id))
        if self._fail_on == "mint_team_token":
            self._boom("mint_team_token")
        return ProvisionedToken(token=RAW_TOKEN)

    async def ensure_webhook(self, *, team_id, routing_url, secret):
        self.calls.append(("ensure_webhook", team_id, routing_url, secret))
        if self._fail_on == "ensure_webhook":
            self._boom("ensure_webhook")


class _SuccessAdapter:
    """Recording adapter where every step succeeds (control case)."""

    def __init__(self) -> None:
        self.calls: list = []

    async def create_team(self, *, org):
        self.calls.append("create_team")
        return ProvisionedTeam(team_id=TEAM_ID)

    async def mint_team_token(self, *, team_id):
        self.calls.append(("mint_team_token", team_id))
        return ProvisionedToken(token=RAW_TOKEN)

    async def ensure_webhook(self, *, team_id, routing_url, secret):
        self.calls.append(("ensure_webhook", team_id, routing_url, secret))


def _org():
    return SimpleNamespace(id=uuid.uuid4(), name="Acme Ltd", slug="acme")


@pytest.fixture(autouse=True)
def _no_audit(monkeypatch):
    """Stub the audit writer (it does not self-guard) for every example."""

    async def _noop(**_kwargs):
        return None

    monkeypatch.setattr(cs, "write_audit_log", _noop)


# ---------------------------------------------------------------------------
# Property 28 — failure at any step recovers to a manually-completable state
# ---------------------------------------------------------------------------


class TestFailedAutoProvisionRecovers:
    """Property 28: a failure at any step never leaves a broken state.

    **Validates: Requirements 20.3, 20.4**
    """

    @PBT_SETTINGS
    @given(
        fail_on=st.sampled_from(FAIL_STEPS),
        exc_type=st.sampled_from(EXC_TYPES),
        pre_existing=st.booleans(),
    )
    def test_failure_preserves_partial_state_and_manual_path(
        self, fail_on: str, exc_type: type[BaseException], pre_existing: bool
    ):
        org_id = uuid.uuid4()
        # Optionally start from a prior partial run (a bare row with only the
        # routing id), exercising the re-runnable / reuse path too.
        conn_row = None
        if pre_existing:
            conn_row = EsignOrgConnection(
                id=uuid.uuid4(),
                org_id=org_id,
                base_url="",
                documenso_team_id=None,
                service_token_encrypted=None,
                webhook_secret_encrypted=None,
                webhook_routing_id="route-prior",
                is_verified=False,
            )
        session = _FakeSession(conn_row=conn_row, org_row=_org())
        adapter = _FailingAdapter(fail_on=fail_on, exc_type=exc_type)

        with mock.patch.object(cs, "get_provisioning_adapter", lambda: adapter):
            # Must NOT raise — any failure is caught and humanized.
            result = asyncio.run(cs.auto_provision_connection(session, org_id))

        # Returns a result dict, partial status, humanized leak-free error.
        assert isinstance(result, dict)
        assert result["status"] == "partial"
        assert result["code"] == CODE_AUTO_PROVISION_FAILED
        assert isinstance(result["error"], str) and result["error"]
        assert RAW_LEAK_MARKER not in result["error"]

        row = session.conn_row
        assert row is not None  # the row exists (manually completable)
        assert row.is_verified is False  # never verified on failure

        # Artefacts created BEFORE the failing step are persisted; nothing later.
        if fail_on == "create_team":
            assert row.documenso_team_id is None
            assert row.service_token_encrypted is None
            assert row.webhook_secret_encrypted is None
        elif fail_on == "mint_team_token":
            assert row.documenso_team_id == TEAM_ID
            assert row.service_token_encrypted is None
            assert row.webhook_secret_encrypted is None
        else:  # ensure_webhook
            assert row.documenso_team_id == TEAM_ID
            assert row.service_token_encrypted is not None
            assert envelope_decrypt_str(row.service_token_encrypted) == RAW_TOKEN
            assert row.webhook_secret_encrypted is None

        # A masked connection is returned with NO plaintext secrets.
        conn = result["connection"]
        assert conn is not None
        assert "service_token_last4" in conn
        assert "webhook_secret_last4" in conn
        assert "service_token" not in conn
        assert "webhook_secret" not in conn
        assert "service_token_encrypted" not in conn

        # The manual path is preserved: the same row can still be saved/edited
        # (manual completion) and then tested — neither corrupted nor blocked.
        async def _async_true():
            return True

        def _fake_for_org(_conn, _http):
            # ``for_org`` is a synchronous factory returning a client whose
            # ``test_connection`` is awaited by the service.
            return SimpleNamespace(test_connection=_async_true)

        with mock.patch.object(cs.DocumensoClient, "for_org", _fake_for_org):
            saved = asyncio.run(
                cs.save_connection(
                    session,
                    org_id,
                    base_url="https://documenso.example.test",
                    documenso_team_id=row.documenso_team_id or "team-manual",
                    service_token="manual-token-final",
                    webhook_signing_secret="manual-whsec-final",
                )
            )
            tested = asyncio.run(cs.test_connection(session, org_id))

        assert saved["base_url"] == "https://documenso.example.test"
        assert "service_token" not in saved  # manual save also masks
        assert tested["is_verified"] is True  # manual test path works end-to-end


# ---------------------------------------------------------------------------
# Controls — full success → 'provisioned'; mode off → 'unavailable'
# ---------------------------------------------------------------------------


class TestAutoProvisionControls:
    """Controls proving the partial path is reached ONLY on failure.

    **Validates: Requirements 20.1, 20.5**
    """

    @settings(max_examples=25, deadline=None)
    @given(pre_existing=st.booleans())
    def test_full_success_is_provisioned(self, pre_existing: bool):
        org_id = uuid.uuid4()
        conn_row = None
        if pre_existing:
            conn_row = EsignOrgConnection(
                id=uuid.uuid4(),
                org_id=org_id,
                base_url="",
                documenso_team_id=None,
                service_token_encrypted=None,
                webhook_secret_encrypted=None,
                webhook_routing_id="route-prior",
                is_verified=False,
            )
        session = _FakeSession(conn_row=conn_row, org_row=_org())
        adapter = _SuccessAdapter()

        async def _fake_test_connection(db, oid, **_kwargs):
            return {"is_verified": True, "valid": True}

        with mock.patch.object(
            cs, "get_provisioning_adapter", lambda: adapter
        ), mock.patch.object(cs, "test_connection", _fake_test_connection):
            result = asyncio.run(cs.auto_provision_connection(session, org_id))

        assert result["status"] == "provisioned"
        assert result["error"] is None
        assert result["is_verified"] is True
        row = session.conn_row
        assert row.documenso_team_id == TEAM_ID
        assert envelope_decrypt_str(row.service_token_encrypted) == RAW_TOKEN
        assert row.webhook_secret_encrypted is not None

    @settings(max_examples=25, deadline=None)
    @given(pre_existing=st.booleans())
    def test_mode_off_is_unavailable(self, pre_existing: bool):
        org_id = uuid.uuid4()
        conn_row = None
        if pre_existing:
            conn_row = EsignOrgConnection(
                id=uuid.uuid4(),
                org_id=org_id,
                base_url="https://documenso.example.test",
                documenso_team_id="team-prior",
                service_token_encrypted=None,
                webhook_secret_encrypted=None,
                webhook_routing_id="route-prior",
                is_verified=False,
            )
        session = _FakeSession(conn_row=conn_row, org_row=_org())

        with mock.patch.object(cs, "get_provisioning_adapter", lambda: None):
            result = asyncio.run(cs.auto_provision_connection(session, org_id))

        assert result["status"] == "unavailable"
        assert result["code"] == CODE_AUTO_PROVISION_UNAVAILABLE
        assert result["error"]
        # No adapter ran; an existing row (if any) is left intact for manual use.
        if pre_existing:
            assert result["connection"] is not None
        else:
            assert result["connection"] is None
