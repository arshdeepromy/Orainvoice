# Requirements Document

## Introduction

OraInvoice integrates a self-hosted e-signature engine for sending and signing documents. That engine has been forked, self-managed, and rebranded to **OraSign** (the rebranded monorepo lives in `/OraSign`). OraSign is to be operated as a **completely separate, standalone product**: it spins up and owns its **own PostgreSQL database**, runs as its **own Docker Compose stack** (its own project name, containers, volumes, and exposed port), and manages its own schema through its own Prisma migrations. It runs **alongside** OraInvoice as an independent stack, not merged into OraInvoice's compose.

OraInvoice already integrates with the signing service over its **API**. That integration's application logic — the esignatures module, the `DocumensoClient` class, the per-organisation connection stored envelope-encrypted in the OraInvoice database, and the Global Admin GUI that configures it — is **already configured and working** and is **not changed by this spec**. The rename does, however, complete at the **wiring layer**: the external Docker network is renamed `documenso_default` → `orasign_default` and the internal host is renamed `http://documenso:3030` → `http://orasign:3030`, with **no `documenso` compatibility alias**. Because the legacy network and host names are removed with no alias, a **minimal, well-bounded OraInvoice WIRING change is now required as a direct consequence of the rename** (network reference repoint, per-organisation connection `base_url` repoint, and an optional cosmetic config comment) — but **no OraInvoice application code, database columns, error codes, or esignatures module logic change**.

This spec also retires the legacy local "documenso" development stack (separate compose project `documenso`, container `documenso-documenso-1`, external network `documenso_default`) and replaces it with the rebranded standalone OraSign stack that has its **own database**. The OraInvoice app container currently attaches to the `documenso_default` network to reach the service; that membership is repointed to the renamed `orasign_default` network so the standalone OraSign stack remains reachable to OraInvoice over the network/API (or via the configured public API URL).

The standalone OraSign stack must be deployable across the existing OraInvoice environments — local DEV on the Ubuntu host and PROD on the Raspberry Pi — using its own distinct port and data volume so it does not collide with OraInvoice's PostgreSQL or app services.

### OraInvoice Wiring Change Now In Scope

As a direct consequence of renaming the network and internal host with no compatibility alias, the following minimal, configuration-only OraInvoice wiring items are **in scope**:

- `docker-compose.dev.yml`: the OraInvoice app service's `networks:` entry and the bottom `networks:` declaration repointed from `documenso_default` to `orasign_default`, and related comments referencing `http://documenso:3030` updated to `http://orasign:3030`.
- Any Pi PROD compose that joins the signing network repointed from `documenso_default` to `orasign_default` the same way, per environment.
- The per-organisation connection `base_url` repointed from `http://documenso:3030` to `http://orasign:3030` through the Global Admin GUI (a runtime operator step, not a code change).
- Optionally (cosmetic, comment-only) the comment in `app/config.py` referencing `http://documenso:3030` updated to the new host.

### Explicitly Out of Scope

Beyond the minimal wiring change above, this spec makes **no changes** to the OraInvoice main application. Specifically, it does **not** modify any of the following, all of which are already configured and working:

- OraInvoice application code (`app/`, `frontend-v2/`, `mobile/`, `tests/`, `scripts/`).
- The OraInvoice integration client class (`DocumensoClient`) or any of its symbols.
- The OraInvoice database columns `documenso_document_id`, `documenso_team_id`, `documenso_recipient_id`.
- The OraInvoice API error code `documenso_error`.
- The OraInvoice esignatures module logic.
- The OraInvoice environment variable **names** `NEXT_PRIVATE_DOCUMENSO_*` / `ESIGN_DOCUMENSO_*`.

The previously planned five-phase rename of OraInvoice internals is discarded.

## Glossary

