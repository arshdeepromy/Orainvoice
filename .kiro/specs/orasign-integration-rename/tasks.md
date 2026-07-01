# Implementation Plan: OraSign Integration Rename (Standalone Stack, Two Repos)

## Overview

This is an infrastructure/deployment effort spanning **two separate git repositories**, not application code:

- **[OraSign repo]** — `github.com/arshdeepromy/Orasign`, cloned to a separate workspace (`/mnt/hindi-tv/OraSign` locally, `/home/nerdy/orasign` on the Pi). Owns the compose files, Dockerfile, Prisma migrations, env templates, and the guard/update scripts.
- **[OraInvoice repo]** — `arshdeepromy/Orainvoice`, this workspace (`/mnt/hindi-tv/Invoicing`). Receives a **single one-line network-reference change** plus deploy-flow/doc wiring. No application code, DB columns, error codes, stored `base_url`, or esignatures logic change.

The repository split (extracting OraSign to its own repo, purging OraInvoice history, force-push) is **already done** — this plan does **not** re-do the split; task 1 only **verifies** the resulting state.

The network rename keeps a compatibility **alias**: the Docker network becomes `orasign_default`, and the OraSign app service carries the alias `documenso` so the stored internal base_url `http://documenso:3030` still resolves with **no OraInvoice code/DB change**. Both environments start with a **fresh, empty OraSign database** — there are **no data-migration tasks**; legacy `documenso_*` references in OraInvoice are accepted to dangle.

Because this is network/volume/config/script wiring, verification uses **deterministic smoke and integration checks tied to the five correctness properties** (data isolation, URL resolution via the `documenso` alias, guard idempotency, persistence, end-to-end signing). There are **no property-based tests** here. The cutover is **gated**: OraSign must be verified end-to-end in **local DEV before Pi PROD proceeds** (Requirement 12.4).

Each task is labelled with the repo/environment it touches. Tasks that touch **Pi PROD (real production data — 7 orgs, live signing)** are flagged and gated behind the DEV verification checkpoint.

## Tasks

- [ ] 1. Verify repository-split state (both repos, read-only)
  - [ ] 1.1 Verify the OraSign repo holds the OraSign source **[OraSign repo]**
    - Confirm the OraSign clone contains `docker/Dockerfile`, `docker/start.sh`, `packages/prisma`, and the `docker/production` + `docker/development` compose locations; confirm the remote is `github.com/arshdeepromy/Orasign` with a clean single-commit history
    - _Requirements: 1.1, 1.3, 1.4_
  - [ ] 1.2 Verify the OraInvoice repo contains no OraSign source **[OraInvoice repo]**
    - Confirm no `/OraSign` (or prior subfolder) path exists in this workspace and that git history no longer tracks OraSign source; confirm the OraInvoice remote is `arshdeepromy/Orainvoice`
    - _Requirements: 1.2, 1.5_

