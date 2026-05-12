# Workshop Landing Page — SEO Strategy

**Status:** Implemented
**Page:** `/workshop` (aliases: `/mechanics`, `/garage`)
**Owner:** Frontend / Platform
**Last updated:** 2026-05-12

This document captures the competitor SEO analysis that informed the design of
`frontend/src/pages/public/WorkshopPage.tsx`, plus the keyword clusters,
NZ-specific positioning gaps, and content strategy behind the page.

The goal: rank in the NZ SERP for workshop / mechanic / garage software
queries, alongside the three incumbents below, while positioning OraInvoice on
its unique NZ-native advantages (CarJam, WOF, COF, NZ-hosted data, Xero,
GST, NZD).

---

## 1. Competitor snapshot

### 1.1 Workshop Software — `workshopsoftware.com`

| Signal | Value |
|---|---|
| Title tag | “Home” (very weak — no keyword targeting) |
| H1 | “Garage Management Software – In one easy to use system” |
| Value prop | “Software that will transform your business by managing and optimising your entire mechanic garage” |
| Key H2s | Smarter tools better results · Auto shops change for the better · Inefficiency limiting your profit and growth? · Optimise performance, maximise profits · Boost customer retention · Integrates with your entire toolkit · Transform your workshop into a profit machine · Your workshop, in the palm of your hand · Ready to streamline your workshop? |
| Feature list | Customer management · Mobile App · WorkshopPay (payments) · Online customer bookings · Job management · Vehicle Inspections · (plus integrations with accounting / CRM / DVI) |
| Trust signals | “$5.1BIL invoices generated” · “8,507,756+ invoices processed” · “30 years” · six named on-page testimonials (Ratcliff Motors, Brakes West, CB Automotive, The Battery Shop Lower Hutt, SBO Auto, Bosch Car Service) · “thousands of global workshops” |
| CTA strategy | Multiple “Book a demo” + “Download the Workshop Software App” + “Ready to streamline your workshop?” bottom CTA |
| Schema / SEO | No obvious JSON-LD on homepage; no FAQ schema; no breadcrumbs. Heavy WordPress page-builder output, lots of boilerplate, thin meta |
| Notable patterns | Heavy emotional copy (“stuck on the tools”, “daily chaos”), customer logo wall, pain-point-led sections. Targets global audience — mentions UK (£) and AU ($) figures |

### 1.2 MechanicDesk — `mechanicdesk.com.au`

| Signal | Value |
|---|---|
| Title tag | “Workshop Software - Software for Automotive, Mechanical and Electrical Workshops\|MechanicDesk” |
| H1 | (Homepage renders a pricing table; feature headings on `/features`) |
| Value prop | Cloud workshop management for AU / NZ / UK / Global |
| Key H2s | Booking Diary · Job Management · Invoicing/Quoting · Customer Management · Stock Management · Service Scheduling (reminders) · Productivity · Integrations |
| Feature list | Booking diary · Job management · Invoicing / quoting · Stock · Service reminders · Customer DB · Productivity tracking · Vehicle Visuals integration · Digital Signatures · Customized print templates · Workstation (time clocking) |
| Trust signals | Long testimonial page (separate) · “for any workshop” scalable plans · regional phone support lines (AU / NZ / UK) |
| CTA strategy | Clear pricing per plan, 14 day free trial, “Sign Up” on every plan card, “Support/Demo” nav item |
| Pricing | Starter $85 / Small $115 / Team $150 / Large $250 (AUD + GST, per user caps with $15/m overage, $0.10 per SMS) |
| Schema / SEO | Strong title keyword stacking (“Workshop Software - Software for Automotive, Mechanical and Electrical Workshops”). Pricing visible on homepage — good for decision-stage searches. No visible FAQ schema |
| Notable patterns | Feature-first homepage structure, transparent pricing up front, multi-country currency selector (AU / NZ / UK / Global) |

### 1.3 Auxo Software — `auxosoftware.com`

| Signal | Value |
|---|---|
| Title tag | “Home - Auxo Software” (weak — no keyword targeting) |
| H1 | “We make software to drive your business” |
| Value prop | Industry specialist solutions: Workshop / Dealership / Fleet / Rental / Parts |
| Key H2s | Workshop · Dealership · Fleet · Rental · Inventory · Importer (product-family hub) |
| Product lines | Auxo Workshop (cloud, small/medium) · SAM Workshop Management (desktop, medium/large) · Orion Workshop Management (desktop, multisite/larger) · Orion Dealer · Systime Dealer (96,000 dealerships globally) · Orion Fleet · Orion Rental · Orion Inventory · Systime Importer |
| Feature list | Not on homepage — each product has its own page. Workshop product emphasises cloud-based, small-to-medium teams |
| Trust signals | “Used globally by 96,000 dealerships” (Systime) · multi-product enterprise-grade positioning |
| CTA strategy | Product-catalogue style homepage — click through to each product page for demo/trial |
| Schema / SEO | Homepage is effectively a product hub page — keyword-dilute. Individual product pages (`/auxo-workshop`) likely carry the ranking SEO |
| Notable patterns | Enterprise framing, multiple products, global customer base. Weak homepage keyword targeting but deep product funnel below |

