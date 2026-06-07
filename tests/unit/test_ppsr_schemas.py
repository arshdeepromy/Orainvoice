"""Unit tests for ``app/modules/ppsr/schemas.py``.

**Validates: Requirements R4, R5, R6, R8 — PPSR module Phase 1, task C2.**

Coverage matrix (per tasks.md C2 ``**Verify:**`` block):

  - Happy-path round-trips for every schema (request + response).
  - ``rego`` validation: rejects non-alphanumeric, lowercase
    normalised to upper, length bounds (1, 8, 9).
  - **Encrypted-payload safety (G31):** asserts that constructing a
    :class:`PpsrSearchSummary` from a ``PpsrSearch``-like dict that
    includes ``response_encrypted=b"secret"`` does NOT serialise the
    encrypted bytes back into ``model_dump()`` output. This is the
    primary defence against accidentally leaking PII through the
    history-list endpoint.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.ppsr.schemas import (
    PpsrLinkVehicleRequest,
    PpsrQuotaResponse,
    PpsrSearchListResponse,
    PpsrSearchOptions,
    PpsrSearchRequest,
    PpsrSearchResult,
    PpsrSearchSummary,
)


# ---------------------------------------------------------------------------
# PpsrSearchOptions — happy-path defaults + round-trip
# ---------------------------------------------------------------------------


class TestPpsrSearchOptions:
    def test_defaults_match_design(self):
        opts = PpsrSearchOptions()
        # Defaults — all PPSR data flags off so the caller explicitly opts
        # into a PPSR lookup; an owner-check-only search skips lookup_ppsr.
        assert opts.include_ownership_history is False
        assert opts.include_current_owner is False
        assert opts.include_warnings is False
        assert opts.include_fws is False
        assert opts.check_hidden_plates is False
        assert opts.s241_purpose is None

    def test_round_trip_via_model_dump(self):
        opts = PpsrSearchOptions(
            include_ownership_history=True,
            include_current_owner=True,
            include_warnings=False,
            include_fws=True,
            check_hidden_plates=True,
            s241_purpose="Selling vehicle",
        )
        again = PpsrSearchOptions(**opts.model_dump())
        assert again == opts


# ---------------------------------------------------------------------------
# PpsrSearchRequest — rego validation + flattened option fields
# ---------------------------------------------------------------------------


class TestPpsrSearchRequestRego:
    def test_lowercase_normalised_to_upper(self):
        req = PpsrSearchRequest(rego="abc123")
        assert req.rego == "ABC123"

    def test_whitespace_stripped(self):
        req = PpsrSearchRequest(rego="  abc123  ")
        assert req.rego == "ABC123"

    def test_min_length_one_accepted(self):
        req = PpsrSearchRequest(rego="A")
        assert req.rego == "A"

    def test_max_length_eight_accepted(self):
        req = PpsrSearchRequest(rego="ABCDE123")
        assert req.rego == "ABCDE123"

    def test_length_nine_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PpsrSearchRequest(rego="ABCDEF123")
        assert "rego" in str(exc.value)

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            PpsrSearchRequest(rego="")

    def test_whitespace_only_rejected(self):
        with pytest.raises(ValidationError):
            PpsrSearchRequest(rego="   ")

    @pytest.mark.parametrize(
        "bad",
        ["ABC-123", "ABC 123", "ABC.123", "ABC/123", "ABC*", "ABC$", "ABC#1"],
    )
    def test_non_alphanumeric_rejected(self, bad: str):
        with pytest.raises(ValidationError) as exc:
            PpsrSearchRequest(rego=bad)
        assert "rego" in str(exc.value)

    def test_unicode_letters_rejected(self):
        # Macron / accented chars should fail — CarJam can't look these up.
        with pytest.raises(ValidationError):
            PpsrSearchRequest(rego="ABCDÉ")

    def test_non_string_rejected(self):
        with pytest.raises(ValidationError):
            PpsrSearchRequest(rego=12345)  # type: ignore[arg-type]


class TestPpsrSearchRequestFlattenedOptions:
    def test_defaults_match_options_defaults(self):
        req = PpsrSearchRequest(rego="ABC123")
        assert req.include_ownership_history is False
        assert req.include_current_owner is False
        assert req.include_warnings is False
        assert req.include_fws is False
        assert req.check_hidden_plates is False
        assert req.s241_purpose is None
        assert req.force_refresh is False

    def test_force_refresh_round_trips(self):
        req = PpsrSearchRequest(rego="ABC123", force_refresh=True)
        assert req.force_refresh is True

    def test_to_options_projects_fields(self):
        req = PpsrSearchRequest(
            rego="abc123",
            include_ownership_history=True,
            include_current_owner=True,
            include_warnings=False,
            include_fws=True,
            check_hidden_plates=True,
            s241_purpose="Buying vehicle",
            force_refresh=True,
        )
        opts = req.to_options()
        assert opts.include_ownership_history is True
        assert opts.include_current_owner is True
        assert opts.include_warnings is False
        assert opts.include_fws is True
        assert opts.check_hidden_plates is True
        assert opts.s241_purpose == "Buying vehicle"
        # to_options() does NOT carry force_refresh — the service uses
        # that flag separately and it must NOT influence options_hash.
        assert "force_refresh" not in opts.model_dump()


class TestPpsrSearchRequestOwnerCheck:
    """Owner-check per-type required-field validation (mirrors CarJam's
    ``err-owner-check-validation`` rules)."""

    def test_no_owner_check_by_default(self):
        req = PpsrSearchRequest(rego="ABC123")
        assert req.owner_check_type is None

    def test_owner_check_type_normalised_to_lower(self):
        req = PpsrSearchRequest(
            rego="ABC123",
            owner_check_type="PERSON_DL",
            owner_driver_licence="DL123",
        )
        assert req.owner_check_type == "person_dl"

    def test_blank_owner_check_type_treated_as_none(self):
        req = PpsrSearchRequest(rego="ABC123", owner_check_type="  ")
        assert req.owner_check_type is None

    def test_unknown_owner_check_type_rejected(self):
        with pytest.raises(ValidationError):
            PpsrSearchRequest(rego="ABC123", owner_check_type="bogus")

    def test_company_requires_company_name(self):
        with pytest.raises(ValidationError) as exc:
            PpsrSearchRequest(rego="ABC123", owner_check_type="company")
        assert "owner_company_name" in str(exc.value)

    def test_company_with_name_valid(self):
        req = PpsrSearchRequest(
            rego="ABC123",
            owner_check_type="company",
            owner_company_name="Acme Ltd",
        )
        assert req.owner_check_type == "company"

    def test_person_dl_requires_licence(self):
        with pytest.raises(ValidationError) as exc:
            PpsrSearchRequest(rego="ABC123", owner_check_type="person_dl")
        assert "owner_driver_licence" in str(exc.value)

    def test_person_names_requires_last_name(self):
        with pytest.raises(ValidationError) as exc:
            PpsrSearchRequest(
                rego="ABC123",
                owner_check_type="person_names",
                owner_first_name="Jane",
            )
        assert "owner_last_name" in str(exc.value)

    def test_person_names_requires_first_or_dob(self):
        with pytest.raises(ValidationError) as exc:
            PpsrSearchRequest(
                rego="ABC123",
                owner_check_type="person_names",
                owner_last_name="Smith",
            )
        assert "owner_first_name or owner_dob" in str(exc.value)

    def test_person_names_with_dob_only_valid(self):
        req = PpsrSearchRequest(
            rego="ABC123",
            owner_check_type="person_names",
            owner_last_name="Smith",
            owner_dob="1990-01-01",
        )
        assert req.owner_dob == "1990-01-01"

    def test_to_options_carries_owner_check_fields(self):
        req = PpsrSearchRequest(
            rego="ABC123",
            owner_check_type="person_names",
            owner_last_name="Smith",
            owner_first_name="Jane",
        )
        opts = req.to_options()
        assert opts.owner_check_type == "person_names"
        assert opts.owner_last_name == "Smith"
        assert opts.owner_first_name == "Jane"

    def test_owner_check_changes_options_hash(self):
        """An owner-check search must not cache-hit a plain search."""
        from app.modules.ppsr.service import _hash_options_payload

        plain = PpsrSearchRequest(rego="ABC123").to_options()
        owner = PpsrSearchRequest(
            rego="ABC123",
            owner_check_type="company",
            owner_company_name="Acme Ltd",
        ).to_options()
        assert _hash_options_payload(plain.model_dump()) != _hash_options_payload(
            owner.model_dump()
        )


class TestPpsrLinkVehicleRequest:
    def test_happy_path(self):
        ov = uuid4()
        req = PpsrLinkVehicleRequest(org_vehicle_id=ov)
        assert req.org_vehicle_id == ov

    def test_org_vehicle_id_required(self):
        with pytest.raises(ValidationError):
            PpsrLinkVehicleRequest()  # type: ignore[call-arg]

    def test_invalid_uuid_rejected(self):
        with pytest.raises(ValidationError):
            PpsrLinkVehicleRequest(org_vehicle_id="not-a-uuid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PpsrSearchResult — happy-path + cached round-trip
# ---------------------------------------------------------------------------


class TestPpsrSearchResult:
    def test_minimal_fresh_result(self):
        sid = uuid4()
        res = PpsrSearchResult(
            search_id=sid,
            rego="ABC123",
            cached=False,
            statement_count=0,
        )
        assert res.search_id == sid
        assert res.cached is False
        assert res.cached_at is None
        assert res.source_search_id is None
        assert res.ppsr_details == []
        assert res.warnings == []
        assert res.ownership_history is None
        assert res.current_owner is None
        assert res.basic is None
        assert res.not_found is False

    def test_full_cached_result_round_trips(self):
        sid = uuid4()
        source = uuid4()
        cached_at = datetime(2026, 6, 1, 12, 30, tzinfo=timezone.utc)
        res = PpsrSearchResult(
            search_id=sid,
            rego="ABC123",
            cached=True,
            cached_at=cached_at,
            source_search_id=source,
            match="N",
            match_description="No match — clear",
            statement_count=0,
            ppsr_details=[],
            ownership_history=[{"owner": "John Smith", "from": "2020-01-01"}],
            current_owner={"name": "John Smith"},
            warnings=[],
            basic={"make": "Toyota", "model": "Corolla"},
            not_found=False,
            charges_cents=200,
            carjam_request_id="cj-12345",
        )
        again = PpsrSearchResult(**res.model_dump())
        assert again == res
        assert again.cached is True
        assert again.source_search_id == source

    def test_from_attributes_supports_orm_objects(self):
        """``from_attributes=True`` lets the service build the response
        from an ORM-style object (mirrors the ``PpsrSearch`` model).
        """

        class FakeOrm:
            search_id = uuid4()
            rego = "XYZ789"
            cached = False
            cached_at = None
            source_search_id = None
            match = "Y"
            match_description = "Money owing"
            statement_count = 3
            ppsr_details: list[dict] = []
            ownership_history = None
            current_owner = None
            warnings: list[dict] = []
            basic = None
            not_found = False
            charges_cents = 500
            carjam_request_id = "cj-99"

        res = PpsrSearchResult.model_validate(FakeOrm(), from_attributes=True)
        assert res.rego == "XYZ789"
        assert res.match == "Y"
        assert res.statement_count == 3


# ---------------------------------------------------------------------------
# PpsrSearchSummary — encrypted-payload safety (G31)
# ---------------------------------------------------------------------------


class TestPpsrSearchSummaryEncryptedPayloadSafety:
    """The history list MUST never leak ``response_encrypted`` or any
    decrypted PII. Construct a summary from an ORM-style dict that
    includes the encrypted bytes and assert the bytes are absent from
    ``model_dump()`` output.
    """

    @staticmethod
    def _orm_like_dict(*, response_encrypted: bytes | None) -> dict:
        return {
            "id": uuid4(),
            "org_id": uuid4(),
            "user_id": uuid4(),
            "rego": "ABC123",
            "options_json": {"include_warnings": True},
            "options_hash": "deadbeef" * 8,
            "match": "N",
            "match_description": "No match — clear",
            "statement_count": 0,
            "has_warnings": False,
            "has_ownership_data": False,
            "response_encrypted": response_encrypted,
            "charges_cents": 200,
            "not_found": False,
            "error_message": None,
            "carjam_request_id": "cj-1",
            "forgotten_at": None,
            "org_vehicle_id": None,
            "global_vehicle_id": None,
            "created_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }

    def test_response_encrypted_not_in_model_dump(self):
        orm = self._orm_like_dict(response_encrypted=b"super-secret-blob")
        summary = PpsrSearchSummary.model_validate(orm)
        dumped = summary.model_dump()
        assert "response_encrypted" not in dumped
        # Defence-in-depth — also check the bytes are not nested
        # anywhere in the serialised payload (e.g. via a typo'd alias).
        assert b"super-secret-blob" not in repr(dumped).encode()
        assert "super-secret-blob" not in repr(dumped)

    def test_no_decrypted_owner_or_debtor_fields_present(self):
        orm = self._orm_like_dict(response_encrypted=b"x")
        # Even if the caller tries to splat decrypted fields in via
        # **kwargs, Pydantic v2 silently drops unknown fields by
        # default (extra='ignore'). Confirm that behaviour so the
        # service can't accidentally widen the payload.
        orm["current_owner"] = {"name": "Jane Doe", "address": "1 Main St"}
        orm["ownership_history"] = [{"owner": "Past Owner"}]
        orm["debtors"] = [{"name": "Debtor Co"}]
        summary = PpsrSearchSummary.model_validate(orm)
        dumped = summary.model_dump()
        assert "current_owner" not in dumped
        assert "ownership_history" not in dumped
        assert "debtors" not in dumped
        assert "Jane Doe" not in repr(dumped)

    def test_round_trip_preserves_summary_fields(self):
        orm = self._orm_like_dict(response_encrypted=b"x")
        summary = PpsrSearchSummary.model_validate(orm)
        again = PpsrSearchSummary(**summary.model_dump())
        assert again == summary

    def test_forgotten_search_summary_round_trips(self):
        orm = self._orm_like_dict(response_encrypted=None)
        orm["forgotten_at"] = datetime(2026, 6, 2, tzinfo=timezone.utc)
        summary = PpsrSearchSummary.model_validate(orm)
        assert summary.forgotten_at is not None


# ---------------------------------------------------------------------------
# PpsrSearchListResponse — `{ items, total }` envelope
# ---------------------------------------------------------------------------


class TestPpsrSearchListResponse:
    def test_envelope_shape(self):
        orm = TestPpsrSearchSummaryEncryptedPayloadSafety._orm_like_dict(
            response_encrypted=b"keep-me-secret",
        )
        summary = PpsrSearchSummary.model_validate(orm)
        envelope = PpsrSearchListResponse(items=[summary], total=1)
        assert envelope.total == 1
        assert len(envelope.items) == 1

        # The envelope dump must also be free of the encrypted blob.
        dumped = envelope.model_dump()
        assert "items" in dumped
        assert "total" in dumped
        assert "response_encrypted" not in repr(dumped)
        assert "keep-me-secret" not in repr(dumped)

    def test_empty_envelope(self):
        envelope = PpsrSearchListResponse(items=[], total=0)
        assert envelope.items == []
        assert envelope.total == 0


# ---------------------------------------------------------------------------
# PpsrQuotaResponse — G44 renamed field names
# ---------------------------------------------------------------------------


class TestPpsrQuotaResponse:
    def test_defaults(self):
        q = PpsrQuotaResponse()
        assert q.used == 0
        assert q.included == 0
        assert q.hidden_plate_used == 0
        assert q.hidden_plate_included == 0
        assert q.resets_at is None

    def test_field_names_match_g44(self):
        # G44 — the renamed columns are hidden_plate_*, NOT money_owing_*.
        q = PpsrQuotaResponse(
            used=7,
            included=50,
            hidden_plate_used=1,
            hidden_plate_included=10,
            resets_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        )
        dumped = q.model_dump()
        assert "hidden_plate_used" in dumped
        assert "hidden_plate_included" in dumped
        # Defence — the old name must NOT be present.
        assert "money_owing_used" not in dumped
        assert "money_owing_included" not in dumped

    def test_round_trip(self):
        q = PpsrQuotaResponse(used=3, included=100, hidden_plate_used=0)
        again = PpsrQuotaResponse(**q.model_dump())
        assert again == q
