"""Pricing rule service: evaluate_price, CRUD, conflict validation.

evaluate_price() checks active rules in priority order (highest first)
and returns the first matching price. If no rules match, the product's
base sale_price is returned.

Rule matching logic:
- customer_specific: matches when customer_id equals the rule's customer_id
- volume: matches when quantity falls within [min_quantity, max_quantity]
- date_based: matches when evaluation date falls within [start_date, end_date]
- trade_category: matches when the rule's customer_tag matches (placeholder)

**Validates: Requirement 10.1, 10.2, 10.5**
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pricing_rules.models import PricingRule
from app.modules.pricing_rules.schemas import (
    ConflictWarning,
    EvaluatedPrice,
    PricingRuleCreate,
    PricingRuleUpdate,
)


class PricingRuleService:
    """Service layer for pricing rules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Price evaluation
    # ------------------------------------------------------------------

    async def evaluate_price(
        self,
        org_id: uuid.UUID,
        product_id: uuid.UUID,
        base_price: Decimal,
        *,
        customer_id: uuid.UUID | None = None,
        quantity: Decimal = Decimal("1"),
        eval_date: date | None = None,
    ) -> EvaluatedPrice:
        """Evaluate pricing rules and return the effective price.

        Checks active rules for the product in descending priority order.
        Returns the first matching rule's price, or the base_price if none match.
        """
        if eval_date is None:
            eval_date = date.today()

        stmt = (
            select(PricingRule)
            .where(
                and_(
                    PricingRule.org_id == org_id,
                    PricingRule.is_active == True,  # noqa: E712
                    or_(
                        PricingRule.product_id == product_id,
                        PricingRule.product_id.is_(None),
                    ),
                ),
            )
            .order_by(PricingRule.priority.desc())
        )
        result = await self.db.execute(stmt)
        rules = list(result.scalars().all())

        for rule in rules:
            if self._rule_matches(rule, customer_id=customer_id, quantity=quantity, eval_date=eval_date):
                price = self._compute_price(rule, base_price)
                return EvaluatedPrice(
                    price=price,
                    rule_id=rule.id,
                    rule_type=rule.rule_type,
                    is_base_price=False,
                )

        return EvaluatedPrice(price=base_price, is_base_price=True)

    @staticmethod
    def _rule_matches(
        rule: PricingRule,
        *,
        customer_id: uuid.UUID | None,
        quantity: Decimal,
        eval_date: date,
    ) -> bool:
        """Check whether a rule matches the given context."""
        if rule.rule_type == "customer_specific":
            return rule.customer_id is not None and customer_id == rule.customer_id

        if rule.rule_type == "volume":
            if rule.min_quantity is not None and quantity < rule.min_quantity:
                return False
            if rule.max_quantity is not None and quantity > rule.max_quantity:
                return False
            return True

        if rule.rule_type == "date_based":
            if rule.start_date is not None and eval_date < rule.start_date:
                return False
            if rule.end_date is not None and eval_date > rule.end_date:
                return False
            return True

        if rule.rule_type == "trade_category":
            # trade_category rules match any context (org-wide)
            return True

        return False

    @staticmethod
    def _compute_price(rule: PricingRule, base_price: Decimal) -> Decimal:
        """Compute the effective price from a matched rule."""
        if rule.price_override is not None:
            return rule.price_override
        if rule.discount_percent is not None:
            discount = base_price * rule.discount_percent / Decimal("100")
            return base_price - discount
        return base_price

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_rules(
        self,
        org_id: uuid.UUID,
        *,
        product_id: uuid.UUID | None = None,
        is_active: bool | None = True,
    ) -> list[PricingRule]:
        stmt = select(PricingRule).where(PricingRule.org_id == org_id)
        if product_id is not None:
            stmt = stmt.where(PricingRule.product_id == product_id)
        if is_active is not None:
            stmt = stmt.where(PricingRule.is_active == is_active)
        stmt = stmt.order_by(PricingRule.priority.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_rule(
        self, org_id: uuid.UUID, rule_id: uuid.UUID,
    ) -> PricingRule | None:
        stmt = select(PricingRule).where(
            and_(PricingRule.id == rule_id, PricingRule.org_id == org_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_rule(
        self, org_id: uuid.UUID, data: PricingRuleCreate,
    ) -> tuple[PricingRule, list[ConflictWarning]]:
        """Create a pricing rule and return any conflict warnings."""
        warnings = await self._check_conflicts(org_id, data)
        rule = PricingRule(
            org_id=org_id,
            product_id=data.product_id,
            rule_type=data.rule_type,
            priority=data.priority,
            customer_id=data.customer_id,
            customer_tag=data.customer_tag,
            min_quantity=data.min_quantity,
            max_quantity=data.max_quantity,
            start_date=data.start_date,
            end_date=data.end_date,
            price_override=data.price_override,
            discount_percent=data.discount_percent,
        )
        self.db.add(rule)
        await self.db.flush()
        return rule, warnings

    async def update_rule(
        self, org_id: uuid.UUID, rule_id: uuid.UUID, data: PricingRuleUpdate,
    ) -> PricingRule | None:
        rule = await self.get_rule(org_id, rule_id)
        if rule is None:
            return None
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
        await self.db.flush()
        return rule

    async def delete_rule(
        self, org_id: uuid.UUID, rule_id: uuid.UUID,
    ) -> PricingRule | None:
        rule = await self.get_rule(org_id, rule_id)
        if rule is None:
            return None
        await self.db.delete(rule)
        await self.db.flush()
        return rule

    # ------------------------------------------------------------------
    # Conflict detection
    # ------------------------------------------------------------------

    async def _check_conflicts(
        self, org_id: uuid.UUID, data: PricingRuleCreate,
    ) -> list[ConflictWarning]:
        """Check for overlapping/conflicting rules and return warnings."""
        warnings: list[ConflictWarning] = []
        stmt = select(PricingRule).where(
            and_(
                PricingRule.org_id == org_id,
                PricingRule.is_active == True,  # noqa: E712
                PricingRule.rule_type == data.rule_type,
            ),
        )
        if data.product_id is not None:
            stmt = stmt.where(
                or_(
                    PricingRule.product_id == data.product_id,
                    PricingRule.product_id.is_(None),
                ),
            )
        result = await self.db.execute(stmt)
        existing = list(result.scalars().all())

        for rule in existing:
            if self._rules_overlap(rule, data):
                warnings.append(ConflictWarning(
                    existing_rule_id=rule.id,
                    conflict_description=(
                        f"Overlaps with existing {rule.rule_type} rule "
                        f"(priority={rule.priority})"
                    ),
                ))
        return warnings

    @staticmethod
    def _rules_overlap(existing: PricingRule, new: PricingRuleCreate) -> bool:
        """Determine if two rules of the same type overlap in scope."""
        if existing.rule_type == "customer_specific":
            return existing.customer_id == new.customer_id

        if existing.rule_type == "volume":
            e_min = existing.min_quantity or Decimal("0")
            e_max = existing.max_quantity or Decimal("999999999")
            n_min = new.min_quantity or Decimal("0")
            n_max = new.max_quantity or Decimal("999999999")
            return e_min <= n_max and n_min <= e_max

        if existing.rule_type == "date_based":
            e_start = existing.start_date or date.min
            e_end = existing.end_date or date.max
            n_start = new.start_date or date.min
            n_end = new.end_date or date.max
            return e_start <= n_end and n_start <= e_end

        if existing.rule_type == "trade_category":
            return existing.customer_tag == new.customer_tag

        return False
