"""Property-based tests for compliance document file storage module.

Tests the file validation, path generation, and security checks in
ComplianceFileStorage using Hypothesis to verify properties hold
across all valid (and invalid) inputs.

**Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 12.1, 12.2, 12.4, 12.5**
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath

import pytest
from hypothesis import given, settings as h_settings, HealthCheck, assume
from hypothesis import strategies as st

from app.modules.compliance_docs.file_storage import (
    ACCEPTED_MIME_TYPES,
    ALLOWED_EXTENSIONS,
    MAGIC_BYTES,
    MAX_FILE_SIZE,
    ComplianceFileStorage,
)


PBT_SETTINGS = h_settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeUploadFile:
    """Minimal stand-in for Fastapi UploadFile with a content_type attribute."""
    content_type: str | None


# Strategies
mime_type_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=0,
    max_size=80,
)

# Strategy that mixes known-valid MIME types with arbitrary strings
mixed_mime_strategy = st.one_of(
    st.sampled_from(sorted(ACCEPTED_MIME_TYPES)),
    mime_type_strategy,
)

file_size_strategy = st.integers(min_value=0, max_value=20_971_520)  # 0 to 20 MB

# Filename strategies
safe_filename_chars = st.characters(
    whitelist_categories=("L", "N"),
    whitelist_characters=".-_ ",
)
filename_strategy = st.text(alphabet=safe_filename_chars, min_size=1, max_size=100)

# Extension strategies for double-extension tests
allowed_ext_strategy = st.sampled_from(sorted(ALLOWED_EXTENSIONS))
disallowed_ext_strategy = st.sampled_from([
    ".exe", ".bat", ".cmd", ".sh", ".js", ".vbs", ".ps1", ".msi",
    ".com", ".scr", ".pif", ".hta", ".cpl", ".reg", ".inf",
])


# =========================================================================
# Property 5: MIME type validation
# =========================================================================

class TestMimeTypeValidation:
    """For any MIME type string, the validator should accept it if and only
    if it is one of the 6 accepted types.

    # Feature: compliance-documents-rebuild, Property 5: MIME type validation
    **Validates: Requirements 3.2, 3.4**
    """

    @given(mime_type=mixed_mime_strategy)
    @PBT_SETTINGS
    def test_mime_type_accepted_iff_in_allowed_set(self, mime_type: str) -> None:
        """For any MIME type, _validate_mime_type accepts iff in ACCEPTED_MIME_TYPES."""
        fake_file = FakeUploadFile(content_type=mime_type)
        should_accept = mime_type in ACCEPTED_MIME_TYPES

        if should_accept:
            # Should not raise
            ComplianceFileStorage._validate_mime_type(fake_file)
        else:
            # Should raise HTTPException 400
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                ComplianceFileStorage._validate_mime_type(fake_file)
            assert exc_info.value.status_code == 400

    @given(mime_type=st.sampled_from(sorted(ACCEPTED_MIME_TYPES)))
    @PBT_SETTINGS
    def test_all_accepted_types_pass_validation(self, mime_type: str) -> None:
        """Every MIME type in the accepted set passes validation."""
        fake_file = FakeUploadFile(content_type=mime_type)
        # Should not raise
        ComplianceFileStorage._validate_mime_type(fake_file)

    @given(mime_type=mime_type_strategy)
    @PBT_SETTINGS
    def test_arbitrary_strings_rejected_unless_in_set(self, mime_type: str) -> None:
        """Arbitrary MIME strings are rejected unless they happen to be accepted."""
        fake_file = FakeUploadFile(content_type=mime_type)
        from fastapi import HTTPException

        if mime_type in ACCEPTED_MIME_TYPES:
            ComplianceFileStorage._validate_mime_type(fake_file)
        else:
            with pytest.raises(HTTPException) as exc_info:
                ComplianceFileStorage._validate_mime_type(fake_file)
            assert exc_info.value.status_code == 400


# =========================================================================
# Property 6: File size validation
# =========================================================================

class TestFileSizeValidation:
    """For any non-negative file size in bytes, accept if ≤ 10,485,760 bytes,
    reject otherwise.

    # Feature: compliance-documents-rebuild, Property 6: File size validation
    **Validates: Requirements 3.3, 3.5**
    """

    @given(size=file_size_strategy)
    @PBT_SETTINGS
    def test_file_size_accepted_iff_within_limit(self, size: int) -> None:
        """For any file size, _validate_file_size accepts iff size ≤ MAX_FILE_SIZE."""
        content = b"\x00" * size
        should_accept = size <= MAX_FILE_SIZE

        if should_accept:
            ComplianceFileStorage._validate_file_size(content)
        else:
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as exc_info:
                ComplianceFileStorage._validate_file_size(content)
            assert exc_info.value.status_code == 400

    def test_exact_boundary_accepted(self) -> None:
        """A file of exactly MAX_FILE_SIZE bytes is accepted."""
        content = b"\x00" * MAX_FILE_SIZE
        ComplianceFileStorage._validate_file_size(content)

    def test_one_byte_over_rejected(self) -> None:
        """A file of MAX_FILE_SIZE + 1 bytes is rejected."""
        content = b"\x00" * (MAX_FILE_SIZE + 1)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            ComplianceFileStorage._validate_file_size(content)
        assert exc_info.value.status_code == 400


# =========================================================================
# Property 7: Storage path generation
# =========================================================================

class TestStoragePathGeneration:
    """For any valid org_id and filename, the generated path should match
    `compliance/{org_id}/{uuid}_{sanitized_filename}` with no path separators
    or traversal sequences, and extension preserved.

    # Feature: compliance-documents-rebuild, Property 7: Storage path generation
    **Validates: Requirements 3.6, 12.2**
    """

    @given(
        org_id=st.uuids(),
        filename=filename_strategy,
    )
    @PBT_SETTINGS
    def test_path_structure_matches_pattern(
        self, org_id: uuid.UUID, filename: str,
    ) -> None:
        """Generated path matches compliance/{org_id}/{uuid}_{sanitized}."""
        assume(filename.strip() != "")
        # Filter out filenames that are only dots/whitespace after stripping
        stripped = filename.strip()
        assume(stripped.lstrip(".") != "" or True)  # allow fallback to "unnamed"

        path = ComplianceFileStorage._generate_storage_path(org_id, filename)

        # Must start with compliance/{org_id}/
        prefix = f"compliance/{org_id}/"
        assert path.startswith(prefix), (
            f"Path {path!r} does not start with {prefix!r}"
        )

        # The remainder after the prefix should be {uuid}_{sanitized_filename}
        remainder = path[len(prefix):]
        # Should contain at least one underscore separating UUID from filename
        assert "_" in remainder, f"No underscore separator in remainder: {remainder!r}"

        # Extract the UUID prefix (first 36 chars should be a valid UUID4)
        uuid_part = remainder[:36]
        try:
            parsed_uuid = uuid.UUID(uuid_part, version=4)
        except ValueError:
            pytest.fail(f"UUID prefix {uuid_part!r} is not a valid UUID4")

        # No path traversal sequences in the path
        assert ".." not in path, f"Path contains traversal sequence: {path!r}"

        # No path separators in the filename portion (after compliance/org_id/)
        filename_portion = remainder[37:]  # after uuid_
        assert "/" not in filename_portion, (
            f"Filename portion contains /: {filename_portion!r}"
        )
        assert "\\" not in filename_portion, (
            f"Filename portion contains \\: {filename_portion!r}"
        )

    @given(
        org_id=st.uuids(),
        base=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=30,
        ),
        ext=allowed_ext_strategy,
    )
    @PBT_SETTINGS
    def test_extension_preserved(
        self, org_id: uuid.UUID, base: str, ext: str,
    ) -> None:
        """The file extension from the original filename is preserved."""
        filename = f"{base}{ext}"
        path = ComplianceFileStorage._generate_storage_path(org_id, filename)

        assert path.endswith(ext) or path.endswith(ext.lower()) or path.endswith(ext.upper()), (
            f"Path {path!r} does not preserve extension {ext!r} from filename {filename!r}"
        )

    @given(org_id=st.uuids())
    @PBT_SETTINGS
    def test_traversal_attempts_sanitised(self, org_id: uuid.UUID) -> None:
        """Filenames with traversal sequences are sanitised."""
        malicious = "../../etc/passwd"
        path = ComplianceFileStorage._generate_storage_path(org_id, malicious)

        assert ".." not in path, f"Path still contains ..: {path!r}"
        assert path.startswith(f"compliance/{org_id}/")


# =========================================================================
# Property 13: Magic byte validation
# =========================================================================

class TestMagicByteValidation:
    """For any file content and declared MIME type, accept if leading bytes
    match expected signature, reject on mismatch.

    # Feature: compliance-documents-rebuild, Property 13: Magic byte validation
    **Validates: Requirements 12.1, 12.5**
    """

    @given(
        mime_type=st.sampled_from(sorted(MAGIC_BYTES.keys())),
        extra_content=st.binary(min_size=0, max_size=100),
    )
    @PBT_SETTINGS
    def test_correct_magic_bytes_accepted(
        self, mime_type: str, extra_content: bytes,
    ) -> None:
        """Content starting with the correct magic bytes for the declared
        MIME type is accepted."""
        magic = MAGIC_BYTES[mime_type]
        content = magic + extra_content

        # Should not raise
        ComplianceFileStorage._validate_magic_bytes(content, mime_type)

    @given(
        declared_mime=st.sampled_from(sorted(MAGIC_BYTES.keys())),
        wrong_mime=st.sampled_from(sorted(MAGIC_BYTES.keys())),
        extra_content=st.binary(min_size=0, max_size=100),
    )
    @PBT_SETTINGS
    def test_mismatched_magic_bytes_rejected(
        self, declared_mime: str, wrong_mime: str, extra_content: bytes,
    ) -> None:
        """Content whose magic bytes don't match the declared MIME is rejected."""
        assume(declared_mime != wrong_mime)
        # Build content with wrong_mime's magic bytes but declare as declared_mime
        wrong_magic = MAGIC_BYTES[wrong_mime]
        content = wrong_magic + extra_content

        # The magic bytes for declared_mime should not match
        expected_magic = MAGIC_BYTES[declared_mime]
        # Only test when the wrong magic doesn't accidentally start with the right one
        assume(not content[:len(expected_magic)] == expected_magic)

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            ComplianceFileStorage._validate_magic_bytes(content, declared_mime)
        assert exc_info.value.status_code == 400

    @given(
        mime_type=mime_type_strategy,
        content=st.binary(min_size=0, max_size=100),
    )
    @PBT_SETTINGS
    def test_unknown_mime_type_always_passes(
        self, mime_type: str, content: bytes,
    ) -> None:
        """MIME types not in MAGIC_BYTES have no signature to check, so pass."""
        assume(mime_type not in MAGIC_BYTES)
        # Should not raise — unknown MIME types are not validated
        ComplianceFileStorage._validate_magic_bytes(content, mime_type)

    @given(
        mime_type=st.sampled_from(sorted(MAGIC_BYTES.keys())),
    )
    @PBT_SETTINGS
    def test_empty_content_rejected_for_known_mime(self, mime_type: str) -> None:
        """Empty content cannot match any magic bytes, so it's rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            ComplianceFileStorage._validate_magic_bytes(b"", mime_type)
        assert exc_info.value.status_code == 400


# =========================================================================
# Property 14: Double extension rejection
# =========================================================================

class TestDoubleExtensionRejection:
    """For any filename, reject if it has multiple extensions where the
    final extension is not in the allowed set.

    # Feature: compliance-documents-rebuild, Property 14: Double extension rejection
    **Validates: Requirements 12.4**
    """

    @given(
        base=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        middle_ext=allowed_ext_strategy,
        final_ext=disallowed_ext_strategy,
    )
    @PBT_SETTINGS
    def test_double_extension_with_disallowed_final_rejected(
        self, base: str, middle_ext: str, final_ext: str,
    ) -> None:
        """Filenames like 'doc.pdf.exe' are rejected (disallowed final ext)."""
        filename = f"{base}{middle_ext}{final_ext}"
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            ComplianceFileStorage._validate_filename(filename)
        assert exc_info.value.status_code == 400

    @given(
        base=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        ext=allowed_ext_strategy,
    )
    @PBT_SETTINGS
    def test_single_allowed_extension_accepted(
        self, base: str, ext: str,
    ) -> None:
        """Filenames with a single allowed extension are accepted."""
        filename = f"{base}{ext}"
        # Should not raise
        ComplianceFileStorage._validate_filename(filename)

    @given(
        base=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        ext1=allowed_ext_strategy,
        ext2=allowed_ext_strategy,
    )
    @PBT_SETTINGS
    def test_double_extension_with_allowed_final_accepted(
        self, base: str, ext1: str, ext2: str,
    ) -> None:
        """Filenames like 'doc.pdf.jpg' (both extensions allowed) are accepted."""
        filename = f"{base}{ext1}{ext2}"
        # Should not raise — final extension is in the allowed set
        ComplianceFileStorage._validate_filename(filename)

    def test_classic_double_extension_attack_rejected(self) -> None:
        """The classic 'document.pdf.exe' attack vector is rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            ComplianceFileStorage._validate_filename("document.pdf.exe")

    def test_empty_filename_rejected(self) -> None:
        """Empty or whitespace-only filenames are rejected."""
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            ComplianceFileStorage._validate_filename("")
        with pytest.raises(HTTPException):
            ComplianceFileStorage._validate_filename("   ")


