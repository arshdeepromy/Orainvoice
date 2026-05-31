"""Staff service: CRUD, location assignment, utilisation, and labour costs.

**Validates: Requirement — Staff Module (R2, R3, R4 for Phase 1 task B4)**
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import envelope_encrypt
from app.modules.organisations.service import get_org_settings
from app.modules.staff.models import (
    StaffLocationAssignment,
    StaffMember,
    StaffPayRate,
)
from app.modules.staff.schemas import StaffMemberCreate, StaffMemberUpdate
from app.modules.staff.security import is_masked_bank, is_masked_ird
from app.modules.time_tracking_v2.models import TimeEntry

# ---------------------------------------------------------------------------
# Service-layer exceptions (Phase 1 task B4)
# ---------------------------------------------------------------------------


class MinimumWageBelowThresholdError(Exception):
    """Raised by ``create_staff`` / ``update_staff`` when the submitted
    ``hourly_rate`` is below the org's configured minimum-wage threshold
    and the request did not include ``minimum_wage_override=true``.

    The ``threshold`` attribute exposes the value the request was
    compared against so the router can surface it in the HTTP 422
    response body (per R4 / C10).
    """

    def __init__(self, threshold: Decimal) -> None:
        self.threshold = threshold
        super().__init__(
            f"hourly_rate is below the NZ minimum wage threshold of "
            f"NZD {threshold}",
        )


# Default threshold applied when the org has not customised it via the
# Settings UI. Keeps create/update working before B6's settings entry is
# populated and matches the design's "no row backfill needed" rule.
_DEFAULT_MINIMUM_WAGE_THRESHOLD = Decimal("23.15")


class StaffService:
    """Service layer for staff and contractor management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_staff(
        self,
        org_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        role_type: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[StaffMember], int]:
        """List staff members with pagination and filtering."""
        stmt = select(StaffMember).where(StaffMember.org_id == org_id)

        if role_type is not None:
            stmt = stmt.where(StaffMember.role_type == role_type)
        if is_active is not None:
            stmt = stmt.where(StaffMember.is_active == is_active)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = stmt.order_by(StaffMember.name).offset(offset).limit(page_size)
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all()), total

    async def create_staff(
        self,
        org_id: uuid.UUID,
        payload: StaffMemberCreate,
        *,
        changed_by: uuid.UUID | None = None,
    ) -> StaffMember:
        """Create a new staff member.

        Phase 1 task B4 extends the original create flow to:
        - envelope-encrypt the IRD + bank account fields when supplied
          as plaintext (skipping mask-pattern values),
        - auto-set ``probation_end_date`` to ``employment_start_date +
          90 days`` when start_date is supplied and probation_end is
          not,
        - apply the minimum-wage gate (raises
          :class:`MinimumWageBelowThresholdError` when below the org's
          threshold and ``payload.minimum_wage_override`` is False),
        - insert an initial ``staff_pay_rates`` row when an hourly or
          overtime rate is supplied,
        - call ``await db.refresh(staff)`` after the final flush so
          relationships like ``location_assignments`` can be accessed
          lazily by ``StaffMemberResponse.from_attributes`` without
          tripping ``MissingGreenlet`` (P1-N15).
        """
        # Check for duplicates within the same org
        await self._check_duplicates(org_id, payload.email, payload.phone, payload.employee_id)

        # ------------------------------------------------------------------
        # Minimum-wage gate (R4 / C10).
        # The router-side audit log entry for an explicit override is
        # written by the C10 wiring; the service merely refuses without it.
        # ------------------------------------------------------------------
        await self._check_minimum_wage(
            org_id,
            hourly_rate=payload.hourly_rate,
            override=payload.minimum_wage_override,
        )

        first = payload.first_name.strip()
        last = (payload.last_name or "").strip()
        full_name = f"{first} {last}".strip()

        # ------------------------------------------------------------------
        # Encrypt PII (IRD + bank). Skip when the value is masked or
        # missing (defence-in-depth — schema validators already reject
        # masks on UPDATE; CREATE accepts plaintext only).
        # ------------------------------------------------------------------
        ird_ciphertext: bytes | None = None
        if payload.ird_number and not is_masked_ird(payload.ird_number):
            ird_ciphertext = envelope_encrypt(payload.ird_number)

        bank_ciphertext: bytes | None = None
        if payload.bank_account_number and not is_masked_bank(
            payload.bank_account_number,
        ):
            bank_ciphertext = envelope_encrypt(payload.bank_account_number)

        # ------------------------------------------------------------------
        # Auto-set probation_end_date when start_date is supplied and
        # probation_end is not. (R2.6.)
        # ------------------------------------------------------------------
        probation_end = payload.probation_end_date
        if probation_end is None and payload.employment_start_date is not None:
            probation_end = payload.employment_start_date + timedelta(days=90)

        # ------------------------------------------------------------------
        # Phase 3 task B3a (G9) — when the caller did NOT explicitly
        # supply ``self_service_clock_enabled`` (i.e. the schema field
        # is ``None``), derive the default from the org's
        # ``clock_in_policy.default_channel``:
        #   - ``'kiosk_and_self_service'`` → True
        #   - ``'kiosk_only'`` (system default) → False
        # An explicit boolean from the caller is respected as-is, even
        # when it disagrees with the org policy. Existing staff are
        # never touched by changes to ``default_channel`` — the policy
        # only applies on NEW staff insertion (R6b.3).
        #
        # Read the column directly via SQL because the ``Organisation``
        # ORM model does not yet declare ``clock_in_policy`` as a typed
        # field (the migration adds the JSONB column but the ORM
        # extension is owned by Phase 3 task B3, not Phase 1).
        # ------------------------------------------------------------------
        self_service_flag = payload.self_service_clock_enabled
        if self_service_flag is None:
            default_channel = await self._resolve_default_clock_channel(org_id)
            self_service_flag = default_channel == "kiosk_and_self_service"

        staff = StaffMember(
            org_id=org_id,
            user_id=payload.user_id,
            name=full_name,
            first_name=first,
            last_name=last or None,
            email=payload.email,
            phone=payload.phone,
            employee_id=payload.employee_id,
            position=payload.position,
            reporting_to=payload.reporting_to,
            shift_start=payload.shift_start,
            shift_end=payload.shift_end,
            role_type=payload.role_type,
            hourly_rate=payload.hourly_rate,
            overtime_rate=payload.overtime_rate,
            availability_schedule=payload.availability_schedule,
            skills=payload.skills,
            # ----------------------------------------------------------
            # Phase 1 employment record fields (R2.1).
            # ----------------------------------------------------------
            employment_start_date=payload.employment_start_date,
            employment_end_date=payload.employment_end_date,
            employment_type=payload.employment_type,
            standard_hours_per_week=payload.standard_hours_per_week,
            tax_code=payload.tax_code,
            ird_number_encrypted=ird_ciphertext,
            student_loan=payload.student_loan,
            kiwisaver_enrolled=payload.kiwisaver_enrolled,
            kiwisaver_employee_rate=payload.kiwisaver_employee_rate,
            kiwisaver_employer_rate=payload.kiwisaver_employer_rate,
            bank_account_number_encrypted=bank_ciphertext,
            probation_end_date=probation_end,
            residency_type=payload.residency_type,
            visa_expiry_date=payload.visa_expiry_date,
            self_service_clock_enabled=self_service_flag,
            on_file_photo_url=payload.on_file_photo_url,
            emergency_contact_name=payload.emergency_contact_name,
            emergency_contact_phone=payload.emergency_contact_phone,
            weekly_roster_email_enabled=payload.weekly_roster_email_enabled,
            weekly_roster_sms_enabled=payload.weekly_roster_sms_enabled,
        )
        self.db.add(staff)
        await self.db.flush()

        # ------------------------------------------------------------------
        # Insert initial pay-rate row when a rate is supplied (R3.3).
        # ------------------------------------------------------------------
        if payload.hourly_rate is not None or payload.overtime_rate is not None:
            self.db.add(
                StaffPayRate(
                    org_id=org_id,
                    staff_id=staff.id,
                    hourly_rate=payload.hourly_rate,
                    overtime_rate=payload.overtime_rate,
                    effective_from=date.today(),
                    changed_by=changed_by,
                    change_reason="initial_rate",
                ),
            )
            await self.db.flush()

        # P1-N15: refresh so lazily-loaded relationships
        # (``location_assignments``) are available when the router
        # serialises the response via ``StaffMemberResponse.from_attributes``.
        await self.db.refresh(staff)
        return staff

    async def _check_duplicates(
        self,
        org_id: uuid.UUID,
        email: str | None,
        phone: str | None,
        employee_id: str | None,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        """Raise ValueError if email, phone, or employee_id already exists for another active staff member."""
        conflicts: list[str] = []
        for field_name, value in [("email", email), ("phone", phone), ("employee_id", employee_id)]:
            if not value or not value.strip():
                continue
            col = getattr(StaffMember, field_name)
            stmt = select(StaffMember.id).where(
                StaffMember.org_id == org_id,
                col == value.strip(),
                StaffMember.is_active.is_(True),
            )
            if exclude_id:
                stmt = stmt.where(StaffMember.id != exclude_id)
            result = await self.db.execute(stmt.limit(1))
            if result.scalar_one_or_none() is not None:
                label = field_name.replace("_", " ").title()
                conflicts.append(f"{label} '{value.strip()}' is already in use by another staff member")
        if conflicts:
            raise ValueError("; ".join(conflicts))



    async def get_staff(
        self, org_id: uuid.UUID, staff_id: uuid.UUID,
    ) -> StaffMember | None:
        """Get a single staff member by ID."""
        stmt = select(StaffMember).where(
            and_(StaffMember.org_id == org_id, StaffMember.id == staff_id),
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def update_staff(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, payload: StaffMemberUpdate,
        *,
        changed_by: uuid.UUID | None = None,
    ) -> StaffMember | None:
        """Update an existing staff member.

        Phase 1 task B4 extends the original update flow to:
        - envelope-encrypt incoming plaintext IRD + bank values, skip
          masked round-trips so the existing ciphertext is preserved,
        - apply the minimum-wage gate when ``hourly_rate`` is being
          changed (raises :class:`MinimumWageBelowThresholdError`),
        - insert a new ``staff_pay_rates`` row when ``hourly_rate`` or
          ``overtime_rate`` change to a different value, and bump
          ``last_pay_review_date`` to today (R3.4 + R6.3),
        - call ``await db.refresh(staff)`` after the final flush so
          lazy relationships continue to work post-flush (P1-N15).
        """
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            return None

        # ``model_dump(exclude_unset=True)`` keeps the "field omitted"
        # vs "field set to None" distinction the client cares about.
        update_data = payload.model_dump(exclude_unset=True)

        # Pull the special-handling fields out of the dict so the
        # generic ``setattr`` loop below can't accidentally write the
        # plaintext IRD / bank into a column that doesn't exist on the
        # model, or set the request-only override flag.
        ird_value = update_data.pop("ird_number", None)
        bank_value = update_data.pop("bank_account_number", None)
        # ``minimum_wage_override`` is a request-only flag; never a
        # column on ``staff_members``.
        update_data.pop("minimum_wage_override", None)

        # ------------------------------------------------------------------
        # Minimum-wage gate (R4 / C10) — apply when the request actually
        # supplies an ``hourly_rate`` (changed or not — same threshold
        # check the create path uses).
        # ------------------------------------------------------------------
        if "hourly_rate" in update_data:
            new_rate = update_data["hourly_rate"]
            await self._check_minimum_wage(
                org_id,
                hourly_rate=new_rate,
                override=payload.minimum_wage_override,
            )

        # ------------------------------------------------------------------
        # Encrypt IRD + bank when supplied as plaintext. Skip masked
        # values entirely so the existing ciphertext isn't overwritten.
        # ------------------------------------------------------------------
        if ird_value is not None and not is_masked_ird(ird_value):
            staff.ird_number_encrypted = envelope_encrypt(ird_value)
        if bank_value is not None and not is_masked_bank(bank_value):
            staff.bank_account_number_encrypted = envelope_encrypt(bank_value)

        # ------------------------------------------------------------------
        # Pay-rate history detection (R3.4) — capture the prior rate
        # values BEFORE the setattr loop overwrites them, so we can
        # compare and decide whether a new audit row is needed.
        # ------------------------------------------------------------------
        prior_hourly = staff.hourly_rate
        prior_overtime = staff.overtime_rate
        rate_changed = False
        if "hourly_rate" in update_data and update_data["hourly_rate"] != prior_hourly:
            rate_changed = True
        if "overtime_rate" in update_data and update_data["overtime_rate"] != prior_overtime:
            rate_changed = True

        # Check for duplicates, excluding the current staff member.
        await self._check_duplicates(
            org_id,
            update_data.get("email", staff.email),
            update_data.get("phone", staff.phone),
            update_data.get("employee_id", staff.employee_id),
            exclude_id=staff_id,
        )

        for field, value in update_data.items():
            setattr(staff, field, value)
        # Keep legacy 'name' field in sync
        if "first_name" in update_data or "last_name" in update_data:
            first = staff.first_name or ""
            last = staff.last_name or ""
            staff.name = f"{first} {last}".strip()

        if rate_changed:
            new_hourly = update_data.get("hourly_rate", prior_hourly)
            new_overtime = update_data.get("overtime_rate", prior_overtime)
            self.db.add(
                StaffPayRate(
                    org_id=org_id,
                    staff_id=staff.id,
                    hourly_rate=new_hourly,
                    overtime_rate=new_overtime,
                    effective_from=date.today(),
                    changed_by=changed_by,
                    change_reason="rate_change",
                ),
            )
            staff.last_pay_review_date = date.today()

        await self.db.flush()
        # P1-N15: refresh after the final flush so lazy relationships
        # remain accessible to the Pydantic response serialiser.
        await self.db.refresh(staff)
        return staff

    # ------------------------------------------------------------------
    # Phase 1 — pay-rate history (B5)
    # ------------------------------------------------------------------

    async def get_pay_rate_history(
        self,
        org_id: uuid.UUID,
        staff_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the pay-rate audit ledger for ``staff_id``.

        Joins ``staff_pay_rates`` to ``users`` (LEFT/OUTER — ``changed_by``
        is nullable for system-inserted rows) so each item carries the
        e-mail of whoever made the change. Mirrors the
        ``StaffPayRateResponse`` Pydantic shape so the router can pass
        the dicts straight through to ``StaffPayRateListResponse``.

        Ordered by ``effective_from DESC, created_at DESC`` so the most
        recent change appears first; ``created_at`` is the tiebreaker
        when several rows share the same effective date (e.g. the
        initial-rate row plus an immediate correction).

        Returns ``(items, total)``: ``total`` is the unfiltered count
        (without offset/limit applied) so the UI can render an accurate
        pagination footer.
        """
        # Local import keeps ``app.modules.staff.service`` free of an
        # import-time dependency on the auth module (avoids cycles).
        from app.modules.auth.models import User

        # Total — counts every row matching the org+staff filter,
        # before offset/limit. Using ``count(StaffPayRate.id)`` instead
        # of ``count()`` lets the planner avoid materialising the join.
        count_stmt = (
            select(func.count(StaffPayRate.id))
            .where(
                StaffPayRate.org_id == org_id,
                StaffPayRate.staff_id == staff_id,
            )
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        # Paginated rows with the changer's e-mail joined in.
        rows_stmt = (
            select(
                StaffPayRate.id,
                StaffPayRate.effective_from,
                StaffPayRate.hourly_rate,
                StaffPayRate.overtime_rate,
                StaffPayRate.change_reason,
                User.email.label("changed_by_email"),
            )
            .select_from(StaffPayRate)
            .outerjoin(User, StaffPayRate.changed_by == User.id)
            .where(
                StaffPayRate.org_id == org_id,
                StaffPayRate.staff_id == staff_id,
            )
            .order_by(
                StaffPayRate.effective_from.desc(),
                StaffPayRate.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(rows_stmt)
        items: list[dict[str, Any]] = [
            {
                "id": row.id,
                "effective_from": row.effective_from,
                "hourly_rate": row.hourly_rate,
                "overtime_rate": row.overtime_rate,
                "change_reason": row.change_reason,
                "changed_by_email": row.changed_by_email,
            }
            for row in result.all()
        ]
        return items, int(total)

    # ------------------------------------------------------------------
    # Phase 1 — compliance counters (C9, R6, G1, G2, G3)
    # ------------------------------------------------------------------

    async def get_compliance_summary(
        self,
        org_id: uuid.UUID,
        threshold: Decimal,
    ) -> dict[str, int]:
        """Return all 7 compliance counters in one round-trip.

        Each counter is computed via ``COUNT(*) FILTER (WHERE ...)``
        in a single SELECT against ``staff_members``, so the database
        scans the org's staff list once and bucketises into the seven
        aggregates in-pass. The partial indexes added by migration
        ``0204`` (``idx_staff_missing_employee_id`` and
        ``idx_staff_missing_start_date``) cover the G1/G3 counters, and
        the ``idx_staff_*`` indexes on ``probation_end_date``,
        ``visa_expiry_date``, etc. cover the rest.

        ``threshold`` is the org's ``minimum_wage_threshold_nzd``
        resolved by the caller (router) — not re-loaded here, to keep
        this method side-effect-free and easy to test.

        Returns a flat dict with all seven integer keys so the caller
        can shovel it straight into :class:`ComplianceSummary`.

        **Validates: Requirements R6, G1, G2, G3** (Phase 1 task C9).
        """
        # ``func.now()`` is rendered as PostgreSQL's ``now()`` which
        # uses the transaction-start timestamp — fine for compliance
        # counters that rely on coarse 14-day / 60-day / 12-month
        # windows. The ``text("interval '14 days'")`` literals avoid
        # parameterising arbitrary strings and let the planner
        # constant-fold the window bounds.
        in_14_days = func.now() + text("interval '14 days'")
        in_60_days = func.now() + text("interval '60 days'")
        twelve_months_ago = func.now() - text("interval '12 months'")
        active = StaffMember.is_active.is_(True)

        stmt = (
            select(
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.probation_end_date.between(
                            func.now(), in_14_days,
                        ),
                    ),
                )
                .label("probation_ending_soon"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.visa_expiry_date.between(
                            func.now(), in_60_days,
                        ),
                        StaffMember.residency_type.in_(
                            ("work_visa", "student_visa", "other"),
                        ),
                    ),
                )
                .label("visa_expiring_soon"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.employment_agreement_upload_id.is_(None),
                    ),
                )
                .label("missing_agreement"),
                func.count()
                .filter(
                    and_(
                        active,
                        or_(
                            StaffMember.last_pay_review_date.is_(None),
                            StaffMember.last_pay_review_date < twelve_months_ago,
                        ),
                    ),
                )
                .label("pay_review_due"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.hourly_rate.is_not(None),
                        StaffMember.hourly_rate < threshold,
                    ),
                )
                .label("below_minimum_wage"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.employee_id.is_(None),
                    ),
                )
                .label("missing_employee_id"),
                func.count()
                .filter(
                    and_(
                        active,
                        StaffMember.employment_start_date.is_(None),
                    ),
                )
                .label("missing_start_date"),
            )
            .where(StaffMember.org_id == org_id)
        )
        row = (await self.db.execute(stmt)).one()
        return {
            "probation_ending_soon": int(row.probation_ending_soon or 0),
            "visa_expiring_soon": int(row.visa_expiring_soon or 0),
            "missing_agreement": int(row.missing_agreement or 0),
            "pay_review_due": int(row.pay_review_due or 0),
            "below_minimum_wage": int(row.below_minimum_wage or 0),
            "missing_employee_id": int(row.missing_employee_id or 0),
            "missing_start_date": int(row.missing_start_date or 0),
        }

    # ------------------------------------------------------------------
    # Phase 1 helpers (B4)
    # ------------------------------------------------------------------

    async def _resolve_minimum_wage_threshold(
        self, org_id: uuid.UUID,
    ) -> Decimal:
        """Return the org's minimum-wage threshold, defaulting to 23.15.

        Reads ``minimum_wage_threshold_nzd`` from the cached org
        settings. When the key is missing or the lookup fails (e.g.
        Redis is down and the DB read raises), returns the documented
        Phase 1 default so the create/update path keeps functioning.
        """
        try:
            settings = await get_org_settings(self.db, org_id=org_id)
        except Exception:
            return _DEFAULT_MINIMUM_WAGE_THRESHOLD
        raw = settings.get("minimum_wage_threshold_nzd")
        if raw is None:
            return _DEFAULT_MINIMUM_WAGE_THRESHOLD
        try:
            return Decimal(str(raw))
        except Exception:
            return _DEFAULT_MINIMUM_WAGE_THRESHOLD

    async def _check_minimum_wage(
        self,
        org_id: uuid.UUID,
        *,
        hourly_rate: Decimal | None,
        override: bool,
    ) -> None:
        """Raise ``MinimumWageBelowThresholdError`` when the rate is below
        the org threshold and ``override`` is False.

        ``hourly_rate`` of ``None`` short-circuits — there is no rate to
        compare. The caller must have already checked that the field is
        present in the inbound payload (so a partial update that does
        not touch the rate doesn't trip this gate).
        """
        if hourly_rate is None:
            return
        threshold = await self._resolve_minimum_wage_threshold(org_id)
        if hourly_rate < threshold and not override:
            raise MinimumWageBelowThresholdError(threshold=threshold)

    # ------------------------------------------------------------------
    # Phase 3 task B3a (G9) — default clock-in channel resolution
    # ------------------------------------------------------------------

    async def _resolve_default_clock_channel(
        self, org_id: uuid.UUID,
    ) -> str:
        """Return the org's ``clock_in_policy.default_channel``.

        Reads the JSONB column directly via SQL because the
        ``Organisation`` ORM model does not yet declare
        ``clock_in_policy`` as a typed field (the migration adds it but
        the ORM extension lives in the Phase 3 time_clock module). The
        helper falls back to the documented system default
        (``'kiosk_only'``) when the column is ``NULL``, the org row
        doesn't exist (e.g. an in-memory test using a random UUID), or
        the JSONB key is missing — so create_staff keeps working in
        every state of the data.
        """
        try:
            result = await self.db.execute(
                text(
                    "SELECT clock_in_policy FROM organisations "
                    "WHERE id = :org_id",
                ),
                {"org_id": str(org_id)},
            )
            row = result.scalar_one_or_none()
        except Exception:
            return "kiosk_only"
        if not isinstance(row, dict):
            return "kiosk_only"
        channel = row.get("default_channel")
        if not isinstance(channel, str):
            return "kiosk_only"
        return channel


    # ------------------------------------------------------------------
    # Location assignment
    # ------------------------------------------------------------------

    async def assign_to_location(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, location_id: uuid.UUID,
    ) -> StaffLocationAssignment:
        """Assign a staff member to a location. Inactive staff cannot be assigned."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            raise ValueError("Staff member not found")
        if not staff.is_active:
            raise ValueError("Cannot assign inactive staff to a location")

        # Check for existing assignment
        stmt = select(StaffLocationAssignment).where(
            and_(
                StaffLocationAssignment.staff_id == staff_id,
                StaffLocationAssignment.location_id == location_id,
            ),
        )
        existing = (await self.db.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            raise ValueError("Staff member is already assigned to this location")

        assignment = StaffLocationAssignment(
            staff_id=staff_id,
            location_id=location_id,
        )
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def remove_from_location(
        self, org_id: uuid.UUID, staff_id: uuid.UUID, location_id: uuid.UUID,
    ) -> bool:
        """Remove a staff member from a location."""
        staff = await self.get_staff(org_id, staff_id)
        if staff is None:
            return False
        stmt = select(StaffLocationAssignment).where(
            and_(
                StaffLocationAssignment.staff_id == staff_id,
                StaffLocationAssignment.location_id == location_id,
            ),
        )
        assignment = (await self.db.execute(stmt)).scalar_one_or_none()
        if assignment is None:
            return False
        await self.db.delete(assignment)
        await self.db.flush()
        return True

    # ------------------------------------------------------------------
    # Utilisation calculation
    # ------------------------------------------------------------------

    async def calculate_utilisation(
        self,
        org_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        staff_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Calculate utilisation: billable hours / available hours for date range."""
        staff_stmt = select(StaffMember).where(StaffMember.org_id == org_id)
        if staff_id is not None:
            staff_stmt = staff_stmt.where(StaffMember.id == staff_id)
        staff_result = await self.db.execute(staff_stmt)
        staff_list = list(staff_result.scalars().unique().all())

        results: list[dict[str, Any]] = []
        for member in staff_list:
            # Get time entries for this staff member in the date range
            te_stmt = (
                select(
                    func.coalesce(func.sum(TimeEntry.duration_minutes), 0).label("total_minutes"),
                    func.coalesce(
                        func.sum(
                            func.case(
                                (TimeEntry.is_billable.is_(True), TimeEntry.duration_minutes),
                                else_=0,
                            )
                        ), 0,
                    ).label("billable_minutes"),
                )
                .where(
                    and_(
                        TimeEntry.org_id == org_id,
                        TimeEntry.staff_id == member.id,
                        TimeEntry.start_time >= date_from.isoformat(),
                        TimeEntry.start_time < date_to.isoformat(),
                    ),
                )
            )
            row = (await self.db.execute(te_stmt)).one()
            total_minutes = int(row[0])
            billable_minutes = int(row[1])

            # Calculate available minutes from availability schedule
            available_minutes = self._calculate_available_minutes(
                member.availability_schedule, date_from, date_to,
            )

            utilisation = (
                Decimal(str(billable_minutes)) / Decimal(str(available_minutes)) * 100
                if available_minutes > 0
                else Decimal("0")
            )

            results.append({
                "staff_id": member.id,
                "staff_name": member.name,
                "billable_minutes": billable_minutes,
                "total_minutes": total_minutes,
                "available_minutes": available_minutes,
                "utilisation_percent": round(utilisation, 2),
            })

        return results

    @staticmethod
    def _calculate_available_minutes(
        schedule: dict, date_from: date, date_to: date,
    ) -> int:
        """Calculate total available minutes from a weekly availability schedule.

        Schedule format: {"monday": {"start": "09:00", "end": "17:00"}, ...}
        Falls back to 8 hours/day, 5 days/week if schedule is empty.
        """
        if not schedule:
            # Default: 8 hours/day, Mon-Fri
            num_days = (date_to - date_from).days
            if num_days <= 0:
                return 0
            # Rough estimate: 5/7 of days are working days
            working_days = max(1, int(num_days * 5 / 7))
            return working_days * 8 * 60

        total = 0
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        current = date_from
        while current < date_to:
            day_name = day_names[current.weekday()]
            day_schedule = schedule.get(day_name)
            if day_schedule and isinstance(day_schedule, dict):
                start = day_schedule.get("start", "09:00")
                end = day_schedule.get("end", "17:00")
                try:
                    sh, sm = map(int, start.split(":"))
                    eh, em = map(int, end.split(":"))
                    minutes = (eh * 60 + em) - (sh * 60 + sm)
                    if minutes > 0:
                        total += minutes
                except (ValueError, AttributeError):
                    total += 480  # fallback 8 hours
            current = date(current.year, current.month, current.day)
            from datetime import timedelta
            current = current + timedelta(days=1)
        return total

    # ------------------------------------------------------------------
    # Labour costs
    # ------------------------------------------------------------------

    async def get_labour_costs(
        self,
        org_id: uuid.UUID,
        date_from: date,
        date_to: date,
        *,
        staff_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Calculate labour costs from time entries × hourly rate for date range."""
        staff_stmt = select(StaffMember).where(StaffMember.org_id == org_id)
        if staff_id is not None:
            staff_stmt = staff_stmt.where(StaffMember.id == staff_id)
        staff_result = await self.db.execute(staff_stmt)
        staff_list = list(staff_result.scalars().unique().all())

        entries: list[dict[str, Any]] = []
        grand_total = Decimal("0")

        for member in staff_list:
            te_stmt = (
                select(func.coalesce(func.sum(TimeEntry.duration_minutes), 0))
                .where(
                    and_(
                        TimeEntry.org_id == org_id,
                        TimeEntry.staff_id == member.id,
                        TimeEntry.start_time >= date_from.isoformat(),
                        TimeEntry.start_time < date_to.isoformat(),
                    ),
                )
            )
            total_minutes = (await self.db.execute(te_stmt)).scalar() or 0
            total_minutes = int(total_minutes)

            rate = member.hourly_rate or Decimal("0")
            hours = Decimal(str(total_minutes)) / Decimal("60")
            cost = round(hours * rate, 2)

            entries.append({
                "staff_id": member.id,
                "staff_name": member.name,
                "total_minutes": total_minutes,
                "hourly_rate": rate,
                "total_cost": cost,
            })
            grand_total += cost

        return {
            "entries": entries,
            "total_cost": grand_total,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
