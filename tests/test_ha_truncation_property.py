"""Property-based test: truncation table set correctness.

**Validates: Requirements 2.1**

For any set of public schema table names, the set of tables to truncate
equals the full set minus ``ha_config``. ``ha_config`` is never in the
truncation set. All other public tables are in the truncation set.

Uses Hypothesis to verify the ``filter_tables_for_truncation`` pure function.
"""

from __future__ import annotations

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.ha.replication import filter_tables_for_truncation

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid PostgreSQL table names: lowercase letters, digits, underscores.
# Must start with a letter or underscore, 1-63 chars.
pg_table_name = st.from_regex(r"[a-z_][a-z0-9_]{0,30}", fullmatch=True)

# A set of unique table names (as a list for the function input)
table_name_sets = st.lists(pg_table_name, min_size=0, max_size=50, unique=True)


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestTruncationTableSetCorrectness:
    """Property 5: Truncation Table Set Correctness.

    **Validates: Requirements 2.1**
    """

    @given(tables=table_name_sets)
    @PBT_SETTINGS
    def test_ha_config_never_in_truncation_set(self, tables: list[str]):
        """ha_config is never included in the truncation result,
        regardless of whether it appears in the input."""
        result = filter_tables_for_truncation(tables)
        assert "ha_config" not in result

    @given(tables=table_name_sets)
    @PBT_SETTINGS
    def test_truncation_set_equals_input_minus_ha_config(self, tables: list[str]):
        """The truncation set is exactly the input set minus ha_config."""
        result = filter_tables_for_truncation(tables)
        expected = [t for t in tables if t != "ha_config"]
        assert result == expected

    @given(tables=table_name_sets)
    @PBT_SETTINGS
    def test_all_non_ha_config_tables_included(self, tables: list[str]):
        """Every table in the input that is not ha_config appears in the result."""
        result_set = set(filter_tables_for_truncation(tables))
        for t in tables:
            if t != "ha_config":
                assert t in result_set

    @given(tables=table_name_sets)
    @PBT_SETTINGS
    def test_truncation_set_size(self, tables: list[str]):
        """The result size equals input size minus 1 if ha_config is present,
        otherwise equals input size."""
        result = filter_tables_for_truncation(tables)
        ha_config_count = tables.count("ha_config")
        assert len(result) == len(tables) - ha_config_count

    @given(
        tables=st.lists(
            pg_table_name.filter(lambda t: t != "ha_config"),
            min_size=1,
            max_size=50,
            unique=True,
        )
    )
    @PBT_SETTINGS
    def test_no_tables_lost_when_ha_config_absent(self, tables: list[str]):
        """When ha_config is not in the input, all tables pass through."""
        result = filter_tables_for_truncation(tables)
        assert result == tables

    @PBT_SETTINGS
    @given(
        tables=st.lists(pg_table_name, min_size=0, max_size=50, unique=True)
    )
    def test_ha_config_explicitly_present_still_excluded(self, tables: list[str]):
        """Even when ha_config is explicitly added to the input, it is excluded."""
        tables_with_ha = tables + ["ha_config"] if "ha_config" not in tables else tables
        result = filter_tables_for_truncation(tables_with_ha)
        assert "ha_config" not in result
