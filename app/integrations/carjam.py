"""Carjam API client with Redis sliding-window rate limiting.

Provides async vehicle lookup by NZ registration plate via the Carjam API.
Rate limiting is enforced globally across the platform using a Redis
sliding-window counter, with the limit configurable by Global_Admin via
the ``integration_configs`` table (falls back to ``settings``).

Usage::

    from app.integrations.carjam import CarjamClient

    client = CarjamClient(redis=redis_pool)
    vehicle = await client.lookup_vehicle("ABC123")

Errors::

    CarjamError          — base error for all Carjam failures
    CarjamRateLimitError — platform-wide rate limit exceeded
    CarjamNotFoundError  — Carjam returned no result for the rego
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from redis.asyncio import Redis

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CarjamError(Exception):
    """Base exception for Carjam integration failures."""


class CarjamRateLimitError(CarjamError):
    """Raised when the platform-wide Carjam rate limit is exceeded."""

    def __init__(self, retry_after: int = 1) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Carjam rate limit exceeded — retry after {retry_after}s"
        )


class CarjamNotFoundError(CarjamError):
    """Raised when Carjam returns no data for the given registration."""

    def __init__(self, rego: str) -> None:
        self.rego = rego
        super().__init__(f"No Carjam result for rego '{rego}'")


class CarjamOwnerCheckValidationError(CarjamError):
    """Raised when CarJam rejects an owner_check call with
    ``err-owner-check-validation`` (missing / unrecognised type, missing
    plate, missing per-type fields, or invalid dob).

    The upstream ``message`` field describes the specific issue and is
    carried through verbatim so the API layer can surface it to the
    user.
    """


class CarjamOwnerCheckNotAllowedError(CarjamError):
    """Raised when the CarJam account is not subscribed to the
    ``owner_check`` API product (``err-api-product-not-allowed``).

    This is a platform-configuration problem (the org's CarJam key
    lacks the product), not user input, so it is surfaced distinctly
    from a validation error.
    """


# ---------------------------------------------------------------------------
# Vehicle data container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CarjamVehicleData:
    """Typed container for vehicle data returned by the Carjam API."""

    rego: str
    lookup_type: str = "basic"  # "basic" or "abcd"
    make: str | None = None
    model: str | None = None
    year: int | None = None
    colour: str | None = None
    body_type: str | None = None
    fuel_type: str | None = None
    engine_size: str | None = None
    seats: int | None = None
    wof_expiry: str | None = None
    rego_expiry: str | None = None
    odometer: int | None = None
    # Extended fields
    vin: str | None = None
    chassis: str | None = None
    engine_no: str | None = None
    transmission: str | None = None
    country_of_origin: str | None = None
    number_of_owners: int | None = None
    vehicle_type: str | None = None
    reported_stolen: str | None = None
    power_kw: int | None = None
    tare_weight: int | None = None
    gross_vehicle_mass: int | None = None
    date_first_registered_nz: str | None = None
    plate_type: str | None = None
    submodel: str | None = None
    second_colour: str | None = None
    # COF (Certificate of Fitness) fields
    cof_expiry: str | None = None
    inspection_type: str | None = None


# ---------------------------------------------------------------------------
# Rate limiter (sliding window via Redis sorted set)
# ---------------------------------------------------------------------------

_RATE_LIMIT_KEY = "carjam:global_rate_limit"
_RATE_LIMIT_WINDOW = 60  # seconds


async def _check_carjam_rate_limit(
    redis: Redis,
    limit: int,
) -> tuple[bool, int]:
    """Check the global Carjam rate limit using a sliding-window sorted set.

    Returns ``(allowed, retry_after_seconds)``.
    """
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW

    pipe = redis.pipeline()
    pipe.zremrangebyscore(_RATE_LIMIT_KEY, 0, window_start)
    pipe.zcard(_RATE_LIMIT_KEY)
    results = await pipe.execute()
    count: int = results[1]

    if count >= limit:
        oldest = await redis.zrange(
            _RATE_LIMIT_KEY, 0, 0, withscores=True,
        )
        if oldest:
            retry_after = int(oldest[0][1] + _RATE_LIMIT_WINDOW - now) + 1
        else:
            retry_after = 1
        return False, max(retry_after, 1)

    # Record this call.
    pipe2 = redis.pipeline()
    pipe2.zadd(_RATE_LIMIT_KEY, {f"{now}": now})
    pipe2.expire(_RATE_LIMIT_KEY, _RATE_LIMIT_WINDOW + 5)
    await pipe2.execute()

    return True, 0


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _derive_inspection_type(subject_to_wof: Any, subject_to_cof: Any) -> str | None:
    """Derive inspection type from CarJam subject_to_wof/cof flags."""
    if str(subject_to_cof).upper() == "Y":
        return "cof"
    if str(subject_to_wof).upper() == "Y":
        return "wof"
    return None


def _parse_vehicle_response(rego: str, data: dict[str, Any], lookup_type: str = "basic") -> CarjamVehicleData:
    """Extract vehicle fields from a Carjam regular API response dict.
    
    Regular API returns data in message.idh.vehicle format.
    """

    def _safe_int(val: Any) -> int | None:
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    def _safe_str(val: Any) -> str | None:
        """Convert value to string, handling None and empty values."""
        if val is None or val == "":
            return None
        return str(val)

    def _timestamp_to_date(val: Any) -> str | None:
        """Convert UNIX timestamp to ISO date string."""
        if val is None or val == "":
            return None
        try:
            import datetime
            ts = int(val)
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
            return dt.date().isoformat()
        except (ValueError, TypeError):
            return None

    # Parse COF expiry and log warning if present but unparseable
    raw_cof_expiry = data.get("expiry_date_of_last_successful_cof")
    parsed_cof_expiry = _timestamp_to_date(raw_cof_expiry)
    if raw_cof_expiry is not None and raw_cof_expiry != "" and parsed_cof_expiry is None:
        logger.warning(
            "Unparseable expiry_date_of_last_successful_cof value: %r for rego=%s",
            raw_cof_expiry,
            rego,
        )

    return CarjamVehicleData(
        rego=rego.upper().strip(),
        lookup_type=lookup_type,
        make=data.get("make"),
        model=data.get("model"),
        year=_safe_int(data.get("year_of_manufacture")),
        colour=data.get("main_colour"),
        body_type=data.get("body_style"),
        fuel_type=_safe_str(data.get("fuel_type")),
        engine_size=_safe_str(data.get("cc_rating")),
        seats=_safe_int(data.get("no_of_seats")),
        wof_expiry=_timestamp_to_date(data.get("expiry_date_of_last_successful_wof")),
        rego_expiry=_timestamp_to_date(data.get("licence_expiry_date")),
        odometer=_safe_int(data.get("latest_odometer_reading")),
        # Extended fields
        vin=_safe_str(data.get("vin")),
        chassis=_safe_str(data.get("chassis")),
        engine_no=_safe_str(data.get("engine_no")),
        transmission=_safe_str(data.get("transmission_type")),
        country_of_origin=_safe_str(data.get("country_of_origin")),
        number_of_owners=_safe_int(data.get("number_of_owners")),
        vehicle_type=_safe_str(data.get("vehicle_type")),
        reported_stolen=_safe_str(data.get("reported_stolen_nzta") or data.get("reported_stolen")),
        power_kw=_safe_int(data.get("power")),
        tare_weight=_safe_int(data.get("tare_weight")),
        gross_vehicle_mass=_safe_int(data.get("gross_vehicle_mass")),
        date_first_registered_nz=_timestamp_to_date(data.get("date_of_first_registration_in_nz")),
        plate_type=_safe_str(data.get("plate_type")),
        submodel=_safe_str(data.get("submodel")),
        second_colour=_safe_str(data.get("second_colour")),
        # COF (Certificate of Fitness) fields
        cof_expiry=parsed_cof_expiry,
        inspection_type=_derive_inspection_type(
            data.get("subject_to_wof"),
            data.get("subject_to_cof"),
        ),
    )


# ---------------------------------------------------------------------------
# PPSR response container + parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CarjamPpsrResponse:
    """Typed container for a CarJam PPSR response.

    Holds the structured fields parsed out of a CarJam PPSR/finance-status
    response (regardless of whether the upstream returned JSON or XML).

    Attributes
    ----------
    rego:
        Normalised registration plate (UPPER + stripped) the search ran against.
    not_found:
        ``True`` when CarJam reported no vehicle for the rego.
    basic:
        Basic vehicle details (the equivalent of the ``idh.vehicle`` block from
        ``lookup_vehicle``); ``None`` when ``include_basic=False`` or the
        upstream did not return ``idh``.
    ownership_history:
        Ordered list of prior owners (from ``ioh.owners``) when ``include_owners=True``.
    current_owner:
        Current-owner block (from ``ico``) when ``include_owner=True``.
    ppsr_summary:
        ``ppsr`` tag content — typically ``{"count": N, ...}``. Empty dict when absent.
    ppsr_details:
        Per-financing-statement entries from ``ppsr_details``. Empty list when absent.
    money_owing:
        ``money_owing`` block — ``{"match": "Y/PY/M/PM/U/N", "match_description": ..., "search_id": ...}``.
        Always present (empty dict when CarJam omits it).
    warnings:
        Compulsory recall / warning entries (when ``warnings=1``).
    flood:
        Flood / fire / write-off block (when ``fws=1``).
    charges_cents:
        Cost CarJam reported for this call (in cents NZD), if returned.
    raw_xml:
        The unaltered upstream response body. Field is named ``raw_xml`` for
        legacy compatibility with the original XML-era plan; in practice it
        holds whatever ``response.text`` was — typically JSON when ``f=json``.
    requested_options:
        The query-string parameters the call was issued with, for audit and
        reproducibility.
    """

    rego: str
    not_found: bool
    basic: dict | None
    ownership_history: list[dict] | None
    current_owner: dict | None
    ppsr_summary: dict
    ppsr_details: list[dict]
    money_owing: dict
    warnings: list[dict] | None
    flood: dict | None
    charges_cents: int | None
    raw_xml: str
    requested_options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CarjamOwnerCheckResponse:
    """Typed container for a CarJam ``owner_check`` response.

    The owner_check API product verifies supplied identity details
    against the current registered owner in the NZ Motor Vehicle
    Register and returns a boolean ``match`` flag.

    Attributes
    ----------
    rego:
        Normalised registration plate (UPPER + stripped) the check ran against.
    check_type:
        One of ``person_names`` / ``person_dl`` / ``company`` — echoed
        back by CarJam under ``owner_check.type``.
    match:
        ``True`` when the supplied details match the registered owner
        (CarJam ``match=1``), ``False`` otherwise (``match=0``).
    ref:
        CarJam reference id for the check (e.g. ``OC1A2B3C4D``).
    charges_cents:
        Cost CarJam reported for this call (in cents NZD), if returned.
    raw_response:
        The unaltered upstream response body (JSON when ``f=json``).
    requested_options:
        The query-string parameters the call was issued with (api_key
        redacted) for audit + reproducibility.
    """

    rego: str
    check_type: str
    match: bool
    ref: str | None
    charges_cents: int | None
    raw_response: str
    requested_options: dict = field(default_factory=dict)


def _xml_element_to_dict(elem: ET.Element) -> Any:
    """Convert an ``ElementTree`` element to a plain Python dict / list / str.

    Mirrors the structure CarJam uses when ``f=json`` is passed: nested tags
    become nested dicts; repeated child tags become lists. Text-only leaves
    return the stripped text.
    """
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        return text if text else None

    # Group children by tag — repeated tags become lists.
    grouped: dict[str, list[Any]] = {}
    for child in children:
        grouped.setdefault(child.tag, []).append(_xml_element_to_dict(child))

    out: dict[str, Any] = {}
    for tag, values in grouped.items():
        out[tag] = values[0] if len(values) == 1 else values
    return out


def _coerce_list(value: Any) -> list[dict]:
    """Coerce a single dict or a list-of-dict into a list-of-dict.

    CarJam's serialiser collapses single-item lists to a bare object in some
    responses; this helper keeps callers' code simple.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _coerce_int(value: Any) -> int | None:
    """Best-effort int coercion that returns ``None`` on failure."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _coerce_bool(value: Any) -> bool:
    """Best-effort bool coercion (``"true"``/``"1"``/``True`` → ``True``)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("true", "1", "yes", "y")


