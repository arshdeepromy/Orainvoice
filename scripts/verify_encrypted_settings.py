#!/usr/bin/env python3
"""Encrypted Settings Verifier.

Connects to the database, iterates over all tables with encrypted columns,
attempts decryption via envelope_decrypt_str, and outputs a JSON
VerificationReport.

Usage:
    python scripts/verify_encrypted_settings.py --phase phase1 --stage pre
    python scripts/verify_encrypted_settings.py --phase phase1 --stage post
    python scripts/verify_encrypted_settings.py --stage rollback
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from sqlalchemy import text

# ---------------------------------------------------------------------------
# Report data structures
# ---------------------------------------------------------------------------


@dataclass
class FieldResult:
    table: str
    record_id: str
    status: str  # "OK" or "FAIL: <error>"


@dataclass
class VerificationReport:
    timestamp: str
    phase: str
    stage: str
    results: dict[str, list[dict]]  # keyed by table name
    total_checked: int = 0
    total_failed: int = 0
    passed: bool = True


# ---------------------------------------------------------------------------
# Verification logic
# ---------------------------------------------------------------------------


async def verify_all_encrypted_fields(phase: str, stage: str) -> VerificationReport:
    """Attempt decryption of every encrypted field and return a report."""
    from app.core.database import async_session_factory
    from app.core.encryption import envelope_decrypt_str

    report = VerificationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        phase=phase,
        stage=stage,
        results={},
    )

    async with async_session_factory() as session:
        # 1. integration_configs.config_encrypted (keyed by name)
        table = "integration_configs"
        results: list[dict] = []
        rows = (await session.execute(
            text("SELECT name, config_encrypted FROM integration_configs")
        )).fetchall()
        for row in rows:
            record_id = row[0]
            blob = row[1]
            result = _try_decrypt(envelope_decrypt_str, blob, table, record_id)
            results.append(asdict(result))
            report.total_checked += 1
            if not result.status.startswith("OK"):
                report.total_failed += 1
        report.results[table] = results

        # 2. sms_verification_providers.credentials_encrypted (keyed by provider_key)
        table = "sms_verification_providers"
        results = []
        rows = (await session.execute(
            text("SELECT provider_key, credentials_encrypted FROM sms_verification_providers")
        )).fetchall()
        for row in rows:
            record_id = row[0]
            blob = row[1]
            if blob is None:
                # No encrypted data stored — skip
                results.append(asdict(FieldResult(table=table, record_id=record_id, status="OK (no data)")))
                report.total_checked += 1
                continue
            result = _try_decrypt(envelope_decrypt_str, blob, table, record_id)
            results.append(asdict(result))
            report.total_checked += 1
            if not result.status.startswith("OK"):
                report.total_failed += 1
        report.results[table] = results

        # 3. email_providers.credentials_encrypted (keyed by provider_key)
        table = "email_providers"
        results = []
        rows = (await session.execute(
            text("SELECT provider_key, credentials_encrypted FROM email_providers")
        )).fetchall()
        for row in rows:
            record_id = row[0]
            blob = row[1]
            if blob is None:
                results.append(asdict(FieldResult(table=table, record_id=record_id, status="OK (no data)")))
                report.total_checked += 1
                continue
            result = _try_decrypt(envelope_decrypt_str, blob, table, record_id)
            results.append(asdict(result))
            report.total_checked += 1
            if not result.status.startswith("OK"):
                report.total_failed += 1
        report.results[table] = results

        # 4. user_mfa_methods.secret_encrypted (keyed by user_id + method, TOTP only)
        table = "user_mfa_methods"
        results = []
        rows = (await session.execute(
            text(
                "SELECT user_id, method, secret_encrypted FROM user_mfa_methods "
                "WHERE method = 'totp' AND secret_encrypted IS NOT NULL"
            )
        )).fetchall()
        for row in rows:
            record_id = f"{row[0]}/{row[1]}"
            blob = row[2]
            result = _try_decrypt(envelope_decrypt_str, blob, table, record_id)
            results.append(asdict(result))
            report.total_checked += 1
            if not result.status.startswith("OK"):
                report.total_failed += 1
        report.results[table] = results

    report.passed = report.total_failed == 0
    return report


def _try_decrypt(decrypt_fn, blob: bytes, table: str, record_id: str) -> FieldResult:
    """Attempt decryption and return a FieldResult."""
    try:
        decrypt_fn(blob)
        return FieldResult(table=table, record_id=record_id, status="OK")
    except Exception as exc:
        return FieldResult(
            table=table,
            record_id=record_id,
            status=f"FAIL: {type(exc).__name__}: {exc}",
        )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify all encrypted settings in the database")
    parser.add_argument("--phase", default="unknown", help="Upgrade phase name (e.g. phase1)")
    parser.add_argument("--stage", default="manual", help="Verification stage (pre, post, rollback)")
    args = parser.parse_args()

    report = asyncio.run(verify_all_encrypted_fields(args.phase, args.stage))

    print(json.dumps(asdict(report), indent=2))

    if not report.passed:
        print(
            f"\nFAILED: {report.total_failed}/{report.total_checked} encrypted fields could not be decrypted.",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print(f"\nPASSED: All {report.total_checked} encrypted fields decrypted successfully.", file=sys.stderr)


if __name__ == "__main__":
    main()