- **OraSign_Service**: The self-managed, self-hosted e-signature engine (the rebranded fork in `/OraSign`), operated as a standalone product with its own database and containers.
- **OraSign_Stack**: The independent Docker Compose project that runs OraSign — comprising the OraSign **App_Container**, the OraSign **Database_Container**, the OraSign **Data_Volume**, and the network it exposes. Production project name is `orasign-production`; development project name is `orasign-development`.
- **App_Container**: The OraSign application service (image `orasign/orasign:latest` in production), serving the OraSign web app and API on its configured port (default 3000).
- **Database_Container**: The PostgreSQL 15 service owned by the OraSign_Stack, holding the OraSign schema and data.
- **Data_Volume**: The Docker named volume backing the Database_Container's PostgreSQL data directory (`database` in production, `orasign_database` in development).
- **OraSign_Database**: The PostgreSQL database instance owned and initialised by the OraSign_Stack, entirely separate from the OraInvoice_Database.
- **OraInvoice_Database**: The PostgreSQL database owned by OraInvoice (DB port 5434 on local DEV, 5432 on Pi PROD). Out of scope for modification.
- **OraInvoice_App**: The main OraInvoice application and its containers. Out of scope for modification.
- **API_Integration**: The existing, already-configured connection by which OraInvoice's esignatures module calls the OraSign_Service over HTTP/API using a per-organisation, envelope-encrypted connection record stored in the OraInvoice_Database and configured via the Global Admin GUI.
- **Configured_API_URL**: The OraSign_Service base URL that the OraInvoice API_Integration is configured to call (internal host on the Docker network for server-to-server calls, `http://orasign:3030` after the rename; public host for signer links, `https://esignd.oraflows.co.nz`).
- **Wiring_Change**: The minimal, configuration-only OraInvoice change required as a direct consequence of the rename — repointing the OraInvoice app's external network reference from `documenso_default` to `orasign_default` in the relevant compose files, repointing the per-organisation connection `base_url` from `http://documenso:3030` to `http://orasign:3030` via the Global Admin GUI, and an optional cosmetic config comment. It touches no OraInvoice application code, database columns, error codes, or esignatures module logic.
- **Legacy_Documenso_Stack**: The retired local development stack — compose project `documenso`, container `documenso-documenso-1`, and external network name `documenso_default` — being replaced by the OraSign_Stack on the renamed `orasign_default` network.
- **Deployment_Environment**: One of the OraInvoice environments the OraSign_Stack is deployed into — local DEV (Ubuntu host) and Pi PROD (Raspberry Pi at 192.168.1.90).
- **OraSign_Configuration**: The set of environment-driven values the App_Container requires at startup — including `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY` (and secondary), `NEXT_PUBLIC_WEBAPP_URL`, `NEXT_PRIVATE_DATABASE_URL`, `NEXT_PRIVATE_DIRECT_DATABASE_URL`, the upload transport, email transport (SMTP/Resend/MailChannels), and the signing certificate.
- **Signing_Certificate**: The PKCS#12 signing certificate the App_Container uses to seal signed documents, mounted at `/opt/orasign/cert.p12`.
- **Prisma_Migrations**: The OraSign-owned database migrations under `OraSign/packages/prisma`, applied by the App_Container against the OraSign_Database on startup.

## Requirements

### Requirement 1: Standalone OraSign Stack Definition

**User Story:** As an operator, I want OraSign to run as its own self-contained Docker Compose stack, so that it is a completely separate product from OraInvoice with its own lifecycle.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL be defined as an independent Docker Compose project that is separate from any OraInvoice compose project, using its own project name (`orasign-production` for production, `orasign-development` for development).
2. THE OraSign_Stack SHALL include a Database_Container, an App_Container, and a Data_Volume backing the Database_Container.
3. THE OraSign_Stack SHALL run alongside the OraInvoice_App as a separate stack AND SHALL NOT be merged into any OraInvoice compose project or file.
4. WHERE the App_Container depends on the Database_Container, THE OraSign_Stack SHALL start the App_Container only after the Database_Container reports a healthy status.
5. THE OraSign_Stack SHALL NOT modify, attach to, or depend on the OraInvoice_Database, OraInvoice containers, or OraInvoice volumes for its own operation.

### Requirement 2: OraSign Owns and Initialises Its Own Database

