# Data Residency and Backup Policy — WorkshopPro NZ

This document defines the data residency, backup, and disaster recovery requirements for the WorkshopPro NZ platform. All configuration must comply with the New Zealand Privacy Act 2020.

## 1. Data Residency Requirements (Requirement 53.1)

### NZ/AU Data Centre Mandate

All customer data must reside within New Zealand or Australian data centres. This applies to:

| Component | Residency Requirement |
|-----------|----------------------|
| PostgreSQL (primary + replicas) | NZ or AU region only |
| Redis (cache, sessions, broker) | NZ or AU region only |
| Application servers (FastAPI) | NZ or AU region only |
| Celery workers | NZ or AU region only |
| Backup storage | NZ or AU region only (geographically separate from primary) |
| Load balancers / CDN edge | NZ or AU region only |

### Approved Cloud Regions

| Provider | Approved Regions |
|----------|-----------------|
| AWS | `ap-southeast-2` (Sydney) |
| Azure | `australiaeast` (Sydney), `australiasoutheast` (Melbourne) |
| Google Cloud | `australia-southeast1` (Sydney), `australia-southeast2` (Melbourne) |
| On-premise | Physical data centres located in NZ or AU |

### Prohibited Data Flows

- Customer PII must never transit through or be stored in data centres outside NZ/AU.
- DNS resolution and TLS termination must occur within NZ/AU infrastructure.
- Third-party integrations (Stripe, Carjam, Brevo, Twilio) transmit only the minimum data required and are governed by their own data processing agreements.

### Privacy Act 2020 Compliance

Under the NZ Privacy Act 2020, Information Privacy Principle 12 restricts disclosure of personal information outside New Zealand. By hosting all infrastructure in NZ/AU:

- All personal information remains within jurisdictions with comparable privacy protections.
- Data access requests (IPP 6) and correction requests (IPP 7) can be fulfilled from local infrastructure.
- The platform operator retains full control over data location and access.

## 2. Backup Strategy (Requirements 53.2, 53.3)

### Retention Policy

| Parameter | Value |
|-----------|-------|
| Retention period | 30 days |
| Recovery granularity | Point-in-time to the minute |
| Backup frequency | Continuous WAL archiving + daily base backups |
| Backup encryption | AES-256 at rest |
| Backup location | Geographically separate NZ/AU data centre |

### Backup Architecture

```
Primary Database (NZ/AU Region A)
    │
    ├── Continuous WAL Archiving ──► Encrypted Backup Storage (NZ/AU Region B)
    │
    └── Daily Base Backup (02:00 NZST) ──► Encrypted Backup Storage (NZ/AU Region B)
```

### Point-in-Time Recovery (PITR)

PostgreSQL Write-Ahead Log (WAL) archiving enables recovery to any point within the 30-day retention window:

1. WAL segments are continuously shipped to the backup location.
2. Daily base backups provide restore starting points.
3. Recovery replays WAL from the nearest base backup to the target timestamp.

### Cloud-Specific Configuration

#### AWS (RDS PostgreSQL)

```
Backup retention: 30 days
Backup window: 02:00–03:00 NZST
Multi-AZ: Enabled
Storage encryption: AES-256 (AWS KMS)
Automated backups: Enabled
Point-in-time recovery: Enabled
Cross-region backup: ap-southeast-2 (primary) → separate AZ within ap-southeast-2
```

#### Self-Managed PostgreSQL

```bash
# postgresql.conf
archive_mode = on
archive_command = 'pgbackrest --stanza=workshoppro archive-push %p'

# pgBackRest configuration
[workshoppro]
pg1-path=/var/lib/postgresql/data
repo1-type=s3
repo1-s3-bucket=workshoppro-backups
repo1-s3-region=ap-southeast-2
repo1-s3-endpoint=s3.ap-southeast-2.amazonaws.com
repo1-cipher-type=aes-256-cbc
repo1-retention-full=30
```

## 3. Backup Encryption (Requirement 53.3)

### Encryption at Rest

All backups are encrypted using AES-256 before being written to storage:

- **AWS RDS**: Encryption enabled via AWS KMS (default or customer-managed CMK).
- **Self-managed**: pgBackRest encrypts with `aes-256-cbc`; encryption key stored in a separate secrets manager.
- **Backup storage volumes**: Must use encrypted storage (e.g., encrypted S3 buckets, encrypted EBS).

### Geographic Separation

Backup storage must be in a different physical location from the primary database while remaining within NZ/AU:

| Primary Location | Backup Location |
|-----------------|-----------------|
| AWS ap-southeast-2a | AWS ap-southeast-2b (different AZ) |
| Azure australiaeast | Azure australiasoutheast |
| NZ on-premise DC1 | AU on-premise DC2 (or NZ DC in different city) |

## 4. Data Retention Policy (Requirement 53.4)

### Configurable Retention

The Global_Admin can configure the data retention policy via the admin console:

| Setting | Default | Range |
|---------|---------|-------|
| Backup retention days | 30 | 7–90 |
| Error log retention | 12 months | 3–24 months |
| Audit log retention | Indefinite | Indefinite (append-only) |
| Notification log retention | 12 months | 3–24 months |

### Deletion and Anonymisation

- Customer deletion requests (Privacy Act 2020) anonymise records rather than delete them, preserving financial integrity.
- Backups containing deleted customer data expire naturally within the retention window.
- No mechanism exists to selectively purge individual records from backups; the retention window governs lifecycle.

## 5. Disaster Recovery

### Recovery Time Objectives

| Metric | Target |
|--------|--------|
| Recovery Point Objective (RPO) | < 1 minute (continuous WAL archiving) |
| Recovery Time Objective (RTO) | < 1 hour |

### Recovery Procedure

1. Identify the target recovery timestamp.
2. Restore the most recent base backup prior to the target time.
3. Replay WAL segments up to the target timestamp.
4. Verify data integrity and tenant isolation (RLS policies active).
5. Switch application traffic to the recovered instance.

## 6. Monitoring and Verification

### Automated Checks

- Daily verification that the latest backup completed successfully.
- Weekly test restore to a staging environment to validate backup integrity.
- Alert if backup age exceeds 25 hours (missed daily backup).
- Alert if WAL archiving lag exceeds 5 minutes.

### Compliance Audit

- Quarterly review of data residency configuration to confirm all resources remain in NZ/AU.
- Annual disaster recovery drill with documented results.
