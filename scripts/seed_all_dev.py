"""Seed all development data — run this for fresh dev environment setup.

Run: python scripts/seed_all_dev.py

Creates:
  1. Global admin user (admin@orainvoice.com / admin123)
  2. Demo org_admin user (demo@orainvoice.com / demo123) with all modules

Idempotent — safe to run multiple times.
"""

from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    from scripts.seed_dev_user import seed as seed_global_admin
    from scripts.seed_demo_org_admin import seed as seed_demo_org

    print("=" * 50)
    print("  SEEDING DEV ENVIRONMENT")
    print("=" * 50)
    print()

    print("--- 1. Global Admin ---")
    await seed_global_admin()
    print()

    print("--- 2. Demo Org Admin ---")
    await seed_demo_org()
    print()

    print("Dev environment seeding complete.")


if __name__ == "__main__":
    asyncio.run(main())
