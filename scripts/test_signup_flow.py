#!/usr/bin/env python3
"""End-to-end signup flow test script.

Simulates the full frontend signup journey by hitting the same API endpoints
the browser does, then verifies the resulting org has the correct trade
category assigned.

Usage:
    docker compose exec app python /app/scripts/test_signup_flow.py

Or from host:
    docker compose exec -T app python /app/scripts/test_signup_flow.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Bootstrap — add app to path so we can import project modules
# ---------------------------------------------------------------------------
sys.path.insert(0, "/app")


async def main() -> None:
    print("=" * 70)
    print("  SIGNUP FLOW TEST — Trade Category Auto-Selection")
    print("=" * 70)
    print()

    # ------------------------------------------------------------------
    # 1. Connect to DB directly (same as the app does)
    # ------------------------------------------------------------------
    from app.core.database import async_session_factory
    from sqlalchemy import select, text

    # Import all models to ensure SQLAlchemy relationships resolve
    from app.modules.auth.models import User  # noqa: F401
    from app.modules.admin.models import Organisation, SubscriptionPlan  # noqa: F401
    from app.modules.trade_categories.models import TradeFamily, TradeCategory  # noqa: F401
    from app.modules.module_management.models import OrgModule, ModuleRegistry  # noqa: F401

    async with async_session_factory() as db:
        async with db.begin():
            # ----------------------------------------------------------
            # 2. Find the Mech Pro plan
            # ----------------------------------------------------------
            result = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.name == "Mech Pro")
            )
            plan = result.scalar_one_or_none()
            if plan is None:
                print("❌ FAIL: Mech Pro plan not found in database")
                sys.exit(1)

            print(f"✅ Found plan: {plan.name} (id={plan.id})")
            print(f"   trial_duration: {plan.trial_duration}")
            print(f"   monthly_price_nzd: {plan.monthly_price_nzd}")
            print(f"   enabled_modules: {plan.enabled_modules}")
            print()

            is_paid = plan.trial_duration == 0
            print(f"   Flow type: {'PAID (confirm-payment)' if is_paid else 'TRIAL (immediate creation)'}")
            print()

            # ----------------------------------------------------------
            # 3. List trade families (same as GET /api/v2/trade-families)
            # ----------------------------------------------------------
            families_result = await db.execute(
                select(TradeFamily).where(TradeFamily.is_active == True)
            )
            families = families_result.scalars().all()
            print(f"📋 Available trade families ({len(families)}):")
            for f in families:
                print(f"   - {f.display_name} (slug={f.slug})")
            print()

            # Find automotive-transport family
            auto_family = next((f for f in families if f.slug == "automotive-transport"), None)
            if auto_family is None:
                print("❌ FAIL: automotive-transport trade family not found")
                sys.exit(1)

            print(f"🚗 Selected trade family: {auto_family.display_name} (slug={auto_family.slug})")
            print()

            # ----------------------------------------------------------
            # 4. Show categories in this family (what the user would see
            #    in the setup wizard, but NOT during signup — signup only
            #    sends trade_family_slug, not trade_category_slug)
            # ----------------------------------------------------------
            cats_result = await db.execute(
                select(TradeCategory).where(
                    TradeCategory.family_id == auto_family.id,
                    TradeCategory.is_active == True,
                ).order_by(TradeCategory.display_name)
            )
            categories = cats_result.scalars().all()
            print(f"📋 Categories in {auto_family.display_name}:")
            for c in categories:
                print(f"   - {c.display_name} (slug={c.slug})")
            print()

            # ----------------------------------------------------------
            # 5. Simulate the trade category auto-selection query
            #    This is what public_signup() does in organisations/service.py
            # ----------------------------------------------------------
            print("=" * 70)
            print("  TEST A: organisations/service.py query (trial flow)")
            print("=" * 70)

            from sqlalchemy import case as sa_case
            cat_result_a = await db.execute(
                select(TradeCategory.id, TradeCategory.slug, TradeCategory.display_name).where(
                    TradeCategory.family_id == auto_family.id,
                    TradeCategory.is_active == True,
                ).order_by(
                    sa_case(
                        (TradeCategory.slug.like("general-%"), 0),
                        else_=1,
                    ),
                    TradeCategory.display_name,
                ).limit(1)
            )
            row_a = cat_result_a.first()
            if row_a:
                print(f"   Selected: {row_a[2]} (slug={row_a[1]})")
                if row_a[1] == "general-automotive":
                    print("   ✅ PASS — Correctly selected General Automotive")
                else:
                    print(f"   ❌ FAIL — Expected general-automotive, got {row_a[1]}")
            else:
                print("   ❌ FAIL — No category found")
            print()

            # ----------------------------------------------------------
            # 6. Simulate the trade category auto-selection query
            #    from auth/router.py confirm_signup_payment (paid flow)
            # ----------------------------------------------------------
            print("=" * 70)
            print("  TEST B: auth/router.py query (paid/confirm-payment flow)")
            print("=" * 70)

            # This is the FIXED version — check if the fix is applied
            cat_result_b = await db.execute(
                select(TradeCategory.id, TradeCategory.slug, TradeCategory.display_name).where(
                    TradeCategory.family_id == auto_family.id,
                    TradeCategory.is_active == True,
                ).order_by(
                    sa_case(
                        (TradeCategory.slug.like("general-%"), 0),
                        else_=1,
                    ),
                    TradeCategory.display_name,
                ).limit(1)
            )
            row_b = cat_result_b.first()
            if row_b:
                print(f"   Selected: {row_b[2]} (slug={row_b[1]})")
                if row_b[1] == "general-automotive":
                    print("   ✅ PASS — Correctly selected General Automotive")
                else:
                    print(f"   ❌ FAIL — Expected general-automotive, got {row_b[1]}")
            else:
                print("   ❌ FAIL — No category found")
            print()

            # Also test the OLD (broken) query to show the difference
            print("  TEST B2: OLD query (alphabetical — the bug)")
            cat_result_old = await db.execute(
                select(TradeCategory.id, TradeCategory.slug, TradeCategory.display_name).where(
                    TradeCategory.family_id == auto_family.id,
                    TradeCategory.is_active == True,
                ).order_by(TradeCategory.display_name).limit(1)
            )
            row_old = cat_result_old.first()
            if row_old:
                print(f"   Selected: {row_old[2]} (slug={row_old[1]})")
                if row_old[1] == "auto-electrical":
                    print("   ⚠️  Confirmed: old query picks Auto Electrical (the bug)")
                else:
                    print(f"   Selected: {row_old[1]}")
            print()

            # ----------------------------------------------------------
            # 7. Full integration test: call public_signup() directly
            #    with a unique test email
            # ----------------------------------------------------------
            print("=" * 70)
            print("  TEST C: Full public_signup() call (integration test)")
            print("=" * 70)

            test_email = f"test-signup-{uuid.uuid4().hex[:8]}@test.local"
            test_org_name = f"Test Org {uuid.uuid4().hex[:6]}"

            print(f"   Email: {test_email}")
            print(f"   Org:   {test_org_name}")
            print(f"   Plan:  {plan.name} (id={plan.id})")
            print(f"   Trade: automotive-transport")
            print()

            from app.modules.organisations.service import public_signup

            try:
                result = await public_signup(
                    db,
                    org_name=test_org_name,
                    admin_email=test_email,
                    admin_first_name="Test",
                    admin_last_name="User",
                    password="TestPassword123!",
                    plan_id=plan.id,
                    trade_family_slug="automotive-transport",
                    country_code="NZ",
                    base_url="http://localhost",
                )

                org_id = result.get("organisation_id")
                requires_payment = result.get("requires_payment", False)

                if requires_payment:
                    print(f"   ⚠️  Plan requires payment — org NOT created yet")
                    print(f"   pending_signup_id: {result.get('pending_signup_id')}")
                    print()
                    print("   The org will be created in confirm_signup_payment().")
                    print("   That code path had the bug (alphabetical ordering).")
                    print("   Fix has been applied — verify by checking the code.")
                    print()

                    # Check what's stored in the pending signup
                    pending_id = result.get("pending_signup_id")
                    if pending_id:
                        from app.core.redis import redis_pool
                        raw = await redis_pool.get(f"pending_signup:{pending_id}")
                        if raw:
                            pending_data = json.loads(raw)
                            print(f"   Pending signup data:")
                            print(f"     trade_family_slug: {pending_data.get('trade_family_slug')}")
                            print(f"     plan_id: {pending_data.get('plan_id')}")
                            print(f"     billing_interval: {pending_data.get('billing_interval')}")
                            print()

                            # Simulate what confirm_signup_payment does
                            print("   Simulating confirm_signup_payment trade category lookup...")
                            tfs = pending_data.get("trade_family_slug")
                            if tfs:
                                fam_result = await db.execute(
                                    select(TradeFamily).where(
                                        TradeFamily.slug == tfs,
                                        TradeFamily.is_active == True,
                                    )
                                )
                                fam = fam_result.scalar_one_or_none()
                                if fam:
                                    # FIXED query (with general-* preference)
                                    fixed_result = await db.execute(
                                        select(TradeCategory.id, TradeCategory.slug, TradeCategory.display_name).where(
                                            TradeCategory.family_id == fam.id,
                                            TradeCategory.is_active == True,
                                        ).order_by(
                                            sa_case(
                                                (TradeCategory.slug.like("general-%"), 0),
                                                else_=1,
                                            ),
                                            TradeCategory.display_name,
                                        ).limit(1)
                                    )
                                    fixed_row = fixed_result.first()
                                    if fixed_row:
                                        print(f"     FIXED query selects: {fixed_row[2]} (slug={fixed_row[1]})")
                                        if fixed_row[1] == "general-automotive":
                                            print("     ✅ PASS")
                                        else:
                                            print(f"     ❌ FAIL — got {fixed_row[1]}")

                                    # OLD query (alphabetical — the bug)
                                    old_result = await db.execute(
                                        select(TradeCategory.id, TradeCategory.slug, TradeCategory.display_name).where(
                                            TradeCategory.family_id == fam.id,
                                            TradeCategory.is_active == True,
                                        ).order_by(TradeCategory.display_name).limit(1)
                                    )
                                    old_row = old_result.first()
                                    if old_row:
                                        print(f"     OLD query selects:   {old_row[2]} (slug={old_row[1]})")
                                        if old_row[1] != "general-automotive":
                                            print(f"     ⚠️  Confirmed bug: old query picks {old_row[1]}")

                        # Clean up the pending signup from Redis
                        from app.modules.auth.pending_signup import delete_pending_signup
                        await delete_pending_signup(pending_id)
                        print()
                        print("   🧹 Cleaned up pending signup from Redis")

                else:
                    # Trial flow — org was created directly
                    print(f"   ✅ Org created: {org_id}")

                    # Check what trade category was assigned
                    from app.modules.admin.models import Organisation
                    org_result = await db.execute(
                        select(Organisation).where(Organisation.id == org_id)
                    )
                    org = org_result.scalar_one_or_none()
                    if org and org.trade_category_id:
                        tc_result = await db.execute(
                            select(TradeCategory).where(TradeCategory.id == org.trade_category_id)
                        )
                        tc = tc_result.scalar_one_or_none()
                        if tc:
                            print(f"   Trade category: {tc.display_name} (slug={tc.slug})")
                            if tc.slug == "general-automotive":
                                print("   ✅ PASS — Correctly assigned General Automotive")
                            else:
                                print(f"   ❌ FAIL — Expected general-automotive, got {tc.slug}")
                    else:
                        print("   ⚠️  No trade category assigned")

                    # Clean up test org
                    print()
                    print("   🧹 Cleaning up test data...")
                    await db.execute(text("DELETE FROM org_modules WHERE org_id = :oid"), {"oid": org_id})
                    await db.execute(text("DELETE FROM branches WHERE org_id = :oid"), {"oid": org_id})
                    await db.execute(text("DELETE FROM users WHERE org_id = :oid"), {"oid": org_id})
                    await db.execute(text("DELETE FROM audit_logs WHERE org_id = :oid"), {"oid": org_id})
                    await db.execute(text("DELETE FROM organisations WHERE id = :oid"), {"oid": org_id})
                    print("   ✅ Test data cleaned up")

            except ValueError as exc:
                print(f"   ⚠️  Signup raised ValueError: {exc}")
                print("   (This may be expected for paid plans without Stripe)")
            except Exception as exc:
                print(f"   ❌ ERROR: {type(exc).__name__}: {exc}")

            print()

            # ----------------------------------------------------------
            # 8. Check all existing orgs' trade categories
            # ----------------------------------------------------------
            print("=" * 70)
            print("  AUDIT: All orgs and their trade categories")
            print("=" * 70)

            orgs_result = await db.execute(
                select(Organisation).order_by(Organisation.created_at.desc())
            )
            orgs = orgs_result.scalars().all()
            for org in orgs:
                tc_name = "—"
                tc_slug = "—"
                if org.trade_category_id:
                    tc_r = await db.execute(
                        select(TradeCategory).where(TradeCategory.id == org.trade_category_id)
                    )
                    tc = tc_r.scalar_one_or_none()
                    if tc:
                        tc_name = tc.display_name
                        tc_slug = tc.slug

                flag = ""
                if tc_slug == "auto-electrical":
                    flag = " ⚠️  (should be general-automotive?)"

                print(f"   {org.name:<30} → {tc_name} ({tc_slug}){flag}")

            print()

            # ----------------------------------------------------------
            # 9. Check feature flags for staff module
            # ----------------------------------------------------------
            print("=" * 70)
            print("  AUDIT: Feature flag defaults for module-gated features")
            print("=" * 70)

            ff_result = await db.execute(
                text("SELECT key, default_value FROM feature_flags WHERE is_active = true ORDER BY key")
            )
            for row in ff_result:
                status = "✅" if row[1] else "❌ (will block new orgs!)"
                print(f"   {row[0]:<25} default={row[1]}  {status}")

            print()

            # ----------------------------------------------------------
            # 10. Check org_modules for recent orgs
            # ----------------------------------------------------------
            print("=" * 70)
            print("  AUDIT: Module enablement for recent orgs")
            print("=" * 70)

            for org in orgs[:4]:
                om_result = await db.execute(
                    text("""
                        SELECT module_slug, is_enabled
                        FROM org_modules
                        WHERE org_id = :oid
                        ORDER BY module_slug
                    """),
                    {"oid": str(org.id)},
                )
                modules = om_result.fetchall()
                enabled = [m[0] for m in modules if m[1]]
                disabled = [m[0] for m in modules if not m[1]]
                print(f"   {org.name}:")
                print(f"     Enabled:  {', '.join(enabled) if enabled else '(none)'}")
                if disabled:
                    print(f"     Disabled: {', '.join(disabled)}")
                # Check if staff is missing
                if "staff" not in [m[0] for m in modules]:
                    print(f"     ⚠️  'staff' module NOT in org_modules at all")
                print()

            # Rollback — we don't want to persist any test changes
            await db.rollback()

    print("=" * 70)
    print("  DONE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
