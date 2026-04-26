---
inclusion: auto
---

# Setup Guide — Auto-Updating Module Questions

The Setup Guide is a question-driven onboarding flow that asks users plain-language questions to enable or skip optional modules. It is **self-maintaining** — no code changes are needed when new modules or subscription plans are added.

## How It Works

The setup guide dynamically queries `module_registry` at runtime. A module appears in the setup guide when ALL of these are true:

1. The module has a non-null `setup_question` in `module_registry`
2. The module has `is_core = false`
3. The module is NOT in the `TRADE_GATED_MODULES` set (currently: `vehicles`)
4. The module is in the org's subscription plan `enabled_modules` list

This means:
- **New module added?** → If it has a `setup_question`, it automatically appears in the setup guide for any plan that includes it
- **New subscription plan created?** → If the plan's `enabled_modules` includes modules with setup questions, those questions automatically appear for orgs on that plan
- **Module removed from a plan?** → Its question automatically stops appearing for orgs on that plan

## When Adding a New Module

Every new non-core, non-trade-gated module MUST include `setup_question` and `setup_question_description` values in its `module_registry` migration. This ensures the setup guide stays current without code changes.

### Migration Template

In your Alembic migration that inserts the new module into `module_registry`, include:

```python
op.execute("""
    UPDATE module_registry
    SET setup_question = 'Will you be using [feature description] for your business?',
        setup_question_description = 'One sentence explaining what this module does and why a user would want it.'
    WHERE slug = 'your_module_slug'
""")
```

Or if inserting a new row:

```python
op.execute("""
    INSERT INTO module_registry (id, slug, display_name, description, category, is_core, dependencies, incompatibilities, status, setup_question, setup_question_description)
    VALUES (
        gen_random_uuid(),
        'your_module_slug',
        'Your Module Name',
        'Technical description for admin UI',
        'your_category',
        false,
        '[]'::jsonb,
        '[]'::jsonb,
        'available',
        'Plain-language question for the user?',
        'One sentence explaining the benefit.'
    )
""")
```

### Question Writing Guidelines

- **setup_question**: A yes/no question in plain language. Start with "Do you..." or "Will you..." or "Would you like to...". Avoid technical jargon. The user should understand what they're saying yes to without knowing what a "module" is.
- **setup_question_description**: One sentence explaining the benefit. Focus on what the user gets, not how it works technically.

### Examples

| Module | setup_question | setup_question_description |
|--------|---------------|---------------------------|
| quotes | "Will you be sending quotes or estimates to your customers?" | "Create professional quotes, send them for approval, and convert accepted quotes into invoices." |
| scheduling | "Do you need a visual calendar for scheduling work?" | "Drag-and-drop scheduling and resource allocation." |
| bookings | "Do your customers book appointments with you?" | "Customer-facing booking pages and appointment management." |

### Modules That Should NOT Have Setup Questions

- **Core modules** (`is_core = true`): invoicing, customers, notifications — always enabled, no question needed
- **Trade-family-gated modules**: vehicles — auto-enabled based on trade family, no question needed
- If your module is always-on for a specific trade family, add it to `TRADE_GATED_MODULES` in `app/modules/setup_guide/router.py` instead of giving it a setup question

## When Creating a New Subscription Plan

No code changes needed. When a Global Admin creates a new plan via the admin UI and adds modules to the plan's `enabled_modules` list, the setup guide automatically picks up those modules' questions for any org that subscribes to that plan.

## Re-run Behaviour

When a user re-runs the setup guide from Settings, only modules where `org_modules.is_enabled = false` are shown. This means:
- Modules they previously said "yes" to won't appear again
- Modules they said "no" to will appear so they can reconsider
- New modules added to their plan since the last run will also appear (they won't have an `org_modules` record yet, or it will be `is_enabled = false`)

## Checklist for New Modules

- [ ] Module has `setup_question` set in its migration
- [ ] Module has `setup_question_description` set in its migration
- [ ] Question is plain-language, yes/no format
- [ ] Description is one sentence explaining the user benefit
- [ ] If trade-family-gated, added to `TRADE_GATED_MODULES` set instead
- [ ] Module is included in at least one subscription plan's `enabled_modules`