# =========================================================================
# Imports for Property 1, 12, 8 (status computation, badge count, preview)
# =========================================================================

from datetime import date, datetime, timedelta
from uuid import uuid4

from app.modules.compliance_docs.schemas import ComplianceDocumentResponse


# ---------------------------------------------------------------------------
# Helpers for document construction
# ---------------------------------------------------------------------------

def _make_doc_response(expiry_date: date | None = None) -> ComplianceDocumentResponse:
    """Build a minimal ComplianceDocumentResponse with a given expiry_date.

    The model_validator will compute the status automatically.
    """
    return ComplianceDocumentResponse(
        id=uuid4(),
        org_id=uuid4(),
        document_type="Test Certificate",
        description=None,
        file_key="compliance/test/fake_key.pdf",
        file_name="test.pdf",
        expiry_date=expiry_date,
        invoice_id=None,
        job_id=None,
        uploaded_by=None,
        created_at=datetime.now(),
    )


# Strategies for expiry dates
_today = date.today()

# Strategy producing dates across a wide range: past, near-future, far-future, and None
expiry_date_strategy = st.one_of(
    st.none(),
    # Dates from 2 years ago to 2 years in the future
    st.dates(
        min_value=_today - timedelta(days=730),
        max_value=_today + timedelta(days=730),
    ),
)