- [ ] 2. Author the OraSign compose files — local build + `documenso` alias + fresh DB **[OraSign repo]**
  - [ ] 2.1 Adapt the production compose (`docker/production/compose.yml`)
    - Keep `name: orasign-production`; `database` (`postgres:15`) with `pg_isready` healthcheck and named volume `orasign_pgdata`; `app` with `depends_on: database (condition: service_healthy)`
    - App image **built locally**: `build: { context: .., dockerfile: docker/Dockerfile }` (NO `image:` registry pull)
    - Set `PORT=${PORT:-3030}`; publish `${ORASIGN_HOST_PORT:-3030}:${PORT:-3030}` (host port distinct from OraInvoice 80/8999)
    - Attach `app` to `default` and external `orasign_default` with network **alias `documenso`** so `http://documenso:3030` resolves; declare top-level `networks: { orasign_default: { external: true } }`
    - Mount the signing cert read-only at `${NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH:-/opt/orasign/cert.p12}`; enforce required env with `${VAR:?err}`
    - _Requirements: 2.1, 2.2, 2.4, 3.5, 4.5, 4.6, 5.1, 5.3, 7.1, 9.4_
  - [ ]* 2.2 Smoke-check the production compose definition
    - `docker compose -f docker/production/compose.yml config` parses; project is `orasign-production`; services `database` + `app`; volume `orasign_pgdata`; app declares `build:` (no `image:`); alias `documenso` on `orasign_default`; cert mounted `:ro`; port/volume names do not collide with OraInvoice
    - _Requirements: 2.1, 2.2, 5.3, 7.1, 7.4_
  - [ ] 2.3 Author the development compose (`docker/development/compose.yml`) with maildev
    - `name: orasign-development`; `database` (`postgres:15`) with healthcheck and volume `orasign_pgdata_dev`; `app` with local `build:`, `PORT=${PORT:-3030}`, ports `${ORASIGN_HOST_PORT:-3030}:${PORT:-3030}`, cert mount `./certs/cert.p12:/opt/orasign/cert.p12:ro`
    - Add a `maildev` service (web inbox on 1080, SMTP 1025 internal) replacing the retired `documenso-maildev`; point OraSign SMTP at `maildev:1025`
    - Attach `app` to `default` and external `orasign_default` with alias `documenso`
    - _Requirements: 2.1, 2.2, 2.4, 3.5, 4.4, 5.1, 5.3, 7.1_
  - [ ]* 2.4 Smoke-check the development compose definition
    - `docker compose -f docker/development/compose.yml config` parses; project `orasign-development`; services `database`, `maildev`, `app`; volume `orasign_pgdata_dev`; maildev web on 1080; alias `documenso` on `orasign_default`
    - _Requirements: 2.1, 2.2, 5.3, 7.1_

- [ ] 3. Author env templates, secret handling, and signing-cert provisioning **[OraSign repo]**
  - [ ] 3.1 Create per-environment `.env.example` templates (prod + dev)
    - Create `docker/production/.env.example` and `docker/development/.env.example` documenting required vs optional vars
    - Required (`:?err`): `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY`, `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY`, `NEXT_PUBLIC_WEBAPP_URL`, `NEXT_PRIVATE_DATABASE_URL`, `POSTGRES_USER/PASSWORD/DB`, `NEXT_PRIVATE_SMTP_TRANSPORT`, `NEXT_PRIVATE_SMTP_FROM_NAME/ADDRESS`
    - Optional/defaults: `NEXT_PRIVATE_DIRECT_DATABASE_URL`, `PORT=3030`, `ORASIGN_HOST_PORT=3030`, `NEXT_PUBLIC_UPLOAD_TRANSPORT=database`, `NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH=/opt/orasign/cert.p12`, `NEXT_PRIVATE_SIGNING_PASSPHRASE`, `NEXT_PRIVATE_INTERNAL_WEBAPP_URL`
    - DEV template: `NEXT_PUBLIC_WEBAPP_URL=http://localhost:3030`, SMTP → `maildev:1025`. PROD template: `NEXT_PUBLIC_WEBAPP_URL=https://esignd.oraflows.co.nz`, real transport (resend/mailchannels/authenticated SMTP)
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [ ] 3.2 Ensure real `.env` files and certs are excluded from version control
    - Add/confirm `.gitignore` entries for `docker/**/.env` and `certs/` (only `.env.example` committed)
    - _Requirements: 4.7_
  - [ ] 3.3 Provision the signing-certificate mount per environment
    - DEV: place/document `docker/development/certs/cert.p12` mounted at `/opt/orasign/cert.p12:ro` (git-ignored)
    - PROD: document the host path `/opt/orasign/cert.p12` mounted read-only and set `NEXT_PRIVATE_SIGNING_PASSPHRASE` in the PROD env
    - _Requirements: 4.5_
  - [ ]* 3.4 Smoke-check configuration and secret handling
    - Confirm `${VAR:?err}` aborts `up` naming a missing required var (unset one var, assert the failure message names it); confirm real `.env` files are git-ignored (`git check-ignore`)
    - _Requirements: 4.6, 4.7_

