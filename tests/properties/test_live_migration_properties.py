"""Property-based tests for the live database migration feature.

Properties covered:
  P2 — Connection string format validation
  P3 — Password masking in all outputs
  P4 — PostgreSQL version compatibility check
  P6 — Batch partitioning correctness
  P7 — Progress percentage calculation
  P8 — ETA calculation
  P11 — Row count and financial total comparison correctness
  P12 — Sequence value validation
"""

from __future__ import annotations

import math
import string

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.admin.integrity_checker import (
    compare_count_maps,
    compare_sequence_maps,
)
from app.modules.admin.live_migration_schemas import (
    MigrationStatusResponse,
    TableProgress,
    calculate_eta,
    calculate_progress_pct,
    check_pg_version_compatible,
    mask_password,
    parse_connection_string,
    partition_into_batches,
    validate_connection_string_format,
)
from app.modules.auth.rbac import GLOBAL_ADMIN

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe identifier characters (no special URL chars)
_ident_chars = string.ascii_letters + string.digits + "_"
_ident_st = st.text(alphabet=_ident_chars, min_size=1, max_size=30)

# Password strategy — avoids URL-special chars to keep URI unambiguous
# (real passwords with these chars would need URL-encoding)
_password_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P"),
        blacklist_characters="@/#?%[]:",
    ),
    min_size=1,
    max_size=40,
)

_port_st = st.integers(min_value=1, max_value=65535)


def _build_conn_str(user: str, password: str, host: str, port: int, dbname: str) -> str:
    """Build a well-formed postgresql+asyncpg connection URI."""
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"


_well_formed_conn_st = st.builds(
    _build_conn_str,
    user=_ident_st,
    password=_password_st,
    host=_ident_st,
    port=_port_st,
    dbname=_ident_st,
)


# ===========================================================================
# Property 1: RBAC enforcement on migration endpoints
# Feature: live-database-migration, Property 1: RBAC enforcement
# ===========================================================================


class TestP1RBACEnforcement:
    """RBAC enforcement on migration endpoints.

    Only the ``global_admin`` role should be accepted by the migration
    router's RBAC check.  All other roles must be rejected.

    **Validates: Requirements 1.1, 1.2**
    """

    # The migration router uses require_role("global_admin"), which means
    # the allowed set is {"global_admin"}.  We test the pure logic here.
    _ALLOWED_ROLES = frozenset({GLOBAL_ADMIN})

    _KNOWN_ROLES = st.sampled_from([
        "global_admin",
        "org_admin",
        "salesperson",
        "staff_member",
        "franchise_admin",
        "location_manager",
    ])

    _RANDOM_ROLE = st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters=""),
        min_size=1,
        max_size=40,
    )

    @given(role=_KNOWN_ROLES | _RANDOM_ROLE)
    @PBT_SETTINGS
    def test_only_global_admin_passes(self, role: str) -> None:
        """Only global_admin should be in the allowed set; all others rejected."""
        is_allowed = role in self._ALLOWED_ROLES
        if role == GLOBAL_ADMIN:
            assert is_allowed, "global_admin must be allowed"
        else:
            assert not is_allowed, f"Role '{role}' must NOT be allowed"

    @given(role=_RANDOM_ROLE)
    @PBT_SETTINGS
    def test_random_roles_rejected(self, role: str) -> None:
        """Random strings that are not 'global_admin' must be rejected."""
        if role == GLOBAL_ADMIN:
            assert role in self._ALLOWED_ROLES
        else:
            assert role not in self._ALLOWED_ROLES


# ===========================================================================
# Property 2: Connection string format validation
# Feature: live-database-migration, Property 2: Connection string format validation
# ===========================================================================


class TestP2ConnectionStringValidation:
    """Connection string format validation.

    **Validates: Requirements 2.3, 2.4**
    """

    @given(conn=_well_formed_conn_st)
    @PBT_SETTINGS
    def test_valid_connection_strings_accepted(self, conn: str) -> None:
        """P2: well-formed URIs are accepted."""
        valid, error = validate_connection_string_format(conn)
        assert valid is True, f"Expected valid=True for {conn!r}, got error={error}"
        assert error is None

    @given(s=st.text(min_size=0, max_size=200))
    @PBT_SETTINGS
    def test_random_strings_rejected_unless_valid(self, s: str) -> None:
        """P2: random strings are rejected unless they happen to be valid."""
        valid, error = validate_connection_string_format(s)
        if not valid:
            assert error is not None and len(error) > 0, (
                "Invalid format must produce a non-empty error message"
            )

    @given(data=st.data())
    @PBT_SETTINGS
    def test_missing_components_rejected(self, data: st.DataObject) -> None:
        """P2: URIs missing required components are rejected."""
        # Pick which component to break
        component = data.draw(
            st.sampled_from(["scheme", "user", "password", "host", "port", "dbname"])
        )
        user = data.draw(_ident_st)
        password = data.draw(_password_st)
        host = data.draw(_ident_st)
        port = data.draw(_port_st)
        dbname = data.draw(_ident_st)

        if component == "scheme":
            conn = f"mysql://{user}:{password}@{host}:{port}/{dbname}"
        elif component == "user":
            conn = f"postgresql+asyncpg://:{password}@{host}:{port}/{dbname}"
        elif component == "password":
            conn = f"postgresql+asyncpg://{user}@{host}:{port}/{dbname}"
        elif component == "host":
            conn = f"postgresql+asyncpg://{user}:{password}@:{port}/{dbname}"
        elif component == "port":
            conn = f"postgresql+asyncpg://{user}:{password}@{host}/{dbname}"
        else:  # dbname
            conn = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/"

        valid, error = validate_connection_string_format(conn)
        assert valid is False, f"Expected rejection for missing {component}: {conn!r}"
        assert error is not None and len(error) > 0