def _flatten_financing_statement(fs: dict) -> dict:
    """Flatten a deeply-nested CarJam financing statement into frontend-friendly keys.

    CarJam returns:
      fs.secured_party_details.secured_party[0].sp_organisation.name
      fs.collateral_details.collateral[0].type_description
      fs.fs_details.registered_date / expiry_date / status

    The frontend PpsrResultPanel reads:
      secured_party_name, collateral_description, registration_date, status
    """
    if not isinstance(fs, dict):
        return fs

    flat = dict(fs)  # keep all original keys too

    # Secured party name
    spd = fs.get("secured_party_details")
    if isinstance(spd, dict):
        parties = spd.get("secured_party")
        if isinstance(parties, list) and parties:
            sp = parties[0]
            org = sp.get("sp_organisation") if isinstance(sp, dict) else None
            if isinstance(org, dict):
                flat["secured_party_name"] = org.get("name", "")
            elif isinstance(sp, dict):
                flat["secured_party_name"] = sp.get("name", "")
        elif isinstance(parties, dict):
            org = parties.get("sp_organisation")
            if isinstance(org, dict):
                flat["secured_party_name"] = org.get("name", "")

    # Collateral description
    cd = fs.get("collateral_details")
    if isinstance(cd, dict):
        collaterals = cd.get("collateral")
        if isinstance(collaterals, list) and collaterals:
            c = collaterals[0]
            flat["collateral_description"] = c.get("type_description", "") if isinstance(c, dict) else ""
        elif isinstance(collaterals, dict):
            flat["collateral_description"] = collaterals.get("type_description", "")

    # Also check @attributes on the fs itself for motor_vehicle collateral
    if not flat.get("collateral_description"):
        mv = fs.get("motor_vehicle")
        if isinstance(mv, dict):
            attrs = mv.get("@attributes", mv)
            desc_parts = [attrs.get("make", ""), attrs.get("model", "")]
            flat["collateral_description"] = " ".join(p for p in desc_parts if p).strip() or "Motor vehicle"

    # Registration date + status from fs_details
    fsd = fs.get("fs_details")
    if isinstance(fsd, dict):
        flat["registration_date"] = fsd.get("registered_date", "")
        raw_status = fsd.get("status", "")
        # Map status codes: R=Registered, D=Discharged, etc.
        status_map = {"R": "Registered", "D": "Discharged", "E": "Expired", "S": "Subordinated"}
        flat["status"] = status_map.get(raw_status, raw_status)
        if not flat.get("registration_date"):
            flat["registration_date"] = fsd.get("expiry_date", "")

    # Fallback: if secured_party_name still empty, try @attributes pattern
    if not flat.get("secured_party_name"):
        attrs = fs.get("@attributes")
        if isinstance(attrs, dict):
            flat.setdefault("secured_party_name", attrs.get("secured_party", ""))
            flat.setdefault("registration_date", attrs.get("registered_date", ""))

    return flat


