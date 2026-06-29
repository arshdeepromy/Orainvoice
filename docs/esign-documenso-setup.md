# E-Signature (Documenso) — Per-Organisation Setup

Operator/Global-Admin guide for wiring up the OraInvoice **E-Signature
(Agreements)** integration. Each organisation calls **its own** Documenso Team
with its own team-scoped token, so this setup is performed **once per
organisation** and **once per environment** (dev and prod have separate
Documenso instances/URLs — their tokens, secrets and routing ids never cross).

This is the supported manual path. The optional one-click **Provision
e-signature** action (when `ESIGN_PROVISIONING_MODE` is enabled) automates most
of it best-effort, but this manual flow is always available as the fallback.

> Why manual: Documenso's public REST API exposes **no** endpoint to create a
> Team, mint a team token, or register a Team webhook subscription. Those are
> done in the Documenso UI by an operator.

---

## What you need before starting

For the target organisation, in the target environment, gather:

- The **Documenso base URL** for the environment (HTTPS, e.g.
  `https://documenso.example.com`).
- The organisation's **Documenso Team** (create it in Documenso if it doesn't
  exist) and its **Team ID**.
- A **team-scoped API token** for that Team (Documenso → Team → Settings →
  API Tokens). OraInvoice sends this raw token in the `Authorization` header
  (no `Bearer` prefix).
- A **webhook signing secret** — any sufficiently random string you choose.
  You will paste the *same* value into both OraInvoice and Documenso.

OraInvoice stores the team token and webhook secret **envelope-encrypted**; they
are never returned in plaintext (the UI shows a mask + last-4 only).

---

## Step 1 — Record the connection in OraInvoice

1. Sign in as **Global Admin** and open **Organisations**.
2. Open the target organisation and go to its **E-Signature connection**
   management view.
3. Enter the **base URL**, **Team ID**, **service token**, and **webhook signing
   secret**, then **Save**.

Saving generates (and thereafter preserves) the org's opaque
`webhook_routing_id` and **clears** `is_verified` until you re-test (R19.5).

The view now shows the org's **webhook URL**:

```
{public-base}/api/v2/esign/webhook/{webhook_routing_id}
```

`{public-base}` is the externally reachable origin that fronts the OraInvoice
API in this environment (Documenso must be able to reach it).

## Step 2 — Register the webhook in Documenso

1. In **Documenso**, signed in to **that organisation's Team**, open
   **Settings → Webhooks → Create webhook**.
2. **Endpoint URL**: paste the webhook URL copied from OraInvoice.
3. **Secret**: enter the **same** webhook signing secret you saved in Step 1.
   OraInvoice compares it **verbatim** — Documenso sends the configured secret
   as-is in the `X-Documenso-Secret` header; it does **not** HMAC the body.
4. **Events**: subscribe to the document lifecycle events:
   - document opened / viewed
   - recipient completed / recipient rejected
   - document completed / document cancelled
5. Save the webhook.

## Step 3 — Verify the connection

1. Back in OraInvoice, click **Test connection** on the same view.
2. A successful test sets **`is_verified = true`** (R19.2). Only a verified
   connection lets the organisation send for signature — while unverified, sends
   are blocked with a human-readable error (R19.3 / R19.4).

## Step 4 — Confirm webhook delivery (optional but recommended)

