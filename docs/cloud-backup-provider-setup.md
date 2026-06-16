# Cloud Backup — Provider Setup Guide (Global Admin)

This guide walks a Global Admin through configuring each backup **destination**
in **Admin Console → Backup & Restore → Cloud Backup → Destinations & Schedule**.

The platform supports four provider types:

| Provider | Auth model | Best used as |
|---|---|---|
| Amazon S3 / S3-compatible | Access key + secret | Primary or Immutable copy (Object Lock) |
| NAS / SMB share | Username + password (or local mount) | Onshore copy destination |
| Google Drive | OAuth (popup) | Copy destination |
| OneDrive | OAuth (popup) | Copy destination |

You can configure **several destinations** with exactly **one primary** and zero
or more **copy** destinations. A backup fans the identical encrypted artifact set
out to every destination. A copy-destination failure is reported but doesn't fail
the job; a **primary** failure fails the backup.

---

## Prerequisites (do these once, first)

1. **Set up the backup key.** Go to **Recovery Keys** and complete first-run
   setup (generate or enter a passphrase, download the Recovery Kit, confirm you
   stored it offline). Backups cannot run until a backup key exists. The Recovery
   Kit is the *only* way to decrypt backups on a fresh deployment after a total
   loss — store it offline (password manager + printed copy in a safe).
2. **Everything is encrypted before upload.** All four providers only ever
   receive ciphertext (AES-256-GCM under the escrowed backup key). Even an
   onshore NAS or your own S3 bucket never sees plaintext.
3. **Residency acknowledgement.** Before the first upload to an **offshore**
   destination, you must acknowledge the data-residency notice (the **Residency**
   button on the destination row). Onshore (NZ) destinations don't require this.

> Credentials are stored encrypted and are **masked** in the UI (e.g.
> `••••1234`). When you edit a destination, leave a masked secret untouched to
> keep the stored value; type a new value only to replace it.

---

## Amazon S3 / S3-compatible (AWS, MinIO, Wasabi, Backblaze B2)

