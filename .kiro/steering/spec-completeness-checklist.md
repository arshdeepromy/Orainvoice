---
inclusion: manual
---

# Spec Completeness Checklist — Preventing Frontend/UX Gaps

This steering doc is loaded when creating or reviewing feature specs. It ensures that every spec design document includes enough frontend detail to be implementable without ambiguity — preventing the class of gaps where backend is well-specified but frontend components, navigation, and user workflows are underspecified.

## The Problem

Specs that focus on backend APIs and data models but skip frontend component breakdown lead to:
- Missing UI components discovered during implementation
- Unclear user workflows ("where does this button go?")
- Features that are technically complete but inaccessible from the GUI
- Forgotten navigation items, route registrations, and lazy imports

## Mandatory Design Document Sections

Every design document for a feature with frontend UI MUST include these sections:

### 1. Navigation & Access

- [ ] WHERE in the existing navigation does the user access this feature? (sidebar item, header button, settings tab, etc.)
- [ ] WHAT is the exact nav item label and which section does it go under?
- [ ] IS the nav item always visible or conditionally shown (role, module, feature flag)?
- [ ] WHAT routes need to be registered in App.tsx?
- [ ] WHAT lazy imports are needed?
- [ ] IS there a route guard (RequireAuth, RequireGlobalAdmin, RequireOrgAdmin, ModuleRoute)?

### 2. Frontend Component Tree

For every screen/page in the feature, document:

- [ ] Component filename and location (`frontend/src/pages/...` or `frontend/src/admin/...`)
- [ ] Parent layout (OrgLayout, AdminLayout, standalone)
- [ ] Child components (modals, panels, drawers, toolbars)
- [ ] State management approach (local useState, context, URL params)
- [ ] API calls made (which endpoints, when)

### 3. User Workflow Trace

For every user action the feature supports, trace the full flow:

```
User clicks X → Component Y renders → API call Z → Response updates state → UI shows result
```

Common actions to trace:
- [ ] First-time access (empty state)
- [ ] Create/Add flow
- [ ] Edit flow
- [ ] Delete/Remove flow
- [ ] Save (draft vs publish vs auto-save)
- [ ] Error states (validation, network, conflict)
- [ ] Success feedback (toast, redirect, inline message)
- [ ] Navigation away with unsaved changes

### 4. Panel/Modal/Drawer Inventory

For every overlay UI element:
- [ ] What triggers it? (button click, menu item, keyboard shortcut)
- [ ] What does it contain? (form fields, lists, previews)
- [ ] How does it close? (X button, backdrop click, Escape key, save action)
- [ ] What happens on close with unsaved changes?

### 5. Toolbar/Action Bar Specification

If the feature has a toolbar or action bar:
- [ ] What buttons/controls does it contain?
- [ ] What is the layout (left-aligned, right-aligned, split)?
- [ ] Which buttons are always visible vs conditionally shown?
- [ ] What loading/disabled states do buttons have?

### 6. List/Table Specification

If the feature has a list or table view:
- [ ] What columns/fields are shown?
- [ ] Is there search? What fields does it search?
- [ ] Is there filtering? What filter options?
- [ ] Is there sorting? What sort options?
- [ ] Is there pagination? What page size?
- [ ] What is the empty state?
- [ ] What row actions are available (edit, delete, duplicate, etc.)?
- [ ] How are row actions triggered (inline buttons, context menu, swipe)?

### 7. Error & Edge Case UI

- [ ] What does the user see on API error (network failure, 500)?
- [ ] What does the user see on validation error (422)?
- [ ] What does the user see on conflict (409)?
- [ ] What does the user see on unauthorized (403)?
- [ ] What does the user see on not-found (404)?
- [ ] What does the user see during loading?
- [ ] What does the user see when data is empty?

### 8. Integration Points with Existing UI

- [ ] Does this feature add items to existing navigation (sidebar, header, settings tabs)?
- [ ] Does this feature add actions to existing pages (buttons on other pages)?
- [ ] Does this feature modify existing components (adding fields, columns, badges)?
- [ ] Does this feature need to communicate with other features (contexts, events, shared state)?

## Quick Validation Questions

Before considering a design document complete, ask:

1. **Can I draw every screen?** If not, the component breakdown is incomplete.
2. **Can I trace every user action from click to result?** If not, the workflow is underspecified.
3. **Do I know where every button goes?** If not, the toolbar/action specification is missing.
4. **Do I know what happens on every error?** If not, the error handling UI is missing.
5. **Do I know how to navigate TO this feature?** If not, the navigation section is missing.
6. **Do I know how to navigate AWAY from this feature?** If not, the unsaved-changes guard is missing.

## Example: Minimum Frontend Section for a CRUD Feature

```markdown
## Frontend Component Breakdown

### Navigation
- Sidebar item: "Page Editor" under "Tools" section in AdminLayout
- Route: `/admin/page-editor` (list), `/admin/page-editor/:pageKey` (edit)
- Guard: RequireGlobalAdmin
- Lazy imports: PageEditorList, PageEditorEdit

### Pages
1. **PageEditorList** (`frontend/src/admin/page-editor/pages/PageEditorList.tsx`)
   - Layout: AdminLayout
   - API: GET /api/v2/admin/page-editor/pages
   - Features: search, filter by origin/state, pagination (20/page)
   - Row actions: Edit, Duplicate, Delete (editor-only), Revert (hand-coded)
   - Empty state: "No pages yet. Hand-coded pages will appear after first app restart."
   - "New Page" button → opens CreatePageModal

2. **PageEditorEdit** (`frontend/src/admin/page-editor/pages/PageEditorEdit.tsx`)
   - Layout: AdminLayout (but Puck takes over the main content area)
   - API: GET page, PUT draft, POST publish, POST preview
   - Toolbar: [Page Title] [Save Draft] [Preview] [Publish] [Settings ⚙️] [History 🕐]
   - Panels: PageSettingsDrawer (right), RevisionHistoryDrawer (right), MediaLibraryModal
   - Auto-save: 30s debounce, conflict detection (409 → warning banner)
   - Concurrent edit: advisory lock warning banner at top

### Modals/Panels
- CreatePageModal: title, slug, template picker, meta fields → POST /pages
- PageSettingsDrawer: slug, noindex, meta title/desc, canonical, OG, JSON-LD → PUT /settings
- RevisionHistoryDrawer: list of versions, View/Revert buttons
- MediaLibraryModal: grid of uploaded images, upload button, search, select → returns asset ID
- DeleteConfirmModal: "Type page title to confirm" pattern
- ConflictWarningBanner: "Draft updated by another session. Reload?"
- ConcurrentEditBanner: "Being edited by {email}. Changes may be overwritten."
```

## When to Apply This Checklist

- During design document creation (before generating tasks)
- During design review (before approving for implementation)
- During task generation (verify every component has a corresponding task)
- During implementation review (verify nothing was skipped)