### 1.4 Summary comparison table

| Dimension | Workshop Software | MechanicDesk | Auxo Software | **OraInvoice (target)** |
|---|---|---|---|---|
| Primary keyword in H1 | “Garage Management Software” | (generic on HP; feature-led on /features) | (generic corporate) | **“Workshop Software for NZ Mechanics, Auto Repair & Service Centres”** |
| Geo focus | Global (AU / UK / US) | AU primary, NZ / UK switcher | Global / enterprise | **NZ-only, 100% NZ hosted** |
| Pricing transparency | Hidden behind demo | **Visible on homepage** | Hidden, per-product | **Visible in card ($60 NZD/mo)** |
| Trust stats | “$5.1BIL invoices” | — | “96,000 dealerships” | NZ-hosted, testimonial-ready |
| Pain-point narrative | Strong (“inefficiency”, “chaos”) | Feature-list led | Product-catalogue led | Mix: NZ-specific pains (WOF expiry, CarJam) |
| NZ-specific features | None | Currency switcher only | None | **CarJam integration · WOF / COF tracking · NZ GST · NZ hosted** |
| Structured data | Minimal | Minimal | Minimal | **SoftwareApplication + FAQPage + BreadcrumbList + AggregateRating** |
| FAQ / AEO targeting | No FAQ schema | No FAQ schema | No FAQ schema | **FAQPage JSON-LD with 8 Q/A** |
| Xero integration mentioned | Yes | Yes | — | **Yes (prominent)** |
| Mobile app story | Workshop Software Mobile App | App available | Varies per product | **Mobile companion app** |
| CTA primary | “Book a demo” | “Sign Up” / “Free Trial” | “Contact” | **“Start 30-Day Free Trial” + “Book a Demo”** |

---

## 2. Keyword clusters

Keywords below are grouped by search intent. The page targets the primary
cluster in the H1 and meta description, covers the secondary cluster in H2s
and feature bullets, and earns long-tail traffic through the FAQ block.

### 2.1 Primary keywords (head terms, high intent)

- workshop software nz
- workshop management software nz
- auto workshop software new zealand
- garage management software nz
- mechanic software nz
- automotive workshop software
- car service software nz
- workshop invoicing software
- mechanic invoicing nz
- WOF reminder software
- CarJam integration

### 2.2 Secondary keywords (modifier + product)

- cloud workshop management nz
- online workshop software nz
- mechanic shop software
- car repair shop software nz
- auto repair software
- workshop job card software
- mechanic booking software nz
- WOF tracking software
- COF compliance software
- workshop software with Xero
- workshop software with CarJam

### 2.3 Long-tail keywords (question / comparison intent — FAQ schema territory)

- best workshop software for nz mechanics
- what is workshop management software
- how does CarJam integration work
- can i import my customer list from excel
- does workshop software work on mobile or tablet
- can i send WOF reminders by sms
- does workshop software integrate with xero
- is workshop software secure where is my data stored
- small workshop software vs 10 bay shop
- auto shop management nz
- workshop app for mechanics nz

### 2.4 Keyword density approach

- **H1** contains “Workshop Software”, “NZ”, “Mechanics”, “Auto Repair”, “Service Centres”.
- **Hero sub-head** contains “CarJam”, “WOF/COF”, “NZ hosted”, “NZD”.
- **Section H2s** each own one cluster (features → primary; made for NZ → CarJam/WOF/GST; comparison → pain keywords; FAQ → long-tail).
- Each feature `<h3>` is a keyword phrase in itself (“Vehicle lookup with CarJam”, “WOF & COF expiry reminders”, “Xero accounting integration”).

---

## 3. Gap analysis — what competitors miss that we can own

1. **No competitor positions explicitly as NZ-first.**
   Workshop Software is UK/AU/global. MechanicDesk is AU with a NZ phone line and currency toggle. Auxo is a multi-product global umbrella. **None of them lead with “built for NZ, hosted in NZ, WOF + COF + CarJam first-class citizens.”** That is our wedge.

2. **No visible CarJam integration.**
   CarJam is the de-facto NZ vehicle lookup (rego → make/model/VIN/WOF/reg/odo history). Competitors rely on generic VIN decoders. We have CarJam as a core module and should keyword-target “workshop software with CarJam” and “CarJam integration NZ”.

