"""Google OAuth 2.0 client — exchange authorization code for user info."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@dataclass
class GoogleUserInfo:
    """Extracted user information from Google OAuth."""

    email: str
    name: str | None
    google_id: str


class GoogleOAuthError(Exception):
    """Raised when Google OAuth flow fails."""


async def exchange_code_for_user_info(
    code: str,
    redirect_uri: str,
) -> GoogleUserInfo:
    """Exchange an authorization code for Google user info.

    1. POST to Google token endpoint to get access + ID tokens.
    2. Use the access token to fetch user info from the userinfo endpoint.

    Raises ``GoogleOAuthError`` on any failure.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleOAuthError("Google OAuth is not configured")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # --- Step 1: Exchange code for tokens ---
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

        if token_response.status_code != 200:
            logger.warning(
                "Google token exchange failed: %s %s",
                token_response.status_code,
                token_response.text,
            )
            raise GoogleOAuthError("Failed to exchange authorization code")

        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise GoogleOAuthError("No access token in Google response")

        # --- Step 2: Fetch user info ---
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_response.status_code != 200:
            logger.warning(
                "Google userinfo fetch failed: %s %s",
                userinfo_response.status_code,
                userinfo_response.text,
            )
            raise GoogleOAuthError("Failed to fetch user info from Google")

        userinfo = userinfo_response.json()
        email = userinfo.get("email")
        if not email:
            raise GoogleOAuthError("Google account has no email address")

        return GoogleUserInfo(
            email=email,
            name=userinfo.get("name"),
            google_id=userinfo.get("sub", ""),
        )
