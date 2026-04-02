"""FastAPI application factory and middleware registration."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.rbac import RBACMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.tenant import TenantMiddleware
from app.middleware.api_version import APIVersionMiddleware
from app.middleware.idempotency import IdempotencyMiddleware
from app.middleware.modules import ModuleMiddleware
from app.middleware.feature_flags import FeatureFlagMiddleware
from app.core.pen_test_mode import PenTestMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance."""
    is_dev = settings.environment == "development"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if is_dev else None,
        redoc_url="/redoc" if is_dev else None,
        openapi_url="/openapi.json" if is_dev else None,
    )

    # ------------------------------------------------------------------
    # Global exception handlers — catch unhandled errors and return JSON
    # instead of bare 500 responses.
    # ------------------------------------------------------------------

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        logger.error("Database error on %s %s: %s", request.method, request.url.path, exc)
        detail = str(exc.orig) if hasattr(exc, "orig") and exc.orig else str(exc)

        # Persist to error_log table (best-effort, don't cascade on DB errors)
        try:
            import traceback as tb
            from app.core.errors import log_error, Severity, Category
            from app.core.database import async_session_factory
            async with async_session_factory() as session:
                await log_error(
                    session,
                    severity=Severity.ERROR,
                    category=Category.DATA,
                    module="sqlalchemy",
                    function_name="exception_handler",
                    message=f"Database error: {detail[:500]}",
                    stack_trace=tb.format_exc()[:2000],
                    org_id=getattr(request.state, "org_id", None) if hasattr(request, "state") else None,
                    user_id=getattr(request.state, "user_id", None) if hasattr(request, "state") else None,
                    http_method=request.method,
                    http_endpoint=request.url.path,
                )
                await session.commit()
        except Exception:
            pass  # Don't log failure-to-log — avoids cascade

        if not settings.debug:
            detail = "A database error occurred"
        return JSONResponse(
            status_code=503,
            content={"detail": detail, "error_type": "database_error"},
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
        detail = str(exc) if settings.debug else "Internal server error"

        # Persist to error_log table (best-effort)
        try:
            import traceback as tb
            from app.core.errors import log_error, Severity, Category
            from app.core.database import async_session_factory
            async with async_session_factory() as session:
                await log_error(
                    session,
                    severity=Severity.ERROR,
                    category=None,
                    module=type(exc).__module__ or "unknown",
                    function_name=type(exc).__name__,
                    message=str(exc)[:500],
                    stack_trace=tb.format_exc()[:2000],
                    org_id=getattr(request.state, "org_id", None) if hasattr(request, "state") else None,
                    user_id=getattr(request.state, "user_id", None) if hasattr(request, "state") else None,
                    http_method=request.method,
                    http_endpoint=request.url.path,
                )
                await session.commit()
        except Exception:
            pass  # Don't log failure-to-log

        return JSONResponse(
            status_code=500,
            content={"detail": detail, "error_type": "internal_error"},
        )

    # ------------------------------------------------------------------
    # Middleware stack (order matters — outermost first, innermost last).
    #
    # Starlette processes middleware in *reverse* registration order for
    # the request path, so the LAST middleware added is the FIRST to run
    # on an incoming request.  We register in this order:
    #
    #   1. CORS            (outermost — handles preflight)
    #   2. APIVersion       (deprecation headers / 410 enforcement)
    #   3. SecurityHeaders  (adds headers on every response)
    #   3b. PenTest         (diagnostic headers when PEN_TEST_MODE set)
    #   4. RateLimit        (reject before heavy processing)
    #   5. Auth             (decode JWT, populate request.state)
    #   6. RBAC             (enforce role-based path access)
    #   7. FeatureFlag      (gate endpoints by feature flag evaluation)
    #   8. Idempotency      (check/store idempotency keys)
    #   9. Module           (check module enablement per org)
    #  10. Tenant           (set org context for RLS)
    #
    # Because Starlette reverses the order, we add them bottom-up:
    # ------------------------------------------------------------------

    # 10 → registered first so it runs last (innermost)
    app.add_middleware(TenantMiddleware)

    # 10.5 — HA standby write protection (reject writes on standby)
    from app.modules.ha.middleware import StandbyWriteProtectionMiddleware
    app.add_middleware(StandbyWriteProtectionMiddleware)

    # 10.6 — Branch context (validates X-Branch-Id header, needs org_id from Auth)
    from app.core.branch_context import BranchContextMiddleware
    app.add_middleware(BranchContextMiddleware)

    # 9
    app.add_middleware(ModuleMiddleware)

    # 8
    app.add_middleware(IdempotencyMiddleware)

    # 7
    app.add_middleware(FeatureFlagMiddleware)

    # 6
    app.add_middleware(RBACMiddleware)

    # 5
    app.add_middleware(AuthMiddleware)

    # 4
    app.add_middleware(RateLimitMiddleware)

    # 3b — pen-test diagnostic headers (no-op in production)
    app.add_middleware(PenTestMiddleware)

    # 3
    app.add_middleware(SecurityHeadersMiddleware)

    # 2
    app.add_middleware(APIVersionMiddleware)

    # 1 → registered last so it runs first (outermost)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Ensure all ORM models are imported so SQLAlchemy can resolve
    # string-based relationship references (e.g. "Organisation" in
    # FleetAccount.organisation).  Without this, lazy mapper resolution
    # fails with InvalidRequestError when a relationship is first
    # accessed via selectinload.
    # ------------------------------------------------------------------
    from app.modules.auth import models as _auth_models  # noqa: F401
    from app.modules.admin import models as _admin_models  # noqa: F401
    from app.modules.organisations import models as _org_models  # noqa: F401
    from app.modules.customers import models as _customer_models  # noqa: F401
    from app.modules.suppliers import models as _supplier_models  # noqa: F401
    from app.modules.catalogue import models as _catalogue_models  # noqa: F401
    from app.modules.catalogue import fluid_oil_models as _fluid_oil_models  # noqa: F401
    from app.modules.inventory import models as _inventory_models  # noqa: F401
    from app.modules.invoices import models as _invoice_models  # noqa: F401
    from app.modules.vehicles import models as _vehicle_models  # noqa: F401
    from app.modules.billing import models as _billing_models  # noqa: F401
    from app.modules.job_cards import models as _job_card_models  # noqa: F401
    from app.modules.staff import models as _staff_models  # noqa: F401
    from app.modules.sms_chat import models as _sms_chat_models  # noqa: F401
    from app.modules.ha import models as _ha_models  # noqa: F401
    from app.modules.stock import models as _stock_models  # noqa: F401
    from app.modules.quotes import models as _quote_models  # noqa: F401
    from app.modules.payments import models as _payment_models  # noqa: F401

    # Force SQLAlchemy to resolve all relationship references now,
    # while all models are loaded. This prevents lazy mapper configuration
    # errors during async request handling.
    from sqlalchemy.orm import configure_mappers
    configure_mappers()

    # --- V1 Routers (existing, unchanged) ---
    from app.modules.auth.router import router as auth_router
    from app.modules.admin.router import router as admin_router
    from app.modules.admin.router import coupon_public_router
    from app.modules.organisations.router import router as org_router
    from app.modules.customers.router import router as customers_router
    from app.modules.vehicles.router import router as vehicles_router
    from app.modules.invoices.router import router as invoices_router
    from app.modules.payments.router import router as payments_router
    from app.modules.billing.router import router as billing_router
    from app.modules.catalogue.router import router as catalogue_router
    from app.modules.catalogue.fluid_oil_router import router as fluid_oil_router
    from app.modules.storage.router import router as storage_router
    from app.modules.notifications.router import router as notifications_router
    from app.modules.quotes.router import router as quotes_router
    from app.modules.job_cards.router import router as job_cards_router
    from app.modules.bookings.router import router as bookings_router
    from app.modules.time_tracking.router import router as time_tracking_router
    from app.modules.inventory.router import router as inventory_router
    from app.modules.inventory.stock_items_router import router as stock_items_router
    from app.modules.inventory.transfer_router import router as transfer_router
    from app.modules.reports.router import router as reports_router
    from app.modules.portal.router import router as portal_router
    from app.modules.data_io.router import router as data_io_router
    from app.modules.webhooks.router import router as webhooks_router
    from app.modules.accounting.router import router as accounting_router
    from app.modules.kiosk.router import router as kiosk_router
    from app.modules.scheduling.router import router as scheduling_router

    app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])
    app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])
    app.include_router(coupon_public_router, prefix="/api/v1/coupons", tags=["coupons"])
    app.include_router(org_router, prefix="/api/v1/org", tags=["organisations"])
    app.include_router(customers_router, prefix="/api/v1/customers", tags=["customers"])
    app.include_router(vehicles_router, prefix="/api/v1/vehicles", tags=["vehicles"])
    app.include_router(invoices_router, prefix="/api/v1/invoices", tags=["invoices"])
    app.include_router(payments_router, prefix="/api/v1/payments", tags=["payments"])
    app.include_router(billing_router, prefix="/api/v1/billing", tags=["billing"])
    app.include_router(catalogue_router, prefix="/api/v1/catalogue", tags=["catalogue"])
    app.include_router(fluid_oil_router, prefix="/api/v1/catalogue/fluids", tags=["catalogue-fluids"])
    app.include_router(storage_router, prefix="/api/v1/storage", tags=["storage"])
    app.include_router(notifications_router, prefix="/api/v1/notifications", tags=["notifications"])
    app.include_router(quotes_router, prefix="/api/v1/quotes", tags=["quotes"])
    app.include_router(job_cards_router, prefix="/api/v1/job-cards", tags=["job-cards"])
    app.include_router(bookings_router, prefix="/api/v1/bookings", tags=["bookings"])
    app.include_router(time_tracking_router, prefix="/api/v1/job-cards", tags=["time-tracking"])
    app.include_router(inventory_router, prefix="/api/v1/inventory", tags=["inventory"])
    app.include_router(stock_items_router, prefix="/api/v1/inventory/stock-items", tags=["stock-items"])
    app.include_router(transfer_router, prefix="/api/v1/inventory/transfers", tags=["stock-transfers"])
    app.include_router(reports_router, prefix="/api/v1/reports", tags=["reports"])
    app.include_router(portal_router, prefix="/api/v1/portal", tags=["portal"])
    app.include_router(data_io_router, prefix="/api/v1/data", tags=["data-import-export"])
    app.include_router(webhooks_router, prefix="/api/v1/webhooks", tags=["webhooks"])
    app.include_router(accounting_router, prefix="/api/v1/org/accounting", tags=["accounting"])
    app.include_router(kiosk_router, prefix="/api/v1/kiosk", tags=["kiosk"])
    app.include_router(scheduling_router, prefix="/api/v1/scheduling", tags=["scheduling"])

    # --- Claims module ---
    from app.modules.claims.router import router as claims_router
    from app.modules.claims.router import customer_claims_router
    app.include_router(claims_router, prefix="/api/v1/claims", tags=["claims"])
    app.include_router(customer_claims_router, prefix="/api/v1/customers", tags=["customer-claims"])

    # --- Dashboard (branch-scoped metrics) ---
    from app.modules.organisations.dashboard_router import router as dashboard_router
    app.include_router(dashboard_router, prefix="/api/v1/dashboard", tags=["dashboard"])

    # --- V2 Routers (universal platform) ---
    # Existing V1 modules are also available under /api/v2/ for continuity.
    # Deduplicated: use a loop instead of repeating include_router calls.
    _V1_ROUTERS_FOR_V2 = [
        (auth_router, "/api/v2/auth", "v2-auth"),
        (admin_router, "/api/v2/admin", "v2-admin"),
        (org_router, "/api/v2/org", "v2-organisations"),
        (customers_router, "/api/v2/customers", "v2-customers"),
        (invoices_router, "/api/v2/invoices", "v2-invoices"),
        (payments_router, "/api/v2/payments", "v2-payments"),
        (billing_router, "/api/v2/billing", "v2-billing"),
        (catalogue_router, "/api/v2/catalogue", "v2-catalogue"),
        (storage_router, "/api/v2/storage", "v2-storage"),
        (notifications_router, "/api/v2/notifications", "v2-notifications"),
        (quotes_router, "/api/v2/quotes", "v2-quotes"),
        (bookings_router, "/api/v2/bookings", "v2-bookings"),
        (inventory_router, "/api/v2/inventory", "v2-inventory"),
        (reports_router, "/api/v2/reports", "v2-reports"),
        (webhooks_router, "/api/v2/webhooks", "v2-webhooks"),
        (accounting_router, "/api/v2/org/accounting", "v2-accounting"),
        (portal_router, "/api/v2/portal", "v2-portal"),
    ]
    for _v2_router, _v2_prefix, _v2_tag in _V1_ROUTERS_FOR_V2:
        app.include_router(_v2_router, prefix=_v2_prefix, tags=[_v2_tag])
    # --- New universal-platform module routers ---
    from app.modules.feature_flags.router import admin_router as ff_admin_router
    from app.modules.feature_flags.router import org_router as ff_org_router
    from app.modules.module_management.router import router as module_mgmt_router

    from app.modules.terminology.router import router as terminology_router
    from app.modules.trade_categories.router import (
        families_router as tc_families_router,
        categories_router as tc_categories_router,
        admin_families_router as tc_admin_families_router,
        admin_categories_router as tc_admin_categories_router,
    )

    app.include_router(ff_admin_router, prefix="/api/v2/admin/flags", tags=["v2-feature-flags-admin"])
    app.include_router(ff_org_router, prefix="/api/v2/flags", tags=["v2-feature-flags"])
    app.include_router(module_mgmt_router, prefix="/api/v2/modules", tags=["v2-modules"])
    app.include_router(terminology_router, prefix="/api/v2/terminology", tags=["v2-terminology"])
    app.include_router(tc_families_router, prefix="/api/v2/trade-families", tags=["v2-trade-families"])
    app.include_router(tc_categories_router, prefix="/api/v2/trade-categories", tags=["v2-trade-categories"])
    app.include_router(tc_admin_families_router, prefix="/api/v2/admin/trade-families", tags=["v2-admin-trade-families"])
    app.include_router(tc_admin_categories_router, prefix="/api/v2/admin/trade-categories", tags=["v2-admin-trade-categories"])

    from app.modules.compliance_profiles.router import (
        public_router as cp_public_router,
        admin_router as cp_admin_router,
    )
    app.include_router(cp_public_router, prefix="/api/v2/compliance-profiles", tags=["v2-compliance-profiles"])
    app.include_router(cp_admin_router, prefix="/api/v2/admin/compliance-profiles", tags=["v2-admin-compliance-profiles"])

    from app.modules.setup_wizard.router import router as setup_wizard_router
    app.include_router(setup_wizard_router, prefix="/api/v2/setup-wizard", tags=["v2-setup-wizard"])

    # --- Inventory module routers ---
    from app.modules.products.router import router as products_router_v2
    from app.modules.products.category_router import router as product_categories_router
    from app.modules.stock.router import (
        movements_router as stock_movements_router,
        adjustments_router as stock_adjustments_router,
        stocktakes_router as stocktakes_router,
    )
    from app.modules.suppliers.router import router as suppliers_router_v2

    app.include_router(products_router_v2, prefix="/api/v2/products", tags=["v2-products"])
    app.include_router(product_categories_router, prefix="/api/v2/product-categories", tags=["v2-product-categories"])
    app.include_router(stock_movements_router, prefix="/api/v2/stock-movements", tags=["v2-stock-movements"])
    app.include_router(stock_adjustments_router, prefix="/api/v2/stock-adjustments", tags=["v2-stock-adjustments"])
    app.include_router(stocktakes_router, prefix="/api/v2/stocktakes", tags=["v2-stocktakes"])
    app.include_router(suppliers_router_v2, prefix="/api/v2/suppliers", tags=["v2-suppliers"])

    from app.modules.pricing_rules.router import router as pricing_rules_router
    app.include_router(pricing_rules_router, prefix="/api/v2/pricing-rules", tags=["v2-pricing-rules"])

    # --- Jobs module routers ---
    from app.modules.jobs_v2.router import router as jobs_router, templates_router as job_templates_router
    app.include_router(jobs_router, prefix="/api/v2/jobs", tags=["v2-jobs"])
    app.include_router(job_templates_router, prefix="/api/v2/job-templates", tags=["v2-job-templates"])

    # --- Quotes module routers ---
    from app.modules.quotes_v2.router import router as quotes_v2_router, public_router as quotes_public_router
    app.include_router(quotes_v2_router, prefix="/api/v2/quotes", tags=["v2-quotes-v2"])
    app.include_router(quotes_public_router, prefix="/api/v2/public/quotes", tags=["v2-public-quotes"])

    # --- Time tracking module routers ---
    from app.modules.time_tracking_v2.router import router as time_tracking_v2_router
    app.include_router(time_tracking_v2_router, prefix="/api/v2/time-entries", tags=["v2-time-entries"])

    # --- Projects module routers ---
    from app.modules.projects.router import router as projects_router
    app.include_router(projects_router, prefix="/api/v2/projects", tags=["v2-projects"])

    # --- Expenses module routers ---
    from app.modules.expenses.router import router as expenses_router
    app.include_router(expenses_router, prefix="/api/v2/expenses", tags=["v2-expenses"])

    # --- Uploads module routers ---
    from app.modules.uploads.router import router as uploads_router
    app.include_router(uploads_router, prefix="/api/v2/uploads", tags=["v2-uploads"])

    # --- Purchase orders module routers ---
    from app.modules.purchase_orders.router import router as purchase_orders_router
    app.include_router(purchase_orders_router, prefix="/api/v2/purchase-orders", tags=["v2-purchase-orders"])

    # --- Staff module routers ---
    from app.modules.staff.router import router as staff_router
    app.include_router(staff_router, prefix="/api/v2/staff", tags=["v2-staff"])

    # --- Scheduling module routers ---
    from app.modules.scheduling_v2.router import router as scheduling_router
    app.include_router(scheduling_router, prefix="/api/v2/schedule", tags=["v2-schedule"])

    # --- Bookings module routers ---
    from app.modules.bookings_v2.router import (
        router as bookings_v2_router,
        public_router as bookings_public_router,
        rules_router as booking_rules_router,
    )
    app.include_router(bookings_v2_router, prefix="/api/v2/bookings", tags=["v2-bookings-v2"])
    app.include_router(bookings_public_router, prefix="/api/v2/public/bookings", tags=["v2-public-bookings"])
    app.include_router(booking_rules_router, prefix="/api/v2/booking-rules", tags=["v2-booking-rules"])

    # --- POS module routers ---
    from app.modules.pos.router import router as pos_router
    app.include_router(pos_router, prefix="/api/v2/pos", tags=["v2-pos"])

    # --- Receipt printer module routers ---
    from app.modules.receipt_printer.router import router as receipt_printer_router
    app.include_router(receipt_printer_router, prefix="/api/v2/printers", tags=["v2-printers"])

    # --- Tables module routers ---
    from app.modules.tables.router import router as tables_router
    app.include_router(tables_router, prefix="/api/v2/tables", tags=["v2-tables"])

    # --- Kitchen display module routers ---
    from app.modules.kitchen_display.router import router as kitchen_router
    app.include_router(kitchen_router, prefix="/api/v2/kitchen", tags=["v2-kitchen"])

    # --- Kitchen display WebSocket ---
    from app.modules.kitchen_display.websocket import ws_router as kitchen_ws_router
    app.include_router(kitchen_ws_router)

    # --- Tipping module routers ---
    from app.modules.tipping.router import router as tipping_router
    app.include_router(tipping_router, prefix="/api/v2/tips", tags=["v2-tips"])

    # --- Recurring invoices module routers ---
    from app.modules.recurring_invoices.router import router as recurring_router
    app.include_router(recurring_router, prefix="/api/v2/recurring", tags=["v2-recurring"])

    # --- Progress claims module routers ---
    from app.modules.progress_claims.router import router as progress_claims_router
    app.include_router(progress_claims_router, prefix="/api/v2/progress-claims", tags=["v2-progress-claims"])

    # --- Variation orders module routers ---
    from app.modules.variations.router import router as variations_router
    app.include_router(variations_router, prefix="/api/v2/variations", tags=["v2-variations"])

    # --- Retention tracking module routers ---
    from app.modules.retentions.router import router as retentions_router
    app.include_router(retentions_router, prefix="/api/v2/retentions", tags=["v2-retentions"])

    # --- Compliance documents module routers ---
    from app.modules.compliance_docs.router import router as compliance_docs_router
    app.include_router(compliance_docs_router, prefix="/api/v2/compliance-docs", tags=["v2-compliance-docs"])

    # --- Ecommerce module routers ---
    from app.modules.ecommerce.router import router as ecommerce_router
    app.include_router(ecommerce_router, prefix="/api/v2/ecommerce", tags=["v2-ecommerce"])

    # --- Multi-currency module routers ---
    from app.modules.multi_currency.router import router as multi_currency_router
    app.include_router(multi_currency_router, prefix="/api/v2/currencies", tags=["v2-currencies"])

    # --- Loyalty module routers ---
    from app.modules.loyalty.router import router as loyalty_router
    app.include_router(loyalty_router, prefix="/api/v2/loyalty", tags=["v2-loyalty"])

    # --- Outbound webhooks module routers ---
    from app.modules.webhooks_v2.router import router as webhooks_v2_router
    app.include_router(webhooks_v2_router, prefix="/api/v2/outbound-webhooks", tags=["v2-outbound-webhooks"])

    # --- Franchise & multi-location module routers ---
    from app.modules.franchise.router import (
        locations_router,
        transfers_router,
        franchise_router,
    )
    app.include_router(locations_router, prefix="/api/v2/locations", tags=["v2-locations"])
    app.include_router(transfers_router, prefix="/api/v2/stock-transfers", tags=["v2-stock-transfers"])
    app.include_router(franchise_router, prefix="/api/v2/franchise", tags=["v2-franchise"])

    # --- Global Admin analytics routers ---
    from app.modules.admin.analytics_router import router as analytics_router
    app.include_router(analytics_router, prefix="/api/v2/admin/analytics", tags=["v2-admin-analytics"])

    # --- Platform notifications routers ---
    from app.modules.admin.notifications_router import (
        admin_router as notif_admin_router,
        org_router as notif_org_router,
    )
    app.include_router(notif_admin_router, prefix="/api/v2/admin/notifications", tags=["v2-admin-notifications"])
    app.include_router(notif_org_router, prefix="/api/v2/notifications", tags=["v2-notifications"])

    # --- Migration tool routers ---
    from app.modules.admin.migration_router import router as migration_router
    app.include_router(migration_router, prefix="/api/v2/admin/migrations", tags=["v2-admin-migrations"])

    # --- Live database migration router ---
    from app.modules.admin.live_migration_router import router as live_migration_router
    app.include_router(live_migration_router, prefix="/api/v1/admin/migration", tags=["admin-live-migration"])

    # --- HA Replication router ---
    from app.modules.ha.router import router as ha_router
    app.include_router(ha_router, prefix="/api/v1/ha", tags=["ha"])

    # --- I18n module routers ---
    from app.modules.i18n.router import router as i18n_router
    app.include_router(i18n_router, prefix="/api/v2/i18n", tags=["v2-i18n"])

    # --- Branding module routers ---
    from app.modules.branding.router import router as branding_router, public_router as branding_public_router
    app.include_router(branding_router, prefix="/api/v2/admin/branding", tags=["v2-admin-branding"])
    app.include_router(branding_public_router, prefix="/api/v1/public/branding", tags=["public-branding"])

    # --- Asset tracking module routers ---
    from app.modules.assets.router import router as assets_router
    app.include_router(assets_router, prefix="/api/v2/assets", tags=["v2-assets"])

    # --- Enhanced reports (v2) ---
    from app.modules.reports_v2.router import router as reports_v2_router
    app.include_router(reports_v2_router, prefix="/api/v2/reports", tags=["v2-reports-v2"])

    # --- SMS Verification Providers ---
    from app.modules.sms_providers.router import router as sms_providers_router
    app.include_router(sms_providers_router, prefix="/api/v2/admin/sms-providers", tags=["v2-admin-sms-providers"])

    # --- SMS Chat (Connexus two-way SMS) ---
    from app.modules.sms_chat.router_webhooks import router as sms_webhooks_router
    from app.modules.sms_chat.router import router as sms_chat_router
    from app.modules.sms_chat.router_admin import router as sms_chat_admin_router

    app.include_router(sms_webhooks_router, tags=["v2-sms-webhooks"])
    app.include_router(sms_chat_router, prefix="/api/v2", tags=["v2-sms-chat"])
    app.include_router(sms_chat_admin_router, prefix="/api/v2", tags=["v2-admin-connexus"])

    # --- Email Providers ---
    from app.modules.email_providers.router import router as email_providers_router
    app.include_router(email_providers_router, prefix="/api/v2/admin/email-providers", tags=["v2-admin-email-providers"])

    # --- Public (no-auth) invoice sharing ---
    from app.modules.invoices.public_router import router as public_invoice_router
    app.include_router(public_invoice_router, prefix="/api/v1/public/invoice", tags=["public"])

    # --- Public (no-auth) quote acceptance ---
    from app.modules.quotes.public_router import router as public_quote_router
    app.include_router(public_quote_router, prefix="/api/v1/public/quotes", tags=["public-quotes"])

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    # --- Startup event: warm Redis caches ---
    @app.on_event("startup")
    async def _warm_caches() -> None:
        from app.core.cache_warming import warm_all_caches
        await warm_all_caches()

    @app.on_event("startup")
    async def _sync_demo_org() -> None:
        from app.core.demo_org_sync import sync_demo_org_modules
        await sync_demo_org_modules()

    @app.on_event("startup")
    async def _start_connexus_token_refresher() -> None:
        from app.integrations.connexus_sms import _token_refresher
        await _token_refresher.start()

    @app.on_event("startup")
    async def _start_task_scheduler() -> None:
        from app.tasks.scheduled import start_scheduler
        await start_scheduler()

    @app.on_event("startup")
    async def _start_ha_heartbeat() -> None:
        from app.modules.ha.service import HAService
        from app.modules.ha.middleware import set_node_role
        from app.core.database import async_session_factory
        try:
            async with async_session_factory() as session:
                async with session.begin():
                    config = await HAService.get_config(session)
                    if config is not None:
                        set_node_role(config.role, config.peer_endpoint)
                        # Start heartbeat if peer is configured
                        if config.peer_endpoint:
                            import os
                            from app.modules.ha.heartbeat import HeartbeatService
                            from app.modules.ha import service as ha_svc_module
                            secret = os.environ.get("HA_HEARTBEAT_SECRET", "")
                            hb = HeartbeatService(
                                peer_endpoint=config.peer_endpoint,
                                interval=config.heartbeat_interval_seconds,
                                secret=secret,
                            )
                            ha_svc_module._heartbeat_service = hb
                            await hb.start()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Could not initialize HA on startup: %s", exc,
            )

    @app.on_event("shutdown")
    async def _stop_connexus_token_refresher() -> None:
        from app.integrations.connexus_sms import _token_refresher
        await _token_refresher.stop()

    @app.on_event("shutdown")
    async def _stop_task_scheduler() -> None:
        from app.tasks.scheduled import stop_scheduler
        await stop_scheduler()

    @app.on_event("shutdown")
    async def _stop_ha_heartbeat() -> None:
        from app.modules.ha.service import get_heartbeat_service
        hb = get_heartbeat_service()
        if hb is not None:
            await hb.stop()

    return app


app = create_app()
