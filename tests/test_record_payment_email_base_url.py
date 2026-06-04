"""Regression test for ISSUE-170 — record-payment auto-email link host.

When a payment is recorded ("Record Payment" on an issued invoice, or
"mark paid" at invoice creation), the app auto-sends an updated invoice
email via ``email_invoice`` from a fire-and-forget background task.

Bug: those background calls did NOT pass ``base_url``, so ``email_invoice``
fell back to ``settings.frontend_base_url`` for the invoice-view link. On the
Pi PROD deploy that setting is a LAN IP (``http://192.168.1.90:8999``), so the
customer received a link to the LAN IP instead of the public domain the staff
member was actually on.

Fix: both background callers now capture the request ``Origin`` header before
spawning the task and pass it as ``base_url=...`` to ``email_invoice`` — the
same pattern every other email-sending endpoint already uses (issue email, QR
session, send-payment-link, regenerate-link).

This is a source-level guard: every ``email_invoice(...)`` call site inside the
two payment-triggering routers must pass a ``base_url`` argument. It is
intentionally static (AST-based) rather than driving the fire-and-forget
``asyncio.create_task`` background tasks, which are not deterministically
observable from an endpoint test.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Routers that spawn a background ``email_invoice`` after recording a payment.
ROUTER_FILES = [
    REPO_ROOT / "app" / "modules" / "payments" / "router.py",
    REPO_ROOT / "app" / "modules" / "invoices" / "router.py",
]


def _email_invoice_calls(tree: ast.AST) -> list[ast.Call]:
    """Return every call expression whose callee is named ``email_invoice``."""
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name == "email_invoice":
                calls.append(node)
    return calls


@pytest.mark.parametrize("router_path", ROUTER_FILES, ids=lambda p: p.name)
def test_every_email_invoice_call_passes_base_url(router_path: Path):
    """No ``email_invoice(...)`` call in the payment routers may omit base_url.

    Guards ISSUE-170: a missing ``base_url`` makes the receipt email fall back
    to ``settings.frontend_base_url`` (a LAN IP on Pi PROD) for the invoice link.
    """
    source = router_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = _email_invoice_calls(tree)

    # Sanity: each router has at least one email_invoice call to check.
    assert calls, f"expected at least one email_invoice(...) call in {router_path.name}"

    missing = [
        call.lineno
        for call in calls
        if not any(kw.arg == "base_url" for kw in call.keywords)
    ]

    assert not missing, (
        f"{router_path.name}: email_invoice(...) call(s) at line(s) {missing} "
        f"do not pass base_url — the receipt email would fall back to "
        f"settings.frontend_base_url (a LAN IP on Pi PROD) for the invoice link "
        f"(ISSUE-170)."
    )
