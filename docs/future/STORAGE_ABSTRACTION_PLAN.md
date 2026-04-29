# Storage Abstraction & Cloud Migration Plan

**Status:** Future implementation — not needed now  
**Priority:** Low (revisit when file count exceeds ~10K or a customer requests cloud storage)  
**Last reviewed:** 2026-04-29  

---

## Current State (as of April 2026)

### How Files Are Stored

All files are stored on local disk inside Docker named volumes:

| Volume | Container mount | Host path | Contents |
|---|---|---|---|
| `app_uploads` | `/app/uploads/` | `/var/lib/docker/volumes/invoicing_app_uploads/_data` | Customer uploads, job attachments, expense receipts, branding logos |
| `compliance_files` | `/app/compliance_files/` | `/var/lib/docker/volumes/invoicing_compliance_files/_data` | Compliance/certification documents |

The base upload directory is configurable via `UPLOAD_DIR` env var (defaults to `/app/uploads`).

### Directory Structure

```
/app/uploads/
├── branding/                    # Org logos, favicons (served via /api/v1/branding/files/)
│   ├── {uuid-hex}.png
│   └── {uuid-hex}.ico
├── job-card-attachments/        # Job card photos and documents
│   └── {org_id}/
│       └── {job_card_id}/
│           └── {uuid}_{filename}
└── {org_id}/                    # General uploads (invoices, receipts, etc.)
    └── {category}/
        └── {filename}

/app/compliance_files/
└── {org_id}/
    └── {document_type}/
        └── {filename}
```

### Database Tables That Store File References

| Table | Column | Format | Example |
|---|---|---|---|
| `job_attachments` | `file_key` (String 500) | `job-card-attachments/{org_id}/{job_card_id}/{uuid}_{name}` | `job-card-attachments/abc123/def456/a1b2c3_photo.jpg` |
| `compliance_documents` | `file_key` (String 500) | `{org_id}/certifications/{filename}` | `abc123/certifications/electrical_cert.pdf` |
| `expenses` | `receipt_file_key` (String 500) | `{org_id}/receipts/{filename}` | `abc123/receipts/receipt_001.jpg` |
| `organisations` | `logo_url` (Text) | Full URL or relative path | `/api/v1/branding/files/{uuid}` |
| `branding_configs` | `logo_url`, `dark_logo_url` (String 500) | API URL pattern | `/api/v1/branding/files/{uuid}` |
| `branding_configs` | `logo_data`, `dark_logo_data` (LargeBinary) | Binary blob in DB | Raw bytes (migrated from disk) |

**Key observation:** The `file_key` columns already use a storage-agnostic format — they don't include the `/app/uploads/` prefix. The app prepends the base path at read time. This is good — it means the database references are already partially abstracted.

**Exception:** Branding files use two approaches:
1. **Legacy:** Files on disk at `/app/uploads/branding/{uuid}`, served via API URL `/api/v1/branding/files/{uuid}`
2. **Current:** Binary data stored directly in the `branding_configs` table (`logo_data`, `dark_logo_data` columns). A migration service moves disk files into the DB.

### How Files Are Served

| Module | Serve method | Code location |
|---|---|---|
| Job attachments | `FileResponse` from disk path | `app/modules/job_cards/attachment_service.py` |
| Compliance docs | `FileResponse` from disk path | `app/modules/compliance_docs/router.py` |
| Expense receipts | `FileResponse` from disk path | `app/modules/expenses/router.py` |
| Branding logos | DB binary → `Response(content=bytes)` | `app/modules/branding/router.py` |
| General uploads | `FileResponse` from disk path | `app/modules/uploads/router.py` |

### How Files Are Uploaded

All uploads go through module-specific endpoints that:
1. Validate file size and type
2. Generate a `file_key` (org-scoped path)
3. Write to `UPLOAD_BASE / file_key` on disk
4. Store the `file_key` in the database

### HA Volume Sync (Current)

Files are replicated between primary and standby nodes using rsync over SSH:
- Runs as a background asyncio task inside the app container
- Configurable interval (default 5 minutes)
- Uses `--archive --compress --delete` flags (full mirror)
- SSH key-based auth via `/ha_keys/id_ed25519`
- Scans entire directory tree each cycle (O(n) where n = total files)

**Bottleneck threshold:** ~50-100K files, where the rsync scan itself takes minutes even with no changes.

---

## Migration Plan

### Phase 1: Storage Abstraction Layer (when needed)

**Trigger:** First customer requests S3/Google Drive, or file count approaches 50K.

Create a `FileStorage` interface that all file operations go through:

```python
# app/core/file_storage.py

from abc import ABC, abstractmethod

class FileStorage(ABC):
    """Abstract interface for file storage backends."""

    @abstractmethod
    async def save(self, key: str, data: bytes, content_type: str) -> str:
        """Save file data, return the storage key."""
        ...

    @abstractmethod
    async def read(self, key: str) -> bytes:
        """Read file data by key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete a file by key."""
        ...

    @abstractmethod
    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        """Get a URL to access the file (presigned for cloud, local path for disk)."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a file exists."""
        ...


class LocalFileStorage(FileStorage):
    """Current implementation — reads/writes to /app/uploads/."""
    def __init__(self, base_path: str = "/app/uploads"):
        self.base_path = Path(base_path)
    # ... implement methods using pathlib


class S3FileStorage(FileStorage):
    """AWS S3 or S3-compatible (MinIO) backend."""
    def __init__(self, bucket: str, region: str, credentials: dict):
        ...
    # ... implement methods using boto3/aioboto3


class GoogleDriveStorage(FileStorage):
    """Google Drive backend — customer provides OAuth credentials."""
    def __init__(self, credentials: dict, folder_id: str):
        ...
    # ... implement methods using Google Drive API
```