- [ ] 4. Author the guard script (start-if-down, never rebuild) **[OraSign repo]**
  - [ ] 4.1 Create `scripts/ensure-orasign.sh`
    - Idempotent guard: count running containers in the OraSign project; if any are running → no-op; if stopped → `docker compose ... up -d` **without** `--build`, no `git pull`, no `--force-recreate`; never rebuilds or upgrades
    - Parameterise `ORASIGN_DIR`, `ORASIGN_PROJECT`, compose file, and `--env-file`; make the script executable
    - _Requirements: 8.2, 8.3, 8.4, 8.5_
  - [ ]* 4.2 Verify guard idempotency (Property 3)
    - **Property 3: Guard idempotency**
    - **Validates: Requirements 8.3, 8.4, 8.5**
    - With the stack up, capture container IDs + image digest; run the guard three times and assert IDs/digest unchanged and no `build`/`create` occurred; then bring the stack `down`, run the guard once, and assert it comes up **without** a rebuild (image digest equals the pre-existing local build)

- [ ] 5. Author the explicit update command (only rebuild path) **[OraSign repo]**
  - [ ] 5.1 Create `scripts/update-orasign.sh`
    - The sole path that `git pull`s the OraSign repo at its clone path, `docker compose ... build`s the local image, and `docker compose ... up -d` recreates containers; run explicitly by an operator, never by the OraInvoice deploy flow; make executable
    - _Requirements: 7.2, 8.6_
  - [ ]* 5.2 Verify update-command exclusivity
    - **Validates: Requirements 8.6, 8.7**
    - Run `update-orasign.sh`; assert it pulls, rebuilds (new image digest), and recreates. Confirm no other script (including the guard) performs a rebuild

- [ ] 6. Apply the single OraInvoice network edit and retire the legacy stack **[OraInvoice repo / host]**
  - [ ] 6.1 Repoint `docker-compose.dev.yml` external network `documenso_default` → `orasign_default`
    - Change the `app` service `networks:` entry and the bottom `networks:` declaration from `documenso_default` to `orasign_default`; leave the stored base_url `http://documenso:3030` unchanged (resolved via the alias)
    - Do NOT touch OraInvoice app code, DB columns (`documenso_document_id`/`documenso_team_id`/`documenso_recipient_id`), the `documenso_error` code, the esignatures module, or `NEXT_PRIVATE_DOCUMENSO_*` / `ESIGN_DOCUMENSO_*` env names; comment updates are cosmetic only
    - _Requirements: 6.1, 6.2, 6.5, 10.5_
  - [ ] 6.2 Repoint any Pi PROD compose that declares the signing network
    - Inspect Pi compose (`docker-compose.pi.yml` / override) for a `documenso_default` external-network membership; apply the identical one-line rename to `orasign_default` if present; otherwise no Pi-side OraInvoice change
    - _Requirements: 6.1, 10.5_
  - [ ] 6.3 Retire the Legacy Documenso stack (optional archive, then teardown)
    - Optionally take a `pg_dump` of the legacy `documenso-db` as an off-to-the-side **archive only** (NEVER restored into OraSign); then `docker compose -f documenso/docker-compose.yml down` the `documenso` project; ensure no OraSign workload depends on the `documenso` project/container or the legacy `documenso_default` network name
    - _Requirements: 3.8, 10.1, 10.3, 10.4, 10.5_
  - [ ]* 6.4 Smoke-check the OraInvoice change surface
    - Assert the only functional edit in the OraInvoice diff is the external-network name change; assert the stored per-org `base_url` is still `http://documenso:3030` and no `app/`, `DocumensoClient`, DB-column, or error-code change is present
    - _Requirements: 6.2, 6.3, 6.5_

