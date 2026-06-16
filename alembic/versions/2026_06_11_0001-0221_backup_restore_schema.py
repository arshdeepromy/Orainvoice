"""Cloud Backup & Restore (platform DR/BCP) — table creation.

Creates the 11 platform/global tables backing the Cloud Backup & Restore
subsystem (design Data Models section):

  - ``backup_destinations``        — configured provider-agnostic destinations
  - ``backup_residency_ack``       — per-destination residency acknowledgements
  - ``backup_key_versions``        — escrowed BMK→BDK key hierarchy versions
  - ``backup_config``              — single-row global backup configuration
  - ``backups``                    — committed Full_Backup catalog rows
  - ``backup_destination_copies``  — M:N backups ↔ destinations write status
  - ``backup_blobs``               — content-addressed File_Blob dedup store
  - ``blob_refcounts``             — File_Index reference rows for refcount GC
  - ``backup_jobs``                — Backup_Job lifecycle/progress rows
  - ``restore_jobs``               — Restore_Job lifecycle/progress rows
  - ``restore_rehearsals``         — scheduled restore-rehearsal results

These are **platform/global** tables: NO ``org_id`` column and NO Row-Level
Security policy on any of them (Req 1.1, 7.1, 8.4, 16.10). Access control is
enforced at the API layer via ``require_role('global_admin')`` — matching how
``audit_log``, ``error_log`` and the HA tables work.

Idempotent: every table is created with ``CREATE TABLE IF NOT EXISTS`` so the
migration is safely re-runnable (project rule). Indexes are intentionally NOT
created here — they live in the separate ``0222`` index-only migration which
uses ``CREATE INDEX CONCURRENTLY``.

Column types/constraints mirror ``app/modules/backup_restore/models.py`` exactly.

Revision ID: 0221
Revises: 0220
Create Date: 2026-06-11
"""

from __future__ import annotations

from alembic import op

