"""Pure utility functions for the Billing module.

These functions encapsulate core billing logic as pure, testable functions
with no side effects or database dependencies.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def is_expiring_soon(
    exp_month: int, exp_year: int, reference_date: date | None = None
) -> bool:
    """True when the card's last valid day is within 30 days of reference_date.

    A credit card is valid through the last calendar day of its expiry month.
    This function returns ``True`` when that last day falls on or before
    ``reference_date + 30 days``.

    Uses ``calendar.monthrange`` for correct last-day-of-month handling
    (28/29/30/31), including leap years and year boundaries.

    Requirements: 4.3
    """
    ref = reference_date or date.today()
    last_day = calendar.monthrange(exp_year, exp_month)[1]
    expiry_date = date(exp_year, exp_month, last_day)
    return expiry_date <= ref + timedelta(days=30)
