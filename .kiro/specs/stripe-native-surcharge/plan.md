# Stripe-Native Surcharge Migration

**Status:** Plan only — no code changes.
**Goal:** Stop sending the surcharge to Stripe as `metadata[surcharge_amount]` and start sending it as Stripe's first-class `amount_details[surcharge][amount]` field, so Stripe treats the surcharge as a structured, customer-facing pass-through rather than an opaque internal annotation.

> **Explicitly NOT in scope.** We are not changing how surcharge rates are configured, who configures them, how they're calculated, where they're stored, or any caps/limits. The admin settings UI, the `org.settings.surcharge_rates` JSON, the gross-up math in `app/modules/payments/surcharge.py`, and the customer-facing UI line item all stay exactly as they are today. **No cap is added** — NZ's updated surcharging law permits passing the full cost of acceptance to the customer, and our existing `MAX_PERCENTAGE = 10%` validation cap stays intact.

---

## 1. Why migrate

Per [Stripe's surcharging docs](https://docs.stripe.com/payments/cards/surcharge), the correct way to tell Stripe that part of a PaymentIntent's amount is a surcharge being passed to the customer is:

```
amount_details[surcharge][amount] = <surcharge in smallest currency unit>
```

Today we send it as `metadata[surcharge_amount]` instead. Both result in the customer paying the same total — the migration is **functionally neutral** for the customer's wallet — but using the native field unlocks:

| Stripe-native capability | Today (metadata) | After migration (amount_details) |
|---|---|---|
| Customer sees "surcharge" line on Stripe-hosted receipts | ❌ Not shown | ✅ Shown automatically |
| Stripe Sigma `amount_details_surcharge_amount` column populates | ❌ Empty | ✅ Populated |
| Refunds auto-prorate the surcharge per card-network rules | ❌ Manual | ✅ Automatic |
| Card-network compliance signalling (we're declaring "this is a surcharge") | ❌ Opaque | ✅ Explicit |
| Fraud / risk scoring sees the surcharge structure | ❌ Hidden | ✅ Visible |

In one sentence: **same dollar amount, same calculation, same UI — just told to Stripe in the field Stripe designed for it.**

---

## 2. What stays exactly the same

These are explicit non-changes — listed here so reviewers can confirm scope:

- **Calculation engine** at [app/modules/payments/surcharge.py](app/modules/payments/surcharge.py) — `calculate_surcharge`, `get_surcharge_for_method`, gross-up formula, banker's rounding, all unchanged.
- **Configuration source** — `org.settings.surcharge_enabled` and `org.settings.surcharge_rates` JSONB. Admins configure rates per payment method in the existing settings page; no UI change.
- **Per-method rates** — `card`, `afterpay_clearpay`, `klarna`, `bank_transfer` defaults from `DEFAULT_SURCHARGE_RATES` in `surcharge.py`. Unchanged.
- **Validation caps** — `MAX_PERCENTAGE = 10%`, `MAX_FIXED = 5.00`. No change. Removing or raising the cap is explicitly out of scope (NZ law allows full cost-of-acceptance pass-through, but our 10% cap is comfortably above any realistic card-acceptance cost, so it stays as a defence-in-depth misconfiguration guard).
- **Wallet → card mapping** (`apple_pay`/`google_pay` → `card` rate) — unchanged.
- **Frontend display** at [InvoicePaymentPage.tsx:324-332](frontend/src/pages/public/InvoicePaymentPage.tsx#L324) — surcharge still rendered as a separate line item with the payment-method label *before* the customer clicks Pay. Same UX.
- **Local frontend pre-compute** for instant display, followed by authoritative server recompute via `/update-surcharge` — same dance.
- **`Payment.surcharge_amount` DB column** at [payments/models.py:64](app/modules/payments/models.py#L64) — kept. This is our internal record and continues to drive the in-app reporting and receipt emails.
- **Receipt email line** at [payments/service.py:660-668](app/modules/payments/service.py#L660) — "Payment method surcharge ({method_label}): {currency} {surcharge_amount}" stays.
- **Refund processing entry points** — `process_refund` at [payments/service.py:1091](app/modules/payments/service.py#L1091) and `create_stripe_refund` at [stripe_connect.py:417](app/integrations/stripe_connect.py#L417). The flow is unchanged; Stripe will auto-prorate the surcharge portion (see §6 below).
- **All caps, gates, business rules** — nothing legal/policy-shaped is touched.

---

## 3. What changes — three precise sites

### 3.1 Outbound write: the `update-surcharge` endpoint

[app/modules/payments/public_router.py:580-595](app/modules/payments/public_router.py#L580) — the Stripe API call that today sends only `amount` and `metadata` for the surcharge.

**Today:**
```python
payload = {
    "amount": str(new_amount_cents),
    "metadata[surcharge_amount]": str(surcharge),
    "metadata[surcharge_method]": body.payment_method_type,
    "metadata[original_amount]": str(resolved_balance),
}
```

**After:**
```python
payload = {
    "amount": str(new_amount_cents),
    # NEW — Stripe-native surcharge declaration
    "amount_details[surcharge][amount]": str(int(surcharge * 100)),
    # KEEP metadata during transition (Phase A); drop in Phase C
    "metadata[surcharge_amount]": str(surcharge),
    "metadata[surcharge_method]": body.payment_method_type,
    "metadata[original_amount]": str(resolved_balance),
}
```

Notes:
- `amount_details[surcharge][amount]` takes an **integer in the smallest currency unit** (cents for NZD), matching the convention of `amount`.
- `amount` still equals total (base + surcharge); this does not change. Stripe expects this — see [Stripe's example: $10 base + $0.20 surcharge → `amount=1020, amount_details[surcharge][amount]=20`](https://docs.stripe.com/payments/cards/surcharge).
- The `Stripe-Account: <org.stripe_connect_account_id>` header continues to scope the call to the connected account.
- **No call to `surcharge.status` / `maximum_amount`** — per the explicit "no cap" requirement, we do not query or honour Stripe's technical maximum. Stripe returns the structured surcharge in the PI response regardless.

### 3.2 Inbound read: the webhook handler

[app/modules/payments/service.py:814-832](app/modules/payments/service.py#L814) — when Stripe fires `payment_intent.succeeded`, we currently parse the surcharge breakdown out of `metadata`.

**Today:**
```python
surcharge_str = metadata.get("surcharge_amount", "0")
surcharge_method = metadata.get("surcharge_method", "")
try:
    surcharge = Decimal(surcharge_str)
except Exception:
    surcharge = Decimal("0")
```

**After (read-both, prefer-native):**
```python
# Prefer Stripe-native amount_details; fall back to metadata for
# any in-flight PaymentIntents created under the old code path.
amount_details = payment_intent.get("amount_details") or {}
native_surcharge = (amount_details.get("surcharge") or {}).get("amount")
if native_surcharge is not None:
    surcharge = Decimal(native_surcharge) / Decimal("100")  # cents → dollars
else:
    # Legacy path — to be removed in Phase C cleanup
    surcharge_str = metadata.get("surcharge_amount", "0")
    try:
        surcharge = Decimal(surcharge_str)
    except Exception:
        surcharge = Decimal("0")
surcharge_method = metadata.get("surcharge_method", "")
```

The `original_amount` and `surcharge_method` fields stay on metadata because there is no Stripe-native equivalent for either (they're our bookkeeping concepts). That's fine — Stripe does not object to extra metadata; we just no longer rely on metadata for the surcharge amount itself.

### 3.3 No change to initial PaymentIntent create

[stripe_connect.py:301-405 `create_payment_intent`](app/integrations/stripe_connect.py#L301) creates the PI with `amount = balance_due` and **no surcharge** because the customer has not yet picked a payment method. The first surcharge value is computed when the customer selects a method and triggers `/update-surcharge` (§3.1). Therefore **no change needed at PI creation time** — the new `amount_details[surcharge][amount]` field is set on the first `update-surcharge` call, exactly when we get the first surcharge value.

If, in a later refactor, we ever pre-compute a default surcharge at PI creation (e.g., for an org with only one configured method), we'd add `amount_details[surcharge][amount]` to the `payload` dict here too. Not required now.

---

## 4. Where the rates come from (verified, no change)

The frontend receives `surcharge_enabled` and `surcharge_rates` from the public payment-page response at [public_router.py:170-201](app/modules/payments/public_router.py#L170). The server reads them from:

```python
org_settings = org.settings or {}
surcharge_enabled = org_settings.get("surcharge_enabled", False)
raw_rates = org_settings.get("surcharge_rates", {})
```

— exactly the same code path that the `update-surcharge` endpoint reads from at [public_router.py:543-548](app/modules/payments/public_router.py#L543). Both endpoints share `deserialise_rates(raw_rates, DEFAULT_SURCHARGE_RATES)` and `get_surcharge_for_method(...)` from `surcharge.py`. **The migration changes neither the read site, the parse, nor the calculator.** It only changes which Stripe field we write to.

---

## 5. Customer-visible behaviour (preserved)

The user asked explicitly: "we would want to show the customer what will be deducted as a surcharge amount". This is already what we do today and is preserved verbatim by this migration:

| Surface | Before customer pays | Stays the same? |
|---|---|---|
| Payment page UI line item ("Surcharge (Card) $X.XX") | ✅ shown | yes |
| Payment page total ("You'll be charged $Y.YY") | ✅ shown | yes |
| Stripe Elements / Payment Element checkout total | ✅ matches `amount` from PI | yes |
| Confirmation email receipt | ✅ surcharge as separate line | yes |
| Stripe-hosted receipt (if customer opts in) | ❌ today / ✅ after migration | **improves** |

Net effect for the customer: identical dollar total, identical disclosure on our payment page, **plus** Stripe's own receipt now shows surcharge as a structured line item instead of being silent about it.

---

## 6. Refund implications

This is the only place where Stripe behaviour materially changes:

**Today**: when we refund a Payment that carries a surcharge, we issue a full or partial refund against the gross PaymentIntent. Stripe does not know which portion is the surcharge, so a partial refund is applied pro-rata against the gross. If a $100 base + $3 surcharge is half-refunded, the customer gets $51.50 back and we have no Stripe-side accounting of the $1.50 surcharge portion.

**After**: with `amount_details[surcharge][amount]` set, **Stripe handles surcharge proration on refunds per card-network rules**. A full refund refunds the full surcharge; a partial refund prorates the surcharge automatically. Our `Payment.surcharge_amount` column continues to hold the original surcharge, and our internal refund records (`Refund.amount`) continue to be authoritative for our own books.

**Action required**: verify in Phase B testing that:
1. A full refund of a surcharged payment returns `amount + surcharge` to the customer.
2. A partial refund returns a prorated amount (Stripe's webhook will report the breakdown via `refund.amount` and `refund.amount_details`).
3. Our `process_refund` flow does not need any logic change — Stripe owns the proration; we just record what Stripe tells us.

If our refund-display flow ever shows a customer "you were refunded $X surcharge", we currently compute that from our DB. Post-migration that number could differ slightly from Stripe's actual refund if the proration formula differs. **Mitigation**: prefer Stripe's `refund.amount` as the source of truth for receipts/display; treat our local `Payment.surcharge_amount` as the *original* surcharge, not the *refunded* surcharge.

---

## 7. Execution phases

### Phase A — Write-both (safe, backwards-compatible)

**Single backend change. No frontend change. No database migration.**

- [ ] Edit `app/modules/payments/public_router.py:580-595` — add the `amount_details[surcharge][amount]` key to the payload alongside the existing `metadata[*]` keys.
- [ ] Edit `app/modules/payments/service.py:814-832` — the webhook handler reads `amount_details.surcharge.amount` first, falls back to `metadata.surcharge_amount`.
- [ ] Add structured log line in the webhook handler indicating which source provided the surcharge (`source="amount_details"` vs `source="metadata_fallback"`). This is the metric for Phase C readiness.
- [ ] Tests:
  - Unit test for the webhook parser: PI with `amount_details.surcharge.amount=120` → `surcharge = Decimal("1.20")`.
  - Unit test for the webhook parser: PI without `amount_details` (legacy) → falls back to metadata.
  - Integration test: mock Stripe modify endpoint, assert payload includes both `amount_details[surcharge][amount]` and `metadata[surcharge_amount]`.

**Gate**: deployed to prod; new PaymentIntents carry both fields; existing in-flight PIs continue to settle via the metadata fallback.

### Phase B — Soak (one release / two weeks)

- [ ] Monitor the log line from §Phase A. Expect 100% of `payment_intent.succeeded` webhooks for new PIs to report `source="amount_details"`.
- [ ] Any `source="metadata_fallback"` hits indicate either (a) an in-flight PI created before Phase A — expected to taper to zero within a few days, or (b) a bug — investigate.
- [ ] Run one real refund (test mode + prod) to confirm Stripe's proration matches what we expect on the customer's statement.
- [ ] Verify Stripe Dashboard now shows a "Surcharge" line on the PaymentIntent details view (visual check, no test).
- [ ] Verify Stripe Sigma `amount_details_surcharge_amount` is populated on a test query.

**Gate**: two-week clean window with no `metadata_fallback` hits on freshly-created PIs.

### Phase C — Drop legacy write

- [ ] Edit `public_router.py` payload to remove `metadata[surcharge_amount]` (keep `metadata[surcharge_method]` and `metadata[original_amount]` — they have no Stripe-native equivalent).
- [ ] Edit `service.py` webhook handler to remove the metadata fallback parsing block.
- [ ] Update the log line to remove `source="metadata_fallback"` branch.
- [ ] Tests: re-run the Phase A integration test, asserting payload no longer contains `metadata[surcharge_amount]`.

**Gate**: backend release; no schema change; no UI change.

---

## 8. Test plan

### 8.1 New tests

| File | Phase | Asserts |
|---|---|---|
| `tests/test_surcharge_native_stripe_payload.py` | A | The `/update-surcharge` endpoint POSTs `amount_details[surcharge][amount]=<surcharge_cents>` to Stripe. Mock httpx; capture and assert the body. |
| `tests/test_surcharge_webhook_native_parse.py` | A | Webhook handler reads `payment_intent.amount_details.surcharge.amount` correctly. Test with `amount=120` → `Decimal("1.20")`. |
| `tests/test_surcharge_webhook_legacy_fallback.py` | A | Webhook handler falls back to `metadata.surcharge_amount` when `amount_details` is absent. Removed in Phase C. |
| `tests/test_surcharge_refund_proration.py` | B | Partial refund of a surcharged payment correctly records the Stripe-reported refunded amount (not our locally-computed surcharge × proportion). |

### 8.2 Existing tests that must stay green

- Any test that asserts on `Payment.surcharge_amount` — value is unchanged, so these pass without modification.
- Any test exercising the receipt email content — surcharge line still printed.
- Frontend tests for `InvoicePaymentPage.tsx` — no frontend code change, no test change.
- The QR partial-payment flow tests (`payment_token.amount_override` path) — surcharge is still computed against the partial amount, total still equals `partial + surcharge_on_partial`. No semantic change.

### 8.3 Manual smoke checklist before Phase B → C cutover

1. Configure `surcharge_enabled=true` and one rate (e.g. `card: 2.9% + $0.30`) on a test org.
2. Issue an invoice with `balance_due=$100.00`.
3. Open the public payment page. Select Card. Confirm UI shows "Surcharge (Card) $X.XX" and total = $100 + surcharge.
4. Complete payment with a Stripe test card.
5. Check Stripe Dashboard → PaymentIntent → expect a "Surcharge" structured field equal to the X.XX shown to the customer.
6. Check `payment_log` in Sigma: `amount_details_surcharge_amount` should equal the cents value.
7. Issue a 50% refund. Check Stripe's refund record shows a prorated surcharge refund. Check our `Refund.amount` equals what Stripe reports.
8. Receipt email: surcharge line still present.
9. Stripe-hosted receipt (if opted in): now shows surcharge structurally — confirm formatting is reasonable.

---

## 9. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `amount_details[surcharge][amount]` requires a newer Stripe API version than we pin | Low | Stripe accepts `amount_details` on all current API versions for PaymentIntent modify (verified via doc). If the connected account is pinned to an old API version, this field is ignored, not rejected — the metadata fallback covers us during Phase A. |
| Stripe-Connect direct charges may behave differently | Low | The `Stripe-Account` header is on the same request as `amount_details`; Stripe treats this as a connected-account modify and processes the surcharge field identically. No special capability needed for the connected account. |
| Customer's Apple/Google Pay confirmation screen shows surcharge as a confusing extra field | Low | Apple/Google Pay surface the total only — the structured surcharge is invisible in the wallet flow. No customer-facing regression. |
| Refund proration result differs from our locally-computed proration | Med | Phase B includes an explicit test refund. If a discrepancy is found, prefer Stripe's `refund.amount_details.surcharge.amount` as the source of truth for receipt display and reconcile in our reporting. |
| Stripe Sigma column was historically empty; downstream BI dashboards may compute "total surcharge" from `metadata` JSON | Low | Once we cut over, the Sigma column populates. Update any internal Sigma queries to read `amount_details_surcharge_amount` instead of `metadata.surcharge_amount` in the same release. |
| Webhook delivers `amount_details=null` for very small or zero-surcharge PIs | Med | Webhook handler MUST handle `amount_details` being absent or `surcharge` being absent — if both are missing, surcharge is effectively zero. The fallback chain in §3.2 covers this: `amount_details or {}` → `.get("surcharge") or {}` → `.get("amount")`. None → surcharge = 0. |
| QR partial-payment flow's `amount_override` interaction with `amount_details` | Low | Surcharge is computed against the override amount, not the full balance ([public_router.py:543-555](app/modules/payments/public_router.py#L543)). Total `amount` and `amount_details[surcharge][amount]` are derived from the same `resolved_balance`. No semantic drift. |

---

## 10. Rollback

Each phase is independently revertible:

| Phase | Rollback |
|---|---|
| A | Revert the `public_router.py` payload addition and the `service.py` webhook-handler diff. PIs revert to metadata-only on creation; webhook reverts to metadata-only on read. Existing PIs created during Phase A still carry both fields, so they settle correctly under either code path. |
| B | No code change, just monitoring. Rollback = "wait longer". |
| C | Revert the deletion of `metadata[surcharge_amount]` and the fallback-removal. Phase A code re-emerges. Existing PIs created during Phase C carry only `amount_details` — the re-introduced fallback never fires for them, but they still settle correctly via the (now re-emerged) primary `amount_details` read path. |

No database migration, no schema change, no data backfill, no frontend release, no mobile release. The entire change ships as backend application code edits.

---

## 11. Acceptance criteria (definition of done)

1. `/update-surcharge` requests to Stripe carry `amount_details[surcharge][amount]=<cents>` exactly equal to `Payment.surcharge_amount × 100`.
2. The `payment_intent.succeeded` webhook reads the surcharge from `amount_details.surcharge.amount` and stores it on `Payment.surcharge_amount` unchanged.
3. Customer's payment-page experience (UI, totals, disclosure) is byte-identical to the pre-migration build.
4. Stripe Dashboard → PaymentIntent view shows "Surcharge" as a structured field with the same dollar value the customer saw on our payment page.
5. Stripe Sigma `amount_details_surcharge_amount` column populates for all new PIs.
6. A test partial refund correctly prorates the surcharge per Stripe's refund proration.
7. Receipt email content and `Payment.surcharge_amount` reporting are unchanged.
8. No schema change, no frontend change, no mobile change, no UI change for admins or customers.
9. After Phase C, `grep -rn "metadata\[surcharge_amount\]" app/` returns zero matches in write sites (the metadata key may still appear in read-side legacy comments or audit-log fields if any — verify with grep before declaring done).

---

## 12. Files that will change (precise inventory)

| File | Phase | What |
|---|---|---|
| `app/modules/payments/public_router.py` | A, C | Add `amount_details[surcharge][amount]` to the Stripe modify payload (Phase A). Remove `metadata[surcharge_amount]` from the same payload (Phase C). |
| `app/modules/payments/service.py` | A, C | Webhook handler reads `amount_details.surcharge.amount` first, falls back to `metadata.surcharge_amount` (Phase A). Remove the metadata fallback (Phase C). |
| `tests/test_surcharge_native_stripe_payload.py` | A | NEW — asserts outgoing payload shape. |
| `tests/test_surcharge_webhook_native_parse.py` | A | NEW — asserts webhook reads native field. |
| `tests/test_surcharge_webhook_legacy_fallback.py` | A then deleted in C | NEW — asserts legacy fallback works during transition. |
| `tests/test_surcharge_refund_proration.py` | B | NEW — asserts refund proration is recorded correctly. |

### Files explicitly NOT touched

- `app/modules/payments/surcharge.py` — calculation engine, no change.
- `app/modules/payments/models.py` — `Payment.surcharge_amount` column, no change.
- `app/integrations/stripe_connect.py` — `create_payment_intent` initial PI create, no change (surcharge is set on the subsequent `update-surcharge`, not at create time).
- `frontend/src/pages/public/InvoicePaymentPage.tsx` — no frontend change.
- Mobile app — no change.
- Admin settings pages (`org.settings.surcharge_*`) — no change.
- Database — no migration.

---

## 13. CHANGELOG entry (drafted)

```markdown
### Changed
- **Stripe-native surcharge.** Outbound `PaymentIntent` updates now carry the
  surcharge in Stripe's structured `amount_details[surcharge][amount]` field
  in addition to (Phase A) and eventually instead of (Phase C) the legacy
  `metadata[surcharge_amount]` field. Customer-facing dollar amounts, disclosure
  UI, our `Payment.surcharge_amount` column, and the admin settings flow are
  unchanged. Stripe-hosted receipts now show surcharge as a structured line
  item; Stripe Sigma's `amount_details_surcharge_amount` column now populates;
  refunds auto-prorate the surcharge per card-network rules.
```

PATCH bump per [versioning-and-changelog.md](.kiro/steering/versioning-and-changelog.md): no API contract change, no breaking change.
