"""Background task infrastructure — direct async execution (no Celery).

All tasks run inline as async functions called directly from the
application layer. Previously these were dispatched via Celery workers;
now they execute in-process for simplicity.

The async helper functions in each task module (notifications, scheduled,
subscriptions, integrations, webhooks, reports, pdf_generation) remain
unchanged — only the Celery decorator wrappers have been removed.

See .kiro/steering/email-notifications.md for email/SMS patterns.
"""
