---
inclusion: auto
---

# No-Shortcut Implementation Rules

These rules exist because of a real incident where an embedded PDF viewer was injected into the invoice list page, breaking print, payment history, internal notes, and other existing functionality. The "shortcut" of replacing a working HTML preview with a PDF `<object>` embed destroyed multiple features that depended on the existing DOM structure.

## Rule 1: Never Replace Working UI with a Different Rendering Approach

When asked to "fix" or "update" an existing UI component:
- **Understand what the component does first** — read the full component, identify all features it supports (print, click handlers, conditional sections, data display)
- **Modify the existing approach** — don't swap it for a fundamentally different rendering method (e.g. don't replace HTML with an iframe/embed/object)
- **If the existing approach can't support the request**, explain the limitation and propose a proper spec instead of hacking in a workaround

## Rule 2: Preserve All Existing Functionality

Before modifying any component:
1. **List all interactive features** the component currently supports (buttons, print, modals, click handlers, conditional rendering)
2. **Verify each feature still works** after your change — if you can't test it, at minimum confirm the DOM structure and event handlers are preserved
3. **Never remove or restructure JSX** that contains event handlers, conditional sections, or data display unless you're certain nothing depends on it

## Rule 3: No Scope Creep on Bug Fixes

When fixing a bug or making a small change:
- **Do the minimum change needed** — don't refactor the surrounding code
- **Don't add new state, effects, or API calls** unless the fix specifically requires them
- **Don't change the component's rendering approach** (HTML → PDF embed, static → dynamic, etc.)
- If the proper fix requires significant changes, **stop and propose a spec** instead

## Rule 4: Large Component Changes Require a Spec

Any change that does one or more of the following **must go through a spec** (requirements → design → tasks):
- Replaces the rendering approach of a component (HTML preview → PDF embed, static → dynamic)
- Adds new API calls or state management to an existing component
- Restructures the JSX tree of a component with 500+ lines
- Affects print functionality, modal behaviour, or navigation

## Rule 5: Test What You Ship

After any frontend change:
- **Build must succeed** (vite build)
- **No TypeScript diagnostics** (getDiagnostics)
- **Visually verify** the change doesn't break surrounding UI by checking the component's key features still render correctly
- If you can't visually verify, **state what you couldn't test** so the user knows to check

## Real Example — What NOT to Do

**Bad**: User asks "why isn't the correct template showing in the invoice preview?" → Agent replaces the entire HTML preview with a `<object data={pdfBlobUrl}>` embed, adding new state (`pdfBlobUrl`, `pdfLoading`), a new useEffect with API call, and wrapping 400 lines of existing JSX in a ternary. This broke print, payment history display, internal notes, and the POS receipt preview.

**Good**: User asks "why isn't the correct template showing in the invoice preview?" → Agent explains that the in-browser preview is a hardcoded React component that doesn't use the org's template, while the actual PDF does. Proposes a spec to properly implement template-aware preview styling without breaking existing functionality.
