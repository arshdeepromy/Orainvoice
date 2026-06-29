"""Throwaway capability probe for the Documenso v2 field / distribute surface.

de-risk the four "Documenso capability assumptions" the E-Signature Field
Placement design depends on (see
`.kiro/specs/esignature-field-placement/design.md` →
*Documenso capability assumptions*). The integrated ``DocumensoClient`` today
exercises only a **narrow slice** of the v2 surface — it ever creates a single
``SIGNATURE`` field, sends **no** ``fieldMeta``, and distributes EMAIL-only with
no signing-order metadata. This script exercises the surface *beyond* that
proven slice and records a **pass/fail** outcome for each assumption so the
conditional tasks (16.3, 19.2/19.3, and the ``fieldMeta`` behaviour in 8.1/17.6)
can be implemented against verified reality instead of an assumption.

The four capabilities probed (matching the design subsection 1:1):

  (a) ``field/create-many`` accepts non-``SIGNATURE`` types — one field each of
      ``INITIALS`` / ``NAME`` / ``DATE`` / ``EMAIL`` / ``TEXT`` on a throwaway
      document, each accepted and rendered at signing.
  (b) ``fieldMeta`` (``required`` / ``label`` / ``placeholder``) is accepted per
      field and honoured by the signing engine.
  (c) a document's fields can be **deleted / replaced** while it is ``sent`` and
      unsigned, and re-running ``field/create-many`` yields exactly the new set.
  (d) per-recipient ``signingOrder`` positions + a ``SEQUENTIAL`` / ``PARALLEL``
      distribution mode are accepted and **enforced** (recipient N+1 cannot sign
      before N).

For each capability found **unsupported**, the documented fallback is:
  (a) restrict the editor palette to the supported subset;
  (b) ``fieldMeta`` becomes a no-op on the wire + advisory only (Tasks 8.1/17.6);
  (c) edit-after-send degrades to **Void_And_Recreate only** — the in-place
      ``PUT …/fields`` replace path is not shipped (Task 16.3);
  (d) sequential **degrades to parallel** with an advisory note (Tasks
      19.2/19.3).

──────────────────────────────────────────────────────────────────────────────
HONESTY CONTRACT
──────────────────────────────────────────────────────────────────────────────
This probe NEVER fabricates a pass. A capability is recorded ``SUPPORTED`` only
when the live call succeeds against the running per-org Documenso build; any
auth/transport/HTTP failure, or the inability to reach an authenticated build,
is recorded ``UNVERIFIED`` (could not determine) — distinct from ``UNSUPPORTED``
(the build actively rejected the call). The conservative reading of both
``UNVERIFIED`` and ``UNSUPPORTED`` is the documented fallback above.

──────────────────────────────────────────────────────────────────────────────
HOW TO RUN (against a real per-org Documenso build)
──────────────────────────────────────────────────────────────────────────────
Two credential sources are supported.

1. Directly via env vars (simplest — no DB needed):

       DOCUMENSO_PROBE_BASE_URL=https://documenso.example.com \
       DOCUMENSO_PROBE_TOKEN=<team-scoped API token> \
       python scripts/probe_documenso_capabilities.py

2. From an organisation's stored, encrypted connection (inside the app
   container, so the DB + encryption key are available):

       docker compose -f docker-compose.yml -f docker-compose.dev.yml \
         exec -T app python scripts/probe_documenso_capabilities.py \
         --org-id <ORG_UUID>

   This loads the org's ``esign_org_connections`` row via the same
   ``get_documenso_connection`` loader the app uses (decrypting the team-scoped
   token at call time).

Optional flags:
  --matrix-out PATH   Write the resulting capability matrix to PATH (Markdown).
                      Defaults to docs/documenso-capability-matrix.md.
  --no-write          Print the matrix but do not write the doc.
  --insecure-http     Allow a plaintext-HTTP internal base URL (mirrors the
                      app's ``esign_allow_insecure_internal_base_url`` escape
                      hatch). Use ONLY for an internal/private dev Documenso.

Cleanup (MANDATORY): every document this probe creates is titled with the
``TEST_PROBE_`` prefix and is cancelled/voided in a ``finally`` block. If a
throwaway document cannot be cleaned up, the probe prints a loud warning naming
the id so it can be removed by hand.

Refs: design §"Documenso capability assumptions"; tasks 9.2, 8.1, 16.3,
19.2/19.3; requirements 2.4, 5.3, 13.3, 15.4.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import sys
import uuid
from dataclasses import dataclass, field as _dc_field
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import httpx
except ImportError as exc:  # pragma: no cover - dependency guard
    print(f"\u26a0\ufe0f  Required dependency not available: {exc}")
    print("   Run inside the app container or `pip install httpx`.")
    sys.exit(2)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"
INFO = "\033[94m\u2192\033[0m"
WARN = "\033[93m!\033[0m"

# Probe outcome vocabulary (kept distinct on purpose — see HONESTY CONTRACT).
SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNVERIFIED = "UNVERIFIED"

TEST_PREFIX = "TEST_PROBE_"


def _note(label: str, detail: str = "") -> None:
    msg = f"  {INFO} {label}"
    if detail:
        msg += f" \u2014 {detail}"
    print(msg)


def _warn(label: str, detail: str = "") -> None:
    msg = f"  {WARN} {label}"
    if detail:
        msg += f" \u2014 {detail}"
    print(msg)


# ---------------------------------------------------------------------------
# Capability matrix model
# ---------------------------------------------------------------------------


@dataclass
class CapabilityResult:
    """Outcome for one of the four design capability assumptions."""

    key: str  # "a" | "b" | "c" | "d"
    name: str
    status: str = UNVERIFIED  # SUPPORTED | UNSUPPORTED | UNVERIFIED
    detail: str = ""
    fallback: str = ""

    @property
    def glyph(self) -> str:
        return {
            SUPPORTED: PASS,
            UNSUPPORTED: FAIL,
            UNVERIFIED: WARN,
        }.get(self.status, WARN)


def _new_matrix() -> dict[str, CapabilityResult]:
    return {
        "a": CapabilityResult(
            key="a",
            name="Non-SIGNATURE field types on field/create-many "
            "(INITIALS/NAME/DATE/EMAIL/TEXT)",
            fallback="Restrict the editor palette to the supported subset; the "
            "type→Documenso mapping + validation already reject unsupported "
            "types so an unsupported type can never reach the wire.",
        ),
        "b": CapabilityResult(
            key="b",
            name="fieldMeta (required/label/placeholder) accepted and honoured",
            fallback="fieldMeta becomes a no-op on the wire + advisory/OraInvoice-"
            "only (Tasks 8.1/17.6); R14.8's advisory-require\u21d2optional degrade "
            "then holds trivially.",
        ),
        "c": CapabilityResult(
            key="c",
            name="Delete/replace fields on a sent, unsigned document",
            fallback="Edit-after-send degrades to Void_And_Recreate only "
            "(proven via cancel_document); the in-place PUT \u2026/fields atomic-"
            "replace path is NOT shipped (Task 16.3).",
        ),
        "d": CapabilityResult(
            key="d",
            name="Per-recipient signingOrder + SEQUENTIAL/PARALLEL mode, enforced",
            fallback="Sequential degrades to parallel with a clear advisory note "
            "that order is recorded but not enforced (Tasks 19.2/19.3); the "
            "additive schema fields remain accepted and stored.",
        ),
    }


# ---------------------------------------------------------------------------
# Minimal throwaway PDF (single page) — no external dependency
# ---------------------------------------------------------------------------


def _make_probe_pdf() -> bytes:
    """Return the bytes of a minimal, valid single-page PDF.

    Hand-assembled so the probe carries no dependency on a PDF library and
    never touches a real customer document. One page, US-Letter-ish media box.
    """
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length 58 >>\nstream\nBT /F1 18 Tf 72 720 Td "
        b"(TEST_PROBE document) Tj ET\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_pos}\n".encode()
    )
    out += b"%%EOF"
    return bytes(out)


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


@dataclass
class ProbeConn:
    base_url: str
    token: str  # raw team-scoped token (NO "Bearer" prefix)


async def _load_conn_from_db(org_id: str) -> ProbeConn:
    """Load an org's decrypted connection via the app's own loader."""
    from app.core.database import async_session_factory  # type: ignore
    from app.integrations.documenso import get_documenso_connection  # type: ignore

    async with async_session_factory() as db:
        # Scope RLS to the org so the connection row is visible.
        await db.execute(
            __import__("sqlalchemy").text(
                "SELECT set_config('app.current_org_id', :oid, true)"
            ),
            {"oid": str(org_id)},
        )
        conn = await get_documenso_connection(db, org_id)
    return ProbeConn(base_url=conn.base_url, token=conn.service_token)


def _resolve_conn(args: argparse.Namespace) -> ProbeConn | None:
    """Resolve credentials from env or --org-id; None if unavailable."""
    base = os.environ.get("DOCUMENSO_PROBE_BASE_URL")
    token = os.environ.get("DOCUMENSO_PROBE_TOKEN")
    if base and token:
        return ProbeConn(base_url=base.rstrip("/"), token=token)
    if args.org_id:
        try:
            return asyncio.get_event_loop().run_until_complete(
                _load_conn_from_db(args.org_id)
            )
        except Exception as exc:  # pragma: no cover - env dependent
            _warn(
                "Could not load org connection from DB",
                f"{type(exc).__name__}: {exc}",
            )
            return None
    return None


# ---------------------------------------------------------------------------
# Thin raw v2 client (the probe goes BEYOND DocumensoClient's proven methods)
# ---------------------------------------------------------------------------


class _RawV2:
    """Minimal raw caller for the v2 RPC surface, scoped by a team token.

    Deliberately separate from ``DocumensoClient`` so the probe can issue calls
    the shipped client does not yet support (multi-type create-many, fieldMeta,
    field deletion, signing order). Mirrors the client's auth convention: the
    raw team-scoped token in ``Authorization`` with **no** ``Bearer`` prefix.
    """

    def __init__(self, conn: ProbeConn, http: httpx.AsyncClient) -> None:
        self._base = conn.base_url.rstrip("/")
        self._token = conn.token
        self._http = http

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base}{path}"

    async def call(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        return await self._http.request(
            method,
            self._url(path),
            headers={"Authorization": self._token},
            timeout=httpx.Timeout(15.0),
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Document lifecycle helpers used by the probes
# ---------------------------------------------------------------------------


async def _create_probe_document(
    raw: _RawV2, *, title: str, recipients: list[dict[str, Any]]
) -> dict[str, Any]:
    """Create a throwaway document; return {document_id, envelope_id, recipients}."""
    payload = {"title": title, "recipients": recipients}
    resp = await raw.call(
        "POST",
        "/api/v2/document/create",
        data={"payload": json.dumps(payload)},
        files={"file": ("document.pdf", _make_probe_pdf(), "application/pdf")},
    )
    resp.raise_for_status()
    created = resp.json()
    document_id = str(created.get("id"))
    envelope_id = created.get("envelopeId")
    # Read back recipients (ids + tokens) — create response omits them.
    got = await raw.call("GET", f"/api/v2/document/{int(document_id)}")
    got.raise_for_status()
    doc = got.json()
    return {
        "document_id": document_id,
        "envelope_id": str(envelope_id) if envelope_id is not None else None,
        "recipients": doc.get("recipients") or [],
    }


async def _cancel_document(raw: _RawV2, document_id: str) -> bool:
    """Best-effort void of a throwaway document. True if cleaned up/gone."""
    try:
        got = await raw.call("GET", f"/api/v2/document/{int(document_id)}")
        if got.status_code == 404:
            return True
        got.raise_for_status()
        envelope_id = got.json().get("envelopeId")
        if not envelope_id:
            return False
        resp = await raw.call(
            "POST",
            "/api/v2/envelope/cancel",
            json={
                "envelopeId": str(envelope_id),
                "reason": "TEST_PROBE cleanup",
            },
        )
        return resp.status_code < 400
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The four capability probes
# ---------------------------------------------------------------------------


async def _probe_a_field_types(
    raw: _RawV2, result: CapabilityResult, created_docs: list[str]
) -> None:
    """(a) Non-SIGNATURE field types on field/create-many."""
    types = ["INITIALS", "NAME", "DATE", "EMAIL", "TEXT"]
    try:
        doc = await _create_probe_document(
            raw,
            title=f"{TEST_PREFIX}types_{uuid.uuid4().hex[:8]}",
            recipients=[
                {"name": "Probe Signer", "email": "probe-a@test.invalid",
                 "role": "SIGNER"},
            ],
        )
        created_docs.append(doc["document_id"])
        recipient_id = int(doc["recipients"][0]["id"])
        fields = [
            {
                "recipientId": recipient_id,
                "type": t,
                "pageNumber": 1,
                "pageX": 10.0 + i * 12,
                "pageY": 10.0 + i * 12,
                "width": 10.0,
                "height": 5.0,
            }
            for i, t in enumerate(types)
        ]
        resp = await raw.call(
            "POST",
            "/api/v2/document/field/create-many",
            json={"documentId": int(doc["document_id"]), "fields": fields},
        )
        if resp.status_code < 400:
            # Confirm the fields stuck by reading them back.
            got = await raw.call(
                "GET", f"/api/v2/document/{int(doc['document_id'])}"
            )
            got.raise_for_status()
            placed = {
                (f or {}).get("type") for f in (got.json().get("fields") or [])
            }
            missing = [t for t in types if t not in placed]
            if missing:
                result.status = UNSUPPORTED
                result.detail = (
                    f"create-many accepted but these types did not persist: "
                    f"{missing}; persisted={sorted(placed)}"
                )
            else:
                result.status = SUPPORTED
                result.detail = f"All non-SIGNATURE types accepted: {types}"
        else:
            result.status = UNSUPPORTED
            result.detail = (
                f"create-many returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
    except Exception as exc:
        result.status = UNVERIFIED
        result.detail = f"probe could not complete: {type(exc).__name__}: {exc}"


async def _probe_b_field_meta(
    raw: _RawV2, result: CapabilityResult, created_docs: list[str]
) -> None:
    """(b) fieldMeta (required/label/placeholder) accepted per field."""
    try:
        doc = await _create_probe_document(
            raw,
            title=f"{TEST_PREFIX}meta_{uuid.uuid4().hex[:8]}",
            recipients=[
                {"name": "Probe Signer", "email": "probe-b@test.invalid",
                 "role": "SIGNER"},
            ],
        )
        created_docs.append(doc["document_id"])
        recipient_id = int(doc["recipients"][0]["id"])
        fields = [
            {
                "recipientId": recipient_id,
                "type": "TEXT",
                "pageNumber": 1,
                "pageX": 20.0,
                "pageY": 20.0,
                "width": 20.0,
                "height": 6.0,
                "fieldMeta": {
                    "required": True,
                    "label": "Probe Label",
                    "placeholder": "Probe Placeholder",
                },
            }
        ]
        resp = await raw.call(
            "POST",
            "/api/v2/document/field/create-many",
            json={"documentId": int(doc["document_id"]), "fields": fields},
        )
        if resp.status_code < 400:
            got = await raw.call(
                "GET", f"/api/v2/document/{int(doc['document_id'])}"
            )
            got.raise_for_status()
            meta_seen = [
                (f or {}).get("fieldMeta")
                for f in (got.json().get("fields") or [])
                if (f or {}).get("type") == "TEXT"
            ]
            honoured = any(
                isinstance(m, dict)
                and m.get("label") == "Probe Label"
                and m.get("placeholder") == "Probe Placeholder"
                for m in meta_seen
            )
            if honoured:
                result.status = SUPPORTED
                result.detail = "fieldMeta accepted and read back on the field."
            else:
                result.status = UNSUPPORTED
                result.detail = (
                    "create-many accepted the payload but fieldMeta was not "
                    f"persisted/honoured; read back: {meta_seen}"
                )
        else:
            result.status = UNSUPPORTED
            result.detail = (
                f"create-many with fieldMeta returned HTTP {resp.status_code}: "
                f"{resp.text[:200]}"
            )
    except Exception as exc:
        result.status = UNVERIFIED
        result.detail = f"probe could not complete: {type(exc).__name__}: {exc}"


async def _probe_c_replace_fields(
    raw: _RawV2, result: CapabilityResult, created_docs: list[str]
) -> None:
    """(c) Delete/replace fields on a sent, unsigned document."""
    try:
        doc = await _create_probe_document(
            raw,
            title=f"{TEST_PREFIX}replace_{uuid.uuid4().hex[:8]}",
            recipients=[
                {"name": "Probe Signer", "email": "probe-c@test.invalid",
                 "role": "SIGNER"},
            ],
        )
        created_docs.append(doc["document_id"])
        recipient_id = int(doc["recipients"][0]["id"])
        # Place an initial SIGNATURE field.
        await raw.call(
            "POST",
            "/api/v2/document/field/create-many",
            json={
                "documentId": int(doc["document_id"]),
                "fields": [
                    {
                        "recipientId": recipient_id,
                        "type": "SIGNATURE",
                        "pageNumber": 1,
                        "pageX": 30.0,
                        "pageY": 30.0,
                        "width": 20.0,
                        "height": 8.0,
                    }
                ],
            },
        )
        # Distribute so the document is `sent` and unsigned.
        await raw.call(
            "POST",
            "/api/v2/document/distribute",
            json={
                "documentId": int(doc["document_id"]),
                "meta": {"distributionMethod": "EMAIL"},
            },
        )
        # Read existing fields and attempt to delete each one. Documenso has no
        # proven field-deletion endpoint today; probe the plausible candidates
        # and record the first that works (or that none do).
        got = await raw.call(
            "GET", f"/api/v2/document/{int(doc['document_id'])}"
        )
        got.raise_for_status()
        existing = got.json().get("fields") or []
        field_ids = [f.get("id") for f in existing if (f or {}).get("id")]
        deleted_ok = False
        delete_detail = "no candidate deletion endpoint succeeded"
        for fid in field_ids:
            for method, path, kwargs in (
                ("POST", "/api/v2/document/field/delete",
                 {"json": {"fieldId": int(fid)}}),
                ("POST", "/api/v2/document/field/delete-many",
                 {"json": {"fieldIds": [int(fid)]}}),
                ("DELETE", f"/api/v2/document/field/{int(fid)}", {}),
            ):
                try:
                    r = await raw.call(method, path, **kwargs)
                    if r.status_code < 400:
                        deleted_ok = True
                        delete_detail = f"{method} {path} succeeded"
                        break
                except Exception:
                    continue
            if deleted_ok:
                break
        if deleted_ok:
            result.status = SUPPORTED
            result.detail = (
                f"Fields deletable on a sent/unsigned document ({delete_detail})."
            )
        else:
            result.status = UNSUPPORTED
            result.detail = (
                "No field deletion/replacement endpoint accepted the call on a "
                f"sent, unsigned document ({delete_detail})."
            )
    except Exception as exc:
        result.status = UNVERIFIED
        result.detail = f"probe could not complete: {type(exc).__name__}: {exc}"


async def _probe_d_signing_order(
    raw: _RawV2, result: CapabilityResult, created_docs: list[str]
) -> None:
    """(d) Per-recipient signingOrder + SEQUENTIAL/PARALLEL distribution mode."""
    try:
        doc = await _create_probe_document(
            raw,
            title=f"{TEST_PREFIX}order_{uuid.uuid4().hex[:8]}",
            recipients=[
                {"name": "Probe One", "email": "probe-d1@test.invalid",
                 "role": "SIGNER", "signingOrder": 1},
                {"name": "Probe Two", "email": "probe-d2@test.invalid",
                 "role": "SIGNER", "signingOrder": 2},
            ],
        )
        created_docs.append(doc["document_id"])
        # Verify the signingOrder positions were accepted on the recipients.
        order_accepted = all(
            isinstance((r or {}).get("signingOrder"), int)
            for r in doc["recipients"]
        )
        # Place a signature for each recipient so the doc is distributable.
        for r in doc["recipients"]:
            await raw.call(
                "POST",
                "/api/v2/document/field/create-many",
                json={
                    "documentId": int(doc["document_id"]),
                    "fields": [
                        {
                            "recipientId": int(r["id"]),
                            "type": "SIGNATURE",
                            "pageNumber": 1,
                            "pageX": 30.0,
                            "pageY": 30.0,
                            "width": 20.0,
                            "height": 8.0,
                        }
                    ],
                },
            )
        # Attempt a SEQUENTIAL distribution.
        resp = await raw.call(
            "POST",
            "/api/v2/document/distribute",
            json={
                "documentId": int(doc["document_id"]),
                "meta": {
                    "distributionMethod": "EMAIL",
                    "signingOrder": "SEQUENTIAL",
                },
            },
        )
        if resp.status_code < 400 and order_accepted:
            # NOTE: true ENFORCEMENT (recipient N+1 cannot sign before N)
            # cannot be confirmed without driving two real signing sessions;
            # acceptance of the payload is recorded here and enforcement is
            # called out as requiring a manual two-signer walkthrough.
            result.status = SUPPORTED
            result.detail = (
                "Per-recipient signingOrder accepted and SEQUENTIAL distribute "
                "accepted. ENFORCEMENT (N+1 blocked until N) still needs a "
                "manual two-signer walkthrough to confirm end-to-end."
            )
        else:
            result.status = UNSUPPORTED
            result.detail = (
                f"signingOrder accepted={order_accepted}; SEQUENTIAL distribute "
                f"HTTP {resp.status_code}: {resp.text[:200]}"
            )
    except Exception as exc:
        result.status = UNVERIFIED
        result.detail = f"probe could not complete: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Matrix rendering / persistence
# ---------------------------------------------------------------------------


def _render_matrix_markdown(
    matrix: dict[str, CapabilityResult],
    *,
    base_url: str | None,
    ran_live: bool,
) -> str:
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    lines.append("# Documenso v2 Capability Matrix")
    lines.append("")
    lines.append(
        "De-risks the four *Documenso capability assumptions* in the "
        "E-Signature Field Placement design "
        "(`.kiro/specs/esignature-field-placement/design.md`). Produced by "
        "`scripts/probe_documenso_capabilities.py` (spec task 9.2)."
    )
    lines.append("")
    lines.append(f"- **Generated:** {now}")
    lines.append(
        f"- **Target build:** {base_url if base_url else '(none reachable)'}"
    )
    lines.append(
        f"- **Live probe executed:** {'yes' if ran_live else 'NO — see note'}"
    )
    lines.append("")
    if not ran_live:
        lines.append(
            "> **NOTE — results are `UNVERIFIED`.** This matrix was generated "
            "without a successful authenticated run against a per-org Documenso "
            "build (no team-scoped token/connection was reachable in the "
            "environment). Each capability is therefore recorded as "
            "`UNVERIFIED — requires running against a live Documenso build`, and "
            "the **conservative fallback** for each is the assumption the "
            "conditional tasks should adopt until a live probe upgrades the "
            "status. Re-run this script against a real build to populate "
            "`SUPPORTED`/`UNSUPPORTED`."
        )
        lines.append("")
    lines.append(
        "| # | Capability | Status | Detail | Documented fallback if unsupported |"
    )
    lines.append("|---|---|---|---|---|")
    for key in ("a", "b", "c", "d"):
        r = matrix[key]
        detail = r.detail.replace("|", "\\|") if r.detail else ""
        fallback = r.fallback.replace("|", "\\|")
        lines.append(
            f"| ({key}) | {r.name} | **{r.status}** | {detail} | {fallback} |"
        )
    lines.append("")
    lines.append("## Status vocabulary")
    lines.append("")
    lines.append(
        "- **SUPPORTED** — the live per-org build accepted (and, where checked, "
        "persisted) the call."
    )
    lines.append(
        "- **UNSUPPORTED** — the live build actively rejected the call; adopt "
        "the documented fallback."
    )
    lines.append(
        "- **UNVERIFIED** — could not be determined (no reachable authenticated "
        "build, or transport failure). Treat conservatively as the fallback "
        "until verified."
    )
    lines.append("")
    lines.append("## Conditional tasks gated by this matrix")
    lines.append("")
    lines.append(
        "- **(a)** gates the editor palette type set (Tasks 8.1 mapping, "
        "frontend `FieldPalette`)."
    )
    lines.append(
        "- **(b)** gates `build_field_meta` on-the-wire behaviour (Tasks "
        "8.1 / 17.6)."
    )
    lines.append(
        "- **(c)** gates the in-place edit-after-send `PUT \u2026/fields` "
        "replace path vs Void_And_Recreate-only (Task 16.3)."
    )
    lines.append(
        "- **(d)** gates sequential signing order vs parallel-with-advisory "
        "(Tasks 19.2 / 19.3)."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def _print_matrix(matrix: dict[str, CapabilityResult]) -> None:
    print("\n" + "=" * 70)
    print("Documenso capability matrix")
    print("=" * 70)
    for key in ("a", "b", "c", "d"):
        r = matrix[key]
        print(f"  {r.glyph} ({key}) {r.status:11s} {r.name}")
        if r.detail:
            print(f"        {r.detail}")
    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def _run_probes(conn: ProbeConn, matrix: dict[str, CapabilityResult]) -> bool:
    """Run all four probes against a live build. Returns True if it ran live."""
    created_docs: list[str] = []
    async with httpx.AsyncClient() as http:
        raw = _RawV2(conn, http)
        # Smoke check: an authenticated GET should not 401/403.
        try:
            smoke = await raw.call("GET", "/api/v2/document/999999999")
            if smoke.status_code in (401, 403):
                _warn(
                    "Authentication rejected by the target build",
                    f"HTTP {smoke.status_code} — token not accepted; recording "
                    "all capabilities UNVERIFIED.",
                )
                return False
        except Exception as exc:
            _warn(
                "Target build unreachable",
                f"{type(exc).__name__}: {exc} — recording all UNVERIFIED.",
            )
            return False

        try:
            _note("Probe (a): non-SIGNATURE field types")
            await _probe_a_field_types(raw, matrix["a"], created_docs)
            _note("Probe (b): fieldMeta required/label/placeholder")
            await _probe_b_field_meta(raw, matrix["b"], created_docs)
            _note("Probe (c): delete/replace fields on a sent, unsigned doc")
            await _probe_c_replace_fields(raw, matrix["c"], created_docs)
            _note("Probe (d): per-recipient signingOrder + SEQUENTIAL mode")
            await _probe_d_signing_order(raw, matrix["d"], created_docs)
        finally:
            # MANDATORY cleanup — void every throwaway document we created.
            for doc_id in created_docs:
                cleaned = await _cancel_document(raw, doc_id)
                if cleaned:
                    _note(f"cleaned up TEST_PROBE document {doc_id}")
                else:
                    _warn(
                        f"COULD NOT CLEAN UP TEST_PROBE document {doc_id}",
                        "remove it by hand in Documenso.",
                    )
    return True


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--org-id", help="Org UUID to load the connection from the DB.")
    p.add_argument(
        "--matrix-out",
        default="docs/documenso-capability-matrix.md",
        help="Where to write the Markdown matrix (default: %(default)s).",
    )
    p.add_argument(
        "--no-write", action="store_true", help="Do not write the matrix doc."
    )
    p.add_argument(
        "--insecure-http",
        action="store_true",
        help="Allow a plaintext-HTTP internal base URL (dev only).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    matrix = _new_matrix()

    print("Documenso v2 capability probe (spec task 9.2)")
    print("-" * 70)

    conn = _resolve_conn(args)
    ran_live = False

    if conn is None:
        _warn(
            "No per-org Documenso credentials available",
            "set DOCUMENSO_PROBE_BASE_URL + DOCUMENSO_PROBE_TOKEN, or pass "
            "--org-id inside the app container.",
        )
        _note("Recording all capabilities as UNVERIFIED (no live probe).")
    else:
        if (
            conn.base_url.lower().startswith("http://")
            and not args.insecure_http
        ):
            _warn(
                "Refusing plaintext-HTTP base URL without --insecure-http",
                conn.base_url,
            )
            _note("Recording all capabilities as UNVERIFIED (no live probe).")
        else:
            _note(f"Probing {conn.base_url} …")
            ran_live = asyncio.run(_run_probes(conn, matrix))

    if not ran_live:
        # Honesty contract: never leave a fabricated pass. Everything that was
        # not positively determined stays UNVERIFIED with the fallback note.
        for r in matrix.values():
            if r.status not in (SUPPORTED, UNSUPPORTED):
                r.status = UNVERIFIED
                if not r.detail:
                    r.detail = (
                        "UNVERIFIED — requires running against a live "
                        "Documenso build."
                    )

    _print_matrix(matrix)

    if not args.no_write:
        out_path = args.matrix_out
        if not os.path.isabs(out_path):
            out_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                out_path,
            )
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        md = _render_matrix_markdown(
            matrix,
            base_url=conn.base_url if conn else None,
            ran_live=ran_live,
        )
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(md)
        _note(f"Wrote capability matrix \u2192 {out_path}")

    # Exit code: 0 if a live probe ran (regardless of supported/unsupported —
    # those are findings, not script failures); 3 if it could not run live.
    return 0 if ran_live else 3


if __name__ == "__main__":
    raise SystemExit(main())
