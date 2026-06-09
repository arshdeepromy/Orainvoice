"""Unit tests for overtime auto-detection and classification."""
import pytest
from datetime import date

from app.modules.timesheets.overtime import (
    classify_overtime,
    OvertimeSettings,
    DailyBreakdown,
)


class TestOvertimeClassification:
    """Tests for classify_overtime()."""

    def test_no_overtime_under_daily_threshold(self):
        result = classify_overtime(
            clock_entries=[
                {"clock_in_date": date(2026, 6, 9), "worked_minutes": 450},
            ],
            public_holiday_dates=set(),
            settings=OvertimeSettings(daily_overtime_threshold_minutes=480),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 9),
        )
        assert result.ordinary_minutes == 450
        assert result.overtime_minutes == 0
        assert result.public_holiday_minutes == 0

    def test_daily_overtime_detection(self):
        result = classify_overtime(
            clock_entries=[
                {"clock_in_date": date(2026, 6, 9), "worked_minutes": 600},
            ],
            public_holiday_dates=set(),
            settings=OvertimeSettings(daily_overtime_threshold_minutes=480),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 9),
        )
        assert result.ordinary_minutes == 480
        assert result.overtime_minutes == 120
        assert result.public_holiday_minutes == 0

    def test_weekly_overtime_detection(self):
        """Multiple days within threshold individually but exceeding weekly."""
        entries = [
            {"clock_in_date": date(2026, 6, 9), "worked_minutes": 480},
            {"clock_in_date": date(2026, 6, 10), "worked_minutes": 480},
            {"clock_in_date": date(2026, 6, 11), "worked_minutes": 480},
            {"clock_in_date": date(2026, 6, 12), "worked_minutes": 480},
            {"clock_in_date": date(2026, 6, 13), "worked_minutes": 480},
            {"clock_in_date": date(2026, 6, 14), "worked_minutes": 480},
        ]
        result = classify_overtime(
            clock_entries=entries,
            public_holiday_dates=set(),
            settings=OvertimeSettings(
                daily_overtime_threshold_minutes=480,
                weekly_overtime_threshold_minutes=2400,
            ),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 14),
        )
        # 6 × 480 = 2880 total. Weekly threshold = 2400.
        # Excess = 480 minutes reclassified as OT.
        assert result.ordinary_minutes == 2400
        assert result.overtime_minutes == 480

    def test_public_holiday_classification(self):
        result = classify_overtime(
            clock_entries=[
                {"clock_in_date": date(2026, 6, 9), "worked_minutes": 480},
            ],
            public_holiday_dates={date(2026, 6, 9)},
            settings=OvertimeSettings(),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 9),
        )
        assert result.ordinary_minutes == 0
        assert result.overtime_minutes == 0
        assert result.public_holiday_minutes == 480

    def test_mixed_normal_and_holiday(self):
        result = classify_overtime(
            clock_entries=[
                {"clock_in_date": date(2026, 6, 9), "worked_minutes": 480},
                {"clock_in_date": date(2026, 6, 10), "worked_minutes": 480},
            ],
            public_holiday_dates={date(2026, 6, 10)},
            settings=OvertimeSettings(),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 10),
        )
        assert result.ordinary_minutes == 480
        assert result.overtime_minutes == 0
        assert result.public_holiday_minutes == 480

    def test_empty_entries(self):
        result = classify_overtime(
            clock_entries=[],
            public_holiday_dates=set(),
            settings=OvertimeSettings(),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 15),
        )
        assert result.ordinary_minutes == 0
        assert result.overtime_minutes == 0
        assert result.public_holiday_minutes == 0

    def test_overtime_exception_flag(self):
        result = classify_overtime(
            clock_entries=[
                {"clock_in_date": date(2026, 6, 9), "worked_minutes": 600},
            ],
            public_holiday_dates=set(),
            settings=OvertimeSettings(daily_overtime_threshold_minutes=480),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 9),
        )
        assert len(result.exception_flags) == 1
        assert result.exception_flags[0]["type"] == "overtime_detected"

    def test_no_exception_flag_when_no_overtime(self):
        result = classify_overtime(
            clock_entries=[
                {"clock_in_date": date(2026, 6, 9), "worked_minutes": 400},
            ],
            public_holiday_dates=set(),
            settings=OvertimeSettings(daily_overtime_threshold_minutes=480),
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 9),
        )
        assert len(result.exception_flags) == 0
