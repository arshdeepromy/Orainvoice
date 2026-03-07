"""SQLAlchemy column-level encryption helpers.

Provides ``EncryptedString`` — a custom SQLAlchemy type that transparently
encrypts values on write and decrypts on read using the envelope encryption
from ``app.core.encryption``.

Sensitive columns (tax numbers, bank details, API keys) should use this type
so that raw database queries never expose plaintext PII.

Usage in a model::

    from app.core.encrypted_field import EncryptedString

    class Organisation(Base):
        tax_number = mapped_column(EncryptedString(), nullable=True)

The underlying column stores ``BYTEA``.  Values are transparently
encrypted/decrypted via the ``process_bind_param`` / ``process_result_value``
hooks.
"""

from __future__ import annotations

from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

from app.core.encryption import encrypt_field, decrypt_field


class EncryptedString(TypeDecorator):
    """A string column that is stored encrypted at rest using AES-256-GCM.

    The database column type is ``LargeBinary`` (BYTEA in PostgreSQL).
    Python-side values are plain ``str``.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> bytes | None:
        """Encrypt the value before writing to the database."""
        if value is None:
            return None
        return encrypt_field(value)

    def process_result_value(self, value: bytes | None, dialect) -> str | None:
        """Decrypt the value when reading from the database."""
        if value is None:
            return None
        return decrypt_field(value)
