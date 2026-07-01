# Requirements Document

## Introduction

OraInvoice integrates a self-hosted e-signature engine for sending and signing documents. That engine was forked, self-managed, and rebranded to **OraSign**. OraSign has now been **extracted out of the OraInvoice repository into its own separate git repository** — `github.com/arshdeepromy/Orasign` (private), with a clean single-commit history. OraInvoice's git history was purged of the OraSign folder and force-pushed, and the `/OraSign` path no longer exists in the OraInvoice workspace. **OraInvoice and OraSign are now two completely separate products, repositories, and codebases.**

OraSign is operated as a **completely separate, standalone product** that runs **alongside** OraInvoice on the same host (local DEV on the Ubuntu host; PROD on the Raspberry Pi) but is an **independent deployable with an independent update lifecycle**. OraSign spins up and owns its **own PostgreSQL database**, runs as its **own Docker Compose project** (its own project name, containers, volumes, and exposed port), and manages its own schema through its own Prisma migrations. It is never merged into OraInvoice's compose.

OraSign's deployment **mirrors OraInvoice's model**: on the Pi, OraSign is cloned to its **own path** (recommended `/home/nerdy/orasign`); an OraSign deploy is `git pull` of the OraSign repo + a **local Docker image build** from OraSign's own `docker/Dockerfile` (the image is **built locally**, not pulled from a public registry) + `docker compose up -d`. This is the same pattern OraInvoice uses to build its `app` image locally.

Because the two products share a host but not a lifecycle, the deployment flows are kept strictly separated:

- **OraInvoice deploy must not redeploy, rebuild, or recreate OraSign.** When OraInvoice is deployed, a running OraSign stack is left untouched.
- OraInvoice's deploy flow invokes a small **guard script** that checks whether the OraSign stack is already running. If it is running, the guard does nothing to it. If it is not running, the guard **starts** it (without rebuilding). The guard never rebuilds or upgrades OraSign.
- A **separate, explicit update command** (e.g. `update-orasign`) is the **only** path that pulls the OraSign repo, rebuilds the image, and recreates the OraSign containers.

OraInvoice already integrates with the signing service over its **API**. That integration's application logic — the esignatures module, the `DocumensoClient` class, the per-organisation connection stored envelope-encrypted in the OraInvoice database (with its stored internal base_url `http://documenso:3030`), and the Global Admin GUI that configures it — is **already configured and working** and is **not changed by this spec**. To keep that already-configured connection working with **no change to OraInvoice application code or the OraInvoice database**, the network rename is done with a compatibility alias: the Docker network is renamed `documenso_default` → `orasign_default`, and the OraSign app service keeps a network **alias `documenso`** so that the stored internal base_url `http://documenso:3030` still resolves to the OraSign app container. The public signer URL stays `https://esignd.oraflows.co.nz`.

### OraInvoice Scope

OraInvoice code and database are **otherwise out of scope**. The **only permitted OraInvoice edit** is a **one-line docker-compose external-network name reference** — repointing the OraInvoice app service's external network from `documenso_default` to `orasign_default`. This is infrastructure configuration only. Specifically, this spec does **not** modify any of the following, all of which are already configured and working:

- OraInvoice application code (`app/`, `frontend-v2/`, `mobile/`, `tests/`, `scripts/`).
- The OraInvoice integration client class (`DocumensoClient`) or any of its symbols.
- The OraInvoice database columns `documenso_document_id`, `documenso_team_id`, `documenso_recipient_id`.
- The stored per-organisation connection `base_url` value (`http://documenso:3030`) — it is preserved and continues to resolve via the `documenso` network alias.
- The OraInvoice API error code `documenso_error`.
- The OraInvoice esignatures module logic.
- The OraInvoice environment variable **names** `NEXT_PRIVATE_DOCUMENSO_*` / `ESIGN_DOCUMENSO_*`.

### Fresh Database (Option B)

OraSign starts with a **fresh, empty PostgreSQL database** in both environments. There is no data carry-over or migration from the legacy documenso stack. Any documents created in the old documenso instance are **not** migrated (accepted cutover consequence).

## Glossary

