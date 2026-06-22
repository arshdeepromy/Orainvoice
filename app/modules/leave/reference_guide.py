"""NZ Holidays Act 2003 reference-guide content (R15).

Structured content surfaced by ``GET /api/v2/leave/reference-guide`` and rendered
by the frontend ``LeaveReferenceGuidePage``. Editable here without a redeploy of
the frontend. Describes the eligibility rules for the leave types this feature
covers, the Hours_Test, the Service_Milestones, and the parental-leave-out-of-
scope note (R15.2–R15.4).
"""

from __future__ import annotations

__all__ = ["REFERENCE_GUIDE_SECTIONS"]

REFERENCE_GUIDE_SECTIONS: list[dict[str, str]] = [
    {
        "key": "overview",
        "title": "Overview",
        "body": (
            "Statutory leave eligibility under the Holidays Act 2003 depends on "
            "two facts only: length of continuous service and a minimum-hours "
            "test. It does NOT depend on employment type (permanent, fixed-term, "
            "full-time or part-time are treated identically). The single genuinely "
            "different path is casual employment, which is paid 8% holiday pay each "
            "pay period instead of accruing annual holidays."
        ),
    },
    {
        "key": "service_milestones",
        "title": "Service milestones",
        "body": (
            "Entitlements unlock at three milestones measured from the employment "
            "start date: day 1 (public holidays, alternative holidays, jury "
            "service), 6 months (sick, bereavement and family-violence leave, "
            "subject to the hours test), and 12 months (annual holidays vest). A "
            "90-day trial period does not delay or reset continuous service."
        ),
    },
    {
        "key": "hours_test",
        "title": "The hours test",
        "body": (
            "Sick, bereavement and family-violence leave require, over the "
            "qualifying period, an average of at least 10 hours per week AND either "
            "at least 1 hour every week OR at least 40 hours every month."
        ),
    },
    {
        "key": "annual_holidays",
        "title": "Annual holidays",
        "body": (
            "Four weeks of paid annual holidays vest after 12 months of continuous "
            "service, expressed in hours using the employee's standard weekly "
            "hours. Casual employees are paid 8% pay-as-you-go instead."
        ),
    },
    {
        "key": "sick_leave",
        "title": "Sick leave",
        "body": (
            "Sick leave becomes available after 6 months of continuous service "
            "when the hours test is met."
        ),
    },
    {
        "key": "bereavement_leave",
        "title": "Bereavement leave",
        "body": (
            "Bereavement leave becomes available after 6 months of continuous "
            "service when the hours test is met."
        ),
    },
    {
        "key": "family_violence_leave",
        "title": "Family violence leave",
        "body": (
            "Family-violence leave becomes available after 6 months of continuous "
            "service when the hours test is met."
        ),
    },
    {
        "key": "public_holidays",
        "title": "Public holidays & alternative holidays",
        "body": (
            "Public holidays are a paid entitlement from day 1 when the day is an "
            "otherwise-working day. Working a public holiday that is an "
            "otherwise-working day earns an alternative holiday (a paid day off in "
            "lieu) from day 1."
        ),
    },
    {
        "key": "jury_service",
        "title": "Jury service",
        "body": "Jury-service job protection applies from day 1 of employment.",
    },
    {
        "key": "termination",
        "title": "Termination payout",
        "body": (
            "On termination before 12 months, annual-holiday pay is 8% of gross "
            "earnings. On or after 12 months, remaining accrued annual holidays are "
            "paid at the greater of ordinary weekly pay or average weekly earnings."
        ),
    },
    {
        "key": "parental_leave_out_of_scope",
        "title": "Parental leave (out of scope)",
        "body": (
            "Parental leave is governed by the Parental Leave and Employment "
            "Protection Act 1987, a separate Act, and is out of scope for accrual "
            "in this feature."
        ),
    },
]
