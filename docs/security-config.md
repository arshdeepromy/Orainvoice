# Security Configuration — WorkshopPro NZ

This document describes the data encryption, transport security, and security header configuration for the WorkshopPro NZ platform.

## 1. Data Encryption at Rest (Requirement 52.1)

### PostgreSQL AES-256 Encryption

All data at rest in PostgreSQL is protected through two complementary mechanisms:

#### Full-Disk Encryption (FDE)

The PostgreSQL data directory (`/var/lib/postgresql/data`) must reside on an encrypted volume:

- **AWS**: Use EBS volumes with AES-256 encryption enabled (default KMS or customer-managed CMK)
- **Azure**: Use Azure Disk Encryption with AES-256
- **On-premise**: Use LUKS/dm-crypt with AES-256-XTS

This encrypts all tablespaces, WAL files, temporary files, and indexes transparently.

#### Application-Level Envelope Encryption (pgcrypto + app layer)

Sensitive fields (integration credentials, MFA secrets, webhook signing keys) use envelope encryption via `app/core/encryption.py`:

- Each secret gets a random 256-bit Data Encryption Key (DEK)
- The DEK encrypts the plaintext using AES-256-GCM
- A master key encrypts the DEK (also AES-256-GCM)
- Stored in `BYTEA` columns as `[DEK length][encrypted DEK][encrypted payload]`

To rotate the master key, only the DEKs need re-encryption — not every secret.

#### PostgreSQL pgcrypto Extension

For column-level encryption needs, enable pgcrypto:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

### Backup Encryption

All database backups must be encrypted at rest using AES-256 and stored in a geographically separate location from the primary data (Requirement 53.3).

## 2. TLS 1.3 Enforcement for Data in Transit (Requirement 52.2)

### Application Layer

All client connections must use TLS 1.3 minimum. This is enforced at the load balancer / reverse proxy level:

#### Nginx Configuration

```nginx
ssl_protocols TLSv1.3;
ssl_prefer_server_ciphers off;
ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256;
```

#### HSTS Header

The application sets `Strict-Transport-Security: max-age=31536000; includeSubDomains` on every response, instructing browsers to only connect via HTTPS.

### Database Connections

PostgreSQL connections from the application enforce SSL:

- **Production/Staging**: `sslmode=require` with TLS 1.3 minimum
- **Development**: `sslmode=prefer` (graceful fallback for local dev without certs)

Configure in `postgresql.conf`:

```ini
ssl = on
ssl_min_protocol_version = 'TLSv1.3'
ssl_cert_file = '/path/to/server.crt'
ssl_key_file = '/path/to/server.key'
```

### Redis Connections

For production, Redis should be configured with TLS:

```ini
tls-port 6380
tls-cert-file /path/to/redis.crt
tls-key-file /path/to/redis.key
tls-protocols "TLSv1.3"
```

## 3. Security Headers (Requirement 52.3)

All API responses include the following security headers, enforced by `SecurityHeadersMiddleware`:

| Header | Value | Purpose |
|--------|-------|---------|
| Content-Security-Policy | `default-src 'self'; script-src 'self'; ...` | Prevents XSS, clickjacking, data injection |
| Strict-Transport-Security | `max-age=31536000; includeSubDomains` | Forces HTTPS for 1 year |
| X-Frame-Options | `DENY` | Prevents iframe embedding (clickjacking) |
| X-Content-Type-Options | `nosniff` | Prevents MIME-type sniffing |
| Referrer-Policy | `strict-origin-when-cross-origin` | Controls referrer information leakage |
| X-XSS-Protection | `1; mode=block` | Legacy XSS filter (defence in depth) |
| Permissions-Policy | `camera=(), microphone=(), geolocation=()` | Restricts browser feature access |

### CSRF Protection (Requirement 52.4)

State-changing requests (POST/PUT/PATCH/DELETE) with cookie-based auth require an `X-CSRF-Token` header. Bearer token requests are exempt since tokens cannot be sent automatically by browser forms.

## 4. Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `development` | Controls SSL enforcement (`production`/`staging` = mandatory) |
| `DATABASE_SSL_MODE` | `prefer` | PostgreSQL SSL mode (`require`/`prefer`/`disable`) |
| `ENCRYPTION_MASTER_KEY` | — | Master key for envelope encryption (must be changed in production) |
