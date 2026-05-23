"""Pytest config / fixtures for the fleet_portal test suite.

Pre-loads the full set of model modules so ``configure_mappers()``
succeeds in any test that constructs a ``select()`` against a model
whose relationships reference Organisation/User/Customer/Branch/etc.
Mirrors ``app/main.py``'s model-loading block.
"""

from __future__ import annotations

# Mirror the model-loading block in app/main.py so SQLAlchemy can resolve
# every string-based relationship reference. Without this, tests that
# import a single model can hit InvalidRequestError when SA tries to
# initialise the full mapper graph.
import app.modules.auth.models  # noqa: F401
import app.modules.admin.models  # noqa: F401
import app.modules.organisations.models  # noqa: F401
import app.modules.customers.models  # noqa: F401
import app.modules.suppliers.models  # noqa: F401
import app.modules.catalogue.models  # noqa: F401
import app.modules.catalogue.fluid_oil_models  # noqa: F401
import app.modules.inventory.models  # noqa: F401
import app.modules.invoices.models  # noqa: F401
import app.modules.invoices.attachment_models  # noqa: F401
import app.modules.vehicles.models  # noqa: F401
import app.modules.billing.models  # noqa: F401
import app.modules.job_cards.models  # noqa: F401
import app.modules.service_types.models  # noqa: F401
import app.modules.staff.models  # noqa: F401
import app.modules.sms_chat.models  # noqa: F401
import app.modules.ha.models  # noqa: F401
import app.modules.ha.volume_sync_models  # noqa: F401
import app.modules.stock.models  # noqa: F401
import app.modules.quotes.models  # noqa: F401
import app.modules.payments.models  # noqa: F401
import app.modules.platform_settings.models  # noqa: F401
import app.modules.ledger.models  # noqa: F401
import app.modules.banking.models  # noqa: F401
import app.modules.tax_wallets.models  # noqa: F401
import app.modules.ird.models  # noqa: F401
import app.modules.in_app_notifications.models  # noqa: F401
import app.modules.fleet_portal.models  # noqa: F401
import app.modules.portal.models  # noqa: F401
