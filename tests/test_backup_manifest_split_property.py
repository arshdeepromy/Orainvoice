"""Property-based test: manifest catalog leaks no customer structure.

# Feature: cloud-backup-restore, Property 13: Manifest catalog leaks no customer structure

**Validates: Requirements 7.2, 7.8**

For any generated set of contained organisations, File_Index path/org listings,
and Per_Org_Index per-org contents, the SERIALIZED manifest produced by
:func:`serialize_manifest` (``app/modules/backup_restore/backup/manifest.py``)
keeps the cleartext-catalog / encrypted-envelope split (Req 7.2, 7.8):

* **Catalog leaks nothing (Req 7.8).** The portion of the serialised document
  readable WITHOUT the Backup_Data_Key — the cleartext ``catalog`` object that
  :func:`read_catalog` exposes — contains NONE of the customer-identifying data:
  no organisation IDs, no File_Index ``file_key``/path, no owning ``org_id``, and
  no Per_Org_Index entity identifiers or export locations. The cleartext catalog
  exposes only the listing fields (backup id, timestamp, encrypted-artifact size,
  checksum, scope, and platform-wide file count/bytes aggregates).
* **Structure lives only in the envelope (Req 7.2).** Every customer-identifying
  value appears only inside the BDK-encrypted envelope and is recovered by
  :func:`deserialize_manifest` with the correct Backup_Data_Key, while a wrong
  Backup_Data_Key fails closed (no plaintext, ``ManifestError``).

Manifest building is pure logic, so nothing heavy is mocked: a fixed 32-byte
Backup_Data_Key drives the real :func:`backup_envelope_encrypt` envelope.
Organisation IDs, filenames, and entity identifiers are generated as UUIDs —
their hyphens are outside the base64 alphabet, so a leak into the catalog cannot
hide as an artefact of the ciphertext encoding.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.backup.manifest import (
    FileIndex,
    FileIndexEntry,
    ManifestError,
    PerOrgEntityCount,
    PerOrgIndex,
    PerOrgIndexEntry,
    build_manifest,
    deserialize_manifest,
    read_catalog,
    serialize_manifest,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations)
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# A fixed 32-byte Backup_Data_Key and a distinct wrong key. The test owns both,
# so the real envelope crypto runs without any settings-resolved secret.
_BDK = bytes(range(32))
_WRONG_BDK = bytes(range(1, 33))

_SCOPES = ["settings_only", "organisations_only", "both"]
_CATEGORIES = ["uploads", "compliance_files"]
_ENTITY_TYPES = ["invoices", "customers", "payments", "line_items", "vehicles"]

_uuid_str = st.uuids().map(str)


# ---------------------------------------------------------------------------
# Strategy: a full set of manifest inputs with real customer-identifying data
# ---------------------------------------------------------------------------


@st.composite
def manifest_inputs(draw):
    """Generate contained orgs + File_Index + Per_Org_Index referencing them."""
    org_ids = draw(st.lists(_uuid_str, min_size=1, max_size=4, unique=True))

    # File_Index entries: paths embed an org id (or an explicit global marker)
    # plus a uuid filename, exactly the structure-revealing fields of Req 7.2.
    n_files = draw(st.integers(min_value=0, max_value=6))
    entries: list[FileIndexEntry] = []
    for _ in range(n_files):
        org = draw(st.sampled_from([*org_ids, None]))
        filename = draw(_uuid_str)
        category = draw(st.sampled_from(_CATEGORIES))
        segment = "global" if org is None else org
        path = f"{category}/{segment}/{filename}"
        content_hash = hashlib.sha256(draw(st.binary(max_size=32))).hexdigest()
        byte_size = draw(st.integers(min_value=0, max_value=10_000))
        entries.append(
            FileIndexEntry(
                path=path,
                org_id=org,
                content_hash=content_hash,
                byte_size=byte_size,
            )
        )
    skipped_count = draw(st.integers(min_value=0, max_value=5))
    file_index = FileIndex(entries=entries, skipped_count=skipped_count)

    # Per_Org_Index: per-org entity identifiers + optional export location, all
    # customer-identifying contents that must live only in the envelope.
    per_entries: list[PerOrgIndexEntry] = []
    for org in org_ids:
        n_types = draw(st.integers(min_value=0, max_value=3))
        ents: list[PerOrgEntityCount] = []
        for _ in range(n_types):
            etype = draw(st.sampled_from(_ENTITY_TYPES))
            identifiers = draw(st.lists(_uuid_str, max_size=3, unique=True))
            ents.append(
                PerOrgEntityCount(
                    entity_type=etype,
                    record_count=len(identifiers),
                    identifiers=identifiers,
                )
            )
        emitted = draw(st.booleans())
        location = f"perorg/{org}/{draw(_uuid_str)}.dump" if emitted else None
        per_entries.append(
            PerOrgIndexEntry(
                org_id=org,
                entities=ents,
                logical_export_emitted=emitted,
                logical_export_location=location,
            )
        )
    per_org_index = PerOrgIndex(entries=per_entries)

    return {
        "backup_id": draw(_uuid_str),
        "created_at": draw(
            st.datetimes(
                min_value=datetime(2000, 1, 1),
                max_value=datetime(2100, 1, 1),
            )
        ),
        "scope": draw(st.sampled_from(_SCOPES)),
        "encrypted_dump": draw(st.binary(min_size=0, max_size=128)),
        "org_ids": org_ids,
        "file_index": file_index,
        "per_org_index": per_org_index,
        "app_version": draw(st.sampled_from(["1.13.0", "1.14.0", None])),
        "schema_version": draw(st.sampled_from(["0194", "0202", None])),
        "key_version": draw(st.sampled_from([1, 2, None])),
    }


def _sensitive_values(inputs: dict) -> set[str]:
    """All customer/organisation-identifying strings that must NOT leak."""
    values: set[str] = set(inputs["org_ids"])
    for entry in inputs["file_index"].entries:
        values.add(entry.path)
        if entry.org_id is not None:
            values.add(entry.org_id)
    for pe in inputs["per_org_index"].entries:
        values.add(pe.org_id)
        if pe.logical_export_location is not None:
            values.add(pe.logical_export_location)
        for ent in pe.entities:
            values.update(ent.identifiers)
    # Drop any empty strings — they are vacuously "contained" everywhere.
    return {v for v in values if v}


# ---------------------------------------------------------------------------
# Property 13: Manifest catalog leaks no customer structure
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(inputs=manifest_inputs())
def test_manifest_catalog_leaks_no_customer_structure(inputs: dict):
    """Cleartext catalog leaks nothing; envelope holds + recovers all structure.

    **Validates: Requirements 7.2, 7.8**
    """
    manifest = build_manifest(
        backup_id=inputs["backup_id"],
        created_at=inputs["created_at"],
        scope=inputs["scope"],
        encrypted_dump=inputs["encrypted_dump"],
        file_index=inputs["file_index"],
        per_org_index=inputs["per_org_index"],
        org_ids=inputs["org_ids"],
        app_version=inputs["app_version"],
        schema_version=inputs["schema_version"],
        key_version=inputs["key_version"],
    )
    raw = serialize_manifest(manifest, _BDK)
    sensitive = _sensitive_values(inputs)

    # -- Req 7.8: the cleartext portion (everything readable WITHOUT the BDK)
    # carries no organisation id, file path, or per-org identifier ------------
    document = json.loads(raw.decode("utf-8"))
    assert isinstance(document.get("envelope"), str), "envelope must be present"
    cleartext_view = {k: v for k, v in document.items() if k != "envelope"}
    cleartext_str = json.dumps(cleartext_view, sort_keys=True)
    for value in sensitive:
        assert value not in cleartext_str, (
            f"customer-identifying value leaked into cleartext catalog: {value!r}"
        )

    # read_catalog is the no-BDK listing path; it must expose only the catalog
    # fields and re-serialise to the same leak-free cleartext.
    catalog = read_catalog(raw)
    assert catalog.to_dict() == manifest.catalog.to_dict()
    catalog_str = json.dumps(catalog.to_dict(), sort_keys=True)
    for value in sensitive:
        assert value not in catalog_str

    # -- Req 7.2: the structure-revealing data is recoverable ONLY via the BDK
    recovered = deserialize_manifest(raw, _BDK)
    assert recovered.envelope.org_ids == inputs["org_ids"]
    assert recovered.envelope.file_index.to_dict() == inputs["file_index"].to_dict()
    assert (
        recovered.envelope.per_org_index.to_dict()
        == inputs["per_org_index"].to_dict()
    )
    # Every sensitive value reappears once decrypted — it was stored, not dropped.
    envelope_str = json.dumps(recovered.envelope.to_dict(), sort_keys=True)
    for value in sensitive:
        assert value in envelope_str

    # -- A wrong Backup_Data_Key fails closed: no plaintext, ManifestError -----
    with pytest.raises(ManifestError):
        deserialize_manifest(raw, _WRONG_BDK)
