"""CI guard: only ``app/integrations/email_sender.py`` may import ``smtplib``.

Phase 3 task 3.20 of the email-provider-unification spec. The grep gate
in task 3.16 was satisfied at the per-site commit level; this test is
the standing CI rule that catches a regression on every CI run.

A new file in ``app/`` that imports ``smtplib`` would route around the
unified sender's failover, time-budget, and bounce-blocklist
guarantees. If this test starts failing, the offending file should
either:

  - call ``send_email`` from ``app.integrations.email_sender`` instead
    of building its own MIME envelope, OR
  - call ``dispatch_one_provider`` if the call is genuinely for a
    single-provider operation like the admin Test button.

Validates: Requirement 6.2
"""

from __future__ import annotations

import pathlib
import re

import pytest


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_APP_DIR = _REPO_ROOT / "app"
_ALLOWED_FILE = _APP_DIR / "integrations" / "email_sender.py"

# ``import smtplib`` (top-level) and ``from smtplib import …`` (top-level
# or function-local). Hand-rolled provider loops would be hidden by
# either form, so both must be flagged.
_SMTPLIB_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+smtplib(?:\s|$|\.)|from\s+smtplib\s+import\b)",
    re.MULTILINE,
)


def test_no_smtplib_imports_outside_email_sender() -> None:
    """Walk ``app/**/*.py`` and assert ``smtplib`` is only imported in
    ``app/integrations/email_sender.py``.

    Catches both ``import smtplib`` and ``from smtplib import …`` —
    function-local imports count too.

    Validates: Requirement 6.2
    """
    offenders: list[tuple[pathlib.Path, list[int]]] = []

    for py_file in _APP_DIR.rglob("*.py"):
        if py_file == _ALLOWED_FILE:
            continue
        # Skip __pycache__, generated files, etc.
        if "__pycache__" in py_file.parts:
            continue

        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Unreadable files are not violators of this rule; let
            # other tests / linters complain about them.
            continue

        line_numbers = [
            i + 1
            for i, line in enumerate(text.splitlines())
            if _SMTPLIB_IMPORT_RE.match(line)
        ]
        if line_numbers:
            offenders.append((py_file.relative_to(_REPO_ROOT), line_numbers))

    if offenders:
        rendered = "\n".join(
            f"  - {path} (lines {', '.join(str(n) for n in lines)})"
            for path, lines in offenders
        )
        pytest.fail(
            "smtplib must only be imported in "
            "app/integrations/email_sender.py — every other email "
            "send site routes through the unified sender. Offenders:\n"
            f"{rendered}\n\n"
            "Fix: replace the smtplib loop with a call to "
            "send_email() (or dispatch_one_provider() for "
            "single-provider operations like the admin Test button)."
        )
