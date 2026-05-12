# Steering Documents — Reusable SaaS Patterns

This folder contains generalized steering documents extracted from production experience building multi-tenant SaaS applications. They can be dropped into any new project as a starting point for code quality, architecture decisions, and bug prevention.

## Documents

| Document | Purpose |
|----------|---------|
| [safe-api-consumption.md](./safe-api-consumption.md) | Frontend patterns for safely consuming REST API responses |
| [feature-gating.md](./feature-gating.md) | How to gate features by user type, plan, role, or business vertical |
| [integration-credentials.md](./integration-credentials.md) | Secure credential storage architecture for third-party integrations |
| [deployment-procedures.md](./deployment-procedures.md) | Multi-environment deployment rules and procedures |
| [common-bug-patterns.md](./common-bug-patterns.md) | Recurring bug patterns and how to prevent them |
| [database-patterns.md](./database-patterns.md) | ORM patterns, migrations, RLS, flush vs commit |
| [ha-replication.md](./ha-replication.md) | PostgreSQL HA replication patterns |
| [frontend-architecture.md](./frontend-architecture.md) | React patterns, context usage, error boundaries, layouts |
| [security-checklist.md](./security-checklist.md) | Security patterns and checklist for SaaS apps |

## How to Use

1. **New project setup:** Copy the relevant documents into your project's `.kiro/steering/` or `docs/` folder
2. **Code review reference:** Link to specific patterns when reviewing PRs
3. **Onboarding:** Share with new team members to communicate established patterns
4. **Steering rules:** Convert into IDE steering files that load automatically when editing relevant file types

## Origin

These documents were extracted from 100+ tracked production issues, security audits, and deployment procedures. Each pattern represents a lesson learned the hard way — a bug that shipped, a crash that affected users, or a security gap that was discovered.

The patterns are technology-agnostic where possible, but examples use:
- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL
- **Frontend:** React, TypeScript, Tailwind CSS
- **Infrastructure:** Docker, Nginx, Redis
