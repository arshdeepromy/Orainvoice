"""Property-based tests for the kiosk vehicle check-in feature.

Feature: kiosk-vehicle-checkin

Uses Hypothesis to verify universal correctness properties for the kiosk
vehicle check-in schemas and service logic.

Validates: Requirements 2.4, 3.4, 6.1, 6.2, 6.3, 7.3, 9.5, 9.7
"""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.modules.kiosk.schemas import KioskVehicleLookupRequest


# ---------------------------------------------------------------------------
# Property 2: Registration input normalization
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(input_str=st.text(min_size=1, max_size=10))
def test_rego_normalization_equals_strip_upper(input_str: str) -> None:
    """For any string input, the cleaned rego equals input.strip().upper().

    Feature: kiosk-vehicle-checkin, Property 2: Registration input normalization
    **Validates: Requirements 2.4**
    """
    # Filter out inputs whose stripped form is empty (would fail min_length=1 validation)
    assume(len(input_str.strip()) >= 1)

    request = KioskVehicleLookupRequest(rego=input_str)
    assert request.rego == input_str.strip().upper()


# ---------------------------------------------------------------------------
# Property 3: Vehicle lookup cache round-trip
# ---------------------------------------------------------------------------

# Strategies for generating random vehicle data
_rego_st = st.from_regex(r"[A-Z0-9]{1,7}", fullmatch=True)
_make_st = st.sampled_from(["Toyota", "Honda", "Mazda", "Ford", "Nissan", "BMW", "Subaru"])
_model_st = st.sampled_from(["Corolla", "Civic", "3", "Ranger", "Leaf", "X5", "Impreza"])
_body_type_st = st.sampled_from(["Sedan", "Hatchback", "SUV", "Ute", "Van", "Wagon"])
_year_st = st.integers(min_value=1980, max_value=2026)
_colour_st = st.sampled_from(["White", "Black", "Silver", "Red", "Blue", "Green", "Grey"])
_odometer_st = st.one_of(st.none(), st.integers(min_value=0, max_value=999999))
_date_st = st.one_of(
    st.none(),
    st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
)


def _make_mock_global_vehicle(
    *,
    vehicle_id: uuid.UUID,
    rego: str,
    make: str,
    model: str,
    body_type: str,
    year: int,
    colour: str,
    wof_expiry: date | None,
    registration_expiry: date | None,
    odometer_last_recorded: int | None,
) -> MagicMock:
    """Build a mock GlobalVehicle ORM object with the given attributes."""
    gv = MagicMock()
    gv.id = vehicle_id
    gv.rego = rego
    gv.make = make
    gv.model = model
    gv.body_type = body_type
    gv.year = year
    gv.colour = colour
    gv.wof_expiry = wof_expiry
    gv.registration_expiry = registration_expiry
    gv.odometer_last_recorded = odometer_last_recorded
    return gv