**User Story:** As an operator, I want OraSign to own and initialise its own PostgreSQL database and schema, so that OraSign data is fully independent of OraInvoice.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL provision its own PostgreSQL 15 Database_Container with its own credentials (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`) supplied through OraSign_Configuration.
2. WHEN the App_Container starts, THE OraSign_Service SHALL apply its Prisma_Migrations against the OraSign_Database so that the OraSign schema is created or brought up to date.
3. THE OraSign_Database SHALL be independent from the OraInvoice_Database such that the two share no tables and no schema (data-isolation property).
4. THE OraSign_Service SHALL read and write OraSign application data only from the OraSign_Database AND SHALL NOT read from or write to the OraInvoice_Database.
5. WHEN OraSign application data is persisted, THE OraSign_Stack SHALL store that data only in its own Data_Volume.
6. THE OraSign_Stack SHALL start with a fresh, empty OraSign_Database in both the local DEV and Pi PROD Deployment_Environments, with no carry-over or migration of legacy signing data from the Legacy_Documenso_Stack.
7. WHERE signing documents were previously created in the Legacy_Documenso_Stack, THE OraSign_Stack SHALL leave the corresponding OraInvoice references (`documenso_document_id`, `documenso_recipient_id`, `documenso_team_id`) unresolved against the fresh OraSign_Database, so that in-flight and historical signings on the legacy service do not resolve against the OraSign_Database (accepted cutover consequence).
8. WHERE a pre-cutover backup of the Legacy_Documenso_Stack database is taken, THE OraSign_Stack SHALL treat that backup as an optional safety archive only AND SHALL NOT restore it into the OraSign_Database.

### Requirement 3: OraSign Configuration and Secrets

**User Story:** As an operator, I want every required OraSign configuration value and secret defined for each environment, so that the App_Container starts cleanly and operates securely.

#### Acceptance Criteria

1. THE OraSign_Configuration SHALL define `NEXTAUTH_SECRET`, `NEXT_PRIVATE_ENCRYPTION_KEY`, and `NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY` for the App_Container.
2. THE OraSign_Configuration SHALL define `NEXT_PRIVATE_DATABASE_URL` and `NEXT_PRIVATE_DIRECT_DATABASE_URL` pointing at the OraSign_Database Database_Container.
3. THE OraSign_Configuration SHALL define `NEXT_PUBLIC_WEBAPP_URL` set to the public URL at which the OraSign_Service is reached.
4. THE OraSign_Configuration SHALL define an email transport configuration using one of the supported providers (SMTP, Resend, or MailChannels).
5. THE OraSign_Stack SHALL mount the Signing_Certificate read-only into the App_Container at the path referenced by `NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH` (default `/opt/orasign/cert.p12`).
6. IF a required OraSign_Configuration value is unset when the App_Container starts, THEN THE OraSign_Stack SHALL fail startup with an error that names the missing value.
7. THE OraSign_Stack SHALL store secret OraSign_Configuration values in environment files that are excluded from version control.

### Requirement 4: Network and Port Allocation

**User Story:** As an operator, I want OraSign to expose a distinct port and be reachable on the renamed Docker network, so that OraInvoice and (in production) external clients can reach it without colliding with OraInvoice's services.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL expose the App_Container on a port that does not collide with any port already used by the OraInvoice_App in the same Deployment_Environment.
2. THE OraSign_Stack SHALL make the App_Container reachable by the OraInvoice_App over the Docker network at the internal host `http://orasign:3030` that the API_Integration is configured to call after the rename.
3. THE OraSign_Stack SHALL provision its Data_Volume with a name that does not collide with any OraInvoice volume in the same Deployment_Environment.
4. WHERE the Deployment_Environment is Pi PROD, THE OraSign_Stack SHALL make the App_Container reachable externally at its public URL `https://esignd.oraflows.co.nz`.
5. WHEN the OraInvoice_App resolves the Configured_API_URL `http://orasign:3030`, THE OraSign_Stack SHALL ensure that URL routes to the standalone OraSign_Service App_Container over the `orasign_default` network (URL-resolution property).
6. THE Wiring_Change SHALL repoint the OraInvoice_App's external network reference from `documenso_default` to `orasign_default` without modifying OraInvoice_App code, the OraInvoice_Database columns, the OraInvoice API error code, or the esignatures module logic.

### Requirement 5: OraInvoice Integration Limited to Minimal Wiring

**User Story:** As a developer, I want the OraInvoice-to-OraSign integration changed only at the wiring layer, so that signing continues to work against the standalone service with no OraInvoice application code, database, error-code, or module-logic changes.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL NOT require any change to OraInvoice_App application code, the OraInvoice_Database columns, the OraInvoice API error code, or the esignatures module logic in order to integrate with the standalone OraSign_Service.
2. THE Wiring_Change SHALL be limited to repointing the OraInvoice_App's external network reference to `orasign_default` and repointing the per-organisation connection `base_url` from `http://documenso:3030` to `http://orasign:3030` via the Global Admin GUI.
3. THE OraSign_Service SHALL accept API calls from the OraInvoice_App at the Configured_API_URL `http://orasign:3030` using the per-organisation connection stored in the OraInvoice_Database with its repointed `base_url`.
4. WHEN the OraInvoice_App sends a signing request to the Configured_API_URL, THE OraSign_Service SHALL process that request against its own OraSign_Database.
5. THE OraSign_Stack SHALL preserve the public signer URL host `https://esignd.oraflows.co.nz` that the API_Integration is configured to use for building signer links.
6. THE OraSign_Stack SHALL NOT alter the structure of the per-organisation OraSign connection record stored encrypted in the OraInvoice_Database beyond its `base_url` value, nor the Global Admin GUI logic that configures it.

### Requirement 6: Deployment to Local DEV and Pi PROD

**User Story:** As an operator, I want a documented, repeatable way to deploy the OraSign_Stack to local DEV and Pi PROD, so that it runs as a separate stack in each environment.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL be deployable to the local DEV Deployment_Environment using its development compose project (`orasign-development`).
2. THE OraSign_Stack SHALL be deployable to the Pi PROD Deployment_Environment using its production compose project (`orasign-production`).
3. WHEN the OraSign_Stack is deployed to a Deployment_Environment, THE OraSign_Stack SHALL run independently of the OraInvoice_App lifecycle in that environment so that starting, stopping, or rebuilding either stack does not require restarting the other.
4. THE OraSign_Stack SHALL use a distinct exposed port and a distinct Data_Volume per Deployment_Environment so that local DEV and Pi PROD do not collide with each other or with OraInvoice services.
5. WHEN the App_Container starts in any Deployment_Environment, THE OraSign_Service SHALL apply outstanding Prisma_Migrations before serving requests.

### Requirement 7: Retiring the Legacy Documenso Stack

**User Story:** As an operator, I want the legacy local documenso stack replaced by the standalone OraSign_Stack, so that local development uses the rebranded service with its own database.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL replace the Legacy_Documenso_Stack as the local e-signature service for development.
2. WHEN the OraSign_Stack replaces the Legacy_Documenso_Stack, THE OraSign_Stack SHALL remain reachable by the OraInvoice_App over the renamed `orasign_default` network or via the Configured_API_URL `http://orasign:3030`.
3. THE OraSign_Stack SHALL provide its own Database_Container rather than reusing the Legacy_Documenso_Stack database.
4. WHERE the OraInvoice_App attaches to an external network to reach the signing service, THE OraSign_Stack SHALL be reachable on the renamed `orasign_default` network that the OraInvoice_App attaches to via the Wiring_Change.
5. WHEN the Legacy_Documenso_Stack is retired, THE OraSign_Stack SHALL ensure no running OraSign workload depends on the `documenso` compose project, the `documenso-documenso-1` container, or the `documenso_default` network for its own operation.
6. WHEN the Legacy_Documenso_Stack is retired, THE OraSign_Stack SHALL retire the `documenso_default` network name in favour of the renamed `orasign_default` network, with no `documenso` compatibility alias retained.

### Requirement 8: Persistence and Backup of OraSign Data

**User Story:** As an operator, I want OraSign's own data volume persisted and backed up, so that OraSign data survives restarts and can be recovered.

#### Acceptance Criteria

1. THE OraSign_Stack SHALL persist the OraSign_Database in its Data_Volume so that data survives App_Container and Database_Container restarts and recreation.
2. WHEN the OraSign_Stack is restarted or its containers are recreated without removing the Data_Volume, THE OraSign_Service SHALL retain all previously stored OraSign data (persistence property).
3. THE OraSign_Stack SHALL provide a documented procedure to back up the Data_Volume in the Pi PROD Deployment_Environment.
4. THE OraSign_Stack SHALL provide a documented procedure to restore the OraSign_Database from a backup into the Data_Volume.

### Requirement 9: End-to-End Verification of Signing Flows

**User Story:** As a developer, I want signing flows verified end-to-end against the standalone OraSign_Service, so that the integration is proven to work before and after deployment.

#### Acceptance Criteria

1. WHEN the OraSign_Stack is running in a Deployment_Environment, THE OraSign_Service SHALL respond to a health or reachability check at the Configured_API_URL.
2. WHEN an OraInvoice organisation initiates a signing request through the API_Integration, THE OraSign_Service SHALL create the corresponding signing document in the OraSign_Database and return a result the OraInvoice_App can consume.
3. WHEN a signer completes a document on the OraSign_Service, THE OraSign_Service SHALL deliver the resulting signing event back to the OraInvoice_App over the same integration path that is already configured.
4. THE OraSign_Stack SHALL be verified end-to-end in the local DEV Deployment_Environment before being deployed to Pi PROD.
5. IF an end-to-end signing verification fails in a Deployment_Environment, THEN the verification procedure SHALL report which step failed (reachability, document creation, or signing-event delivery).
