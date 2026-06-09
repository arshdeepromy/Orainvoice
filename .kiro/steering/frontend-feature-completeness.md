---
inclusion: auto
---

# Frontend Feature Completeness — Preventing Incomplete Pages

## Problem Statement

A page can "work" (renders without errors, calls an API, shows data) but still be incomplete from a user perspective. The frontend gaps we repeatedly miss:

1. **Page layout** — No `.page` / `.page-wide` wrapper → content touches screen edges
2. **Missing form sections** — Only a subset of the backend's config fields have UI controls
3. **No filter/search controls** — Table renders data but user can't narrow results
4. **No action buttons on rows** — Data is displayed but no way to act on it (approve, reject, lock, edit)
5. **No confirmation modals** — Destructive actions fire without user confirmation
6. **No collapsible/secondary sections** — Spec describes sub-sections that are simply absent
7. **No empty states** — Page shows nothing instead of a helpful message
8. **No loading skeletons** — Page is blank during fetch instead of pulsing
9. **No error states** — API failure results in permanent blank screen

## Mandatory Checklist for Every New Frontend Page

Before marking a frontend page task `[x]`, verify ALL of the following:

### Layout & Styling
- [ ] Page wrapped in `.page` or `.page page-wide` (matches PayRunPage / StaffList pattern)
- [ ] Page header uses `.page-head` with `.eyebrow` section label + `h1` + `.sub` description
- [ ] Header has an action area (Settings button, Add/New button, or export)
- [ ] Content uses standard card pattern: `rounded-card border border-border bg-card shadow-card`

### Every Form/Settings Page Must Have
- [ ] One form control for EVERY field in the backend schema (not a subset)
- [ ] Labels + help text on every input
- [ ] `disabled` state for read-only users
- [ ] Save button (sticky bottom bar pattern)
- [ ] Success/error feedback after save
- [ ] Values loaded FROM the API on mount (not just defaults)
- [ ] Values round-trip: change → save → reload → value persists

### Every List/Table Page Must Have
- [ ] Search input (client-side or server-side filter by name/title)
- [ ] At least one status/category filter control
- [ ] Column headers with appropriate alignment (left for text, right for numbers)
- [ ] Per-row action buttons appropriate to the row's state
- [ ] Empty state with icon + message + guidance text
- [ ] Loading skeleton (animate-pulse) during initial fetch
- [ ] Error state with retry button on API failure

### Every Action Must Have
- [ ] A visible button/control to trigger it
- [ ] Confirmation modal for destructive actions (delete, lock, clock-out, reject)
- [ ] Loading state on the button while the action is in-flight
- [ ] Feedback after success (refresh data, show toast, update badge)
- [ ] Error handling (show message, don't leave page in broken state)

### Modals Must Have
- [ ] Backdrop (fixed inset-0 bg-ink/50)
- [ ] Centered card (rounded-card bg-card shadow-pop)
- [ ] Title + description
- [ ] Form content or confirmation message
- [ ] Cancel + Confirm buttons (right-aligned)
- [ ] Escape key or backdrop click closes (for non-destructive modals)
- [ ] Loading/disabled state on confirm button during API call

### Content Sections
- [ ] If spec mentions N sections → page MUST render N sections (not N-2)
- [ ] Sections that can be empty should still render with a collapsed/empty indicator
- [ ] Collapsible sections have a toggle button with chevron animation
- [ ] Each section has a header (title + description) even when content is empty

## Pattern Reference

When implementing a new page, refer to these existing pages for the correct patterns:

| Pattern | Reference file |
|---------|---------------|
| Page layout + header | `PayRunPage.tsx` (`.page page-wide` + `.page-head`) |
| Summary KPI cards | `PayRunPage.tsx` (KpiCard grid) |
| Table with filters | `StaffList.tsx` (search + segmented filter + table) |
| Settings form | `TimesheetSettings.tsx` (sections + save bar) |
| Confirmation modal | `ClockedInTab.tsx` (clock-out modal) |
| Empty state | `TimesheetsTab.tsx` (icon + title + description) |
| Collapsible section | `ClockedInTab.tsx` (On Leave Today / Rostered Not Clocked In) |

## Anti-Patterns to Avoid

| Anti-pattern | What to do instead |
|---|---|
| `<div className="space-y-4">` as page root | Wrap in `<div className="page page-wide">` |
| Table with only "View" link per row | Add status-appropriate action buttons |
| Settings page with 3 of 6 backend fields | Render ALL fields from the schema |
| Hardcoded "Current Period" / "Previous" | Fetch real data or keep as placeholder WITH a comment explaining why |
| Modal that fires API without loading state | Add `disabled={saving}` + spinner text |
| Page with no `useEffect` cleanup | Every fetch gets an AbortController |
| Form that saves but never loads | `useEffect` on mount fetches + populates form state |