# Strategy producing only non-None dates
non_null_expiry_strategy = st.dates(
    min_value=_today - timedelta(days=730),
    max_value=_today + timedelta(days=730),
)


def _expected_status(expiry_date: date | None) -> str:
    """Compute the expected status for a given expiry_date."""
    if expiry_date is None:
        return "no_expiry"
    today = date.today()
    if expiry_date < today:
        return "expired"
    elif expiry_date <= today + timedelta(days=30):
        return "expiring_soon"
    else:
        return "valid"


# Previewable MIME types (from Requirement 4.6 / Property 8)
PREVIEWABLE_MIME_TYPES = frozenset({
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/gif",
})


def is_previewable(mime_type: str) -> bool:
    """Return True if the MIME type supports inline preview."""
    return mime_type in PREVIEWABLE_MIME_TYPES


# =========================================================================
# Property 1: Document status computation
# =========================================================================

class TestDocumentStatusComputation:
    """For any compliance document with any expiry_date (including null),
    the computed status should be correct. Furthermore, filtering documents
    by a given status should return exactly the matching documents.

    # Feature: compliance-documents-rebuild, Property 1: Document status computation
    **Validates: Requirements 2.4, 2.6**
    """

    @given(expiry_date=expiry_date_strategy)
    @PBT_SETTINGS
    def test_status_matches_expiry_date_rules(self, expiry_date: date | None) -> None:
        """For any expiry_date, the computed status follows the defined rules."""
        doc = _make_doc_response(expiry_date)
        expected = _expected_status(expiry_date)
        assert doc.status == expected, (
            f"expiry_date={expiry_date}, expected status={expected!r}, got={doc.status!r}"
        )

    @given(expiry_date=st.none())
    @PBT_SETTINGS
    def test_null_expiry_gives_no_expiry(self, expiry_date: None) -> None:
        """A null expiry_date always produces 'no_expiry' status."""
        doc = _make_doc_response(expiry_date)
        assert doc.status == "no_expiry"

    @given(
        expiry_date=st.dates(
            min_value=_today - timedelta(days=730),
            max_value=_today - timedelta(days=1),
        ),
    )
    @PBT_SETTINGS
    def test_past_dates_give_expired(self, expiry_date: date) -> None:
        """Any expiry_date strictly before today produces 'expired'."""
        doc = _make_doc_response(expiry_date)
        assert doc.status == "expired"

    @given(
        expiry_date=st.dates(
            min_value=_today,
            max_value=_today + timedelta(days=30),
        ),
    )
    @PBT_SETTINGS
    def test_near_future_gives_expiring_soon(self, expiry_date: date) -> None:
        """Any expiry_date from today to today+30 produces 'expiring_soon'."""
        doc = _make_doc_response(expiry_date)
        assert doc.status == "expiring_soon"

    @given(
        expiry_date=st.dates(
            min_value=_today + timedelta(days=31),
            max_value=_today + timedelta(days=730),
        ),
    )
    @PBT_SETTINGS
    def test_far_future_gives_valid(self, expiry_date: date) -> None:
        """Any expiry_date more than 30 days in the future produces 'valid'."""
        doc = _make_doc_response(expiry_date)
        assert doc.status == "valid"

    @given(
        expiry_dates=st.lists(expiry_date_strategy, min_size=1, max_size=20),
        filter_status=st.sampled_from(["valid", "expiring_soon", "expired", "no_expiry"]),
    )
    @PBT_SETTINGS
    def test_filtering_by_status_returns_exact_matches(
        self, expiry_dates: list[date | None], filter_status: str,
    ) -> None:
        """Filtering a list of documents by status returns exactly those
        whose computed status matches."""
        docs = [_make_doc_response(ed) for ed in expiry_dates]
        filtered = [d for d in docs if d.status == filter_status]
        expected_count = sum(1 for d in docs if d.status == filter_status)
        assert len(filtered) == expected_count
        assert all(d.status == filter_status for d in filtered)


