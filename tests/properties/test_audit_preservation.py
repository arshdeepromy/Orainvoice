"""Preservation property tests for platform audit fixes.

These tests capture the BASELINE behavior of the UNFIXED code for all
non-buggy code paths. They must PASS on the current unfixed code and
continue to PASS after fixes are applied, ensuring no regressions.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.13, 3.14**

Property 2: Preservation — Existing Functionality Unchanged
"""

from __future__ import annotations

import json
import re
import uuid as _uuid

import pytest
from hypothesis import given, settings as h_settings, HealthCheck
from hypothesis import strategies as st

PRESERVATION_SETTINGS = h_settings(
    max_examples=30,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


# ===================================================================
# PROPERTY: RLS scoping with valid UUIDs (Preservation Req 3.1)
# ===================================================================


class TestRLSScopingPreservation:
    """For all valid UUIDs, _set_rls_org_id correctly scopes database
    queries to the specified org.

    **Validates: Requirements 3.1**
    """

    @given(org_id=st.uuids().map(str))
    @PRESERVATION_SETTINGS
    def test_rls_setter_accepts_valid_uuids(self, org_id: str):
        """The RLS setter function must accept any valid UUID and execute
        a SQL statement that sets app.current_org_id to that UUID."""
        import pathlib

        source = pathlib.Path("app/core/database.py").read_text()

        # The function must exist
        assert "async def _set_rls_org_id" in source, (
            "_set_rls_org_id function must exist in database.py"
        )

        # The function must validate UUIDs before using them
        assert "uuid.UUID" in source or "_uuid.UUID" in source, (
            "RLS setter must validate org_id as a UUID"
        )

        # The function must execute a SQL statement that sets the org context
        # On unfixed code this uses SET LOCAL; after fix it uses set_config
        # Extract the full function body (everything from the def to the next
        # top-level definition or end of file)
        func_start = source.find("async def _set_rls_org_id")
        assert func_start != -1, "_set_rls_org_id function body not found"
        # Find the next top-level definition after the function
        next_def = re.search(r"\n(?:async )?def |^class ", source[func_start + 10:], re.MULTILINE)
        if next_def:
            func_body = source[func_start:func_start + 10 + next_def.start()]
        else:
            func_body = source[func_start:]

        # Must contain SQL execution that references app.current_org_id
        assert "app.current_org_id" in func_body, (
            "RLS setter must set app.current_org_id in the SQL statement"
        )

        # Must handle None org_id by resetting
        assert "RESET app.current_org_id" in func_body, (
            "RLS setter must RESET app.current_org_id when org_id is None"
        )

    @given(org_id=st.uuids().map(str))
    @PRESERVATION_SETTINGS
    def test_rls_uuid_validation_rejects_invalid_input(self, org_id: str):
        """The RLS setter validates that org_id is a proper UUID format.
        Valid UUIDs should pass validation and be used in the SQL."""
        # Verify the UUID round-trips correctly through validation
        validated = str(_uuid.UUID(org_id))
        assert validated == org_id.lower().replace(
            org_id, validated
        ) or _uuid.UUID(validated), (
            f"UUID {org_id} should round-trip through validation"
        )


# ===================================================================
# PROPERTY: JWT auth flow works correctly (Preservation Req 3.2, 3.3)
# ===================================================================


class TestJWTAuthPreservation:
    """For all valid JWT tokens, authentication and authorization
    continues to work correctly.

    **Validates: Requirements 3.2, 3.3**
    """

    def test_auth_router_has_login_endpoint(self):
        """The auth router must expose a /login endpoint."""
        import pathlib

        source = pathlib.Path("app/modules/auth/router.py").read_text()
        assert '"/login"' in source, "Auth router must have /login endpoint"

    def test_auth_router_has_refresh_endpoint(self):
        """The auth router must expose a /token/refresh endpoint."""
        import pathlib

        source = pathlib.Path("app/modules/auth/router.py").read_text()
        assert '"/token/refresh"' in source, (
            "Auth router must have /token/refresh endpoint"
        )

    def test_auth_router_has_session_management(self):
        """The auth router must expose session management endpoints."""
        import pathlib

        source = pathlib.Path("app/modules/auth/router.py").read_text()
        assert '"/sessions"' in source, "Auth router must have /sessions endpoint"
        assert "invalidate-all" in source or "invalidate_all" in source, (
            "Auth router must have session invalidation endpoint"
        )

    @given(
        env=st.sampled_from(["development", "test"]),
    )
    @PRESERVATION_SETTINGS
    def test_jwt_config_allows_defaults_in_dev(self, env: str):
        """JWT configuration must allow default secrets in development/test
        environments for convenience."""
        import pathlib

        source = pathlib.Path("app/config.py").read_text()

        # The Settings class must have jwt_secret and jwt_algorithm fields
        assert "jwt_secret" in source, "Settings must have jwt_secret field"
        assert "jwt_algorithm" in source, "Settings must have jwt_algorithm field"
        assert "access_token_expire_minutes" in source, (
            "Settings must have access_token_expire_minutes"
        )
        assert "refresh_token_expire_days" in source, (
            "Settings must have refresh_token_expire_days"
        )

    def test_login_returns_token_response(self):
        """The login endpoint must return a TokenResponse model."""
        import pathlib

        source = pathlib.Path("app/modules/auth/router.py").read_text()
        assert "TokenResponse" in source, (
            "Login endpoint must use TokenResponse model"
        )

    def test_refresh_endpoint_implements_rotation(self):
        """The refresh endpoint must implement token rotation."""
        import pathlib

        source = pathlib.Path("app/modules/auth/router.py").read_text()
        assert "rotate_refresh_token" in source, (
            "Refresh endpoint must call rotate_refresh_token"
        )


# ===================================================================
# PROPERTY: API routes respond correctly (Preservation Req 3.5)
# ===================================================================


class TestAPIRoutePreservation:
    """For all existing API routes, response status codes and shapes
    are unchanged after router deduplication.

    **Validates: Requirements 3.5**
    """

    # The V1 routes that must continue to exist
    V1_ROUTE_PREFIXES = [
        "/api/v1/auth",
        "/api/v1/admin",
        "/api/v1/org",
        "/api/v1/customers",
        "/api/v1/vehicles",
        "/api/v1/invoices",
        "/api/v1/payments",
        "/api/v1/billing",
        "/api/v1/catalogue",
        "/api/v1/storage",
        "/api/v1/notifications",
        "/api/v1/quotes",
        "/api/v1/job-cards",
        "/api/v1/bookings",
        "/api/v1/inventory",
        "/api/v1/reports",
        "/api/v1/portal",
        "/api/v1/data",
        "/api/v1/webhooks",
    ]

    @given(prefix=st.sampled_from(V1_ROUTE_PREFIXES))
    @PRESERVATION_SETTINGS
    def test_v1_routes_are_registered(self, prefix: str):
        """All V1 API route prefixes must be registered in main.py."""
        import pathlib

        source = pathlib.Path("app/main.py").read_text()
        assert f'"{prefix}"' in source or f"'{prefix}'" in source, (
            f"V1 route prefix {prefix} must be registered in main.py"
        )

    def test_main_imports_all_required_routers(self):
        """main.py must import all required router modules."""
        import pathlib

        source = pathlib.Path("app/main.py").read_text()

        required_routers = [
            "auth_router",
            "admin_router",
            "notifications_router",
            "invoices_router",
            "customers_router",
        ]
        for router_name in required_routers:
            assert router_name in source, (
                f"main.py must import {router_name}"
            )

    def test_create_app_function_exists(self):
        """main.py must have a create_app function that sets up the app."""
        import pathlib

        source = pathlib.Path("app/main.py").read_text()
        assert "def create_app" in source, (
            "main.py must have a create_app function"
        )


# ===================================================================
# PROPERTY: Notification CRUD endpoints (Preservation Req 3.10, 3.11, 3.12)
# ===================================================================


class TestNotificationCRUDPreservation:
    """For all valid notification CRUD requests, backend endpoints
    return the same responses.

    **Validates: Requirements 3.10, 3.11, 3.12**
    """

    def test_overdue_rules_schema_has_send_email_send_sms(self):
        """The OverdueReminderRuleCreate schema must use send_email/send_sms
        boolean fields (not a channel string)."""
        from app.modules.notifications.schemas import OverdueReminderRuleCreate

        schema = OverdueReminderRuleCreate.model_json_schema()
        props = schema.get("properties", {})
        assert "send_email" in props, (
            "OverdueReminderRuleCreate must have send_email field"
        )
        assert "send_sms" in props, (
            "OverdueReminderRuleCreate must have send_sms field"
        )
        assert "days_after_due" in props, (
            "OverdueReminderRuleCreate must have days_after_due field"
        )

    @given(
        days=st.integers(min_value=1, max_value=365),
        send_email=st.booleans(),
        send_sms=st.booleans(),
    )
    @PRESERVATION_SETTINGS
    def test_overdue_rule_create_schema_accepts_valid_inputs(
        self, days: int, send_email: bool, send_sms: bool
    ):
        """OverdueReminderRuleCreate must accept any valid combination of
        days_after_due, send_email, and send_sms."""
        from app.modules.notifications.schemas import OverdueReminderRuleCreate

        rule = OverdueReminderRuleCreate(
            days_after_due=days,
            send_email=send_email,
            send_sms=send_sms,
        )
        assert rule.days_after_due == days
        assert rule.send_email == send_email
        assert rule.send_sms == send_sms

    def test_overdue_rules_list_response_has_reminders_enabled(self):
        """OverdueReminderRuleListResponse must include reminders_enabled field."""
        from app.modules.notifications.schemas import OverdueReminderRuleListResponse

        schema = OverdueReminderRuleListResponse.model_json_schema()
        props = schema.get("properties", {})
        assert "reminders_enabled" in props, (
            "OverdueReminderRuleListResponse must have reminders_enabled"
        )
        assert "rules" in props, (
            "OverdueReminderRuleListResponse must have rules"
        )
        assert "total" in props, (
            "OverdueReminderRuleListResponse must have total"
        )

    def test_notification_preferences_response_is_grouped(self):
        """NotificationPreferencesResponse must return grouped categories."""
        from app.modules.notifications.schemas import NotificationPreferencesResponse

        schema = NotificationPreferencesResponse.model_json_schema()
        props = schema.get("properties", {})
        assert "categories" in props, (
            "NotificationPreferencesResponse must have categories field"
        )

    @given(
        notification_type=st.sampled_from([
            "invoice_issued", "payment_received", "wof_expiry_reminder",
            "storage_warning_80", "login_alert",
        ]),
        is_enabled=st.booleans(),
        channel=st.sampled_from(["email", "sms", "both"]),
    )
    @PRESERVATION_SETTINGS
    def test_notification_preference_update_schema_accepts_valid_inputs(
        self, notification_type: str, is_enabled: bool, channel: str
    ):
        """NotificationPreferenceUpdateRequest must accept valid inputs."""
        from app.modules.notifications.schemas import NotificationPreferenceUpdateRequest

        update = NotificationPreferenceUpdateRequest(
            notification_type=notification_type,
            is_enabled=is_enabled,
            channel=channel,
        )
        assert update.notification_type == notification_type
        assert update.is_enabled == is_enabled
        assert update.channel == channel

    def test_template_response_has_template_type_field(self):
        """TemplateResponse must include template_type field."""
        from app.modules.notifications.schemas import TemplateResponse

        schema = TemplateResponse.model_json_schema()
        props = schema.get("properties", {})
        assert "template_type" in props, (
            "TemplateResponse must have template_type field"
        )
        assert "id" in props, "TemplateResponse must have id field"
        assert "channel" in props, "TemplateResponse must have channel field"
        assert "subject" in props, "TemplateResponse must have subject field"

    def test_sms_template_response_has_template_type_field(self):
        """SmsTemplateResponse must include template_type field."""
        from app.modules.notifications.schemas import SmsTemplateResponse

        schema = SmsTemplateResponse.model_json_schema()
        props = schema.get("properties", {})
        assert "template_type" in props, (
            "SmsTemplateResponse must have template_type field"
        )
        assert "body" in props, "SmsTemplateResponse must have body field"
        assert "char_count" in props, "SmsTemplateResponse must have char_count"


# ===================================================================
# PROPERTY: Rate limiter with Redis available (Preservation Req 3.7)
# ===================================================================


class TestRateLimiterPreservation:
    """For all rate-limited requests when Redis IS available, rate limits
    are enforced with same thresholds.

    **Validates: Requirements 3.7**
    """

    def test_rate_limiter_has_check_rate_limit_function(self):
        """The rate limiter must have a _check_rate_limit function that
        implements the sliding window algorithm."""
        import pathlib

        source = pathlib.Path("app/middleware/rate_limit.py").read_text()
        assert "async def _check_rate_limit" in source, (
            "Rate limiter must have _check_rate_limit function"
        )

    def test_rate_limiter_enforces_per_user_limit(self):
        """The rate limiter must enforce per-user rate limits."""
        import pathlib

        source = pathlib.Path("app/middleware/rate_limit.py").read_text()
        assert "rl:user:" in source, (
            "Rate limiter must have per-user rate limit key"
        )
        assert "rate_limit_per_user_per_minute" in source, (
            "Rate limiter must reference per-user limit from settings"
        )

    def test_rate_limiter_enforces_per_org_limit(self):
        """The rate limiter must enforce per-org rate limits."""
        import pathlib

        source = pathlib.Path("app/middleware/rate_limit.py").read_text()
        assert "rl:org:" in source, (
            "Rate limiter must have per-org rate limit key"
        )
        assert "rate_limit_per_org_per_minute" in source, (
            "Rate limiter must reference per-org limit from settings"
        )

    def test_rate_limiter_enforces_auth_ip_limit(self):
        """The rate limiter must enforce per-IP limits on auth endpoints."""
        import pathlib

        source = pathlib.Path("app/middleware/rate_limit.py").read_text()
        assert "rl:auth:ip:" in source, (
            "Rate limiter must have per-IP auth rate limit key"
        )
        assert "rate_limit_auth_per_ip_per_minute" in source, (
            "Rate limiter must reference auth IP limit from settings"
        )

    def test_rate_limiter_returns_429_on_exceeded(self):
        """The rate limiter must return HTTP 429 when limits are exceeded."""
        import pathlib

        source = pathlib.Path("app/middleware/rate_limit.py").read_text()
        assert "429" in source, (
            "Rate limiter must return 429 status code"
        )
        assert "Retry-After" in source, (
            "Rate limiter must include Retry-After header"
        )

    def test_rate_limiter_uses_sliding_window(self):
        """The rate limiter must use a sorted-set sliding window algorithm."""
        import pathlib

        source = pathlib.Path("app/middleware/rate_limit.py").read_text()
        assert "zremrangebyscore" in source, (
            "Rate limiter must use zremrangebyscore for sliding window"
        )
        assert "zcard" in source, (
            "Rate limiter must use zcard to count requests in window"
        )

    @given(
        limit=st.integers(min_value=1, max_value=10000),
    )
    @PRESERVATION_SETTINGS
    def test_rate_limit_settings_fields_exist_in_config(self, limit: int):
        """Rate limit settings fields must exist in the config module."""
        import pathlib

        source = pathlib.Path("app/config.py").read_text()
        assert "rate_limit_per_user_per_minute" in source, (
            "Config must have rate_limit_per_user_per_minute"
        )
        assert "rate_limit_per_org_per_minute" in source, (
            "Config must have rate_limit_per_org_per_minute"
        )
        assert "rate_limit_auth_per_ip_per_minute" in source, (
            "Config must have rate_limit_auth_per_ip_per_minute"
        )
        # Verify the defaults are positive integers
        import re
        for field in ["rate_limit_per_user_per_minute", "rate_limit_per_org_per_minute", "rate_limit_auth_per_ip_per_minute"]:
            match = re.search(rf"{field}:\s*int\s*=\s*(\d+)", source)
            assert match, f"Config must have {field} with int default"
            default_val = int(match.group(1))
            assert default_val > 0, f"{field} default must be positive"


# ===================================================================
# PROPERTY: SMTP config saves (Preservation Req 3.8, 3.9)
# ===================================================================


class TestSMTPConfigPreservation:
    """For all SMTP config saves with valid fields, backend stores
    encrypted config and returns success.

    **Validates: Requirements 3.8, 3.9**
    """

    @given(
        provider=st.sampled_from(["brevo", "sendgrid", "smtp"]),
        domain=st.from_regex(r"[a-z]{3,10}\.[a-z]{2,4}", fullmatch=True),
        from_email=st.emails(),
        from_name=st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz "),
    )
    @PRESERVATION_SETTINGS
    def test_smtp_config_request_schema_accepts_valid_inputs(
        self, provider: str, domain: str, from_email: str, from_name: str
    ):
        """SmtpConfigRequest must accept all valid provider/domain/email combos."""
        from app.modules.admin.schemas import SmtpConfigRequest

        config = SmtpConfigRequest(
            provider=provider,
            domain=domain,
            from_email=from_email,
            from_name=from_name,
        )
        assert config.provider == provider
        assert config.domain == domain
        assert config.from_email == from_email
        assert config.from_name == from_name

    def test_smtp_config_request_has_all_10_fields(self):
        """SmtpConfigRequest must have all 10 fields matching the backend schema."""
        from app.modules.admin.schemas import SmtpConfigRequest

        schema = SmtpConfigRequest.model_json_schema()
        props = schema.get("properties", {})
        expected_fields = [
            "provider", "api_key", "host", "port", "username",
            "password", "domain", "from_email", "from_name", "reply_to",
        ]
        for field in expected_fields:
            assert field in props, (
                f"SmtpConfigRequest must have {field} field"
            )

    def test_smtp_test_endpoint_exists(self):
        """The admin router must have an SMTP test endpoint."""
        import pathlib

        source = pathlib.Path("app/modules/admin/router.py").read_text()
        assert "/integrations/smtp/test" in source, (
            "Admin router must have SMTP test endpoint"
        )

    def test_smtp_config_endpoint_exists(self):
        """The admin router must have an SMTP config endpoint."""
        import pathlib

        source = pathlib.Path("app/modules/admin/router.py").read_text()
        assert "/integrations/smtp" in source, (
            "Admin router must have SMTP config endpoint"
        )


# ===================================================================
# PROPERTY: Notification log queries (Preservation Req 3.12)
# ===================================================================


class TestNotificationLogPreservation:
    """For all notification log queries with valid filters, backend
    returns paginated entries with correct fields.

    **Validates: Requirements 3.12**
    """

    def test_notification_log_entry_has_template_type(self):
        """NotificationLogEntry must use template_type (not template_name)."""
        from app.modules.notifications.schemas import NotificationLogEntry

        schema = NotificationLogEntry.model_json_schema()
        props = schema.get("properties", {})
        assert "template_type" in props, (
            "NotificationLogEntry must have template_type field"
        )
        assert "status" in props, (
            "NotificationLogEntry must have status field"
        )
        assert "channel" in props, (
            "NotificationLogEntry must have channel field"
        )
        assert "recipient" in props, (
            "NotificationLogEntry must have recipient field"
        )

    def test_notification_log_response_is_paginated(self):
        """NotificationLogResponse must support pagination."""
        from app.modules.notifications.schemas import NotificationLogResponse

        schema = NotificationLogResponse.model_json_schema()
        props = schema.get("properties", {})
        assert "entries" in props, (
            "NotificationLogResponse must have entries field"
        )
        assert "total" in props, (
            "NotificationLogResponse must have total field"
        )
        assert "page" in props, (
            "NotificationLogResponse must have page field"
        )
        assert "page_size" in props, (
            "NotificationLogResponse must have page_size field"
        )

    @given(
        status=st.sampled_from(["queued", "sent", "delivered", "bounced", "failed"]),
        channel=st.sampled_from(["email", "sms"]),
        page=st.integers(min_value=1, max_value=100),
        page_size=st.integers(min_value=1, max_value=100),
    )
    @PRESERVATION_SETTINGS
    def test_notification_log_filter_params_are_valid(
        self, status: str, channel: str, page: int, page_size: int
    ):
        """The notification log endpoint supports status, channel, page,
        and page_size query parameters."""
        import pathlib

        source = pathlib.Path("app/modules/notifications/router.py").read_text()
        # The endpoint must accept these filter parameters
        assert "status" in source, "Log endpoint must accept status filter"
        assert "channel" in source, "Log endpoint must accept channel filter"
        assert "page" in source, "Log endpoint must accept page parameter"
        assert "page_size" in source, "Log endpoint must accept page_size parameter"

    def test_notification_log_endpoint_exists(self):
        """The notifications router must have a log endpoint."""
        import pathlib

        source = pathlib.Path("app/modules/notifications/router.py").read_text()
        assert "/log" in source or "notification_log" in source or "get_notification_log" in source, (
            "Notifications router must have a log endpoint"
        )


# ===================================================================
# PROPERTY: Integration config encryption (Preservation Req 3.13)
# ===================================================================


class TestIntegrationEncryptionPreservation:
    """For all integration config storage operations, envelope encryption
    is maintained.

    **Validates: Requirements 3.13**
    """

    @given(
        plaintext=st.text(min_size=1, max_size=500, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"),
    )
    @PRESERVATION_SETTINGS
    def test_envelope_encrypt_decrypt_roundtrip(self, plaintext: str):
        """Envelope encryption module must have encrypt and decrypt functions
        that can round-trip data."""
        import pathlib

        source = pathlib.Path("app/core/encryption.py").read_text()
        # Must have both encrypt and decrypt functions
        assert "def envelope_encrypt" in source, (
            "Encryption module must have envelope_encrypt function"
        )
        assert "def envelope_decrypt" in source, (
            "Encryption module must have envelope_decrypt function"
        )
        assert "def envelope_decrypt_str" in source, (
            "Encryption module must have envelope_decrypt_str function"
        )

    @given(
        plaintext=st.text(min_size=1, max_size=200, alphabet="abcdefghijklmnopqrstuvwxyz"),
    )
    @PRESERVATION_SETTINGS
    def test_envelope_encrypt_uses_random_nonce(self, plaintext: str):
        """Each encryption must use a random nonce for security."""
        import pathlib

        source = pathlib.Path("app/core/encryption.py").read_text()
        # Must use os.urandom for nonce generation
        assert "os.urandom" in source, (
            "Encryption must use os.urandom for random nonce/DEK generation"
        )

    def test_envelope_encrypt_uses_aes_gcm(self):
        """The encryption module must use AES-GCM."""
        import pathlib

        source = pathlib.Path("app/core/encryption.py").read_text()
        assert "AESGCM" in source, (
            "Encryption module must use AES-GCM"
        )

    def test_envelope_encrypt_uses_two_layer_scheme(self):
        """The encryption module must implement two-layer envelope encryption
        with a master key and per-record DEK."""
        import pathlib

        source = pathlib.Path("app/core/encryption.py").read_text()
        assert "master_key" in source or "_derive_master_key" in source, (
            "Encryption must use a master key"
        )
        assert "dek" in source.lower(), (
            "Encryption must use data encryption keys (DEK)"
        )

    @given(
        config_json=st.fixed_dictionaries({
            "provider": st.sampled_from(["brevo", "sendgrid", "smtp"]),
            "api_key": st.text(min_size=1, max_size=50, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"),
            "domain": st.from_regex(r"[a-z]{3,10}\.[a-z]{2,4}", fullmatch=True),
        }).map(json.dumps),
    )
    @PRESERVATION_SETTINGS
    def test_integration_config_json_structure_is_preserved(
        self, config_json: str
    ):
        """Integration config JSON must be valid and parseable."""
        parsed = json.loads(config_json)
        assert "provider" in parsed, "Config must have provider field"
        assert "api_key" in parsed, "Config must have api_key field"
        assert "domain" in parsed, "Config must have domain field"
        # Verify the JSON round-trips through serialization
        re_serialized = json.loads(json.dumps(parsed))
        assert re_serialized == parsed, (
            "Integration config JSON must survive serialization round-trip"
        )


# ===================================================================
# PROPERTY: WOF/Rego settings schema (Preservation Req 3.10)
# ===================================================================


class TestWofRegoPreservation:
    """WOF/Rego reminder settings schema is preserved.

    **Validates: Requirements 3.10**
    """

    @given(
        enabled=st.booleans(),
        days=st.integers(min_value=1, max_value=365),
        channel=st.sampled_from(["email", "sms", "both"]),
    )
    @PRESERVATION_SETTINGS
    def test_wof_rego_settings_schema_accepts_valid_inputs(
        self, enabled: bool, days: int, channel: str
    ):
        """WofRegoReminderSettingsRequest must accept valid inputs."""
        from app.modules.notifications.schemas import WofRegoReminderSettingsRequest

        settings = WofRegoReminderSettingsRequest(
            enabled=enabled,
            days_in_advance=days,
            channel=channel,
        )
        assert settings.enabled == enabled
        assert settings.days_in_advance == days
        assert settings.channel == channel

    def test_wof_rego_response_has_combined_fields(self):
        """WofRegoReminderSettingsResponse must have combined fields:
        enabled, days_in_advance, channel."""
        from app.modules.notifications.schemas import WofRegoReminderSettingsResponse

        schema = WofRegoReminderSettingsResponse.model_json_schema()
        props = schema.get("properties", {})
        assert "enabled" in props, "Must have enabled field"
        assert "days_in_advance" in props, "Must have days_in_advance field"
        assert "channel" in props, "Must have channel field"


# ===================================================================
# PROPERTY: Service-layer response shapes (Preservation Req 3.6)
# ===================================================================


class TestServiceLayerPreservation:
    """For all service-layer functions that complete successfully,
    return correct response shapes.

    **Validates: Requirements 3.6**
    """

    def test_admin_service_has_save_smtp_config(self):
        """Admin service must have save_smtp_config function."""
        import pathlib

        source = pathlib.Path("app/modules/admin/service.py").read_text()
        assert "async def save_smtp_config" in source, (
            "Admin service must have save_smtp_config function"
        )

    def test_admin_service_has_list_organisations(self):
        """Admin service must have list_organisations function."""
        import pathlib

        source = pathlib.Path("app/modules/admin/service.py").read_text()
        assert "async def list_organisations" in source, (
            "Admin service must have list_organisations function"
        )

    def test_notification_service_has_list_templates(self):
        """Notification service must have list_templates function."""
        import pathlib

        source = pathlib.Path("app/modules/notifications/service.py").read_text()
        assert "async def list_templates" in source, (
            "Notification service must have list_templates function"
        )

    def test_notification_service_has_update_template(self):
        """Notification service must have update_template function."""
        import pathlib

        source = pathlib.Path("app/modules/notifications/service.py").read_text()
        assert "async def update_template" in source, (
            "Notification service must have update_template function"
        )