**On the provider:**
1. Create a bucket (and, for an Immutable copy, enable **Object Lock** at bucket
   creation — it can't be turned on later).
2. Create an IAM user / access key limited to that bucket with permissions:
   `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`, `s3:DeleteObject` (plus
   `s3:PutObjectRetention` if you use Object Lock).

**In OraInvoice → Add a destination → Amazon S3 / S3-compatible:**

| Field | What to enter |
|---|---|
| Display name | Any label, e.g. `Primary offsite (Wasabi)` |
| Access Key ID | The IAM access key id |
| Secret Access Key | The IAM secret |
| Bucket | The bucket name |
| Region | e.g. `us-east-1`, `ap-southeast-2` (for MinIO use the configured region) |
| Endpoint URL | **Leave blank for AWS.** For S3-compatible, set the endpoint, e.g. `https://s3.wasabisys.com`, `https://s3.us-west-002.backblazeb2.com`, or your MinIO URL |
| Addressing style | `Auto` for AWS. Use `Path-style` for MinIO / older S3-compatible servers if virtual-hosted fails |

3. Save, then click **Test connection** (does a HeadBucket / put-then-delete
   probe). It should flip to **Connected**.
4. To make it the primary, click **Set as primary**.

**Immutable / write-once copy:** toggle it on in the Add/Edit form and set a
**lock window (days)**. The bucket must have Object Lock enabled; backups in the
window can't be deleted early. S3 in compliance mode is the recommended immutable
target.

---

## NAS / SMB share

Two access modes:

- **SMB / CIFS** — connect to `//server/share` with a username/password.
- **Local mount** — the share is already mounted into the app container's
  filesystem (see infra note below).

**In OraInvoice → Add a destination → NAS / SMB share:**

| Field | What to enter |
|---|---|
| Display name | e.g. `Office NAS (onshore)` |
| Share path | `//server/share` (SMB) or the mounted path (local) |
| Access mode | `SMB / CIFS` or `Local mount` |
| Target directory | Subfolder for backups, e.g. `orainvoice/backups` |
| Username | NAS user (SMB only) |
| Password | NAS password (SMB only) |

Save → **Test connection** (mounts/reaches the share and does a write-then-delete
probe).

> **Infra note for Local mount:** the container the app runs in must have the NAS
> volume mounted (a Docker bind/volume). A plain NAS provides no WORM, so it is
> **not** a valid Immutable copy unless it natively offers WORM/immutable
> snapshots. Writes are always temp-file-then-atomic-rename.

---

## Google Drive (OAuth)

Because the OAuth **redirect URI includes the destination's id**, the order is:
create the destination first, then register its specific callback URL, then
connect.

**Step 1 — Create a Google Cloud OAuth client:**
1. In Google Cloud Console → **APIs & Services**, enable the **Google Drive API**.
2. Configure the **OAuth consent screen** (Internal is fine for a single org).
3. Create an **OAuth client ID** of type **Web application**.
4. Note the **Client ID** and **Client secret**. Leave the redirect URI for now.

**Step 2 — Add the destination in OraInvoice → Add a destination → Google Drive:**

| Field | What to enter |
|---|---|
| Display name | e.g. `Google Drive backups` |
| OAuth Client ID | From step 1 |
| OAuth Client Secret | From step 1 |
| Folder path | e.g. `/OraInvoiceBackups` |

Save the destination. It appears in the list as **Disconnected**.

**Step 3 — Register the redirect URI.** The callback URL for this destination is:

```
https://<your-host>/api/v1/backup/destinations/<DESTINATION_ID>/oauth/callback
```

- `<your-host>` is whatever host you use to reach the admin console
  (production: `https://one.oraflows.co.nz`; local dev: `http://localhost`).
- `<DESTINATION_ID>` is the id of the destination you just created.

Add that exact URL under **Authorized redirect URIs** on the OAuth client in
Google Cloud, and save. (Each Drive destination has its own callback URL because
the id differs — register one per destination.)

**Step 4 — Connect.** Click **Connect** on the destination row. A popup runs the
Google consent screen (scope: `drive.file` — access only to files this app
creates). On success the popup hands back automatically and the row flips to
**Connected**. Then **Test connection** to confirm.

---

## OneDrive (OAuth)

Same create-then-register-then-connect order as Google Drive.

**Step 1 — Register an Azure app:**
1. In **Azure Portal → Microsoft Entra ID → App registrations → New
   registration**. Supported account types: single-tenant is fine.
2. Under **Certificates & secrets**, create a **client secret**; note its value.
3. Note the **Application (client) ID**.
4. API permissions: **Microsoft Graph → Delegated → `Files.ReadWrite`** and
   `offline_access` (these are the scopes the app requests).

**Step 2 — Add the destination in OraInvoice → Add a destination → OneDrive:**

| Field | What to enter |
|---|---|
| Display name | e.g. `OneDrive backups` |
| OAuth Client ID | Application (client) ID |
| OAuth Client Secret | The client secret value |
| Folder path | e.g. `/OraInvoiceBackups` |

Save (appears **Disconnected**).

**Step 3 — Register the redirect URI** on the Azure app under **Authentication →
Web → Redirect URIs**:

```
https://<your-host>/api/v1/backup/destinations/<DESTINATION_ID>/oauth/callback
```

**Step 4 — Connect.** Click **Connect**, complete the Microsoft consent popup
(scopes `offline_access Files.ReadWrite`), and the row flips to **Connected**.
**Test connection** to confirm.

---

## After configuring destinations

1. **Set the primary** (one destination must be primary).
2. **Schedule & retention** tab: set the backup cron (NZ time), backup window,
   retention (count/days), and RPO/RTO. Inline warnings flag an RPO that the
   schedule can't meet.
3. **Notifications** tab: choose which events notify, channels (email/SMS/
   webhook), and recipients. Use **Send test** to verify each channel.
4. From the **Overview** page, use **Run backup now** to take an immediate
   backup and confirm the whole pipeline works end-to-end.

## Troubleshooting

- **Test connection fails (S3):** check bucket/region; for S3-compatible set
  the **Endpoint URL** and try **Path-style** addressing.
- **OAuth popup shows an error / "redirect_uri_mismatch":** the redirect URI
  registered at the provider must match the destination's callback URL exactly,
  including the host (https), the destination id, and the path.
- **Popup blocked:** allow popups for the admin host, then click **Connect**
  again.
- **Row stuck on Disconnected after consent:** re-run **Connect**; a revoked or
  expired token flips a connection back to disconnected.
- **Offshore destination won't back up:** open **Residency** on the row and
  acknowledge the disclosure first.
