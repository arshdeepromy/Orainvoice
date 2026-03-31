# Platform Theme System — Design

## Architecture: CSS Custom Properties + data-theme

The theme system works by:
1. Setting `data-theme="classic"` or `data-theme="violet"` on `<html>`
2. Defining CSS custom properties for each theme in `index.css`
3. Components reference these variables via Tailwind's arbitrary value syntax or direct CSS var() usage
4. Switching theme = changing the data-theme attribute + saving to backend

### Why CSS Custom Properties
- Zero runtime overhead (browser handles it natively)
- No re-renders when theme changes (just CSS recalculation)
- Works with Tailwind via `var()` in config or arbitrary values
- Adding a theme = adding a CSS block, no JS changes

## Theme Variable Map

Each theme defines these CSS custom properties:

```css
/* Sidebar */
--sidebar-bg, --sidebar-text, --sidebar-text-muted, --sidebar-hover, --sidebar-active-bg, --sidebar-active-text, --sidebar-border

/* Primary accent */
--color-primary, --color-primary-hover, --color-primary-ring

/* Content area */
--content-bg, --card-bg, --card-border, --card-shadow, --card-radius

/* Inputs */
--input-border, --input-focus-ring, --input-radius

/* Buttons */
--btn-primary-bg, --btn-primary-hover, --btn-secondary-bg, --btn-secondary-hover, --btn-radius

/* Modal */
--modal-radius, --modal-shadow, --modal-backdrop

/* Badge */
--badge-radius

/* Transitions */
--transition-speed
```

## Theme Definitions

### Classic (current design)
```css
[data-theme="classic"] {
  --sidebar-bg: #ffffff;
  --sidebar-text: #374151;
  --sidebar-active-bg: #eff6ff;
  --sidebar-active-text: #2563eb;
  --color-primary: #2563eb;
  --content-bg: #f9fafb;
  --card-radius: 0.375rem;
  --btn-radius: 0.375rem;
  --input-radius: 0.375rem;
  --modal-radius: 0.5rem;
  --badge-radius: 0.375rem;
  /* etc — matches current hardcoded values */
}
```

### Violet (new theme from screenshot)
```css
[data-theme="violet"] {
  --sidebar-bg: #1e1b4b;
  --sidebar-text: rgba(255,255,255,0.7);
  --sidebar-active-bg: rgba(124,58,237,0.2);
  --sidebar-active-text: #ffffff;
  --color-primary: #7c3aed;
  --content-bg: #f8fafc;
  --card-radius: 0.75rem;
  --btn-radius: 0.5rem;
  --input-radius: 0.5rem;
  --modal-radius: 1rem;
  --badge-radius: 9999px;
  /* etc */
}
```

## Files to Create/Modify

### New Files
- `frontend/src/styles/themes.css` — all theme CSS variable definitions
- `frontend/src/contexts/ThemeContext.tsx` — ThemeContext provider, reads from platform branding, applies data-theme to html
- `frontend/src/themes/registry.ts` — theme metadata (name, label, preview colors) for the admin selector

### Modified Files (minimal changes)
- `frontend/src/index.css` — import themes.css, update base styles to use var() instead of hardcoded colors
- `frontend/src/components/ui/Button.tsx` — use var(--btn-primary-bg) etc
- `frontend/src/components/ui/Modal.tsx` — use var(--modal-radius)
- `frontend/src/components/ui/Badge.tsx` — use var(--badge-radius)
- `frontend/src/layouts/OrgLayout.tsx` — sidebar uses var(--sidebar-bg) etc
- `frontend/src/layouts/AdminLayout.tsx` — same sidebar treatment
- `frontend/src/App.tsx` — wrap with ThemeProvider
- `frontend/src/pages/admin/Settings.tsx` or `BrandingConfig.tsx` — add theme selector UI

### Backend
- `app/modules/admin/service.py` — add `platform_theme` to platform_settings (already has a JSONB settings pattern)
- `GET /admin/platform-settings` already returns settings — just add the theme key
- `PUT /admin/platform-settings` already saves — just accept the theme key

## How Components Use Theme Variables

Components use CSS variables through inline styles or Tailwind arbitrary values:

```tsx
// Sidebar example
<aside style={{ backgroundColor: 'var(--sidebar-bg)' }}>

// Or via Tailwind arbitrary values
<aside className="bg-[var(--sidebar-bg)]">

// Button example
<button className="bg-[var(--btn-primary-bg)] hover:bg-[var(--btn-primary-hover)] rounded-[var(--btn-radius)]">
```

## Adding a Future Theme

To add a new theme (e.g., "ocean"):
1. Add a `[data-theme="ocean"]` block in `themes.css` with all variables
2. Add `{ id: 'ocean', label: 'Ocean', preview: '#0ea5e9' }` to `registry.ts`
3. Done — no component changes needed