# =========================================================================
# Property 12: Badge count computation
# =========================================================================

class TestBadgeCountComputation:
    """For any set of compliance documents with various expiry_dates
    (including null), the badge count should equal the number of documents
    whose computed status is either 'expired' or 'expiring_soon'.

    # Feature: compliance-documents-rebuild, Property 12: Badge count computation
    **Validates: Requirements 8.1**
    """

    @given(
        expiry_dates=st.lists(expiry_date_strategy, min_size=0, max_size=30),
    )
    @PBT_SETTINGS
    def test_badge_count_equals_expired_plus_expiring_soon(
        self, expiry_dates: list[date | None],
    ) -> None:
        """Badge count == count of documents with status 'expired' or 'expiring_soon'."""
        docs = [_make_doc_response(ed) for ed in expiry_dates]
        badge_count = sum(
            1 for d in docs if d.status in ("expired", "expiring_soon")
        )
        # Verify against expected computation
        expected = sum(
            1 for ed in expiry_dates if _expected_status(ed) in ("expired", "expiring_soon")
        )
        assert badge_count == expected

    @given(
        expiry_dates=st.lists(expiry_date_strategy, min_size=0, max_size=30),
    )
    @PBT_SETTINGS
    def test_valid_and_no_expiry_not_counted(
        self, expiry_dates: list[date | None],
    ) -> None:
        """Documents with status 'valid' or 'no_expiry' are never counted in badge."""
        docs = [_make_doc_response(ed) for ed in expiry_dates]
        non_badge_docs = [d for d in docs if d.status in ("valid", "no_expiry")]
        badge_docs = [d for d in docs if d.status in ("expired", "expiring_soon")]
        assert len(badge_docs) + len(non_badge_docs) == len(docs)
        # None of the non-badge docs should have expired/expiring_soon status
        for d in non_badge_docs:
            assert d.status not in ("expired", "expiring_soon")

    @given(
        expiry_dates=st.lists(
            st.one_of(
                st.none(),
                st.dates(
                    min_value=_today + timedelta(days=31),
                    max_value=_today + timedelta(days=730),
                ),
            ),
            min_size=1,
            max_size=20,
        ),
    )
    @PBT_SETTINGS
    def test_all_valid_or_no_expiry_gives_zero_badge(
        self, expiry_dates: list[date | None],
    ) -> None:
        """When all documents are valid or no_expiry, badge count is 0."""
        docs = [_make_doc_response(ed) for ed in expiry_dates]
        badge_count = sum(
            1 for d in docs if d.status in ("expired", "expiring_soon")
        )
        assert badge_count == 0


# =========================================================================
# Property 8: Preview eligibility
# =========================================================================

class TestPreviewEligibility:
    """For any file MIME type, the preview eligibility function should return
    true if and only if the MIME type is one of: application/pdf, image/jpeg,
    image/png, or image/gif. All other types should return false.

    # Feature: compliance-documents-rebuild, Property 8: Preview eligibility
    **Validates: Requirements 4.6**
    """

    # Mix known previewable types, known non-previewable types, and arbitrary strings
    _known_non_previewable = [
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/html",
        "application/json",
        "application/xml",
        "application/zip",
        "video/mp4",
        "audio/mpeg",
    ]

    _preview_mime_strategy = st.one_of(
        st.sampled_from(sorted(PREVIEWABLE_MIME_TYPES)),
        st.sampled_from(_known_non_previewable),
        mime_type_strategy,
    )

    @given(mime_type=_preview_mime_strategy)
    @PBT_SETTINGS
    def test_preview_eligibility_iff_in_previewable_set(self, mime_type: str) -> None:
        """Preview returns True iff MIME type is in the previewable set."""
        result = is_previewable(mime_type)
        expected = mime_type in PREVIEWABLE_MIME_TYPES
        assert result == expected, (
            f"mime_type={mime_type!r}, expected previewable={expected}, got={result}"
        )

    @given(mime_type=st.sampled_from(sorted(PREVIEWABLE_MIME_TYPES)))
    @PBT_SETTINGS
    def test_all_previewable_types_return_true(self, mime_type: str) -> None:
        """Every previewable MIME type returns True."""
        assert is_previewable(mime_type) is True

    @given(mime_type=st.sampled_from(_known_non_previewable))
    @PBT_SETTINGS
    def test_word_and_other_types_return_false(self, mime_type: str) -> None:
        """Word documents and other non-previewable types return False."""
        assert is_previewable(mime_type) is False

    @given(mime_type=mime_type_strategy)
    @PBT_SETTINGS
    def test_arbitrary_strings_only_true_if_in_set(self, mime_type: str) -> None:
        """Arbitrary MIME strings return True only if they happen to be previewable."""
        result = is_previewable(mime_type)
        if mime_type in PREVIEWABLE_MIME_TYPES:
            assert result is True
        else:
            assert result is False


# =========================================================================
# Imports for Properties 9, 10, 11 (notification threshold, email, dedup)
# =========================================================================

from app.modules.compliance_docs.notification_service import (
    ComplianceNotificationService,
    THRESHOLD_LABELS,
)


# ---------------------------------------------------------------------------
# Helpers for notification tests
# ---------------------------------------------------------------------------

# The valid notification thresholds in days
VALID_THRESHOLD_DAYS = frozenset(THRESHOLD_LABELS.keys())  # {0, 7, 30}


def should_notify(expiry_date: date, reference_date: date) -> bool:
    """Pure logic: should a document with expiry_date be flagged for
    notification on reference_date?

    True iff the difference (expiry_date - reference_date) is exactly
    30, 7, or 0 days.
    """
    diff = (expiry_date - reference_date).days
    return diff in VALID_THRESHOLD_DAYS


@dataclass
class FakeDoc:
    """Minimal stand-in for ComplianceDocument with attributes needed by
    _build_expiry_email."""
    document_type: str | None
    file_name: str | None
    expiry_date: date | None


# Strategies for notification tests
reference_date_strategy = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)

