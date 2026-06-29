# Documenso v2 Capability Matrix

De-risks the four *Documenso capability assumptions* in the E-Signature Field Placement design (`.kiro/specs/esignature-field-placement/design.md`). Produced by `scripts/probe_documenso_capabilities.py` (spec task 9.2).

- **Generated:** 2026-06-29 07:40 UTC
- **Target build:** (none reachable)
- **Live probe executed:** NO — see note

> **NOTE — results are `UNVERIFIED`.** This matrix was generated without a successful authenticated run against a per-org Documenso build (no team-scoped token/connection was reachable in the environment). Each capability is therefore recorded as `UNVERIFIED — requires running against a live Documenso build`, and the **conservative fallback** for each is the assumption the conditional tasks should adopt until a live probe upgrades the status. Re-run this script against a real build to populate `SUPPORTED`/`UNSUPPORTED`.

| # | Capability | Status | Detail | Documented fallback if unsupported |
|---|---|---|---|---|
| (a) | Non-SIGNATURE field types on field/create-many (INITIALS/NAME/DATE/EMAIL/TEXT) | **UNVERIFIED** | UNVERIFIED — requires running against a live Documenso build. | Restrict the editor palette to the supported subset; the type→Documenso mapping + validation already reject unsupported types so an unsupported type can never reach the wire. |
| (b) | fieldMeta (required/label/placeholder) accepted and honoured | **UNVERIFIED** | UNVERIFIED — requires running against a live Documenso build. | fieldMeta becomes a no-op on the wire + advisory/OraInvoice-only (Tasks 8.1/17.6); R14.8's advisory-require⇒optional degrade then holds trivially. |
| (c) | Delete/replace fields on a sent, unsigned document | **UNVERIFIED** | UNVERIFIED — requires running against a live Documenso build. | Edit-after-send degrades to Void_And_Recreate only (proven via cancel_document); the in-place PUT …/fields atomic-replace path is NOT shipped (Task 16.3). |
| (d) | Per-recipient signingOrder + SEQUENTIAL/PARALLEL mode, enforced | **UNVERIFIED** | UNVERIFIED — requires running against a live Documenso build. | Sequential degrades to parallel with a clear advisory note that order is recorded but not enforced (Tasks 19.2/19.3); the additive schema fields remain accepted and stored. |

## Status vocabulary

- **SUPPORTED** — the live per-org build accepted (and, where checked, persisted) the call.
- **UNSUPPORTED** — the live build actively rejected the call; adopt the documented fallback.
- **UNVERIFIED** — could not be determined (no reachable authenticated build, or transport failure). Treat conservatively as the fallback until verified.

## Conditional tasks gated by this matrix

- **(a)** gates the editor palette type set (Tasks 8.1 mapping, frontend `FieldPalette`).
- **(b)** gates `build_field_meta` on-the-wire behaviour (Tasks 8.1 / 17.6).
- **(c)** gates the in-place edit-after-send `PUT …/fields` replace path vs Void_And_Recreate-only (Task 16.3).
- **(d)** gates sequential signing order vs parallel-with-advisory (Tasks 19.2 / 19.3).

