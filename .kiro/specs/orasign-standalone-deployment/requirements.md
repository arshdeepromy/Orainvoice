# Requirements Document

## Introduction

OraInvoice integrates a self-hosted e-signature engine for sending and signing documents. That engine was forked, self-managed, and rebranded to **OraSign**. OraSign has now been **extracted out of the OraInvoice repository into its own separate git repository** — `github.com/arshdeepromy/Orasign` (private), with a clean single-commit history. OraInvoice's git history was purged of the OraSign folder and force-pushed, and the `/OraSign` path no longer exists in the OraInvoice workspace. **OraInvoice and OraSign are now two completely separate products, repositories, and codebases.**

### Scope: Local DEV only

This spec covers standing up OraSign as a standalone product in the **local DEV Deployment_Environment only** — the Ubuntu host, running as its own Docker Compose project alongside the OraInvoice `invoicing` project. End-to-end signing verification happens in local DEV.

**Pi PROD deployment is explicitly OUT OF SCOPE** and deferred to a future follow-up spec. The reason is that the e-signature integration currently exists **only** in local DEV: it is wired through `docker-compose.dev.yml` (the only OraInvoice compose file that declares the external `documenso_default` network and the `ESIGN_*` environment). Pi PROD has **no** e-signature wiring at all — no `documenso_default` network, no `ESIGN_*` variables in `.env.pi`, no nginx `esignd` route, and no Cloudflare tunnel for `esignd`. A Pi rollout is therefore a greenfield first-time deployment, not an adaptation of an existing wiring, and is intentionally left to a future spec. There is no Pi deploy, no `esignd.oraflows.co.nz` public-URL requirement, and no "DEV-before-PROD gating" in this spec.

### Standalone stack model

OraSign is operated as a **completely separate, standalone product** that runs **alongside** OraInvoice on the local DEV host but is an **independent deployable with an independent update lifecycle**. OraSign spins up and owns its **own PostgreSQL database**, runs as its **own Docker Compose project** (`orasign-development`, with its own containers, volume, and exposed port on 3030), and manages its own schema through its own Prisma migrations. It is never merged into OraInvoice's compose.

### The dev compose is authored from scratch, not adapted

The OraSign repository's existing `docker/development/compose.yml` is a **contributor** stack — services `database` (postgres:15, volume `orasign_database`), `inbucket` (mail capture, ports 9000/2500/1100), `redis`, `minio`, and `gotenberg`. It has **no OraSign app service and no `orasign_default` network**. The standalone dev stack therefore requires **authoring a new app service** (built locally) that joins `orasign_default` with the alias `documenso`, rather than adapting an existing app service. Mail is captured with **inbucket** (the stack's existing mail tool), not maildev.

### Corrected build and runtime facts

- **Local image build context is the repo root (`../..`).** The Dockerfile (`docker/Dockerfile`) does `COPY . .` from the repo root; the compose files sit under `docker/production/` and `docker/development/`, so the app service builds with `build: { context: ../.., dockerfile: docker/Dockerfile }`.
- **Health endpoint is `/api/health`** (confirmed in `docker/start.sh`). The `/health` path used by the contributor dev compose is the gotenberg container's healthcheck, not the OraSign app's.
- **Schema migration on startup:** `docker/start.sh` already runs `npx prisma migrate deploy` on startup, bringing a fresh or existing database to the current schema before the server boots.
- **Document conversion (gotenberg) is not required for this integration.** OraInvoice generates PDFs via WeasyPrint and uploads **only PDFs** for signing, so the gotenberg document-conversion service is unnecessary. If a non-PDF document is ever sent for signing, conversion is unsupported unless a gotenberg service is added (flagged, out of scope now).

### Existing integration is unchanged

OraInvoice already integrates with the signing service over its **API**. That integration's application logic — the esignatures module, the `DocumensoClient` class, the per-organisation connection stored envelope-encrypted in the OraInvoice database (with its stored internal base_url `http://documenso:3030`), and the Global Admin GUI that configures it — is **already configured and working** and is **not changed by this spec**. To keep that connection working with **no change to OraInvoice application code or the OraInvoice database**, the network rename is done with a compatibility alias: the Docker network is renamed `documenso_default` → `orasign_default`, and the OraSign app service keeps a network **alias `documenso`** so that the stored internal base_url `http://documenso:3030` still resolves to the OraSign app container.

