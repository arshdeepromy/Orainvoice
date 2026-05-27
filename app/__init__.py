"""OraInvoice / WorkshopPro NZ FastAPI application.

1.11.1 — security hotfix: the Forgot Password flow previously
short-circuited at the "send the email" step because the auth service
had no implementation for ``_send_password_reset_email``. The reset
URL was generated, persisted, and audit-logged, but never reached the
user's inbox. Implemented using the same raw ``smtplib`` +
``EmailProvider`` priority loop already used by the lockout and
invitation emails, so reset emails now actually deliver.
"""

__version__ = "1.11.1"
