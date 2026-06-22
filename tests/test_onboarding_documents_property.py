"""Property-based test: document upload constraints for staff onboarding.

# Feature: staff-onboarding-link, Property 10: Document upload constraints

**Validates: Requirements 7.2, 7.3**

The public onboarding submit path validates staged working-rights documents
with the pure, side-effect-free ``validate_documents(files) -> bool`` helper in
``app/modules/staff/onboarding_validation.py``. The accepted set is:

* **count** — at most ``MAX_DOCUMENT_COUNT`` (3) files (R7.3); a missing/empty
  set is valid (documents are optional);
* **type** — each file's MIME type ∈ ``ACCEPTED_DOCUMENT_MIME_TYPES``
  (PDF / JPEG / PNG), compared case-insensitively (R7.2);
* **size** — each file's size is a non-bool ``int`` in
  ``[0, MAX_DOCUMENT_SIZE_BYTES]`` (10 MB) (R7.2).

These properties drive the generators below across ≥100 examples, with explicit
boundary coverage around exactly-10 MB / 10 MB + 1 and exactly-3 / 4 documents.
File descriptors are exercised in all three accepted shapes (dict, ``(mime,
size)`` tuple, attribute-bearing object) so the behaviour holds regardless of
how the caller stages the file list. This is a pure in-memory validator — no
database or storage is involved.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.staff.onboarding_validation import (
    ACCEPTED_DOCUMENT_MIME_TYPES,
    MAX_DOCUMENT_COUNT,
    MAX_DOCUMENT_SIZE_BYTES,
    validate_documents,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory validation.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=200, deadline=None)

_ACCEPTED_MIMES = sorted(ACCEPTED_DOCUMENT_MIME_TYPES)
_DISALLOWED_MIMES = [
    "image/gif",
    "application/msword",
    "text/plain",
    "application/zip",
    "video/mp4",
    "image/svg+xml",
    "application/octet-stream",
    "",
]


# ---------------------------------------------------------------------------
# File-descriptor builders — exercise all three accepted shapes.
# ---------------------------------------------------------------------------

class _UploadLike:
    """Attribute-bearing file descriptor (UploadFile-ish)."""

    def __init__(self, content_type, size):
        self.content_type = content_type
        self.size = size


def _as_descriptor(shape: str, mime, size):
    """Render a (mime, size) pair into one of the accepted descriptor shapes."""
    if shape == "dict":
        return {"content_type": mime, "size": size}
    if shape == "tuple":
        return (mime, size)
    return _UploadLike(mime, size)


_SHAPES = ("dict", "tuple", "object")


@st.composite
def _valid_file(draw, *, mime_pool=_ACCEPTED_MIMES):
    """A single valid file: accepted MIME (any case), size in [0, 10 MB]."""
    mime = draw(st.sampled_from(mime_pool))
    # Randomly vary the case to assert case-insensitive MIME comparison.
    if draw(st.booleans()):
        mime = mime.upper()
    size = draw(st.integers(min_value=0, max_value=MAX_DOCUMENT_SIZE_BYTES))
    shape = draw(st.sampled_from(_SHAPES))
    return _as_descriptor(shape, mime, size)


@st.composite
def _valid_file_set(draw):
    """0..MAX_DOCUMENT_COUNT valid files."""
    n = draw(st.integers(min_value=0, max_value=MAX_DOCUMENT_COUNT))
    return [draw(_valid_file()) for _ in range(n)]


# ---------------------------------------------------------------------------
# Property 10: Document upload constraints
# ---------------------------------------------------------------------------


class TestProperty10DocumentUploadConstraints:
    """Property 10: Document upload constraints.

    # Feature: staff-onboarding-link, Property 10: Document upload constraints

    **Validates: Requirements 7.2, 7.3**
    """

    @PBT_SETTINGS
    @given(files=_valid_file_set())
    def test_valid_sets_accepted(self, files):
        """0-3 files, accepted MIME, size in [0, 10 MB] are always accepted.

        **Validates: Requirements 7.2, 7.3**
        """
        assert validate_documents(files) is True

    @PBT_SETTINGS
    @given(st.none() | st.just([]) | st.just(()))
    def test_empty_or_missing_is_valid(self, files):
        """An omitted/empty document set is valid (documents are optional).

        **Validates: Requirements 7.3**
        """
        assert validate_documents(files) is True

    @PBT_SETTINGS
    @given(
        files=st.lists(
            _valid_file(),
            min_size=MAX_DOCUMENT_COUNT + 1,
            max_size=MAX_DOCUMENT_COUNT + 6,
        )
    )
    def test_too_many_files_rejected(self, files):
        """4+ otherwise-valid files exceed the count cap and are rejected.

        **Validates: Requirements 7.3**
        """
        assert len(files) > MAX_DOCUMENT_COUNT
        assert validate_documents(files) is False

    @PBT_SETTINGS
    @given(
        oversize=st.integers(
            min_value=MAX_DOCUMENT_SIZE_BYTES + 1,
            max_value=MAX_DOCUMENT_SIZE_BYTES * 4,
        ),
        mime=st.sampled_from(_ACCEPTED_MIMES),
        shape=st.sampled_from(_SHAPES),
    )
    def test_oversize_file_rejected(self, oversize, mime, shape):
        """A single file just over the 10 MB boundary is rejected.

        **Validates: Requirements 7.2**
        """
        files = [_as_descriptor(shape, mime, oversize)]
        assert validate_documents(files) is False

    @PBT_SETTINGS
    @given(
        disallowed=st.sampled_from(_DISALLOWED_MIMES),
        size=st.integers(min_value=0, max_value=MAX_DOCUMENT_SIZE_BYTES),
        shape=st.sampled_from(_SHAPES),
    )
    def test_disallowed_mime_rejected(self, disallowed, size, shape):
        """A disallowed MIME type (gif/msword/etc.) is rejected even at valid size.

        **Validates: Requirements 7.2**
        """
        files = [_as_descriptor(shape, disallowed, size)]
        assert validate_documents(files) is False

    # --- Explicit boundary examples (non-property, but co-located) ----------

    def test_exactly_max_size_accepted(self):
        """Exactly 10 MB is within the limit and accepted.

        **Validates: Requirements 7.2**
        """
        for shape in _SHAPES:
            files = [_as_descriptor(shape, "application/pdf", MAX_DOCUMENT_SIZE_BYTES)]
            assert validate_documents(files) is True

    def test_one_byte_over_max_size_rejected(self):
        """10 MB + 1 byte is over the limit and rejected.

        **Validates: Requirements 7.2**
        """
        for shape in _SHAPES:
            files = [_as_descriptor(shape, "image/png", MAX_DOCUMENT_SIZE_BYTES + 1)]
            assert validate_documents(files) is False

    def test_exactly_three_documents_accepted(self):
        """Exactly MAX_DOCUMENT_COUNT (3) valid documents are accepted.

        **Validates: Requirements 7.3**
        """
        files = [
            {"content_type": "application/pdf", "size": 1024},
            {"content_type": "image/jpeg", "size": 2048},
            {"content_type": "image/png", "size": 4096},
        ]
        assert len(files) == MAX_DOCUMENT_COUNT
        assert validate_documents(files) is True

    def test_four_documents_rejected(self):
        """4 documents exceed the count cap and are rejected.

        **Validates: Requirements 7.3**
        """
        files = [
            {"content_type": "application/pdf", "size": 1024},
            {"content_type": "image/jpeg", "size": 2048},
            {"content_type": "image/png", "size": 4096},
            {"content_type": "application/pdf", "size": 8192},
        ]
        assert len(files) == MAX_DOCUMENT_COUNT + 1
        assert validate_documents(files) is False
