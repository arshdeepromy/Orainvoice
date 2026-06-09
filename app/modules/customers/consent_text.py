"""Source of truth for kiosk reminder Consent_Text and Consent_Text_Version.

This module defines the legally-reviewed wording shown on the kiosk Reminder
Consent step and the version string that gets persisted on every
``customer.custom_fields["reminder_consent"]`` record.

Version-update rule
-------------------
``KIOSK_CONSENT_TEXT_VERSION`` MUST be bumped whenever ``KIOSK_CONSENT_TEXT``
changes in *substance* — that is, whenever the legal meaning of the wording
changes (different categories, different revocation mechanism, different
penalty wording, different sender identification, etc.). The version string
locks the legal text to a verifiable timestamped identifier so that, if a
compliance challenge is raised, we can prove which exact wording each
Customer agreed to under the Unsolicited Electronic Messages Act 2007.

The ``{workshop_name}`` placeholder is filled in at render time by the
backend ``GET /kiosk/consent-text`` endpoint using the org name from the
organisations service. Substituting the workshop name into the placeholder
DOES NOT count as a substance change and DOES NOT require bumping
``KIOSK_CONSENT_TEXT_VERSION`` — only changes to the surrounding wording do.

The frontend reads this via ``GET /kiosk/consent-text`` at kiosk boot,
includes the version in the check-in submission body, and the backend
persists the echoed version on every reminder_consent record.
"""

KIOSK_CONSENT_TEXT_VERSION = "2026-06-08-v1"

KIOSK_CONSENT_TEXT = (
    "I agree to receive reminders about my vehicle's WOF, COF, registration, "
    "and service due dates from {workshop_name} by SMS or email. "
    "I can revoke this consent at any time by phoning the workshop, "
    "without penalty."
)
