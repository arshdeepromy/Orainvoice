---
inclusion: auto
---

# Versioning & Changelog

OraInvoice follows [Semantic Versioning](https://semver.org/) (MAJOR.MINOR.PATCH) across all three packages. The version must be kept in sync across:

- `pyproject.toml` → `version` field (backend)
- `frontend/package.json` → `version` field (web frontend)
- `mobile/package.json` → `version` field (mobile frontend)

## When to Bump

| Change type | Version bump | Examples |
|---|---|---|
| Breaking API changes, major redesigns, data model overhauls | MAJOR (X.0.0) | Removing an API endpoint, changing auth flow, DB schema rewrite |
| New features, new endpoints, new pages, new modules | MINOR (x.Y.0) | Setup guide, mobile dashboard redesign, new customer edit screen |
| Bug fixes, styling tweaks, steering doc updates, test additions | PATCH (x.y.Z) | Fix double-prefix URLs, fix modal width, hide incomplete fields |

## How to Bump

1. Update the version in all three files listed above
2. Add an entry to `CHANGELOG.md` (see format below)
3. Include the version bump in the same commit as the feature/fix, or as a dedicated version bump commit

## CHANGELOG Format

Maintain `CHANGELOG.md` in the project root. Newest entries at the top.

```markdown
## [1.1.0] - 2026-04-26

### Added
- Setup guide: question-driven module onboarding replacing wizard step 5
- Mobile dashboard: Zoho-style with receivables, transactions, income/expense chart
- Mobile customer screens: list with avatars, profile with quick actions, edit screen
- Setup wizard auto-redirect for new orgs on first login
- Expenses page: list-first layout with modal for creating

### Changed
- Setup wizard: removed Country/Trade steps (captured during signup)
- Structured address fields in wizard matching Settings page

### Fixed
- ISSUE-113: v2 double-prefix in 16 files
- Setup wizard country defaults crash (double-encoded JSONB)
- Watch-build deleting lazy-loaded chunks
- NZ IRD validation accepting 8-9 digits with auto-dash formatting
```

## Rules

- **Never skip a version bump** when pushing a feature (MINOR) or fix (PATCH) to main
- **All three version files must match** — if they drift, the next person to notice should fix it
- **Tag releases** for production deploys: `git tag v1.1.0 && git push --tags` (optional but recommended)
- The version is displayed nowhere in the UI currently — but it's used for tracking what's deployed where