### OraInvoice Scope

OraInvoice code and database are **otherwise out of scope**. The **only permitted OraInvoice edit** is a **one-line docker-compose external-network name reference** in **`docker-compose.dev.yml`** — repointing the OraInvoice app service's external network from `documenso_default` to `orasign_default`. This is a dev file, which fits the DEV-only scope, and the change is infrastructure configuration only. Specifically, this spec does **not** modify any of the following, all of which are already configured and working:

- OraInvoice application code (`app/`, `frontend-v2/`, `mobile/`, `tests/`, `scripts/`).
- The OraInvoice integration client class (`DocumensoClient`) or any of its symbols.
- The OraInvoice database columns `documenso_document_id`, `documenso_team_id`, `documenso_recipient_id`.
- The stored per-organisation connection `base_url` value (`http://documenso:3030`) — it is preserved and continues to resolve via the `documenso` network alias.
- The OraInvoice API error code `documenso_error`.
- The OraInvoice esignatures module logic.
- The OraInvoice environment variable **names** `NEXT_PRIVATE_DOCUMENSO_*` / `ESIGN_DOCUMENSO_*`.

### Fresh Database (Option B)

OraSign starts with a **fresh, empty PostgreSQL database** in local DEV. There is no data carry-over or migration from the legacy documenso stack. Any documents created in the old documenso instance are **not** migrated (accepted cutover consequence).

### Future work

A future follow-up spec will cover the first-time Pi PROD deployment of OraSign (public URL, nginx route, Cloudflare tunnel, and PROD compose project). The Guard_Script and Update_Command authored here are written so they are reusable by that future spec.

## Glossary