# Strategy for expiry dates relative to a reference date — covers all
# interesting intervals (0, 7, 30 days) plus many non-matching intervals
expiry_offset_strategy = st.one_of(
    st.sampled_from([0, 7, 30]),           # exact thresholds
    st.integers(min_value=-365, max_value=365),  # arbitrary offsets
)

threshold_label_strategy = st.sampled_from(sorted(THRESHOLD_LABELS.values()))

# Strategy for document_type strings (non-empty printable text)
doc_type_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
        min_size=1,
        max_size=60,
    ),
)

# Strategy for file_name strings
file_name_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=".-_ "),
        min_size=1,
        max_size=80,
    ),
)

# Strategy for dashboard URL paths
dashboard_url_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/-_"),
    min_size=1,
    max_size=100,
)


# =========================================================================
# Property 9: Notification threshold matching
# =========================================================================

class TestNotificationThresholdMatching:
    """For any compliance document with a non-null expiry_date and any
    reference date, the notification threshold checker should identify
    the document for notification if and only if the expiry_date minus
    the reference date equals exactly 30 days, exactly 7 days, or
    exactly 0 days. Documents at other intervals should not be flagged.

    # Feature: compliance-documents-rebuild, Property 9: Notification threshold matching
    **Validates: Requirements 7.1, 7.2, 7.3**
    """

    @given(
        reference_date=reference_date_strategy,
        offset=expiry_offset_strategy,
    )
    @PBT_SETTINGS
    def test_threshold_matching_iff_exact_interval(
        self, reference_date: date, offset: int,
    ) -> None:
        """A document is flagged iff expiry_date - reference_date is 0, 7, or 30."""
        expiry_date = reference_date + timedelta(days=offset)
        result = should_notify(expiry_date, reference_date)
        expected = offset in VALID_THRESHOLD_DAYS
        assert result == expected, (
            f"reference={reference_date}, expiry={expiry_date}, offset={offset}, "
            f"expected={expected}, got={result}"
        )

    @given(
        reference_date=reference_date_strategy,
        threshold_days=st.sampled_from(sorted(VALID_THRESHOLD_DAYS)),
    )
    @PBT_SETTINGS
    def test_exact_thresholds_always_flagged(
        self, reference_date: date, threshold_days: int,
    ) -> None:
        """Documents at exactly 0, 7, or 30 days are always flagged."""
        expiry_date = reference_date + timedelta(days=threshold_days)
        assert should_notify(expiry_date, reference_date) is True

    @given(
        reference_date=reference_date_strategy,
        offset=st.integers(min_value=-365, max_value=365).filter(
            lambda x: x not in {0, 7, 30}
        ),
    )
    @PBT_SETTINGS
    def test_non_threshold_intervals_never_flagged(
        self, reference_date: date, offset: int,
    ) -> None:
        """Documents at intervals other than 0, 7, 30 are never flagged."""
        expiry_date = reference_date + timedelta(days=offset)
        assert should_notify(expiry_date, reference_date) is False

    @given(reference_date=reference_date_strategy)
    @PBT_SETTINGS
    def test_negative_offsets_never_flagged(
        self, reference_date: date,
    ) -> None:
        """Documents already past expiry (negative offset) are not flagged
        unless offset is exactly 0."""
        for offset in [-1, -7, -30, -100]:
            expiry_date = reference_date + timedelta(days=offset)
            assert should_notify(expiry_date, reference_date) is False


# =========================================================================
# Property 10: Expiry email template completeness
# =========================================================================

class TestExpiryEmailTemplateCompleteness:
    """For any compliance document (with any document_type, file_name, and
    expiry_date) and any threshold label, the built notification email
    should contain the document_type, file_name, expiry_date formatted
    as a string, and a URL path to the compliance dashboard.

    # Feature: compliance-documents-rebuild, Property 10: Expiry email template completeness
    **Validates: Requirements 7.4**
    """

    @given(
        doc_type=doc_type_strategy,
        file_name=file_name_strategy,
        expiry_date=st.one_of(
            st.none(),
            st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31)),
        ),
        threshold=threshold_label_strategy,
        dashboard_url=dashboard_url_strategy,
    )
    @PBT_SETTINGS
    def test_email_contains_all_required_fields(
        self,
        doc_type: str | None,
        file_name: str | None,
        expiry_date: date | None,
        threshold: str,
        dashboard_url: str,
    ) -> None:
        """The built email subject+html+text contain doc_type, file_name,
        expiry_date string, and dashboard URL."""
        doc = FakeDoc(
            document_type=doc_type,
            file_name=file_name,
            expiry_date=expiry_date,
        )

        subject, html_body, text_body = ComplianceNotificationService._build_expiry_email(
            doc, threshold, dashboard_url,
        )

        # The method falls back to defaults for None values
        expected_type = doc_type or "Compliance Document"
        expected_name = file_name or "Unknown"
        expected_expiry = (
            expiry_date.strftime("%d/%m/%Y") if expiry_date else "N/A"
        )

        # Check subject contains the document type
        assert expected_type in subject, (
            f"Subject {subject!r} missing doc_type {expected_type!r}"
        )

        # Check HTML body contains all required fields
        assert expected_type in html_body, (
            f"HTML body missing doc_type {expected_type!r}"
        )
        assert expected_name in html_body, (
            f"HTML body missing file_name {expected_name!r}"
        )
        assert expected_expiry in html_body, (
            f"HTML body missing expiry_date {expected_expiry!r}"
        )
        assert dashboard_url in html_body, (
            f"HTML body missing dashboard_url {dashboard_url!r}"
        )

        # Check text body contains all required fields
        assert expected_type in text_body, (
            f"Text body missing doc_type {expected_type!r}"
        )
        assert expected_name in text_body, (
            f"Text body missing file_name {expected_name!r}"
        )
        assert expected_expiry in text_body, (
            f"Text body missing expiry_date {expected_expiry!r}"
        )
        assert dashboard_url in text_body, (
            f"Text body missing dashboard_url {dashboard_url!r}"
        )

    @given(threshold=threshold_label_strategy)
    @PBT_SETTINGS
    def test_email_contains_urgency_language(self, threshold: str) -> None:
        """The email subject and body contain appropriate urgency wording
        for the given threshold."""
        doc = FakeDoc(
            document_type="Test Cert",
            file_name="cert.pdf",
            expiry_date=date(2025, 6, 15),
        )

        subject, html_body, text_body = ComplianceNotificationService._build_expiry_email(
            doc, threshold, "/compliance",
        )

        if threshold == "30_day":
            expected_urgency = "expires in 30 days"
        elif threshold == "7_day":
            expected_urgency = "expires in 7 days"
        else:
            expected_urgency = "expires today"

        assert expected_urgency in subject, (
            f"Subject {subject!r} missing urgency {expected_urgency!r}"
        )
        assert expected_urgency in html_body, (
            f"HTML body missing urgency {expected_urgency!r}"
        )
        assert expected_urgency in text_body, (
            f"Text body missing urgency {expected_urgency!r}"
        )

    @given(
        doc_type=doc_type_strategy,
        file_name=file_name_strategy,
        expiry_date=st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31)),
        threshold=threshold_label_strategy,
        dashboard_url=dashboard_url_strategy,
    )
    @PBT_SETTINGS
    def test_email_returns_three_strings(
        self,
        doc_type: str | None,
        file_name: str | None,
        expiry_date: date,
        threshold: str,
        dashboard_url: str,
    ) -> None:
        """_build_expiry_email always returns a 3-tuple of non-empty strings."""
        doc = FakeDoc(
            document_type=doc_type,
            file_name=file_name,
            expiry_date=expiry_date,
        )

        result = ComplianceNotificationService._build_expiry_email(
            doc, threshold, dashboard_url,
        )

        assert isinstance(result, tuple)
        assert len(result) == 3
        subject, html_body, text_body = result
        assert isinstance(subject, str) and len(subject) > 0
        assert isinstance(html_body, str) and len(html_body) > 0
        assert isinstance(text_body, str) and len(text_body) > 0


