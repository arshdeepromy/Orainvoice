/**
 * BackupGuide — in-app provider setup guide for the Cloud Backup area (Global
 * Admin). Mounted at /admin/backup/guide and reached from the "Setup Guide" tab
 * in BackupLayout.
 *
 * Mirrors docs/cloud-backup-provider-setup.md, but rendered in-app so a Global
 * Admin can follow it alongside the Destinations form. The OAuth callback URL is
 * derived from the live origin (window.location.origin) so the value shown is
 * exactly what must be registered at Google / Microsoft for this deployment.
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import Badge from '@/components/ui/Badge'
import { AlertBanner } from '@/components/ui/AlertBanner'

/* ------------------------------------------------------------------ */
/*  Small presentational helpers (local to this static content page)   */
/* ------------------------------------------------------------------ */

function Section({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="scroll-mt-24">
      <h2 className="text-[17px] font-semibold text-text">{title}</h2>
      <div className="mt-3 space-y-3 text-[13.5px] leading-relaxed text-text">{children}</div>
    </section>
  )
}

function Mono({ children }: { children: React.ReactNode }) {
  return (
    <code className="mono rounded bg-canvas px-1.5 py-0.5 text-[12.5px] text-text">{children}</code>
  )
}

function FieldTable({ rows }: { rows: { field: string; value: string }[] }) {
  return (
    <div className="overflow-x-auto rounded-card border border-border">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {['Field', 'What to enter'].map((h) => (
              <th
                key={h}
                scope="col"
                className="mono border-b border-border px-4 py-2.5 text-left text-[10.5px] font-medium uppercase tracking-[0.08em] text-muted-2"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.field} className="border-b border-border last:border-b-0">
              <td className="whitespace-nowrap px-4 py-2.5 align-top text-[13px] font-medium text-text">
                {r.field}
              </td>
              <td className="px-4 py-2.5 text-[13px] text-muted">{r.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">
        {n}
      </span>
      <span className="min-w-0">{children}</span>
    </li>
  )
}

/* ------------------------------------------------------------------ */
/*  Page                                                               */
/* ------------------------------------------------------------------ */

export function BackupGuide() {
  // The OAuth redirect URI includes the destination id and is derived from the
  // request host server-side; show the live origin so the operator copies the
  // exact value for THIS deployment.
  const origin = useMemo(
    () => (typeof window !== 'undefined' ? window.location.origin : 'https://<your-host>'),
    [],
  )
  const callbackTemplate = `${origin}/api/v1/backup/destinations/<DESTINATION_ID>/oauth/callback`

  return (
    <div className="max-w-3xl space-y-8 pb-10">
      {/* Intro */}
      <div className="space-y-3">
        <p className="text-[13.5px] leading-relaxed text-text">
          Configure backup <strong>destinations</strong> in{' '}
          <Link to="/admin/backup/settings" className="font-medium text-accent underline">
            Destinations &amp; Schedule
          </Link>
          . You can add several destinations with exactly one <strong>primary</strong> and any
          number of <strong>copy</strong> destinations. Each backup is encrypted, then the same
          encrypted set is sent to every destination.
        </p>

        <div className="flex flex-wrap gap-2">
          {[
            ['Amazon S3 / S3-compatible', 'Primary or Immutable copy'],
            ['NAS / SMB', 'Onshore copy'],
            ['Google Drive', 'OAuth copy'],
            ['OneDrive', 'OAuth copy'],
          ].map(([name, use]) => (
            <span
              key={name}
              className="rounded-ctl border border-border px-3 py-1.5 text-[12.5px] text-text"
            >
              <span className="font-medium">{name}</span>{' '}
              <span className="text-muted">· {use}</span>
            </span>
          ))}
        </div>

        {/* Quick links */}
        <nav className="flex flex-wrap gap-x-4 gap-y-1 pt-1 text-[12.5px]" aria-label="Guide sections">
          <a href="#prereqs" className="text-accent underline">Prerequisites</a>
          <a href="#s3" className="text-accent underline">Amazon S3</a>
          <a href="#nas" className="text-accent underline">NAS / SMB</a>
          <a href="#gdrive" className="text-accent underline">Google Drive</a>
          <a href="#onedrive" className="text-accent underline">OneDrive</a>
          <a href="#after" className="text-accent underline">After setup</a>
          <a href="#trouble" className="text-accent underline">Troubleshooting</a>
        </nav>
      </div>

      {/* Prerequisites */}
      <Section id="prereqs" title="Prerequisites (do these once, first)">
        <ol className="space-y-2">
          <Step n={1}>
            <strong>Set up the backup key</strong> in{' '}
            <Link to="/admin/backup/keys" className="font-medium text-accent underline">
              Recovery Keys
            </Link>
            : generate a passphrase, download the Recovery Kit, and confirm you stored it offline.
            Backups can&apos;t run until a backup key exists.
          </Step>
          <Step n={2}>
            <strong>Everything is encrypted before upload.</strong> All four providers only ever
            store ciphertext (AES-256-GCM under the escrowed backup key) — even an onshore NAS or
            your own S3 bucket never sees plaintext.
          </Step>
          <Step n={3}>
            <strong>Residency acknowledgement.</strong> Before the first upload to an{' '}
            <em>offshore</em> destination, open <Mono>Residency</Mono> on the destination row and
            acknowledge the notice. Onshore (NZ) destinations don&apos;t need this.
          </Step>
        </ol>
        <AlertBanner variant="warning" title="Keep the Recovery Kit safe">
          The Recovery Kit is the only way to decrypt backups on a fresh deployment after a total
          loss. Store it offline (password manager + a printed copy in a safe). Without it, backups
          are unrecoverable.
        </AlertBanner>
        <p className="text-[12.5px] text-muted">
          Credentials are stored encrypted and shown masked (e.g. <Mono>••••1234</Mono>). When
          editing, leave a masked secret untouched to keep it; type a new value only to replace it.
        </p>
      </Section>

      {/* S3 */}
      <Section id="s3" title="Amazon S3 / S3-compatible (AWS, MinIO, Wasabi, Backblaze B2)">
        <p className="font-medium text-text">On the provider:</p>
        <ol className="space-y-2">
          <Step n={1}>
            Create a bucket. For an <strong>Immutable copy</strong>, enable <strong>Object Lock</strong>{' '}
            at bucket creation — it can&apos;t be turned on later.
          </Step>
          <Step n={2}>
            Create an access key limited to that bucket with{' '}
            <Mono>s3:PutObject</Mono>, <Mono>s3:GetObject</Mono>, <Mono>s3:ListBucket</Mono>,{' '}
            <Mono>s3:DeleteObject</Mono> (plus <Mono>s3:PutObjectRetention</Mono> for Object Lock).
          </Step>
        </ol>
        <p className="font-medium text-text">In OraInvoice → Add a destination → Amazon S3:</p>
        <FieldTable
          rows={[
            { field: 'Display name', value: 'Any label, e.g. "Primary offsite (Wasabi)"' },
            { field: 'Access Key ID', value: 'The access key id' },
            { field: 'Secret Access Key', value: 'The secret' },
            { field: 'Bucket', value: 'The bucket name' },
            { field: 'Region', value: 'e.g. us-east-1, ap-southeast-2 (MinIO: the configured region)' },
            {
              field: 'Endpoint URL',
              value:
                'Leave blank for AWS. For S3-compatible set it, e.g. https://s3.wasabisys.com or your MinIO URL.',
            },
            {
              field: 'Addressing style',
              value: 'Auto for AWS. Use Path-style for MinIO / older servers if virtual-hosted fails.',
            },
          ]}
        />
        <p>
          Save → <Mono>Test connection</Mono> (HeadBucket / put-then-delete probe) → it flips to{' '}
          <Badge variant="success">Connected</Badge>. Click <Mono>Set as primary</Mono> to make it
          the primary. For write-once protection, toggle <strong>Immutable copy</strong> and set a
          lock window (the bucket must have Object Lock enabled).
        </p>
      </Section>

      {/* NAS */}
      <Section id="nas" title="NAS / SMB share">
        <p>
          Two access modes: <strong>SMB / CIFS</strong> (connect to <Mono>//server/share</Mono>{' '}
          with credentials) or <strong>Local mount</strong> (the share is already mounted into the
          app container).
        </p>
        <FieldTable
          rows={[
            { field: 'Display name', value: 'e.g. "Office NAS (onshore)"' },
            { field: 'Share path', value: '//server/share (SMB) or the mounted path (local)' },
            { field: 'Access mode', value: 'SMB / CIFS or Local mount' },
            { field: 'Target directory', value: 'Subfolder for backups, e.g. orainvoice/backups' },
            { field: 'Username', value: 'NAS user (SMB only)' },
            { field: 'Password', value: 'NAS password (SMB only)' },
          ]}
        />
        <p>
          Save → <Mono>Test connection</Mono> (reaches the share and does a write-then-delete probe).
        </p>
        <AlertBanner variant="info" title="Local mount & immutability">
          For Local mount, the app container must have the NAS volume mounted. A plain NAS provides
          no WORM, so it isn&apos;t a valid Immutable copy unless it natively offers WORM / immutable
          snapshots. Writes are always temp-file-then-atomic-rename.
        </AlertBanner>
      </Section>

      {/* Shared OAuth callback callout */}
      <AlertBanner variant="info" title="OAuth callback URL for this deployment">
        <p>
          Google Drive and OneDrive use a redirect URI that <strong>includes the destination&apos;s
          id</strong>, so you must create the destination first, then register its specific callback
          URL. For this deployment the format is:
        </p>
        <pre className="mono mt-2 overflow-x-auto rounded-ctl border border-border bg-canvas px-3 py-2 text-[12px] text-text">
          {callbackTemplate}
        </pre>
        <p className="mt-2 text-[12.5px]">
          Replace <Mono>&lt;DESTINATION_ID&gt;</Mono> with the id of the destination you create
          (register one callback URL per OAuth destination).
        </p>
      </AlertBanner>

      {/* Google Drive */}
      <Section id="gdrive" title="Google Drive (OAuth)">
        <ol className="space-y-2">
          <Step n={1}>
            In Google Cloud Console → <strong>APIs &amp; Services</strong>, enable the{' '}
            <strong>Google Drive API</strong> and configure the OAuth consent screen (Internal is
            fine for a single org).
          </Step>
          <Step n={2}>
            Create an <strong>OAuth client ID</strong> of type <strong>Web application</strong>; note
            the Client ID and Client secret.
          </Step>
          <Step n={3}>
            In OraInvoice → Add a destination → Google Drive, enter the Client ID, Client Secret, and
            a Folder path (e.g. <Mono>/OraInvoiceBackups</Mono>). Save — it shows{' '}
            <Badge variant="neutral">Disconnected</Badge>.
          </Step>
          <Step n={4}>
            Add the callback URL above (with this destination&apos;s id) under{' '}
            <strong>Authorized redirect URIs</strong> on the OAuth client, and save.
          </Step>
          <Step n={5}>
            Click <Mono>Connect</Mono> on the row → complete the Google popup (scope{' '}
            <Mono>drive.file</Mono> — only files this app creates) → the row flips to{' '}
            <Badge variant="success">Connected</Badge>. Then <Mono>Test connection</Mono>.
          </Step>
        </ol>
      </Section>

      {/* OneDrive */}
      <Section id="onedrive" title="OneDrive (OAuth)">
        <ol className="space-y-2">
          <Step n={1}>
            In Azure Portal → <strong>Microsoft Entra ID → App registrations → New registration</strong>{' '}
            (single-tenant is fine). Note the <strong>Application (client) ID</strong>.
          </Step>
          <Step n={2}>
            Under <strong>Certificates &amp; secrets</strong>, create a client secret; note its
            value. Under API permissions add Microsoft Graph delegated{' '}
            <Mono>Files.ReadWrite</Mono> and <Mono>offline_access</Mono>.
          </Step>
          <Step n={3}>
            In OraInvoice → Add a destination → OneDrive, enter the Client ID, Client Secret, and a
            Folder path. Save — it shows <Badge variant="neutral">Disconnected</Badge>.
          </Step>
          <Step n={4}>
            Add the callback URL above (with this destination&apos;s id) under{' '}
            <strong>Authentication → Web → Redirect URIs</strong> on the Azure app.
          </Step>
          <Step n={5}>
            Click <Mono>Connect</Mono> → complete the Microsoft popup (scopes{' '}
            <Mono>offline_access Files.ReadWrite</Mono>) → the row flips to{' '}
            <Badge variant="success">Connected</Badge>. Then <Mono>Test connection</Mono>.
          </Step>
        </ol>
      </Section>

      {/* After */}
      <Section id="after" title="After configuring destinations">
        <ol className="space-y-2">
          <Step n={1}>
            <strong>Set the primary</strong> — exactly one destination must be primary.
          </Step>
          <Step n={2}>
            <Link to="/admin/backup/settings" className="font-medium text-accent underline">
              Schedule &amp; retention
            </Link>
            : set the backup cron (NZ time), backup window, retention (count/days), and RPO/RTO.
          </Step>
          <Step n={3}>
            <strong>Notifications</strong>: pick events, channels (email/SMS/webhook), and
            recipients; use <Mono>Send test</Mono> to verify each channel.
          </Step>
          <Step n={4}>
            From the{' '}
            <Link to="/admin/backup" className="font-medium text-accent underline">
              Overview
            </Link>{' '}
            page, use <Mono>Run backup now</Mono> to confirm the whole pipeline works.
          </Step>
        </ol>
      </Section>

      {/* Troubleshooting */}
      <Section id="trouble" title="Troubleshooting">
        <ul className="list-disc space-y-1.5 pl-5 text-[13px] text-muted">
          <li>
            <span className="text-text">Test connection fails (S3):</span> check bucket/region; for
            S3-compatible set the Endpoint URL and try Path-style addressing.
          </li>
          <li>
            <span className="text-text">&quot;redirect_uri_mismatch&quot;:</span> the URI registered
            at the provider must match the destination&apos;s callback URL exactly — host (https),
            destination id, and path.
          </li>
          <li>
            <span className="text-text">Popup blocked:</span> allow popups for this host, then click
            Connect again.
          </li>
          <li>
            <span className="text-text">Row stuck on Disconnected after consent:</span> re-run
            Connect; a revoked/expired token flips a connection back to disconnected.
          </li>
          <li>
            <span className="text-text">Offshore destination won&apos;t back up:</span> open
            Residency on the row and acknowledge the disclosure first.
          </li>
        </ul>
      </Section>
    </div>
  )
}
