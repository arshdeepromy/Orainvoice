# Implementation Plan: OraSign Integration Rename (Standalone Stack)

## Overview

This is an infrastructure/deployment effort, not application code. The work authors and adapts Docker Compose files, environment templates, the `documenso_default` → `orasign_default` network/host rename wiring, the signing-certificate provisioning, deployment runbooks, and backup/restore documentation. Verification is done with **deterministic smoke and integration checks** (no property-based testing — this is network/volume/config wiring whose behavior does not vary with generated inputs).

The cutover is gated: the OraSign stack must be verified end-to-end in **local DEV before the Pi PROD deployment proceeds** (Requirement 9.4). Both environments start with a fresh, empty OraSign database (no legacy data carry-over); legacy `documenso_*` references in OraInvoice are accepted to dangle.

Each task references the requirement clauses it satisfies. Verification tasks are tied to the four correctness properties (data isolation, URL resolution, persistence, end-to-end signing) and are validated by single deterministic checks.

## Tasks

- [ ] 1. Author the standalone OraSign production compose (`OraSign/docker/production/compose.yml`)
  - [ ] 1.1 Adapt the production compose to join the external `orasign_default` network
    - Add top-level `networks: { orasign_default: { external: true } }` and attach the `orasign` service to both `default` and `orasign_default` under its real service name `orasign` (NO `documenso` alias)
    - Keep `name: orasign-production`; keep `database` + `orasign` services with `depends_on: database (condition: service_healthy)`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 4.2, 4.6, 7.6_
  - [ ] 1.2 Set PORT, explicit host port mapping, dedicated volume, and cert mount
    - Set `PORT=${PORT:-3030}` (override image default 3000) so `http://orasign:3030` resolves
    - Map ports `${ORASIGN_HOST_PORT:-3030}:${PORT:-3030}` with a host port distinct from OraInvoice (80/8999)
    - Rename the named volume to `orasign_pgdata` (distinct from `documenso_db` / `invoicing_*`) and mount the signing cert read-only at `/opt/orasign/cert.p12`
    - _Requirements: 2.1, 2.5, 3.5, 4.1, 4.3, 6.4_
  - [ ]* 1.3 Smoke-check the production compose definition
    - `docker compose -f OraSign/docker/production/compose.yml config` parses; project name is `orasign-production`; services include `database`, `orasign`; volume `orasign_pgdata` present; cert mounted `:ro`; port/volume names do not collide with OraInvoice
    - _Requirements: 1.1, 1.2, 3.5, 4.1, 4.3, 6.4, 7.3_

- [ ] 2. Author the standalone OraSign development compose (`OraSign/docker/development/compose.yml`)
  - [ ] 2.1 Define the standalone dev stack: database + maildev + orasign on `orasign_default`
    - `name: orasign-development`; `database` (postgres:15) with healthcheck and volume `orasign_pgdata_dev`; `orasign` app with `depends_on: database (service_healthy)`, `PORT=${PORT:-3030}`, ports `${ORASIGN_HOST_PORT:-3030}:${PORT:-3030}`, cert mount `./certs/cert.p12:/opt/orasign/cert.p12:ro`
    - Replace the legacy `documenso-maildev` with a `maildev` service (web inbox on 1080, SMTP 1025 internal); point OraSign SMTP at `maildev:1025`
    - Attach `orasign` to `default` and external `orasign_default` under the real service name (no alias)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.5, 3.5, 4.1, 4.2, 4.3, 6.4, 7.6_
  - [ ]* 2.2 Smoke-check the development compose definition
    - `docker compose -f OraSign/docker/development/compose.yml config` parses; project `orasign-development`; services include `database`, `maildev`, `orasign`; volume `orasign_pgdata_dev` present; maildev web on 1080
    - _Requirements: 1.1, 1.2, 6.4, 7.3_

