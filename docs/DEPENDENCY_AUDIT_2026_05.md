# OraInvoice Dependency Audit — May 2026

**Audit Date:** 2026-05-28  
**App Version:** 1.9.5  
**Auditor:** Automated (Kiro)

---

## Executive Summary

| Layer | Total Deps | Outdated | Critical | High | Medium | Low |
|-------|-----------|----------|----------|------|--------|-----|
| Python Backend | 26 | 5 | 0 | 0 | 2 | 3 |
| Web Frontend | 28 | 18 | 0 | 1 | 5 | 12 |
| Mobile App | 31 | 30 | 1 | 1 | 7 | 21 |
| **Totals** | **85** | **53** | **1** | **2** | **14** | **36** |

**Overall Health:** Good. No known security vulnerabilities detected. One major version bump available (Capacitor 7→8). Most updates are minor/patch level. The project is well-maintained with dependencies generally within 1-2 minor versions of latest.

---

## Python Backend Dependencies

**Container:** `invoicing-app-1`  
**Runtime:** Python 3.11, FastAPI

### Outdated Packages

| Package | Installed | Latest | Bump Type | Priority | Risk |
|---------|-----------|--------|-----------|----------|------|
| certifi | 2026.4.22 | 2026.5.20 | Patch (CA bundle) | LOW | None — CA certificate bundle update |
| PyJWT | 2.12.1 | 2.13.0 | Minor | MEDIUM | Low — new features, no breaking changes expected |
| greenlet | 3.5.0 | 3.5.1 | Patch | LOW | None — SQLAlchemy transitive dep |
| aiohappyeyeballs | 2.6.1 | 2.6.2 | Patch | LOW | None — async DNS resolution fix |
| wheel | 0.45.1 | 0.47.0 | Minor | MEDIUM | None — build tool only, not runtime |

### Up-to-Date Highlights

The following critical packages are current or very close to latest:

| Package | Installed | Min Required | Status |
|---------|-----------|-------------|--------|
| FastAPI | 0.136.1 | ≥0.135.3 | ✅ Current |
| SQLAlchemy | 2.0.49 | ≥2.0.49 | ✅ Current |
| Pydantic | 2.13.4 | ≥2.12.5 | ✅ Current |
| cryptography | 48.0.0 | ≥46.0.7 | ✅ Current |
| uvicorn | 0.47.0 | ≥0.44.0 | ✅ Current |
| WeasyPrint | 68.1 | ≥62.0 | ✅ Current |
| Pillow | 12.2.0 | ≥12.2.0 | ✅ Current |
| Stripe | 15.1.0 | ≥15.0.1 | ✅ Current |
| Alembic | 1.18.4 | ≥1.18.4 | ✅ Current |

### Python Assessment

The Python backend is in excellent shape. All security-critical packages (cryptography, certifi, PyJWT) are at most one minor version behind. No CVEs identified for installed versions.

---

## Web Frontend Dependencies

**Build:** Vite 8, TypeScript 6, React 19  
**Package Manager:** npm

### Outdated Packages

| Package | Current | Latest | Bump | Priority | Notes |
|---------|---------|--------|------|----------|-------|
| axios | 1.15.0 | 1.16.1 | Minor | HIGH | HTTP client — may contain security patches |
| firebase | 12.12.0 | 12.13.0 | Minor | MEDIUM | Auth provider — keep current for security |
| react | 19.2.5 | 19.2.6 | Patch | MEDIUM | Core framework patch |
| react-dom | 19.2.5 | 19.2.6 | Patch | MEDIUM | Must match react version |
| react-router-dom | 7.14.0 | 7.15.1 | Minor | MEDIUM | Routing — bug fixes |
| @stripe/react-stripe-js | 6.1.0 | 6.4.0 | Minor | MEDIUM | Payment UI — 3 minor versions behind |
| @stripe/stripe-js | 9.1.0 | 9.6.0 | Minor | MEDIUM | Payment SDK — 5 minor versions behind |
| tailwindcss | 4.2.2 | 4.3.0 | Minor | LOW | CSS framework |
| @tailwindcss/postcss | 4.2.2 | 4.3.0 | Minor | LOW | Must match tailwindcss |
| vite | 8.0.8 | 8.0.14 | Patch | LOW | Build tool patches |
| vitest | 4.1.4 | 4.1.7 | Patch | LOW | Test runner patches |
| typescript | 6.0.2 | 6.0.3 | Patch | LOW | Type checker patch |
| postcss | 8.5.9 | 8.5.15 | Patch | LOW | CSS processing patches |
| @vitejs/plugin-react | 6.0.1 | 6.0.2 | Patch | LOW | Vite plugin patch |
| fast-check | 4.6.0 | 4.8.0 | Minor | LOW | Property testing — dev only |
| jsdom | 29.0.2 | 29.1.1 | Minor | LOW | Test environment — dev only |
| @types/node | 25.6.0 | 25.9.1 | Minor | LOW | Type definitions |
| @types/react | 19.2.14 | 19.2.15 | Patch | LOW | Type definitions |

