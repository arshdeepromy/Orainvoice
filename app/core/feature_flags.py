"""Feature flag evaluation service.

Evaluates feature flags against an organisation context using a priority-based
targeting rule system. Results are cached in Redis with a configurable TTL.

Targeting priority (first match wins):
    org_override → trade_category → trade_family → country → plan_tier → percentage

**Validates: Requirement 2**
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


# ---------------------------------------------------------------------------
# Organisation context for flag evaluation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrgContext:
    """Immutable snapshot of an organisation's attributes used for flag targeting."""

    org_id: str
    trade_category_slug: str | None = None
    trade_family_slug: str | None = None
    country_code: str | None = None
    plan_tier: str | None = None


# ---------------------------------------------------------------------------
# Feature flag evaluation service (pure logic, no I/O)
# ---------------------------------------------------------------------------

TARGETING_PRIORITY: list[str] = [
    "org_override",
    "trade_category",
    "trade_family",
    "country",
    "plan_tier",
    "percentage",
]


def _matches_rule(rule: dict[str, Any], org_context: OrgContext) -> bool:
    """Return True if *rule* matches the given *org_context*."""
    rule_type = rule.get("type")
    value = rule.get("value")

    if rule_type == "org_override":
        return str(org_context.org_id) == str(value)

    if rule_type == "trade_category":
        return org_context.trade_category_slug is not None and org_context.trade_category_slug == value

    if rule_type == "trade_family":
        return org_context.trade_family_slug is not None and org_context.trade_family_slug == value

    if rule_type == "country":
        return org_context.country_code is not None and org_context.country_code == value

    if rule_type == "plan_tier":
        return org_context.plan_tier is not None and org_context.plan_tier == value

    if rule_type == "percentage":
        # Deterministic hash-based percentage rollout
        pct = int(value) if value is not None else 0
        hash_input = f"{org_context.org_id}".encode()
        hash_val = int(hashlib.sha256(hash_input).hexdigest(), 16) % 100
        return hash_val < pct

    return False


def _rule_sort_key(rule: dict[str, Any]) -> int:
    """Return the priority index for a targeting rule type."""
    try:
        return TARGETING_PRIORITY.index(rule.get("type", ""))
    except ValueError:
        return len(TARGETING_PRIORITY)


def evaluate_flag(
    *,
    is_active: bool,
    default_value: bool,
    targeting_rules: list[dict[str, Any]],
    org_context: OrgContext,
) -> bool:
    """Evaluate a feature flag against an org context.

    This is a **pure function** with no I/O — caching and DB access are
    handled by the service layer (``app.modules.feature_flags.service``).

    Parameters
    ----------
    is_active:
        Whether the flag is globally active. Inactive flags return *default_value*.
    default_value:
        The fallback value when no targeting rule matches or the flag is inactive.
    targeting_rules:
        List of rule dicts, each with ``type``, ``value``, and ``enabled`` keys.
    org_context:
        The organisation context to evaluate against.

    Returns
    -------
    bool
        The evaluated flag value.
    """
    if not is_active:
        return default_value

    # Sort rules by targeting priority and return first match
    for rule in sorted(targeting_rules, key=_rule_sort_key):
        if _matches_rule(rule, org_context):
            return bool(rule.get("enabled", default_value))

    return default_value
