"""Bug 3 condition exploration test — invitation URL uses ``localhost:5173``.

Spec: ``.kiro/specs/email-delivery-visibility-fixes`` — Phase 0 task 5.

Bug 3 of the bugfix is that several email-link sites build URLs from
``settings.frontend_base_url`` (which defaults to ``http://localhost:5173``
per ``app/config.py`` L40) regardless of the request's ``Origin`` header.
The defective sites are:

  - ``POST /api/v1/org/users/invite`` (org user invitation)
  - ``POST /api/v1/admin/organisations`` (Global Admin provisions org)
  - ``POST /api/v1/auth/password/reset-request`` (password reset)
  - ``POST /api/v1/customers/{customer_id}/send-portal-link`` (portal link)

This file pins the post-fix contract via four sub-tests, all bundled
into one test class ``TestBug3OriginNotPropagated`` per the spec.

**Patch strategy.** Each sub-test mounts only the router under test
(behind a thin ``inject_auth`` middleware that stamps ``request.state``
with the role/org/user identifiers ``require_role`` needs) and patches
the immediate downstream service the router calls — i.e.
``invite_org_user``, ``provision_organisation``,
``request_password_reset``, ``send_portal_link``. This surfaces the bug
at exactly the layer where it sits (the router not extracting
``Origin``) without needing to mock the full DB / Redis / email-sender
chain underneath. The captured ``base_url`` kwarg is the value that
would later flow into the email body's URL builder, so synthesising
``f"{base_url}/verify-email?token=stub"`` and asserting the host
matches ``Origin`` is equivalent to inspecting the final URL.

**On UNFIXED code:** all four sub-tests FAIL — the routers never
extract Origin and never pass ``base_url`` to the service.

**On FIXED code:** all four sub-tests PASS.

Validates: Requirements 2.5, 2.6, 2.7, 2.9
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

# Import models so SQLAlchemy can resolve relationships at import time.
import app.modules.admin.models  # noqa: F401
import app.modules.auth.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401

from app.core.database import get_db_session


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _empty_db() -> AsyncMock:
    """AsyncSession-shaped mock used as the dependency-override return
    value. The downstream service the router calls is patched out, so
    the DB never actually gets read for the assertions in this file —
    but FastAPI still needs a session to hand to the route.
    """
    db = AsyncMock()
    empty_result = MagicMock()
    empty_result.scalar_one_or_none.return_value = None
    empty_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=empty_result)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _override_db():
    return _empty_db()


def _build_app(
    *,
    role: str | None,
    org_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    routers: list[tuple[object, str]],
) -> FastAPI:
    """Mount the supplied routers behind a middleware that stamps
    ``request.state`` so ``require_role`` passes without the real auth
    pipeline (mirrors the helper in
    ``tests/test_email_providers_webhook_secret.py``).
    """
    app = FastAPI()

    @app.middleware("http")
    async def inject_auth(request: Request, call_next):
        request.state.user_id = str(user_id) if user_id else None
        request.state.org_id = str(org_id) if org_id else None
        request.state.role = role
        request.state.email = "test@example.com"
        request.state.client_ip = "127.0.0.1"
        return await call_next(request)

    for router, prefix in routers:
        app.include_router(router, prefix=prefix)

    app.dependency_overrides[get_db_session] = _override_db
    return app


def _origin_host_matches(captured_base_url: str | None, origin: str) -> bool:
    """The router fix must pass ``base_url=origin`` (or a value built
    from origin's scheme+host) through to the downstream service. We
    simulate the email body URL with a stub token and assert the
    final URL begins with the Origin host.
    """
    if not captured_base_url:
        return False
    return captured_base_url.rstrip("/").lower().startswith(
        origin.rstrip("/").lower()
    )



# ---------------------------------------------------------------------------
# Bug 3 condition exploration tests — UNFIXED code: all four FAIL
# ---------------------------------------------------------------------------


class TestBug3OriginNotPropagated:
    """Bug 3 condition exploration — the four defective email-link
    routers do not propagate the request ``Origin`` header to the
    underlying service, so the URL embedded in the email body is
    built from ``settings.frontend_base_url`` (= ``localhost:5173``).

    UNFIXED OUTCOME: all four sub-tests FAIL — failure confirms the
    bug exists.

    Validates: Requirements 2.5, 2.6, 2.7, 2.9
    """

    # ------------------------------------------------------------------
    # Sub-test A — POST /api/v1/org/users/invite (Bug 3 site #1)
    # ------------------------------------------------------------------

    def test_org_user_invite_url_uses_request_origin(self):
        """``POST /api/v1/org/users/invite`` with
        ``Origin: https://devin.oraflows.co.nz`` must result in an
        invitation email whose embedded URL begins with that origin.

        UNFIXED OUTCOME: FAIL. ``invite_user``
        (``app/modules/organisations/router.py`` ~L921) doesn't read
        ``request.headers["origin"]`` and doesn't pass ``base_url`` to
        ``invite_org_user``; the downstream ``create_invitation``
        therefore falls through to ``settings.frontend_base_url``.

        Validates: Requirement 2.5
        """
        from app.modules.organisations.router import router as org_router

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        origin = "https://devin.oraflows.co.nz"

        # AsyncMock returns an OrgUserResponse-shaped dict so the router
        # can assemble its 201 response without erroring.
        invite_stub = AsyncMock(
            return_value={
                "id": str(uuid.uuid4()),
                "email": "u@example.com",
                "role": "salesperson",
                "is_active": True,
                "is_email_verified": False,
                "last_login_at": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        app = _build_app(
            role="org_admin",
            org_id=org_id,
            user_id=user_id,
            routers=[(org_router, "/api/v1/org")],
        )

        with patch(
            "app.modules.organisations.router.invite_org_user",
            new=invite_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/org/users/invite",
                json={"email": "u@example.com", "role": "salesperson"},
                headers={"origin": origin},
            )

        assert resp.status_code == 201, resp.text
        invite_stub.assert_awaited_once()
        kwargs = invite_stub.await_args.kwargs

        # The fix must extract Origin in the router and pass it as
        # ``base_url`` to ``invite_org_user``. ``base_url`` is the
        # string concatenated with ``/verify-email?token=…`` to build
        # the URL the recipient sees in their inbox — capturing it
        # here is equivalent to inspecting the final URL.
        captured_base_url = kwargs.get("base_url")
        simulated_invite_url = (
            f"{(captured_base_url or '').rstrip('/')}/verify-email?token=stub"
        )

        assert simulated_invite_url.startswith(
            f"{origin.rstrip('/')}/verify-email?token="
        ), (
            "POST /api/v1/org/users/invite must build the invitation "
            "email URL from the request Origin header, not from "
            "settings.frontend_base_url. Captured base_url = "
            f"{captured_base_url!r}; resulting invite URL = "
            f"{simulated_invite_url!r}; expected to start with "
            f"{origin}/verify-email?token=."
        )

    # ------------------------------------------------------------------
    # Sub-test B — POST /api/v1/admin/organisations (Bug 3 site #2)
    # ------------------------------------------------------------------

    def test_admin_provision_org_invitation_url_uses_request_origin(self):
        """``POST /api/v1/admin/organisations`` with
        ``Origin: https://example.com`` must result in the org-admin
        invitation email whose URL host = ``example.com``.

        UNFIXED OUTCOME: FAIL. ``create_organisation``
        (``app/modules/admin/router.py``) doesn't extract Origin and
        doesn't pass ``base_url`` to ``provision_organisation``;
        ``provision_organisation`` doesn't accept ``base_url`` either,
        so ``_send_org_admin_invitation_email`` (~L353) falls through
        to ``settings.frontend_base_url``.

        Validates: Requirement 2.6
        """
        from app.modules.admin.router import router as admin_router

        admin_user_id = uuid.uuid4()
        plan_id = uuid.uuid4()
        org_id = uuid.uuid4()
        new_admin_user_id = uuid.uuid4()
        origin = "https://example.com"

        # ProvisionOrganisationResponse-shaped dict so the router can
        # build its response body without exploding.
        provision_stub = AsyncMock(
            return_value={
                "organisation_id": str(org_id),
                "organisation_name": "New Org",
                "plan_id": str(plan_id),
                "admin_user_id": str(new_admin_user_id),
                "admin_email": "admin@example.com",
                "invitation_expires_at": datetime.now(timezone.utc),
            }
        )

        app = _build_app(
            role="global_admin",
            org_id=None,
            user_id=admin_user_id,
            routers=[(admin_router, "/api/v1/admin")],
        )

        with patch(
            "app.modules.admin.router.provision_organisation",
            new=provision_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/admin/organisations",
                json={
                    "name": "New Org",
                    "plan_id": str(plan_id),
                    "admin_email": "admin@example.com",
                    "status": "active",
                },
                headers={"origin": origin},
            )

        assert resp.status_code == 200, resp.text
        provision_stub.assert_awaited_once()
        kwargs = provision_stub.await_args.kwargs

        # Same pattern as sub-test A: the router fix must pass
        # ``base_url=<origin>`` to ``provision_organisation``.
        captured_base_url = kwargs.get("base_url")
        simulated_invite_url = (
            f"{(captured_base_url or '').rstrip('/')}/verify-email?token=stub"
        )

        assert simulated_invite_url.startswith(
            f"{origin.rstrip('/')}/verify-email?token="
        ), (
            "POST /api/v1/admin/organisations must build the org-admin "
            "invitation URL from the request Origin header, not from "
            "settings.frontend_base_url. Captured base_url = "
            f"{captured_base_url!r}; resulting invite URL = "
            f"{simulated_invite_url!r}; expected to start with "
            f"{origin}/verify-email?token=."
        )

    # ------------------------------------------------------------------
    # Sub-test C — POST /api/v1/auth/password/reset-request (Bug 3 site #3)
    # ------------------------------------------------------------------

    def test_password_reset_url_uses_request_origin(self):
        """``POST /api/v1/auth/password/reset-request`` with
        ``Origin: https://example.com`` must result in a reset email
        whose URL host = ``example.com``.

        Note: the spec task description references this route as
        "POST /api/v1/auth/forgot-password"; the actual route in
        ``app/modules/auth/router.py`` is
        ``/password/reset-request``. The spec / bugfix.md both refer
        to the same handler — only the URL slug differs.

        UNFIXED OUTCOME: FAIL. ``password_reset_request`` doesn't
        read ``request.headers["origin"]``; ``request_password_reset``
        doesn't accept ``base_url``; ``_send_password_reset_email``
        (~L2197) builds the URL from ``settings.frontend_base_url``.

        Validates: Requirement 2.7
        """
        from app.modules.auth.router import router as auth_router

        origin = "https://example.com"

        # request_password_reset returns None on success; the route
        # always responds 200 with the uniform message.
        reset_stub = AsyncMock(return_value=None)

        app = _build_app(
            role=None,  # password reset is unauthenticated
            org_id=None,
            user_id=None,
            routers=[(auth_router, "/api/v1/auth")],
        )

        with patch(
            "app.modules.auth.router.request_password_reset",
            new=reset_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v1/auth/password/reset-request",
                json={"email": "user@example.com"},
                headers={"origin": origin},
            )

        assert resp.status_code == 200, resp.text
        reset_stub.assert_awaited_once()
        kwargs = reset_stub.await_args.kwargs

        # The fix must pass ``base_url=<origin>`` from the router
        # through to ``request_password_reset`` (which then threads
        # it to ``_send_password_reset_email``).
        captured_base_url = kwargs.get("base_url")
        simulated_reset_url = (
            f"{(captured_base_url or '').rstrip('/')}/reset-password?token=stub"
        )

        assert simulated_reset_url.startswith(
            f"{origin.rstrip('/')}/reset-password?token="
        ), (
            "POST /api/v1/auth/password/reset-request must build the "
            "password-reset URL from the request Origin header, not "
            "from settings.frontend_base_url. Captured base_url = "
            f"{captured_base_url!r}; resulting reset URL = "
            f"{simulated_reset_url!r}; expected to start with "
            f"{origin}/reset-password?token=."
        )

    # ------------------------------------------------------------------
    # Sub-test D — POST /api/v1/customers/{id}/send-portal-link
    # ------------------------------------------------------------------

    def test_customer_portal_link_url_uses_request_origin(self):
        """``POST /api/v1/customers/{id}/send-portal-link`` with
        ``Origin: https://example.com`` must result in a portal-link
        email whose URL host = ``example.com``.

        UNFIXED OUTCOME: FAIL. ``send_portal_link_endpoint``
        (``app/modules/customers/router.py`` ~L963) doesn't extract
        Origin; ``send_portal_link``
        (``app/modules/customers/service.py`` ~L2284) doesn't accept
        ``base_url`` and builds ``portal_url`` from
        ``settings.frontend_base_url``.

        Validates: Requirement 2.9
        """
        from app.modules.customers.router import router as customers_router

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        origin = "https://example.com"

        portal_stub = AsyncMock(
            return_value={
                "message": "Portal link sent successfully",
                "recipient": "jane@example.com",
            }
        )

        app = _build_app(
            role="org_admin",
            org_id=org_id,
            user_id=user_id,
            routers=[(customers_router, "/api/v1/customers")],
        )

        with patch(
            "app.modules.customers.router.send_portal_link",
            new=portal_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/customers/{customer_id}/send-portal-link",
                headers={"origin": origin},
            )

        assert resp.status_code == 200, resp.text
        portal_stub.assert_awaited_once()
        kwargs = portal_stub.await_args.kwargs

        # The fix must pass ``base_url=<origin>`` from the router
        # to ``send_portal_link``. ``send_portal_link`` then builds
        # ``portal_url = f"{base_url}/portal/{customer.portal_token}"``.
        captured_base_url = kwargs.get("base_url")
        simulated_portal_url = (
            f"{(captured_base_url or '').rstrip('/')}/portal/stub-token"
        )

        assert simulated_portal_url.startswith(
            f"{origin.rstrip('/')}/portal/"
        ), (
            "POST /api/v1/customers/{id}/send-portal-link must build "
            "the portal URL from the request Origin header, not from "
            "settings.frontend_base_url. Captured base_url = "
            f"{captured_base_url!r}; resulting portal URL = "
            f"{simulated_portal_url!r}; expected to start with "
            f"{origin}/portal/."
        )


# ---------------------------------------------------------------------------
# Bug 3 preservation tests — UNFIXED code: all four PASS
# ---------------------------------------------------------------------------


class TestPreservation:
    """Bug 3 preservation — the three already-correct email-link sites
    keep working, and the Origin-missing fallback to
    ``settings.frontend_base_url`` still fires when both ``Origin``
    and ``Host`` headers are absent.

    UNFIXED OUTCOME: all four sub-tests PASS — these capture
    behaviour that must NOT regress when the Bug 3 fix is applied
    to the defective sites in ``TestBug3OriginNotPropagated``.

    Validates: Requirements 4.11, 4.12, 4.13, 4.14, 3.16
    """

    # ------------------------------------------------------------------
    # Sub-test 1 — POST /api/v1/quotes/{id}/send (already correct site)
    # ------------------------------------------------------------------

    def test_quote_send_url_uses_request_origin_unchanged(self):
        """``POST /api/v1/quotes/{quote_id}/send`` already extracts
        ``request.headers["origin"]`` and threads it as ``base_url``
        through to ``send_quote`` (verified at
        ``app/modules/quotes/router.py`` ~L386). The acceptance link
        in the quote email is therefore built from the request
        origin today.

        UNFIXED OUTCOME: PASS — this is one of the reference sites
        per ``bugfix.md`` 2.12 / 4.11.

        Note: the spec task description references this route as
        ``POST /api/v1/quotes/{id}/email``; the actual route in
        ``app/modules/quotes/router.py`` is ``/{quote_id}/send``.
        Both refer to the same handler.

        Validates: Requirement 4.11 (existing correct sites unchanged)
        """
        from app.modules.quotes.router import router as quotes_router

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        quote_id = uuid.uuid4()
        origin = "https://example.com"

        # ``send_quote`` returns a dict matching ``QuoteSendResponse``
        # so the route can build its 200 response body.
        send_quote_stub = AsyncMock(
            return_value={
                "quote_id": quote_id,
                "quote_number": "Q-0001",
                "recipient_email": "buyer@example.com",
                "pdf_size_bytes": 1024,
                "status": "sent",
            }
        )

        app = _build_app(
            role="org_admin",
            org_id=org_id,
            user_id=user_id,
            routers=[(quotes_router, "/api/v1/quotes")],
        )

        with patch(
            "app.modules.quotes.router.send_quote",
            new=send_quote_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/quotes/{quote_id}/send",
                headers={"origin": origin},
            )

        assert resp.status_code == 200, resp.text
        send_quote_stub.assert_awaited_once()
        kwargs = send_quote_stub.await_args.kwargs

        captured_base_url = kwargs.get("base_url")
        assert captured_base_url is not None and captured_base_url != "", (
            "POST /api/v1/quotes/{id}/send already extracts the "
            "request Origin header today; ``base_url`` should not "
            f"be empty. Got: {captured_base_url!r}."
        )
        assert _origin_host_matches(captured_base_url, origin), (
            "POST /api/v1/quotes/{id}/send must build the quote "
            "acceptance link from the request Origin header. "
            f"Captured base_url = {captured_base_url!r}; expected "
            f"to start with {origin}."
        )

    # ------------------------------------------------------------------
    # Sub-test 2 — POST /api/v1/invoices/{id}/email (already correct site)
    # ------------------------------------------------------------------

    def test_invoice_email_url_uses_request_origin_unchanged(self):
        """``POST /api/v1/invoices/{invoice_id}/email`` already
        extracts ``request.headers["origin"]`` and threads it as
        ``base_url`` through to ``email_invoice`` (verified at
        ``app/modules/invoices/router.py`` L1680). The payment link
        in the invoice email is therefore built from the request
        origin today.

        UNFIXED OUTCOME: PASS — this is one of the reference sites
        per ``bugfix.md`` 2.12 / 4.11.

        Validates: Requirement 4.11 (existing correct sites unchanged)
        """
        from app.modules.invoices.router import router as invoices_router

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        invoice_id = uuid.uuid4()
        origin = "https://example.com"

        # ``email_invoice`` returns a dict matching the
        # ``InvoiceEmailResponse`` shape used by the router.
        email_stub = AsyncMock(
            return_value={
                "invoice_id": str(invoice_id),
                "invoice_number": "INV-0001",
                "recipient_email": "buyer@example.com",
                "pdf_size_bytes": 1024,
                "status": "sent",
            }
        )

        app = _build_app(
            role="org_admin",
            org_id=org_id,
            user_id=user_id,
            routers=[(invoices_router, "/api/v1/invoices")],
        )

        with patch(
            "app.modules.invoices.service.email_invoice",
            new=email_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                f"/api/v1/invoices/{invoice_id}/email",
                headers={"origin": origin},
            )

        assert resp.status_code == 200, resp.text
        email_stub.assert_awaited_once()
        kwargs = email_stub.await_args.kwargs

        captured_base_url = kwargs.get("base_url")
        assert captured_base_url is not None and captured_base_url != "", (
            "POST /api/v1/invoices/{id}/email already extracts the "
            "request Origin header today; ``base_url`` should not "
            f"be empty. Got: {captured_base_url!r}."
        )
        assert _origin_host_matches(captured_base_url, origin), (
            "POST /api/v1/invoices/{id}/email must build the "
            "payment link from the request Origin header. "
            f"Captured base_url = {captured_base_url!r}; expected "
            f"to start with {origin}."
        )

    # ------------------------------------------------------------------
    # Sub-test 3 — POST /api/v2/fleet-portal/admin/invite (already correct site)
    # ------------------------------------------------------------------

    def test_fleet_portal_invite_url_uses_request_origin_unchanged(self):
        """``POST /api/v2/fleet-portal/admin/invite`` already extracts
        ``request.headers["origin"]`` (or ``referer`` as a fallback),
        derives ``scheme://netloc`` and threads it as ``base_url``
        through to ``_send_fleet_portal_invite_email`` (verified at
        ``app/modules/fleet_portal/admin_router.py`` L120). The
        accept-invite link is therefore built from the request
        origin today.

        UNFIXED OUTCOME: PASS — this is the canonical reference site
        per ``bugfix.md`` 2.12 / 4.11. The fix in this spec
        replicates this exact pattern across the defective sites.

        Note: the spec task description references this route as
        ``POST /api/v1/fleet-portal/admin/accounts``; the actual
        route in ``app/modules/fleet_portal/admin_router.py`` is
        ``POST /api/v2/fleet-portal/admin/invite``.

        Validates: Requirement 4.11, 4.13 (URL has no double slashes)
        """
        from app.modules.fleet_portal.admin_router import (
            router as fleet_admin_router,
        )

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        account_id = uuid.uuid4()
        origin = "https://example.com"

        # ``account_service.invite_fleet_admin`` returns a
        # ``PortalAccount`` whose ``.id`` is consumed by the router's
        # response builder.
        fake_account = MagicMock()
        fake_account.id = account_id
        fake_account.email = "fleet@example.com"
        fake_account.invite_token = "stub-token"
        fake_account.first_name = "Test"
        fake_account.last_name = "Fleet"

        invite_stub = AsyncMock(return_value=fake_account)
        send_email_stub = AsyncMock(return_value=None)

        app = _build_app(
            role="org_admin",
            org_id=org_id,
            user_id=user_id,
            routers=[(fleet_admin_router, "/api/v2/fleet-portal/admin")],
        )

        with patch(
            "app.modules.fleet_portal.admin_router.account_service.invite_fleet_admin",
            new=invite_stub,
        ), patch(
            "app.modules.fleet_portal.admin_router._send_fleet_portal_invite_email",
            new=send_email_stub,
        ):
            client = TestClient(app)
            resp = client.post(
                "/api/v2/fleet-portal/admin/invite",
                json={"customer_id": str(customer_id)},
                headers={"origin": origin},
            )

        assert resp.status_code == 200, resp.text
        send_email_stub.assert_awaited_once()
        kwargs = send_email_stub.await_args.kwargs

        # The router fix at L114-122 already does:
        #   parsed = urlparse(origin)
        #   base_url = f"{parsed.scheme}://{parsed.netloc}"
        # so the captured value is ``https://example.com`` exactly.
        captured_base_url = kwargs.get("base_url")
        assert captured_base_url is not None and captured_base_url != "", (
            "POST /api/v2/fleet-portal/admin/invite already extracts "
            "the request Origin header today; ``base_url`` should "
            f"not be empty. Got: {captured_base_url!r}."
        )
        assert _origin_host_matches(captured_base_url, origin), (
            "POST /api/v2/fleet-portal/admin/invite must build the "
            "fleet portal invite link from the request Origin "
            f"header. Captured base_url = {captured_base_url!r}; "
            f"expected to start with {origin}."
        )
        # Requirement 4.13 — no double slash before the path
        # component when the URL is later assembled. The fleet
        # portal email body builds
        # ``f"{base_url.rstrip('/')}/fleet/accept-invite/{token}"``,
        # so verify ``base_url`` itself has no trailing slash.
        assert not captured_base_url.endswith("/"), (
            "base_url passed through to the email body builder must "
            "not have a trailing slash, otherwise the resulting URL "
            "would contain a double slash before the path. Got: "
            f"{captured_base_url!r}."
        )

    # ------------------------------------------------------------------
    # Sub-test 4 — Origin-missing AND Host-empty: fallback to frontend_base_url
    # ------------------------------------------------------------------

    def test_origin_and_host_missing_falls_back_to_frontend_base_url(self):
        """When a request arrives at one of the affected endpoints
        (here the org user-invite endpoint from Task 5 sub-test A)
        with NO ``Origin`` header AND an empty ``Host`` header, the
        router cannot derive a request-origin base URL — so the
        captured ``base_url`` is ``None``/empty and the downstream
        service falls back to ``settings.frontend_base_url`` exactly
        as today.

        UNFIXED OUTCOME: PASS — the router never sets ``base_url``
        on this endpoint today, so the kwarg is ``None``.

        POST-FIX BEHAVIOUR: still PASS — the
        ``extract_request_base_url`` helper introduced in Task 19
        returns ``None`` when both ``Origin`` and ``Host`` are
        absent, and ``create_invitation``'s existing
        ``getattr(settings, "frontend_base_url", "") or
        "http://localhost"`` fallback chain handles ``None``
        correctly (see Requirement 3.16).

        Validates: Requirement 3.16 (Origin-missing fallback),
                   Requirement 4.12 (existing fallback chain unchanged)
        """
        from app.modules.organisations.router import router as org_router

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        invite_stub = AsyncMock(
            return_value={
                "id": str(uuid.uuid4()),
                "email": "u@example.com",
                "role": "salesperson",
                "is_active": True,
                "is_email_verified": False,
                "last_login_at": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

        app = _build_app(
            role="org_admin",
            org_id=org_id,
            user_id=user_id,
            routers=[(org_router, "/api/v1/org")],
        )

        with patch(
            "app.modules.organisations.router.invite_org_user",
            new=invite_stub,
        ):
            client = TestClient(app)
            # No ``origin`` header AND empty ``host`` header — both
            # signals the router fix relies on are absent. The
            # post-fix helper ``extract_request_base_url`` returns
            # ``None``; the unfixed router never sets base_url
            # either. Either way, ``kwargs["base_url"]`` is None
            # or empty and the downstream service falls back to
            # ``settings.frontend_base_url``.
            resp = client.post(
                "/api/v1/org/users/invite",
                json={"email": "u@example.com", "role": "salesperson"},
                headers={"host": ""},
            )

        assert resp.status_code == 201, resp.text
        invite_stub.assert_awaited_once()
        kwargs = invite_stub.await_args.kwargs

        captured_base_url = kwargs.get("base_url")
        # Either kwarg-not-passed (unfixed: ``None``) or
        # explicit-None / empty string (post-fix helper returns
        # ``None`` when both headers are absent). All three cases
        # satisfy "fallback to settings.frontend_base_url" because
        # ``create_invitation`` does
        # ``base_url or getattr(settings, "frontend_base_url", "")
        # or "http://localhost"``.
        assert captured_base_url is None or captured_base_url == "", (
            "When both Origin and Host headers are absent, the "
            "router must NOT fabricate a base_url — passing None "
            "(or omitting the kwarg) lets the downstream service "
            "fall back to settings.frontend_base_url, which is the "
            "Requirement 3.16 contract. Captured base_url = "
            f"{captured_base_url!r}."
        )