- [ ] 7. Local DEV bring-up and end-to-end verification (gating step for PROD) **[local DEV]**
  - [ ] 7.1 Create the network and bring up the DEV stack alongside OraInvoice
    - `docker network create orasign_default` (idempotent); bring up `orasign-development` with its `--env-file --build`; recreate the OraInvoice dev `app` on `orasign_default`; start with a fresh, empty OraSign DB (no data carry-over)
    - _Requirements: 3.6, 7.2, 9.1, 9.3_
  - [ ]* 7.2 Verify data isolation (Property 1)
    - **Property 1: Data isolation**
    - **Validates: Requirements 2.5, 3.3, 3.4, 3.5**
    - Inspect the OraSign `app` container: its only DB route is the in-stack `database`; connect to both the OraSign and OraInvoice databases and assert disjoint table sets; assert no OraInvoice mounts/links/connection strings
  - [ ]* 7.3 Verify URL resolution via the `documenso` alias + startup migrations (Property 2)
    - **Property 2: URL resolution via the `documenso` alias**
    - **Validates: Requirements 5.4, 6.2, 6.3, 10.2**
    - From the OraInvoice app container, `curl http://documenso:3030/api/health` succeeds via the alias with the stored base_url unchanged; assert Prisma `migrate deploy` ran on the fresh volume before serving (Requirements 3.2, 9.4)
  - [ ]* 7.4 Verify persistence across restart/recreation (Property 4)
    - **Property 4: Persistence across restart and recreation**
    - **Validates: Requirements 11.1, 11.2**
    - Write data, `docker compose down` (without `-v`), `up`, and assert the data is still present
  - [ ]* 7.5 Verify end-to-end signing in DEV (Property 5)
    - **Property 5: End-to-end signing reachability**
    - **Validates: Requirements 6.4, 12.1, 12.2, 12.3**
    - From an OraInvoice org, initiate a signing request → assert the document row is created in the OraSign DB and a consumable response returns; complete the document → assert OraInvoice receives the completion event over the existing path; on any failure, the procedure reports the failing stage (Requirement 12.5)

- [ ] 8. Checkpoint — DEV verification must pass before PROD
  - Ensure all DEV smoke and integration checks pass (Properties 1–5, guard idempotency, update exclusivity, lifecycle independence). Ask the user if questions arise. **The Pi PROD cutover (task 9) is gated on a clean DEV pass (Requirement 12.4).**

- [ ] 9. Pi PROD deployment + guard integration + verification **[Pi PROD — PRODUCTION, REAL DATA; gated on task 8]**
  - [ ] 9.1 Bring up the OraSign production stack as a separate compose step **[Pi PROD]**
    - Deploy `orasign-production` via its own `docker compose ... up -d --build` from `/home/nerdy/orasign` (NOT added to the `invoicing` redeploy command); start with a fresh, empty OraSign DB (accept dangling legacy refs); apply outstanding Prisma migrations on startup
    - _Requirements: 3.6, 3.7, 7.2, 7.3, 8.1, 9.2, 9.3, 9.4_
  - [ ] 9.2 Repoint the nginx upstream for the public signer URL **[Pi PROD]**
    - Point the nginx upstream for `esignd.oraflows.co.nz` at the OraSign app's published port (3030) instead of the retired documenso container; reload nginx; leave the Cloudflare Tunnel config unchanged
    - _Requirements: 5.6, 5.7_
  - [ ] 9.3 Wire the guard-script invocation into the Pi deploy flow/docs **[OraInvoice repo + Pi PROD]**
    - Append one line invoking `/home/nerdy/orasign/scripts/ensure-orasign.sh` after the OraInvoice services are up in the Pi redeploy command/runbook (steering doc); confirm an OraInvoice redeploy leaves a running OraSign untouched and never rebuilds it
    - _Requirements: 8.1, 8.2, 8.7_
  - [ ]* 9.4 Verify end-to-end signing in PROD + lifecycle independence (Property 5) **[Pi PROD]**
    - **Property 5: End-to-end signing reachability**
    - **Validates: Requirements 6.4, 12.1, 12.2, 12.3**
    - Health check green at the internal (`http://documenso:3030` via alias) and public (`https://esignd.oraflows.co.nz`) URLs; create a signing document (visible in the OraSign DB) and observe the completion event back in OraInvoice; redeploy the OraInvoice `app` (with the guard line) and assert OraSign keeps serving with an unchanged image digest (Requirements 8.1, 8.7); only run after the DEV checkpoint passed (Requirement 12.4)

