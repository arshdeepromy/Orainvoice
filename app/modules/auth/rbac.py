"""Role-Based Access Control (RBAC) dependencies for FastAPI.

Provides FastAPI dependency factories that enforce role-based access on
route handlers. Three roles are supported:

- **global_admin**: Platform management only. Denied org-level customer/invoice data.
- **org_admin**: All salesperson access + org settings, billing, user management,
  catalogue config. Denied global admin endpoints.
- **salesperson**: Customer, vehicle, invoice, payment, quote, job card, booking
  endpoints. Denied org settings, billing, user management, catalogue config.

Usage::

    from app.modules.auth.rbac import require_role, require_any_org_role

    @router.get("/settings", dependencies=[Depends(require_role("org_admin"))])
    async def get_settings(): ...

    @router.get("/invoices", dependencies=[Depends(require_any_org_role())])
    async def list_invoices(): ...

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request


# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------

GLOBAL_ADMIN = "global_admin"
FRANCHISE_ADMIN = "franchise_admin"
ORG_ADMIN = "org_admin"
LOCATION_MANAGER = "location_manager"
SALESPERSON = "salesperson"
STAFF_MEMBER = "staff_member"

ALL_ROLES = {GLOBAL_ADMIN, FRANCHISE_ADMIN, ORG_ADMIN, LOCATION_MANAGER, SALESPERSON, STAFF_MEMBER}

# ---------------------------------------------------------------------------
# Permission-based RBAC
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "global_admin": ["*"],
    "franchise_admin": ["franchise.read", "reports.read"],
    "org_admin": ["org.*", "users.*", "modules.*", "settings.*", "reports.*", "billing.*"],
    "location_manager": [
        "invoices.*", "customers.*", "jobs.*", "inventory.*", "staff.*",
        "scheduling.*", "bookings.*", "pos.*", "reports.read",
    ],
    "salesperson": [
        "invoices.create", "invoices.read", "invoices.update",
        "customers.create", "customers.read", "customers.update",
        "jobs.create", "jobs.read", "jobs.update",
        "quotes.create", "quotes.read", "quotes.update",
        "time_entries.create", "time_entries.read", "time_entries.update",
        "expenses.create", "expenses.read",
        "pos.transact", "bookings.read",
    ],
    "staff_member": [
        "jobs.read_assigned", "time_entries.own", "schedule.own",
        "job_attachments.upload",
    ],
}


def has_permission(role: str, permission: str, overrides: list[dict] | None = None) -> bool:
    """Check if a role has a specific permission, considering overrides.

    Parameters
    ----------
    role:
        The user's base role.
    permission:
        The permission key to check (e.g. "invoices.create").
    overrides:
        Optional list of permission override dicts with keys
        ``permission_key`` and ``is_granted``.

    Returns True if the permission is granted.
    """
    # Check overrides first (they take precedence)
    if overrides:
        for override in overrides:
            if override.get("permission_key") == permission:
                return override.get("is_granted", False)

    # Check base role permissions
    role_perms = ROLE_PERMISSIONS.get(role, [])
    if "*" in role_perms:
        return True

    # Check exact match
    if permission in role_perms:
        return True

    # Check wildcard match (e.g. "invoices.*" matches "invoices.create")
    perm_domain = permission.split(".")[0] if "." in permission else permission
    if f"{perm_domain}.*" in role_perms:
        return True

    return False

# ---------------------------------------------------------------------------
# Endpoint path classification
#
# These define which path prefixes are restricted to specific roles.
# The RBAC dependency checks the *requesting user's role* against the
# endpoint being accessed.
# ---------------------------------------------------------------------------

# Paths only Global Admins may access
GLOBAL_ADMIN_ONLY_PREFIXES: tuple[str, ...] = (
    "/api/v1/admin/",
    "/api/v2/admin/",
)

# Paths that Global Admins are DENIED (org-level customer/invoice data)
GLOBAL_ADMIN_DENIED_PREFIXES: tuple[str, ...] = (
    "/api/v1/customers/",
    "/api/v1/customers",
    "/api/v1/invoices/",
    "/api/v1/invoices",
    "/api/v1/vehicles/",
    "/api/v1/vehicles",
    "/api/v1/payments/",
    "/api/v1/payments",
    "/api/v1/quotes/",
    "/api/v1/quotes",
    "/api/v1/job-cards/",
    "/api/v1/job-cards",
    "/api/v1/bookings/",
    "/api/v1/bookings",
)

# Paths that Salesperson is DENIED (org settings, billing, user management, catalogue)
SALESPERSON_DENIED_PREFIXES: tuple[str, ...] = (
    "/api/v1/org/users",
    "/api/v1/billing/",
    "/api/v1/billing",
    "/api/v1/catalogue/",
    "/api/v1/catalogue",
    "/api/v1/admin/",
)

# Paths where salesperson is denied write access (PUT/POST/DELETE) but
# allowed read access (GET). Endpoint-level RBAC handles the fine-grained
# method check via require_role dependencies.
SALESPERSON_DENIED_WRITE_PREFIXES: tuple[str, ...] = (
    "/api/v1/org/settings",
    "/api/v1/org/branches",
)

# Franchise admin: read-only access to aggregate reports only
FRANCHISE_ADMIN_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/api/v2/franchise/",
    "/api/v2/reports/",
    "/api/v1/admin/reports",
)

# Staff member: only allowed to access own jobs, time entries, schedule
STAFF_MEMBER_ALLOWED_PREFIXES: tuple[str, ...] = (
    "/api/v2/jobs/",
    "/api/v2/jobs",
    "/api/v2/time-tracking/",
    "/api/v2/time-tracking",
    "/api/v2/schedule/",
    "/api/v2/schedule",
    "/api/v1/job-cards/",
    "/api/v1/job-cards",
)


def _matches_any_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    """Return True if path starts with any of the given prefixes."""
    return any(path.startswith(p) for p in prefixes)


# ---------------------------------------------------------------------------
# Core extraction helper
# ---------------------------------------------------------------------------

def _get_user_context(request: Request) -> tuple[str | None, str | None, str | None]:
    """Extract (user_id, org_id, role) from request.state.

    Returns (None, None, None) for unauthenticated requests.
    """
    user_id = getattr(request.state, "user_id", None)
    org_id = getattr(request.state, "org_id", None)
    role = getattr(request.state, "role", None)
    return user_id, org_id, role


# ---------------------------------------------------------------------------
# Dependency factories
# ---------------------------------------------------------------------------

def require_role(*allowed_roles: str):
    """Return a FastAPI dependency that enforces the user has one of the
    specified roles.

    Example::

        @router.get("/admin/orgs", dependencies=[Depends(require_role("global_admin"))])
        async def list_orgs(): ...
    """
    allowed = set(allowed_roles)

    async def _check(request: Request):
        user_id, org_id, role = _get_user_context(request)

        if not user_id or not role:
            raise HTTPException(status_code=401, detail="Authentication required")

        if role not in allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied. Required role(s): {', '.join(sorted(allowed))}",
            )

        # For org-scoped roles, verify org membership
        if role in (ORG_ADMIN, SALESPERSON, LOCATION_MANAGER, STAFF_MEMBER) and not org_id:
            raise HTTPException(
                status_code=403,
                detail="Organisation membership required",
            )

    return Depends(_check)


def require_any_org_role():
    """Dependency that allows org_admin, salesperson, and location_manager.

    Useful for endpoints accessible to all org-level users with data access
    (e.g. invoices, customers, vehicles).
    """
    return require_role(ORG_ADMIN, SALESPERSON, LOCATION_MANAGER)


def require_global_admin():
    """Dependency that allows only global_admin."""
    return require_role(GLOBAL_ADMIN)


def require_org_admin():
    """Dependency that allows only org_admin."""
    return require_role(ORG_ADMIN)


def require_org_admin_or_global():
    """Dependency that allows org_admin or global_admin."""
    return require_role(ORG_ADMIN, GLOBAL_ADMIN)

def require_any_org_member():
    """Dependency that allows any org-level role (org_admin, salesperson, location_manager, staff_member)."""
    return require_role(ORG_ADMIN, SALESPERSON, LOCATION_MANAGER, STAFF_MEMBER)


def require_location_manager_or_above():
    """Dependency that allows location_manager, org_admin, or global_admin."""
    return require_role(LOCATION_MANAGER, ORG_ADMIN, GLOBAL_ADMIN)


# ---------------------------------------------------------------------------
# Path-based RBAC enforcement (for use as middleware-level check)
# ---------------------------------------------------------------------------

def check_role_path_access(role: str, path: str, method: str = "GET") -> str | None:
    """Check whether the given role is allowed to access the given path.

    Returns None if access is allowed, or an error message string if denied.
    """
    if role == GLOBAL_ADMIN:
        if _matches_any_prefix(path, GLOBAL_ADMIN_DENIED_PREFIXES):
            return "Global admins cannot access organisation-level data"

    elif role == FRANCHISE_ADMIN:
        # Franchise admins can only access aggregate reports and franchise endpoints
        if not _matches_any_prefix(path, FRANCHISE_ADMIN_ALLOWED_PREFIXES):
            return "Franchise admin can only access aggregate reports"
        # Franchise admins are read-only
        if method.upper() != "GET":
            return "Franchise admin has read-only access"

    elif role == STAFF_MEMBER:
        # Staff members can only access their own jobs, time entries, schedule
        if not _matches_any_prefix(path, STAFF_MEMBER_ALLOWED_PREFIXES):
            return "Staff member can only access assigned jobs, time entries, and schedule"

    elif role == LOCATION_MANAGER:
        # Location managers have salesperson-level access + staff/inventory/scheduling
        # but are denied global admin and org admin-only endpoints
        if _matches_any_prefix(path, GLOBAL_ADMIN_ONLY_PREFIXES):
            return "Location managers cannot access global admin endpoints"
        if _matches_any_prefix(path, (
            "/api/v1/org/users",
            "/api/v1/billing/",
            "/api/v1/billing",
        )):
            return "Location managers cannot access billing or user management"

    elif role == SALESPERSON:
        if _matches_any_prefix(path, SALESPERSON_DENIED_PREFIXES):
            return "Salesperson role cannot access this resource"
        # Write-only denied paths: block PUT/POST/DELETE/PATCH but allow GET
        if method.upper() != "GET" and _matches_any_prefix(
            path, SALESPERSON_DENIED_WRITE_PREFIXES
        ):
            return "Salesperson role cannot modify this resource"

    elif role == ORG_ADMIN:
        if _matches_any_prefix(path, GLOBAL_ADMIN_ONLY_PREFIXES):
            return "Organisation admins cannot access global admin endpoints"

    # Unknown roles are denied everything except public paths
    elif role not in ALL_ROLES:
        return f"Unknown role: {role}"

    return None


async def enforce_rbac(request: Request):
    """FastAPI dependency that enforces path-based RBAC on every request.

    This can be added as a global dependency on the app or specific routers
    to automatically check role vs. path access rules.

    Skips enforcement for unauthenticated requests (those are handled by
    the auth middleware).
    """
    user_id, org_id, role = _get_user_context(request)

    # Skip for unauthenticated requests (public paths handled by auth middleware)
    if not user_id or not role:
        return

    path = request.url.path

    # Verify org membership for org-scoped roles
    if role in (ORG_ADMIN, SALESPERSON, LOCATION_MANAGER, STAFF_MEMBER) and not org_id:
        # Org roles must have an org_id in their token
        raise HTTPException(
            status_code=403,
            detail="Organisation membership required",
        )

    # Check path-based access
    denial_reason = check_role_path_access(role, path, method=request.method)
    if denial_reason:
        raise HTTPException(status_code=403, detail=denial_reason)


# ---------------------------------------------------------------------------
# Location-scoped permission enforcement
# ---------------------------------------------------------------------------


class PermissionDenied(Exception):
    """Raised when a user lacks permission for a location-scoped resource."""

    def __init__(self, message: str = "Permission denied"):
        self.message = message
        super().__init__(self.message)


class LocationScopedPermission:
    """Enforce that location_manager users can only access data for their
    assigned locations.

    Usage::

        scope = LocationScopedPermission()
        await scope.check(request, resource_location_id=some_location_id)

    The check reads ``assigned_location_ids`` from ``request.state``
    (populated by AuthMiddleware from JWT claims).

    **Validates: Requirement 8.2, 8.6**
    """

    async def check(
        self,
        request: Request,
        resource_location_id: str | None = None,
    ) -> None:
        """Verify the user has access to the given location.

        Parameters
        ----------
        request:
            The current Starlette/FastAPI request.
        resource_location_id:
            The location_id of the resource being accessed. If None,
            the check is skipped (resource is not location-scoped).

        Raises
        ------
        PermissionDenied
            If the user is a location_manager and the resource's location
            is not in their assigned locations.
        """
        role = getattr(request.state, "role", None)
        if role != LOCATION_MANAGER:
            return

        if resource_location_id is None:
            return

        assigned = getattr(request.state, "assigned_location_ids", None) or []
        if str(resource_location_id) not in [str(loc) for loc in assigned]:
            raise PermissionDenied("Access restricted to assigned locations")


def require_location_scope():
    """FastAPI dependency that enforces location scoping for location_manager.

    Reads ``location_id`` from query params or path params and checks
    against the user's assigned locations.
    """
    scope = LocationScopedPermission()

    async def _check(request: Request):
        # Try to get location_id from path params or query params
        location_id = request.path_params.get("location_id") or request.query_params.get("location_id")
        if location_id:
            await scope.check(request, resource_location_id=location_id)

    return Depends(_check)
