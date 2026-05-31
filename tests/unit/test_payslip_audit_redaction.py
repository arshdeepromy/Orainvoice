"""Audit-redaction lint test for the payslips module (G12 + P4-N32).

Implements task E1b from ``.kiro/specs/staff-management-p4/tasks.md``.

The test walks the AST of every ``app/modules/payslips/*.py`` file
and inspects every ``write_audit_log(...)`` call site. For each call
it pulls out the ``after_value`` keyword argument and asserts:

  1. **Forbidden keys** — when ``after_value`` is a ``Dict`` literal,
     NONE of the expanded forbidden-key set may appear:
       gross_pay, net_pay, amount, ird_number, bank_account_number,
       paye, s27_lump_sum, annual_payout_dollars,
       alt_day_total_dollars, casual_8pct_remainder_dollars,
       recipient_email.

     When ``after_value`` is a call to ``_redacted_payslip_event(...)``
     (the central helper that builds the safe base shape and accepts
     ``**extra`` kwargs), we still inspect the keyword args passed to
     the helper and reject any that hit the forbidden set — the
     helper enforces redaction by NAME, not by computing a sanitised
     subset, so a future contributor passing
     ``_redacted_payslip_event(p, action='x', gross_pay=p.gross_pay)``
     would silently ship a leak. This test catches it.

  2. **Positive shape for ``staff.terminated``** — the audit row for
     the ``staff.terminated`` action MUST contain a ``payout_summary``
     key whose value is a Dict literal with at least the three
     documented keys: ``annual_hours``, ``alt_days``,
     ``casual_8pct_remaining``. This guards R14's redacted-summary
     contract: counts only, never dollars.

The test runs against the static source — no DB required.

**Validates: Requirements R14, G12, P4-N32 — Staff Management Phase 4
task B10 + E1b.**
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Spec-locked sets
# ---------------------------------------------------------------------------


FORBIDDEN_AFTER_VALUE_KEYS = frozenset(
    {
        "gross_pay",
        "net_pay",
        "amount",
        "ird_number",
        "bank_account_number",
        "paye",
        "s27_lump_sum",
        "annual_payout_dollars",
        "alt_day_total_dollars",
        "casual_8pct_remainder_dollars",
        "recipient_email",
    }
)

REQUIRED_PAYOUT_SUMMARY_KEYS = frozenset(
    {"annual_hours", "alt_days", "casual_8pct_remaining"}
)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _payslips_module_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "modules" / "payslips"


def _payslips_source_files() -> list[Path]:
    """Return every ``.py`` file under ``app/modules/payslips/``
    (excluding ``__init__.py`` if it has no real content; we still
    parse it for completeness — empty files have no Call nodes so
    they're harmless).
    """
    return sorted(p for p in _payslips_module_dir().glob("*.py"))


def _is_write_audit_log_call(node: ast.AST) -> bool:
    """Return True iff ``node`` is a ``Call`` whose callee is
    ``write_audit_log`` (either by direct name, by ``module.write_audit_log``
    attribute access, or via ``await write_audit_log(...)`` already
    unwrapped to the inner Call).
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "write_audit_log"
    if isinstance(func, ast.Attribute):
        return func.attr == "write_audit_log"
    return False


def _collect_write_audit_log_calls(tree: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if _is_write_audit_log_call(n)]


def _kwarg(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_redacted_payslip_event_call(node: ast.AST) -> bool:
    """Return True iff ``node`` is a Call to ``_redacted_payslip_event``
    (by name or by attribute access)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "_redacted_payslip_event"
    if isinstance(func, ast.Attribute):
        return func.attr == "_redacted_payslip_event"
    return False


def _dict_literal_keys(node: ast.AST) -> set[str]:
    """Return the set of string keys present in a ``Dict`` literal.
    Non-string keys / dynamic keys are skipped (a future contributor
    using a computed key would also need to hand-review — but our
    payslips audit dicts are all string-keyed today).
    """
    if not isinstance(node, ast.Dict):
        return set()
    out: set[str] = set()
    for k in node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            out.add(k.value)
    return out


def _kwarg_names(call: ast.Call) -> set[str]:
    """Return the names of explicit keyword arguments passed to a
    Call. Used to inspect what was passed into ``_redacted_payslip_event(...)``
    — the helper merges these into the audit ``after_value``.
    """
    return {kw.arg for kw in call.keywords if kw.arg is not None}


def _action_name(call: ast.Call) -> str | None:
    """Return the literal value of the ``action=`` kwarg, or None
    when it isn't a string constant.
    """
    action_node = _kwarg(call, "action")
    if isinstance(action_node, ast.Constant) and isinstance(action_node.value, str):
        return action_node.value
    return None


# ---------------------------------------------------------------------------
# Aggregated discovery (collect once across all files)
# ---------------------------------------------------------------------------


def _all_write_audit_calls() -> list[tuple[Path, ast.Call]]:
    """Return ``(path, Call node)`` tuples for every
    ``write_audit_log`` call in the payslips module.
    """
    out: list[tuple[Path, ast.Call]] = []
    for path in _payslips_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — repo invariant
            continue
        for call in _collect_write_audit_log_calls(tree):
            out.append((path, call))
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSourceCoverage:
    """Sanity: confirm we actually found audit call sites — otherwise
    a refactor that renamed the helper would silently bypass this test.
    """

    def test_payslips_module_has_write_audit_log_calls(self):
        calls = _all_write_audit_calls()
        assert calls, (
            "expected at least one write_audit_log call across "
            "app/modules/payslips/*.py — none found"
        )


class TestForbiddenKeys:
    """Every ``write_audit_log`` call site must NOT include any
    forbidden key in its ``after_value`` (G12 + P4-N32).
    """

    def test_no_forbidden_keys_in_dict_literals(self):
        offences: list[str] = []
        for path, call in _all_write_audit_calls():
            after = _kwarg(call, "after_value")
            if after is None:
                continue

            # Inline ``ast.Dict`` literal — inspect keys directly.
            if isinstance(after, ast.Dict):
                keys = _dict_literal_keys(after)
                hit = FORBIDDEN_AFTER_VALUE_KEYS & keys
                if hit:
                    offences.append(
                        f"{path.name}:{call.lineno} dict literal includes "
                        f"forbidden key(s): {sorted(hit)}"
                    )

        assert not offences, (
            "audit redaction violations detected:\n  - "
            + "\n  - ".join(offences)
        )

    def test_no_forbidden_keys_in_redacted_helper_extras(self):
        """The ``_redacted_payslip_event(payslip, action='x', **extra)``
        helper merges its kwargs straight into ``after_value``. A
        contributor who passes a forbidden key as an extra (e.g.
        ``_redacted_payslip_event(p, action='x', gross_pay=p.gross_pay)``)
        would silently leak. This test rejects any forbidden-named
        kwarg passed to the helper.
        """
        offences: list[str] = []
        for path, call in _all_write_audit_calls():
            after = _kwarg(call, "after_value")
            if not _is_redacted_payslip_event_call(after):
                continue
            assert isinstance(after, ast.Call)  # for the type checker
            kwarg_names = _kwarg_names(after)
            hit = FORBIDDEN_AFTER_VALUE_KEYS & kwarg_names
            if hit:
                offences.append(
                    f"{path.name}:{call.lineno} _redacted_payslip_event(...) "
                    f"received forbidden kwarg(s): {sorted(hit)}"
                )
        assert not offences, (
            "redaction-helper kwarg violations detected:\n  - "
            + "\n  - ".join(offences)
        )


class TestStaffTerminatedShape:
    """The ``staff.terminated`` audit row MUST carry a redacted
    ``payout_summary`` (counts only — no dollars) per R14.

    Concretely: ``after_value`` is a ``Dict`` literal with a
    ``payout_summary`` key whose value is itself a ``Dict`` literal
    containing AT LEAST the three keys ``annual_hours``, ``alt_days``,
    and ``casual_8pct_remaining``.

    The test allows ``payout_summary`` to be a Name/variable
    reference (the implementation builds a local dict and references
    it) — in that case we look up the assignment in the same
    function scope and inspect its dict literal.
    """

    def test_terminated_after_value_contains_redacted_payout_summary(self):
        """At least one ``staff.terminated`` audit call exists, and
        its ``after_value.payout_summary`` is a Dict literal (or
        binds to one in the surrounding scope) containing the three
        required keys.
        """
        terminated_calls: list[tuple[Path, ast.Call, ast.AST]] = []
        for path, call in _all_write_audit_calls():
            if _action_name(call) == "staff.terminated":
                tree = ast.parse(path.read_text(encoding="utf-8"))
                terminated_calls.append((path, call, tree))

        assert terminated_calls, (
            "expected a write_audit_log(action='staff.terminated', ...) "
            "call site in app/modules/payslips/* — found none"
        )

        for path, call, tree in terminated_calls:
            after = _kwarg(call, "after_value")
            assert isinstance(after, ast.Dict), (
                f"{path.name}:{call.lineno} staff.terminated after_value "
                f"must be a Dict literal so the redaction shape is "
                f"statically auditable"
            )
            top_keys = _dict_literal_keys(after)
            assert "payout_summary" in top_keys, (
                f"{path.name}:{call.lineno} staff.terminated after_value "
                f"missing required `payout_summary` key (R14)"
            )

            # Find the value bound to the payout_summary key.
            payout_summary_node: ast.AST | None = None
            for k_node, v_node in zip(after.keys, after.values):
                if (
                    isinstance(k_node, ast.Constant)
                    and k_node.value == "payout_summary"
                ):
                    payout_summary_node = v_node
                    break
            assert payout_summary_node is not None  # mypy

            # If it's a direct dict literal, inspect it.
            inner_keys: set[str] = set()
            if isinstance(payout_summary_node, ast.Dict):
                inner_keys = _dict_literal_keys(payout_summary_node)
            elif isinstance(payout_summary_node, ast.Name):
                # Walk the module tree for the most recent
                # ``payout_summary = { ... }`` assignment in the
                # same function as ``call``. Simple search — assumes
                # the assignment uses a Dict literal (that's the
                # convention used by termination.py).
                target_name = payout_summary_node.id
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Assign)
                        and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name)
                        and node.targets[0].id == target_name
                        and isinstance(node.value, ast.Dict)
                    ):
                        inner_keys = _dict_literal_keys(node.value)
                        break
            else:
                pytest.fail(
                    f"{path.name}:{call.lineno} payout_summary must bind to "
                    f"a Dict literal (got {type(payout_summary_node).__name__})"
                )

            missing = REQUIRED_PAYOUT_SUMMARY_KEYS - inner_keys
            assert not missing, (
                f"{path.name}:{call.lineno} staff.terminated payout_summary "
                f"missing required key(s): {sorted(missing)}"
            )

            # Bonus belt-and-braces — payout_summary itself MUST NOT
            # contain any forbidden dollar-amount key.
            forbidden_hit = FORBIDDEN_AFTER_VALUE_KEYS & inner_keys
            assert not forbidden_hit, (
                f"{path.name}:{call.lineno} payout_summary leaks forbidden "
                f"dollar-amount key(s): {sorted(forbidden_hit)}"
            )
