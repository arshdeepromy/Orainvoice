"""Property-based tests for booking modal enhancements.

Feature: booking-modal-enhancements

Uses Hypothesis to verify correctness properties for the enhanced
BookingCreate and BookingResponse schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.bookings.schemas import BookingCreate, BookingResponse


# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

service_catalogue_ids = st.one_of(st.none(), st.builds(uuid.uuid4))

# Prices as Decimal with 2 decimal places, reasonable range
service_prices = st.one_of(
    st.none(),
    st.decimals(
        min_value=Decimal("0.01"),
        max_value=Decimal("99999.99"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    ),
)

reminder_offsets = st.one_of(
    st.none(),
    st.floats(min_value=0.5, max_value=720.0, allow_nan=False, allow_infinity=False),
)


@st.composite
def booking_create_payload(draw):
    """Generate a valid BookingCreate payload with randomised new fields."""
    send_email = draw(st.booleans())
    send_sms = draw(st.booleans())
    catalogue_id = draw(service_catalogue_ids)
    price = draw(service_prices)
    offset = draw(reminder_offsets)

    return {
        "customer_id": uuid.uuid4(),
        "scheduled_at": datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
        "duration_minutes": 60,
        "service_catalogue_id": catalogue_id,
        "service_price": price,
        "send_email_confirmation": send_email,
        "send_sms_confirmation": send_sms,
        "reminder_offset_hours": offset,
    }


# ---------------------------------------------------------------------------
# Property 14: BookingCreate/BookingResponse schema round-trip
# ---------------------------------------------------------------------------


class TestBookingSchemaRoundTrip:
    """Property 14: BookingCreate/BookingResponse schema round-trip.

    Feature: booking-modal-enhancements, Property 14: BookingCreate/BookingResponse schema round-trip

    **Validates: Requirements 6.8, 6.9**

    For any valid combination of the new booking fields
    (service_catalogue_id, service_price, send_email_confirmation,
    send_sms_confirmation, reminder_offset_hours), serializing a
    BookingCreate and then reading the resulting BookingResponse shall
    preserve all field values.
    """

    @given(payload=booking_create_payload())
    @PBT_SETTINGS
    def test_new_fields_survive_round_trip(self, payload):
        """All new booking fields survive a Create → Response round-trip.

        **Validates: Requirements 6.8, 6.9**
        """
        # 1. Build BookingCreate from the generated payload
        create_schema = BookingCreate(**payload)

        # 2. Simulate what _booking_to_dict + BookingResponse would produce:
        #    take the create fields and wrap them in a full response dict.
        response_dict = {
            "id": uuid.uuid4(),
            "org_id": uuid.uuid4(),
            "customer_id": create_schema.customer_id,
            "vehicle_rego": None,
            "branch_id": None,
            "service_type": None,
            "service_catalogue_id": create_schema.service_catalogue_id,
            "service_price": create_schema.service_price,
            "scheduled_at": create_schema.scheduled_at,
            "duration_minutes": create_schema.duration_minutes,
            "notes": None,
            "status": "scheduled",
            "reminder_sent": False,
            "send_email_confirmation": create_schema.send_email_confirmation,
            "send_sms_confirmation": create_schema.send_sms_confirmation,
            "reminder_offset_hours": create_schema.reminder_offset_hours,
            "reminder_scheduled_at": None,
            "reminder_cancelled": False,
            "assigned_to": None,
            "created_by": uuid.uuid4(),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

        response_schema = BookingResponse(**response_dict)

        # 3. Assert every new field is preserved through the round-trip
        assert response_schema.service_catalogue_id == create_schema.service_catalogue_id
        assert response_schema.send_email_confirmation == create_schema.send_email_confirmation
        assert response_schema.send_sms_confirmation == create_schema.send_sms_confirmation
        assert response_schema.reminder_offset_hours == create_schema.reminder_offset_hours

        # service_price needs Decimal comparison (avoid float drift)
        if create_schema.service_price is None:
            assert response_schema.service_price is None
        else:
            assert response_schema.service_price == create_schema.service_price


# ---------------------------------------------------------------------------
# Property 6: Vehicle rego storage is conditional on module enablement
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock, patch


# Strategy: non-empty vehicle rego strings (alphanumeric, 1-20 chars)
vehicle_regos = st.text(
    alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    min_size=1,
    max_size=20,
)


class TestVehicleRegoModuleGating:
    """Property 6: Vehicle rego storage is conditional on module enablement.

    Feature: booking-modal-enhancements, Property 6: Vehicle rego storage is conditional on module enablement

    **Validates: Requirements 2.5, 2.6**

    For any booking creation request containing a non-null vehicle_rego value,
    if the vehicles module is enabled for the organisation, the stored booking
    shall have vehicle_rego equal to the submitted value; if the vehicles module
    is disabled, the stored booking shall have vehicle_rego set to null.
    """

    @given(
        vehicle_rego=vehicle_regos,
        module_enabled=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_vehicle_rego_gated_by_module(self, vehicle_rego, module_enabled):
        """Stored vehicle_rego depends on vehicles module enablement.

        **Validates: Requirements 2.5, 2.6**
        """
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # -- Mock customer returned by the DB lookup --
        mock_customer = MagicMock()
        mock_customer.first_name = "Test"
        mock_customer.last_name = "Customer"

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = mock_customer

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()

        # Capture kwargs passed to the Booking constructor
        captured_booking_kwargs: dict = {}
        added_objects: list = []
        mock_db.add = lambda obj: added_objects.append(obj)

        # -- Mock Booking ORM class to avoid mapper initialisation --
        mock_booking_instance = MagicMock()

        def fake_booking_init(**kwargs):
            captured_booking_kwargs.update(kwargs)
            # Set attributes on the mock so _booking_to_dict can read them
            for k, v in kwargs.items():
                setattr(mock_booking_instance, k, v)
            mock_booking_instance.id = uuid.uuid4()
            mock_booking_instance.reminder_sent = False
            mock_booking_instance.send_email_confirmation = False
            mock_booking_instance.send_sms_confirmation = False
            mock_booking_instance.reminder_offset_hours = None
            mock_booking_instance.reminder_scheduled_at = None
            mock_booking_instance.reminder_cancelled = False
            mock_booking_instance.service_catalogue_id = None
            mock_booking_instance.service_price = None
            mock_booking_instance.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            mock_booking_instance.updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            return mock_booking_instance

        # -- Mock ModuleService.is_enabled --
        with patch("app.core.modules.ModuleService") as MockModuleServiceCls, \
             patch("app.modules.bookings.service.Booking", side_effect=fake_booking_init), \
             patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._check_staff_availability", new_callable=AsyncMock):
            mock_module_svc = AsyncMock()
            mock_module_svc.is_enabled = AsyncMock(return_value=module_enabled)
            MockModuleServiceCls.return_value = mock_module_svc

            result = await create_booking(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                vehicle_rego=vehicle_rego,
                scheduled_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
                duration_minutes=60,
            )

        # -- Assertions --
        # Check the kwargs passed to the Booking constructor
        if module_enabled:
            assert captured_booking_kwargs["vehicle_rego"] == vehicle_rego
            assert result["vehicle_rego"] == vehicle_rego
        else:
            assert captured_booking_kwargs["vehicle_rego"] is None
            assert result["vehicle_rego"] is None


# ---------------------------------------------------------------------------
# Property 8: Service selection stores catalogue ID, name, and price
# ---------------------------------------------------------------------------

# Strategy: service names (non-empty printable strings, 1-50 chars)
service_names = st.text(
    alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz "),
    min_size=1,
    max_size=50,
).map(str.strip).filter(lambda s: len(s) > 0)

# Strategy: service default prices (positive Decimal with 2 places)
service_default_prices = st.decimals(
    min_value=Decimal("0.01"),
    max_value=Decimal("99999.99"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


class TestServiceCatalogueLinkage:
    """Property 8: Service selection stores catalogue ID, name, and price.

    Feature: booking-modal-enhancements, Property 8: Service selection stores catalogue ID, name, and price

    **Validates: Requirements 3.2, 3.8, 3.9**

    For any service selected from the Service_Selector dropdown, the booking
    form state shall contain the selected service's service_catalogue_id,
    service_type (equal to the service name), and service_price (equal to the
    service's default_price).
    """

    @given(
        catalogue_name=service_names,
        catalogue_price=service_default_prices,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_service_selection_stores_catalogue_fields(
        self, catalogue_name, catalogue_price
    ):
        """Booking stores catalogue ID, name, and price from selected service.

        **Validates: Requirements 3.2, 3.8, 3.9**
        """
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()
        catalogue_id = uuid.uuid4()

        # -- Mock ServiceCatalogue entry --
        mock_catalogue = MagicMock()
        mock_catalogue.id = catalogue_id
        mock_catalogue.org_id = org_id
        mock_catalogue.name = catalogue_name
        mock_catalogue.default_price = catalogue_price
        mock_catalogue.is_active = True

        # -- Mock Customer --
        mock_customer = MagicMock()
        mock_customer.first_name = "Test"
        mock_customer.last_name = "Customer"

        # db.execute is called twice:
        #   1) ServiceCatalogue lookup (by service_catalogue_id)
        #   2) Customer lookup (by customer_id + org_id)
        catalogue_result = MagicMock()
        catalogue_result.scalar_one_or_none.return_value = mock_catalogue

        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = mock_customer

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=[catalogue_result, customer_result])
        mock_db.flush = AsyncMock()

        # Capture kwargs passed to the Booking constructor
        captured_booking_kwargs: dict = {}
        mock_booking_instance = MagicMock()

        def fake_booking_init(**kwargs):
            captured_booking_kwargs.update(kwargs)
            for k, v in kwargs.items():
                setattr(mock_booking_instance, k, v)
            mock_booking_instance.id = uuid.uuid4()
            mock_booking_instance.reminder_sent = False
            mock_booking_instance.send_email_confirmation = False
            mock_booking_instance.send_sms_confirmation = False
            mock_booking_instance.reminder_offset_hours = None
            mock_booking_instance.reminder_scheduled_at = None
            mock_booking_instance.reminder_cancelled = False
            mock_booking_instance.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            mock_booking_instance.updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            return mock_booking_instance

        mock_db.add = lambda obj: None

        with patch("app.modules.bookings.service.Booking", side_effect=fake_booking_init), \
             patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._check_staff_availability", new_callable=AsyncMock):

            result = await create_booking(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                service_catalogue_id=catalogue_id,
                scheduled_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
                duration_minutes=60,
            )

        # -- Assertions --
        # The Booking constructor should receive the catalogue fields
        assert captured_booking_kwargs["service_catalogue_id"] == catalogue_id
        assert captured_booking_kwargs["service_type"] == catalogue_name
        assert captured_booking_kwargs["service_price"] == catalogue_price

        # The returned dict should also contain the catalogue fields
        assert result["service_catalogue_id"] == catalogue_id
        assert result["service_type"] == catalogue_name
        assert result["service_price"] == catalogue_price


# ---------------------------------------------------------------------------
# Property 9: Notification channels match confirmation flags
# ---------------------------------------------------------------------------


class TestNotificationChannelDispatch:
    """Property 9: Notification channels match confirmation flags.

    Feature: booking-modal-enhancements, Property 9: Notification channels match confirmation flags

    **Validates: Requirements 4.4, 4.5, 4.6**

    For any booking creation request, the set of notification channels
    triggered (email, SMS, or none) shall exactly match the set of
    confirmation flags (send_email_confirmation, send_sms_confirmation)
    that are set to true. When both flags are false, no notifications
    shall be sent.
    """

    @given(
        send_email=st.booleans(),
        send_sms=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_notification_channels_match_flags(self, send_email, send_sms):
        """Dispatched notification channels exactly match confirmation flags.

        **Validates: Requirements 4.4, 4.5, 4.6**

        Email confirmation uses inline SMTP via _send_booking_confirmation_email
        (same pattern as invoice/quote emails). SMS uses Celery tasks.
        """
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # -- Mock customer with email and phone so dispatch can proceed --
        mock_customer = MagicMock()
        mock_customer.first_name = "Test"
        mock_customer.last_name = "Customer"
        mock_customer.email = "test@example.com"
        mock_customer.phone = "+6421000000"

        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = mock_customer

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=customer_result)
        mock_db.flush = AsyncMock()

        # Capture Booking constructor kwargs
        captured_booking_kwargs: dict = {}
        mock_booking_instance = MagicMock()

        def fake_booking_init(**kwargs):
            captured_booking_kwargs.update(kwargs)
            for k, v in kwargs.items():
                setattr(mock_booking_instance, k, v)
            mock_booking_instance.id = uuid.uuid4()
            mock_booking_instance.reminder_sent = False
            mock_booking_instance.send_email_confirmation = kwargs.get(
                "send_email_confirmation", False
            )
            mock_booking_instance.send_sms_confirmation = kwargs.get(
                "send_sms_confirmation", False
            )
            mock_booking_instance.reminder_offset_hours = None
            mock_booking_instance.reminder_scheduled_at = None
            mock_booking_instance.reminder_cancelled = False
            mock_booking_instance.service_catalogue_id = None
            mock_booking_instance.service_price = None
            mock_booking_instance.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            mock_booking_instance.updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            return mock_booking_instance

        mock_db.add = lambda obj: None

        # -- Patch email (inline SMTP) and SMS (Celery) notification paths --
        mock_send_confirmation_email = AsyncMock(return_value=True)

        mock_log_sms = AsyncMock(return_value={"id": str(uuid.uuid4())})
        mock_send_sms_task = MagicMock()
        mock_send_sms_task.delay = MagicMock()

        with patch("app.modules.bookings.service.Booking", side_effect=fake_booking_init), \
             patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._check_staff_availability", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._send_booking_confirmation_email", mock_send_confirmation_email), \
             patch("app.modules.notifications.service.log_sms_sent", mock_log_sms), \
             patch("app.tasks.notifications.send_sms_task", mock_send_sms_task):

            await create_booking(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                scheduled_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
                duration_minutes=60,
                send_email_confirmation=send_email,
                send_sms_confirmation=send_sms,
            )

        # -- Assertions: channels triggered must exactly match flags --
        # Email: inline SMTP via _send_booking_confirmation_email
        if send_email:
            mock_send_confirmation_email.assert_called_once()
        else:
            mock_send_confirmation_email.assert_not_called()

        # SMS: Celery task via send_sms_task.delay
        if send_sms:
            mock_log_sms.assert_called_once()
            mock_send_sms_task.delay.assert_called_once()
        else:
            mock_log_sms.assert_not_called()
            mock_send_sms_task.delay.assert_not_called()

        # When both flags are false, no notifications at all
        if not send_email and not send_sms:
            mock_send_confirmation_email.assert_not_called()
            mock_log_sms.assert_not_called()
            mock_send_sms_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Property 10: Reminder scheduled_at equals booking time minus offset
# ---------------------------------------------------------------------------


# Strategy: scheduled_at datetimes far in the future (2027) so reminder is always in the future
future_scheduled_at = st.datetimes(
    min_value=datetime(2027, 1, 1),
    max_value=datetime(2027, 12, 31),
    timezones=st.just(timezone.utc),
)

# Strategy: reminder offset hours between 0.5 and 168 (1 week)
reminder_offset_hours_st = st.floats(
    min_value=0.5,
    max_value=168.0,
    allow_nan=False,
    allow_infinity=False,
)


class TestReminderScheduling:
    """Property 10: Reminder scheduled_at equals booking time minus offset.

    Feature: booking-modal-enhancements, Property 10: Reminder scheduled_at equals booking time minus offset

    **Validates: Requirements 5.5**

    For any booking created with a non-null reminder_offset_hours where
    scheduled_at - reminder_offset_hours is in the future, the stored
    reminder_scheduled_at shall equal scheduled_at - timedelta(hours=reminder_offset_hours).
    """

    @given(
        scheduled_at=future_scheduled_at,
        offset_hours=reminder_offset_hours_st,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_reminder_scheduled_at_equals_booking_minus_offset(
        self, scheduled_at, offset_hours
    ):
        """Stored reminder_scheduled_at = scheduled_at - timedelta(hours=offset).

        **Validates: Requirements 5.5**
        """
        from datetime import timedelta
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        expected_reminder_at = scheduled_at - timedelta(hours=offset_hours)

        # -- Mock customer --
        mock_customer = MagicMock()
        mock_customer.first_name = "Test"
        mock_customer.last_name = "Customer"

        mock_scalar_result = MagicMock()
        mock_scalar_result.scalar_one_or_none.return_value = mock_customer

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_scalar_result)
        mock_db.flush = AsyncMock()

        # Capture kwargs passed to the Booking constructor
        captured_booking_kwargs: dict = {}
        mock_booking_instance = MagicMock()

        def fake_booking_init(**kwargs):
            captured_booking_kwargs.update(kwargs)
            for k, v in kwargs.items():
                setattr(mock_booking_instance, k, v)
            mock_booking_instance.id = uuid.uuid4()
            mock_booking_instance.reminder_sent = False
            mock_booking_instance.send_email_confirmation = False
            mock_booking_instance.send_sms_confirmation = False
            mock_booking_instance.reminder_offset_hours = kwargs.get("reminder_offset_hours")
            mock_booking_instance.reminder_scheduled_at = kwargs.get("reminder_scheduled_at")
            mock_booking_instance.reminder_cancelled = False
            mock_booking_instance.service_catalogue_id = None
            mock_booking_instance.service_price = None
            mock_booking_instance.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            mock_booking_instance.updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            return mock_booking_instance

        mock_db.add = lambda obj: None

        with patch("app.modules.bookings.service.Booking", side_effect=fake_booking_init), \
             patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._check_staff_availability", new_callable=AsyncMock):

            result = await create_booking(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                scheduled_at=scheduled_at,
                duration_minutes=60,
                reminder_offset_hours=offset_hours,
            )

        # -- Assertions --
        # The Booking constructor should receive the correct reminder_scheduled_at
        assert captured_booking_kwargs["reminder_offset_hours"] == offset_hours
        assert captured_booking_kwargs["reminder_scheduled_at"] == expected_reminder_at

        # The returned dict should also contain the correct values
        assert result["reminder_offset_hours"] == offset_hours
        assert result["reminder_scheduled_at"] == expected_reminder_at


# ---------------------------------------------------------------------------
# Property 13: Reminder uses same channels as confirmation
# ---------------------------------------------------------------------------


class TestReminderChannelMatching:
    """Property 13: Reminder uses same channels as confirmation.

    Feature: booking-modal-enhancements, Property 13: Reminder uses same channels as confirmation

    **Validates: Requirements 5.9**

    For any booking with a scheduled reminder, the reminder notification
    channels shall be identical to the confirmation notification channels
    stored on the booking (send_email_confirmation, send_sms_confirmation).
    """

    @given(
        send_email=st.booleans(),
        send_sms=st.booleans(),
        offset_hours=st.floats(
            min_value=0.5, max_value=168.0, allow_nan=False, allow_infinity=False
        ),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_reminder_channels_match_confirmation_channels(
        self, send_email, send_sms, offset_hours
    ):
        """Stored reminder channels are identical to confirmation channels.

        **Validates: Requirements 5.9**
        """
        from app.modules.bookings.service import create_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # Use a far-future date so reminder_scheduled_at is never in the past
        scheduled_at = datetime(2027, 6, 15, 10, 0, tzinfo=timezone.utc)

        # -- Mock customer --
        mock_customer = MagicMock()
        mock_customer.first_name = "Test"
        mock_customer.last_name = "Customer"
        mock_customer.email = "test@example.com"
        mock_customer.phone = "+6421000000"

        customer_result = MagicMock()
        customer_result.scalar_one_or_none.return_value = mock_customer

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=customer_result)
        mock_db.flush = AsyncMock()

        # Capture kwargs passed to the Booking constructor
        captured_booking_kwargs: dict = {}
        mock_booking_instance = MagicMock()

        def fake_booking_init(**kwargs):
            captured_booking_kwargs.update(kwargs)
            for k, v in kwargs.items():
                setattr(mock_booking_instance, k, v)
            mock_booking_instance.id = uuid.uuid4()
            mock_booking_instance.reminder_sent = False
            mock_booking_instance.send_email_confirmation = kwargs.get(
                "send_email_confirmation", False
            )
            mock_booking_instance.send_sms_confirmation = kwargs.get(
                "send_sms_confirmation", False
            )
            mock_booking_instance.reminder_offset_hours = kwargs.get("reminder_offset_hours")
            mock_booking_instance.reminder_scheduled_at = kwargs.get("reminder_scheduled_at")
            mock_booking_instance.reminder_cancelled = False
            mock_booking_instance.service_catalogue_id = None
            mock_booking_instance.service_price = None
            mock_booking_instance.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            mock_booking_instance.updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
            return mock_booking_instance

        mock_db.add = lambda obj: None

        # -- Patch email (inline SMTP) and SMS (Celery) notification paths --
        mock_send_confirmation_email = AsyncMock(return_value=True)

        mock_log_sms = AsyncMock(return_value={"id": str(uuid.uuid4())})
        mock_send_sms_task = MagicMock()
        mock_send_sms_task.delay = MagicMock()

        with patch("app.modules.bookings.service.Booking", side_effect=fake_booking_init), \
             patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._check_staff_availability", new_callable=AsyncMock), \
             patch("app.modules.bookings.service._send_booking_confirmation_email", mock_send_confirmation_email), \
             patch("app.modules.notifications.service.log_sms_sent", mock_log_sms), \
             patch("app.tasks.notifications.send_sms_task", mock_send_sms_task):

            result = await create_booking(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                customer_id=customer_id,
                scheduled_at=scheduled_at,
                duration_minutes=60,
                send_email_confirmation=send_email,
                send_sms_confirmation=send_sms,
                reminder_offset_hours=offset_hours,
            )

        # -- Assertions --
        # A reminder was scheduled (far-future date ensures it's not in the past)
        assert captured_booking_kwargs["reminder_scheduled_at"] is not None
        assert captured_booking_kwargs["reminder_offset_hours"] == offset_hours

        # The reminder channels (stored on the booking) must be identical
        # to the confirmation channels — they are the same fields.
        assert captured_booking_kwargs["send_email_confirmation"] == send_email
        assert captured_booking_kwargs["send_sms_confirmation"] == send_sms

        # The returned dict must also reflect the same channel flags
        assert result["send_email_confirmation"] == send_email
        assert result["send_sms_confirmation"] == send_sms

        # Verify reminder is scheduled alongside the channel flags
        assert result["reminder_offset_hours"] == offset_hours
        assert result["reminder_scheduled_at"] is not None


# ---------------------------------------------------------------------------
# Property 11: Booking cancellation cancels pending reminder
# ---------------------------------------------------------------------------

# Strategy: reminder_scheduled_at datetimes (always non-null, far future)
reminder_scheduled_at_st = st.datetimes(
    min_value=datetime(2027, 1, 1),
    max_value=datetime(2027, 12, 31),
    timezones=st.just(timezone.utc),
)

# Strategy: cancellable booking statuses (not completed/cancelled/no_show)
cancellable_statuses = st.sampled_from(["scheduled", "confirmed"])


class TestCancellationReminderHandling:
    """Property 11: Booking cancellation cancels pending reminder.

    Feature: booking-modal-enhancements, Property 11: Booking cancellation cancels pending reminder

    **Validates: Requirements 5.6**

    For any booking that has a non-null reminder_scheduled_at and
    reminder_cancelled = false, when the booking status is changed to
    cancelled, the reminder_cancelled field shall be set to true.
    """

    @given(
        reminder_at=reminder_scheduled_at_st,
        initial_status=cancellable_statuses,
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_cancellation_sets_reminder_cancelled(
        self, reminder_at, initial_status
    ):
        """Cancelling a booking with a pending reminder sets reminder_cancelled = True.

        **Validates: Requirements 5.6**
        """
        from app.modules.bookings.service import delete_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking_id = uuid.uuid4()

        # -- Build a mock booking with a pending reminder --
        mock_booking = MagicMock()
        mock_booking.id = booking_id
        mock_booking.org_id = org_id
        mock_booking.status = initial_status
        mock_booking.reminder_scheduled_at = reminder_at
        mock_booking.reminder_cancelled = False

        # db.execute returns the booking
        booking_result = MagicMock()
        booking_result.scalar_one_or_none.return_value = mock_booking

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=booking_result)
        mock_db.flush = AsyncMock()

        with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock):
            await delete_booking(
                mock_db,
                org_id=org_id,
                user_id=user_id,
                booking_id=booking_id,
                ip_address="127.0.0.1",
            )

        # -- Assertions --
        # The booking status should be cancelled
        assert mock_booking.status == "cancelled"
        # The pending reminder should be cancelled
        assert mock_booking.reminder_cancelled is True


# ---------------------------------------------------------------------------
# Property 12: Reminder sent at most once per booking
# ---------------------------------------------------------------------------

# Strategy: random sequences of update dicts (fields that update_booking accepts)
update_field_values = {
    "notes": st.one_of(st.none(), st.text(min_size=0, max_size=100)),
    "vehicle_rego": st.one_of(
        st.none(),
        st.text(
            alphabet=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
            min_size=1,
            max_size=10,
        ),
    ),
    "service_type": st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    "duration_minutes": st.integers(min_value=15, max_value=480),
}


@st.composite
def update_sequences(draw):
    """Generate a list of 1-5 update dicts for a booking."""
    num_updates = draw(st.integers(min_value=1, max_value=5))
    updates = []
    for _ in range(num_updates):
        update = {}
        # Randomly include some fields in each update
        for field, strategy in update_field_values.items():
            if draw(st.booleans()):
                update[field] = draw(strategy)
        # Ensure at least one field per update
        if not update:
            update["notes"] = draw(st.text(min_size=0, max_size=50))
        updates.append(update)
    return updates


class TestReminderSentAtMostOnce:
    """Property 12: Reminder sent at most once per booking.

    Feature: booking-modal-enhancements, Property 12: Reminder sent at most once per booking

    **Validates: Requirements 5.7**

    For any booking with a scheduled reminder, regardless of how many times
    the booking is updated, the reminder notification shall be dispatched
    at most once (tracked by the existing reminder_sent flag).
    """

    @given(
        updates=update_sequences(),
        reminder_sent_before=st.booleans(),
    )
    @PBT_SETTINGS
    @pytest.mark.asyncio
    async def test_reminder_sent_flag_transitions_at_most_once(
        self, updates, reminder_sent_before
    ):
        """reminder_sent transitions False→True at most once and never True→False.

        **Validates: Requirements 5.7**
        """
        from app.modules.bookings.service import update_booking

        org_id = uuid.uuid4()
        user_id = uuid.uuid4()
        booking_id = uuid.uuid4()
        customer_id = uuid.uuid4()

        # -- Build a mock booking with a scheduled reminder --
        mock_booking = MagicMock()
        mock_booking.id = booking_id
        mock_booking.org_id = org_id
        mock_booking.customer_id = customer_id
        mock_booking.status = "scheduled"
        mock_booking.vehicle_rego = "ABC123"
        mock_booking.branch_id = None
        mock_booking.service_type = "Test Service"
        mock_booking.service_catalogue_id = None
        mock_booking.service_price = None
        mock_booking.scheduled_at = datetime(2027, 6, 15, 10, 0, tzinfo=timezone.utc)
        mock_booking.duration_minutes = 60
        mock_booking.notes = "Initial notes"
        mock_booking.assigned_to = None
        mock_booking.created_by = user_id
        mock_booking.created_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
        mock_booking.updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
        mock_booking.send_email_confirmation = True
        mock_booking.send_sms_confirmation = False
        mock_booking.reminder_offset_hours = 24.0
        mock_booking.reminder_scheduled_at = datetime(2027, 6, 14, 10, 0, tzinfo=timezone.utc)
        mock_booking.reminder_cancelled = False
        # Start with the generated initial state for reminder_sent
        mock_booking.reminder_sent = reminder_sent_before

        # -- Mock customer for response --
        mock_customer = MagicMock()
        mock_customer.first_name = "Test"
        mock_customer.last_name = "Customer"

        # Track all reminder_sent values across updates
        reminder_sent_history: list[bool] = [reminder_sent_before]

        # Apply each update sequentially
        for update_dict in updates:
            # Reset mocks for each call
            booking_result = MagicMock()
            booking_result.scalar_one_or_none.return_value = mock_booking

            customer_result = MagicMock()
            customer_result.scalar_one_or_none.return_value = mock_customer

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=[booking_result, customer_result])
            mock_db.flush = AsyncMock()

            with patch("app.modules.bookings.service.write_audit_log", new_callable=AsyncMock), \
                 patch("app.modules.bookings.service._check_staff_availability", new_callable=AsyncMock):
                await update_booking(
                    mock_db,
                    org_id=org_id,
                    user_id=user_id,
                    booking_id=booking_id,
                    updates=update_dict,
                )

            # Record the reminder_sent value after this update
            reminder_sent_history.append(mock_booking.reminder_sent)

        # -- Assertions --
        # 1. reminder_sent must never transition from True back to False
        for i in range(1, len(reminder_sent_history)):
            if reminder_sent_history[i - 1] is True:
                assert reminder_sent_history[i] is True, (
                    f"reminder_sent was reset from True to False at update {i}. "
                    f"History: {reminder_sent_history}"
                )

        # 2. Count False→True transitions: must be at most 1
        false_to_true_count = sum(
            1
            for i in range(1, len(reminder_sent_history))
            if reminder_sent_history[i - 1] is False
            and reminder_sent_history[i] is True
        )
        assert false_to_true_count <= 1, (
            f"reminder_sent transitioned False→True {false_to_true_count} times "
            f"(expected at most 1). History: {reminder_sent_history}"
        )
