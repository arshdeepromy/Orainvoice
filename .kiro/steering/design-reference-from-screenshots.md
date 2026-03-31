---
inclusion: manual
---

# Design Reference from Screenshots or Code Snippets

This steering doc is activated when the user provides a screenshot, image, Figma link, Google Sites snippet, or any external design reference to guide the visual appearance of the app.

## Core Rule: Design Only — No Feature Invention

When the user shares a screenshot or design reference, your job is strictly visual:

1. Extract the visual style, layout, spacing, colours, typography, and component patterns from the reference
2. Apply those patterns to the existing pages and components in this app
3. DO NOT add new features, buttons, fields, menu items, data columns, or functionality that appear in the reference but don't exist in our app

The reference is a design guide, not a feature spec.

## What to Extract from the Reference

Look at the reference and identify:

- Colour palette (backgrounds, text, borders, accents, hover states)
- Typography (font sizes, weights, line heights, letter spacing)
- Spacing and padding patterns (card padding, section gaps, form field spacing)
- Border radius and shadow styles
- Button styles (primary, secondary, danger — shape, padding, hover)
- Card and container styles (borders, backgrounds, shadows)
- Table styles (header bg, row hover, cell padding, border style)
- Form input styles (height, border, focus ring, label positioning)
- Sidebar/navigation patterns (width, bg colour, active state, icon style)
- Modal styles (overlay, container, header, footer)
- Badge/tag styles (colours, border radius, padding)
- Empty state patterns
- Loading state patterns

## What NOT to Do

These are hard rules. Violating them breaks the app:

- DO NOT add navigation items, sidebar links, or routes that don't exist in our app
- DO NOT add form fields, table columns, or data that our backend doesn't serve
- DO NOT add buttons or actions that have no backend endpoint
- DO NOT rename existing features to match the reference's terminology
- DO NOT remove existing features because they don't appear in the reference
- DO NOT change the data structure, API calls, or state management
- DO NOT add new dependencies or UI libraries unless explicitly asked
- DO NOT change the component's props interface or exported API

## How to Apply Design Changes

### Step 1: Identify the scope

Ask yourself: "Which existing pages/components in our app correspond to what's shown in the reference?"

Map the reference to our existing pages. If the reference shows a dashboard, apply the style to our existing dashboard — don't create a new one.

### Step 2: Apply changes through Tailwind classes

This app uses Tailwind CSS. All design changes should be made by updating Tailwind utility classes on existing JSX elements. The key files that control app-wide appearance:

- `frontend/src/index.css` — global styles, CSS variables
- `frontend/tailwind.config.js` — theme configuration (colours, fonts, spacing)
- `frontend/src/components/ui/` — shared UI components (Button, Input, Modal, Badge, etc.)
- `frontend/src/layouts/OrgLayout.tsx` — org-level sidebar and layout
- `frontend/src/layouts/AdminLayout.tsx` — admin sidebar and layout

For app-wide changes, prefer updating the shared UI components and Tailwind config rather than individual pages.

### Step 3: Maintain consistency

When changing a visual pattern, apply it everywhere:

- If you change button styles, update the Button component in `frontend/src/components/ui/Button.tsx`
- If you change card styles, update all pages that use cards
- If you change table styles, update the pattern across all list pages
- If you change the sidebar, update both OrgLayout and AdminLayout

### Step 4: Preserve all existing functionality

Before and after your changes:

- Every button must still call the same onClick handler
- Every form must still submit to the same API endpoint
- Every table must still show the same columns and data
- Every modal must still open/close the same way
- Every route must still navigate to the same page
- All conditional rendering (trade gating, feature flags, module gates) must remain intact

## Checklist Before Considering Design Changes Complete

- [ ] Only Tailwind classes and CSS were changed — no JS logic modified
- [ ] No new features, fields, columns, or actions were added
- [ ] No existing features were removed
- [ ] All existing onClick handlers, form submissions, and API calls are untouched
- [ ] Trade family gating (`isAutomotive` checks) is preserved
- [ ] Feature flag gating is preserved
- [ ] Module gate wrappers are preserved
- [ ] The design is consistent across similar pages (all list pages look the same, all forms look the same)
- [ ] Responsive behaviour still works (mobile sidebar, table scroll, form stacking)
- [ ] Dark/light mode considerations (if applicable)

## Example: Correct vs Incorrect

### Reference shows a sidebar with "Analytics", "Reports", "AI Insights"

Correct: Update the sidebar visual style (colours, spacing, icons) for our existing nav items
Incorrect: Add an "AI Insights" nav item because it appears in the reference

### Reference shows a customer table with "Revenue", "LTV", "Churn Risk" columns

Correct: Update the table header style, row hover, and cell padding to match the reference
Incorrect: Add "LTV" and "Churn Risk" columns that don't exist in our data

### Reference shows rounded buttons with gradient backgrounds

Correct: Update Button component to use rounded-full and gradient classes
Incorrect: Fine — this is purely visual, go ahead