- **OraSign_Service**: The self-managed, self-hosted e-signature engine (the rebranded fork), operated as a standalone product with its own repository, database, and containers.
- **OraSign_Repository**: The separate, private git repository `github.com/arshdeepromy/Orasign` that holds all OraSign source code. It is independent of the OraInvoice repository.
- **OraInvoice_Repository**: The OraInvoice git repository (`arshdeepromy/Orainvoice`). It contains no OraSign source code after the repo split.
- **OraSign_Stack**: The independent Docker Compose project that runs OraSign in local DEV — comprising the OraSign **App_Container**, the OraSign **Database_Container**, the OraSign **Data_Volume**, the DEV **Mail_Capture** service, and the network it exposes. The development project name is `orasign-development`.
- **App_Container**: The OraSign application service, serving the OraSign web app and API on its configured port (3030). Its Docker image is **built locally** from the OraSign_Repository's `docker/Dockerfile` using the build context `../..` (the repo root), not pulled from a public registry.
- **Database_Container**: The PostgreSQL 15 service owned by the OraSign_Stack, holding the OraSign schema and data.
- **Data_Volume**: The Docker named volume backing the Database_Container's PostgreSQL data directory (`orasign_pgdata_dev` in development).
- **Mail_Capture**: The DEV-only mail capture service (**inbucket**) that captures signing emails locally instead of delivering them, so signing flows can be verified in local DEV.
- **OraSign_Database**: The PostgreSQL database instance owned and initialised by the OraSign_Stack, entirely separate from the OraInvoice_Database.
- **OraInvoice_Database**: The PostgreSQL database owned by OraInvoice (DB port 5434 on local DEV). Out of scope for modification.
- **OraInvoice_App**: The main OraInvoice application and its containers. Out of scope for modification except the single permitted Network_Reference_Change.
- **OraSign_Clone_Path**: The filesystem path into which the OraSign_Repository is cloned on the local DEV host, independent of the OraInvoice clone path.
- **API_Integration**: The existing, already-configured connection by which OraInvoice's esignatures module calls the OraSign_Service over HTTP/API using a per-organisation, envelope-encrypted connection record stored in the OraInvoice_Database and configured via the Global Admin GUI.
- **Configured_API_URL**: The OraSign_Service internal base URL that the OraInvoice API_Integration is configured to call — the stored internal host `http://documenso:3030` for server-to-server calls, resolved via the `documenso` network alias.
- **Health_Endpoint**: The OraSign_Service reachability endpoint `/api/health` (per `docker/start.sh`), used to verify the App_Container is serving.
- **Network_Alias**: The Docker network alias `documenso` attached to the OraSign App_Container on the `orasign_default` network, so that the OraInvoice_App's stored base_url `http://documenso:3030` continues to resolve to the OraSign App_Container without any OraInvoice code or database change.
- **Network_Reference_Change**: The single permitted OraInvoice edit — a one-line change to the OraInvoice_App's external-network name reference in `docker-compose.dev.yml`, from `documenso_default` to `orasign_default`. Infrastructure configuration only; touches no OraInvoice application code, database, error codes, or esignatures module logic.
- **Guard_Script**: The script `scripts/ensure-orasign.sh` in the OraSign_Repository that ensures the OraSign_Stack is running without rebuilding. If the stack is already running, it makes no change; if it is not running, it starts the OraSign_Stack without rebuilding. It never rebuilds or upgrades OraSign.
- **Update_Command**: The explicit OraSign update command `scripts/update-orasign.sh` in the OraSign_Repository — the sole path that pulls the OraSign_Repository, rebuilds the App_Container image locally, and recreates the OraSign containers.
- **Legacy_Documenso_Stack**: The retired local development stack — compose project `documenso`, container `documenso-documenso-1`, and external network name `documenso_default` — being replaced by the OraSign_Stack on the renamed `orasign_default` network.
- **Deployment_Environment**: The environment this spec targets — the local DEV Ubuntu host.
- **OraSign_Configuration**: The set of environment-driven values the App_Container requires at startup — including `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY` (and secondary), `NEXT_PUBLIC_WEBAPP_URL`, `NEXT_PRIVATE_DATABASE_URL`, `NEXT_PRIVATE_DIRECT_DATABASE_URL`, the upload transport, the email transport (SMTP pointed at the DEV Mail_Capture service), and the signing certificate.
- **Signing_Certificate**: The PKCS#12 signing certificate the App_Container uses to seal signed documents, mounted read-only at `/opt/orasign/cert.p12`.
- **Prisma_Migrations**: The OraSign-owned database migrations under the OraSign_Repository's Prisma package, applied by `docker/start.sh` via `npx prisma migrate deploy` against the OraSign_Database on startup.

## Requirements

### Requirement 1: Repository Separation

**User Story:** As a developer, I want OraSign source code to live only in its own repository, so that OraInvoice and OraSign are maintained as two independent codebases.

#### Acceptance Criteria

1. THE OraSign_Service source code SHALL reside only in the OraSign_Repository (`github.com/arshdeepromy/Orasign`).
2. THE OraInvoice_Repository SHALL contain no OraSign_Service source code.
3. THE OraSign_Repository SHALL be an independent git repository with its own commit history, separate from the OraInvoice_Repository history.
4. THE OraSign_Stack SHALL be built and deployed from a clone of the OraSign_Repository at the OraSign_Clone_Path, independent of the OraInvoice_App clone location.
5. THE OraSign_Repository SHALL be updated on its own lifecycle independently of the OraInvoice_Repository.

### Requirement 2: Standalone OraSign Stack Definition

**User Story:** As an operator, I want OraSign to run as its own self-contained Docker Compose stack in local DEV, so that it is a completely separate product from OraInvoice with its own lifecycle.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL be defined as an independent Docker Compose project that is separate from any OraInvoice compose project, using the project name `orasign-development`.
2. THE OraSign_Stack SHALL include a Database_Container, an App_Container authored specifically for the standalone stack, a Data_Volume backing the Database_Container, and the DEV Mail_Capture service.
3. WHERE the OraSign_Repository's contributor `docker/development/compose.yml` provides no OraSign app service and no `orasign_default` network, THE OraSign_Stack SHALL define a new App_Container service and the `orasign_default` network rather than reusing the contributor stack unchanged.
4. THE OraSign_Stack SHALL run alongside the OraInvoice_App as a separate stack AND SHALL NOT be merged into any OraInvoice compose project or file.
5. WHERE the App_Container depends on the Database_Container, THE OraSign_Stack SHALL start the App_Container only after the Database_Container reports a healthy status.
6. THE OraSign_Stack SHALL NOT modify, attach to, or depend on the OraInvoice_Database, OraInvoice containers, or OraInvoice volumes for its own operation.