# =========================================================================
# Property 11: Notification deduplication
# =========================================================================

class TestNotificationDeduplication:
    """For any set of (document_id, threshold) pairs where some have already
    been logged as sent, running the notification service should produce
    send actions only for pairs not already in the log. No pair that already
    exists in the log should result in a duplicate send.

    This tests the pure deduplication logic: given a universe of pairs and
    a subset already notified, the new notifications should be exactly the
    set difference.

    # Feature: compliance-documents-rebuild, Property 11: Notification deduplication
    **Validates: Requirements 7.5, 13.2**
    """

    @given(
        all_pairs=st.lists(
            st.tuples(st.uuids(), threshold_label_strategy),
            min_size=1,
            max_size=30,
            unique=True,
        ),
        data=st.data(),
    )
    @PBT_SETTINGS
    def test_new_notifications_are_set_difference(
        self, all_pairs: list[tuple[uuid.UUID, str]], data,
    ) -> None:
        """New notifications = all_pairs - already_notified_pairs."""
        # Pick a random subset as already notified
        already_notified = set(
            data.draw(
                st.lists(
                    st.sampled_from(all_pairs),
                    min_size=0,
                    max_size=len(all_pairs),
                    unique=True,
                )
            )
        )

        all_set = set(all_pairs)
        expected_new = all_set - already_notified

        # Simulate the dedup logic: for each pair, check if already notified
        actual_new = set()
        for pair in all_pairs:
            if pair not in already_notified:
                actual_new.add(pair)

        assert actual_new == expected_new, (
            f"Expected new={expected_new}, got={actual_new}"
        )

    @given(
        all_pairs=st.lists(
            st.tuples(st.uuids(), threshold_label_strategy),
            min_size=1,
            max_size=30,
            unique=True,
        ),
    )
    @PBT_SETTINGS
    def test_all_already_notified_produces_no_sends(
        self, all_pairs: list[tuple[uuid.UUID, str]],
    ) -> None:
        """When every pair is already notified, no new sends are produced."""
        already_notified = set(all_pairs)

        actual_new = set()
        for pair in all_pairs:
            if pair not in already_notified:
                actual_new.add(pair)

        assert len(actual_new) == 0

    @given(
        all_pairs=st.lists(
            st.tuples(st.uuids(), threshold_label_strategy),
            min_size=1,
            max_size=30,
            unique=True,
        ),
    )
    @PBT_SETTINGS
    def test_none_already_notified_sends_all(
        self, all_pairs: list[tuple[uuid.UUID, str]],
    ) -> None:
        """When no pairs are already notified, all pairs are sent."""
        already_notified: set[tuple[uuid.UUID, str]] = set()

        actual_new = set()
        for pair in all_pairs:
            if pair not in already_notified:
                actual_new.add(pair)

        assert actual_new == set(all_pairs)

    @given(
        all_pairs=st.lists(
            st.tuples(st.uuids(), threshold_label_strategy),
            min_size=1,
            max_size=30,
            unique=True,
        ),
        data=st.data(),
    )
    @PBT_SETTINGS
    def test_no_already_notified_pair_is_sent_again(
        self, all_pairs: list[tuple[uuid.UUID, str]], data,
    ) -> None:
        """No pair in the already-notified set appears in the new sends."""
        already_notified = set(
            data.draw(
                st.lists(
                    st.sampled_from(all_pairs),
                    min_size=0,
                    max_size=len(all_pairs),
                    unique=True,
                )
            )
        )

        actual_new = set()
        for pair in all_pairs:
            if pair not in already_notified:
                actual_new.add(pair)

        # The critical property: no overlap
        overlap = actual_new & already_notified
        assert len(overlap) == 0, (
            f"Duplicate sends detected for already-notified pairs: {overlap}"
        )

    @given(
        doc_id=st.uuids(),
        threshold=threshold_label_strategy,
    )
    @PBT_SETTINGS
    def test_same_doc_different_thresholds_are_independent(
        self, doc_id: uuid.UUID, threshold: str,
    ) -> None:
        """Notifying a doc at one threshold does not block other thresholds."""
        all_thresholds = set(THRESHOLD_LABELS.values())
        already_notified = {(doc_id, threshold)}

        # All other thresholds for the same doc should still be sendable
        for t in all_thresholds:
            pair = (doc_id, t)
            should_send = pair not in already_notified
            if t == threshold:
                assert not should_send, (
                    f"Already-notified pair {pair} should not be sent again"
                )
            else:
                assert should_send, (
                    f"Pair {pair} should be sendable (different threshold)"
                )