3. **No WOF / COF-specific messaging.**
   WOF (Warrant of Fitness, light vehicles, 6 / 12 month cycle) and COF (Certificate of Fitness, heavy vehicles, 6 month cycle) are NZ-specific legal inspections with expiry dates that workshops need to track and remind customers about. Competitors use generic “service reminders”; we can rank for “WOF reminder software”, “COF expiry tracking”, “WOF tracking software” directly.

4. **No transparent NZD pricing.**
   MechanicDesk is the only competitor with visible pricing and it is AUD + GST, $85 / $115 / $150 / $250. Our single $60 NZD flat-rate Mech Pro plan is materially cheaper and NZD-priced — a powerful price-anchor on the comparison section.

5. **No trade-family mix story.**
   Our platform supports automotive + general invoicing today with plumbing, electrical, and construction variants sharing the same core. Competitors are workshop-only, locking customers in if their business mixes in light commercial or trades work. We can speak to “mixed trade” businesses without cannibalising messaging.

6. **FAQ / AEO (answer-engine) schema.**
   None of the three competitors we analysed emit `FAQPage` JSON-LD on their homepage. Adding 8 well-targeted FAQ entries with structured data is a near-free rich-result opportunity in 2025/26 SERP layouts, and ChatGPT / Perplexity / Gemini prefer structured FAQ answers when surfacing product recommendations.

7. **Aggregate rating placeholder.**
   `AggregateRating` schema with at least a handful of real reviews is a quick win for star ratings in SERP. We emit a placeholder schema now, to be filled in once we collect >5 verified testimonials.

8. **Breadcrumbs.**
   Competitors do not emit `BreadcrumbList` JSON-LD. We already do on `/trades` and `/privacy`; adding it on `/workshop` lets Google render breadcrumb trails under the SERP result, which increases CTR.

9. **Pain-point-led hero without being whiny.**
   Workshop Software's copy (“stuck on the tools”, “daily chaos”) converts well but is very emotive and generic. Our comparison section (“Why mechanics switch to OraInvoice”) uses the same narrative structure but grounds each bullet in a concrete NZ workflow: “Stop retyping rego numbers — CarJam pulls make/model/VIN in two seconds.” That is both specific and SEO-rich.

---

## 4. Content strategy for `/workshop`

Target: ~1,900 — 2,300 words, eight on-page sections, single `<h1>`, one `<h2>` per section, `<h3>` for feature cards. Page budget: the full render must stay inside existing Tailwind component style to avoid design drift from `LandingPage.tsx` and `TradesPage.tsx`.

### 4.1 Section outline

1. **Hero** — H1, sub-head, dual CTA (“Start 30-Day Free Trial” primary, “Book a Demo” secondary, “See pricing” tertiary). 100% NZ Hosted badge. CSS-only hero illustration (no stock photos — matches existing landing page style).
2. **Key features grid** — 11 `<article>` feature cards under one H2, each with an emoji icon + `<h3>` title + short description. Feature set chosen to match competitor coverage (bookings, job cards, invoicing, parts, mobile, kiosk, SMS reminders) while adding our NZ-specific wedges (CarJam, WOF/COF, Xero, multi-branch).
3. **Made for NZ** — 5 trust signals specific to NZ (hosted in NZ, GST built-in, CarJam integration, WOF/COF workflow, NZD pricing).
4. **Why mechanics switch to OraInvoice** — comparison section without naming competitors. Six pain-point bullets mapped to our solution. Each bullet is a long-tail keyword magnet (“sick of retyping rego numbers…”, “tired of manually texting WOF reminders…”).
5. **Pricing card** — single $60 NZD / month plan, feature checklist (dedupes with LandingPage Mech Pro Plan — one transparent price point, no dark patterns).
6. **FAQ** — 8 Q/A pairs wired up with `FAQPage` JSON-LD. Questions chosen from the long-tail keyword cluster.
7. **Testimonials** — three placeholder cards using the same `<blockquote>` pattern as LandingPage. Marked with a `TODO:` comment for real customer quotes.
8. **Final CTA** — single strong “Try OraInvoice free for 30 days” section anchored in the indigo-slate hero gradient for visual bracketing.

### 4.2 Structured data emitted

- `SoftwareApplication` with `offers` ($60 NZD / month), `audience = automotive workshops in NZ`, feature list, `aggregateRating` placeholder (with `reviewCount: 0` acceptable until we collect reviews — we emit it but comment it out if Google flags a “not enough reviews” warning).
- `FAQPage` built from the 8 Q/A pairs on the page (exact text match to on-page content — no schema / content mismatch).
- `BreadcrumbList`: Home → Workshop Software.
- `Review` entries inside testimonials where we have real (non-placeholder) quotes only. Placeholder testimonials deliberately do not emit `Review` schema to avoid Google spam policy hits.

### 4.3 Internal linking

