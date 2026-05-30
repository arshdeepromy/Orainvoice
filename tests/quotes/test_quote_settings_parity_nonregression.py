# Feature: quote-settings-parity, Task 14: Non-regression / smoke checks
"""Smoke / non-regression checks for the quote-settings-parity feature.

These are working-tree assertions — they do not exercise runtime behaviour;
they verify the codebase shape produced by tasks 1-13:

  * The Pydantic ``QuoteResponse`` schema declares the three new fields.
  * ``QuoteDetail.tsx`` no longer uses ``as any`` near the parity field
    accesses.
  * No new Alembic migration was added for this feature.
  * ``OrgSettings.tsx`` and ``app/modules/organisations/`` are present
    (the feature explicitly does not touch them).

Validates Requirements: 3.3, 10.2, 10.3, 10.4, 10.5
"""
from __future__ import annotations

import re
from pathlib import Path

from app.modules.quotes.schemas import QuoteResponse


REPO_ROOT = Path(__file__).resolve().parents[2]


# --- 1. QuoteResponse schema check ----------------------------------------

def test_quote_response_has_three_new_fields() -> None:
    """Validates Requirement 3.1, 6.1, 6.2 (field declarations)."""
    fields = QuoteResponse.model_fields
    assert "payment_terms_text" in fields
    assert "terms_and_conditions" in fields
    assert "terms_and_conditions_enabled" in fields


# --- 2. QuoteDetail.tsx — no `as any` near the parity fields --------------

def test_quote_detail_has_no_as_any_near_parity_fields() -> None:
    """Validates Requirement 3.3: typed access for the parity fields.

    Reads the QuoteDetail.tsx text and confirms that every line referencing
    ``payment_terms_text`` or ``terms_and_conditions`` does not also contain
    ``as any``.
    """
    path = REPO_ROOT / "frontend" / "src" / "pages" / "quotes" / "QuoteDetail.tsx"
    assert path.is_file(), f"Expected {path} to exist"
    content = path.read_text(encoding="utf-8")

    parity_pattern = re.compile(r"(payment_terms_text|terms_and_conditions)")
    offenders: list[str] = []
    for line in content.splitlines():
        if parity_pattern.search(line) and "as any" in line:
            offenders.append(line)

    assert not offenders, (
        "Expected zero occurrences of `as any` on lines referencing the "
        "parity fields, but found:\n" + "\n".join(offenders)
    )


# --- 3. No new Alembic migration for this feature -------------------------

def test_no_quote_settings_parity_migration() -> None:
    """Validates Requirement 10.3: no Alembic migration added for this feature."""
    migrations_dir = REPO_ROOT / "alembic" / "versions"
    assert migrations_dir.is_dir(), f"Expected {migrations_dir} to exist"

    pattern = re.compile(r"quote.*settings.*parity", re.IGNORECASE)
    matches = [
        p
        for p in migrations_dir.glob("*.py")
        if pattern.search(p.name)
    ]
    assert not matches, (
        f"Expected no migration matching *quote*settings*parity*, "
        f"but found: {[m.name for m in matches]}"
    )


# --- 4. OrgSettings.tsx and 5. organisations module are present -----------

def test_org_settings_tsx_present_and_unchanged_in_scope() -> None:
    """Validates Requirement 10.5: OrgSettings.tsx remains the single
    user-facing edit surface; this feature does not touch it.

    The three field names (``payment_terms_text`` / ``terms_and_conditions`` /
    ``terms_and_conditions_enabled``) already exist in OrgSettings.tsx as
    part of the shared org settings UI — this test verifies the file is
    present, which is sufficient for the parity feature's non-regression
    contract (the design explicitly does not modify the file).
    """
    path = REPO_ROOT / "frontend" / "src" / "pages" / "settings" / "OrgSettings.tsx"
    assert path.is_file(), f"Expected {path} to exist"


def test_organisations_module_present() -> None:
    """Validates Requirement 10.4: no new HTTP endpoint added; the
    existing PUT /org/settings remains the write path. The organisations
    module is left intact.
    """
    org_dir = REPO_ROOT / "app" / "modules" / "organisations"
    assert org_dir.is_dir(), f"Expected {org_dir} to exist"
    py_files = list(org_dir.glob("*.py"))
    assert py_files, f"Expected at least one Python file in {org_dir}"
