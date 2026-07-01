# Implementation Plan: OraSign Standalone Deployment (Local DEV only)

## Overview

This is an infrastructure/deployment effort spanning **two separate git repositories**, not application code, and its scope is **local DEV only**:

- **[OraSign repo]** — `github.com/arshdeepromy/Orasign`, cloned to a separate path on the local DEV host (independent of the OraInvoice clone). Owns the new standalone dev compose file, the `docker/Dockerfile`, Prisma migrations, the DEV env template, the signing-cert mount, and the guard/update scripts.
- **[OraInvoice repo]** — `arshdeepromy/Orainvoice`, this workspace. Receives a **single one-line network-reference change** in `docker-compose.dev.yml` plus docs/CHANGELOG wiring. No application code, DB columns, error codes, stored `base_url`, or esignatures logic change.

**Pi PROD is explicitly OUT OF SCOPE** and deferred to a future follow-up spec. There are therefore **no** production/Pi tasks in this plan: no `.env.pi`/Pi-compose work, no nginx `esignd` upstream repoint, no Cloudflare tunnel, no `esignd.oraflows.co.nz` public URL, and **no DEV-before-PROD gating checkpoint**. The guard and update scripts are still authored here (in the OraSign repo) and written to be reusable by that future PROD spec.

Key facts driving the tasks:

- The dev compose is **authored from scratch** as a new file `docker/development/compose.standalone.yml`. The OraSign repo's existing `docker/development/compose.yml` is a **contributor** stack (`database`, `inbucket`, `redis`, `minio`, `gotenberg`) with **no app service and no `orasign_default` network** — it cannot be adapted.
- The app image is **built locally** with `build: { context: ../.., dockerfile: docker/Dockerfile }` — context is the repo root because the compose file lives under `docker/development/` and the Dockerfile does `COPY . .` from the root. **Not** `context: ..`.
- Mail capture is **inbucket** (SMTP 2500, web UI 9000) — not maildev. OraSign SMTP points at `inbucket:2500`.
- **PDF-only** — OraInvoice uploads only PDFs (WeasyPrint), so **no gotenberg / no document-conversion tasks**.
- App reachability is the **`/api/health`** endpoint (per `docker/start.sh`). The `/health` path in the contributor compose is gotenberg's, not the app's.
- **Fresh DB (Option B)** — the OraSign database starts empty; there are **no data-migration tasks**. Legacy `documenso_*` references in OraInvoice are accepted to dangle.

The network rename keeps a compatibility **alias**: the external Docker network becomes `orasign_default`, and the OraSign `app` service carries the alias `documenso` so the stored internal base_url `http://documenso:3030` still resolves with **no OraInvoice code/DB change**.

Because this is network/volume/config/script wiring, verification uses **deterministic smoke and integration checks** — **there are no property-based tests** (behavior does not vary with generated inputs). Each task is labelled with the repo it touches.

## Tasks

- [ ] 1. Verify repository-split state (both repos, read-only)
  - [ ] 1.1 Verify the OraSign repo holds the OraSign source **[OraSign repo]**
    - Confirm the OraSign clone contains `docker/Dockerfile`, `docker/start.sh`, `packages/prisma`, and `docker/development/` (the contributor `compose.yml`); confirm the remote is `github.com/arshdeepromy/Orasign` with a clean single-commit history; confirm the clone path is separate from the OraInvoice clone
    - _Requirements: 1.1, 1.3, 1.4_
  - [ ] 1.2 Verify the OraInvoice repo contains no OraSign source **[OraInvoice repo]**
    - Confirm no `/OraSign` (or prior subfolder) path exists in this workspace and that git history no longer tracks OraSign source; confirm the OraInvoice remote is `arshdeepromy/Orainvoice`
    - _Requirements: 1.2, 1.5_

