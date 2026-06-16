"""Property-based test: data-residency notice derivation matches destination residency.

# Feature: cloud-backup-restore, Property 21: Data-residency notice derivation matches destination residency

**Validates: Requirements 20.2, 20.8, 20.9**

This property drives the real, pure residency functions in
``app/modules/backup_restore/residency.py``:

* ``derive_residency(provider_type, config)`` → ``offshore`` | ``onshore`` | ``unknown``
* ``build_disclosure_notice(provider_type, config)`` → :class:`ResidencyNotice`
* ``requires_acknowledgement(residency)`` → ``bool``

The generators construct ``(provider_type, config)`` pairs *by category* so the
**expected** residency is known by construction (rather than re-deriving it with
a parallel copy of the same logic). The categories cover every documented rule
in Req 20.8 / 20.9:

* explicit operator declarations (``residency`` / ``data_residency`` string, an
  ``onshore`` boolean, or a New-Zealand vs non-NZ ``country`` / ``location``)
  always override the provider derivation;
* ``google_drive`` / ``onedrive`` → offshore;
* ``s3`` with a New-Zealand region → onshore, with a declared non-NZ region →
  offshore, and with no region declared → unknown;
* ``nas`` with no onshore declaration → unknown;
* an unrecognised provider → unknown.

For every generated case the test asserts:

1. **Derivation matches the documented rule** — ``derive_residency`` equals the
   residency the category was constructed to produce (Req 20.8 / 20.9).
2. **Notice is consistent with the residency** — ``offshore_warning`` equals
   ``requires_acknowledgement`` equals ``requires_acknowledgement(residency)``
   equals ``residency in {offshore, unknown}`` (``unknown`` is treated as
   offshore — Req 20.9), so no first upload would proceed for an offshore /
   undeterminable destination without acknowledgement (Req 20.2), while an
   onshore destination shows no warning and needs no acknowledgement (Req 20.7 /
   20.8).
3. **Notice text reflects the residency** — an offshore / unknown notice carries
   the offshore-disclosure warning headline (and, for unknown, the
   "could not be reliably determined" statement), while an onshore notice states
   the offshore-disclosure warning does not apply.

These functions are pure, so no storage adapter or database is involved.
"""

from __future__ import annotations

from collections.abc import Mapping

from hypothesis import given, settings
from hypothesis import strategies as st

from app.modules.backup_restore.residency import (
    OFFSHORE,
    ONSHORE,
    UNKNOWN,
    build_disclosure_notice,
    derive_residency,
    requires_acknowledgement,
)

# ---------------------------------------------------------------------------
# Hypothesis settings (min 100 iterations) — pure in-memory, no I/O.
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(max_examples=300, deadline=None)

ALL_PROVIDERS = ["google_drive", "onedrive", "s3", "nas"]

# Values that resolve a region/country to New Zealand (onshore). Mix of region
# codes, the AWS Auckland region, an ``nz-*`` code, and free-text place names,
# with varied casing / spacing / separators.
NZ_VALUES = [
    "nz",
    "NZ",
    "Nz",
    "nzl",
    "NZL",
    "ap-southeast-6",
    "nz-north-1",
    "nz_auckland_1",
    "New Zealand",
    "new zealand",
    "new-zealand",
    "newzealand",
    "Auckland",
    "auckland",
    "Aotearoa",
    "AOTEAROA",
]

# Values that are clearly NOT New Zealand (offshore). Includes ``tanzania`` as an
# adversarial case (it contains the letters "nz" but is not a NZ token).
NON_NZ_VALUES = [
    "us-east-1",
    "us-west-2",
    "eu-west-1",
    "eu-central-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "United States",
    "Australia",
    "Sydney",
    "Germany",
    "France",
    "Singapore",
    "tanzania",
    "Tanzania",
]

# Noise keys that are NOT residency-relevant declarations, used to ensure the
# derivation ignores unrelated config and that explicit overrides still win.
_SAFE_NOISE_KEYS = ["bucket", "endpoint_url", "endpoint", "prefix", "addressing_style"]


def _noise(draw) -> dict:
    """Draw a small dict of residency-irrelevant config keys."""
    keys = draw(st.lists(st.sampled_from(_SAFE_NOISE_KEYS), unique=True, max_size=3))
    return {k: draw(st.text(min_size=1, max_size=8)) for k in keys}