### Requirement 3: OraSign Owns and Initialises Its Own Fresh Database

**User Story:** As an operator, I want OraSign to own and initialise its own fresh PostgreSQL database and schema, so that OraSign data is fully independent of OraInvoice and of the retired legacy stack.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL provision its own PostgreSQL 15 Database_Container with its own credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) supplied through OraSign_Configuration.
2. WHEN the App_Container starts, THE OraSign_Service SHALL apply its Prisma_Migrations via `npx prisma migrate deploy` against the OraSign_Database so that the OraSign schema is created or brought up to date before the server serves requests.
3. THE OraSign_Database SHALL be independent from the OraInvoice_Database such that the two share no tables and no schema (data-isolation property).
4. THE OraSign_Service SHALL read and write OraSign application data only from the OraSign_Database AND SHALL NOT read from or write to the OraInvoice_Database.
5. WHEN OraSign application data is persisted, THE OraSign_Stack SHALL store that data only in its own Data_Volume.
6. THE OraSign_Stack SHALL start with a fresh, empty OraSign_Database in the local DEV Deployment_Environment, with no carry-over or migration of legacy signing data from the Legacy_Documenso_Stack (fresh-database decision, Option B).
7. WHERE signing documents were previously created in the Legacy_Documenso_Stack, THE OraSign_Stack SHALL leave the corresponding OraInvoice references (`documenso_document_id`, `documenso_recipient_id`, `documenso_team_id`) unresolved against the fresh OraSign_Database, so that historical signings on the legacy service do not resolve against the OraSign_Database (accepted cutover consequence).
8. WHERE a pre-cutover backup of the Legacy_Documenso_Stack database is taken, THE OraSign_Stack SHALL treat that backup as an optional safety archive only AND SHALL NOT restore it into the OraSign_Database.

### Requirement 4: OraSign Configuration and Secrets

**User Story:** As an operator, I want every required OraSign configuration value and secret defined for local DEV, so that the App_Container starts cleanly and operates securely.

#### Acceptance Criteria

1. THE OraSign_Configuration SHALL define `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY`, and `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY` for the App_Container.
2. THE OraSign_Configuration SHALL define `NEXT_PRIVATE_DATABASE_URL` and `NEXT_PRIVATE_DIRECT_DATABASE_URL` pointing at the OraSign_Database Database_Container.
3. THE OraSign_Configuration SHALL define `NEXT_PUBLIC_WEBAPP_URL` set to the local DEV URL at which the OraSign_Service is reached (`http://localhost:3030`).
4. THE OraSign_Configuration SHALL define an email transport that directs signing emails to the DEV Mail_Capture (inbucket) service so that emails are captured locally rather than delivered externally.
5. THE OraSign_Stack SHALL mount the Signing_Certificate read-only into the App_Container at the path referenced by `NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH` (default `/opt/orasign/cert.p12`).
6. IF a required OraSign_Configuration value is unset when the App_Container starts, THEN THE OraSign_Stack SHALL fail startup with an error that names the missing value.
7. THE OraSign_Stack SHALL store secret OraSign_Configuration values in environment files that are excluded from version control.

### Requirement 5: Network Rename, Alias, and Port Allocation