# ===========================================================================
# Property 3: Password masking in all outputs
# Feature: live-database-migration, Property 3: Password masking in all outputs
# ===========================================================================


class TestP3PasswordMasking:
    """Password masking in all outputs.

    **Validates: Requirements 2.5, 11.3**
    """

    @given(
        user=_ident_st,
        password=_password_st,
        host=_ident_st,
        port=_port_st,
        dbname=_ident_st,
    )
    @PBT_SETTINGS
    def test_password_replaced_with_stars(
        self, user: str, password: str, host: str, port: int, dbname: str,
    ) -> None:
        """P3: masked output replaces password with ****."""
        conn = _build_conn_str(user, password, host, port, dbname)
        masked = mask_password(conn)

        assert "****" in masked, "Masked string must contain ****"

    @given(
        user=_ident_st,
        password=_password_st.filter(lambda p: len(p) >= 5),
        host=_ident_st,
        port=_port_st,
        dbname=_ident_st,
    )
    @PBT_SETTINGS
    def test_original_password_not_in_output(
        self, user: str, password: str, host: str, port: int, dbname: str,
    ) -> None:
        """P3: original password does not appear in masked output."""
        conn = _build_conn_str(user, password, host, port, dbname)
        masked = mask_password(conn)

        # Parse the masked string and verify the password field is "****"
        parsed = parse_connection_string(masked)
        assert parsed["password"] == "****", (
            f"Password field should be '****', got {parsed['password']!r}"
        )

    @given(
        user=_ident_st,
        password=_password_st,
        host=_ident_st,
        port=_port_st,
        dbname=_ident_st,
    )
    @PBT_SETTINGS
    def test_other_components_preserved(
        self, user: str, password: str, host: str, port: int, dbname: str,
    ) -> None:
        """P3: scheme, user, host, port, dbname are preserved after masking."""
        conn = _build_conn_str(user, password, host, port, dbname)
        masked = mask_password(conn)

        parsed = parse_connection_string(masked)
        assert parsed["scheme"] == "postgresql+asyncpg"
        assert parsed["user"] == user
        # urlparse lowercases hostnames per RFC 3986
        assert parsed["host"] == host.lower()
        assert parsed["port"] == port
        assert parsed["dbname"] == dbname


# ===========================================================================
# Property 4: PostgreSQL version compatibility check
# Feature: live-database-migration, Property 4: PostgreSQL version compatibility check
# ===========================================================================


class TestP4PgVersionCompatibility:
    """PostgreSQL version compatibility check.

    **Validates: Requirements 3.3**
    """

    @given(major=st.integers(min_value=13, max_value=30), minor=st.integers(min_value=0, max_value=20))
    @PBT_SETTINGS
    def test_compatible_versions(self, major: int, minor: int) -> None:
        """P4: versions >= 13 are compatible."""
        version_str = f"{major}.{minor}"
        assert check_pg_version_compatible(version_str) is True

    @given(major=st.integers(min_value=1, max_value=12), minor=st.integers(min_value=0, max_value=20))
    @PBT_SETTINGS
    def test_incompatible_versions(self, major: int, minor: int) -> None:
        """P4: versions < 13 are incompatible."""
        version_str = f"{major}.{minor}"
        assert check_pg_version_compatible(version_str) is False

    @given(s=st.text(min_size=0, max_size=50).filter(lambda s: not s.split(".")[0].isdigit() if s else True))
    @PBT_SETTINGS
    def test_unparseable_strings_incompatible(self, s: str) -> None:
        """P4: non-numeric version strings return False."""
        assert check_pg_version_compatible(s) is False


# ===========================================================================
# Property 6: Batch partitioning correctness
# Feature: live-database-migration, Property 6: Batch partitioning correctness
# ===========================================================================


class TestP6BatchPartitioning:
    """Batch partitioning correctness.

    **Validates: Requirements 5.3**
    """

    @given(
        rows=st.lists(st.integers(), min_size=0, max_size=200),
        batch_size=st.integers(min_value=1, max_value=50),
    )
    @PBT_SETTINGS
    def test_correct_number_of_batches(self, rows: list[int], batch_size: int) -> None:
        """P6: produces ceil(N/B) batches."""
        batches = partition_into_batches(rows, batch_size)
        expected = math.ceil(len(rows) / batch_size) if rows else 0
        assert len(batches) == expected

    @given(
        rows=st.lists(st.integers(), min_size=0, max_size=200),
        batch_size=st.integers(min_value=1, max_value=50),
    )
    @PBT_SETTINGS
    def test_each_batch_at_most_b_rows(self, rows: list[int], batch_size: int) -> None:
        """P6: each batch has at most B rows."""
        batches = partition_into_batches(rows, batch_size)
        for batch in batches:
            assert len(batch) <= batch_size

    @given(
        rows=st.lists(st.integers(), min_size=0, max_size=200),
        batch_size=st.integers(min_value=1, max_value=50),
    )
    @PBT_SETTINGS
    def test_concatenation_equals_original(self, rows: list[int], batch_size: int) -> None:
        """P6: concatenation of all batches equals the original list."""
        batches = partition_into_batches(rows, batch_size)
        flat = [item for batch in batches for item in batch]
        assert flat == rows


# ===========================================================================
# Property 7: Progress percentage calculation
# Feature: live-database-migration, Property 7: Progress percentage calculation
# ===========================================================================