- Hero “See pricing” → `#pricing` anchor on this page.
- “Multi-trade? See the trades we support” → `/trades`.
- Footer / nav `Privacy` → `/privacy`.
- Final CTA → `/signup`.
- Demo request CTA opens the shared `DemoRequestModal` component.

### 4.4 External linking

- No outbound links on the page today. If we add partner links (CarJam, Xero) they must use `rel="noopener noreferrer"` and `target="_blank"` for consistency with the rest of the public pages.

### 4.5 Image / media strategy

- No paid stock photos. Use emoji glyphs (🚗 🔧 📅 📱 🇳🇿) with `aria-hidden="true"` and a descriptive alt where an actual `<img>` is unavoidable (e.g. the NZ flag). This matches `LandingPage.tsx` and `TradesPage.tsx` exactly and keeps Lighthouse LCP within budget.
- Future: commission one real “NZ workshop” photo for the hero and export as WebP + AVIF with `loading="eager"` and an explicit `width` / `height` to preserve CLS.

### 4.6 Ranking hygiene

- Canonical URL is always `https://one.oraflows.co.nz/workshop` regardless of whether the visitor arrived via `/mechanics`, `/garage` or `/workshop`. This consolidates link-equity to one URL.
- `/mechanics` and `/garage` are alias routes that issue a client-side `<Navigate to="/workshop" replace />`. Google treats same-origin client-side redirects as follows in practice, and the canonical tag seals the deal.
- `robots.txt` explicitly `Allow: /workshop` (and the aliases) so crawlers that honour robots directives are not accidentally blocked by the existing wildcard `Disallow` rules.
- `sitemap.xml` lists only `/workshop` (the canonical), not the aliases.

---

## 5. Measurement plan (post-launch)

| Signal | Tool | Baseline (T0) | Target (T+90 days) |
|---|---|---|---|
| Indexed | GSC → URL Inspection | “Discovered — not indexed” | “URL is on Google” |
| Impressions on “workshop software nz” | GSC → Performance → Queries | 0 | ≥ 200 / week |
| Clicks on primary keywords | GSC → Performance | 0 | ≥ 30 / week |
| Avg position on “workshop software nz” | GSC | n/a | top 10 |
| Rich result: FAQ | GSC → Enhancements | — | “Valid” with 0 errors |
| Rich result: SoftwareApplication | GSC → Enhancements | — | “Valid” with 0 errors |
| Bounce rate on `/workshop` | Analytics (after we install one) | — | < 60% |
| Signup conversion from `/workshop` | Server-side (utm_source = organic, landing = /workshop) | — | > 2% |

---

## 6. Follow-up pages (next quarter)

Once `/workshop` is indexed and ranking for the primary cluster, the same
pattern can ship for other trade families. Each gets its own narrow keyword
cluster and NZ-specific wedge:

- `/electrician-software` — EWRN certification, PrescribeD, registered electricians, electrical WOF equivalent (Electrical Safety Certificate).
- `/plumbing-software` — gasfitter certification, PGDB, backflow prevention, drainage reports.
- `/construction-software` — progress claims (payment schedules, Construction Contracts Act 2002), retentions, variations, builders' risk.
- `/hospitality-software` — POS, floor plan, kitchen display, table management — already covered by existing modules, just needs a dedicated landing page.
- `/franchise-software` — multi-location, stock transfers, consolidated reporting — niche but low competition.
- `/tradies-nz` — umbrella trade family page targeting the generic “tradie app NZ” cluster, linking down to each specialist page.

All of these reuse the same seven-section structure (hero → features → NZ advantages → switch story → pricing → FAQ → testimonials → CTA), the same JSON-LD schemas, and the same `LandingHeader` / `LandingFooter` components.

---

## 7. How we verify the page in Google Search Console

1. Confirm the page is live: `curl -I https://one.oraflows.co.nz/workshop` → `200 OK`, no `X-Robots-Tag: noindex` header.
2. Confirm aliases redirect: visit `/mechanics` and `/garage` → browser URL becomes `/workshop`.
3. Confirm canonical: view source of `/workshop` → `<link rel="canonical" href="https://one.oraflows.co.nz/workshop">`.
4. Confirm structured data: [Rich Results Test](https://search.google.com/test/rich-results) on `https://one.oraflows.co.nz/workshop` — should detect `SoftwareApplication`, `FAQPage`, `BreadcrumbList`.
5. In GSC: **URL Inspection** → `https://one.oraflows.co.nz/workshop` → “Request indexing”.
6. In GSC: **Sitemaps** → re-submit `sitemap.xml` (now containing `/workshop`).
7. In GSC after 3–7 days: **Performance → Queries** — filter `page = /workshop`, look for first impressions on the primary keyword cluster.
8. In GSC: **Enhancements → FAQ** and **Enhancements → Products** — should show `/workshop` as a valid item with zero errors.