- [ ] 2. Author the standalone DEV compose from scratch **[OraSign repo]**
  - [ ] 2.1 Create `docker/development/compose.standalone.yml`
    - `name: orasign-development`. Define a `database` service (`postgres:15`) with `POSTGRES_USER/PASSWORD/DB` from env, a `pg_isready -U ${POSTGRES_USER}` healthcheck, and the named volume `orasign_pgdata_dev`
    - Define an `inbucket` service for local mail capture (`inbucket/inbucket`), publishing web UI `9000:9000` and SMTP `2500:2500`
    - Define an `app` service **built locally**: `build: { context: ../.., dockerfile: docker/Dockerfile }` (repo root context; **no** `image:` registry pull, **not** `context: ..`); `depends_on: database (condition: service_healthy)`; `PORT=${PORT:-3030}`; publish `${ORASIGN_HOST_PORT:-3030}:${PORT:-3030}` (distinct from OraInvoice DEV port 80 / DB 5434 and from inbucket 9000/2500)
    - Point OraSign SMTP env at inbucket: `NEXT_PRIVATE_SMTP_HOST=inbucket`, `NEXT_PRIVATE_SMTP_PORT=2500`; set `NEXT_PUBLIC_UPLOAD_TRANSPORT=database`
    - Attach `app` to `default` and to the external `orasign_default` network with the network **alias `documenso`** so `http://documenso:3030` still resolves; declare top-level `networks: { orasign_default: { external: true } }` and `volumes: { orasign_pgdata_dev: }`
    - Mount the signing cert read-only at `${NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH:-/opt/orasign/cert.p12}` (`./certs/cert.p12:/opt/orasign/cert.p12:ro`); enforce required env with `${VAR:?err}`
    - **OMIT** `redis`, `minio`, and `gotenberg` — none are needed for the DEV signing integration (PDF-only)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.5, 4.4, 4.5, 4.6, 5.1, 5.3, 5.5, 7.1, 12.2_
  - [ ]* 2.2 Smoke-check the standalone dev compose definition
    - `docker compose -f docker/development/compose.standalone.yml config` parses; project is `orasign-development`; services are exactly `database`, `inbucket`, `app` (no `redis`/`minio`/`gotenberg`); volume `orasign_pgdata_dev`; `app` declares `build:` with `context: ../..` and `dockerfile: docker/Dockerfile` (no `image:`); alias `documenso` on `orasign_default`; cert mounted `:ro`; published ports and volume name do not collide with OraInvoice
    - _Requirements: 2.1, 2.2, 2.3, 5.3, 7.1, 12.2_

- [ ] 3. Author the DEV env template, secret handling, and signing-cert mount **[OraSign repo]**
  - [ ] 3.1 Create `docker/development/.env.example`
    - Document required vs optional/default vars for local DEV
    - Required (`:?err`): `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY`, `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY`, `NEXT_PUBLIC_WEBAPP_URL=http://localhost:3030`, `NEXT_PRIVATE_DATABASE_URL` (host `database`), `POSTGRES_USER/PASSWORD/DB`, `NEXT_PRIVATE_SMTP_FROM_NAME/ADDRESS`
    - Optional/defaults: `NEXT_PRIVATE_DIRECT_DATABASE_URL` (falls back to `NEXT_PRIVATE_DATABASE_URL`), `PORT=3030`, `ORASIGN_HOST_PORT=3030`, `NEXT_PUBLIC_UPLOAD_TRANSPORT=database`, `NEXT_PRIVATE_SMTP_TRANSPORT=smtp-auth`, `NEXT_PRIVATE_SMTP_HOST=inbucket`, `NEXT_PRIVATE_SMTP_PORT=2500`, `NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH=/opt/orasign/cert.p12`, `NEXT_PRIVATE_SIGNING_PASSPHRASE`
    - _Requirements: 4.1, 4.2, 4.3, 4.4_
  - [ ] 3.2 Exclude real `.env` files and certs from version control
    - Add/confirm `.gitignore` entries so `docker/**/.env` and `docker/development/certs/` are ignored; only `.env.example` is committed
    - _Requirements: 4.7_
  - [ ] 3.3 Provision the DEV signing-certificate mount
    - Place/document the DEV PKCS#12 cert at `docker/development/certs/cert.p12` (git-ignored), mounted read-only at `/opt/orasign/cert.p12`; document that a missing cert only disables signing (start.sh warns, non-signing flows stay up) and that `NEXT_PRIVATE_SIGNING_PASSPHRASE` must be set
    - _Requirements: 4.5_
  - [ ]* 3.4 Smoke-check configuration and secret handling
    - Unset one required var and assert `up` aborts with a message naming that variable (`${VAR:?err}`); assert real `.env` and `certs/` are git-ignored via `git check-ignore`
    - _Requirements: 4.6, 4.7_