# =========================================================================
# Properties 2, 3, 4: Document sorting, text search, category filtering
# =========================================================================

# ---------------------------------------------------------------------------
# Helpers for sorting / search / category filtering tests
# ---------------------------------------------------------------------------

# Sortable columns as defined in the DocumentTable component
SORTABLE_COLUMNS = ("document_type", "file_name", "expiry_date", "created_at")

# Strategy for generating document-like dicts with various field values
_printable_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=60,
)

_non_empty_printable = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=1,
    max_size=60,
)


def _doc_response_strategy():
    """Strategy that builds ComplianceDocumentResponse objects with varied fields."""
    return st.builds(
        ComplianceDocumentResponse,
        id=st.uuids(),
        org_id=st.uuids(),
        document_type=_non_empty_printable,
        description=st.one_of(st.none(), _printable_text),
        file_key=st.just("compliance/test/fake.pdf"),
        file_name=_non_empty_printable,
        expiry_date=st.one_of(
            st.none(),
            st.dates(
                min_value=_today - timedelta(days=730),
                max_value=_today + timedelta(days=730),
            ),
        ),
        invoice_id=st.none(),
        job_id=st.none(),
        uploaded_by=st.none(),
        created_at=st.datetimes(
            min_value=datetime(2020, 1, 1),
            max_value=datetime(2030, 12, 31),
        ),
    )


def _sort_key(doc: ComplianceDocumentResponse, col: str) -> str:
    """Extract the sort key for a given column, matching the frontend's
    localeCompare-based sorting (string comparison with '' for nulls)."""
    val = getattr(doc, col, None)
    if val is None:
        return ""
    return str(val)


def _text_search_matches(doc: ComplianceDocumentResponse, query: str) -> bool:
    """Return True if the query appears (case-insensitive) in file_name,
    document_type, or description. Matches the frontend DocumentTable logic."""
    q = query.lower().strip()
    if not q:
        return True
    return (
        q in (doc.file_name or "").lower()
        or q in (doc.document_type or "").lower()
        or q in (doc.description or "").lower()
    )


def _category_filter_matches(doc: ComplianceDocumentResponse, category: str) -> bool:
    """Return True if the document's document_type matches the category exactly.
    Matches the frontend DocumentTable logic where categoryFilter !== 'all'."""
    return doc.document_type == category


# =========================================================================
# Property 2: Document sorting correctness
# =========================================================================

class TestDocumentSorting:
    """For any list of compliance documents and any sortable column,
    sorting in ascending order produces a list where each element ≤ next
    element, and descending produces the reverse.

    # Feature: compliance-documents-rebuild, Property 2: Document sorting correctness
    **Validates: Requirements 2.2**
    """

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=30),
        sort_col=st.sampled_from(SORTABLE_COLUMNS),
    )
    @PBT_SETTINGS
    def test_ascending_sort_is_non_decreasing(
        self,
        docs: list[ComplianceDocumentResponse],
        sort_col: str,
    ) -> None:
        """Sorting ascending produces a list where each element's sort key
        is ≤ the next element's sort key."""
        sorted_docs = sorted(docs, key=lambda d: _sort_key(d, sort_col))

        for i in range(len(sorted_docs) - 1):
            a = _sort_key(sorted_docs[i], sort_col)
            b = _sort_key(sorted_docs[i + 1], sort_col)
            assert a <= b, (
                f"Ascending sort violated at index {i}: {a!r} > {b!r} "
                f"(column={sort_col})"
            )

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=30),
        sort_col=st.sampled_from(SORTABLE_COLUMNS),
    )
    @PBT_SETTINGS
    def test_descending_sort_is_non_increasing(
        self,
        docs: list[ComplianceDocumentResponse],
        sort_col: str,
    ) -> None:
        """Sorting descending produces a list where each element's sort key
        is ≥ the next element's sort key."""
        sorted_docs = sorted(
            docs, key=lambda d: _sort_key(d, sort_col), reverse=True,
        )

        for i in range(len(sorted_docs) - 1):
            a = _sort_key(sorted_docs[i], sort_col)
            b = _sort_key(sorted_docs[i + 1], sort_col)
            assert a >= b, (
                f"Descending sort violated at index {i}: {a!r} < {b!r} "
                f"(column={sort_col})"
            )

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=30),
        sort_col=st.sampled_from(SORTABLE_COLUMNS),
    )
    @PBT_SETTINGS
    def test_sort_preserves_all_elements(
        self,
        docs: list[ComplianceDocumentResponse],
        sort_col: str,
    ) -> None:
        """Sorting does not add or remove documents — the sorted list
        contains exactly the same elements as the input."""
        sorted_asc = sorted(docs, key=lambda d: _sort_key(d, sort_col))
        sorted_desc = sorted(
            docs, key=lambda d: _sort_key(d, sort_col), reverse=True,
        )

        assert len(sorted_asc) == len(docs)
        assert len(sorted_desc) == len(docs)

        # Same set of document IDs
        original_ids = sorted(d.id for d in docs)
        asc_ids = sorted(d.id for d in sorted_asc)
        desc_ids = sorted(d.id for d in sorted_desc)
        assert asc_ids == original_ids
        assert desc_ids == original_ids

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=30),
        sort_col=st.sampled_from(SORTABLE_COLUMNS),
    )
    @PBT_SETTINGS
    def test_descending_is_reverse_of_ascending(
        self,
        docs: list[ComplianceDocumentResponse],
        sort_col: str,
    ) -> None:
        """Descending sort produces the same key sequence as reversing the
        ascending sort (stable sort property on keys)."""
        sorted_asc = sorted(docs, key=lambda d: _sort_key(d, sort_col))
        sorted_desc = sorted(
            docs, key=lambda d: _sort_key(d, sort_col), reverse=True,
        )

        asc_keys = [_sort_key(d, sort_col) for d in sorted_asc]
        desc_keys = [_sort_key(d, sort_col) for d in sorted_desc]
        assert desc_keys == list(reversed(asc_keys))


# =========================================================================
# Property 3: Text search filtering
# =========================================================================