- [ ] 3. Author per-environment env templates and ensure secrets are git-ignored
  - [ ] 3.1 Create env example templates for production and development
    - Create `OraSign/docker/production/.env.example` and `OraSign/docker/development/.env.example` documenting required vs optional vars
    - Required (`:?err`): `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY`, `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY`, `NEXT_PUBLIC_WEBAPP_URL`, `NEXT_PRIVATE_DATABASE_URL`, `POSTGRES_USER/PASSWORD/DB`, `NEXT_PRIVATE_SMTP_TRANSPORT`, `NEXT_PRIVATE_SMTP_FROM_NAME/ADDRESS`
    - Optional/defaults: `NEXT_PRIVATE_DIRECT_DATABASE_URL`, `PORT=3030`, `ORASIGN_HOST_PORT=3030`, `NEXT_PUBLIC_UPLOAD_TRANSPORT=database`, `NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH=/opt/orasign/cert.p12`, `NEXT_PRIVATE_SIGNING_PASSPHRASE`, `NEXT_PRIVATE_INTERNAL_WEBAPP_URL`
    - DEV template: `NEXT_PUBLIC_WEBAPP_URL=http://localhost:3030`, SMTP pointed at `maildev:1025`. PROD template: `NEXT_PUBLIC_WEBAPP_URL=https://esignd.oraflows.co.nz`, real transport (resend/mailchannels/authenticated SMTP)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [ ] 3.2 Ensure real `.env` files are excluded from version control
    - Add/confirm `.gitignore` entries for `OraSign/docker/production/.env` and `OraSign/docker/development/.env` (only `.env.example` committed)
    - _Requirements: 3.7_
  - [ ]* 3.3 Smoke-check configuration and secret handling
    - Confirm `${VAR:?err}` aborts `up` naming a missing required var (unset one var, assert failure message); confirm real `.env` files are git-ignored (`git check-ignore`)
    - _Requirements: 3.6, 3.7_

- [ ] 4. Apply the OraInvoice wiring change (config-only — no app code/DB/error-code changes)
  - [ ] 4.1 Repoint `docker-compose.dev.yml` from `documenso_default` to `orasign_default`
    - Change the `app` service `networks:` entry and the bottom `networks:` declaration from `documenso_default` to `orasign_default`
    - Update related comments referencing `http://documenso:3030` to `http://orasign:3030`
    - Do NOT touch OraInvoice app code, DB columns, error codes, or esignatures logic; `ESIGN_*` env names unchanged
    - _Requirements: 4.6, 5.1, 5.2, 7.4_
  - [ ] 4.2 Check and repoint any Pi PROD compose that joins the signing network
    - Inspect Pi PROD compose files (`docker-compose.pi.yml` / related) for a `documenso_default` membership; repoint to `orasign_default` the same way if present
    - _Requirements: 4.6, 5.1, 7.4_
  - [ ] 4.3 Optional cosmetic config comment update in `app/config.py`
    - Update the comment (line ~171) referencing `http://documenso:3030` to `http://orasign:3030` (comment only, no logic change)
    - _Requirements: 5.1_

- [ ] 5. Provision the signing certificate mount per environment
  - [ ] 5.1 Wire certificate paths for DEV and PROD
    - DEV: place/document `OraSign/docker/development/certs/cert.p12` mounted at `/opt/orasign/cert.p12:ro`; ensure the `certs/` real cert is git-ignored
    - PROD: document the host path `/opt/orasign/cert.p12` mounted read-only; set `NEXT_PRIVATE_SIGNING_PASSPHRASE` in the PROD env
    - _Requirements: 3.5_

- [ ] 6. Local DEV bring-up and verification (gating step for PROD)
  - [ ] 6.1 Create the external network and bring up the dev stack
    - `docker network create orasign_default` (idempotent); bring up `orasign-development` with its `--env-file`
    - Recreate the OraInvoice dev `app` on `orasign_default`; repoint the per-org connection `base_url` to `http://orasign:3030` via the Global Admin GUI
    - _Requirements: 4.5, 5.2, 6.1, 7.1, 7.2, 7.4_
  - [ ]* 6.2 Verify data isolation (Property 1)
    - **Property 1: Data isolation**
    - **Validates: Requirements 1.5, 2.3, 2.4, 2.5**
    - Inspect the `orasign` container: only DB route is the in-stack `database`; connect to both OraSign and OraInvoice DBs and assert disjoint table sets; assert no OraInvoice mounts/links
  - [ ]* 6.3 Verify URL resolution + startup migrations (Property 2)
    - **Property 2: URL resolution**
    - **Validates: Requirements 4.5, 7.2**
    - From the OraInvoice app container, `curl http://orasign:3030/api/health` succeeds; assert Prisma `migrate deploy` ran on the fresh volume before serving (Requirements 2.2, 6.5)
  - [ ]* 6.4 Verify persistence across restart/recreation (Property 3)
    - **Property 3: Persistence across restart and recreation**
    - **Validates: Requirements 8.1, 8.2**
    - Write data, `docker compose down` (without `-v`), `up`, assert data is still present
  - [ ]* 6.5 Verify end-to-end signing in DEV (Property 4)
    - **Property 4: End-to-end signing reachability**
    - **Validates: Requirements 5.2, 5.3, 9.1, 9.2, 9.3**
    - From an OraInvoice org, initiate a signing request → assert the document row is created in the OraSign DB and a consumable response returns; complete the document → assert OraInvoice receives the completion event; on any failure, the procedure reports the failing stage (Requirement 9.5)