- **OraSign_Service**: The self-managed, self-hosted e-signature engine (the rebranded fork), operated as a standalone product with its own repository, database, and containers.
- **OraSign_Repository**: The separate, private git repository `github.com/arshdeepromy/Orasign` that holds all OraSign source code. It is independent of the OraInvoice repository.
- **OraInvoice_Repository**: The OraInvoice git repository (`arshdeepromy/Orainvoice`). It contains no OraSign source code after the repo split.
- **OraSign_Stack**: The independent Docker Compose project that runs OraSign — comprising the OraSign **App_Container**, the OraSign **Database_Container**, the OraSign **Data_Volume**, and the network it exposes. Production project name is `orasign-production`; development project name is `orasign-development`.
- **App_Container**: The OraSign application service, serving the OraSign web app and API on its configured port (3030). Its Docker image is **built locally** from the OraSign_Repository's `docker/Dockerfile`, not pulled from a public registry.
- **Database_Container**: The PostgreSQL 15 service owned by the OraSign_Stack, holding the OraSign schema and data.
- **Data_Volume**: The Docker named volume backing the Database_Container's PostgreSQL data directory (`orasign_pgdata` in production, `orasign_pgdata_dev` in development).
- **OraSign_Database**: The PostgreSQL database instance owned and initialised by the OraSign_Stack, entirely separate from the OraInvoice_Database.
- **OraInvoice_Database**: The PostgreSQL database owned by OraInvoice (DB port 5434 on local DEV, 5432 on Pi PROD). Out of scope for modification.
- **OraInvoice_App**: The main OraInvoice application and its containers. Out of scope for modification except the single permitted Network_Reference_Change.
- **OraSign_Clone_Path**: The filesystem path into which the OraSign_Repository is cloned on a host, independent of the OraInvoice clone path (recommended `/home/nerdy/orasign` on the Pi).
- **API_Integration**: The existing, already-configured connection by which OraInvoice's esignatures module calls the OraSign_Service over HTTP/API using a per-organisation, envelope-encrypted connection record stored in the OraInvoice_Database and configured via the Global Admin GUI.
- **Configured_API_URL**: The OraSign_Service base URL that the OraInvoice API_Integration is configured to call — the stored internal host `http://documenso:3030` for server-to-server calls (resolved via the `documenso` network alias), and the public host `https://esignd.oraflows.co.nz` for signer links.
- **Network_Alias**: The Docker network alias `documenso` attached to the OraSign App_Container on the `orasign_default` network, so that the OraInvoice_App's stored base_url `http://documenso:3030` continues to resolve to the OraSign App_Container without any OraInvoice code or database change.
- **Network_Reference_Change**: The single permitted OraInvoice edit — a one-line change to the OraInvoice_App's external-network name reference in its docker-compose configuration, from `documenso_default` to `orasign_default`. Infrastructure configuration only; touches no OraInvoice application code, database, error codes, or esignatures module logic.
- **Guard_Script**: The small script invoked by the OraInvoice deploy flow that checks whether the OraSign_Stack is already running. If running, it makes no change to the OraSign_Stack; if not running, it starts the OraSign_Stack without rebuilding. It never rebuilds or upgrades OraSign.
- **Update_Command**: The separate, explicit OraSign update command (e.g. `update-orasign`) — the sole path that pulls the OraSign_Repository, rebuilds the App_Container image locally, and recreates the OraSign containers.
- **Legacy_Documenso_Stack**: The retired local development stack — compose project `documenso`, container `documenso-documenso-1`, and external network name `documenso_default` — being replaced by the OraSign_Stack on the renamed `orasign_default` network.
- **Deployment_Environment**: One of the environments the OraSign_Stack is deployed into — local DEV (Ubuntu host) and Pi PROD (Raspberry Pi at 192.168.1.90).
- **OraSign_Configuration**: The set of environment-driven values the App_Container requires at startup — including `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY` (and secondary), `NEXT_PUBLIC_WEBAPP_URL`, `NEXT_PRIVATE_DATABASE_URL`, `NEXT_PRIVATE_DIRECT_DATABASE_URL`, the upload transport, email transport (SMTP/Resend/MailChannels), and the signing certificate.
- **Signing_Certificate**: The PKCS#12 signing certificate the App_Container uses to seal signed documents, mounted read-only at `/opt/orasign/cert.p12`.
- **Prisma_Migrations**: The OraSign-owned database migrations under the OraSign_Repository's Prisma package, applied by the App_Container against the OraSign_Database on startup.

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

