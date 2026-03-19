"""Create normalised MFA tables and migrate data from JSONB columns.

Creates user_mfa_methods, user_passkey_credentials, and user_backup_codes
tables, migrates existing data from users.mfa_methods,
users.passkey_credentials, and users.backup_codes_hash JSONB columns,
then drops the deprecated JSONB columns.

Revision ID: 0098
Revises: 0097
Create Date: 2026-03-19 09:00:00

Requirements: 1.3, 2.3, 3.3, 5.2, 11.3
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- 1. Create new normalised tables ------------------------------------

    # user_mfa_methods
    op.create_table(
        "user_mfa_methods",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("phone_number", sa.String(20), nullable=True),
        sa.Column("secret_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_mfa_methods_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "method", name="uq_user_mfa_method"),
        sa.CheckConstraint(
            "method IN ('totp', 'sms', 'email', 'passkey')",
            name="chk_method",
        ),
    )
    op.create_index(
        "idx_user_mfa_methods_user", "user_mfa_methods", ["user_id"]
    )

    # user_passkey_credentials
    op.create_table(
        "user_passkey_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("credential_id", sa.String(512), nullable=False),
        sa.Column("public_key", sa.Text(), nullable=False),
        sa.Column("public_key_alg", sa.Integer(), nullable=False),
        sa.Column(
            "sign_count",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "device_name",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'My Passkey'"),
        ),
        sa.Column(
            "flagged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_passkey_credentials_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "credential_id", name="uq_passkey_credential_id"
        ),
    )
    op.create_index(
        "idx_passkey_creds_user",
        "user_passkey_credentials",
        ["user_id"],
    )
    op.create_index(
        "idx_passkey_creds_credential_id",
        "user_passkey_credentials",
        ["credential_id"],
    )

    # user_backup_codes
    op.create_table(
        "user_backup_codes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(128), nullable=False),
        sa.Column(
            "used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_backup_codes_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "idx_backup_codes_user", "user_backup_codes", ["user_id"]
    )

    # -- 2. Migrate existing data from JSONB columns -----------------------

    # Migrate mfa_methods JSONB → user_mfa_methods rows
    # Each entry: {"type": "totp"|"sms"|"email", "verified": bool,
    #              "secret_encrypted": hex (TOTP), "phone": str (SMS),
    #              "enrolled_at": iso_str}
    op.execute("""
        INSERT INTO user_mfa_methods (user_id, method, verified, phone_number,
                                       secret_encrypted, enrolled_at, verified_at)
        SELECT
            u.id,
            (elem->>'type'),
            COALESCE((elem->>'verified')::boolean, false),
            elem->>'phone',
            CASE
                WHEN elem->>'secret_encrypted' IS NOT NULL
                THEN decode(elem->>'secret_encrypted', 'hex')
                ELSE NULL
            END,
            CASE
                WHEN elem->>'enrolled_at' IS NOT NULL
                THEN (elem->>'enrolled_at')::timestamptz
                ELSE now()
            END,
            CASE
                WHEN COALESCE((elem->>'verified')::boolean, false) = true
                THEN COALESCE(
                    (elem->>'enrolled_at')::timestamptz,
                    now()
                )
                ELSE NULL
            END
        FROM users u,
             jsonb_array_elements(u.mfa_methods) AS elem
        WHERE jsonb_array_length(u.mfa_methods) > 0
          AND elem->>'type' IS NOT NULL
        ON CONFLICT (user_id, method) DO NOTHING
    """)

    # Migrate passkey_credentials JSONB → user_passkey_credentials rows
    # Each entry: {"credential_id": str, "public_key": str,
    #              "public_key_alg": int, "sign_count": int,
    #              "device_name": str, "created_at": iso_str}
    op.execute("""
        INSERT INTO user_passkey_credentials (user_id, credential_id, public_key,
                                               public_key_alg, sign_count,
                                               device_name, created_at)
        SELECT
            u.id,
            elem->>'credential_id',
            elem->>'public_key',
            COALESCE((elem->>'public_key_alg')::integer, -7),
            COALESCE((elem->>'sign_count')::bigint, 0),
            COALESCE(elem->>'device_name', 'My Passkey'),
            CASE
                WHEN elem->>'created_at' IS NOT NULL
                THEN (elem->>'created_at')::timestamptz
                ELSE now()
            END
        FROM users u,
             jsonb_array_elements(u.passkey_credentials) AS elem
        WHERE jsonb_array_length(u.passkey_credentials) > 0
          AND elem->>'credential_id' IS NOT NULL
        ON CONFLICT (credential_id) DO NOTHING
    """)

    # For users with migrated passkey credentials, ensure a 'passkey' entry
    # exists in user_mfa_methods
    op.execute("""
        INSERT INTO user_mfa_methods (user_id, method, verified, enrolled_at, verified_at)
        SELECT DISTINCT
            upc.user_id,
            'passkey',
            true,
            MIN(upc.created_at),
            MIN(upc.created_at)
        FROM user_passkey_credentials upc
        GROUP BY upc.user_id
        ON CONFLICT (user_id, method) DO NOTHING
    """)

    # Migrate backup_codes_hash JSONB → user_backup_codes rows
    # Each entry: {"hash": str, "used": bool}
    op.execute("""
        INSERT INTO user_backup_codes (user_id, code_hash, used, created_at)
        SELECT
            u.id,
            elem->>'hash',
            COALESCE((elem->>'used')::boolean, false),
            u.created_at
        FROM users u,
             jsonb_array_elements(u.backup_codes_hash) AS elem
        WHERE u.backup_codes_hash IS NOT NULL
          AND jsonb_array_length(u.backup_codes_hash) > 0
          AND elem->>'hash' IS NOT NULL
    """)

    # -- 3. Drop deprecated JSONB columns from users -----------------------
    op.drop_column("users", "mfa_methods")
    op.drop_column("users", "passkey_credentials")
    op.drop_column("users", "backup_codes_hash")


def downgrade() -> None:
    # -- 1. Re-add JSONB columns to users ----------------------------------
    op.add_column(
        "users",
        sa.Column(
            "mfa_methods",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "passkey_credentials",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("backup_codes_hash", postgresql.JSONB(), nullable=True),
    )

    # -- 2. Migrate data back to JSONB columns -----------------------------

    # Restore mfa_methods (excluding 'passkey' type which was synthetic)
    op.execute("""
        UPDATE users u
        SET mfa_methods = COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'type', m.method,
                        'verified', m.verified,
                        'enrolled_at', m.enrolled_at::text
                    )
                    ||
                    CASE
                        WHEN m.phone_number IS NOT NULL
                        THEN jsonb_build_object('phone', m.phone_number)
                        ELSE '{}'::jsonb
                    END
                    ||
                    CASE
                        WHEN m.secret_encrypted IS NOT NULL
                        THEN jsonb_build_object('secret_encrypted', encode(m.secret_encrypted, 'hex'))
                        ELSE '{}'::jsonb
                    END
                )
                FROM user_mfa_methods m
                WHERE m.user_id = u.id
                  AND m.method != 'passkey'
            ),
            '[]'::jsonb
        )
    """)

    # Restore passkey_credentials
    op.execute("""
        UPDATE users u
        SET passkey_credentials = COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'credential_id', pc.credential_id,
                        'public_key', pc.public_key,
                        'public_key_alg', pc.public_key_alg,
                        'sign_count', pc.sign_count,
                        'device_name', pc.device_name,
                        'created_at', pc.created_at::text
                    )
                )
                FROM user_passkey_credentials pc
                WHERE pc.user_id = u.id
            ),
            '[]'::jsonb
        )
    """)

    # Restore backup_codes_hash
    op.execute("""
        UPDATE users u
        SET backup_codes_hash = (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'hash', bc.code_hash,
                    'used', bc.used
                )
            )
            FROM user_backup_codes bc
            WHERE bc.user_id = u.id
        )
    """)

    # -- 3. Drop normalised tables -----------------------------------------
    op.drop_index("idx_backup_codes_user", table_name="user_backup_codes")
    op.drop_table("user_backup_codes")

    op.drop_index(
        "idx_passkey_creds_credential_id",
        table_name="user_passkey_credentials",
    )
    op.drop_index(
        "idx_passkey_creds_user", table_name="user_passkey_credentials"
    )
    op.drop_table("user_passkey_credentials")

    op.drop_index("idx_user_mfa_methods_user", table_name="user_mfa_methods")
    op.drop_table("user_mfa_methods")