Trigger one signing event (or use Documenso's "send test" on the webhook). Once
OraInvoice records the first inbound webhook on this org's routing URL, the
connection's **subscription status** advances to `active`.

---

## Subscription status meanings

The connection response surfaces `webhook_subscription_status`:

| Status | Meaning |
|---|---|
| `not_configured` | No connection recorded for this org yet. |
| `pending_verification` | Connection recorded, but the connection test has not passed (`is_verified = false`). Sends are blocked. |
| `verified` | Connection test passed, but no inbound webhook seen yet — the Documenso-side webhook registration is recorded but unconfirmed. |
| `active` | Verified **and** at least one webhook received on the org's routing URL — the per-org subscription is live end-to-end. |

---

## Per-environment notes

- Repeat **all** steps independently for each organisation **and** each
  environment. Dev and prod use different Documenso instances/URLs, so each
  needs its own Team token, webhook secret, and webhook registration (R18.3).
- The `webhook_routing_id` is opaque and unique per organisation; it embeds in
  the callback URL so inbound webhooks resolve to the correct org before the
  shared-secret check runs.
- Never reuse one org's token, secret, or routing id for another org or
  environment (R13.7).

_Refs: requirements 1.x, 13.7, 18.1, 18.2, 18.3, 19.1–19.5; spec
`.kiro/specs/esignature-integration/`._

---

# Go-Live Checklist / Operational Prerequisites

These are **non-code go-live gates** — operational prerequisites that must be
satisfied **before** the E-Signature integration is used in a given
environment (and re-confirmed for **each** organisation). They cannot be
enforced by application code; a Global Admin / operator must complete and tick
each one. Treat this as a release gate: do **not** flip an organisation's
`esignatures` module on in prod until every applicable item below is checked.

Work through the list **once per organisation, per environment**. Dev and prod
run separate Documenso instances/URLs, so their tokens, secrets, routing ids,
and webhook registrations never cross.

## 1. Per-org, per-environment manual provisioning

For **each** organisation, in **each** environment (dev, then prod):

- [ ] In **Documenso** (the instance for this environment), create that
      organisation's **Team** and note its **Team ID**.
- [ ] Mint a **team-scoped API token** for that Team (Documenso → Team →
      Settings → API Tokens). OraInvoice sends this raw token in the
      `Authorization` header (no `Bearer` prefix).
- [ ] Choose a fresh, sufficiently random **webhook signing secret** for this
      org+environment (you will paste the same value into OraInvoice and
      Documenso).
- [ ] In **OraInvoice** as **Global Admin**, record the connection via the
      per-org connection settings surface — Organisations → (org) →
      **E-Signature connection** — i.e.
      `PUT /api/v2/admin/organisations/{org_id}/esign/connection` with the
      base URL, Team ID, team token, and webhook secret. Saving generates the
      org's opaque `webhook_routing_id` and clears `is_verified` until you
      re-test.
- [ ] Copy the org's **webhook URL** shown by OraInvoice:
      `{public-base}/api/v2/esign/webhook/{webhook_routing_id}` — where
      `{public-base}` is this environment's externally reachable OraInvoice
      origin (must be reachable from the Documenso container).
- [ ] In **Documenso**, signed in to **that org's Team**, register the webhook
      subscription (Settings → Webhooks → Create webhook) targeting that
      org's routing URL, with the **same** webhook secret, subscribed to the
      document lifecycle events (opened/viewed, recipient completed/rejected,
      document completed/cancelled).
- [ ] Back in OraInvoice, run **Test connection** and confirm `is_verified`
      flips to `true` (sends stay blocked until verified).
- [ ] Confirm the org's `webhook_subscription_status` reaches `active` after the
      first inbound webhook (see "Subscription status meanings" above).

> Do all of the above **independently** per organisation and per environment.
> Never reuse one org's token / secret / routing id for another org or
> environment (R13.7, R18.3, R19.1).

## 2. Production signing certificate confirmed

- [ ] Confirm a **real production signing certificate** (`.p12`, with a
      non-empty passphrase) is provisioned in the **prod** Documenso instance.
- [ ] Confirm the **dev** self-signed certificate (the dev `documenso/.env`
      ships a self-signed cert with an **empty** passphrase —
      `NEXT_PRIVATE_SIGNING_PASSPHRASE` empty) is **NOT** in use in prod. The
      dev cert is for local integration testing only and must never sign
      production agreements.

## 3. In-container webhook delivery test

- [ ] From **inside the Documenso container** (per
      [documenso#1303](https://github.com/documenso/documenso/issues/1303)),
      confirm each org's callback `/.../api/v2/esign/webhook/{routing_id}` is
      reachable for the active environment — Documenso dispatches webhooks from
      within its own container/network, so reachability must be validated from
      there, not from your laptop. Do this **early** (before go-live), so a
      tunnel/DNS/origin misconfiguration surfaces before real signing events
      are lost.
- [ ] Confirm the test delivery advances the org's
      `webhook_subscription_status` to `active`.

## 4. Fresh prod secrets + rotate committed dev secrets

- [ ] Generate **fresh prod Documenso secrets** — per-org team tokens **and**
      per-org webhook secrets — directly in the prod Documenso instance. Do
      **NOT** reuse any value from the committed dev `documenso/.env`.
- [ ] **Rotate the committed dev Gmail app password.** The dev `documenso/.env`
      contains a live Gmail SMTP app password (`NEXT_PRIVATE_SMTP_PASSWORD`)
      that has been committed to the repo — rotate it in the Google account and
      replace the committed value. Treat any other secret committed in that dev
      env file as compromised and rotate it too.
- [ ] Confirm prod Documenso secrets live only in the prod environment
      (envelope-encrypted in OraInvoice's per-org connection record / the prod
      Documenso instance) and are never committed to the repo.

## 5. `ESIGN_PROVISIONING_MODE` deployment note

`ESIGN_PROVISIONING_MODE` is a **platform-level** flag controlling the optional
one-click "Provision e-signature" auto-provisioning action.

- [ ] **Recommended default: `off`.** With it off, only the manual per-org
      connection path (Section 1) is available — which is the supported,
      guaranteed path.
- [ ] If set to **`trpc`**: provision the platform-level Documenso **admin
      credential** (the tRPC session/credential its web UI uses) as
      **envelope-encrypted platform config**. Never store it on any org's
      `esign_org_connections` row.
- [ ] If set to **`db`**: provision the platform-level Documenso **database
      URL** as **envelope-encrypted platform config**. Never store it on any
      org's `esign_org_connections` row.
- [ ] Understand the tradeoff: auto-provisioning is **best-effort,
      unsupported, and upgrade-fragile** — it relies on Documenso internals not
      covered by the public REST API and may break on Documenso upgrades. Any
      adapter failure is isolated and never blocks or corrupts the manual
      path. The **manual per-org connection path (Section 1) remains the
      guaranteed fallback at all times.**
- [ ] Platform provisioning credentials are used **only** for provisioning —
      never for per-org Documenso API calls (those always use the org's own
      team-scoped token, R13.7).

_Refs: requirements 18.1, 18.3, 19.1, 20.4, 20.5; Non-Functional Constraints
(signing certificate, manual provisioning, optional auto-provisioning); spec
`.kiro/specs/esignature-integration/`._