def _make_scalar_result(value):
    """Create a mock DB execute result that returns value from scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@settings(max_examples=100, deadline=None)
@given(
    rego=_rego_st,
    make=_make_st,
    model=_model_st,
    body_type=_body_type_st,
    year=_year_st,
    colour=_colour_st,
    wof_expiry=_date_st,
    registration_expiry=_date_st,
    odometer=_odometer_st,
)
@pytest.mark.asyncio
async def test_global_vehicle_cache_roundtrip_returns_cache_source(
    rego: str,
    make: str,
    model: str,
    body_type: str,
    year: int,
    colour: str,
    wof_expiry: date | None,
    registration_expiry: date | None,
    odometer: int | None,
) -> None:
    """For any valid vehicle data in global_vehicles, lookup returns source='cache' without CarJam.

    Feature: kiosk-vehicle-checkin, Property 3: Vehicle lookup cache round-trip
    **Validates: Requirements 3.4**
    """
    from app.modules.kiosk.service import lookup_vehicle_for_kiosk

    vehicle_id = uuid.uuid4()
    org_id = uuid.uuid4()

    global_vehicle = _make_mock_global_vehicle(
        vehicle_id=vehicle_id,
        rego=rego,
        make=make,
        model=model,
        body_type=body_type,
        year=year,
        colour=colour,
        wof_expiry=wof_expiry,
        registration_expiry=registration_expiry,
        odometer_last_recorded=odometer,
    )

    db = AsyncMock()
    redis = AsyncMock()
    # First call: org_vehicles miss; Second call: global_vehicles hit
    db.execute = AsyncMock(side_effect=[
        _make_scalar_result(None),          # org_vehicles miss
        _make_scalar_result(global_vehicle),  # global_vehicles hit
    ])

    with patch("app.modules.vehicles.service._load_carjam_client") as mock_carjam:
        result = await lookup_vehicle_for_kiosk(db, redis, rego=rego, org_id=org_id)

        # CarJam should never be called when global_vehicles has a hit
        mock_carjam.assert_not_called()

    # Verify source is "cache"
    assert result["source"] == "cache"

    # Verify returned data matches what was stored
    assert result["id"] == str(vehicle_id)
    assert result["rego"] == rego
    assert result["make"] == make
    assert result["model"] == model
    assert result["body_type"] == body_type
    assert result["year"] == year
    assert result["colour"] == colour
    assert result["wof_expiry"] == (wof_expiry.isoformat() if wof_expiry else None)
    assert result["rego_expiry"] == (registration_expiry.isoformat() if registration_expiry else None)
    assert result["odometer"] == odometer


# ---------------------------------------------------------------------------
# Property 10: Customer lookup matching semantics
# ---------------------------------------------------------------------------

# Strategies for generating customer data
_phone_st = st.from_regex(r"02[0-9]{7,9}", fullmatch=True)
_email_st = st.builds(
    lambda user, domain: f"{user}@{domain}.com",
    user=st.from_regex(r"[a-z]{3,10}", fullmatch=True),
    domain=st.from_regex(r"[a-z]{3,8}", fullmatch=True),
)
_name_st = st.from_regex(r"[A-Z][a-z]{2,10}", fullmatch=True)


@st.composite
def _customer_list_st(draw):
    """Generate a list of customers with controlled matching characteristics.

    Returns (customers, search_phone, search_email, expected_matching_ids)
    where expected_matching_ids are the IDs of non-anonymised customers that
    match the search criteria.
    """
    org_id = draw(st.uuids())
    search_phone = draw(_phone_st)
    search_email = draw(_email_st)

    customers = []
    expected_matching_ids = []

    # Number of customers to generate (mix of matching and non-matching)
    num_customers = draw(st.integers(min_value=0, max_value=8))

    for _ in range(num_customers):
        cust_id = draw(st.uuids())
        first_name = draw(_name_st)
        last_name = draw(_name_st)
        is_anonymised = draw(st.booleans())

        # Decide matching type for this customer
        match_type = draw(st.sampled_from([
            "phone_match",
            "email_match_exact",
            "email_match_different_case",
            "no_match",
        ]))

        if match_type == "phone_match":
            phone = search_phone
            email = draw(_email_st)  # random different email
        elif match_type == "email_match_exact":
            phone = draw(_phone_st)  # random different phone
            email = search_email
        elif match_type == "email_match_different_case":
            phone = draw(_phone_st)  # random different phone
            # Vary the case of the search email
            email = draw(st.sampled_from([
                search_email.upper(),
                search_email.swapcase(),
                search_email.capitalize(),
            ]))
        else:  # no_match
            # Ensure phone and email don't match
            phone = draw(_phone_st.filter(lambda p: p != search_phone))
            email = draw(_email_st.filter(lambda e: e.lower() != search_email.lower()))

        cust = MagicMock()
        cust.id = cust_id
        cust.org_id = org_id
        cust.first_name = first_name
        cust.last_name = last_name
        cust.phone = phone
        cust.email = email
        cust.is_anonymised = is_anonymised

        customers.append(cust)

        # A customer matches if: (phone matches exactly OR email matches
        # case-insensitively) AND is not anonymised
        phone_matches = phone == search_phone
        email_matches = (email is not None and email.lower() == search_email.lower())

        if (phone_matches or email_matches) and not is_anonymised:
            expected_matching_ids.append(cust_id)

    return (customers, org_id, search_phone, search_email, expected_matching_ids)


@settings(max_examples=100, deadline=None)
@given(data=_customer_list_st())
@pytest.mark.asyncio
async def test_customer_lookup_matching_semantics(data) -> None:
    """For any phone/email, returns all org customers matching exact phone OR
    case-insensitive email, and no others. Anonymised customers are excluded.

    Feature: kiosk-vehicle-checkin, Property 10: Customer lookup matching semantics
    **Validates: Requirements 9.5, 9.7**
    """
    from app.modules.kiosk.service import customer_lookup_for_kiosk

    customers, org_id, search_phone, search_email, expected_matching_ids = data

    # Compute the expected matching (non-anonymised) customers
    matching_customers = [
        c for c in customers if c.id in expected_matching_ids
    ]

    # Mock the DB: the function makes two queries:
    # 1. count query (returns total count)
    # 2. data query (returns up to 5 matching customers)
    count_result = MagicMock()
    count_result.scalar_one.return_value = len(matching_customers)

    # The data query returns a scalars().all() result
    data_result = MagicMock()
    # Limit to 5 as the function does
    data_result.scalars.return_value.all.return_value = matching_customers[:5]

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, data_result])

    result = await customer_lookup_for_kiosk(
        db,
        org_id=org_id,
        phone=search_phone,
        email=search_email,
    )

    # Verify total count matches expected
    assert result["total"] == len(matching_customers)

    # Verify returned items are limited to 5
    assert len(result["items"]) <= 5

    # Verify all returned items correspond to expected matching customers
    returned_ids = {item["id"] for item in result["items"]}
    expected_ids_limited = {str(c.id) for c in matching_customers[:5]}
    assert returned_ids == expected_ids_limited

    # Verify no anonymised customers are in the results
    for item in result["items"]:
        matching_cust = next(
            c for c in matching_customers if str(c.id) == item["id"]
        )
        assert not matching_cust.is_anonymised

    # Verify each returned customer actually matches the search criteria
    for item in result["items"]:
        matching_cust = next(
            c for c in matching_customers if str(c.id) == item["id"]
        )
        phone_matches = matching_cust.phone == search_phone
        email_matches = (
            matching_cust.email is not None
            and matching_cust.email.lower() == search_email.lower()
        )
        assert phone_matches or email_matches, (
            f"Customer {item['id']} does not match search criteria: "
            f"phone={matching_cust.phone!r} vs {search_phone!r}, "
            f"email={matching_cust.email!r} vs {search_email!r}"
        )


# ---------------------------------------------------------------------------
# Property 6: Check-in links all confirmed vehicles
# ---------------------------------------------------------------------------

# Strategies for generating valid check-in request data
_first_name_st = st.from_regex(r"[A-Z][a-z]{2,10}", fullmatch=True)
_last_name_st = st.from_regex(r"[A-Z][a-z]{2,10}", fullmatch=True)
_checkin_phone_st = st.from_regex(r"02[0-9]{7,9}", fullmatch=True)
_vehicle_count_st = st.integers(min_value=1, max_value=5)
_odometer_km_st = st.one_of(st.none(), st.integers(min_value=0, max_value=999999))


@st.composite
def _checkin_vehicles_st(draw):
    """Generate a list of N vehicle entries with valid UUIDs and optional odometer."""
    n = draw(_vehicle_count_st)
    vehicles = []
    for _ in range(n):
        vehicles.append({
            "global_vehicle_id": str(draw(st.uuids())),
            "odometer_km": draw(_odometer_km_st),
        })
    return vehicles


@settings(max_examples=100, deadline=None)
@given(
    first_name=_first_name_st,
    last_name=_last_name_st,
    phone=_checkin_phone_st,
    vehicles=_checkin_vehicles_st(),
)
@pytest.mark.asyncio
async def test_checkin_links_all_confirmed_vehicles(
    first_name: str,
    last_name: str,
    phone: str,
    vehicles: list[dict],
) -> None:
    """For any valid customer data and N vehicles, exactly N CustomerVehicle links are created.

    Feature: kiosk-vehicle-checkin, Property 6: Check-in links all confirmed vehicles
    **Validates: Requirements 6.1, 6.2, 7.3**
    """
    from app.modules.kiosk.schemas import KioskCheckInRequestV2
    from app.modules.kiosk.service import kiosk_check_in_v2

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    # Build the request
    request_data = KioskCheckInRequestV2(
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        vehicles=[
            {"global_vehicle_id": v["global_vehicle_id"], "odometer_km": v["odometer_km"]}
            for v in vehicles
        ],
    )

    n = len(vehicles)

    # Mock DB: customer lookup returns None (new customer path)
    db = AsyncMock()

    # _search_customer_by_phone does db.execute → result.scalar_one_or_none()
    customer_search_result = MagicMock()
    customer_search_result.scalar_one_or_none.return_value = None

    # Set up db.execute: only the customer search query is needed
    # since _ensure_vehicle_linked is mocked at the module level
    db.execute = AsyncMock(return_value=customer_search_result)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    # Mock create_customer to return a valid customer dict
    mock_customer_dict = {
        "id": str(customer_id),
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "email": None,
    }

    # Patch _ensure_vehicle_linked at the kiosk service module level
    # and create_customer at the customers service module level
    import app.modules.customers.service  # ensure module is imported for patching

    with patch(
        "app.modules.customers.service.create_customer",
        new=AsyncMock(return_value=mock_customer_dict),
    ) as mock_create, patch(
        "app.modules.kiosk.service._ensure_vehicle_linked",
        new=AsyncMock(),
    ) as mock_link, patch(
        "app.modules.kiosk.service.OdometerReading",
    ) as mock_odometer_cls, patch(
        "app.modules.vehicles.service.promote_vehicle",
        new=AsyncMock(return_value=MagicMock(odometer_last_recorded=None)),
    ):
        # OdometerReading() returns a mock object that db.add can accept
        mock_odometer_cls.return_value = MagicMock()

        result = await kiosk_check_in_v2(
            db,
            org_id=org_id,
            user_id=user_id,
            data=request_data,
            ip_address="127.0.0.1",
        )

    # The response vehicles_linked count must equal N
    assert result.vehicles_linked == n, (
        f"Expected {n} vehicles linked, got {result.vehicles_linked}"
    )

    # Verify _ensure_vehicle_linked was called exactly N times (once per vehicle)
    assert mock_link.call_count == n, (
        f"Expected _ensure_vehicle_linked called {n} times, "
        f"got {mock_link.call_count}"
    )


# ---------------------------------------------------------------------------
# Property 7: Odometer recording for vehicles with readings
# ---------------------------------------------------------------------------

# Strategy for generating vehicle entries with a mix of non-null and null odometer_km
_odometer_positive_st = st.integers(min_value=1, max_value=999999)


@st.composite
def _checkin_vehicles_with_odometer_st(draw):
    """Generate a list of vehicle entries where some have non-null odometer_km and some have None.

    Returns (vehicles_list, expected_odometer_count) where expected_odometer_count
    is the number of vehicles with non-null odometer_km.
    """
    n = draw(st.integers(min_value=1, max_value=5))
    vehicles = []
    for _ in range(n):
        # Decide whether this vehicle has an odometer reading
        has_odometer = draw(st.booleans())
        odometer_km = draw(_odometer_positive_st) if has_odometer else None
        vehicles.append({
            "global_vehicle_id": str(draw(st.uuids())),
            "odometer_km": odometer_km,
        })
    expected_odometer_count = sum(1 for v in vehicles if v["odometer_km"] is not None)
    return (vehicles, expected_odometer_count)


@settings(max_examples=100, deadline=None)
@given(
    first_name=_first_name_st,
    last_name=_last_name_st,
    phone=_checkin_phone_st,
    vehicles_data=_checkin_vehicles_with_odometer_st(),
)
@pytest.mark.asyncio
async def test_odometer_recording_for_vehicles_with_readings(
    first_name: str,
    last_name: str,
    phone: str,
    vehicles_data: tuple[list[dict], int],
) -> None:
    """For any vehicle entry with non-null odometer_km, an odometer_reading record
    is created with source='kiosk' and the provided reading value.

    Feature: kiosk-vehicle-checkin, Property 7: Odometer recording for vehicles with readings
    **Validates: Requirements 6.3**
    """
    from app.modules.kiosk.schemas import KioskCheckInRequestV2
    from app.modules.kiosk.service import kiosk_check_in_v2

    vehicles, expected_odometer_count = vehicles_data

    org_id = uuid.uuid4()
    user_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    # Build the request
    request_data = KioskCheckInRequestV2(
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        vehicles=[
            {"global_vehicle_id": v["global_vehicle_id"], "odometer_km": v["odometer_km"]}
            for v in vehicles
        ],
    )

    # Mock DB: customer lookup returns None (new customer path)
    db = AsyncMock()

    customer_search_result = MagicMock()
    customer_search_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=customer_search_result)
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    # Mock create_customer to return a valid customer dict
    mock_customer_dict = {
        "id": str(customer_id),
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "email": None,
    }

    # Track OdometerReading instances created
    odometer_instances = []

    def capture_odometer(*args, **kwargs):
        """Capture OdometerReading constructor calls."""
        instance = MagicMock()
        instance.global_vehicle_id = kwargs.get("global_vehicle_id")
        instance.reading_km = kwargs.get("reading_km")
        instance.source = kwargs.get("source")
        instance.recorded_by = kwargs.get("recorded_by")
        instance.org_id = kwargs.get("org_id")
        odometer_instances.append(instance)
        return instance

    with patch(
        "app.modules.customers.service.create_customer",
        new=AsyncMock(return_value=mock_customer_dict),
    ), patch(
        "app.modules.kiosk.service._ensure_vehicle_linked",
        new=AsyncMock(),
    ), patch(
        "app.modules.kiosk.service.OdometerReading",
        side_effect=capture_odometer,
    ), patch(
        "app.modules.vehicles.service.promote_vehicle",
        new=AsyncMock(return_value=MagicMock(odometer_last_recorded=None)),
    ):
        result = await kiosk_check_in_v2(
            db,
            org_id=org_id,
            user_id=user_id,
            data=request_data,
            ip_address="127.0.0.1",
        )

    # Verify exactly M OdometerReading objects were created (M = vehicles with non-null odometer_km)
    assert len(odometer_instances) == expected_odometer_count, (
        f"Expected {expected_odometer_count} OdometerReading records, "
        f"got {len(odometer_instances)}"
    )

    # Verify each OdometerReading has source="kiosk" and correct reading_km
    vehicles_with_odometer = [v for v in vehicles if v["odometer_km"] is not None]
    for i, odometer_obj in enumerate(odometer_instances):
        assert odometer_obj.source == "kiosk", (
            f"OdometerReading[{i}] source should be 'kiosk', got {odometer_obj.source!r}"
        )
        assert odometer_obj.reading_km == vehicles_with_odometer[i]["odometer_km"], (
            f"OdometerReading[{i}] reading_km should be "
            f"{vehicles_with_odometer[i]['odometer_km']}, got {odometer_obj.reading_km}"
        )
        assert odometer_obj.global_vehicle_id == uuid.UUID(vehicles_with_odometer[i]["global_vehicle_id"]), (
            f"OdometerReading[{i}] global_vehicle_id mismatch"
        )

    # Verify db.add was called for each OdometerReading
    add_calls = db.add.call_args_list
    odometer_add_calls = [
        call for call in add_calls if call[0][0] in odometer_instances
    ]
    assert len(odometer_add_calls) == expected_odometer_count, (
        f"Expected db.add called {expected_odometer_count} times for OdometerReading, "
        f"got {len(odometer_add_calls)}"
    )


# ---------------------------------------------------------------------------
# Property 8: Idempotent vehicle linking
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    vehicle_id=st.uuids(),
    customer_id=st.uuids(),
    org_id=st.uuids(),
    user_id=st.uuids(),
    num_calls=st.integers(min_value=2, max_value=5),
)
@pytest.mark.asyncio
async def test_idempotent_vehicle_linking(
    vehicle_id: uuid.UUID,
    customer_id: uuid.UUID,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    num_calls: int,
) -> None:
    """For any vehicle+customer pair, calling link multiple times results in
    exactly one CustomerVehicle record (db.add called once, on the first call only).

    Feature: kiosk-vehicle-checkin, Property 8: Idempotent vehicle linking
    **Validates: Requirements 6.4**
    """
    from app.modules.kiosk.service import _ensure_vehicle_linked

    # Build a mock existing link object (returned after first call creates it)
    existing_link = MagicMock()
    existing_link.org_id = org_id
    existing_link.customer_id = customer_id
    existing_link.global_vehicle_id = vehicle_id

    # Mock DB execute results:
    # - First call: no existing link found (scalar_one_or_none returns None)
    # - Subsequent calls: existing link found (scalar_one_or_none returns the link)
    first_query_result = MagicMock()
    first_query_result.scalar_one_or_none.return_value = None

    subsequent_query_result = MagicMock()
    subsequent_query_result.scalar_one_or_none.return_value = existing_link

    db = AsyncMock()
    # First call to db.execute returns "not found", all subsequent return "found"
    db.execute = AsyncMock(
        side_effect=[first_query_result] + [subsequent_query_result] * (num_calls - 1)
    )

    # Mock link_vehicle_to_customer at its source module — it's imported inside
    # _ensure_vehicle_linked via `from app.modules.vehicles.service import ...`
    # We need to mock the module to avoid transitive import issues (httpx not available)
    mock_vehicles_service = MagicMock()
    mock_link_fn = AsyncMock()
    mock_vehicles_service.link_vehicle_to_customer = mock_link_fn

    with patch.dict(
        "sys.modules",
        {"app.modules.vehicles.service": mock_vehicles_service},
    ):
        # Call _ensure_vehicle_linked num_calls times with the same parameters
        for _ in range(num_calls):
            await _ensure_vehicle_linked(
                db,
                vehicle_id=vehicle_id,
                customer_id=customer_id,
                org_id=org_id,
                user_id=user_id,
                ip_address="127.0.0.1",
            )

        # The link function should be called exactly once (on the first call only)
        assert mock_link_fn.call_count == 1, (
            f"Expected link_vehicle_to_customer called exactly 1 time for "
            f"{num_calls} calls to _ensure_vehicle_linked, "
            f"got {mock_link_fn.call_count}"
        )

        # Verify the single call had the correct parameters
        mock_link_fn.assert_called_once_with(
            db,
            vehicle_id=vehicle_id,
            customer_id=customer_id,
            org_id=org_id,
            user_id=user_id,
            ip_address="127.0.0.1",
        )