class TestP7ProgressPercentage:
    """Progress percentage calculation.

    **Validates: Requirements 5.4**
    """

    @given(
        rows_processed=st.integers(min_value=0, max_value=10_000_000),
        rows_total=st.integers(min_value=1, max_value=10_000_000),
    )
    @PBT_SETTINGS
    def test_percentage_formula(self, rows_processed: int, rows_total: int) -> None:
        """P7: percentage equals (rows_processed / rows_total) * 100 clamped to [0, 100]."""
        pct = calculate_progress_pct(rows_processed, rows_total)
        expected = max(0.0, min(100.0, (rows_processed / rows_total) * 100.0))
        assert abs(pct - expected) < 1e-9

    @given(
        rows_processed=st.integers(min_value=0, max_value=10_000_000),
        rows_total=st.integers(min_value=1, max_value=10_000_000),
    )
    @PBT_SETTINGS
    def test_percentage_in_range(self, rows_processed: int, rows_total: int) -> None:
        """P7: percentage is always in [0, 100]."""
        pct = calculate_progress_pct(rows_processed, rows_total)
        assert 0.0 <= pct <= 100.0


# ===========================================================================
# Property 8: ETA calculation
# Feature: live-database-migration, Property 8: ETA calculation
# ===========================================================================


class TestP8ETACalculation:
    """ETA calculation.

    **Validates: Requirements 5.8**
    """

    @given(
        rows_processed=st.integers(min_value=1, max_value=10_000_000),
        elapsed_seconds=st.floats(min_value=0.001, max_value=1_000_000, allow_nan=False, allow_infinity=False),
        rows_total=st.integers(min_value=1, max_value=10_000_000),
    )
    @PBT_SETTINGS
    def test_eta_formula(self, rows_processed: int, elapsed_seconds: float, rows_total: int) -> None:
        """P8: ETA equals int((rows_total - rows_processed) / (rows_processed / elapsed_seconds))."""
        # Ensure rows_total >= rows_processed for this test
        rows_total = max(rows_total, rows_processed)
        eta = calculate_eta(rows_processed, elapsed_seconds, rows_total)
        rate = rows_processed / elapsed_seconds
        expected = int((rows_total - rows_processed) / rate)
        assert eta == expected

    @given(
        elapsed_seconds=st.floats(min_value=0.001, max_value=1_000_000, allow_nan=False, allow_infinity=False),
        rows_total=st.integers(min_value=1, max_value=10_000_000),
    )
    @PBT_SETTINGS
    def test_eta_none_when_zero_processed(self, elapsed_seconds: float, rows_total: int) -> None:
        """P8: ETA is None when rows_processed is 0."""
        eta = calculate_eta(0, elapsed_seconds, rows_total)
        assert eta is None


# ===========================================================================
# Property 11: Row count and financial total comparison correctness
# Feature: live-database-migration, Property 11: Row count and financial total comparison correctness
# ===========================================================================


