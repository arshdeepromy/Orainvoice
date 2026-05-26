"""B2B Fleet Portal module.

Self-service portal for business customers (fleet operators) to manage
their vehicle fleets, invite drivers, run NZTA pre-trip checklists, book
services, request quotes, and manage WOF/COF reminders.

The module is gated behind the ``b2b-fleet-management`` module slug
(depends on ``vehicles``, restricted to the ``automotive-transport``
trade family) and exposes two router surfaces:

- ``router.py``       — ``/fleet/api/*`` for portal users (browser, HttpOnly cookie auth)
- ``admin_router.py`` — ``/api/v2/fleet-portal/admin/*`` for workshop staff (JWT auth)

Implements: B2B Fleet Portal spec (.kiro/specs/b2b-fleet-portal/).
"""
