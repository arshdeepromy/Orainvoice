"""Audit-redaction lint (H4).

Feature: customer-reminder-consent

AST-walks ``app/modules/customers/consent.py``, finds every call to
``write_audit_log(...)``, and enforces the PII-redaction contract:

  * the ``after_value=`` argument is a *variable* (a redacted copy), never a
    raw ``record.model_dump()`` call or a dict literal carrying PII keys;
  * no dict literal anywhere in the module uses a forbidden key as a literal
    key (so a forbidden key can never be hand-written into an audit payload);
  * the enclosing function pops every forbidden key it must strip before the
    write (ip_address / user_agent for the grant path; recorded_by_user_id /
    recorded_by_user_email for the revocation path).

Validates: Requirements 7.1, 7.2; NFR-5.
"""

from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_KEYS = {
    "ip_address",
    "user_agent",
    "recorded_by_user_id",
    "recorded_by_user_email",
}

MODULE_PATH = Path("app/modules/customers/consent.py")


def _tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text())


def _enclosing_functions(tree: ast.Module):
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node)
    return funcs


def test_no_dict_literal_uses_a_forbidden_key():
    """No Dict literal in the module may carry a forbidden PII key."""
    tree = _tree()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value in FORBIDDEN_KEYS:
                    raise AssertionError(
                        f"Dict literal uses forbidden audit key {key.value!r}"
                    )


def test_write_audit_log_after_value_is_a_redacted_variable():
    """Every write_audit_log call passes after_value as a Name (redacted copy),
    never a raw model_dump() or a dict literal."""
    tree = _tree()
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "write_audit_log"
    ]
    assert calls, "expected at least one write_audit_log call in consent.py"
    for call in calls:
        after = next((kw.value for kw in call.keywords if kw.arg == "after_value"), None)
        assert after is not None, "write_audit_log call missing after_value"
        # Must be a plain variable reference (the redacted copy), or None.
        assert isinstance(after, (ast.Name, ast.Constant)), (
            "after_value must be a redacted variable, not an inline expression"
        )


def test_each_audit_function_pops_its_forbidden_keys():
    """The grant path strips ip_address + user_agent; the revocation path
    strips recorded_by_user_id + recorded_by_user_email."""
    tree = _tree()
    required = {
        "record_consent_given": {"ip_address", "user_agent"},
        "record_consent_revoked": {"recorded_by_user_id", "recorded_by_user_email"},
    }
    by_name = {f.name: f for f in _enclosing_functions(tree)}
    for fn_name, keys in required.items():
        assert fn_name in by_name, f"{fn_name} not found in consent.py"
        popped: set[str] = set()
        for node in ast.walk(by_name[fn_name]):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "pop"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                popped.add(node.args[0].value)
        missing = keys - popped
        assert not missing, f"{fn_name} fails to pop forbidden keys: {missing}"
