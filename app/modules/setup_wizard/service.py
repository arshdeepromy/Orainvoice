"""Setup wizard service.

Implements the 7-step onboarding wizard logic:
1. Country selection → applies compliance profile defaults to org
2. Trade category → applies recommended modules, terminology, defaults
3. Business details → sets org name, tax number (validated), contact info
4. Branding → sets logo, colours
5. Module selection → enables chosen modules (with dependency resolution)
6. Catalogue seeding → creates initial services/products
7. Ready → marks wizard complete

**Validates: Requirement 5.1–5.10**
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone as tz

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modules import ModuleService
from app.modules.compliance_profiles.models import ComplianceProfile
from app.modules.setup_wizard.models import SetupWizardProgress
from app.modules.setup_wizard.schemas import (
    BrandingStepData,
    BusinessStepData,
    CatalogueStepData,
    CountryStepData,
    ModulesStepData,
    StepResult,
    TradeStepData,
)
from app.modules.trade_categories.models import TradeCategory


# ---------------------------------------------------------------------------
# Country defaults (fallback when no compliance profile exists)
# ---------------------------------------------------------------------------

COUNTRY_DEFAULTS: dict[str, dict] = {
    "NZ": {
        "base_currency": "NZD",
        "date_format": "dd/MM/yyyy",
        "number_format": "en-NZ",
        "tax_label": "GST",
        "default_tax_rate": 15.00,
        "timezone": "Pacific/Auckland",
        "tax_inclusive_default": True,
    },
    "AU": {
        "base_currency": "AUD",
        "date_format": "dd/MM/yyyy",
        "number_format": "en-AU",
        "tax_label": "GST",
        "default_tax_rate": 10.00,
        "timezone": "Australia/Sydney",
        "tax_inclusive_default": True,
    },
    "GB": {
        "base_currency": "GBP",
        "date_format": "dd/MM/yyyy",
        "number_format": "en-GB",
        "tax_label": "VAT",
        "default_tax_rate": 20.00,
        "timezone": "Europe/London",
        "tax_inclusive_default": True,
    },
    "US": {
        "base_currency": "USD",
        "date_format": "MM/dd/yyyy",
        "number_format": "en-US",
        "tax_label": "Tax",
        "default_tax_rate": 0.00,
        "timezone": "America/New_York",
        "tax_inclusive_default": False,
    },
}

# NZ defaults used when all steps are skipped
NZ_DEFAULTS = COUNTRY_DEFAULTS["NZ"]


# ---------------------------------------------------------------------------
# Tax number validation patterns per country
# ---------------------------------------------------------------------------

TAX_VALIDATORS: dict[str, re.Pattern] = {
    # NZ IRD: 8 or 9 digits, optionally with dashes (XX-XXX-XXX or XXX-XXX-XXX)
    "NZ": re.compile(r"^\d{2,3}-?\d{3}-?\d{3}$"),
    # AU ABN: 11 digits (may have spaces)
    "AU": re.compile(r"^\d{11}$"),
    # UK VAT: GB + 9 or 12 digits
    "GB": re.compile(r"^GB\d{9}(\d{3})?$"),
}


def validate_tax_number(country_code: str, tax_number: str) -> bool:
    """Validate a tax identifier against country-specific format.

    Returns True if valid or if no validator exists for the country.
    """
    pattern = TAX_VALIDATORS.get(country_code.upper())
    if pattern is None:
        return True  # No validation rule → accept anything
    return bool(pattern.match(tax_number))


def _abn_check_digit_valid(abn: str) -> bool:
    """Validate Australian Business Number check digit.

    The ABN is 11 digits. Subtract 1 from the first digit, then apply
    weights [10,1,3,5,7,9,11,13,15,17,19] and check sum % 89 == 0.
    """
    if len(abn) != 11 or not abn.isdigit():
        return False
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    digits = [int(d) for d in abn]
    digits[0] -= 1
    total = sum(d * w for d, w in zip(digits, weights))
    return total % 89 == 0


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SetupWizardService:
    """Orchestrates the multi-step setup wizard."""

    TOTAL_STEPS = 7

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -- Progress management ------------------------------------------------

    async def get_progress(
        self, org_id: uuid.UUID,
    ) -> SetupWizardProgress | None:
        """Return existing progress or None if no record exists."""
        stmt = select(SetupWizardProgress).where(
            SetupWizardProgress.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create_progress(
        self, org_id: uuid.UUID,
    ) -> SetupWizardProgress:
        """Return existing progress or create a new record.

        Steps 1 (Country) and 2 (Trade) are always auto-marked as
        complete because they are captured during signup — the wizard
        no longer includes these steps.
        """
        progress = await self.get_progress(org_id)
        if progress is None:
            progress = SetupWizardProgress(org_id=org_id)
            # Country and Trade are handled by signup — always mark complete
            progress.step_1_complete = True
            progress.step_2_complete = True
            self.db.add(progress)
            await self.db.flush()
        return progress

    async def get_progress(self, org_id: uuid.UUID) -> SetupWizardProgress | None:
        """Return progress record or None."""
        stmt = select(SetupWizardProgress).where(
            SetupWizardProgress.org_id == org_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # -- Step processing ----------------------------------------------------

    async def process_step(
        self, org_id: uuid.UUID, step_number: int, data: dict,
    ) -> StepResult:
        """Process a wizard step. Idempotent — re-submitting overwrites."""
        if step_number < 1 or step_number > self.TOTAL_STEPS:
            raise ValueError(f"Invalid step number: {step_number}")

        progress = await self.get_or_create_progress(org_id)

        handler = {
            1: self._process_country_step,
            2: self._process_trade_step,
            3: self._process_business_step,
            4: self._process_branding_step,
            5: self._process_modules_step,
            6: self._process_catalogue_step,
            7: self._process_ready_step,
        }[step_number]

        result = await handler(org_id, data, progress)

        # Mark step complete
        setattr(progress, f"step_{step_number}_complete", True)
        progress.updated_at = datetime.now(tz.utc)

        # Check if all steps done
        if all(
            getattr(progress, f"step_{i}_complete")
            for i in range(1, self.TOTAL_STEPS + 1)
        ):
            progress.wizard_completed = True
            progress.completed_at = datetime.now(tz.utc)

        await self.db.flush()
        return result

    async def skip_step(
        self, org_id: uuid.UUID, step_number: int,
    ) -> StepResult:
        """Skip a wizard step, applying sensible defaults."""
        if step_number < 1 or step_number > self.TOTAL_STEPS:
            raise ValueError(f"Invalid step number: {step_number}")

        progress = await self.get_or_create_progress(org_id)

        # For step 1 (country), apply NZ defaults when skipped
        if step_number == 1:
            await self._apply_country_defaults(org_id, "NZ", None)

        setattr(progress, f"step_{step_number}_complete", True)
        progress.updated_at = datetime.now(tz.utc)

        if all(
            getattr(progress, f"step_{i}_complete")
            for i in range(1, self.TOTAL_STEPS + 1)
        ):
            progress.wizard_completed = True
            progress.completed_at = datetime.now(tz.utc)

        await self.db.flush()
        return StepResult(
            step_number=step_number,
            completed=True,
            skipped=True,
            message=f"Step {step_number} skipped",
        )

    # -- Step 1: Country ----------------------------------------------------

    async def _process_country_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        parsed = CountryStepData(**data)
        country_code = parsed.country_code.upper()

        # Look up compliance profile
        stmt = select(ComplianceProfile).where(
            ComplianceProfile.country_code == country_code,
        )
        result = await self.db.execute(stmt)
        profile = result.scalar_one_or_none()

        applied = await self._apply_country_defaults(
            org_id, country_code, profile,
        )

        return StepResult(
            step_number=1,
            completed=True,
            message=f"Country set to {country_code}",
            applied_defaults=applied,
        )

    async def _apply_country_defaults(
        self,
        org_id: uuid.UUID,
        country_code: str,
        profile: ComplianceProfile | None,
    ) -> dict:
        """Apply country defaults to the organisation row."""
        if profile is not None:
            # Handle double-encoded JSONB (stored as JSON string instead of array)
            tax_rates = profile.default_tax_rates
            if isinstance(tax_rates, str):
                import json
                try:
                    tax_rates = json.loads(tax_rates)
                except (ValueError, TypeError):
                    tax_rates = []

            defaults = {
                "country_code": country_code,
                "base_currency": profile.currency_code,
                "date_format": profile.date_format,
                "number_format": profile.number_format,
                "tax_label": profile.tax_label,
                "default_tax_rate": (
                    tax_rates[0]["rate"]
                    if tax_rates and isinstance(tax_rates, list)
                    else 0
                ),
                "timezone": COUNTRY_DEFAULTS.get(
                    country_code, NZ_DEFAULTS,
                ).get("timezone", "UTC"),
                "tax_inclusive_default": profile.tax_inclusive_default,
                "compliance_profile_id": str(profile.id),
            }
        else:
            fallback = COUNTRY_DEFAULTS.get(country_code, NZ_DEFAULTS)
            defaults = {
                "country_code": country_code,
                "base_currency": fallback["base_currency"],
                "date_format": fallback["date_format"],
                "number_format": fallback["number_format"],
                "tax_label": fallback["tax_label"],
                "default_tax_rate": fallback["default_tax_rate"],
                "timezone": fallback["timezone"],
                "tax_inclusive_default": fallback.get("tax_inclusive_default", True),
            }

        await self._update_org(org_id, defaults)
        return defaults

    # -- Step 2: Trade category ---------------------------------------------

    async def _process_trade_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        parsed = TradeStepData(**data)

        stmt = select(TradeCategory).where(
            TradeCategory.slug == parsed.trade_category_slug,
            TradeCategory.is_active.is_(True),
            TradeCategory.is_retired.is_(False),
        )
        result = await self.db.execute(stmt)
        category = result.scalar_one_or_none()
        if category is None:
            raise ValueError(
                f"Trade category '{parsed.trade_category_slug}' not found or retired",
            )

        # Apply trade category to org
        await self._update_org(org_id, {
            "trade_category_id": str(category.id),
        })

        # Apply terminology overrides (delete existing, insert new)
        await self.db.execute(
            text("DELETE FROM org_terminology_overrides WHERE org_id = :oid"),
            {"oid": str(org_id)},
        )
        for key, label in (category.terminology_overrides or {}).items():
            await self.db.execute(
                text(
                    "INSERT INTO org_terminology_overrides (id, org_id, generic_key, custom_label) "
                    "VALUES (:id, :oid, :key, :label)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "oid": str(org_id),
                    "key": key,
                    "label": label,
                },
            )

        # Enable recommended modules
        module_svc = ModuleService(self.db)
        for mod_slug in (category.recommended_modules or []):
            await module_svc.enable_module(str(org_id), mod_slug)

        return StepResult(
            step_number=2,
            completed=True,
            message=f"Trade category set to {category.display_name}",
            applied_defaults={
                "trade_category_id": str(category.id),
                "recommended_modules": category.recommended_modules or [],
                "terminology_overrides": category.terminology_overrides or {},
                "default_services_count": len(category.default_services or []),
            },
        )

    # -- Step 3: Business details -------------------------------------------

    async def _process_business_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        parsed = BusinessStepData(**data)

        # Validate tax number if provided
        if parsed.tax_number:
            # Get the org's country code
            row = await self.db.execute(
                text("SELECT country_code FROM organisations WHERE id = :oid"),
                {"oid": str(org_id)},
            )
            org_row = row.mappings().first()
            country_code = (org_row["country_code"] or "NZ") if org_row else "NZ"

            # Strip spaces for AU ABN validation
            clean_tax = parsed.tax_number.replace(" ", "")
            if not validate_tax_number(country_code, clean_tax):
                raise ValueError(
                    f"Invalid tax number format for {country_code}. "
                    f"NZ IRD numbers should be 8 or 9 digits (e.g. 12-345-678 or 123-456-789).",
                )
            # Additional AU ABN check digit validation
            if country_code == "AU" and not _abn_check_digit_valid(clean_tax):
                raise ValueError("Invalid ABN check digit")

        # Update org settings
        org_updates: dict = {"name": parsed.business_name}
        settings_updates: dict = {}
        if parsed.trading_name is not None:
            settings_updates["trading_name"] = parsed.trading_name
        if parsed.registration_number is not None:
            settings_updates["registration_number"] = parsed.registration_number
        if parsed.tax_number is not None:
            settings_updates["tax_number"] = parsed.tax_number
        if parsed.phone is not None:
            settings_updates["phone"] = parsed.phone
        if parsed.address_unit is not None:
            settings_updates["address_unit"] = parsed.address_unit
        if parsed.address_street is not None:
            settings_updates["address_street"] = parsed.address_street
        if parsed.address_city is not None:
            settings_updates["address_city"] = parsed.address_city
        if parsed.address_state is not None:
            settings_updates["address_state"] = parsed.address_state
        if parsed.address_postcode is not None:
            settings_updates["address_postcode"] = parsed.address_postcode
        if parsed.website is not None:
            settings_updates["website"] = parsed.website

        await self._update_org(org_id, org_updates)
        if settings_updates:
            await self._merge_org_settings(org_id, settings_updates)

        return StepResult(
            step_number=3,
            completed=True,
            message="Business details saved",
        )

    # -- Step 4: Branding ---------------------------------------------------

    async def _process_branding_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        parsed = BrandingStepData(**data)
        settings_updates: dict = {}
        if parsed.logo_url is not None:
            settings_updates["logo_url"] = parsed.logo_url
        if parsed.primary_colour is not None:
            settings_updates["primary_colour"] = parsed.primary_colour
        if parsed.secondary_colour is not None:
            settings_updates["secondary_colour"] = parsed.secondary_colour

        if settings_updates:
            await self._merge_org_settings(org_id, settings_updates)

        return StepResult(
            step_number=4,
            completed=True,
            message="Branding saved",
        )

    # -- Step 5: Module selection -------------------------------------------

    async def _process_modules_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        parsed = ModulesStepData(**data)
        module_svc = ModuleService(self.db)

        additionally_enabled: list[str] = []
        for slug in parsed.enabled_modules:
            deps = await module_svc.enable_module(str(org_id), slug)
            additionally_enabled.extend(deps)

        return StepResult(
            step_number=5,
            completed=True,
            message=f"Enabled {len(parsed.enabled_modules)} modules",
            applied_defaults={
                "enabled_modules": parsed.enabled_modules,
                "auto_enabled_dependencies": list(set(additionally_enabled)),
            },
        )

    # -- Step 6: Catalogue seeding ------------------------------------------

    async def _process_catalogue_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        parsed = CatalogueStepData(**data)

        # Delete any previously seeded wizard items (idempotent)
        await self.db.execute(
            text(
                "DELETE FROM catalogue_items "
                "WHERE org_id = :oid AND source = 'setup_wizard'"
            ),
            {"oid": str(org_id)},
        )

        created = 0
        for item in parsed.items:
            await self.db.execute(
                text(
                    "INSERT INTO catalogue_items "
                    "(id, org_id, name, description, price, unit_of_measure, item_type, source) "
                    "VALUES (:id, :oid, :name, :desc, :price, :uom, :itype, 'setup_wizard')"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "oid": str(org_id),
                    "name": item.name,
                    "desc": item.description or "",
                    "price": item.price,
                    "uom": item.unit_of_measure,
                    "itype": item.item_type,
                },
            )
            created += 1

        return StepResult(
            step_number=6,
            completed=True,
            message=f"Seeded {created} catalogue items",
            applied_defaults={"items_created": created},
        )

    # -- Step 7: Ready ------------------------------------------------------

    async def _process_ready_step(
        self,
        org_id: uuid.UUID,
        data: dict,
        progress: SetupWizardProgress,
    ) -> StepResult:
        """Mark the wizard as complete."""
        progress.wizard_completed = True
        progress.completed_at = datetime.now(tz.utc)
        return StepResult(
            step_number=7,
            completed=True,
            message="Setup wizard complete — your workspace is ready!",
        )

    # -- Helpers ------------------------------------------------------------

    async def _update_org(self, org_id: uuid.UUID, fields: dict) -> None:
        """Update organisation columns directly."""
        if not fields:
            return
        set_clauses = ", ".join(f"{k} = :{k}" for k in fields)
        params = {k: v for k, v in fields.items()}
        params["oid"] = str(org_id)
        await self.db.execute(
            text(f"UPDATE organisations SET {set_clauses} WHERE id = :oid"),
            params,
        )

    async def _merge_org_settings(
        self, org_id: uuid.UUID, updates: dict,
    ) -> None:
        """Merge key-value pairs into the org's JSONB settings column."""
        import json as _json
        # Use CAST() instead of :: to avoid asyncpg named-param conflict
        await self.db.execute(
            text(
                "UPDATE organisations "
                "SET settings = settings || CAST(:patch AS jsonb) "
                "WHERE id = :oid"
            ),
            {"patch": _json.dumps(updates), "oid": str(org_id)},
        )
