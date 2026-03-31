# Platform Theme System — Requirements

## Overview
Build a theme system that lets the global admin switch the entire app's visual appearance between multiple themes. The current design becomes "Classic" theme. A new "Violet" theme (inspired by the provided design reference) is the first additional theme. The system must be extensible so more themes can be added in the future without code changes to individual pages.

## Design Reference (Violet Theme)
From the provided screenshot:
- Dark navy/indigo sidebar with white text and purple accent for active state
- Colorful pastel card backgrounds
- Large rounded corners on cards and buttons
- Clean light gray main content background
- Purple/violet as the primary accent color
- Soft drop shadows on cards
- Spacious layout with generous padding
- Smooth, friendly, modern SaaS feel

## Requirements

### REQ-1: Theme Infrastructure
- Create a ThemeContext that provides the active theme name and CSS variables to the entire app
- Theme is stored as a platform_settings value in the backend (key: `platform_theme`)
- Frontend loads the active theme from `GET /admin/platform-settings` or the branding context
- Theme is applied via CSS custom properties on the `<html>` element (data-theme attribute)
- All themes share the same HTML structure — only CSS variables and a few Tailwind classes change

### REQ-2: Classic Theme (Current Design — Default)
- Preserve the current look exactly as-is as the "classic" theme
- White sidebar, blue primary accent, gray backgrounds
- This is the default when no theme is set

### REQ-3: Violet Theme (New)
- Dark indigo sidebar (#1e1b4b), white nav text, violet active pill
- Primary accent: violet/purple (#7c3aed)
- Content background: light gray (#f8fafc)
- Cards: rounded-xl with soft shadows
- Buttons: violet primary, rounded-lg
- Inputs: rounded-lg, violet focus ring
- Modals: rounded-2xl with backdrop blur
- Badges: rounded-full pill shape
- Smooth hover transitions on interactive elements

### REQ-4: Global Admin Theme Switcher
- Add a theme selector to the admin Settings page (or Branding page)
- Shows available themes with a visual preview/swatch
- Changing the theme saves to backend and applies immediately app-wide
- All connected browser sessions pick up the new theme on next page load

### REQ-5: Extensibility
- Adding a new theme should only require:
  1. A new CSS file or CSS variable block in `index.css`
  2. Adding the theme name to the themes registry array
  3. No changes to any component JSX or page files
- Theme definitions are purely CSS custom properties

### REQ-6: No Feature Changes
- Themes only change visual appearance (colors, borders, shadows, radius, transitions)
- No JS logic, API calls, routes, or component structure changes
- All existing functionality, gating, and conditional rendering must be preserved

## Constraints
- No new npm dependencies
- CSS custom properties + data-theme attribute approach (no runtime JS style injection)
- Must work with existing Tailwind setup
- Responsive behavior must work identically across all themes