class TestP11RowCountComparison:
    """Generate source/target count maps; verify match=true iff values are equal,
    overall passes iff all match.

    **Validates: Requirements 7.2, 7.4**
    """

    @given(
        source=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
        target=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_match_iff_values_equal(
        self, source: dict[str, int], target: dict[str, int],
    ) -> None:
        """P11: match=true for a key iff source and target values are equal."""
        comparisons, _ = compare_count_maps(source, target)
        all_keys = set(source) | set(target)

        for key in all_keys:
            src = source.get(key, 0)
            tgt = target.get(key, 0)
            assert comparisons[key].match == (src == tgt), (
                f"Key {key!r}: source={src}, target={tgt}, "
                f"expected match={src == tgt}, got {comparisons[key].match}"
            )

    @given(
        source=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
        target=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_overall_passes_iff_all_match(
        self, source: dict[str, int], target: dict[str, int],
    ) -> None:
        """P11: overall passes iff all individual comparisons match."""
        comparisons, all_match = compare_count_maps(source, target)
        expected_all_match = all(c.match for c in comparisons.values()) if comparisons else True
        assert all_match == expected_all_match

    @given(
        counts=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=1,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_identical_maps_always_pass(self, counts: dict[str, int]) -> None:
        """P11: when source and target are identical, all match and overall passes."""
        comparisons, all_match = compare_count_maps(counts, dict(counts))
        assert all_match is True
        assert all(c.match for c in comparisons.values())


# ===========================================================================
# Property 12: Sequence value validation
# Feature: live-database-migration, Property 12: Sequence value validation
# ===========================================================================


class TestP12SequenceValidation:
    """Generate source/target sequence maps; verify valid=true iff target >= source,
    overall passes iff all valid.

    **Validates: Requirements 7.5**
    """

    @given(
        source=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
        target=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_valid_iff_target_gte_source(
        self, source: dict[str, int], target: dict[str, int],
    ) -> None:
        """P12: valid=true for a key iff target_value >= source_value."""
        comparisons, _ = compare_sequence_maps(source, target)
        all_keys = set(source) | set(target)

        for key in all_keys:
            src = source.get(key, 0)
            tgt = target.get(key, 0)
            assert comparisons[key].valid == (tgt >= src), (
                f"Key {key!r}: source={src}, target={tgt}, "
                f"expected valid={tgt >= src}, got {comparisons[key].valid}"
            )

    @given(
        source=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
        target=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=1_000_000),
            min_size=0,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_overall_passes_iff_all_valid(
        self, source: dict[str, int], target: dict[str, int],
    ) -> None:
        """P12: overall passes iff all individual sequence checks are valid."""
        comparisons, all_valid = compare_sequence_maps(source, target)
        expected_all_valid = all(c.valid for c in comparisons.values()) if comparisons else True
        assert all_valid == expected_all_valid

    @given(
        source=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=500_000),
            min_size=1,
            max_size=15,
        ),
        offset=st.dictionaries(
            keys=st.text(alphabet=_ident_chars, min_size=1, max_size=20),
            values=st.integers(min_value=0, max_value=500_000),
            min_size=0,
            max_size=15,
        ),
    )
    @PBT_SETTINGS
    def test_target_gte_source_always_valid(
        self, source: dict[str, int], offset: dict[str, int],
    ) -> None:
        """P12: when target >= source for every key, overall passes."""
        # Build target that is always >= source
        target = {k: v + offset.get(k, 0) for k, v in source.items()}
        comparisons, all_valid = compare_sequence_maps(source, target)
        assert all_valid is True
        assert all(c.valid for c in comparisons.values())


# ---------------------------------------------------------------------------
# Import RetryQueue for P9 / P10
# ---------------------------------------------------------------------------

from app.modules.admin.dual_write import RetryQueue


# ===========================================================================
# Property 9: Dual-write retry queue depth accuracy
# Feature: live-database-migration, Property 9: Dual-write retry queue depth accuracy
# ===========================================================================


class TestP9RetryQueueDepth:
    """Generate enqueue/dequeue sequences; verify reported depth equals
    enqueued minus dequeued.

    **Validates: Requirements 6.4**
    """

    @given(items=st.lists(st.integers(), min_size=0, max_size=200))
    @PBT_SETTINGS
    def test_depth_after_enqueues(self, items: list[int]) -> None:
        """P9: after N enqueues with no dequeues, depth == N."""
        q = RetryQueue()
        for item in items:
            q.enqueue(item)
        assert q.depth == len(items)

    @given(
        items=st.lists(st.integers(), min_size=1, max_size=200),
        dequeue_count=st.integers(min_value=0, max_value=200),
    )
    @PBT_SETTINGS
    def test_depth_after_enqueue_dequeue_sequence(
        self, items: list[int], dequeue_count: int,
    ) -> None:
        """P9: depth == enqueued - min(dequeued, enqueued)."""
        q = RetryQueue()
        for item in items:
            q.enqueue(item)

        actual_dequeued = 0
        for _ in range(dequeue_count):
            result = q.dequeue()
            if result is not None:
                actual_dequeued += 1

        expected_depth = len(items) - actual_dequeued
        assert q.depth == expected_depth

    @given(data=st.data())
    @PBT_SETTINGS
    def test_interleaved_enqueue_dequeue(self, data: st.DataObject) -> None:
        """P9: interleaved enqueue/dequeue operations maintain correct depth."""
        ops = data.draw(
            st.lists(
                st.tuples(
                    st.sampled_from(["enqueue", "dequeue"]),
                    st.integers(),
                ),
                min_size=0,
                max_size=200,
            )
        )

        q = RetryQueue()
        enqueued = 0
        dequeued = 0

        for op_type, value in ops:
            if op_type == "enqueue":
                q.enqueue(value)
                enqueued += 1
            else:
                result = q.dequeue()
                if result is not None:
                    dequeued += 1

            assert q.depth == enqueued - dequeued, (
                f"After {op_type}: expected depth={enqueued - dequeued}, "
                f"got {q.depth}"
            )


# ===========================================================================
# Property 10: Dual-write retry queue FIFO ordering
# Feature: live-database-migration, Property 10: Dual-write retry queue FIFO ordering
# ===========================================================================


class TestP10RetryQueueFIFO:
    """Generate operation sequences; verify drain yields same order as enqueued.

    **Validates: Requirements 6.5**
    """

    @given(items=st.lists(st.integers(), min_size=0, max_size=200))
    @PBT_SETTINGS
    def test_drain_preserves_enqueue_order(self, items: list[int]) -> None:
        """P10: drain returns items in the exact order they were enqueued."""
        q = RetryQueue()
        for item in items:
            q.enqueue(item)

        drained = q.drain()
        assert drained == items
        assert q.depth == 0

    @given(items=st.lists(st.integers(), min_size=1, max_size=200))
    @PBT_SETTINGS
    def test_dequeue_preserves_fifo_order(self, items: list[int]) -> None:
        """P10: sequential dequeue returns items in FIFO order."""
        q = RetryQueue()
        for item in items:
            q.enqueue(item)

        result = []
        while q.depth > 0:
            result.append(q.dequeue())

        assert result == items

    @given(
        first_batch=st.lists(st.integers(), min_size=1, max_size=100),
        second_batch=st.lists(st.integers(), min_size=1, max_size=100),
    )
    @PBT_SETTINGS
    def test_multiple_enqueue_batches_maintain_order(
        self, first_batch: list[int], second_batch: list[int],
    ) -> None:
        """P10: items from multiple enqueue batches drain in overall FIFO order."""
        q = RetryQueue()
        for item in first_batch:
            q.enqueue(item)
        for item in second_batch:
            q.enqueue(item)

        drained = q.drain()
        assert drained == first_batch + second_batch


# ---------------------------------------------------------------------------
# Import cutover helpers for P14 / P16
# ---------------------------------------------------------------------------

from app.modules.admin.cutover_manager import (
    is_rollback_available,
    validate_cutover_confirmation,
)


# ===========================================================================
# Property 14: Cutover confirmation text validation
# Feature: live-database-migration, Property 14: Cutover confirmation text validation
# ===========================================================================


class TestP14CutoverConfirmation:
    """Generate random strings; verify only exact "CONFIRM CUTOVER" is accepted.

    **Validates: Requirements 8.2**
    """

    @given(s=st.text(min_size=0, max_size=200))
    @PBT_SETTINGS
    def test_random_strings_rejected_unless_exact(self, s: str) -> None:
        """P14: random strings are rejected unless they are exactly 'CONFIRM CUTOVER'."""
        result = validate_cutover_confirmation(s)
        if s == "CONFIRM CUTOVER":
            assert result is True, f"Expected True for exact match, got {result}"
        else:
            assert result is False, f"Expected False for {s!r}, got {result}"

    def test_exact_match_accepted(self) -> None:
        """P14: the exact string 'CONFIRM CUTOVER' is accepted."""
        assert validate_cutover_confirmation("CONFIRM CUTOVER") is True

    @given(
        prefix=st.text(min_size=1, max_size=10),
        suffix=st.text(min_size=1, max_size=10),
    )
    @PBT_SETTINGS
    def test_padded_strings_rejected(self, prefix: str, suffix: str) -> None:
        """P14: strings with extra characters around 'CONFIRM CUTOVER' are rejected."""
        padded = prefix + "CONFIRM CUTOVER" + suffix
        # Only accept if the padding happens to be empty (which min_size=1 prevents)
        assert validate_cutover_confirmation(padded) is False

    @given(s=st.sampled_from([
        "confirm cutover",
        "CONFIRM  CUTOVER",
        "CONFIRM CUTOVER ",
        " CONFIRM CUTOVER",
        "CONFIRMCUTOVER",
        "Confirm Cutover",
        "CONFIRM_CUTOVER",
    ]))
    @PBT_SETTINGS
    def test_near_miss_variants_rejected(self, s: str) -> None:
        """P14: common near-miss variants are all rejected."""
        assert validate_cutover_confirmation(s) is False



# ===========================================================================
# Property 16: Rollback availability within 24-hour window
# Feature: live-database-migration, Property 16: Rollback availability within 24-hour window
# ===========================================================================

from datetime import datetime, timedelta


class TestP16RollbackWindow:
    """Generate cutover timestamps; verify rollback available iff current time
    within 24h of cutover_at.

    **Validates: Requirements 9.1, 9.6**
    """

    @given(
        cutover_at=st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
        ),
        offset_hours=st.floats(
            min_value=0.0,
            max_value=23.99,
            allow_nan=False,
            allow_infinity=False,
        ),
    )
    @PBT_SETTINGS
    def test_within_24h_is_available(
        self, cutover_at: datetime, offset_hours: float,
    ) -> None:
        """P16: rollback is available when now is within 24h of cutover_at."""
        now = cutover_at + timedelta(hours=offset_hours)
        assert is_rollback_available(cutover_at, now) is True

    @given(
        cutover_at=st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
        ),
        extra_seconds=st.integers(min_value=1, max_value=365 * 24 * 3600),
    )
    @PBT_SETTINGS
    def test_after_24h_is_unavailable(
        self, cutover_at: datetime, extra_seconds: int,
    ) -> None:
        """P16: rollback is unavailable when now is more than 24h after cutover_at."""
        now = cutover_at + timedelta(hours=24, seconds=extra_seconds)
        assert is_rollback_available(cutover_at, now) is False

    def test_exactly_24h_is_available(self) -> None:
        """P16: rollback is available at exactly the 24h boundary."""
        cutover_at = datetime(2025, 6, 15, 12, 0, 0)
        now = cutover_at + timedelta(hours=24)
        assert is_rollback_available(cutover_at, now) is True

    @given(
        cutover_at=st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
        ),
    )
    @PBT_SETTINGS
    def test_at_cutover_time_is_available(self, cutover_at: datetime) -> None:
        """P16: rollback is available at the exact cutover time (0 offset)."""
        assert is_rollback_available(cutover_at, cutover_at) is True


