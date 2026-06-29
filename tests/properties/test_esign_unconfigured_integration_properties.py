"""Property-based test for the unconfigured-integration failure path (task 5.3).

When an organisation has **no** ``esign_org_connections`` row, the per-org
connection loader :func:`app.integrations.documenso.get_documenso_connection`
must raise :class:`DocumensoNotConfiguredError`. Because every Documenso
operation (send / void / list / detail / download / **connection test**) must
first load the org's connection, this single failure mode gates *every*
operation: there is no way to reach Documenso without a configured connection.

The raised error must humanize (via
:func:`app.modules.esignatures.errors.humanize_esign_error`) to a non-empty,
human-readable message carrying the machine code ``integration_not_configured``
so the user always gets a safe, actionable message instead of a raw exception.

The loader is exercised with a lightweight fake async session returning ``None``
for the connection row (the same pattern as
``tests/test_documenso_connection_loader.py``) over arbitrary org ids (uuids and
their string form), so no real DB is needed.

# Feature: esignature-integration, Property 4: Unconfigured integration fails every operation with a message

**Validates: Requirements 1.9, 1.10**
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.integrations import documenso
from app.integrations.documenso import (
    DocumensoNotConfiguredError,
    get_documenso_connection,
    invalidate_documenso_connection_cache,
)
from app.modules.esignatures.errors import (
    CODE_INTEGRATION_NOT_CONFIGURED,
    humanize_esign_error,
)


# ---------------------------------------------------------------------------
# Fake async session — returns None for the connection row (no connection)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    """Minimal stand-in for AsyncSession.execute(select(...)) returning no row."""

    def __init__(self, row=None):
        self._row = row

    async def execute(self, _stmt):
        return _FakeResult(self._row)


@pytest.fixture(autouse=True)
def _clear_cache():
    invalidate_documenso_connection_cache()
    yield
    invalidate_documenso_connection_cache()


# Generate arbitrary org ids as both UUID objects and their string form, since
# the loader accepts either.
_org_id_strategy = st.one_of(st.uuids(), st.uuids().map(str))


# ---------------------------------------------------------------------------
# Property 4 — unconfigured integration fails every operation with a message
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(org_id=_org_id_strategy)
def test_unconfigured_org_raises_and_humanizes(org_id):
    """No connection row => raises DocumensoNotConfiguredError that humanizes to
    a non-empty message with code ``integration_not_configured``."""
    # A fresh cache per example so the absence of a row is always re-read.
    invalidate_documenso_connection_cache()
    session = _FakeSession(row=None)

    with pytest.raises(DocumensoNotConfiguredError) as exc_info:
        asyncio.run(get_documenso_connection(session, org_id))

    humanized = humanize_esign_error(exc_info.value)

    # Code identifies the unconfigured integration (gates EVERY operation).
    assert humanized.code == CODE_INTEGRATION_NOT_CONFIGURED
    # Message is human-readable and never empty.
    assert isinstance(humanized.message, str)
    assert humanized.message.strip() != ""
    # And it never leaks the raw exception text.
    assert str(exc_info.value) != humanized.message


@settings(max_examples=200)
@given(org_id=st.uuids())
def test_humanized_message_is_stable_for_every_org(org_id):
    """The humanized unconfigured message is the same safe sentence regardless
    of which org attempted the (any) operation — including the connection test."""
    invalidate_documenso_connection_cache()
    session = _FakeSession(row=None)

    with pytest.raises(DocumensoNotConfiguredError) as exc_info:
        asyncio.run(get_documenso_connection(session, org_id))

    humanized = humanize_esign_error(exc_info.value)
    assert humanized.code == CODE_INTEGRATION_NOT_CONFIGURED
    assert humanized.message == documenso_unconfigured_message()


def documenso_unconfigured_message() -> str:
    """The canonical humanized message for an unconfigured integration."""
    from app.modules.esignatures.errors import ESIGN_ERROR_MESSAGES

    return ESIGN_ERROR_MESSAGES[CODE_INTEGRATION_NOT_CONFIGURED]