def _parse_ppsr_response(
    rego: str,
    body_text: str,
    requested_options: dict,
) -> CarjamPpsrResponse:
    """Parse a CarJam PPSR response body (JSON or XML) into a typed dataclass.

    CarJam returns JSON when ``f=json`` is set on the request, but the upstream
    has been observed to emit XML for some flag combinations. This parser tries
    JSON first and falls back to XML on parse failure (per design §4.1, G-CODE-13).

    Raises
    ------
    CarjamError
        When the response contains a top-level ``error`` key / ``<error>`` tag.
    """
    rego_norm = rego.strip().upper()

    # --- 1. Decode body into a dict ------------------------------------------------
    body: dict[str, Any] | None = None
    parse_error: Exception | None = None

    text = (body_text or "").strip()
    if text:
        # Try JSON first.
        try:
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                body = decoded
            else:
                parse_error = CarjamError("Carjam PPSR response was not a JSON object")
        except (ValueError, json.JSONDecodeError) as exc:
            parse_error = exc

        # Fall back to XML if JSON failed.
        if body is None:
            try:
                root = ET.fromstring(text)
            except ET.ParseError as exc:
                raise CarjamError(
                    f"Failed to parse Carjam PPSR response: {exc}"
                ) from parse_error or exc
            xml_dict = _xml_element_to_dict(root)
            if isinstance(xml_dict, dict):
                # Wrap under the root tag so downstream handling matches the
                # JSON layout (CarJam's JSON nests everything under ``message``).
                body = {root.tag: xml_dict} if root.tag != "message" else {"message": xml_dict}
            else:
                raise CarjamError("Carjam PPSR XML root had no children")
    else:
        raise CarjamError("Carjam PPSR response was empty")

    assert body is not None  # for type-checkers

    # --- 2. Top-level error -------------------------------------------------------
    # CarJam error responses come in two shapes:
    #   A) Nested: {"error": {"code": -1, "message": "...", "class": "wterror"}}
    #   B) Flat:   {"code": -1, "message": "Invalid API Key", "class": "wterror"}
    # Shape B is the actual production format when f=json is set. We must
    # detect both.
    if "error" in body and isinstance(body["error"], dict):
        err = body["error"]
        msg = err.get("message") or err.get("description") or "Unknown Carjam error"
        raise CarjamError(str(msg))

    # Flat error shape: top-level "class"=="wterror" or negative "code" with
    # a "message" field and NO "message" sub-dict (which would indicate a
    # successful response envelope).
    if (
        isinstance(body.get("class"), str)
        and body["class"] == "wterror"
        or (isinstance(body.get("code"), int) and body["code"] < 0)
    ):
        msg = body.get("message") or body.get("scode") or "Unknown Carjam error"
        # Don't confuse a flat error with a successful response that happens
        # to have a "message" key containing a dict (the success envelope).
        if not isinstance(msg, dict):
            raise CarjamError(str(msg))

    # CarJam wraps content under ``message`` when ``f=json``; XML root is
    # ``<message>`` so we already normalised that above.
    container = body.get("message") if isinstance(body.get("message"), dict) else body

    # Errors may also live inside the ``message`` envelope when CarJam returns
    # XML wrapped in ``<message><error>...</error></message>``.
    if isinstance(container, dict) and isinstance(container.get("error"), dict):
        err = container["error"]
        msg = err.get("message") or err.get("description") or "Unknown Carjam error"
        raise CarjamError(str(msg))

    # --- 3. not_found indicator ---------------------------------------------------
    not_found = False
    idh = container.get("idh") if isinstance(container, dict) else None
    if isinstance(idh, dict):
        header = idh.get("header")
        if isinstance(header, dict) and _coerce_bool(header.get("not_found")):
            not_found = True
    if not not_found and isinstance(container, dict):
        # XML form: <not_found>true</not_found> at top-level message.
        if _coerce_bool(container.get("not_found")):
            not_found = True

    # --- 4. basic (idh.vehicle) ---------------------------------------------------
    basic: dict | None = None
    if isinstance(idh, dict):
        vehicle = idh.get("vehicle")
        if isinstance(vehicle, dict) and vehicle:
            # Reuse the existing parser to keep field-name parity with
            # lookup_vehicle. Convert dataclass back to dict for storage.
            try:
                vd = _parse_vehicle_response(rego_norm, vehicle, lookup_type="basic")
                basic = {
                    k: v
                    for k, v in vd.__dict__.items()
                    if v is not None or k in ("rego", "lookup_type")
                }
            except Exception:
                # Fall back to the raw vehicle dict if the structured parser
                # chokes on an unexpected shape — never fail the whole PPSR
                # parse on a basic-block parse error.
                basic = dict(vehicle)

    # --- 5. ownership_history (ioh.owners) ----------------------------------------
    ownership_history: list[dict] | None = None
    ioh = container.get("ioh") if isinstance(container, dict) else None
    if isinstance(ioh, dict):
        owners = ioh.get("owners")
        if isinstance(owners, dict):
            # XML/JSON variant: owners → owner → [list]
            inner = owners.get("owner")
            ownership_history = _coerce_list(inner)
        elif isinstance(owners, list):
            ownership_history = _coerce_list(owners)

    # --- 6. current_owner (ico) ---------------------------------------------------
    ico = container.get("ico") if isinstance(container, dict) else None
    current_owner: dict | None = ico if isinstance(ico, dict) and ico else None

    # --- 7. ppsr_summary + ppsr_details -------------------------------------------
    ppsr_summary_raw = container.get("ppsr") if isinstance(container, dict) else None
    ppsr_summary: dict = ppsr_summary_raw if isinstance(ppsr_summary_raw, dict) else {}

    ppsr_details_raw = container.get("ppsr_details") if isinstance(container, dict) else None
    if isinstance(ppsr_details_raw, dict):
        # Wrapper element — pull out the inner statement list.
        # CarJam returns: ppsr_details.search_details_result.finance_statement[...]
        inner = (
            ppsr_details_raw.get("financing_statement")
            or ppsr_details_raw.get("statement")
            or ppsr_details_raw.get("item")
            or ppsr_details_raw.get("finance_statement")
        )
        # Also check the nested search_details_result wrapper (real prod format).
        if inner is None:
            sdr = ppsr_details_raw.get("search_details_result")
            if isinstance(sdr, dict):
                inner = sdr.get("finance_statement") or sdr.get("financing_statement")
        if inner is not None:
            ppsr_details = _coerce_list(inner)
        elif ppsr_details_raw:
            # Single non-empty statement dict (no wrapper key).
            ppsr_details = [ppsr_details_raw]
        else:
            # Empty wrapper — no statements.
            ppsr_details = []
    elif isinstance(ppsr_details_raw, list):
        # CarJam can return ppsr_details as a list (one entry per plate when ppsrh=1).
        # Each entry may be a wrapper: {"search_details_result": {"finance_statement": [...]}}
        # or a direct financing statement dict.
        ppsr_details = []
        for item in ppsr_details_raw:
            if isinstance(item, dict):
                sdr = item.get("search_details_result")
                if isinstance(sdr, dict):
                    fs = sdr.get("finance_statement") or sdr.get("financing_statement")
                    ppsr_details.extend(_coerce_list(fs))
                else:
                    ppsr_details.append(item)
    else:
        ppsr_details = []

    # Flatten each financing statement into the field names the frontend expects.
    # CarJam nests data under secured_party_details.secured_party[0].sp_organisation.name
    # but the frontend reads flat keys like "secured_party_name", "collateral_description", etc.
    ppsr_details = [_flatten_financing_statement(fs) for fs in ppsr_details]

    # --- 8. money_owing -----------------------------------------------------------
    money_owing_raw = container.get("money_owing") if isinstance(container, dict) else None
    money_owing: dict = {}
    if isinstance(money_owing_raw, dict):
        money_owing = {
            "match": money_owing_raw.get("match"),
            "match_description": money_owing_raw.get("match_description"),
            "search_id": money_owing_raw.get("search_id"),
        }

    # --- 9. warnings --------------------------------------------------------------
    warnings_raw = container.get("warnings") if isinstance(container, dict) else None
    warnings: list[dict] | None = None
    if isinstance(warnings_raw, dict):
        inner = warnings_raw.get("warning") or warnings_raw.get("item")
        if inner is not None:
            warnings = _coerce_list(inner)
        elif warnings_raw:
            warnings = [warnings_raw]
    elif isinstance(warnings_raw, list):
        warnings = _coerce_list(warnings_raw)

    # --- 10. flood ----------------------------------------------------------------
    flood_raw = container.get("flood") if isinstance(container, dict) else None
    flood: dict | None = flood_raw if isinstance(flood_raw, dict) and flood_raw else None

    # --- 11. charges --------------------------------------------------------------
    charges_cents: int | None = None
    charges_raw = container.get("charges") if isinstance(container, dict) else None
    if isinstance(charges_raw, dict):
        charges_cents = _coerce_int(charges_raw.get("cents"))

    return CarjamPpsrResponse(
        rego=rego_norm,
        not_found=not_found,
        basic=basic,
        ownership_history=ownership_history,
        current_owner=current_owner,
        ppsr_summary=ppsr_summary,
        ppsr_details=ppsr_details,
        money_owing=money_owing,
        warnings=warnings,
        flood=flood,
        charges_cents=charges_cents,
        raw_xml=body_text,
        requested_options=dict(requested_options or {}),
    )


