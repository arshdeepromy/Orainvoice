"""Update the Brevo email-providers setup_guide for the unified UI.

Phase 6 (task 6.5) of the email-provider-unification spec. The seed copy
shipped in migration 0065 only describes the SMTP-key flow, but the
unified Email Providers admin page now accepts either:

1. A REST API key (``xkeysib-...``) — single field, no SMTP login
   required. Used for direct API dispatch by ``send_email``'s Brevo
   REST adapter.
2. An SMTP key + SMTP login — the legacy two-field combination still
   used when API access is restricted on the Brevo account.

This migration rewrites ``email_providers.setup_guide`` for the
``brevo`` row to explain both flows and where to find each credential
in the Brevo admin UI. The downgrade restores the verbatim seed copy
shipped with migration 0065 so a forward-then-back deploy is clean.

The guide is rendered as a numbered list by the admin page's
``SetupGuide`` component — which splits on newlines, strips the
``N.`` prefix, and renders each line as a step. Steps are kept short
so they render legibly in the side panel.

HA replication
--------------
``email_providers`` was created in migration 0065 and is not on the
publication-exclusion list (``ha_config``, ``dead_letter_queue``,
``ha_event_log``, ``alembic_version``); it is already a member of
``orainvoice_ha_pub`` (and any legacy ``ora_publication``). A pure
``UPDATE`` on a single row is replicated automatically by PostgreSQL
logical replication, so no ``_HA_ADD_TPL`` snippet is required.

Idempotency
-----------
Both the upgrade and the downgrade are pure ``UPDATE`` statements
keyed on ``provider_key = 'brevo'`` — re-running either is a no-op
beyond rewriting the column to the same value.

Revision ID: 0196
Revises: 0195
Create Date: 2026-05-27
"""

from __future__ import annotations

from alembic import op


revision: str = "0196"
down_revision: str = "0195"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Phase 6 unified guide. Newline-delimited numbered steps; the admin
# page renders each line as a list item.
NEW_BREVO_SETUP_GUIDE = (
    "1. Sign up at https://www.brevo.com and verify your sending domain "
    "under Senders, Domains & Dedicated IPs → Domains.\n"
    "2. Decide which credential type you want to use — Brevo supports "
    "two and the unified email sender accepts either:\n"
    "3. REST API key (recommended): in the Brevo dashboard go to SMTP & "
    "API → API Keys → \"Generate a new API key\" (v3). Copy the "
    "xkeysib-... value and paste it into the SMTP Key or API Key field. "
    "Leave the SMTP Login field blank — the API path does not need it.\n"
    "4. SMTP key + SMTP login (alternative): in the Brevo dashboard go "
    "to SMTP & API → SMTP. Copy the SMTP key into the SMTP Key field "
    "and paste your SMTP login (typically your Brevo account email or "
    "the dedicated SMTP user shown on that page) into the SMTP Login "
    "field.\n"
    "5. Set the From Email to a verified sender address (matching one "
    "of the verified domains from step 1) and an optional From Name.\n"
    "6. Click Save and use the Send Test Email button to confirm "
    "delivery before activating the provider."
)


# Verbatim setup_guide shipped in migration 0065 — kept here so the
# downgrade path is reversible.
LEGACY_BREVO_SETUP_GUIDE = (
    "1. Sign up at https://www.brevo.com and verify your domain.\n"
    "2. Go to SMTP & API → SMTP and copy your SMTP key.\n"
    "3. Enter the SMTP key below as the API Key.\n"
    "4. Set From Email to a verified sender address.\n"
    "5. Click Save and send a test email to confirm delivery."
)


def upgrade() -> None:
    op.execute(
        "UPDATE email_providers "
        f"SET setup_guide = {_sql_literal(NEW_BREVO_SETUP_GUIDE)}, "
        "    updated_at = NOW() "
        "WHERE provider_key = 'brevo'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE email_providers "
        f"SET setup_guide = {_sql_literal(LEGACY_BREVO_SETUP_GUIDE)}, "
        "    updated_at = NOW() "
        "WHERE provider_key = 'brevo'"
    )


def _sql_literal(value: str) -> str:
    """Render ``value`` as a single-quoted SQL string literal.

    We avoid SQLAlchemy ``text(...).bindparams(...)`` here so the
    on-disk migration body stays readable. Single quotes inside the
    value are doubled per the SQL standard escape rule.
    """
    return "'" + value.replace("'", "''") + "'"