**User Story:** As an operator, I want OraSign to run as its own self-contained Docker Compose stack, so that it is a completely separate product from OraInvoice with its own lifecycle.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL be defined as an independent Docker Compose project that is separate from any OraInvoice compose project, using its own project name (`orasign-production` for production, `orasign-development` for development).
2. THE OraSign_Stack SHALL include a Database_Container, an App_Container, and a Data_Volume backing the Database_Container.
3. THE OraSign_Stack SHALL run alongside the OraInvoice_App as a separate stack AND SHALL NOT be merged into any OraInvoice compose project or file.
4. WHERE the App_Container depends on the Database_Container, THE OraSign_Stack SHALL start the App_Container only after the Database_Container reports a healthy status.
5. THE OraSign_Stack SHALL NOT modify, attach to, or depend on the OraInvoice_Database, OraInvoice containers, or OraInvoice volumes for its own operation.

### Requirement 3: OraSign Owns and Initialises Its Own Fresh Database

**User Story:** As an operator, I want OraSign to own and initialise its own fresh PostgreSQL database and schema, so that OraSign data is fully independent of OraInvoice and of the retired legacy stack.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL provision its own PostgreSQL 15 Database_Container with its own credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) supplied through OraSign_Configuration.
2. WHEN the App_Container starts, THE OraSign_Service SHALL apply its Prisma_Migrations against the OraSign_Database so that the OraSign schema is created or brought up to date.
3. THE OraSign_Database SHALL be independent from the OraInvoice_Database such that the two share no tables and no schema (data-isolation property).
4. THE OraSign_Service SHALL read and write OraSign application data only from the OraSign_Database AND SHALL NOT read from or write to the OraInvoice_Database.
5. WHEN OraSign application data is persisted, THE OraSign_Stack SHALL store that data only in its own Data_Volume.
6. THE OraSign_Stack SHALL start with a fresh, empty OraSign_Database in both the local DEV and Pi PROD Deployment_Environments, with no carry-over or migration of legacy signing data from the Legacy_Documenso_Stack (fresh-database decision, Option B).
7. WHERE signing documents were previously created in the Legacy_Documenso_Stack, THE OraSign_Stack SHALL leave the corresponding OraInvoice references (`documenso_document_id`, `documenso_recipient_id`, `documenso_team_id`) unresolved against the fresh OraSign_Database, so that in-flight and historical signings on the legacy service do not resolve against the OraSign_Database (accepted cutover consequence).
8. WHERE a pre-cutover backup of the Legacy_Documenso_Stack database is taken, THE OraSign_Stack SHALL treat that backup as an optional safety archive only AND SHALL NOT restore it into the OraSign_Database.

### Requirement 4: OraSign Configuration and Secrets

**User Story:** As an operator, I want every required OraSign configuration value and secret defined for each environment, so that the App_Container starts cleanly and operates securely.

#### Acceptance Criteria

1. THE OraSign_Configuration SHALL define `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY`, and `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY` for the App_Container.
2. THE OraSign_Configuration SHALL define `NEXT_PRIVATE_DATABASE_URL` and `NEXT_PRIVATE_DIRECT_DATABASE_URL` pointing at the OraSign_Database Database_Container.
3. THE OraSign_Configuration SHALL define `NEXT_PUBLIC_WEBAPP_URL` set to the public URL at which the OraSign_Service is reached.
4. THE OraSign_Configuration SHALL define an email transport configuration using one of the supported providers (SMTP, Resend, or MailChannels).
5. THE OraSign_Stack SHALL mount the Signing_Certificate read-only into the App_Container at the path referenced by `NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH` (default `/opt/orasign/cert.p12`).
6. IF a required OraSign_Configuration value is unset when the App_Container starts, THEN THE OraSign_Stack SHALL fail startup with an error that names the missing value.
7. THE OraSign_Stack SHALL store secret OraSign_Configuration values in environment files that are excluded from version control.

### Requirement 5: Network Rename, Alias, and Port Allocation

