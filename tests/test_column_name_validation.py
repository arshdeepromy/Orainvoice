"""Unit tests for dynamic SQL column name whitelist (REM-21).

Validates that ``validate_column_name`` in the admin service correctly
accepts allowed columns and rejects everything else with a ``ValueError``.
"""

import pytest

from app.modules.admin.service import _ALLOWED_SORT_COLUMNS, validate_column_name


# ---------------------------------------------------------------------------
# Happy-path: every allowed column passes through unchanged
# ---------------------------------------------------------------------------


class TestValidateColumnNameAllowed:
    """Allowed columns must be returned unchanged."""

    @pytest.mark.parametrize(
        "table,column",
        [
            ("organisations", "created_at"),
            ("organisations", "updated_at"),
            ("organisations", "name"),
            ("organisations", "status"),
            ("users", "created_at"),
            ("users", "email"),
            ("users", "role"),
            ("users", "last_login_at"),
            ("users", "is_active"),
            ("invoices", "created_at"),
            ("invoices", "total"),
            ("invoices", "status"),
            ("invoices", "due_date"),
        ],
    )
    def test_allowed_column_returns_unchanged(self, table: str, column: str):
        assert validate_column_name(table, column) == column


# ---------------------------------------------------------------------------
# Rejection: invalid columns raise ValueError
# ---------------------------------------------------------------------------


class TestValidateColumnNameRejected:
    """Non-allowed columns must raise ValueError."""

    @pytest.mark.parametrize(
        "table,column",
        [
            ("organisations", "password_hash"),
            ("organisations", "id; DROP TABLE --"),
            ("users", "password_hash"),
            ("users", "nonexistent"),
            ("invoices", "secret"),
            ("unknown_table", "created_at"),
            ("organisations", ""),
            ("users", " "),
        ],
    )
    def test_invalid_column_raises_value_error(self, table: str, column: str):
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name(table, column)

    def test_unknown_table_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid column name"):
            validate_column_name("nonexistent_table", "created_at")


# ---------------------------------------------------------------------------
# Allowlist completeness sanity check
# ---------------------------------------------------------------------------


class TestAllowedSortColumnsStructure:
    """Verify the allowlist dict has the expected tables and is non-empty."""

    def test_contains_organisations(self):
        assert "organisations" in _ALLOWED_SORT_COLUMNS
        assert len(_ALLOWED_SORT_COLUMNS["organisations"]) > 0

    def test_contains_users(self):
        assert "users" in _ALLOWED_SORT_COLUMNS
        assert len(_ALLOWED_SORT_COLUMNS["users"]) > 0

    def test_contains_invoices(self):
        assert "invoices" in _ALLOWED_SORT_COLUMNS
        assert len(_ALLOWED_SORT_COLUMNS["invoices"]) > 0
