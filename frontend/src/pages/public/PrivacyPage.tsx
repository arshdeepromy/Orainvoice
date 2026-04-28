import { useState, useEffect } from 'react'
import axios from 'axios'
import { LandingHeader, LandingFooter } from '@/components/public'

/* ------------------------------------------------------------------ */
/*  Simple Markdown-to-HTML renderer                                   */
/*  Converts: headings, bold, italic, links, lists, paragraphs        */
/* ------------------------------------------------------------------ */

function renderMarkdownToHtml(markdown: string): string {
  let html = markdown
    // Escape HTML entities first
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // Headings (### before ## before #)
  html = html.replace(/^### (.+)$/gm, '<h3 class="mt-8 mb-3 text-xl font-semibold text-gray-900">$1</h3>')
  html = html.replace(/^## (.+)$/gm, '<h2 class="mt-10 mb-4 text-2xl font-bold text-gray-900">$1</h2>')
  html = html.replace(/^# (.+)$/gm, '<h1 class="mt-12 mb-6 text-3xl font-bold text-gray-900">$1</h1>')

  // Bold and italic
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')

  // Links [text](url)
  html = html.replace(
    /\[([^\]]+)\]\(([^)]+)\)/g,
    '<a href="$2" class="text-blue-600 underline hover:text-blue-500" target="_blank" rel="noopener noreferrer">$1</a>',
  )

  // Unordered lists (- item)
  html = html.replace(/^- (.+)$/gm, '<li class="ml-6 list-disc text-gray-700">$1</li>')

  // Ordered lists (1. item)
  html = html.replace(/^\d+\. (.+)$/gm, '<li class="ml-6 list-decimal text-gray-700">$1</li>')

  // Wrap consecutive <li> elements in <ul> or <ol>
  html = html.replace(
    /(<li class="ml-6 list-disc[^"]*">[\s\S]*?<\/li>\n?)+/g,
    (match) => `<ul class="my-3 space-y-1">${match}</ul>`,
  )
  html = html.replace(
    /(<li class="ml-6 list-decimal[^"]*">[\s\S]*?<\/li>\n?)+/g,
    (match) => `<ol class="my-3 space-y-1">${match}</ol>`,
  )

  // Paragraphs — lines that aren't already wrapped in HTML tags
  html = html
    .split('\n')
    .map((line) => {
      const trimmed = line.trim()
      if (!trimmed) return ''
      if (trimmed.startsWith('<')) return trimmed
      return `<p class="mb-4 leading-relaxed text-gray-700">${trimmed}</p>`
    })
    .join('\n')

  return html
}

/* ------------------------------------------------------------------ */
/*  Table of Contents entries for the default policy                   */
/* ------------------------------------------------------------------ */

interface TocEntry {
  id: string
  label: string
}

const TABLE_OF_CONTENTS: TocEntry[] = [
  { id: 'introduction', label: '1. Introduction' },
  { id: 'data-collection', label: '2. Data Collection Disclosure' },
  { id: 'ipp-1', label: '3. IPP 1 — Purpose of Collection' },
  { id: 'ipp-2', label: '4. IPP 2 — Source of Information' },
  { id: 'ipp-3', label: '5. IPP 3 — Collection of Information from Subject' },
  { id: 'ipp-4', label: '6. IPP 4 — Manner of Collection' },
  { id: 'ipp-5', label: '7. IPP 5 — Storage and Security' },
  { id: 'ipp-6', label: '8. IPP 6 — Access to Personal Information' },
  { id: 'ipp-7', label: '9. IPP 7 — Correction of Personal Information' },
  { id: 'ipp-8', label: '10. IPP 8 — Accuracy of Information' },
  { id: 'ipp-9', label: '11. IPP 9 — Retention of Personal Information' },
  { id: 'ipp-10', label: '12. IPP 10 — Limits on Use' },
  { id: 'ipp-11', label: '13. IPP 11 — Limits on Disclosure' },
  { id: 'ipp-12', label: '14. IPP 12 — Cross-Border Transfers' },
  { id: 'ipp-13', label: '15. IPP 13 — Unique Identifiers' },
  { id: 'breach-notification', label: '16. Breach Notification' },
  { id: 'data-portability', label: '17. Data Portability and Deletion' },
  { id: 'children', label: '18. Children\'s Data' },
  { id: 'data-sovereignty', label: '19. Data Sovereignty' },
  { id: 'contact', label: '20. Contact and Complaints' },
]

/* Default hardcoded date for the built-in policy */
const DEFAULT_LAST_UPDATED = '2025-01-01'

/* ------------------------------------------------------------------ */
/*  PrivacyPage Component                                              */
/* ------------------------------------------------------------------ */

export default function PrivacyPage() {
  const [customContent, setCustomContent] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // Allow document scroll on public pages
  useEffect(() => {
    document.documentElement.classList.add('public-page')
    return () => { document.documentElement.classList.remove('public-page') }
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    const fetchPolicy = async () => {
      try {
        const res = await axios.get<{ content?: string | null; last_updated?: string | null }>(
          '/api/v1/public/privacy-policy',
          { signal: controller.signal },
        )
        setCustomContent(res.data?.content ?? null)
        setLastUpdated(res.data?.last_updated ?? null)
      } catch (err) {
        if (!controller.signal.aborted) {
          // On error, fall back to default policy (customContent stays null)
          console.error('Failed to fetch privacy policy:', err)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    fetchPolicy()
    return () => controller.abort()
  }, [])

  const displayDate = lastUpdated ?? DEFAULT_LAST_UPDATED

  return (
    <>
      <LandingHeader />

      <main className="min-h-screen bg-white pt-16">
        <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6 lg:px-8 text-base">
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
            </div>
          ) : customContent ? (
            /* ---- Custom Markdown content from admin ---- */
            <article>
              <h1 className="mb-2 text-3xl font-bold text-gray-900 sm:text-4xl">Privacy Policy</h1>
              <p className="mb-8 text-sm text-gray-500">
                Last Updated: {new Date(displayDate).toLocaleDateString('en-NZ', { year: 'numeric', month: 'long', day: 'numeric' })}
              </p>
              <div
                className="prose prose-gray max-w-none text-base leading-relaxed"
                dangerouslySetInnerHTML={{ __html: renderMarkdownToHtml(customContent) }}
              />
            </article>
          ) : (
            /* ---- Default hardcoded NZ Privacy Act 2020 policy ---- */
            <DefaultPrivacyPolicy displayDate={displayDate} />
          )}
        </div>
      </main>

      <LandingFooter />
    </>
  )
}


/* ------------------------------------------------------------------ */
/*  Default Privacy Policy — Full NZ Privacy Act 2020 Compliance       */
/*  Covers all 13 IPPs, data collection, breach notification,          */
/*  data portability/deletion, contact/complaints, children's data,    */
/*  and data sovereignty.                                              */
/* ------------------------------------------------------------------ */

function DefaultPrivacyPolicy({ displayDate }: { displayDate: string }) {
  return (
    <article className="text-base leading-relaxed">
      {/* Title and last updated */}
      <h1 className="mb-2 text-3xl font-bold text-gray-900 sm:text-4xl">Privacy Policy</h1>
      <p className="mb-8 text-sm text-gray-500">
        Last Updated:{' '}
        {new Date(displayDate).toLocaleDateString('en-NZ', {
          year: 'numeric',
          month: 'long',
          day: 'numeric',
        })}
      </p>

      {/* ---- Table of Contents ---- */}
      <nav aria-label="Table of contents" className="mb-12 rounded-lg border border-gray-200 bg-gray-50 p-6">
        <h2 className="mb-4 text-lg font-semibold text-gray-900">Table of Contents</h2>
        <ol className="list-decimal space-y-1 pl-5">
          {TABLE_OF_CONTENTS.map((entry) => (
            <li key={entry.id}>
              <a
                href={`#${entry.id}`}
                className="text-blue-600 transition-colors hover:text-blue-500 hover:underline"
              >
                {entry.label.replace(/^\d+\.\s*/, '')}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      {/* ============================================================ */}
      {/*  1. Introduction                                              */}
      {/* ============================================================ */}
      <section id="introduction" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">1. Introduction</h2>
        <p className="mb-4 text-gray-700">
          OraInvoice is a business management and invoicing platform operated by Oraflows Limited, a
          New Zealand registered company. This Privacy Policy explains how we collect, use, store,
          and protect personal and business information in accordance with the New Zealand Privacy
          Act 2020.
        </p>
        <p className="mb-4 text-gray-700">
          This policy applies to all users of the OraInvoice platform, including business owners,
          staff members, and their customers whose data is stored within the system. By using
          OraInvoice, you agree to the collection and use of information as described in this policy.
        </p>
        <p className="text-gray-700">
          OraInvoice does not use third-party tracking cookies. We are committed to transparency and
          to protecting your privacy in compliance with all 13 Information Privacy Principles (IPPs)
          of the NZ Privacy Act 2020.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  2. Data Collection Disclosure                                */}
      {/* ============================================================ */}
      <section id="data-collection" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">2. Data Collection Disclosure</h2>
        <p className="mb-4 text-gray-700">
          OraInvoice collects the following categories of information to provide our services:
        </p>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Personal Information</h3>
        <ul className="mb-4 list-disc space-y-1 pl-6 text-gray-700">
          <li>Name</li>
          <li>Email address</li>
          <li>Phone number</li>
          <li>Business name</li>
          <li>Business address</li>
        </ul>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Business Data</h3>
        <ul className="mb-4 list-disc space-y-1 pl-6 text-gray-700">
          <li>Invoices</li>
          <li>Quotes</li>
          <li>Job cards</li>
          <li>Customer records</li>
          <li>Vehicle records</li>
          <li>Staff records</li>
          <li>Inventory records</li>
          <li>Financial transactions</li>
          <li>Accounting data</li>
        </ul>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Vehicle Data</h3>
        <ul className="mb-4 list-disc space-y-1 pl-6 text-gray-700">
          <li>Registration number</li>
          <li>Make, model, and year</li>
          <li>Vehicle Identification Number (VIN)</li>
          <li>Odometer readings</li>
          <li>Warrant of Fitness (WOF) expiry</li>
          <li>Registration expiry</li>
        </ul>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Payment Data</h3>
        <ul className="mb-4 list-disc space-y-1 pl-6 text-gray-700">
          <li>Stripe payment tokens and transaction records</li>
          <li>
            OraInvoice does <strong>not</strong> store full credit card numbers. Payment processing
            is handled securely by Stripe.
          </li>
        </ul>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Technical Data</h3>
        <ul className="mb-4 list-disc space-y-1 pl-6 text-gray-700">
          <li>IP addresses</li>
          <li>Browser type</li>
          <li>JWT session tokens</li>
          <li>Login timestamps</li>
        </ul>

        <p className="text-gray-700">
          OraInvoice does <strong>not</strong> use third-party tracking cookies.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  3. IPP 1 — Purpose of Collection                            */}
      {/* ============================================================ */}
      <section id="ipp-1" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          3. IPP 1 — Purpose of Collection
        </h2>
        <p className="mb-4 text-gray-700">
          We collect personal information for the following specific purposes:
        </p>
        <ol className="mb-4 list-decimal space-y-2 pl-6 text-gray-700">
          <li>To create and manage your OraInvoice account and authenticate your identity.</li>
          <li>To provide invoicing, quoting, job management, and business operations services.</li>
          <li>To process payments through our integrated payment provider (Stripe).</li>
          <li>To send transactional notifications (invoice reminders, appointment confirmations, overdue notices) via email and SMS.</li>
          <li>To perform vehicle lookups via CarJam for automotive business features.</li>
          <li>To synchronise accounting data with Xero when the integration is enabled by the user.</li>
          <li>To generate business reports and analytics for the account holder.</li>
          <li>To maintain platform security, prevent fraud, and comply with legal obligations.</li>
          <li>To respond to support enquiries and demo requests.</li>
        </ol>
        <p className="text-gray-700">
          We do not collect personal information unless it is necessary for one or more of the
          purposes listed above.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  4. IPP 2 — Source of Information                             */}
      {/* ============================================================ */}
      <section id="ipp-2" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          4. IPP 2 — Source of Information
        </h2>
        <p className="mb-4 text-gray-700">
          Personal information is collected directly from the individual or their authorised
          representative. Specifically:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>
            <strong>Account holders and staff</strong> provide their own personal information during
            registration and account setup.
          </li>
          <li>
            <strong>Customer records</strong> are entered by the business (the OraInvoice account
            holder) on behalf of their customers, as part of normal business operations.
          </li>
          <li>
            <strong>Vehicle data</strong> may be retrieved from CarJam (a third-party vehicle
            information service) based on a registration number provided by the user.
          </li>
          <li>
            <strong>Technical data</strong> (IP addresses, browser type) is collected automatically
            when you access the platform.
          </li>
        </ul>
      </section>

      {/* ============================================================ */}
      {/*  5. IPP 3 — Collection of Information from Subject            */}
      {/* ============================================================ */}
      <section id="ipp-3" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          5. IPP 3 — Collection of Information from Subject
        </h2>
        <p className="mb-4 text-gray-700">
          When we collect personal information directly from an individual, we take reasonable steps
          to ensure that the individual is aware of:
        </p>
        <ol className="mb-4 list-decimal space-y-2 pl-6 text-gray-700">
          <li>The fact that information is being collected.</li>
          <li>The purpose for which the information is being collected.</li>
          <li>The intended recipients of the information.</li>
          <li>Whether the supply of information is voluntary or mandatory.</li>
          <li>The consequences (if any) of not providing the information.</li>
          <li>The individual's rights of access to and correction of their personal information.</li>
        </ol>
        <p className="text-gray-700">
          This information is provided through this Privacy Policy, through in-app notices at the
          point of collection, and through our Terms of Service.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  6. IPP 4 — Manner of Collection                             */}
      {/* ============================================================ */}
      <section id="ipp-4" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          6. IPP 4 — Manner of Collection
        </h2>
        <p className="mb-4 text-gray-700">
          OraInvoice collects personal information by lawful means that are fair and not
          unreasonably intrusive. Information is collected through:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>Account registration forms</li>
          <li>In-app data entry (invoices, job cards, customer records, etc.)</li>
          <li>API integrations initiated by the user (CarJam, Xero, Stripe)</li>
          <li>Automated technical logging (IP addresses, session tokens)</li>
          <li>Demo request forms on our public website</li>
        </ul>
        <p className="text-gray-700">
          We do not collect information through deceptive or covert means.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  7. IPP 5 — Storage and Security                             */}
      {/* ============================================================ */}
      <section id="ipp-5" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          7. IPP 5 — Storage and Security
        </h2>
        <p className="mb-4 text-gray-700">
          OraInvoice takes the security of your personal information seriously. We implement the
          following safeguards:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>
            <strong>Encryption at rest:</strong> All data stored in our PostgreSQL database is
            encrypted. Sensitive fields (API keys, integration credentials) use additional
            application-level encryption.
          </li>
          <li>
            <strong>Encryption in transit:</strong> All communications between your browser and our
            servers use HTTPS/TLS encryption.
          </li>
          <li>
            <strong>Row-level security:</strong> PostgreSQL row-level security policies ensure that
            each organisation can only access its own data.
          </li>
          <li>
            <strong>Authentication:</strong> Multi-factor authentication (MFA) is available via
            TOTP, SMS, passkeys, and backup codes.
          </li>
          <li>
            <strong>Role-based access control:</strong> Staff access is restricted based on assigned
            roles and permissions.
          </li>
          <li>
            <strong>Hosted entirely in New Zealand:</strong> All servers, databases, and application
            infrastructure are located in New Zealand. No data leaves New Zealand.
          </li>
        </ul>
        <p className="text-gray-700">
          We regularly review our security practices and take reasonable steps to protect personal
          information from unauthorised access, use, modification, disclosure, or loss.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  8. IPP 6 — Access to Personal Information                    */}
      {/* ============================================================ */}
      <section id="ipp-6" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          8. IPP 6 — Access to Personal Information
        </h2>
        <p className="mb-4 text-gray-700">
          You have the right to access the personal information we hold about you. You can do this
          by:
        </p>
        <ol className="mb-4 list-decimal space-y-2 pl-6 text-gray-700">
          <li>
            <strong>Self-service:</strong> Using the platform's Data Import/Export feature to export
            your data in CSV format.
          </li>
          <li>
            <strong>Direct request:</strong> Contacting our Privacy Officer at{' '}
            <a
              href="mailto:privacy@oraflows.co.nz"
              className="text-blue-600 underline hover:text-blue-500"
            >
              privacy@oraflows.co.nz
            </a>{' '}
            to request a copy of your personal information.
          </li>
        </ol>
        <p className="text-gray-700">
          We will respond to access requests within 20 working days, as required by the Privacy Act
          2020.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  9. IPP 7 — Correction of Personal Information                */}
      {/* ============================================================ */}
      <section id="ipp-7" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          9. IPP 7 — Correction of Personal Information
        </h2>
        <p className="mb-4 text-gray-700">
          You have the right to request correction of any personal information we hold about you
          that is inaccurate, incomplete, or misleading. You can correct your information by:
        </p>
        <ol className="mb-4 list-decimal space-y-2 pl-6 text-gray-700">
          <li>
            <strong>Self-service:</strong> Editing your profile, customer records, or other data
            directly through the OraInvoice platform interface.
          </li>
          <li>
            <strong>Direct request:</strong> Contacting our Privacy Officer at{' '}
            <a
              href="mailto:privacy@oraflows.co.nz"
              className="text-blue-600 underline hover:text-blue-500"
            >
              privacy@oraflows.co.nz
            </a>{' '}
            to request a correction.
          </li>
        </ol>
        <p className="text-gray-700">
          If we decline a correction request, we will attach a statement of the correction sought
          but not made to the information.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  10. IPP 8 — Accuracy of Information                          */}
      {/* ============================================================ */}
      <section id="ipp-8" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          10. IPP 8 — Accuracy of Information
        </h2>
        <p className="text-gray-700">
          OraInvoice takes reasonable steps to ensure that personal information is accurate, up to
          date, complete, and not misleading before it is used or disclosed. Users are encouraged to
          keep their account information current. Vehicle data retrieved from CarJam is sourced from
          the NZ Transport Agency (Waka Kotahi) database and is considered authoritative at the time
          of retrieval.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  11. IPP 9 — Retention of Personal Information                */}
      {/* ============================================================ */}
      <section id="ipp-9" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          11. IPP 9 — Retention of Personal Information
        </h2>
        <p className="mb-4 text-gray-700">
          We retain personal information only for as long as necessary to fulfil the purposes for
          which it was collected, or as required by law. Specifically:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>
            <strong>Active accounts:</strong> Data is retained for the duration of the account's
            active subscription.
          </li>
          <li>
            <strong>Closed accounts:</strong> Upon account closure or deletion request, personal
            data is deleted within 30 business days, except where retention is required by law.
          </li>
          <li>
            <strong>Financial records:</strong> Invoice and transaction records may be retained for
            up to 7 years as required by New Zealand tax law (Tax Administration Act 1994).
          </li>
          <li>
            <strong>Audit logs:</strong> Security and access logs are retained for 12 months for
            security and compliance purposes.
          </li>
        </ul>
        <p className="text-gray-700">
          We do not retain personal information longer than is necessary for the purpose for which
          it was collected.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  12. IPP 10 — Limits on Use                                   */}
      {/* ============================================================ */}
      <section id="ipp-10" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          12. IPP 10 — Limits on Use
        </h2>
        <p className="mb-4 text-gray-700">
          Personal information collected by OraInvoice is used only for the purpose for which it was
          collected, or a directly related purpose that the individual would reasonably expect. We do
          not use your data for:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>Targeted advertising or marketing to third parties</li>
          <li>Selling or renting personal information to any third party</li>
          <li>Profiling or automated decision-making that affects your rights</li>
          <li>Any purpose unrelated to the provision of our business management services</li>
        </ul>
      </section>

      {/* ============================================================ */}
      {/*  13. IPP 11 — Limits on Disclosure                            */}
      {/* ============================================================ */}
      <section id="ipp-11" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          13. IPP 11 — Limits on Disclosure
        </h2>
        <p className="mb-4 text-gray-700">
          OraInvoice may disclose personal information to the following third parties, only as
          necessary to provide our services:
        </p>
        <ol className="mb-4 list-decimal space-y-3 pl-6 text-gray-700">
          <li>
            <strong>Stripe</strong> — Payment processing. When you or your customers make payments
            through OraInvoice, payment tokens and transaction data are shared with Stripe to
            process the payment. Stripe operates under its own privacy policy.
          </li>
          <li>
            <strong>CarJam</strong> — Vehicle lookups. When a user performs a vehicle lookup,
            the registration number is sent to CarJam to retrieve vehicle details. CarJam operates
            under its own privacy policy.
          </li>
          <li>
            <strong>Xero</strong> — Accounting synchronisation. When the Xero integration is
            enabled by the user, invoice and contact data is synchronised with the user's Xero
            account. Xero operates under its own privacy policy.
          </li>
          <li>
            <strong>Connexus</strong> — SMS notifications. When SMS notifications are enabled,
            phone numbers and message content are shared with Connexus to deliver SMS messages.
            Connexus operates under its own privacy policy.
          </li>
        </ol>
        <p className="text-gray-700">
          We do not disclose personal information to any other third parties unless required by law,
          or with the explicit consent of the individual.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  14. IPP 12 — Cross-Border Transfers                          */}
      {/* ============================================================ */}
      <section id="ipp-12" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          14. IPP 12 — Cross-Border Transfers
        </h2>
        <p className="mb-4 text-gray-700">
          OraInvoice does <strong>not</strong> transfer any personal data outside New Zealand. All
          data, including the application itself, is hosted entirely within New Zealand.
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>All servers and databases are located in New Zealand.</li>
          <li>The application infrastructure runs entirely within New Zealand.</li>
          <li>
            Payment processing via Stripe uses Stripe's New Zealand infrastructure.
          </li>
          <li>No cross-border data transfers occur.</li>
        </ul>
        <p className="text-gray-700">
          This ensures full compliance with IPP 12 of the NZ Privacy Act 2020 regarding
          cross-border disclosure of personal information.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  15. IPP 13 — Unique Identifiers                              */}
      {/* ============================================================ */}
      <section id="ipp-13" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">
          15. IPP 13 — Unique Identifiers
        </h2>
        <p className="mb-4 text-gray-700">
          OraInvoice assigns internal UUIDs (Universally Unique Identifiers) to users, customers,
          invoices, and other records for system purposes. These identifiers are:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>Generated randomly and are not derived from personal information.</li>
          <li>Used solely for internal system identification and database relationships.</li>
          <li>Not shared with third parties as identifiers.</li>
        </ul>
        <p className="text-gray-700">
          OraInvoice does not use government-issued identifiers (such as IRD numbers, driver licence
          numbers, or passport numbers) as primary keys or unique identifiers within the system.
        </p>
      </section>

      {/* ============================================================ */}
      {/*  16. Breach Notification                                      */}
      {/* ============================================================ */}
      <section id="breach-notification" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">16. Breach Notification</h2>
        <p className="mb-4 text-gray-700">
          In the event of a privacy breach, OraInvoice will act in accordance with Part 6 of the NZ
          Privacy Act 2020:
        </p>
        <ol className="mb-4 list-decimal space-y-3 pl-6 text-gray-700">
          <li>
            <strong>Notification to the Privacy Commissioner:</strong> We will notify the Office of
            the Privacy Commissioner of any notifiable privacy breach as soon as practicable after
            becoming aware of the breach.
          </li>
          <li>
            <strong>Notification to affected individuals:</strong> If a breach is likely to cause
            serious harm to affected individuals, we will notify those individuals as soon as
            practicable. The notification will include:
            <ul className="mt-2 list-disc space-y-1 pl-6">
              <li>The nature of the breach</li>
              <li>The personal information involved</li>
              <li>Steps we are taking to respond to the breach</li>
              <li>Steps the individual can take to protect themselves</li>
            </ul>
          </li>
          <li>
            <strong>Timeframe:</strong> Breach notifications will be made as soon as practicable
            after we become aware of the breach, and in any case within the timeframes required by
            the Privacy Act 2020.
          </li>
        </ol>
      </section>

      {/* ============================================================ */}
      {/*  17. Data Portability and Deletion                            */}
      {/* ============================================================ */}
      <section id="data-portability" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">17. Data Portability and Deletion</h2>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Data Export</h3>
        <p className="mb-4 text-gray-700">
          You can export your data in CSV format at any time using the platform's Data Import/Export
          feature. This includes invoices, customers, job cards, inventory, and other business data.
        </p>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Account Deletion</h3>
        <p className="mb-4 text-gray-700">
          You can request deletion of your account and all associated data by contacting our Privacy
          Officer at{' '}
          <a
            href="mailto:privacy@oraflows.co.nz"
            className="text-blue-600 underline hover:text-blue-500"
          >
            privacy@oraflows.co.nz
          </a>
          .
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>
            Deletion requests will be processed within <strong>30 business days</strong>.
          </li>
          <li>
            Upon deletion, all personal information and business data will be permanently removed
            from our systems.
          </li>
          <li>
            <strong>Exception:</strong> Financial transaction records (invoices, payment records) may
            be retained for up to 7 years as required by New Zealand tax law (Tax Administration Act
            1994). These records will be anonymised where possible.
          </li>
        </ul>
      </section>

      {/* ============================================================ */}
      {/*  18. Children's Data                                          */}
      {/* ============================================================ */}
      <section id="children" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">18. Children&apos;s Data</h2>
        <p className="mb-4 text-gray-700">
          OraInvoice is a business-to-business platform designed for trade businesses and their
          staff. It is not intended for use by individuals under 16 years of age.
        </p>
        <p className="mb-4 text-gray-700">
          We do not knowingly collect personal information from children under 16. If we become
          aware that personal information has been collected from a child under 16, we will take
          steps to delete that information promptly.
        </p>
        <p className="text-gray-700">
          If you believe that a child's personal information has been provided to OraInvoice, please
          contact our Privacy Officer immediately at{' '}
          <a
            href="mailto:privacy@oraflows.co.nz"
            className="text-blue-600 underline hover:text-blue-500"
          >
            privacy@oraflows.co.nz
          </a>
          .
        </p>
      </section>

      {/* ============================================================ */}
      {/*  19. Data Sovereignty                                         */}
      {/* ============================================================ */}
      <section id="data-sovereignty" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">19. Data Sovereignty</h2>
        <p className="mb-4 text-gray-700">
          OraInvoice is committed to keeping all data within New Zealand:
        </p>
        <ul className="mb-4 list-disc space-y-2 pl-6 text-gray-700">
          <li>
            All servers, databases, and application infrastructure are located in New Zealand.
          </li>
          <li>
            No personal or business data is transferred to, stored in, or processed in any country
            outside New Zealand.
          </li>
          <li>
            Oraflows Limited is a New Zealand registered company and operates under New Zealand law.
          </li>
          <li>
            Our commitment to data sovereignty means you can trust that your business information
            remains protected under New Zealand's privacy and data protection framework.
          </li>
        </ul>
      </section>

      {/* ============================================================ */}
      {/*  20. Contact and Complaints                                   */}
      {/* ============================================================ */}
      <section id="contact" className="mb-10 scroll-mt-20">
        <h2 className="mb-4 text-2xl font-bold text-gray-900">20. Contact and Complaints</h2>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Privacy Officer</h3>
        <p className="mb-4 text-gray-700">
          For any privacy enquiries, access requests, correction requests, or complaints, please
          contact our Privacy Officer:
        </p>
        <div className="mb-6 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <p className="font-semibold text-gray-900">Privacy Officer</p>
          <p className="text-gray-700">Oraflows Limited</p>
          <p className="text-gray-700">
            Email:{' '}
            <a
              href="mailto:privacy@oraflows.co.nz"
              className="text-blue-600 underline hover:text-blue-500"
            >
              privacy@oraflows.co.nz
            </a>
          </p>
        </div>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">About Oraflows Limited</h3>
        <p className="mb-4 text-gray-700">
          OraInvoice is operated by Oraflows Limited, a locally owned New Zealand registered
          company. We are committed to protecting the privacy of our users and their customers in
          accordance with the NZ Privacy Act 2020.
        </p>

        <h3 className="mb-2 mt-6 text-xl font-semibold text-gray-900">Making a Complaint</h3>
        <p className="mb-4 text-gray-700">
          If you believe your privacy has been breached, you can make a complaint to our Privacy
          Officer using the contact details above. We will investigate your complaint and respond
          within 20 working days.
        </p>
        <p className="text-gray-700">
          If your complaint is not resolved to your satisfaction, you have the right to escalate
          your complaint to the Office of the Privacy Commissioner:
        </p>
        <div className="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <p className="font-semibold text-gray-900">Office of the Privacy Commissioner</p>
          <p className="text-gray-700">
            Website:{' '}
            <a
              href="https://privacy.org.nz"
              className="text-blue-600 underline hover:text-blue-500"
              target="_blank"
              rel="noopener noreferrer"
            >
              privacy.org.nz
            </a>
          </p>
        </div>
      </section>
    </article>
  )
}