**User Story:** As an operator, I want OraSign to expose a distinct port and to be reachable on the renamed Docker network under a compatibility alias, so that OraInvoice reaches it without any OraInvoice application or database change.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL expose the App_Container on a listen port of 3030 so that the stored internal base_url `http://documenso:3030` resolves to the App_Container.
2. THE OraSign_Stack SHALL publish the App_Container on a host port that does not collide with any port already used by the OraInvoice_App in the same Deployment_Environment.
3. THE OraSign_Stack SHALL attach the App_Container to the external Docker network `orasign_default` with the Network_Alias `documenso`.
4. WHEN the OraInvoice_App resolves the Configured_API_URL `http://documenso:3030`, THE OraSign_Stack SHALL ensure that URL routes to the standalone OraSign_Service App_Container over the `orasign_default` network via the `documenso` Network_Alias (URL-resolution property).
5. THE OraSign_Stack SHALL provision its Data_Volume with a name that does not collide with any OraInvoice volume in the same Deployment_Environment.
6. WHERE the Deployment_Environment is Pi PROD, THE OraSign_Stack SHALL make the App_Container reachable externally at its public URL `https://esignd.oraflows.co.nz`.
7. THE OraSign_Stack SHALL preserve the public signer URL host `https://esignd.oraflows.co.nz` that the API_Integration is configured to use for building signer links.

### Requirement 6: OraInvoice Integration Limited to One-Line Network Reference

**User Story:** As a developer, I want the OraInvoice-to-OraSign integration to require only a single infrastructure-config line change in OraInvoice, so that signing continues to work against the standalone service with no OraInvoice application code, database, error-code, or module-logic changes.

#### Acceptance Criteria

1. THE Network_Reference_Change SHALL be limited to repointing the OraInvoice_App's external-network name reference from `documenso_default` to `orasign_default` in its docker-compose configuration.
2. THE OraSign_Stack SHALL NOT require any change to OraInvoice_App application code, the stored per-organisation connection `base_url` value, the OraInvoice_Database columns, the OraInvoice API error code, or the esignatures module logic in order to integrate with the standalone OraSign_Service.
3. THE OraSign_Service SHALL accept API calls from the OraInvoice_App at the Configured_API_URL `http://documenso:3030` using the per-organisation connection already stored in the OraInvoice_Database with its unchanged `base_url`.
4. WHEN the OraInvoice_App sends a signing request to the Configured_API_URL, THE OraSign_Service SHALL process that request against its own OraSign_Database.
5. THE OraSign_Stack SHALL NOT alter the structure or the stored `base_url` value of the per-organisation OraSign connection record in the OraInvoice_Database, nor the Global Admin GUI logic that configures it.

### Requirement 7: Local-Build Deployment Mirroring OraInvoice

**User Story:** As an operator, I want OraSign deployed by pulling its repo and building its image locally, so that its deployment mirrors OraInvoice's local-build model and depends on no public image registry.

#### Acceptance Criteria

1. THE App_Container image SHALL be built locally from the OraSign_Repository's `docker/Dockerfile` AND SHALL NOT be pulled from a public image registry.
2. WHEN OraSign is deployed to a Deployment_Environment, THE deployment SHALL perform a `git pull` of the OraSign_Repository at the OraSign_Clone_Path, then build the App_Container image locally, then run `docker compose up -d` for the OraSign_Stack.
3. THE OraSign_Clone_Path SHALL be a path owned by OraSign that is separate from the OraInvoice_App clone location (recommended `/home/nerdy/orasign` on the Pi).
4. THE OraSign local-build deployment SHALL mirror the OraInvoice model in which the OraInvoice `app` image is built locally rather than pulled.

### Requirement 8: Deployment Lifecycle Separation and Guard Script

**User Story:** As an operator, I want OraInvoice and OraSign deploys kept strictly separate, so that deploying OraInvoice never disturbs a running OraSign stack and OraSign is only rebuilt on an explicit command.

#### Acceptance Criteria

