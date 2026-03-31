# Platform Theme System — Tasks

## Phase 1: Theme Infrastructure
- [x] 1.1 Create `frontend/src/styles/themes.css` — CSS custom properties for "classic" and "violet" themes
- [x] 1.2 Create `frontend/src/themes/registry.ts` — theme definitions array for admin UI
- [x] 1.3 Create `frontend/src/contexts/ThemeContext.tsx` — reads theme from branding, sets data-theme on html
- [x] 1.4 Update `frontend/src/index.css` — import themes.css, base styles use CSS variables for focus rings and radii
- [x] 1.5 Update `frontend/src/App.tsx` — wrap with ThemeProvider

## Phase 2: Core UI Components (use CSS variables)
- [x] 2.1 Update `Button.tsx` — uses var(--btn-primary-bg), var(--btn-radius) etc
- [x] 2.2 Update `Modal.tsx` — uses var(--modal-radius), backdrop blur, fadeIn animation
- [x] 2.3 Update `AlertBanner.tsx` — uses var(--card-radius)
- [x] 2.4 `Badge.tsx` — already uses rounded-full, no change needed
- [x] 2.5 Update `Spinner.tsx` — uses var(--color-primary)
- [ ] 2.6 Update `Tabs.tsx` — active indicator color uses var(--color-primary)
- [ ] 2.7 Update `Pagination.tsx` — active page button uses var(--color-primary)
- [ ] 2.8 Update `Input.tsx` — ensure consistent with theme variables

## Phase 3: Layout Components (sidebar theming)
- [x] 3.1 Update `OrgLayout.tsx` sidebar — uses var(--sidebar-bg), var(--sidebar-text), var(--sidebar-active-bg/text)
- [x] 3.2 Update `AdminLayout.tsx` sidebar — same CSS variable treatment
- [x] 3.3 Content area background uses var(--content-bg) in both layouts

## Phase 4: Backend + Admin Theme Selector
- [x] 4.1 Add `platform_theme` column to platform_branding model + migration 0128
- [x] 4.2 Update branding schemas (BrandingUpdate, BrandingResponse, PublicBrandingResponse) + router
- [x] 4.3 Add theme selector UI to BrandingConfig page with visual swatches
- [x] 4.4 ThemeContext reads theme from PlatformBrandingContext and applies on load

## Phase 5: Polish and Verify
- [ ] 5.1 Verify classic theme looks identical to current design
- [ ] 5.2 Verify violet theme applies correctly across sidebar, buttons, inputs, modals
- [ ] 5.3 Test theme switching from admin Branding page
- [ ] 5.4 Verify responsive behavior works with both themes
- [ ] 5.5 Build and deploy
