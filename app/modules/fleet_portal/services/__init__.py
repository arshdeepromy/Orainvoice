"""Fleet Portal service layer.

One service module per domain area:

- :mod:`account_service` — portal user provisioning, invite, revoke
- :mod:`session_service` — session create / destroy / touch
- :mod:`vehicle_service` — fleet vehicle access (admin + driver)
- :mod:`driver_service` — driver invite / assign / activity
- :mod:`checklist_service` — NZTA template seed + submissions
- :mod:`reminder_service` — per-vehicle reminder preferences
- :mod:`booking_service` — service booking requests
- :mod:`quote_service` — quotation requests
- :mod:`invoice_service` — invoice list / detail / PDF (admin-only)
- :mod:`dashboard_service` — summary aggregations
- :mod:`audit_service` — portal_audit_log writers
- :mod:`expiry` — Property 16 badge function

Implements: B2B Fleet Portal spec.
"""

from __future__ import annotations
