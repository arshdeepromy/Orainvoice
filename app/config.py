"""Application settings loaded from environment variables."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """All platform configuration, sourced from env vars or a .env file."""

    # --- Application ---
    app_name: str = "WorkshopPro NZ"
    debug: bool = False
    environment: str = "development"  # development | staging | production

    # --- Database (PostgreSQL) ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/workshoppro"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT / Auth ---
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    refresh_token_remember_days: int = 30

    # --- Stripe ---
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_connect_client_id: str = ""
    stripe_connect_redirect_uri: str = "http://localhost:8000/api/v1/billing/stripe/connect/callback"

    # --- Frontend ---
    frontend_base_url: str = "http://localhost:5173"

    # --- Carjam ---
    carjam_api_key: str = ""
    carjam_base_url: str = "https://www.carjam.co.nz"
    carjam_global_rate_limit_per_minute: int = 60

    # --- Email (Brevo / SendGrid / SMTP) ---
    smtp_api_key: str = ""
    smtp_from_email: str = "noreply@workshoppro.nz"
    smtp_from_name: str = "WorkshopPro NZ"

    # --- Bounce webhook secrets ---
    brevo_webhook_secret: str = ""
    sendgrid_webhook_secret: str = ""

    # --- Twilio SMS ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_sender_number: str = ""

    # --- Xero ---
    xero_client_id: str = ""
    xero_client_secret: str = ""

    # --- MYOB ---
    myob_client_id: str = ""
    myob_client_secret: str = ""

    # --- Google OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- WebAuthn / Passkeys ---
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "OraInvoice"
    webauthn_origin: str = "http://localhost:5173"

    # --- Encryption ---
    encryption_master_key: str = "change-me-in-production"

    # --- Database SSL (Requirement 52.1, 52.2) ---
    database_ssl_mode: str = "prefer"  # require | prefer | disable

    # --- Session Management ---
    max_sessions_per_user: int = 5

    # --- Rate Limiting ---
    rate_limit_per_user_per_minute: int = 100
    rate_limit_per_org_per_minute: int = 1000
    rate_limit_auth_per_ip_per_minute: int = Field(
        default=10,
        description="Rate limit for auth endpoints per IP per minute (increase for development)"
    )

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:80", "http://localhost", "https://invoice.oraflows.co.nz"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @model_validator(mode="after")
    def _validate_secrets_not_default(self) -> "Settings":
        """Reject default placeholder secrets in production/staging."""
        if self.environment in ("production", "staging"):
            placeholder = "change-me-in-production"
            if self.jwt_secret == placeholder:
                raise ValueError(
                    f"jwt_secret must not be the default placeholder in {self.environment}"
                )
            if self.encryption_master_key == placeholder:
                raise ValueError(
                    f"encryption_master_key must not be the default placeholder in {self.environment}"
                )
        return self


settings = Settings()