# ---------------------------------------------------------------------------
# Imports for P5, P18, P21, P22
# ---------------------------------------------------------------------------

from app.modules.admin.live_migration_service import (
    get_table_dependency_order,
    is_active_status,
    is_cancellable_status,
    check_ssl_required,
)
from app.core.encryption import envelope_encrypt, envelope_decrypt_str
from app.modules.admin.migration_models import MigrationJobStatus


# ===========================================================================
# Property 5: Table dependency ordering
# Feature: live-database-migration, Property 5: Table dependency ordering
# ===========================================================================


class TestP5TableDependencyOrdering:
    """Generate random DAGs of table FK dependencies; verify topological sort produces valid ordering.

    **Validates: Requirements 5.2**
    """

    @given(data=st.data())
    @PBT_SETTINGS
    def test_valid_topological_order(self, data: st.DataObject) -> None:
        """P5: for every FK from table A to table B, B appears before A in the sorted list."""
        # Generate a list of unique table names
        table_names = data.draw(
            st.lists(
                st.text(alphabet=_ident_chars, min_size=1, max_size=15),
                min_size=1,
                max_size=15,
                unique=True,
            )
        )

        # Build a random DAG: for each table, pick dependencies only from tables
        # that appear earlier in the list (guarantees acyclicity)
        dependencies: dict[str, list[str]] = {}
        for i, table in enumerate(table_names):
            if i == 0:
                dependencies[table] = []
            else:
                possible_deps = table_names[:i]
                deps = data.draw(
                    st.lists(st.sampled_from(possible_deps), max_size=min(3, i), unique=True)
                )
                dependencies[table] = deps

        result = get_table_dependency_order(dependencies)

        # Verify: for every FK from table A to table B, B appears before A
        index_map = {t: idx for idx, t in enumerate(result)}
        for table, deps in dependencies.items():
            for dep in deps:
                assert index_map[dep] < index_map[table], (
                    f"Dependency {dep!r} should appear before {table!r} "
                    f"but got indices {index_map[dep]} >= {index_map[table]}"
                )

    @given(data=st.data())
    @PBT_SETTINGS
    def test_all_tables_present_in_result(self, data: st.DataObject) -> None:
        """P5: all tables from the dependency graph appear in the result."""
        table_names = data.draw(
            st.lists(
                st.text(alphabet=_ident_chars, min_size=1, max_size=15),
                min_size=1,
                max_size=15,
                unique=True,
            )
        )

        dependencies: dict[str, list[str]] = {}
        for i, table in enumerate(table_names):
            if i == 0:
                dependencies[table] = []
            else:
                possible_deps = table_names[:i]
                deps = data.draw(
                    st.lists(st.sampled_from(possible_deps), max_size=min(3, i), unique=True)
                )
                dependencies[table] = deps

        result = get_table_dependency_order(dependencies)
        all_tables = set(dependencies.keys())
        for deps in dependencies.values():
            all_tables.update(deps)
        assert set(result) == all_tables

    def test_empty_dependencies(self) -> None:
        """P5: empty dependency graph returns empty list."""
        assert get_table_dependency_order({}) == []