def _parse_owner_check_response(
    rego: str,
    body_text: str,
    requested_options: dict,
) -> CarjamOwnerCheckResponse:
    """Parse a CarJam ``owner_check`` response body (JSON or XML).

    CarJam returns JSON when ``f=json`` is set; the XML fallback mirrors
    ``_parse_ppsr_response``. The success envelope wraps the payload
    under ``owner_check`` (optionally nested under ``message`` for XML).

    Raises
    ------
    CarjamOwnerCheckValidationError
        On ``err-owner-check-validation`` (carries the upstream message).
    CarjamOwnerCheckNotAllowedError
        On ``err-api-product-not-allowed``.
    CarjamError
        On any other top-level error or a malformed / empty response.
    """

    rego_norm = rego.strip().upper()

    # --- 1. Decode body into a dict ------------------------------------------------
    body: dict[str, Any] | None = None
    parse_error: Exception | None = None

    text = (body_text or "").strip()
    if not text:
        raise CarjamError("Carjam owner_check response was empty")

    try:
        decoded = json.loads(text)
        if isinstance(decoded, dict):
            body = decoded
        else:
            parse_error = CarjamError("Carjam owner_check response was not a JSON object")
    except (ValueError, json.JSONDecodeError) as exc:
        parse_error = exc

    if body is None:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise CarjamError(
                f"Failed to parse Carjam owner_check response: {exc}"
            ) from parse_error or exc
        xml_dict = _xml_element_to_dict(root)
        if isinstance(xml_dict, dict):
            body = (
                {root.tag: xml_dict}
                if root.tag != "message"
                else {"message": xml_dict}
            )
        else:
            raise CarjamError("Carjam owner_check XML root had no children")

    assert body is not None  # for type-checkers

    # --- 2. Error detection -------------------------------------------------------
    # CarJam error shapes (per the owner_check guide):
    #   Nested: {"error": {"code": -1, "scode": "...", "message": "..."}}
    #   Flat:   {"code": -1, "scode": "err-...", "message": "...", "class": "apperror"}
    def _raise_for_error(err: dict) -> None:
        scode = str(err.get("scode") or "")
        msg = err.get("message") or err.get("description") or scode or "Unknown Carjam error"
        if scode == "err-owner-check-validation":
            raise CarjamOwnerCheckValidationError(str(msg))
        if scode == "err-api-product-not-allowed":
            raise CarjamOwnerCheckNotAllowedError(str(msg))
        if not isinstance(msg, dict):
            raise CarjamError(str(msg))

    if isinstance(body.get("error"), dict):
        _raise_for_error(body["error"])

    is_flat_error = (
        (isinstance(body.get("class"), str) and body["class"] == "apperror")
        or (isinstance(body.get("code"), int) and body["code"] < 0)
    )
    if is_flat_error and not isinstance(body.get("owner_check"), dict):
        _raise_for_error(body)

    # CarJam wraps content under ``message`` when returning XML.
    container = body.get("message") if isinstance(body.get("message"), dict) else body
    if isinstance(container, dict) and isinstance(container.get("error"), dict):
        _raise_for_error(container["error"])

    # --- 3. owner_check payload ---------------------------------------------------
    oc = container.get("owner_check") if isinstance(container, dict) else None
    if not isinstance(oc, dict):
        raise CarjamError("Carjam owner_check response missing owner_check block")

    match_val = oc.get("match")
    match = _coerce_bool(match_val) or str(match_val).strip() == "1"
    ref = oc.get("ref")
    check_type = str(oc.get("type") or requested_options.get("type") or "")

    # --- 4. charges ---------------------------------------------------------------
    charges_cents: int | None = None
    charges_raw = container.get("charges") if isinstance(container, dict) else None
    if isinstance(charges_raw, dict):
        charges_cents = _coerce_int(charges_raw.get("cents"))

    return CarjamOwnerCheckResponse(
        rego=rego_norm,
        check_type=check_type,
        match=bool(match),
        ref=str(ref) if ref else None,
        charges_cents=charges_cents,
        raw_response=body_text,
        requested_options=dict(requested_options or {}),
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 10.0  # seconds


class CarjamClient:
    """Async Carjam API client with Redis-backed global rate limiting.

    Parameters
    ----------
    redis:
        An ``redis.asyncio.Redis`` instance for rate limiting.
    api_key:
        Carjam API key.  Falls back to ``settings.carjam_api_key``.
    base_url:
        Carjam base URL.  Falls back to ``settings.carjam_base_url``.
    rate_limit:
        Maximum Carjam API calls per minute (platform-wide).
        Falls back to ``settings.carjam_global_rate_limit_per_minute``.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        rate_limit: int | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._redis = redis
        self._api_key = api_key or settings.carjam_api_key
        self._base_url = self._normalize_base_url(
            base_url or settings.carjam_base_url
        )
        self._rate_limit = rate_limit or settings.carjam_global_rate_limit_per_minute
        self._timeout = timeout

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        """Normalize the CarJam base URL to the correct production domain.

        Handles common misconfigurations like ``api.carjam.co.nz`` (which
        301-redirects and drops query params) by rewriting to the canonical
        ``www.carjam.co.nz`` domain.
        """
        url = url.rstrip("/")
        # api.carjam.co.nz redirects to www.carjam.co.nz — fix it upfront
        url = url.replace("://api.carjam.co.nz", "://www.carjam.co.nz")
        return url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def lookup_vehicle(self, rego: str) -> CarjamVehicleData:
        """Look up a vehicle by NZ registration plate.

        Enforces the global rate limit before making the HTTP call.

        Raises
        ------
        CarjamRateLimitError
            If the platform-wide rate limit has been exceeded.
        CarjamNotFoundError
            If Carjam returns no data for the registration.
        CarjamError
            On any other HTTP or parsing failure.
        """
        rego = rego.upper().strip()
        if not rego:
            raise CarjamError("Registration plate cannot be empty")

        # --- Rate limit check ---
        allowed, retry_after = await _check_carjam_rate_limit(
            self._redis, self._rate_limit,
        )
        if not allowed:
            logger.warning(
                "Carjam global rate limit hit (%d/min) — retry after %ds",
                self._rate_limit,
                retry_after,
            )
            raise CarjamRateLimitError(retry_after=retry_after)

        # --- HTTP call ---
        # Carjam regular API endpoint: /api/car/
        url = f"{self._base_url}/api/car/"
        params = {
            "key": self._api_key,
            "plate": rego,
            "basic": "1",
            "f": "json",  # Request JSON format instead of XML
        }

        logger.info(f"Carjam API call: URL={url}, params={params}")

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as http:
                response = await http.get(url, params=params)
                logger.info(
                    "Carjam API response: status=%d, final_url=%s, history=%s",
                    response.status_code,
                    response.url,
                    [r.status_code for r in response.history] if response.history else "no redirects",
                )
        except httpx.TimeoutException:
            logger.error("Carjam API timeout for rego=%s", rego)
            raise CarjamError(f"Carjam API timed out for rego '{rego}'")
        except httpx.HTTPError as exc:
            logger.error("Carjam HTTP error for rego=%s: %s", rego, exc)
            raise CarjamError(f"Carjam HTTP error: {exc}") from exc

        # --- Handle response status ---
        if response.status_code == 404:
            logger.warning("Carjam 404 for rego=%s, final_url=%s", rego, response.url)
            raise CarjamNotFoundError(rego)

        if response.status_code == 429:
            # Carjam's own rate limit (distinct from our platform limit).
            retry_hdr = response.headers.get("Retry-After", "60")
            try:
                retry_secs = int(retry_hdr)
            except ValueError:
                retry_secs = 60
            logger.warning(
                "Carjam API returned 429 for rego=%s — retry after %ds",
                rego,
                retry_secs,
            )
            raise CarjamRateLimitError(retry_after=retry_secs)

        if response.status_code != 200:
            logger.error(
                "Carjam API unexpected status %d for rego=%s: %s",
                response.status_code,
                rego,
                response.text[:500],
            )
            raise CarjamError(
                f"Carjam API returned status {response.status_code}"
            )

        # --- Parse response ---
        try:
            body = response.json()
        except Exception as exc:
            raise CarjamError("Failed to parse Carjam response JSON") from exc

        # Check for error response (has "error" key)
        if "error" in body:
            error_data = body["error"]
            error_code = error_data.get("code", "unknown")
            error_msg = error_data.get("message", "Unknown Carjam error")
            logger.error("Carjam API error for rego=%s: [%s] %s", rego, error_code, error_msg)
            
            # Check if it's a "not found" type error
            if "not found" in error_msg.lower():
                raise CarjamNotFoundError(rego)
            
            raise CarjamError(f"Carjam API error: {error_msg}")

        # JSON format: may return {'message': {'idh': {...}}} or {'idh': {...}}
        # Check both structures
        if "message" in body and isinstance(body["message"], dict):
            container = body["message"]
        elif "idh" in body:
            container = body
        else:
            logger.warning("Carjam response missing 'idh' for rego=%s, body keys=%s", rego, list(body.keys()) if isinstance(body, dict) else type(body))
            raise CarjamNotFoundError(rego)
        
        if "idh" not in container:
            logger.warning("Carjam container missing 'idh' for rego=%s, keys=%s", rego, list(container.keys()))
            raise CarjamNotFoundError(rego)

        idh_data = container["idh"]
        
        if "vehicle" not in idh_data:
            logger.warning("Carjam 'idh' missing 'vehicle' for rego=%s, idh keys=%s", rego, list(idh_data.keys()) if isinstance(idh_data, dict) else type(idh_data))
            raise CarjamNotFoundError(rego)

        vehicle_data = idh_data["vehicle"]
        
        # Check if vehicle has basic data
        if not vehicle_data.get("make"):
            raise CarjamNotFoundError(rego)

        return _parse_vehicle_response(rego, vehicle_data, lookup_type="basic")

    async def lookup_vehicle_abcd(self, rego: str, use_mvr: bool = True) -> CarjamVehicleData:
        """Look up a vehicle using ABCD (Absolute Basic Car Details) API.
        
        This is a lower-cost API option that provides basic vehicle information.
        
        Parameters
        ----------
        rego:
            Vehicle registration plate, VIN, or chassis number
        use_mvr:
            If True (default), allows fetching from Motor Vehicle Register if CarJam
            doesn't have data internally. If False, only uses CarJam's internal data.
            Note: MVR access adds 17c NZD to the API call cost.
        
        Raises
        ------
        CarjamRateLimitError
            If the platform-wide rate limit has been exceeded.
        CarjamNotFoundError
            If Carjam returns no data for the registration.
        CarjamError
            On any other HTTP or parsing failure.
        """
        rego = rego.upper().strip()
        if not rego:
            raise CarjamError("Registration plate cannot be empty")

        # --- Rate limit check ---
        allowed, retry_after = await _check_carjam_rate_limit(
            self._redis, self._rate_limit,
        )
        if not allowed:
            logger.warning(
                "Carjam global rate limit hit (%d/min) — retry after %ds",
                self._rate_limit,
                retry_after,
            )
            raise CarjamRateLimitError(retry_after=retry_after)

        # --- HTTP call ---
        # Carjam ABCD API endpoint: /a/vehicle:abcd
        url = f"{self._base_url}/a/vehicle:abcd"
        params = {
            "key": self._api_key,
            "plate": rego,
            "mvr": "1" if use_mvr else "0",
        }

        logger.info(f"Carjam ABCD API call: URL={url}, plate={rego}, mvr={use_mvr}")

        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as http:
                response = await http.get(url, params=params)
                logger.info(f"Carjam ABCD API response: status={response.status_code}")
                
                # Check for Refresh header (data is being fetched)
                refresh_header = response.headers.get("Refresh")
                if refresh_header:
                    logger.info(f"Carjam ABCD: Data being fetched, refresh in {refresh_header}s")
                    raise CarjamError(f"Carjam is fetching data, retry in {refresh_header} seconds")
                    
        except httpx.TimeoutException:
            logger.error("Carjam ABCD API timeout for rego=%s", rego)
            raise CarjamError(f"Carjam ABCD API timed out for rego '{rego}'")
        except httpx.HTTPError as exc:
            logger.error("Carjam ABCD HTTP error for rego=%s: %s", rego, exc)
            raise CarjamError(f"Carjam ABCD HTTP error: {exc}") from exc

        # --- Handle response status ---
        if response.status_code == 404:
            raise CarjamNotFoundError(rego)

        if response.status_code == 429:
            retry_hdr = response.headers.get("Retry-After", "60")
            try:
                retry_secs = int(retry_hdr)
            except ValueError:
                retry_secs = 60
            logger.warning(
                "Carjam ABCD API returned 429 for rego=%s — retry after %ds",
                rego,
                retry_secs,
            )
            raise CarjamRateLimitError(retry_after=retry_secs)

        if response.status_code != 200:
            logger.error(
                "Carjam ABCD API unexpected status %d for rego=%s: %s",
                response.status_code,
                rego,
                response.text[:500],
            )
            raise CarjamError(
                f"Carjam ABCD API returned status {response.status_code}"
            )

        # --- Parse response ---
        try:
            body = response.json()
        except Exception as exc:
            raise CarjamError("Failed to parse Carjam ABCD response JSON") from exc

        # Check for error response
        if "code" in body and "message" in body:
            error_code = body.get("code")
            error_msg = body.get("message", "Unknown Carjam error")
            logger.error("Carjam ABCD API error for rego=%s: [%s] %s", rego, error_code, error_msg)
            raise CarjamError(f"Carjam ABCD API error: {error_msg}")

        # Check for null response (data not ready yet)
        if body is None or (isinstance(body, dict) and not body):
            logger.info(f"Carjam ABCD: Null response for {rego}, data not ready")
            # Return a special response indicating data is being fetched
            raise CarjamError("ABCD_FETCHING")

        # Check if we have basic required fields
        if not body.get("make"):
            raise CarjamNotFoundError(rego)

        return _parse_vehicle_response(rego, body, lookup_type="abcd")

    async def lookup_ppsr(
        self,
        rego: str,
        *,
        include_basic: bool = True,
        include_owners: bool = False,
        include_owner: bool = False,
        include_warnings: bool = True,
        include_fws: bool = False,
        check_hidden_plates: bool = False,
        s241_purpose: str | None = None,
        translate: bool = True,
        use_cache: int | str | None = None,
    ) -> CarjamPpsrResponse:
        """Run a PPSR (Personal Property Securities Register) check via CarJam.

        Reuses the same rate-limited HTTP path as ``lookup_vehicle``; PPSR
        searches count against the platform-wide CarJam budget.

        Parameters
        ----------
        rego:
            NZ registration plate. Normalised to UPPER + stripped.
        include_basic:
            Sends ``basic=1`` so the response includes ``idh.vehicle`` (default ``True``).
        include_owners:
            Sends ``owners=1``. Requires ``s241_purpose`` to be set.
        include_owner:
            Sends ``owner=1``. Requires ``s241_purpose`` to be set.
        include_warnings:
            Sends ``warnings=1`` (default ``True``).
        include_fws:
            Sends ``fws=1`` (fire / water / write-off).
        check_hidden_plates:
            Sends ``ppsrh=1``. Charged at a higher rate by CarJam.
        s241_purpose:
            s241 authorisation reason — required when ``include_owners``
            or ``include_owner`` is true.
        translate:
            Sends ``translate=1`` so the response includes human-readable
            ``hidh``/``hioh``/``hico``/``hirh`` blocks.
        use_cache:
            Maps to CarJam's ``cache`` parameter (``0`` = no cache, ``1`` =
            default 10 years, or a ``strtotime`` string like ``-1 month``).

        Raises
        ------
        ValueError
            When owner / ownership-history is requested without ``s241_purpose``.
        CarjamRateLimitError
            When the platform-wide CarJam rate limit is exhausted.
        CarjamError
            On upstream errors, parse failures, or HTTP non-2xx responses.
        """
        if (include_owners or include_owner) and not s241_purpose:
            raise ValueError(
                "s241_purpose required when include_owners or include_owner is true"
            )

        rego_norm = rego.strip().upper()
        if not rego_norm:
            raise CarjamError("Registration plate cannot be empty")

        # --- Rate limit check (G-CODE-14: tuple unpack) ---
        allowed, retry_after = await _check_carjam_rate_limit(
            self._redis, self._rate_limit,
        )
        if not allowed:
            logger.warning(
                "Carjam global rate limit hit (%d/min) — retry after %ds",
                self._rate_limit,
                retry_after,
            )
            raise CarjamRateLimitError(retry_after=retry_after)

        # --- Build query-string parameters ---
        params: dict[str, str] = {
            "key": self._api_key,
            "plate": rego_norm,
            "basic": "1" if include_basic else "0",
            "ppsr": "1",
            "f": "json",
            "charges": "1",
        }
        if include_owners:
            params["owners"] = "1"
        if include_owner:
            params["owner"] = "1"
        if include_warnings:
            params["warnings"] = "1"
        if include_fws:
            params["fws"] = "1"
        if check_hidden_plates:
            params["ppsrh"] = "1"
        if s241_purpose:
            params["s241_purpose"] = s241_purpose
        if translate:
            params["translate"] = "1"
        if use_cache is not None:
            params["cache"] = str(use_cache)

        # --- HTTP call (same path as lookup_vehicle per G-CODE-13) ---
        url = f"{self._base_url}/api/car/"

        # Avoid logging the api_key.
        log_params = {k: ("<redacted>" if k == "key" else v) for k, v in params.items()}
        logger.info("Carjam PPSR API call: URL=%s, params=%s", url, log_params)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True,
            ) as http:
                response = await http.get(url, params=params)
                logger.info(
                    "Carjam PPSR API response: status=%d, final_url=%s",
                    response.status_code,
                    response.url,
                )
        except httpx.TimeoutException:
            logger.error("Carjam PPSR API timeout for rego=%s", rego_norm)
            raise CarjamError(
                f"Carjam PPSR API timed out for rego '{rego_norm}'"
            )
        except httpx.HTTPError as exc:
            logger.error("Carjam PPSR HTTP error for rego=%s: %s", rego_norm, exc)
            raise CarjamError(f"Carjam PPSR HTTP error: {exc}") from exc

        # --- Handle response status ---
        if response.status_code == 404:
            raise CarjamNotFoundError(rego_norm)

        if response.status_code == 429:
            retry_hdr = response.headers.get("Retry-After", "60")
            try:
                retry_secs = int(retry_hdr)
            except ValueError:
                retry_secs = 60
            logger.warning(
                "Carjam PPSR API returned 429 for rego=%s — retry after %ds",
                rego_norm,
                retry_secs,
            )
            raise CarjamRateLimitError(retry_after=retry_secs)

        if response.status_code != 200:
            logger.error(
                "Carjam PPSR API unexpected status %d for rego=%s: %s",
                response.status_code,
                rego_norm,
                response.text[:500],
            )
            raise CarjamError(
                f"Carjam PPSR API returned status {response.status_code}"
            )

        body_text = response.text
        # Redact the api_key from the params we record on the response so the
        # raw_xml/requested_options blob is safe to persist.
        recorded_options = {
            k: ("<redacted>" if k == "key" else v) for k, v in params.items()
        }
        return _parse_ppsr_response(rego_norm, body_text, recorded_options)

    async def lookup_owner_check(
        self,
        rego: str,
        *,
        check_type: str,
        last_name: str | None = None,
        first_name: str | None = None,
        dob: str | None = None,
        driver_licence: str | None = None,
        company_name: str | None = None,
    ) -> CarjamOwnerCheckResponse:
        """Run a CarJam ``owner_check`` — verify supplied identity details
        against the current registered owner in the NZ MVR.

        Reuses the same rate-limited HTTP path as :meth:`lookup_ppsr`;
        owner_check calls count against the platform-wide CarJam budget
        and are charged at the ``owner_check`` API product price.

        Parameters
        ----------
        rego:
            NZ registration plate or VIN. Normalised to UPPER + stripped.
        check_type:
            One of ``person_names`` / ``person_dl`` / ``company``.
        last_name / first_name / dob:
            For ``person_names`` — ``last_name`` required; one of
            ``first_name`` / ``dob`` required. ``dob`` is any
            ``strtotime``-compatible value (``YYYY-MM-DD`` works).
        driver_licence:
            For ``person_dl`` — NZ driver licence number (required).
        company_name:
            For ``company`` — company name (required).

        Raises
        ------
        ValueError
            When required per-type fields are missing (pre-flight guard).
        CarjamRateLimitError
            When the platform-wide CarJam rate limit is exhausted.
        CarjamOwnerCheckValidationError
            When CarJam rejects the inputs (``err-owner-check-validation``).
        CarjamOwnerCheckNotAllowedError
            When the account lacks the ``owner_check`` API product.
        CarjamError
            On other upstream errors / parse failures / non-2xx responses.
        """

        normalised_type = (check_type or "").strip().lower()
        if normalised_type not in {"person_names", "person_dl", "company"}:
            raise ValueError(
                "check_type must be one of person_names / person_dl / company",
            )

        rego_norm = rego.strip().upper()
        if not rego_norm:
            raise CarjamError("Registration plate cannot be empty")

        # --- Pre-flight per-type field validation (mirror CarJam rules) ---
        per_type: dict[str, str] = {}
        if normalised_type == "person_names":
            ln = (last_name or "").strip()
            fn = (first_name or "").strip()
            db_val = (dob or "").strip()
            if not ln:
                raise ValueError("last_name is required for person_names")
            if not fn and not db_val:
                raise ValueError(
                    "first_name or dob is required for person_names",
                )
            per_type["last_name"] = ln
            if fn:
                per_type["first_name"] = fn
            if db_val:
                per_type["dob"] = db_val
        elif normalised_type == "person_dl":
            dl = (driver_licence or "").strip()
            if not dl:
                raise ValueError("driver_licence is required for person_dl")
            per_type["driver_licence"] = dl
        else:  # company
            cn = (company_name or "").strip()
            if not cn:
                raise ValueError("company_name is required for company")
            per_type["company_name"] = cn

        # --- Rate limit check ---
        allowed, retry_after = await _check_carjam_rate_limit(
            self._redis, self._rate_limit,
        )
        if not allowed:
            logger.warning(
                "Carjam global rate limit hit (%d/min) — retry after %ds",
                self._rate_limit,
                retry_after,
            )
            raise CarjamRateLimitError(retry_after=retry_after)

        # --- Build query-string parameters ---
        params: dict[str, str] = {
            "key": self._api_key,
            "f": "json",
            "type": normalised_type,
            "plate": rego_norm,
            "charges": "1",
            **per_type,
        }

        url = f"{self._base_url}/api/car/"
        log_params = {k: ("<redacted>" if k == "key" else v) for k, v in params.items()}
        logger.info("Carjam owner_check API call: URL=%s, params=%s", url, log_params)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, follow_redirects=True,
            ) as http:
                response = await http.get(url, params=params)
                logger.info(
                    "Carjam owner_check API response: status=%d, final_url=%s",
                    response.status_code,
                    response.url,
                )
        except httpx.TimeoutException:
            logger.error("Carjam owner_check API timeout for rego=%s", rego_norm)
            raise CarjamError(
                f"Carjam owner_check API timed out for rego '{rego_norm}'"
            )
        except httpx.HTTPError as exc:
            logger.error("Carjam owner_check HTTP error for rego=%s: %s", rego_norm, exc)
            raise CarjamError(f"Carjam owner_check HTTP error: {exc}") from exc

        if response.status_code == 429:
            retry_hdr = response.headers.get("Retry-After", "60")
            try:
                retry_secs = int(retry_hdr)
            except ValueError:
                retry_secs = 60
            logger.warning(
                "Carjam owner_check API returned 429 for rego=%s — retry after %ds",
                rego_norm,
                retry_secs,
            )
            raise CarjamRateLimitError(retry_after=retry_secs)

        if response.status_code != 200:
            logger.error(
                "Carjam owner_check API unexpected status %d for rego=%s: %s",
                response.status_code,
                rego_norm,
                response.text[:500],
            )
            raise CarjamError(
                f"Carjam owner_check API returned status {response.status_code}"
            )

        body_text = response.text
        recorded_options = {
            k: ("<redacted>" if k == "key" else v) for k, v in params.items()
        }
        return _parse_owner_check_response(rego_norm, body_text, recorded_options)