**User Story:** As an operator, I want OraSign to expose a distinct port and to be reachable on the renamed Docker network under a compatibility alias, so that OraInvoice reaches it without any OraInvoice application or database change.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL expose the App_Container on a listen port of 3030 so that the stored internal base_url `http://documenso:3030` resolves to the App_Container.
2. THE OraSign_Stack SHALL publish the App_Container on a host port that does not collide with any port already used by the OraInvoice_App in the local DEV Deployment_Environment.
3. THE OraSign_Stack SHALL attach the App_Container to the external Docker network `orasign_default` with the Network_Alias `documenso`.
4. WHEN the OraInvoice_App resolves the Configured_API_URL `http://documenso:3030`, THE OraSign_Stack SHALL ensure that URL routes to the standalone OraSign_Service App_Container over the `orasign_default` network via the `documenso` Network_Alias (URL-resolution property).
5. THE OraSign_Stack SHALL provision its Data_Volume with a name that does not collide with any OraInvoice volume in the local DEV Deployment_Environment.

### Requirement 6: OraInvoice Integration Limited to One-Line Network Reference

**User Story:** As a developer, I want the OraInvoice-to-OraSign integration to require only a single infrastructure-config line change in OraInvoice, so that signing continues to work against the standalone service with no OraInvoice application code, database, error-code, or module-logic changes.

#### Acceptance Criteria

1. THE Network_Reference_Change SHALL be limited to repointing the OraInvoice_App's external-network name reference from `documenso_default` to `orasign_default` in `docker-compose.dev.yml`.
2. THE OraSign_Stack SHALL NOT require any change to OraInvoice_App application code, the stored per-organisation connection `base_url` value, the OraInvoice_Database columns, the OraInvoice API error code, or the esignatures module logic in order to integrate with the standalone OraSign_Service.
3. THE OraSign_Service SHALL accept API calls from the OraInvoice_App at the Configured_API_URL `http://documenso:3030` using the per-organisation connection already stored in the OraInvoice_Database with its unchanged `base_url`.
4. WHEN the OraInvoice_App sends a signing request to the Configured_API_URL, THE OraSign_Service SHALL process that request against its own OraSign_Database.
5. THE OraSign_Stack SHALL NOT alter the structure or the stored `base_url` value of the per-organisation OraSign connection record in the OraInvoice_Database, nor the Global Admin GUI logic that configures it.

### Requirement 7: Local-Build Deployment Mirroring OraInvoice

**User Story:** As an operator, I want OraSign deployed by pulling its repo and building its image locally, so that its deployment mirrors OraInvoice's local-build model and depends on no public image registry.

#### Acceptance Criteria

1. THE App_Container image SHALL be built locally from the OraSign_Repository's `docker/Dockerfile` using the build context `../..` (the repo root) AND SHALL NOT be pulled from a public image registry.
2. WHEN OraSign is brought up in local DEV, THE deployment SHALL build the App_Container image locally, then run `docker compose up -d` for the OraSign_Stack.
3. THE OraSign_Clone_Path SHALL be a path owned by OraSign that is separate from the OraInvoice_App clone location.
4. THE OraSign local-build deployment SHALL mirror the OraInvoice model in which the OraInvoice `app` image is built locally rather than pulled.

### Requirement 8: Deployment Lifecycle Separation and Guard Script

**User Story:** As an operator, I want OraInvoice and OraSign lifecycles kept separate in local DEV, so that acting on OraInvoice never disturbs a running OraSign stack and OraSign is only rebuilt on an explicit command.

#### Acceptance Criteria

1. THE Guard_Script (`scripts/ensure-orasign.sh`) SHALL ensure the OraSign_Stack is running without rebuilding the App_Container image.
2. WHILE the OraSign_Stack is already running, THE Guard_Script SHALL make no change to the OraSign_Stack and SHALL NOT rebuild it (guard-idempotency property).
3. IF the OraSign_Stack is not running when the Guard_Script runs, THEN THE Guard_Script SHALL start the OraSign_Stack without rebuilding the App_Container image.
4. THE Guard_Script SHALL NOT rebuild or upgrade the OraSign_Stack under any condition.
5. THE Update_Command (`scripts/update-orasign.sh`) SHALL be the only path that pulls the OraSign_Repository, rebuilds the App_Container image, and recreates the OraSign containers.
6. WHEN either stack is started, stopped, or rebuilt, THE OraSign_Stack and the OraInvoice_App SHALL each continue to run independently so that acting on one does not require restarting the other.

