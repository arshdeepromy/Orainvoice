"""Cloud Backup & Restore (Platform DR/BCP) module.

Platform-wide Disaster Recovery / Business Continuity subsystem, operated
exclusively from the Global Admin tier. Produces full ``pg_dump`` custom-format
database dumps plus content-addressed, incrementally-deduplicated file blobs,
encrypts everything client-side under a dedicated escrowed backup key hierarchy
(BMK -> BDK), and uploads the encrypted artifact set to one or more pluggable
destinations through a single provider-agnostic Storage_Interface.

Follows the standard module pattern (``router.py`` / ``service.py`` /
``models.py`` / ``schemas.py``). All tables defined here are platform/global
(no ``org_id``, no RLS).
"""
