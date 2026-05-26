"""Create B2B Fleet Portal schema.

Adds the portal_accounts foundation table and 15 fleet-domain tables that
back the standalone Fleet Portal SPA mounted at /fleet/* (or fleet.<domain>).

Schema groups created here:

  Portal account / security parity (6 tables — all created from scratch;
  the docs/future/portal-password-login.md proposal was never migrated):
    - portal_accounts                   (login + lockout + invite/reset)
    - portal_account_mfa_methods        (TOTP / SMS / backup_codes)
    - portal_account_backup_codes       (one-time recovery codes)
    - portal_account_password_history   (password reuse prevention)
    - portal_audit_log                  (auth + admin event log)
    - portal_account_devices            (mobile push tokens)

  Fleet-domain tables (10):
    - portal_fleet_accounts                (one row per business customer
                                            who has portal access — distinct
                                            from the legacy fleet_accounts
                                            table created in migration 0002,
                                            which groups many customers
                                            under a single commercial account
                                            via customers.fleet_account_id)
    - fleet_driver_assignments             (driver ↔ vehicle visibility)
    - fleet_checklist_templates            (NZTA seed + custom)
    - fleet_checklist_template_items       (items per template)
    - fleet_checklist_submissions          (one run by a driver)
    - fleet_checklist_submission_items     (per-item snapshot results)
    - fleet_reminder_preferences           (per-vehicle WOF/COF reminders)
    - fleet_service_booking_requests       (portal → bookings draft)
    - fleet_quotation_requests             (portal → quotes draft)
    - fleet_driver_hours                   (driving-hours log)

  Existing-table extensions (additive only):
    - customer_vehicles.fleet_checklist_template_id  (per-vehicle override)
    - portal_sessions.portal_account_id              (discriminator for
      fleet portal sessions vs token-link sessions; customer_id stays
      NOT NULL — fleet sessions write BOTH columns)

  module_registry: inserts the 'b2b-fleet-management' row.

  organisations.settings: seeds default 'portal_security_policy' JSONB key
  for any org that already has the module enabled (none on first deploy,
  but the loop is idempotent and future-proof).

Trade-family gating ('automotive-transport' only) is enforced in code via
TRADE_FAMILY_REQUIRED_MODULES in app/core/modules.py — no DB column.

RLS policies on the new tables are added in a separate migration / task
(task 1.2 in the b2b-fleet-portal spec). This migration intentionally
creates schema only.

Revision ID: 0191
Revises: 0190
Create Date: 2026-05-18

Requirements: 1.1, 4.2, 5.2, 8.1, 9.1, 10.3, 11.2, 12.2, 14.1, 17.2,
              21.1, 21.5, 21.10, 21.12, 21.15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0191"
down_revision: str = "0190"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


# Tables created by this migration, in the order they should be added to
# the HA replication publication and dropped on downgrade (children first
# on drop, parents first on add).
_NEW_TABLES: tuple[str, ...] = (
    # Portal account + security
    "portal_accounts",
    "portal_account_mfa_methods",
    "portal_account_backup_codes",
    "portal_account_password_history",
    "portal_audit_log",
    "portal_account_devices",
    # Fleet domain
    "portal_fleet_accounts",
    "fleet_checklist_templates",
    "fleet_checklist_template_items",
    "fleet_driver_assignments",
    "fleet_checklist_submissions",
    "fleet_checklist_submission_items",
    "fleet_reminder_preferences",
    "fleet_service_booking_requests",
    "fleet_quotation_requests",
    "fleet_driver_hours",
)


_HA_ADD_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'ora_publication') THEN
        ALTER PUBLICATION ora_publication ADD TABLE {table};
    END IF;
END
$ha_block$
"""

_HA_DROP_TPL = """
DO $ha_block$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'ora_publication' AND tablename = '{table}'
    ) THEN
        ALTER PUBLICATION ora_publication DROP TABLE {table};
    END IF;
END
$ha_block$
"""