- [ ] 7. Checkpoint — DEV verification must pass before PROD
  - Ensure all DEV smoke and integration checks pass (Properties 1–4, lifecycle independence 6.3). Ask the user if questions arise. PROD cutover is gated on a clean DEV pass (Requirement 9.4).

- [ ] 8. Retire the legacy documenso stack (DEV first)
  - [ ] 8.1 Optional safety archive of the legacy DB
    - Take a `pg_dump` of the legacy `documenso-db` as an off-to-the-side archive only — NEVER restored into OraSign
    - _Requirements: 2.8_
  - [ ] 8.2 Tear down the legacy documenso project and confirm independence
    - `docker compose -f documenso/docker-compose.yml down` the `documenso` project; ensure OraInvoice is recreated on `orasign_default`; assert no OraSign workload depends on the `documenso` project/container/`documenso_default` network
    - _Requirements: 7.1, 7.3, 7.5, 7.6_

- [ ] 9. Pi PROD deployment (gated on DEV pass)
  - [ ] 9.1 Bring up the OraSign production stack as a separate compose step
    - Deploy `orasign-production` via its own `docker compose ... up -d` (NOT added to the `invoicing` redeploy command); start with a fresh, empty OraSign DB (accept dangling legacy refs)
    - _Requirements: 2.6, 2.7, 6.2, 6.3, 6.5_
  - [ ] 9.2 Repoint nginx upstream and per-org base_url for PROD
    - Repoint nginx upstream for `esignd.oraflows.co.nz` to the OraSign app published port (3030) and reload nginx; repoint the per-org connection `base_url` to `http://orasign:3030` via the Global Admin GUI
    - _Requirements: 4.4, 5.2, 5.5_
  - [ ]* 9.3 Verify end-to-end signing in PROD (Property 4)
    - **Property 4: End-to-end signing reachability**
    - **Validates: Requirements 5.2, 5.3, 9.1, 9.2, 9.3**
    - Health check green at internal (`http://orasign:3030`) and public (`https://esignd.oraflows.co.nz`) URLs; create a signing document (visible in OraSign DB) and observe the completion event back in OraInvoice; only run after the DEV checkpoint passed (Requirement 9.4)

- [ ] 10. Backup/restore runbook and documentation
  - [ ] 10.1 Document the OraSign DB backup and restore procedures
    - Backup: `pg_dump` of the `orasign-production` `database` service piped to gzip; Restore: `gunzip | psql` into the `orasign_pgdata` volume; note volume-snapshot alternative
    - _Requirements: 8.3, 8.4_
  - [ ] 10.2 Update project documentation (CHANGELOG/docs)
    - Record the standalone OraSign stack, the `orasign_default` rename, the cutover, and the runbooks in CHANGELOG/docs
    - _Requirements: 6.1, 6.2, 7.1_

## Notes

- Tasks marked with `*` are optional verification sub-tasks (deterministic smoke/integration checks) and can be skipped for a faster bring-up, but they are how the four correctness properties are validated.
- This is an infrastructure/deployment feature — there are **no property-based-testing tasks**; verification uses deterministic smoke checks and 1–3 representative integration executions.
- DEV-before-PROD gating is enforced by the checkpoint (task 7): PROD tasks (9.x) must not run until the DEV verification passes (Requirement 9.4).
- Both environments start with a fresh OraSign DB; legacy `documenso_*` references are accepted to dangle (Requirements 2.6, 2.7).
- No OraInvoice application code, DB columns, error codes, or esignatures module logic change — only network wiring, the per-org `base_url` repoint, and an optional comment.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1", "3.1", "4.1", "4.2", "4.3", "5.1"] },
    { "id": 1, "tasks": ["1.2", "3.2"] },
    { "id": 2, "tasks": ["1.3", "2.2", "3.3", "6.1"] },
    { "id": 3, "tasks": ["6.2", "6.3", "6.4", "6.5"] },
    { "id": 4, "tasks": ["8.1"] },
    { "id": 5, "tasks": ["8.2"] },
    { "id": 6, "tasks": ["9.1"] },
    { "id": 7, "tasks": ["9.2"] },
    { "id": 8, "tasks": ["9.3"] },
    { "id": 9, "tasks": ["10.1", "10.2"] }
  ]
}
```
