"""OraInvoice / WorkshopPro NZ FastAPI application.

Bumped to 1.11.0 with the QR partial-payment flow: org users can now
choose between Full and Partial payment when generating a kiosk QR
session, with proportional Stripe application-fee scaling, partial-
aware webhook recording, partial-amount-aware receipt emails, and a
post-payment cleanup that closes a pre-existing reuse-branch
regression in ``create_qr_session_for_existing_invoice``.
"""

__version__ = "1.11.0"