- [ ] 10. Backup/restore procedure and documentation **[OraSign repo / Pi PROD docs]**
  - [ ] 10.1 Document the OraSign DB backup and restore procedures
    - Backup: `pg_dump` of the `orasign-production` `database` service piped to gzip; Restore: `gunzip | psql` into the `orasign_pgdata` volume; note the volume-snapshot alternative
    - _Requirements: 11.3, 11.4_
  - [ ] 10.2 Update project documentation (CHANGELOG/docs) **[OraInvoice repo]**
    - Record the standalone OraSign stack, the `orasign_default` rename + `documenso` alias, the fresh-DB cutover, the guard/update lifecycle split, and the backup/restore runbooks
    - _Requirements: 1.1, 7.2, 10.1_

- [ ] 11. Final checkpoint — full cutover verified
  - Ensure DEV and PROD end-to-end signing pass, the legacy documenso stack is retired, the guard is wired into the OraInvoice deploy flow, and backup/restore is documented. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional verification sub-tasks (deterministic smoke/integration checks) and can be skipped for a faster bring-up, but they are how the five correctness properties are validated. **There are no property-based tests** — this is infrastructure wiring whose behavior does not vary with generated inputs.
- **Two repos:** tasks are labelled **[OraSign repo]** (separate workspace/clone, remote `arshdeepromy/Orasign`) or **[OraInvoice repo]** (this workspace). The OraSign work is authored in its own clone; the only OraInvoice source edit is the one-line network rename plus deploy-flow/doc wiring.
- **Repo split is already done** — task 1 only verifies the resulting state; there is no task to perform the split.
- **Fresh DB (Option B):** both environments start empty; there are **no data-migration tasks**. Legacy `documenso_*` references in OraInvoice are accepted to dangle; any legacy `pg_dump` is an optional archive that is never restored.
- **DEV-before-PROD gating** is enforced by the checkpoint (task 8): the Pi PROD tasks (9.x) — flagged **[Pi PROD — PRODUCTION, REAL DATA]** — must not run until the DEV verification passes (Requirement 12.4).
- No OraInvoice application code, DB columns, error codes, stored `base_url`, or esignatures module logic change — only the network reference, the guard-invocation line, and cosmetic comments.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "2.3", "3.1", "3.2", "3.3", "4.1", "5.1", "6.1", "6.2"] },
    { "id": 1, "tasks": ["2.2", "2.4", "3.4", "6.4"] },
    { "id": 2, "tasks": ["7.1"] },
    { "id": 3, "tasks": ["6.3"] },
    { "id": 4, "tasks": ["7.2", "7.3"] },
    { "id": 5, "tasks": ["7.4"] },
    { "id": 6, "tasks": ["7.5"] },
    { "id": 7, "tasks": ["4.2"] },
    { "id": 8, "tasks": ["5.2"] },
    { "id": 9, "tasks": ["9.1"] },
    { "id": 10, "tasks": ["9.2"] },
    { "id": 11, "tasks": ["9.3"] },
    { "id": 12, "tasks": ["9.4"] },
    { "id": 13, "tasks": ["10.1", "10.2"] }
  ]
}
```