@st.composite
def residency_cases(draw):
    """Generate ``{provider_type, config, expected}`` across every documented rule.

    ``expected`` is the residency the case was constructed to produce, so the
    test can assert ``derive_residency`` against a known answer rather than a
    parallel re-implementation.
    """
    category = draw(
        st.sampled_from(
            [
                "explicit_residency_str",
                "explicit_onshore_bool",
                "explicit_country_nz",
                "explicit_country_non_nz",
                "oauth_drive",
                "s3_nz_region",
                "s3_non_nz_region",
                "s3_no_region",
                "nas_undeclared",
                "unknown_provider",
            ]
        )
    )

    # --- explicit declarations: override any provider derivation ---
    if category == "explicit_residency_str":
        provider = draw(st.sampled_from(ALL_PROVIDERS))
        value = draw(st.sampled_from([OFFSHORE, ONSHORE, UNKNOWN]))
        # Tolerate surrounding whitespace / casing — the derivation normalises.
        decorated = draw(
            st.sampled_from([value, value.upper(), f"  {value}  ", value.title()])
        )
        key = draw(st.sampled_from(["residency", "data_residency"]))
        config = {**_noise(draw), key: decorated}
        return {"provider_type": provider, "config": config, "expected": value}

    if category == "explicit_onshore_bool":
        provider = draw(st.sampled_from(ALL_PROVIDERS))
        flag = draw(st.booleans())
        config = {**_noise(draw), "onshore": flag}
        return {
            "provider_type": provider,
            "config": config,
            "expected": ONSHORE if flag else OFFSHORE,
        }

    if category == "explicit_country_nz":
        provider = draw(st.sampled_from(ALL_PROVIDERS))
        key = draw(st.sampled_from(["country", "location"]))
        config = {**_noise(draw), key: draw(st.sampled_from(NZ_VALUES))}
        return {"provider_type": provider, "config": config, "expected": ONSHORE}

    if category == "explicit_country_non_nz":
        provider = draw(st.sampled_from(ALL_PROVIDERS))
        key = draw(st.sampled_from(["country", "location"]))
        config = {**_noise(draw), key: draw(st.sampled_from(NON_NZ_VALUES))}
        return {"provider_type": provider, "config": config, "expected": OFFSHORE}

    # --- provider-derived (no explicit declaration present) ---
    if category == "oauth_drive":
        provider = draw(st.sampled_from(["google_drive", "onedrive"]))
        return {"provider_type": provider, "config": _noise(draw), "expected": OFFSHORE}

    if category == "s3_nz_region":
        config = {**_noise(draw), "region": draw(st.sampled_from(NZ_VALUES))}
        return {"provider_type": "s3", "config": config, "expected": ONSHORE}

    if category == "s3_non_nz_region":
        config = {**_noise(draw), "region": draw(st.sampled_from(NON_NZ_VALUES))}
        return {"provider_type": "s3", "config": config, "expected": OFFSHORE}

    if category == "s3_no_region":
        # No declared region (e.g. self-hosted S3-compatible endpoint) -> unknown.
        return {"provider_type": "s3", "config": _noise(draw), "expected": UNKNOWN}

    if category == "nas_undeclared":
        # NAS with no onshore declaration -> physical location undeterminable.
        return {"provider_type": "nas", "config": _noise(draw), "expected": UNKNOWN}

    # category == "unknown_provider"
    provider = draw(
        st.sampled_from(["ftp", "dropbox", "box", "", "azure_blob", "gcs"])
    )
    return {"provider_type": provider, "config": _noise(draw), "expected": UNKNOWN}


# ---------------------------------------------------------------------------
# Property 21: Data-residency notice derivation matches destination residency
# ---------------------------------------------------------------------------


@PBT_SETTINGS
@given(case=residency_cases())
def test_residency_notice_matches_destination_residency(case):
    """Derivation matches the documented rules and the notice is consistent.

    **Validates: Requirements 20.2, 20.8, 20.9**
    """
    provider_type = case["provider_type"]
    config: Mapping = case["config"]
    expected = case["expected"]

    # 1. Derivation matches the documented rule (Req 20.8 / 20.9).
    residency = derive_residency(provider_type, config)
    assert residency == expected, (
        f"provider={provider_type!r} config={dict(config)!r}: "
        f"derived {residency!r}, expected {expected!r}"
    )

    notice = build_disclosure_notice(provider_type, config)

    # The notice derives the same residency when none is supplied.
    assert notice.residency == residency

    offshore_or_unknown = residency in (OFFSHORE, UNKNOWN)

    # 2. Notice consistency: warning == ack == requires_acknowledgement(r)
    #    == (residency in {offshore, unknown}) — unknown treated as offshore.
    assert notice.offshore_warning == offshore_or_unknown
    assert notice.requires_acknowledgement == offshore_or_unknown
    assert requires_acknowledgement(residency) == offshore_or_unknown
    assert notice.offshore_warning == notice.requires_acknowledgement

    # 3. Notice text reflects the residency.
    if residency == ONSHORE:
        # Onshore: no warning / no acknowledgement (Req 20.7 / 20.8).
        assert notice.offshore_warning is False
        assert notice.requires_acknowledgement is False
        assert "Onshore" in notice.headline
        assert "does not apply" in notice.body
    else:
        # Offshore or undeterminable: warning + acknowledgement (Req 20.2 / 20.9).
        assert notice.offshore_warning is True
        assert notice.requires_acknowledgement is True
        assert "Offshore" in notice.headline
        if residency == UNKNOWN:
            # Undeterminable residency is explicitly treated as offshore (Req 20.9).
            assert "could not be reliably determined" in notice.body

    # The full notice text always contains its component parts.
    assert notice.headline in notice.text
    assert notice.body in notice.text
    assert notice.biometric_notice in notice.text


@PBT_SETTINGS
@given(case=residency_cases())
def test_supplied_residency_is_honoured_by_notice(case):
    """When a residency is supplied to ``build_disclosure_notice`` it is used as-is.

    Guards the explicit-residency path the service uses (it derives once then
    passes the value in) so the notice never silently re-derives a different
    residency.

    **Validates: Requirements 20.8, 20.9**
    """
    provider_type = case["provider_type"]
    config = case["config"]

    for supplied in (OFFSHORE, ONSHORE, UNKNOWN):
        notice = build_disclosure_notice(provider_type, config, residency=supplied)
        assert notice.residency == supplied
        assert notice.requires_acknowledgement == (supplied in (OFFSHORE, UNKNOWN))
        assert notice.offshore_warning == notice.requires_acknowledgement