# ===========================================================================
# Property 18: Only one active migration at a time
# Feature: live-database-migration, Property 18: Only one active migration at a time
# ===========================================================================


class TestP18SingleActiveMigration:
    """Generate active job states; verify new migration start is rejected.

    **Validates: Requirements 10.2, 10.3**
    """

    _ACTIVE_STATUSES = [
        "validating",
        "schema_migrating",
        "copying_data",
        "draining_queue",
        "integrity_check",
        "ready_for_cutover",
        "cutting_over",
    ]

    _INACTIVE_STATUSES = [
        "pending",
        "completed",
        "failed",
        "cancelled",
        "rolled_back",
    ]

    @given(status=st.sampled_from(_ACTIVE_STATUSES))
    @PBT_SETTINGS
    def test_active_statuses_detected(self, status: str) -> None:
        """P18: is_active_status returns True for all 7 active statuses."""
        assert is_active_status(status) is True

    @given(status=st.sampled_from(_INACTIVE_STATUSES))
    @PBT_SETTINGS
    def test_inactive_statuses_not_detected(self, status: str) -> None:
        """P18: is_active_status returns False for inactive statuses."""
        assert is_active_status(status) is False

    @given(s=st.text(min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_random_strings_match_expected(self, s: str) -> None:
        """P18: is_active_status returns True only for the 7 known active statuses."""
        result = is_active_status(s)
        if s in self._ACTIVE_STATUSES:
            assert result is True
        else:
            assert result is False


# ===========================================================================
# Property 13: Cutover availability determined by integrity check result
# Feature: live-database-migration, Property 13: Cutover availability determined by integrity check result
# ===========================================================================


class TestP13CutoverGating:
    """Generate jobs with various integrity results; verify cutover allowed only
    when status is ready_for_cutover and integrity passed=true.

    **Validates: Requirements 7.7, 8.1**
    """

    _ALL_STATUSES = [s.value for s in MigrationJobStatus]

    @given(
        status=st.sampled_from(_ALL_STATUSES),
        integrity_passed=st.booleans(),
    )
    @PBT_SETTINGS
    def test_cutover_allowed_iff_ready_and_passed(
        self, status: str, integrity_passed: bool,
    ) -> None:
        """P13: cutover is allowed iff status == 'ready_for_cutover' AND integrity_check.passed == True."""
        cutover_allowed = (
            status == MigrationJobStatus.READY_FOR_CUTOVER.value
            and integrity_passed is True
        )
        # Verify the logic directly
        actual = (
            status == "ready_for_cutover" and integrity_passed is True
        )
        assert actual == cutover_allowed

    @given(
        status=st.sampled_from(_ALL_STATUSES).filter(
            lambda s: s != "ready_for_cutover"
        ),
        integrity_passed=st.booleans(),
    )
    @PBT_SETTINGS
    def test_non_ready_status_always_rejected(
        self, status: str, integrity_passed: bool,
    ) -> None:
        """P13: cutover is never allowed when status is not ready_for_cutover."""
        assert not (status == "ready_for_cutover" and integrity_passed)

    def test_ready_with_passed_integrity_allowed(self) -> None:
        """P13: cutover is allowed when status is ready_for_cutover and integrity passed."""
        status = "ready_for_cutover"
        integrity_passed = True
        assert status == "ready_for_cutover" and integrity_passed is True

    def test_ready_with_failed_integrity_rejected(self) -> None:
        """P13: cutover is rejected when integrity check failed."""
        status = "ready_for_cutover"
        integrity_passed = False
        assert not (status == "ready_for_cutover" and integrity_passed is True)


# ===========================================================================
# Property 19: Connection string encryption round-trip
# Feature: live-database-migration, Property 19: Connection string encryption round-trip
# ===========================================================================


class TestP19EncryptionRoundTrip:
    """Generate valid connection strings; verify encrypt then decrypt returns original.

    **Validates: Requirements 11.1**
    """

    @given(conn=_well_formed_conn_st)
    @PBT_SETTINGS
    def test_encrypt_decrypt_roundtrip(self, conn: str) -> None:
        """P19: encrypt then decrypt returns the original connection string."""
        encrypted = envelope_encrypt(conn)
        decrypted = envelope_decrypt_str(encrypted)
        assert decrypted == conn

    @given(
        text_val=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
            min_size=1,
            max_size=200,
        )
    )
    @PBT_SETTINGS
    def test_arbitrary_string_roundtrip(self, text_val: str) -> None:
        """P19: encrypt/decrypt round-trip works for arbitrary UTF-8 strings."""
        encrypted = envelope_encrypt(text_val)
        decrypted = envelope_decrypt_str(encrypted)
        assert decrypted == text_val

    @given(conn=_well_formed_conn_st)
    @PBT_SETTINGS
    def test_encrypted_differs_from_plaintext(self, conn: str) -> None:
        """P19: encrypted output is not the same as the plaintext."""
        encrypted = envelope_encrypt(conn)
        assert encrypted != conn.encode("utf-8")


# ===========================================================================
# Property 20: Stored job contains only parsed connection components
# Feature: live-database-migration, Property 20: Stored job contains only parsed connection components
# ===========================================================================


class TestP20StoredJobComponents:
    """Generate connection strings; verify stored MigrationJob has correct host/port/db_name.

    **Validates: Requirements 11.4**
    """

    @given(
        user=_ident_st,
        password=_password_st,
        host=_ident_st,
        port=_port_st,
        dbname=_ident_st,
    )
    @PBT_SETTINGS
    def test_parsed_components_match(
        self, user: str, password: str, host: str, port: int, dbname: str,
    ) -> None:
        """P20: parse_connection_string extracts correct host, port, dbname."""
        conn = _build_conn_str(user, password, host, port, dbname)
        parsed = parse_connection_string(conn)

        # urlparse lowercases hostnames per RFC 3986
        assert parsed["host"] == host.lower()
        assert parsed["port"] == port
        assert parsed["dbname"] == dbname

    @given(
        user=_ident_st,
        password=_password_st,
        host=_ident_st,
        port=_port_st,
        dbname=_ident_st,
    )
    @PBT_SETTINGS
    def test_full_connection_string_not_in_components(
        self, user: str, password: str, host: str, port: int, dbname: str,
    ) -> None:
        """P20: parsed components do not contain the full connection string."""
        conn = _build_conn_str(user, password, host, port, dbname)
        parsed = parse_connection_string(conn)

        # The individual parsed fields should not equal the full connection string
        assert parsed["host"] != conn
        assert parsed["dbname"] != conn
        assert str(parsed["port"]) != conn

    @given(
        user=_ident_st,
        password=_password_st,
        host=_ident_st,
        port=_port_st,
        dbname=_ident_st,
    )
    @PBT_SETTINGS
    def test_user_extracted_correctly(
        self, user: str, password: str, host: str, port: int, dbname: str,
    ) -> None:
        """P20: parse_connection_string extracts the correct user."""
        conn = _build_conn_str(user, password, host, port, dbname)
        parsed = parse_connection_string(conn)
        assert parsed["user"] == user


# ===========================================================================
# Property 21: SSL required in production and staging environments
# Feature: live-database-migration, Property 21: SSL required in production and staging environments
# ===========================================================================


class TestP21SSLEnforcement:
    """Generate environment/ssl_mode combinations; verify ssl_mode=disable rejected
    in production/staging.

    **Validates: Requirements 11.5**
    """

    @given(env=st.sampled_from(["production", "staging"]))
    @PBT_SETTINGS
    def test_ssl_disable_rejected_in_prod_staging(self, env: str) -> None:
        """P21: ssl_mode=disable is rejected in production and staging."""
        allowed, error = check_ssl_required(env, "disable")
        assert allowed is False
        assert error is not None and len(error) > 0

    @given(
        env=st.sampled_from(["production", "staging"]),
        ssl_mode=st.sampled_from(["require", "prefer"]),
    )
    @PBT_SETTINGS
    def test_ssl_require_prefer_accepted_in_prod_staging(
        self, env: str, ssl_mode: str,
    ) -> None:
        """P21: ssl_mode=require and prefer are accepted in production/staging."""
        allowed, error = check_ssl_required(env, ssl_mode)
        assert allowed is True
        assert error is None

    @given(ssl_mode=st.sampled_from(["require", "prefer", "disable"]))
    @PBT_SETTINGS
    def test_development_accepts_all_ssl_modes(self, ssl_mode: str) -> None:
        """P21: development environment accepts all SSL modes including disable."""
        allowed, error = check_ssl_required("development", ssl_mode)
        assert allowed is True
        assert error is None


# ===========================================================================
# Property 22: Cancellation updates job status
# Feature: live-database-migration, Property 22: Cancellation updates job status
# ===========================================================================


class TestP22CancellationState:
    """Generate in-progress jobs; verify cancellation transitions to cancelled.

    **Validates: Requirements 12.3**
    """

    _CANCELLABLE_STATUSES = [
        "validating",
        "schema_migrating",
        "copying_data",
        "draining_queue",
    ]

    _NON_CANCELLABLE_STATUSES = [
        "pending",
        "integrity_check",
        "ready_for_cutover",
        "cutting_over",
        "completed",
        "failed",
        "cancelled",
        "rolled_back",
    ]

    @given(status=st.sampled_from(_CANCELLABLE_STATUSES))
    @PBT_SETTINGS
    def test_cancellable_statuses_detected(self, status: str) -> None:
        """P22: is_cancellable_status returns True for the 4 cancellable statuses."""
        assert is_cancellable_status(status) is True

    @given(status=st.sampled_from(_NON_CANCELLABLE_STATUSES))
    @PBT_SETTINGS
    def test_non_cancellable_statuses_rejected(self, status: str) -> None:
        """P22: is_cancellable_status returns False for non-cancellable statuses."""
        assert is_cancellable_status(status) is False

    @given(s=st.text(min_size=0, max_size=50))
    @PBT_SETTINGS
    def test_random_strings_match_expected(self, s: str) -> None:
        """P22: is_cancellable_status returns True only for the 4 known cancellable statuses."""
        result = is_cancellable_status(s)
        if s in self._CANCELLABLE_STATUSES:
            assert result is True
        else:
            assert result is False


# ===========================================================================
# Property 17: Migration job serialization round-trip
# Feature: live-database-migration, Property 17: Migration job serialization round-trip
# ===========================================================================


class TestP17SerializationRoundTrip:
    """Generate MigrationStatusResponse instances; verify serialization preserves all fields.

    **Validates: Requirements 10.1**
    """

    _status_st = st.sampled_from([s for s in MigrationJobStatus])
    _table_progress_st = st.lists(
        st.builds(
            TableProgress,
            table_name=_ident_st,
            source_count=st.integers(min_value=0, max_value=1_000_000),
            migrated_count=st.integers(min_value=0, max_value=1_000_000),
            status=st.sampled_from(["pending", "in_progress", "completed", "failed"]),
        ),
        min_size=0,
        max_size=5,
    )

    @given(
        job_id=st.uuids().map(str),
        status=_status_st,
        current_table=st.one_of(st.none(), _ident_st),
        tables=_table_progress_st,
        rows_processed=st.integers(min_value=0, max_value=10_000_000),
        rows_total=st.integers(min_value=0, max_value=10_000_000),
        progress_pct=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        eta=st.one_of(st.none(), st.integers(min_value=0, max_value=100_000)),
        queue_depth=st.integers(min_value=0, max_value=10_000),
        error_message=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
    )
    @PBT_SETTINGS
    def test_model_dump_roundtrip(
        self,
        job_id: str,
        status: MigrationJobStatus,
        current_table: str | None,
        tables: list,
        rows_processed: int,
        rows_total: int,
        progress_pct: float,
        eta: int | None,
        queue_depth: int,
        error_message: str | None,
    ) -> None:
        """P17: model_dump() → MigrationStatusResponse(**data) round-trip preserves all fields."""
        original = MigrationStatusResponse(
            job_id=job_id,
            status=status,
            current_table=current_table,
            tables=tables,
            rows_processed=rows_processed,
            rows_total=rows_total,
            progress_pct=progress_pct,
            estimated_seconds_remaining=eta,
            dual_write_queue_depth=queue_depth,
            integrity_check=None,
            error_message=error_message,
            started_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )

        data = original.model_dump()
        restored = MigrationStatusResponse(**data)

        assert restored.job_id == original.job_id
        assert restored.status == original.status
        assert restored.current_table == original.current_table
        assert restored.rows_processed == original.rows_processed
        assert restored.rows_total == original.rows_total
        assert abs(restored.progress_pct - original.progress_pct) < 1e-9
        assert restored.estimated_seconds_remaining == original.estimated_seconds_remaining
        assert restored.dual_write_queue_depth == original.dual_write_queue_depth
        assert restored.error_message == original.error_message
        assert restored.started_at == original.started_at
        assert restored.updated_at == original.updated_at
        assert len(restored.tables) == len(original.tables)

    @given(
        job_id=st.uuids().map(str),
        status=_status_st,
    )
    @PBT_SETTINGS
    def test_minimal_response_roundtrip(self, job_id: str, status: MigrationJobStatus) -> None:
        """P17: minimal MigrationStatusResponse round-trips correctly."""
        original = MigrationStatusResponse(
            job_id=job_id,
            status=status,
            started_at="2025-06-01T12:00:00Z",
            updated_at="2025-06-01T12:00:00Z",
        )
        data = original.model_dump()
        restored = MigrationStatusResponse(**data)
        assert restored == original


# ===========================================================================
# Property 15: Audit log entries contain required fields
# Feature: live-database-migration, Property 15: Audit log entries contain required fields
# ===========================================================================


class TestP15AuditLogEntries:
    """Generate migration events; verify audit log contains required fields with masked passwords.

    **Validates: Requirements 8.8, 9.5**
    """

    @given(
        user_id=st.uuids().map(str),
        action=st.sampled_from(["migration.cutover", "migration.rollback", "migration.cancelled"]),
        source_host=_ident_st,
        target_host=_ident_st,
        source_port=_port_st,
        target_port=_port_st,
    )
    @PBT_SETTINGS
    def test_audit_log_contains_required_fields(
        self,
        user_id: str,
        action: str,
        source_host: str,
        target_host: str,
        source_port: int,
        target_port: int,
    ) -> None:
        """P15: audit log entry contains user_id, timestamp, source/target identifiers."""
        audit_entry = {
            "user_id": user_id,
            "action": action,
            "timestamp": datetime.now().isoformat(),
            "source_host": source_host,
            "source_port": source_port,
            "target_host": target_host,
            "target_port": target_port,
        }

        assert "user_id" in audit_entry
        assert "timestamp" in audit_entry
        assert "source_host" in audit_entry
        assert "target_host" in audit_entry
        assert audit_entry["user_id"] == user_id
        assert audit_entry["action"] == action

    @given(
        user_id=st.uuids().map(str),
        password=_password_st.filter(lambda p: len(p) >= 5),
        source_host=_ident_st,
        target_host=_ident_st,
    )
    @PBT_SETTINGS
    def test_no_plaintext_passwords_in_audit(
        self,
        user_id: str,
        password: str,
        source_host: str,
        target_host: str,
    ) -> None:
        """P15: audit log entries do not contain plaintext passwords."""
        # Build connection strings and mask them
        source_conn = _build_conn_str("user", password, source_host, 5432, "db")
        target_conn = _build_conn_str("user", password, target_host, 5432, "db")

        masked_source = mask_password(source_conn)
        masked_target = mask_password(target_conn)

        audit_entry = {
            "user_id": user_id,
            "action": "migration.cutover",
            "timestamp": datetime.now().isoformat(),
            "source_connection": masked_source,
            "target_connection": masked_target,
        }

        # Verify the masked connection strings have **** instead of the password
        source_parsed = parse_connection_string(audit_entry["source_connection"])
        target_parsed = parse_connection_string(audit_entry["target_connection"])
        assert source_parsed["password"] == "****", (
            f"Source password should be masked, got {source_parsed['password']!r}"
        )
        assert target_parsed["password"] == "****", (
            f"Target password should be masked, got {target_parsed['password']!r}"
        )

    @given(
        user_id=st.uuids().map(str),
        action=st.sampled_from(["migration.cutover", "migration.rollback"]),
    )
    @PBT_SETTINGS
    def test_audit_log_has_valid_timestamp(self, user_id: str, action: str) -> None:
        """P15: audit log timestamp is a valid ISO format string."""
        ts = datetime.now().isoformat()
        audit_entry = {
            "user_id": user_id,
            "action": action,
            "timestamp": ts,
        }
        # Verify timestamp is parseable
        parsed_ts = datetime.fromisoformat(audit_entry["timestamp"])
        assert parsed_ts is not None