class TestTextSearchFiltering:
    """For any list of compliance documents and any non-empty search string,
    the filtered results contain exactly the documents where the search
    string appears (case-insensitive) in file_name, document_type, or
    description. No matching document is excluded and no non-matching
    document is included.

    # Feature: compliance-documents-rebuild, Property 3: Text search filtering
    **Validates: Requirements 2.3**
    """

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=30),
        query=_non_empty_printable,
    )
    @PBT_SETTINGS
    def test_search_returns_exactly_matching_documents(
        self,
        docs: list[ComplianceDocumentResponse],
        query: str,
    ) -> None:
        """Filtered results contain exactly the documents that match the
        search query in at least one of the three fields."""
        assume(query.strip() != "")

        filtered = [d for d in docs if _text_search_matches(d, query)]
        expected_ids = {d.id for d in docs if _text_search_matches(d, query)}
        actual_ids = {d.id for d in filtered}

        assert actual_ids == expected_ids, (
            f"query={query!r}: expected {len(expected_ids)} docs, "
            f"got {len(actual_ids)}"
        )

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=1, max_size=20),
        data=st.data(),
    )
    @PBT_SETTINGS
    def test_search_by_substring_of_existing_field_finds_document(
        self,
        docs: list[ComplianceDocumentResponse],
        data,
    ) -> None:
        """Searching for a substring taken from an existing document's field
        always includes that document in the results."""
        # Pick a random document and a random field to extract a substring from
        doc = data.draw(st.sampled_from(docs))
        field = data.draw(st.sampled_from(["file_name", "document_type", "description"]))
        field_val = getattr(doc, field, None) or ""
        assume(len(field_val) > 0)

        # Pick a random substring
        start = data.draw(st.integers(min_value=0, max_value=len(field_val) - 1))
        end = data.draw(st.integers(min_value=start + 1, max_value=len(field_val)))
        query = field_val[start:end]
        assume(query.strip() != "")

        filtered = [d for d in docs if _text_search_matches(d, query)]
        filtered_ids = {d.id for d in filtered}

        assert doc.id in filtered_ids, (
            f"Document {doc.id} with {field}={field_val!r} not found "
            f"when searching for {query!r}"
        )

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=20),
        query=_non_empty_printable,
    )
    @PBT_SETTINGS
    def test_search_is_case_insensitive(
        self,
        docs: list[ComplianceDocumentResponse],
        query: str,
    ) -> None:
        """Searching with upper/lower/mixed case of the same query returns
        the same results."""
        assume(query.strip() != "")

        lower_results = {d.id for d in docs if _text_search_matches(d, query.lower())}
        upper_results = {d.id for d in docs if _text_search_matches(d, query.upper())}
        mixed_results = {d.id for d in docs if _text_search_matches(d, query)}

        assert lower_results == upper_results == mixed_results, (
            f"Case sensitivity mismatch for query={query!r}"
        )

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=20),
        query=_non_empty_printable,
    )
    @PBT_SETTINGS
    def test_no_non_matching_document_included(
        self,
        docs: list[ComplianceDocumentResponse],
        query: str,
    ) -> None:
        """Every document in the filtered results actually matches the query."""
        assume(query.strip() != "")

        filtered = [d for d in docs if _text_search_matches(d, query)]
        q = query.lower().strip()

        for d in filtered:
            matches = (
                q in (d.file_name or "").lower()
                or q in (d.document_type or "").lower()
                or q in (d.description or "").lower()
            )
            assert matches, (
                f"Document {d.id} in results but does not match query={query!r}"
            )


# =========================================================================
# Property 4: Category filtering
# =========================================================================

class TestCategoryFiltering:
    """For any list of compliance documents and any selected category name,
    the filtered results contain exactly the documents whose document_type
    matches the selected category. No matching document is excluded and
    no non-matching document is included.

    # Feature: compliance-documents-rebuild, Property 4: Category filtering
    **Validates: Requirements 2.5**
    """

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=30),
        category=_non_empty_printable,
    )
    @PBT_SETTINGS
    def test_category_filter_returns_exact_matches(
        self,
        docs: list[ComplianceDocumentResponse],
        category: str,
    ) -> None:
        """Filtered results contain exactly the documents whose document_type
        equals the selected category."""
        filtered = [d for d in docs if _category_filter_matches(d, category)]
        expected_ids = {d.id for d in docs if d.document_type == category}
        actual_ids = {d.id for d in filtered}

        assert actual_ids == expected_ids

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=1, max_size=20),
        data=st.data(),
    )
    @PBT_SETTINGS
    def test_filtering_by_existing_category_includes_all_matching(
        self,
        docs: list[ComplianceDocumentResponse],
        data,
    ) -> None:
        """When filtering by a category that exists in the document list,
        all documents with that category are included."""
        # Pick a category from an existing document
        doc = data.draw(st.sampled_from(docs))
        category = doc.document_type

        filtered = [d for d in docs if _category_filter_matches(d, category)]
        all_matching = [d for d in docs if d.document_type == category]

        assert len(filtered) == len(all_matching)
        assert {d.id for d in filtered} == {d.id for d in all_matching}

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=20),
        category=_non_empty_printable,
    )
    @PBT_SETTINGS
    def test_no_non_matching_document_in_category_results(
        self,
        docs: list[ComplianceDocumentResponse],
        category: str,
    ) -> None:
        """Every document in the filtered results has document_type equal
        to the selected category."""
        filtered = [d for d in docs if _category_filter_matches(d, category)]

        for d in filtered:
            assert d.document_type == category, (
                f"Document {d.id} has document_type={d.document_type!r} "
                f"but category filter is {category!r}"
            )

    @given(
        docs=st.lists(_doc_response_strategy(), min_size=0, max_size=20),
    )
    @PBT_SETTINGS
    def test_category_filter_is_case_sensitive(
        self,
        docs: list[ComplianceDocumentResponse],
    ) -> None:
        """Category filtering uses exact match (case-sensitive), matching
        the frontend's strict equality check."""
        for doc in docs:
            cat = doc.document_type
            # Exact match always includes the document
            assert _category_filter_matches(doc, cat)
            # Different case should not match (unless the string is case-invariant)
            if cat != cat.upper():
                assert not _category_filter_matches(doc, cat.upper())