- [ ] 4. Author the guard script (start-if-down, never rebuild) **[OraSign repo]**
  - [ ] 4.1 Create `scripts/ensure-orasign.sh`
    - Idempotent guard: count running containers in the `orasign-development` project; if any are running → no-op; if stopped → `docker compose -f docker/development/compose.standalone.yml --env-file docker/development/.env -p orasign-development up -d` **without** `--build`, no `git pull`, no `--force-recreate`; never rebuilds or upgrades
    - Parameterise `ORASIGN_DIR`, `ORASIGN_PROJECT`, compose file, and `--env-file`; make executable; written to be reusable by the future Pi PROD spec
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [ ]* 4.2 Verify guard idempotency
    - With the stack up, capture container IDs + image digest; run the guard three times and assert IDs/digest unchanged and no `build`/`create` occurred; then bring the stack `down`, run the guard once, and assert it comes up **without** a rebuild (image digest equals the pre-existing local build)
    - _Requirements: 8.2, 8.3, 8.4_

- [ ] 5. Author the explicit update command (only rebuild path) **[OraSign repo]**
  - [ ] 5.1 Create `scripts/update-orasign.sh`
    - The sole path that `git pull`s the OraSign repo at its clone path, `docker compose ... build`s the local image, and `docker compose ... up -d` recreates containers; run explicitly by an operator, never by the OraInvoice deploy flow; make executable; reusable by the future Pi PROD spec
    - _Requirements: 7.2, 8.5, 8.6_
  - [ ]* 5.2 Verify update-command exclusivity
    - Run `update-orasign.sh`; assert it pulls, rebuilds (new image digest), and recreates. Confirm no other script (including the guard) performs a rebuild
    - _Requirements: 8.5, 8.6_

- [ ] 6. Apply the single OraInvoice network edit and retire the legacy stack **[OraInvoice repo / host]**
  - [ ] 6.1 Repoint `docker-compose.dev.yml` external network `documenso_default` → `orasign_default` **[OraInvoice repo]**
    - Change the `app` service `networks:` entry and the bottom `networks:` declaration from `documenso_default` to `orasign_default`; leave the stored base_url `http://documenso:3030` unchanged (resolved via the alias)
    - Do NOT touch OraInvoice app code, DB columns (`documenso_document_id`/`documenso_team_id`/`documenso_recipient_id`), the `documenso_error` code, the esignatures module, or `NEXT_PRIVATE_DOCUMENSO_*` / `ESIGN_DOCUMENSO_*` env names; comment updates are cosmetic only. No Pi compose edits (Pi PROD out of scope)
    - _Requirements: 6.1, 6.2, 6.5, 10.5_
  - [ ] 6.2 Retire the legacy Documenso local dev stack **[OraInvoice repo / host]**
    - Optionally take a `pg_dump` of the legacy `documenso-db` as an off-to-the-side **archive only** (NEVER restored into OraSign); then `docker compose -f documenso/docker-compose.yml down` the `documenso` project; ensure no OraSign workload depends on the `documenso` project/container or the legacy `documenso_default` network name
    - _Requirements: 3.8, 10.1, 10.3, 10.4, 10.5_
  - [ ]* 6.3 Smoke-check the OraInvoice change surface
    - Assert the only functional edit in the OraInvoice diff is the external-network name change in `docker-compose.dev.yml`; assert the stored per-org `base_url` is still `http://documenso:3030` and no `app/`, `DocumensoClient`, DB-column, or error-code change is present
    - _Requirements: 6.2, 6.3, 6.5_

- [ ] 7. Local DEV bring-up and end-to-end signing verification **[local DEV]**
  - [ ] 7.1 Create the network and bring up the DEV stack alongside OraInvoice
    - `docker network create orasign_default` (idempotent); bring up `orasign-development` with `docker compose -f docker/development/compose.standalone.yml --env-file docker/development/.env up -d --build`; recreate the OraInvoice dev `app` on `orasign_default`; start with a fresh, empty OraSign DB (no data carry-over)
    - _Requirements: 3.6, 7.2, 7.3, 9.1, 9.3_
  - [ ]* 7.2 Verify data isolation
    - Inspect the OraSign `app` container: its only DB route is the in-stack `database` service; connect to both the OraSign and OraInvoice databases and assert disjoint table sets; assert no OraInvoice mounts/links/connection strings
    - _Requirements: 2.6, 3.3, 3.4, 3.5_
  - [ ]* 7.3 Verify reachability, URL resolution via the `documenso` alias, and startup migrations
    - From the OraInvoice app container, `curl http://documenso:3030/api/health` succeeds via the alias with the stored base_url unchanged; assert Prisma `migrate deploy` ran on the fresh volume before serving
    - _Requirements: 3.2, 5.4, 6.3, 6.4, 9.3, 10.2, 13.1_
  - [ ]* 7.4 Verify persistence across restart/recreation
    - Write data, `docker compose ... down` (without `-v`), `up`, and assert the data is still present
    - _Requirements: 11.1, 11.2_
  - [ ]* 7.5 Verify end-to-end signing in DEV
    - From an OraInvoice org, initiate a signing request → assert the document row is created in the OraSign DB and a consumable response returns; complete the document → assert OraInvoice receives the completion event over the existing integration path; verify the signing email is captured in the inbucket web UI (`http://localhost:9000`); on any failure, the procedure reports the failing stage (reachability, document creation, or signing-event delivery)
    - _Requirements: 6.4, 12.1, 13.2, 13.3, 13.4_

