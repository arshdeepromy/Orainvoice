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

    # --- JWT RS256 Migration (REM-22) ---
    jwt_rs256_private_key_path: str = ""  # Path to RSA private key PEM
    jwt_rs256_public_key_path: str = ""   # Path to RSA public key PEM

    # --- Stripe ---
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_connect_client_id: str = ""
    stripe_connect_webhook_secret: str = ""

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
    # Precedence: env var > DB (platform_settings) > empty string default.
    # When env vars are empty, the Xero OAuth flow should look up
    # XERO_CLIENT_ID / XERO_CLIENT_SECRET from the platform_settings table
    # via platform_settings.service.get_setting().
    xero_client_id: str = ""
    xero_client_secret: str = ""

    # --- Akahu ---
    akahu_client_id: str = ""
    akahu_client_secret: str = ""
    akahu_app_token: str = ""

    # --- MYOB ---
    myob_client_id: str = ""
    myob_client_secret: str = ""

    # --- Google OAuth ---
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Microsoft / OneDrive OAuth (Microsoft identity platform) ---
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""

    # --- WebAuthn / Passkeys ---
    # Legacy single-value fallback (used when a request's origin is not on the
    # trusted allowlist below — e.g. server-to-server or a missing Origin header).
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "OraInvoice"
    webauthn_origin: str = "http://localhost:5173"
    # Trusted front-end origins for passkeys. The RP ID + expected origin are
    # derived per-request from whichever of these the request actually came from,
    # so passkeys work across every front-end domain (and localhost in dev)
    # without per-domain config. An origin must be listed here (or added via the
    # WEBAUTHN_ORIGINS env var) to be trusted — this prevents a spoofed Origin
    # header from redirecting the WebAuthn relying party to a domain we don't own.
    webauthn_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost",
        "https://invoice.oraflows.co.nz",
        "https://devin.oraflows.co.nz",
    ]

    # --- Firebase ---
    firebase_project_id: str = ""

    # --- Connexus Webhooks ---
    connexus_webhook_secret: str = ""

    # --- Fleet Portal (B2B Fleet Portal — see .kiro/specs/b2b-fleet-portal/) ---
    # Host or path used to resolve the Workshop_Org for fleet portal requests.
    # Examples:
    #   "fleet.example.com"      → subdomain mode; <slug>.fleet.example.com
    #   ""                       → path mode (default); /fleet/<slug>/...
    # When fleet_portal_default_org_slug is set, single-tenant deployments
    # can route /fleet/* to that org without a subdomain or path slug.
    fleet_portal_host: str = ""
    fleet_portal_default_org_slug: str = ""

    # --- Build metadata (used by /fleet/api/version + /api/v2/version) ---
    # Populated at image build time via Dockerfile ARG GIT_SHA → ENV BUILD_SHA.
    # Frontend bundles read this through the version refresh mechanism
    # (B2B Fleet Portal task 19A.2 — Req 22.1).
    build_sha: str = "dev"

    # --- Portal Token TTL (REM-15) ---
    portal_token_ttl_days: int = 90

    # --- Encryption ---
    encryption_master_key: str = "change-me-in-production"

    # --- Backup blob naming (content-addressed store) ---
    # Platform secret used to key the HMAC-SHA-256 that names content-addressed
    # backup File_Blobs (cloud-backup-restore Req 21.5). It is a *blob-naming*
    # secret only — it never encrypts artifacts (that is the escrowed BDK's job,
    # Req 21.4). When left empty it is derived deterministically from
    # ``encryption_master_key`` (a deployment secret) via HKDF with domain
    # separation, so the destination cannot infer plaintext equality from blob
    # names while the platform's own File_Index still dedups.
    backup_blob_hmac_secret: str = ""

    # --- E-Signature auto-provisioning (Documenso, R20) — PLATFORM-level, best-effort ---
    # Selects the OPTIONAL Documenso auto-provisioning adapter. `off` disables it
    # entirely (the manual per-org connection path remains the supported fallback);
    # `trpc` drives Documenso's internal admin tRPC layer; `db` writes directly to
    # Documenso's self-hosted PostgreSQL. Both `trpc`/`db` rely on Documenso
    # internals (NOT its public REST API) and are upgrade-fragile.
    esign_provisioning_mode: str = "off"  # off | trpc | db
    # Platform-level Documenso admin endpoint + session/credential used ONLY by the
    # `trpc` adapter for provisioning — NEVER a per-org credential and NEVER used for
    # per-org Documenso API calls (those use the org's own team token, R13.7).
    # Held as platform config; may be supplied envelope-encrypted (prefix the value
    # with `enc:` + base64 of the envelope blob) and is decrypted before use.
    esign_documenso_admin_url: str = ""
    esign_documenso_admin_token: str = ""
    # Platform-config Documenso self-hosted PostgreSQL URL used ONLY by the `db`
    # adapter for provisioning. Same handling/secrecy rules as above.
    esign_documenso_db_url: str = ""
    # Allow OraInvoice -> Documenso API calls over plain HTTP **only** for
    # private / loopback / internal-DNS hosts (e.g. container-to-container on a
    # shared Docker network, RFC1918, *.internal). PUBLIC hosts ALWAYS require
    # HTTPS regardless of this flag (R15.4). Default off (HTTPS everywhere); set
    # true only in trusted-network deployments where the team token never
    # traverses the public internet.
    esign_allow_insecure_internal_base_url: bool = False
    # Public origin of the org's Documenso instance used to build recipient
    # signing links (`{public}/sign/{token}`). The per-org connection `base_url`
    # is typically the INTERNAL/private host the API is reached on
    # (e.g. http://documenso:3030 on a shared Docker network), which is NOT a
    # link a signer's browser can open. This is the public `NEXT_PUBLIC_WEBAPP_URL`
    # of the Documenso instance (e.g. https://esignd.example.com). When empty the
    # signing link falls back to the connection's own `base_url`.
    esign_public_documenso_url: str = ""
    # Whether the target Documenso build's `field/create-many` endpoint accepts
    # and HONOURS per-field `fieldMeta` (`required` / `label` / `placeholder`).
    # Per docs/documenso-capability-matrix.md this is currently UNVERIFIED, so
    # the conservative default is False: `create_fields` OMITS `fieldMeta` on the
    # wire (a no-op), and `required`/`label`/`placeholder` stay advisory /
    # OraInvoice-only. Flip to True once a live capability probe (spec task 9.2)
    # confirms the build honours `fieldMeta`.
    esign_field_create_many_honours_field_meta: bool = False
    # Whether the target Documenso build supports DELETING / REPLACING a
    # document's fields in place while it is `sent` and unsigned — the
    # capability the edit-after-send atomic-replace path
    # (`DocumensoClient.replace_fields`) depends on. Per
    # docs/documenso-capability-matrix.md capability (c) is currently
    # UNVERIFIED and the client has NO proven delete-field endpoint, so the
    # conservative default is False: an in-place `PUT …/fields` replace is NOT
    # performed and `replace_fields` raises a clear DocumensoError so
    # edit-after-send degrades to Void_And_Recreate only (proven via
    # `cancel_document`). Flip to True only once a live capability probe (spec
    # task 9.2) confirms the build supports deleting/replacing fields on a
    # sent, unsigned document — mirrors the
    # `esign_field_create_many_honours_field_meta` flag above.
    esign_field_replace_supported: bool = False
    # Whether the target Documenso build supports per-recipient `signingOrder`
    # positions plus a `SEQUENTIAL`/`PARALLEL` distribution mode — the
    # capability the signing-order feature (R15) depends on. Per
    # docs/documenso-capability-matrix.md capability (d) is currently
    # UNVERIFIED: `send_document` today distributes EMAIL-only with no
    # signing-order metadata. The conservative default is False, so sequential
    # DEGRADES to parallel — `create_document` omits the per-recipient
    # `signingOrder` positions and `send_document` always distributes with the
    # `PARALLEL` mode, so no sequential enforcement is claimed. The additive
    # `RecipientSpec.signing_order` field and the `send_document`
    # `signing_order_mode` argument remain accepted and stored regardless. Flip
    # to True only once a live capability probe (spec task 9.2) confirms the
    # build accepts and ENFORCES `signingOrder` + `SEQUENTIAL` (recipient N+1
    # cannot sign before N) — mirrors the two esign capability flags above.
    esign_signing_order_supported: bool = False

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