# Default portal_security_policy (mirrors OrgSecuritySettings shape).
# Stored verbatim so the org settings UI can edit each field.
_DEFAULT_PORTAL_SECURITY_POLICY = """{
  "mfa_policy": {"mode": "optional", "excluded_user_ids": []},
  "password_policy": {
    "min_length": 8,
    "require_uppercase": false,
    "require_lowercase": false,
    "require_digit": false,
    "require_special": false,
    "expiry_days": 0,
    "history_count": 0,
    "require_not_pwned": false
  },
  "lockout_policy": {
    "temp_lock_threshold": 5,
    "temp_lock_minutes": 30,
    "permanent_lock_threshold": 10
  },
  "session_policy": {
    "idle_timeout_minutes": 240,
    "max_sessions_per_user": 5,
    "refresh_token_expire_days": 7
  }
}"""


def upgrade() -> None:
    # All DDL is wrapped with IF NOT EXISTS / guarded blocks for idempotency
    # so re-running the migration is safe (per database-migration-checklist).

    # ── 1. portal_accounts ────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            email VARCHAR(255) NOT NULL,
            password_hash VARCHAR(255) NULL,
            password_changed_at TIMESTAMPTZ NULL,
            must_change_password BOOLEAN NOT NULL DEFAULT false,
            invite_token VARCHAR(255) NULL,
            invite_sent_at TIMESTAMPTZ NULL,
            invite_accepted_at TIMESTAMPTZ NULL,
            reset_token VARCHAR(255) NULL,
            reset_token_expires_at TIMESTAMPTZ NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            is_locked_permanently BOOLEAN NOT NULL DEFAULT false,
            last_login_at TIMESTAMPTZ NULL,
            last_login_ip VARCHAR(45) NULL,
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ NULL,
            portal_user_role VARCHAR(20) NOT NULL,
            fleet_account_id UUID NULL,
            first_name VARCHAR(100) NULL,
            last_name VARCHAR(100) NULL,
            phone VARCHAR(50) NULL,
            mfa_required_at_next_login BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_portal_accounts_role
                CHECK (portal_user_role IN ('fleet_admin', 'driver'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_accounts_org_email "
        "ON portal_accounts (org_id, lower(email))"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_accounts_reset_token "
        "ON portal_accounts (reset_token) WHERE reset_token IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_accounts_invite_token "
        "ON portal_accounts (invite_token) WHERE invite_token IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_accounts_fleet_role_active "
        "ON portal_accounts (fleet_account_id, portal_user_role, is_active)"
    )

    # ── 2. portal_account_mfa_methods ────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_account_mfa_methods (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE CASCADE,
            method VARCHAR(20) NOT NULL,
            secret_encrypted BYTEA NULL,
            phone_number VARCHAR(50) NULL,
            verified BOOLEAN NOT NULL DEFAULT false,
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_verified_at TIMESTAMPTZ NULL,
            CONSTRAINT ck_portal_account_mfa_methods_method
                CHECK (method IN ('totp', 'sms', 'backup_codes'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_account_mfa_account_method "
        "ON portal_account_mfa_methods (portal_account_id, method)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_account_mfa_default "
        "ON portal_account_mfa_methods (portal_account_id) WHERE is_default = true"
    )

    # ── 3. portal_account_backup_codes ───────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_account_backup_codes (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE CASCADE,
            code_hash VARCHAR(255) NOT NULL,
            consumed_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_account_backup_codes_account "
        "ON portal_account_backup_codes (portal_account_id) "
        "WHERE consumed_at IS NULL"
    )

    # ── 4. portal_account_password_history ───────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_account_password_history (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE CASCADE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_account_password_history_account "
        "ON portal_account_password_history (portal_account_id, created_at DESC)"
    )

    # ── 5. portal_audit_log ──────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_audit_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_account_id UUID NULL
                REFERENCES portal_accounts(id) ON DELETE SET NULL,
            actor_user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(80) NOT NULL,
            ip_address VARCHAR(45) NULL,
            user_agent VARCHAR(500) NULL,
            details JSONB NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_audit_log_account_created "
        "ON portal_audit_log (portal_account_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_audit_log_org_action_created "
        "ON portal_audit_log (org_id, action, created_at DESC)"
    )

    # ── 6. portal_account_devices ────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_account_devices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE CASCADE,
            device_token VARCHAR(500) NOT NULL,
            platform VARCHAR(10) NOT NULL,
            app_version VARCHAR(50) NULL,
            os_version VARCHAR(50) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_portal_account_devices_platform
                CHECK (platform IN ('ios', 'android'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_account_devices_account_token "
        "ON portal_account_devices (portal_account_id, device_token)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_account_devices_account "
        "ON portal_account_devices (portal_account_id)"
    )

    # ── 7. portal_fleet_accounts ────────────────────────────────────────
    # Renamed from the spec's "fleet_accounts" because that name is
    # already taken by an unrelated table created in migration 0002.
    # Internal column names (fleet_account_id) are kept per the spec so
    # the rest of the implementation reads naturally.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_fleet_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            display_name VARCHAR(255) NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_portal_fleet_accounts_org_customer "
        "ON portal_fleet_accounts (org_id, customer_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_fleet_accounts_org_active "
        "ON portal_fleet_accounts (org_id, is_active)"
    )

    # portal_accounts.fleet_account_id FK now resolves to the new
    # portal_fleet_accounts table. Done as a separate ALTER so the
    # constraint can be added idempotently.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                  AND table_name = 'portal_accounts'
                  AND constraint_name = 'fk_portal_accounts_fleet_account_id'
            ) THEN
                ALTER TABLE portal_accounts
                    ADD CONSTRAINT fk_portal_accounts_fleet_account_id
                    FOREIGN KEY (fleet_account_id)
                    REFERENCES portal_fleet_accounts(id) ON DELETE SET NULL;
            END IF;
        END
        $$
        """
    )

    # ── 8. fleet_checklist_templates ─────────────────────────────────────
    # Created before fleet_driver_assignments so the customer_vehicles
    # ALTER TABLE below can reference it.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_checklist_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            name VARCHAR(200) NOT NULL,
            description TEXT NULL,
            is_default BOOLEAN NOT NULL DEFAULT false,
            is_system_seeded BOOLEAN NOT NULL DEFAULT false,
            archived_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_fleet_checklist_templates_default_per_fleet "
        "ON fleet_checklist_templates (fleet_account_id) WHERE is_default = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_checklist_templates_fleet "
        "ON fleet_checklist_templates (fleet_account_id, archived_at)"
    )

    # ── 9. fleet_checklist_template_items ───────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_checklist_template_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            template_id UUID NOT NULL
                REFERENCES fleet_checklist_templates(id) ON DELETE CASCADE,
            category VARCHAR(80) NOT NULL,
            label VARCHAR(200) NOT NULL,
            description VARCHAR(500) NULL,
            requires_photo_on_fail BOOLEAN NOT NULL DEFAULT false,
            display_order INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_checklist_template_items_template_order "
        "ON fleet_checklist_template_items (template_id, display_order)"
    )

    # ── 10. fleet_driver_assignments ────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_driver_assignments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE CASCADE,
            customer_vehicle_id UUID NOT NULL
                REFERENCES customer_vehicles(id) ON DELETE CASCADE,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            assigned_by_portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_fleet_driver_assignments_driver_vehicle "
        "ON fleet_driver_assignments (portal_account_id, customer_vehicle_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_driver_assignments_vehicle "
        "ON fleet_driver_assignments (customer_vehicle_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_driver_assignments_fleet "
        "ON fleet_driver_assignments (fleet_account_id)"
    )

    # ── 11. fleet_checklist_submissions ─────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_checklist_submissions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            customer_vehicle_id UUID NOT NULL
                REFERENCES customer_vehicles(id) ON DELETE CASCADE,
            template_id UUID NOT NULL
                REFERENCES fleet_checklist_templates(id) ON DELETE RESTRICT,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE RESTRICT,
            status VARCHAR(20) NOT NULL DEFAULT 'in_progress',
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at TIMESTAMPTZ NULL,
            passed_item_count INTEGER NOT NULL DEFAULT 0,
            failed_item_count INTEGER NOT NULL DEFAULT 0,
            na_item_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_fleet_checklist_submissions_status
                CHECK (status IN ('in_progress', 'completed', 'cancelled'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_checklist_submissions_fleet_completed "
        "ON fleet_checklist_submissions (fleet_account_id, completed_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_checklist_submissions_vehicle_completed "
        "ON fleet_checklist_submissions (customer_vehicle_id, completed_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_checklist_submissions_driver_completed "
        "ON fleet_checklist_submissions (portal_account_id, completed_at DESC)"
    )

    # ── 12. fleet_checklist_submission_items ────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_checklist_submission_items (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            submission_id UUID NOT NULL
                REFERENCES fleet_checklist_submissions(id) ON DELETE CASCADE,
            template_item_id UUID NOT NULL
                REFERENCES fleet_checklist_template_items(id) ON DELETE RESTRICT,
            category VARCHAR(80) NOT NULL,
            label VARCHAR(200) NOT NULL,
            requires_photo_on_fail BOOLEAN NOT NULL DEFAULT false,
            result VARCHAR(10) NULL,
            notes VARCHAR(500) NULL,
            photo_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
            recorded_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_fleet_checklist_submission_items_result
                CHECK (result IS NULL OR result IN ('pass', 'fail', 'na'))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_checklist_submission_items_submission "
        "ON fleet_checklist_submission_items (submission_id)"
    )

    # ── 13. fleet_reminder_preferences ──────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_reminder_preferences (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            customer_vehicle_id UUID NOT NULL
                REFERENCES customer_vehicles(id) ON DELETE CASCADE,
            reminder_type VARCHAR(40) NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT false,
            lead_time_days INTEGER NOT NULL DEFAULT 14,
            channels JSONB NOT NULL DEFAULT '[]'::jsonb,
            recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
            service_interval_km INTEGER NULL,
            service_interval_months INTEGER NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_fleet_reminder_preferences_lead_time
                CHECK (lead_time_days IN (7, 14, 30)),
            CONSTRAINT ck_fleet_reminder_preferences_type
                CHECK (reminder_type IN (
                    'wof_expiry_reminder',
                    'cof_expiry_reminder',
                    'service_due_reminder',
                    'registration_expiry_reminder'
                ))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_fleet_reminder_preferences_vehicle_type "
        "ON fleet_reminder_preferences (customer_vehicle_id, reminder_type)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_reminder_preferences_fleet "
        "ON fleet_reminder_preferences (fleet_account_id)"
    )

    # ── 14. fleet_service_booking_requests ──────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_service_booking_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            customer_vehicle_id UUID NOT NULL
                REFERENCES customer_vehicles(id) ON DELETE CASCADE,
            requested_by_portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE RESTRICT,
            preferred_date DATE NOT NULL,
            preferred_slot VARCHAR(20) NOT NULL,
            service_description TEXT NOT NULL,
            notes TEXT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            decline_reason TEXT NULL,
            booking_id UUID NULL REFERENCES bookings(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_fleet_service_booking_requests_slot
                CHECK (preferred_slot IN ('morning', 'afternoon', 'all_day')),
            CONSTRAINT ck_fleet_service_booking_requests_status
                CHECK (status IN (
                    'pending', 'accepted', 'declined',
                    'completed', 'cancelled'
                ))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_service_booking_requests_fleet_status "
        "ON fleet_service_booking_requests (fleet_account_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_service_booking_requests_org_status_created "
        "ON fleet_service_booking_requests (org_id, status, created_at DESC)"
    )

    # ── 15. fleet_quotation_requests ────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_quotation_requests (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            customer_vehicle_id UUID NOT NULL
                REFERENCES customer_vehicles(id) ON DELETE CASCADE,
            requested_by_portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE RESTRICT,
            service_description TEXT NOT NULL,
            notes TEXT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            quote_id UUID NULL REFERENCES quotes(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_fleet_quotation_requests_status
                CHECK (status IN (
                    'pending', 'quoted', 'accepted',
                    'declined', 'expired', 'cancelled'
                ))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_quotation_requests_fleet_status "
        "ON fleet_quotation_requests (fleet_account_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_quotation_requests_org_status_created "
        "ON fleet_quotation_requests (org_id, status, created_at DESC)"
    )

    # ── 16. fleet_driver_hours ──────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS fleet_driver_hours (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id UUID NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
            fleet_account_id UUID NOT NULL
                REFERENCES portal_fleet_accounts(id) ON DELETE CASCADE,
            customer_vehicle_id UUID NOT NULL
                REFERENCES customer_vehicles(id) ON DELETE CASCADE,
            portal_account_id UUID NOT NULL
                REFERENCES portal_accounts(id) ON DELETE RESTRICT,
            start_at TIMESTAMPTZ NOT NULL,
            end_at TIMESTAMPTZ NOT NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_fleet_driver_hours_range
                CHECK (end_at >= start_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_driver_hours_driver_start "
        "ON fleet_driver_hours (portal_account_id, start_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fleet_driver_hours_vehicle_start "
        "ON fleet_driver_hours (customer_vehicle_id, start_at DESC)"
    )

    # ── 17. customer_vehicles.fleet_checklist_template_id ───────────────
    op.execute(
        """
        ALTER TABLE customer_vehicles
            ADD COLUMN IF NOT EXISTS fleet_checklist_template_id UUID NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                  AND table_name = 'customer_vehicles'
                  AND constraint_name = 'fk_customer_vehicles_fleet_checklist_template_id'
            ) THEN
                ALTER TABLE customer_vehicles
                    ADD CONSTRAINT fk_customer_vehicles_fleet_checklist_template_id
                    FOREIGN KEY (fleet_checklist_template_id)
                    REFERENCES fleet_checklist_templates(id) ON DELETE SET NULL;
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_customer_vehicles_fleet_checklist_template "
        "ON customer_vehicles (fleet_checklist_template_id) "
        "WHERE fleet_checklist_template_id IS NOT NULL"
    )

    # ── 18. portal_sessions.portal_account_id ───────────────────────────
    # Discriminator: portal_account_id IS NOT NULL → fleet portal session
    # (created via password login). When NULL, the row is a token-link
    # session for the legacy customer portal — customer_id stays NOT NULL
    # in both cases.
    op.execute(
        """
        ALTER TABLE portal_sessions
            ADD COLUMN IF NOT EXISTS portal_account_id UUID NULL
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE table_schema = 'public'
                  AND table_name = 'portal_sessions'
                  AND constraint_name = 'fk_portal_sessions_portal_account_id'
            ) THEN
                ALTER TABLE portal_sessions
                    ADD CONSTRAINT fk_portal_sessions_portal_account_id
                    FOREIGN KEY (portal_account_id)
                    REFERENCES portal_accounts(id) ON DELETE CASCADE;
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_portal_sessions_portal_account_id "
        "ON portal_sessions (portal_account_id) "
        "WHERE portal_account_id IS NOT NULL"
    )

    # ── 19. module_registry row ─────────────────────────────────────────
    op.execute(
        """
        INSERT INTO module_registry (
            id, slug, display_name, description, category,
            is_core, dependencies, incompatibilities, status,
            setup_question, setup_question_description, created_at
        ) VALUES (
            gen_random_uuid(),
            'b2b-fleet-management',
            'B2B Fleet Management',
            'Self-service portal for business customers to manage vehicle fleets.',
            'fleet_management',
            false,
            '["vehicles"]'::jsonb,
            '[]'::jsonb,
            'available',
            'Do your business customers need a self-service portal to manage their vehicle fleet?',
            'Let fleet operators log in to view vehicles, invite drivers, run NZTA pre-trip checklists, book services, request quotes, and manage WOF/COF reminders.',
            now()
        )
        ON CONFLICT ON CONSTRAINT uq_module_registry_slug DO NOTHING
        """
    )

    # ── 20. Default portal_security_policy for orgs already enabled ─────
    # Idempotent: only sets the key when it is currently absent. On first
    # deploy no org has the module enabled so the UPDATE matches zero
    # rows; the loop is here so future re-runs do not skip orgs that
    # enabled the module before this migration was reapplied.
    op.execute(
        sa.text(
            """
            UPDATE organisations o
            SET settings = jsonb_set(
                COALESCE(o.settings, '{}'::jsonb),
                '{portal_security_policy}',
                CAST(:policy AS jsonb),
                true
            )
            WHERE EXISTS (
                SELECT 1 FROM org_modules om
                WHERE om.org_id = o.id
                  AND om.module_slug = 'b2b-fleet-management'
                  AND om.is_enabled = true
            )
            AND (
                o.settings IS NULL
                OR NOT (o.settings ? 'portal_security_policy')
            )
            """
        ).bindparams(policy=_DEFAULT_PORTAL_SECURITY_POLICY)
    )

    # ── 20b. feature_flags row (drives the Global Admin Feature Flags UI) ──
    # The module_registry row (above) drives the per-org module management
    # system; this feature_flags row makes the module visible in the
    # Global Admin → Feature Flags page so platform admins can toggle it.
    op.execute(
        """
        INSERT INTO feature_flags (
            id, key, display_name, description, category,
            access_level, dependencies, default_value, is_active
        ) VALUES (
            gen_random_uuid(),
            'b2b-fleet-management',
            'B2B Fleet Management',
            'Self-service portal for business customers to manage vehicle fleets, invite drivers, run NZTA pre-trip checklists, book services, request quotes, and manage WOF/COF reminders.',
            'Automotive',
            'all_users',
            '["vehicles"]'::jsonb,
            false,
            true
        )
        ON CONFLICT (key) DO NOTHING
        """
    )

    # ── 21. HA replication publication membership ───────────────────────
    for table in _NEW_TABLES:
        op.execute(sa.text(_HA_ADD_TPL.format(table=table)))


def downgrade() -> None:
    # ── 1. Drop HA publication membership (children first) ──────────────
    for table in reversed(_NEW_TABLES):
        op.execute(sa.text(_HA_DROP_TPL.format(table=table)))

    # ── 2. Remove module_registry row ───────────────────────────────────
    op.execute(
        "DELETE FROM org_modules WHERE module_slug = 'b2b-fleet-management'"
    )
    op.execute(
        "DELETE FROM module_registry WHERE slug = 'b2b-fleet-management'"
    )
    op.execute(
        "DELETE FROM feature_flags WHERE key = 'b2b-fleet-management'"
    )

    # ── 3. Reverse existing-table extensions ────────────────────────────
    op.execute(
        "DROP INDEX IF EXISTS ix_portal_sessions_portal_account_id"
    )
    op.execute(
        "ALTER TABLE portal_sessions "
        "DROP CONSTRAINT IF EXISTS fk_portal_sessions_portal_account_id"
    )
    op.execute(
        "ALTER TABLE portal_sessions "
        "DROP COLUMN IF EXISTS portal_account_id"
    )

    op.execute(
        "DROP INDEX IF EXISTS ix_customer_vehicles_fleet_checklist_template"
    )
    op.execute(
        "ALTER TABLE customer_vehicles "
        "DROP CONSTRAINT IF EXISTS fk_customer_vehicles_fleet_checklist_template_id"
    )
    op.execute(
        "ALTER TABLE customer_vehicles "
        "DROP COLUMN IF EXISTS fleet_checklist_template_id"
    )

    # ── 4. Drop the new tables in FK-safe order (children first) ────────
    op.execute("DROP TABLE IF EXISTS fleet_driver_hours CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_quotation_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_service_booking_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_reminder_preferences CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_checklist_submission_items CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_checklist_submissions CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_driver_assignments CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_checklist_template_items CASCADE")
    op.execute("DROP TABLE IF EXISTS fleet_checklist_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_fleet_accounts CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_account_devices CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_account_password_history CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_account_backup_codes CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_account_mfa_methods CASCADE")
    op.execute("DROP TABLE IF EXISTS portal_accounts CASCADE")

    # The portal_security_policy JSONB key inside organisations.settings
    # is left in place on downgrade — it carries no harm and removing it
    # from arbitrary org settings could mask hand-tuned values that an
    # operator may want preserved across migration cycles.