- [ ] 8. Checkpoint — DEV verification complete
  - Ensure all DEV smoke and integration checks pass (data isolation, alias URL resolution, startup migrations, persistence, guard idempotency, update exclusivity, end-to-end signing). Ask the user if questions arise.

- [ ] 9. Backup/restore procedure and documentation
  - [ ] 9.1 Document the OraSign DEV DB backup and restore procedures **[OraSign repo]**
    - Backup: `pg_dump` of the `orasign-development` `database` service piped to gzip; Restore: `gunzip | psql` into the `orasign_pgdata_dev` volume; note the volume-snapshot alternative
    - _Requirements: 11.3, 11.4_
  - [ ] 9.2 Update project documentation (CHANGELOG/docs) **[OraInvoice repo]**
    - Record the standalone OraSign DEV stack, the `orasign_default` rename + `documenso` alias, the fresh-DB cutover, inbucket mail capture, the guard/update lifecycle split, and the backup/restore runbook; note that Pi PROD is deferred to a future spec
    - _Requirements: 1.1, 7.4, 10.1_

- [ ] 10. Final checkpoint — DEV cutover verified
  - Ensure DEV end-to-end signing passes, the legacy documenso stack is retired, the guard/update scripts are authored, and backup/restore is documented. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional verification sub-tasks (deterministic smoke/integration checks) and can be skipped for a faster bring-up. **There are no property-based tests** — this is infrastructure wiring whose behavior does not vary with generated inputs.
- **Two repos:** tasks are labelled **[OraSign repo]** (separate clone, remote `arshdeepromy/Orasign`) or **[OraInvoice repo]** (this workspace). The OraSign work is authored in its own clone; the only OraInvoice source edit is the one-line network rename plus docs/CHANGELOG.
- **Repo split is already done** — task 1 only verifies the resulting state; there is no task to perform the split.
- **Local DEV only.** Pi PROD is out of scope and deferred to a future follow-up spec: no Pi/PROD deploy task, no `.env.pi`/Pi-compose edits, no nginx `esignd` repoint, no Cloudflare tunnel, no `esignd.oraflows.co.nz` URL, and **no DEV-before-PROD gating checkpoint**.
- **Standalone dev compose is authored from scratch** (`docker/development/compose.standalone.yml`); the contributor `compose.yml` is not adapted (it has no app service and no `orasign_default` network).
- **Local build:** the app image is built with `context: ../..` (repo root) and `dockerfile: docker/Dockerfile` — not pulled from a registry.
- **PDF-only:** no gotenberg / no document-conversion tasks; mail capture is inbucket (SMTP 2500, web UI 9000).
- **Fresh DB (Option B):** the OraSign DB starts empty; there are **no data-migration tasks**. Legacy `documenso_*` references in OraInvoice are accepted to dangle; any legacy `pg_dump` is an optional archive that is never restored.
- No OraInvoice application code, DB columns, error codes, stored `base_url`, or esignatures module logic change — only the one-line network reference and cosmetic comments.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "2.1", "3.1", "3.2", "4.1", "5.1", "6.1"] },
    { "id": 1, "tasks": ["2.2", "3.3", "6.3"] },
    { "id": 2, "tasks": ["3.4", "6.2"] },
    { "id": 3, "tasks": ["7.1"] },
    { "id": 4, "tasks": ["7.2", "7.3", "7.4", "4.2", "5.2"] },
    { "id": 5, "tasks": ["7.5"] },
    { "id": 6, "tasks": ["9.1", "9.2"] }
  ]
}
```