### Requirement 9: Deployment to Local DEV

**User Story:** As an operator, I want a documented, repeatable way to deploy the OraSign_Stack to local DEV, so that it runs as a separate stack in that environment.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL be deployable to the local DEV Deployment_Environment using its development compose project (`orasign-development`).
2. THE OraSign_Stack SHALL use a published host port and a Data_Volume that do not collide with OraInvoice services in the local DEV Deployment_Environment.
3. WHEN the App_Container starts in local DEV, THE OraSign_Service SHALL apply outstanding Prisma_Migrations before serving requests.

### Requirement 10: Retiring the Legacy Documenso Stack

**User Story:** As an operator, I want the legacy local documenso stack replaced by the standalone OraSign_Stack, so that local development uses the rebranded service with its own database.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL replace the Legacy_Documenso_Stack as the e-signature service in local DEV.
2. WHEN the OraSign_Stack replaces the Legacy_Documenso_Stack, THE OraSign_Stack SHALL remain reachable by the OraInvoice_App over the renamed `orasign_default` network at the Configured_API_URL `http://documenso:3030` via the `documenso` Network_Alias.
3. THE OraSign_Stack SHALL provide its own Database_Container rather than reusing the Legacy_Documenso_Stack database.
4. WHEN the Legacy_Documenso_Stack is retired, THE OraSign_Stack SHALL ensure no running OraSign workload depends on the `documenso` compose project, the `documenso-documenso-1` container, or the legacy `documenso_default` network name for its own operation.
5. WHEN the Legacy_Documenso_Stack is retired, THE OraSign_Stack SHALL adopt the renamed `orasign_default` network name in place of the legacy `documenso_default` network name.

### Requirement 11: Persistence and Backup of OraSign Data

**User Story:** As an operator, I want OraSign's own data volume persisted and backed up, so that OraSign data survives restarts and can be recovered.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL persist the OraSign_Database in its Data_Volume so that data survives App_Container and Database_Container restarts and recreation.
2. WHEN the OraSign_Stack is restarted or its containers are recreated without removing the Data_Volume, THE OraSign_Service SHALL retain all previously stored OraSign data (persistence property).
3. THE OraSign_Stack SHALL provide a documented procedure to back up the Data_Volume.
4. THE OraSign_Stack SHALL provide a documented procedure to restore the OraSign_Database from a backup into the Data_Volume.

### Requirement 12: Document Format Support (PDF-only)

**User Story:** As a developer, I want the standalone stack to support the documents OraInvoice actually sends, so that the DEV stack stays minimal and no unnecessary conversion service is required.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL accept PDF documents for signing without requiring a document-conversion (gotenberg) service, because the OraInvoice_App generates and uploads only PDF documents (via WeasyPrint).
2. THE OraSign_Stack SHALL NOT include a gotenberg document-conversion service in the local DEV stack.
3. IF a non-PDF document is sent to the OraSign_Service for signing, THEN document conversion SHALL be unsupported unless a gotenberg service is added (flagged, out of scope for this spec).

### Requirement 13: End-to-End Verification of Signing Flows in Local DEV

**User Story:** As a developer, I want signing flows verified end-to-end against the standalone OraSign_Service in local DEV, so that the integration is proven to work.

#### Acceptance Criteria

1. WHEN the OraSign_Stack is running in local DEV, THE OraSign_Service SHALL respond to a reachability check at the Health_Endpoint `/api/health`.
2. WHEN an OraInvoice organisation initiates a signing request through the API_Integration, THE OraSign_Service SHALL create the corresponding signing document in the OraSign_Database and return a result the OraInvoice_App can consume.
3. WHEN a signer completes a document on the OraSign_Service, THE OraSign_Service SHALL deliver the resulting signing event back to the OraInvoice_App over the same integration path that is already configured.
4. IF an end-to-end signing verification fails in local DEV, THEN the verification procedure SHALL report which step failed (reachability, document creation, or signing-event delivery).