revision: str = "0221"
down_revision: str = "0220"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. backup_destinations — configured provider-agnostic destinations.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_destinations (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            provider_type       varchar(20) NOT NULL,
            display_name        varchar(120) NOT NULL,
            is_primary          boolean NOT NULL DEFAULT false,
            is_immutable_copy   boolean NOT NULL DEFAULT false,
            connection_state    varchar(20) NOT NULL DEFAULT 'disconnected',
            config_encrypted    bytea,
            residency           varchar(20) NOT NULL DEFAULT 'unknown',
            lock_window_days    integer,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            updated_by          uuid
        )
        """
    )

    # ------------------------------------------------------------------
    # 2. backup_residency_ack — per-destination residency acknowledgements.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_residency_ack (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            destination_id  uuid NOT NULL REFERENCES backup_destinations(id),
            acknowledged_by uuid NOT NULL,
            acknowledged_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------------------------
    # 3. backup_key_versions — escrowed BMK→BDK key hierarchy versions.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_key_versions (
            id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            version                 integer UNIQUE NOT NULL,
            is_active               boolean NOT NULL DEFAULT false,
            kdf_algo                varchar(20) NOT NULL,
            kdf_params              jsonb NOT NULL,
            kdf_salt                bytea NOT NULL,
            wrapped_bmk_passphrase  bytea NOT NULL,
            wrapped_bmk_env         bytea NOT NULL,
            wrapped_bdk             bytea NOT NULL,
            bmk_kcv                 bytea NOT NULL,
            created_at              timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------------------------
    # 4. backup_config — single-row global backup configuration.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_config (
            id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            schedule_cron                   varchar(120),
            backup_window_start             time,
            backup_window_end               time,
            retention_count                 integer,
            retention_days                  integer,
            default_scope                   varchar(20) NOT NULL DEFAULT 'both',
            rpo_seconds                     integer NOT NULL DEFAULT 86400,
            rto_seconds                     integer NOT NULL DEFAULT 14400,
            rpo_rto_changed_at              timestamptz,
            notify_backup_failure           boolean NOT NULL DEFAULT true,
            notify_backup_success           boolean NOT NULL DEFAULT false,
            notify_restore_failure          boolean NOT NULL DEFAULT true,
            notify_restore_success          boolean NOT NULL DEFAULT false,
            webhook_url                     text,
            sms_enabled                     boolean NOT NULL DEFAULT false,
            email_enabled                   boolean NOT NULL DEFAULT true,
            notification_emails             jsonb NOT NULL DEFAULT '[]'::jsonb,
            notification_sms_numbers        jsonb NOT NULL DEFAULT '[]'::jsonb,
            orphan_gc_grace_hours           integer NOT NULL DEFAULT 24,
            perorg_export_size_cap_bytes    bigint,
            rehearsal_cron                  varchar(120),
            restore_maintenance_active      boolean NOT NULL DEFAULT false,
            created_at                      timestamptz NOT NULL DEFAULT now(),
            updated_at                      timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------------------------
    # 5. backups — committed Full_Backup catalog rows.
    #    Cleartext catalog fields only; org-identifying data lives encrypted
    #    in ``org_ids_encrypted`` (Req 7.8).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backups (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at          timestamptz NOT NULL DEFAULT now(),
            scope               varchar(20) NOT NULL,
            app_version         varchar(20),
            schema_version      varchar(64),
            key_version         integer REFERENCES backup_key_versions(version),
            dump_size_bytes     bigint,
            dump_checksum       varchar(128),
            file_count          bigint,
            file_bytes          bigint,
            consistency_level   varchar(2),
            manifest_key        varchar,
            prune_status        varchar(20) NOT NULL DEFAULT 'retained',
            org_ids_encrypted   bytea
        )
        """
    )

    # ------------------------------------------------------------------
    # 6. backup_destination_copies — M:N backups ↔ destinations write status.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_destination_copies (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            backup_id       uuid NOT NULL REFERENCES backups(id),
            destination_id  uuid NOT NULL REFERENCES backup_destinations(id),
            write_status    varchar(20) NOT NULL DEFAULT 'pending',
            immutable_until timestamptz,
            created_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------------------------
    # 7. backup_blobs — content-addressed File_Blob dedup store.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_blobs (
            content_hash        varchar(64) PRIMARY KEY,
            blob_name           varchar NOT NULL,
            byte_size           bigint NOT NULL,
            first_seen_at       timestamptz NOT NULL DEFAULT now(),
            last_referenced_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    # ------------------------------------------------------------------
    # 8. blob_refcounts — File_Index reference rows for refcount GC.
    #    Composite PK (content_hash, backup_id).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS blob_refcounts (
            content_hash    varchar(64) NOT NULL REFERENCES backup_blobs(content_hash),
            backup_id       uuid NOT NULL REFERENCES backups(id),
            created_at      timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (content_hash, backup_id)
        )
        """
    )

    # ------------------------------------------------------------------
    # 9. backup_jobs — Backup_Job lifecycle/progress rows.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_jobs (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            status              varchar(20) NOT NULL DEFAULT 'queued',
            progress_pct        integer NOT NULL DEFAULT 0,
            last_progress_at    timestamptz,
            last_heartbeat_at   timestamptz,
            started_at          timestamptz,
            finished_at         timestamptz,
            outcome_summary     text,
            error_message       text,
            triggered_by        varchar(20) NOT NULL DEFAULT 'manual',
            created_at          timestamptz NOT NULL DEFAULT now(),
            scope               varchar(20),
            backup_id           uuid REFERENCES backups(id),
            skipped_file_count  bigint NOT NULL DEFAULT 0
        )
        """
    )

    # ------------------------------------------------------------------
    # 10. restore_jobs — Restore_Job lifecycle/progress rows.
    #     ``destructive_apply_started`` gates the pre-apply cancel boundary
    #     (Req 12.16, 12.17).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS restore_jobs (
            id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            status                      varchar(20) NOT NULL DEFAULT 'queued',
            progress_pct                integer NOT NULL DEFAULT 0,
            last_progress_at            timestamptz,
            last_heartbeat_at           timestamptz,
            started_at                  timestamptz,
            finished_at                 timestamptz,
            outcome_summary             text,
            error_message               text,
            triggered_by                varchar(20) NOT NULL DEFAULT 'manual',
            created_at                  timestamptz NOT NULL DEFAULT now(),
            backup_id                   uuid REFERENCES backups(id),
            mode                        varchar(20) NOT NULL,
            target_org_id               uuid,
            conflict_policy             varchar(20),
            schema_compare_outcome      varchar(20),
            restore_decision            varchar(20),
            pre_restore_snapshot_path   text,
            maintenance_enabled_at      timestamptz,
            standby_fenced              boolean NOT NULL DEFAULT false,
            standby_reseeded            boolean NOT NULL DEFAULT false,
            destructive_apply_started   boolean NOT NULL DEFAULT false,
            validation_results          jsonb,
            file_consistency_outcome    varchar(20)
        )
        """
    )

    # ------------------------------------------------------------------
    # 11. restore_rehearsals — scheduled restore-rehearsal results.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS restore_rehearsals (
            id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            backup_id                   uuid REFERENCES backups(id),
            result                      varchar(20),
            schema_check                jsonb,
            rowcount_check              jsonb,
            file_check                  jsonb,
            smoke_check                 jsonb,
            measured_duration_seconds   integer,
            scratch_env_id              varchar(120),
            teardown_status             varchar(20),
            created_at                  timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    # Reverse dependency order so FK references drop cleanly.
    op.execute("DROP TABLE IF EXISTS restore_rehearsals")
    op.execute("DROP TABLE IF EXISTS restore_jobs")
    op.execute("DROP TABLE IF EXISTS backup_jobs")
    op.execute("DROP TABLE IF EXISTS blob_refcounts")
    op.execute("DROP TABLE IF EXISTS backup_blobs")
    op.execute("DROP TABLE IF EXISTS backup_destination_copies")
    op.execute("DROP TABLE IF EXISTS backups")
    op.execute("DROP TABLE IF EXISTS backup_config")
    op.execute("DROP TABLE IF EXISTS backup_key_versions")
    op.execute("DROP TABLE IF EXISTS backup_residency_ack")
    op.execute("DROP TABLE IF EXISTS backup_destinations")