1. WHEN the OraInvoice_App is deployed, THE OraInvoice deploy flow SHALL NOT redeploy, rebuild, or recreate the OraSign_Stack.
2. WHEN the OraInvoice deploy flow runs, THE OraInvoice deploy flow SHALL invoke the Guard_Script.
3. WHILE the OraSign_Stack is already running, THE Guard_Script SHALL make no change to the OraSign_Stack (guard-idempotency property).
4. IF the OraSign_Stack is not running when the Guard_Script runs, THEN THE Guard_Script SHALL start the OraSign_Stack without rebuilding the App_Container image.
5. THE Guard_Script SHALL NOT rebuild or upgrade the OraSign_Stack under any condition.
6. THE Update_Command SHALL be the only path that pulls the OraSign_Repository, rebuilds the App_Container image, and recreates the OraSign containers.
7. WHEN either stack is started, stopped, or rebuilt, THE OraSign_Stack and the OraInvoice_App SHALL each continue to run independently so that acting on one does not require restarting the other.

### Requirement 9: Deployment to Local DEV and Pi PROD

**User Story:** As an operator, I want a documented, repeatable way to deploy the OraSign_Stack to local DEV and Pi PROD, so that it runs as a separate stack in each environment.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL be deployable to the local DEV Deployment_Environment using its development compose project (`orasign-development`).
2. THE OraSign_Stack SHALL be deployable to the Pi PROD Deployment_Environment using its production compose project (`orasign-production`).
3. THE OraSign_Stack SHALL use a distinct published host port and a distinct Data_Volume per Deployment_Environment so that local DEV and Pi PROD do not collide with each other or with OraInvoice services.
4. WHEN the App_Container starts in any Deployment_Environment, THE OraSign_Service SHALL apply outstanding Prisma_Migrations before serving requests.

### Requirement 10: Retiring the Legacy Documenso Stack

**User Story:** As an operator, I want the legacy local documenso stack replaced by the standalone OraSign_Stack, so that development and production use the rebranded service with its own database.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL replace the Legacy_Documenso_Stack as the e-signature service.
2. WHEN the OraSign_Stack replaces the Legacy_Documenso_Stack, THE OraSign_Stack SHALL remain reachable by the OraInvoice_App over the renamed `orasign_default` network at the Configured_API_URL `http://documenso:3030` via the `documenso` Network_Alias.
3. THE OraSign_Stack SHALL provide its own Database_Container rather than reusing the Legacy_Documenso_Stack database.
4. WHEN the Legacy_Documenso_Stack is retired, THE OraSign_Stack SHALL ensure no running OraSign workload depends on the `documenso` compose project, the `documenso-documenso-1` container, or the legacy `documenso_default` network name for its own operation.
5. WHEN the Legacy_Documenso_Stack is retired, THE OraSign_Stack SHALL adopt the renamed `orasign_default` network name in place of the legacy `documenso_default` network name.

### Requirement 11: Persistence and Backup of OraSign Data

**User Story:** As an operator, I want OraSign's own data volume persisted and backed up, so that OraSign data survives restarts and can be recovered.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL persist the OraSign_Database in its Data_Volume so that data survives App_Container and Database_Container restarts and recreation.
2. WHEN the OraSign_Stack is restarted or its containers are recreated without removing the Data_Volume, THE OraSign_Service SHALL retain all previously stored OraSign data (persistence property).
3. THE OraSign_Stack SHALL provide a documented procedure to back up the Data_Volume in the Pi PROD Deployment_Environment.
4. THE OraSign_Stack SHALL provide a documented procedure to restore the OraSign_Database from a backup into the Data_Volume.

### Requirement 12: End-to-End Verification of Signing Flows

**User Story:** As a developer, I want signing flows verified end-to-end against the standalone OraSign_Service, so that the integration is proven to work before and after deployment.

#### Acceptance Criteria

1. WHEN the OraSign_Stack is running in a Deployment_Environment, THE OraSign_Service SHALL respond to a health or reachability check at the Configured_API_URL.
2. WHEN an OraInvoice organisation initiates a signing request through the API_Integration, THE OraSign_Service SHALL create the corresponding signing document in the OraSign_Database and return a result the OraInvoice_App can consume.
3. WHEN a signer completes a document on the OraSign_Service, THE OraSign_Service SHALL deliver the resulting signing event back to the OraInvoice_App over the same integration path that is already configured.
4. THE OraSign_Stack SHALL be verified end-to-end in the local DEV Deployment_Environment before being deployed to Pi PROD.
5. IF an end-to-end signing verification fails in a Deployment_Environment, THEN the verification procedure SHALL report which step failed (reachability, document creation, or signing-event delivery).
