"""Organisation Employee Portal module.

An optional, org-branded self-service portal for an organisation's own staff
members — a deliberate near-clone of the B2B Fleet Portal, but rooted at
``staff_members`` instead of customer fleets.

Portal users authenticate against a dedicated identity store
(``employee_portal_users``) with their own HttpOnly-cookie sessions
(``employee_portal_sessions``) and a dedicated auth/security audit trail
(``employee_portal_audit_log``). The separate session table makes
cross-portal cookie rejection structural: a token minted for the customer
portal, fleet portal, or staff app simply does not exist here.

The portal is reached at ``/e/{slug}`` where ``slug`` is the org's globally
unique, case-insensitive ``organisations.slug``.

Implements: Organisation Employee Portal spec
(.kiro/specs/organisation-employee-portal/).
"""