**Per-org configuration:**

Add a `storage_backend` setting to the `organisations` table:

```sql
ALTER TABLE organisations ADD COLUMN storage_backend VARCHAR(50) DEFAULT 'local';
ALTER TABLE organisations ADD COLUMN storage_config JSONB DEFAULT '{}';
```

Where `storage_config` holds backend-specific settings:
- `local`: `{}` (no config needed)
- `s3`: `{"bucket": "...", "region": "...", "access_key_id": "encrypted:...", "secret_key": "encrypted:..."}`
- `google_drive`: `{"folder_id": "...", "oauth_token": "encrypted:..."}`

**Factory function:**

```python
def get_storage_for_org(org: Organisation) -> FileStorage:
    if org.storage_backend == "s3":
        config = decrypt_storage_config(org.storage_config)
        return S3FileStorage(**config)
    elif org.storage_backend == "google_drive":
        config = decrypt_storage_config(org.storage_config)
        return GoogleDriveStorage(**config)
    else:
        return LocalFileStorage()
```

### Phase 2: Migrate Upload/Download Code

Replace direct disk I/O with the storage interface. The changes are localized to these files:

| File | Current approach | New approach |
|---|---|---|
| `app/modules/job_cards/attachment_service.py` | `Path(UPLOAD_BASE / file_key).write_bytes()` | `storage.save(file_key, data)` |
| `app/modules/compliance_docs/router.py` | `FileResponse(path)` | `storage.read(key)` → `Response(content=bytes)` |
| `app/modules/expenses/router.py` | `FileResponse(path)` | `storage.read(key)` → `Response(content=bytes)` |
| `app/modules/uploads/router.py` | `shutil.copyfileobj()` to disk | `storage.save(key, data)` |

**Important:** The `file_key` format in the database does NOT change. The keys are already backend-agnostic (no `/app/uploads/` prefix). Only the code that resolves keys to actual storage operations changes.

### Phase 3: Per-Org Migration Tool

When a customer wants to switch from local to cloud:

1. **Admin GUI:** Settings → Storage → "Migrate to S3" / "Connect Google Drive"
2. **Background job:** Reads all `file_key` values for the org from all tables, uploads each file to the new backend
3. **Cutover:** Updates `organisations.storage_backend` to the new value
4. **Cleanup:** Optionally deletes local copies after verification

The migration is per-org and non-disruptive — other orgs continue using local storage.

### Phase 4: HA Impact

Once orgs migrate off local storage:

| Org storage | HA file sync needed? | Why |
|---|---|---|
| `local` | Yes — rsync continues | Files only exist on the primary's disk |
| `s3` | No | S3 handles replication natively (cross-region) |
| `google_drive` | No | Files live in customer's Google account |

As orgs migrate, the rsync workload shrinks. When all orgs are on cloud storage, rsync can be disabled entirely.

---

## Considerations & Risks

### File Key Format (already good)

The current `file_key` format is already storage-agnostic:
- `job-card-attachments/{org_id}/{job_card_id}/{uuid}_{name}` ✅
- `{org_id}/certifications/{filename}` ✅

No database migration needed for file references. The abstraction layer just changes how keys are resolved to actual storage.

### Branding Files (special case)

Branding files have already been migrated from disk to database binary columns (`logo_data`, `dark_logo_data`). These don't need the storage abstraction — they're served directly from the DB. No change needed.

### PDF Generation (WeasyPrint)

WeasyPrint generates PDFs server-side. Currently it reads template assets from local disk. If assets move to cloud storage, WeasyPrint would need to fetch them via HTTP or the storage interface would need a `get_local_path()` method that downloads to a temp file. This is a minor consideration — most PDF templates use inline data, not file references.

### File Size Limits

Current limits:
- General uploads: 10 MB
- Branding logos: 2 MB
- Branding favicons: 512 KB

These limits should be enforced at the storage interface level, not just in the upload endpoints. Cloud backends may have their own limits (S3: 5 GB single upload, Google Drive: 5 TB).

### Security

- S3 credentials and Google Drive OAuth tokens must be stored encrypted (use existing `envelope_encrypt`)
- Presigned URLs for S3 should have short expiry (1 hour default)
- Google Drive files should be in a dedicated folder, not the customer's root
- File access must still go through the app's auth layer — no direct public URLs

### Cost

- S3: ~$0.023/GB/month for storage, $0.09/GB for transfer
- Google Drive: Free up to 15 GB per Google account, then $1.99/month for 100 GB
- For most trade businesses, file storage will be < 10 GB — cost is negligible

### Offline Access (Mobile App)

The mobile app (Capacitor) currently doesn't download files for offline access. If files move to cloud storage, the mobile app would need to cache frequently accessed files locally. This is a separate feature.

---

## When to Start This Work

| Signal | Action |
|---|---|
| File count < 10K, no cloud requests | Do nothing — rsync is fine |
| Customer asks for S3/Google Drive | Build Phase 1 (abstraction layer) + Phase 2 (migrate code) |
| File count approaching 50K | Build Phase 1 + replace rsync with event-driven sync |
| Multiple orgs on different backends | Build Phase 3 (per-org migration tool) |

**Current state (April 2026):** 1 org, ~2 files, 876 KB. No action needed.