### Frontend Assessment

No critical issues. The Stripe packages are the most notable gap (3-5 minor versions behind) — these should be updated to ensure payment flow compatibility and PCI compliance. Axios 1.16.x includes request handling improvements worth picking up.

---

## Mobile App Dependencies

**Build:** Vite 8, TypeScript 6, React 19, Capacitor 7  
**Target:** Android (Capacitor)

### Outdated Packages — CRITICAL/HIGH

| Package | Current | Latest | Bump | Priority | Notes |
|---------|---------|--------|------|----------|-------|
| @capacitor/* (all 13 plugins) | 7.x | 8.x | **MAJOR** | CRITICAL | See breaking changes below |
| axios | 1.15.2 | 1.16.1 | Minor | HIGH | HTTP client — security patches |

### Outdated Packages — MEDIUM

| Package | Current | Latest | Bump | Priority | Notes |
|---------|---------|--------|------|----------|-------|
| firebase | 12.12.1 | 12.13.0 | Minor | MEDIUM | Auth provider |
| react | 19.2.5 | 19.2.6 | Patch | MEDIUM | Core framework |
| react-dom | 19.2.5 | 19.2.6 | Patch | MEDIUM | Must match react |
| react-router-dom | 7.14.2 | 7.15.1 | Minor | MEDIUM | Routing fixes |
| @stripe/react-stripe-js | 6.3.0 | 6.4.0 | Minor | MEDIUM | Payment UI |
| @stripe/stripe-js | 9.3.1 | 9.6.0 | Minor | MEDIUM | Payment SDK |
| tailwindcss | 4.2.4 | 4.3.0 | Minor | MEDIUM | CSS framework |

### Outdated Packages — LOW

| Package | Current | Latest | Bump | Priority | Notes |
|---------|---------|--------|------|----------|-------|
| @tailwindcss/postcss | 4.2.4 | 4.3.0 | Minor | LOW | Match tailwindcss |
| @types/node | 25.6.0 | 25.9.1 | Minor | LOW | Types |
| @types/react | 19.2.14 | 19.2.15 | Patch | LOW | Types |
| @vitejs/plugin-react | 6.0.1 | 6.0.2 | Patch | LOW | Build plugin |
| fast-check | 4.7.0 | 4.8.0 | Minor | LOW | Dev only |
| postcss | 8.5.12 | 8.5.15 | Patch | LOW | CSS processing |
| vite | 8.0.10 | 8.0.14 | Patch | LOW | Build tool |
| vitest | 4.1.5 | 4.1.7 | Patch | LOW | Test runner |
| typescript | 6.0.2 | 6.0.3 | Patch | LOW | Type checker |

### Capacitor 7 → 8 Breaking Changes ⚠️

The entire Capacitor ecosystem has moved to v8. This is the most significant upgrade decision in this audit.

**Known breaking changes in Capacitor 8:**
- Minimum Android SDK raised (likely API 24+)
- Plugin API changes — all `@capacitor/*` plugins must be upgraded together
- New permission handling model for Android 14+
- Gradle 8.x required for Android builds
- Potential changes to `capacitor.config.ts` schema
- `capacitor-native-biometric` (community plugin) may not yet support Capacitor 8

**Risk Assessment:**
- All 13 Capacitor plugins must be upgraded simultaneously
- The community plugin `capacitor-native-biometric` (v4.2.0) needs compatibility verification
- Android build configuration (Gradle, SDK versions) will need updates
- Estimated effort: 1-2 days including testing on device

**Recommendation:** Defer Capacitor 8 upgrade until `capacitor-native-biometric` confirms v8 support. Continue taking v7.x patch updates (7.6.2 → 7.6.5 for core/cli/android).

---

## Prioritized Upgrade Plan

### Phase 1 — Immediate (This Sprint)

**Security & payment-related patches. Zero risk.**

| Action | Packages | Effort |
|--------|----------|--------|
| Frontend: Update Stripe | `@stripe/react-stripe-js` 6.1→6.4, `@stripe/stripe-js` 9.1→9.6 | 15 min |
| Mobile: Update Stripe | `@stripe/react-stripe-js` 6.3→6.4, `@stripe/stripe-js` 9.3→9.6 | 15 min |
| Both: Update axios | 1.15→1.16 | 10 min |
| Python: Update certifi | 2026.4→2026.5 (CA bundle) | 5 min |
| Python: Update PyJWT | 2.12→2.13 | 10 min |
| Mobile: Capacitor patch | `@capacitor/core`, `cli`, `android` 7.6.2→7.6.5 | 15 min |

**Total Phase 1 effort:** ~1 hour  
**Risk:** Very low — all minor/patch bumps within same major version

### Phase 2 — Next Sprint

**Framework patches and dev tooling.**

| Action | Packages | Effort |
|--------|----------|--------|
| Both: Update React | 19.2.5→19.2.6 (react + react-dom) | 10 min |
| Both: Update react-router-dom | 7.14→7.15 | 15 min |
| Both: Update Firebase | 12.12→12.13 | 15 min |
| Both: Update Tailwind | 4.2→4.3 (tailwindcss + @tailwindcss/postcss) | 20 min |
| Both: Update Vite | 8.0.x patches | 10 min |
| Both: Update Vitest | 4.1.x patches | 10 min |
| Frontend: Update TypeScript | 6.0.2→6.0.3 | 10 min |

**Total Phase 2 effort:** ~1.5 hours  
**Risk:** Low — all within semver-compatible ranges

### Phase 3 — Planned (Next Month)

**Major version evaluation.**

| Action | Packages | Effort | Risk |
|--------|----------|--------|------|
| Mobile: Evaluate Capacitor 8 | All 13 `@capacitor/*` plugins | 1-2 days | HIGH |
| Mobile: Verify biometric plugin | `capacitor-native-biometric` v8 compat | 2 hours | MEDIUM |

**Prerequisites for Capacitor 8:**
1. Verify `capacitor-native-biometric` has v8-compatible release
2. Update Android SDK and Gradle in `android/` project
3. Test all native features: camera, biometrics, push notifications, geolocation
4. Test on physical device (not just emulator)
5. Regression test the full kiosk flow and payment flows

---

## Breaking Change Warnings

### Capacitor 8 (NOT YET RECOMMENDED)

| Area | Impact | Mitigation |
|------|--------|------------|
| Plugin API | All plugin imports may change | Follow migration guide |
| Android SDK | Minimum API level increase | Update `android/app/build.gradle` |
| Gradle | Requires Gradle 8.x | Update `android/gradle/wrapper` |
| Biometrics | Community plugin may break | Wait for `capacitor-native-biometric` v5+ |
| Permissions | New Android 14 model | Update permission request flows |

### No Other Major Version Bumps Pending

All other packages (React, Vite, TypeScript, Tailwind) are on their latest major versions with only minor/patch updates available. No breaking changes expected.

---

## Recommended Upgrade Order

```
1. certifi (Python) — CA bundle, zero risk
2. axios (Frontend + Mobile) — HTTP security
3. @stripe/* (Frontend + Mobile) — payment compliance
4. @capacitor/core,cli,android 7.6.5 (Mobile) — patch within v7
5. PyJWT (Python) — auth token handling
6. react + react-dom (Frontend + Mobile) — framework patch
7. react-router-dom (Frontend + Mobile) — routing fixes
8. firebase (Frontend + Mobile) — auth SDK
9. tailwindcss + @tailwindcss/postcss (Frontend + Mobile) — CSS
10. vite + vitest + typescript (Frontend + Mobile) — dev tooling
11. Remaining dev dependencies (types, postcss, jsdom, fast-check)
12. [DEFERRED] Capacitor 8 migration — requires dedicated sprint
```

---

## Packages NOT Outdated (Confirmed Current)

### Python (21 of 26 packages current)
FastAPI, SQLAlchemy, asyncpg, redis, cryptography, pydantic, pydantic-settings, bcrypt, WeasyPrint, httpx, Jinja2, python-multipart, email-validator, Alembic, webauthn, pyotp, Stripe, Twilio, Pillow, python-dateutil, reportlab, requests, gunicorn, uvicorn

### Frontend (10 of 28 packages current)
@dnd-kit/core, @dnd-kit/sortable, @dnd-kit/utilities, @headlessui/react, @puckeditor/core, qrcode.react, recharts, @testing-library/jest-dom, @testing-library/react, @testing-library/user-event, fake-indexeddb

### Mobile (1 of 31 packages current)
@headlessui/react, konsta, capacitor-native-biometric

---

## Notes

- All version ranges in `package.json` use `^` (caret) — compatible with minor/patch auto-updates via `npm update`
- Python uses `>=` minimum constraints — `pip install --upgrade` will pull latest compatible
- No deprecated packages detected in any manifest
- No known CVEs for currently installed versions (checked against npm audit and pip-audit)
- The `capacitor-native-biometric` community plugin (v4.2.0) is the main blocker for Capacitor 8 migration
