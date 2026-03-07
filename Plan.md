WorkshopPro NZ — SaaS Platform: Software Development Plan

Version 1.0 | March 2026

NOte: all notification or any type remiders should be easy to configure not automatic , in my plan may it says automatica it refers to once enabled then auomatic until disabled need password recovery options as well

1\. Product Overview

WorkshopPro is a New Zealand-focused SaaS invoicing and business management platform built specifically for workshops, garages, and service stations. It operates on a multi-tenant subscription model with modular features, enabling each subscribing organisation to configure the platform to their own branding, services, and billing needs.



2\. System Architecture Overview

The platform will be structured across three tiers:

Global Admin Layer — manages all organisations, billing, integrations (Carjam, Stripe, SMTP, SMS), storage quotas, and subscription plans.

Organisation Layer — each workshop has its own isolated data space with configurable branding, services, and user roles.

End User Layer — Org Admin and Salesperson roles interact with customers, vehicles, invoices, and payments.



3\. Module Overview

All features are built as independently deployable modules:



Authentication \& User Management

Organisation Management \& Settings

Customer Management

Vehicle \& Carjam Integration

Invoice Management

Payment Processing (Cash + Stripe)

Service \& Parts Catalogue

Storage \& Document Management

Notifications (Email \& SMS)

Subscription \& Billing (Global)

Reporting \& Analytics

Global Admin Console





4\. User Roles

Global Admin — Anthropic-level access. Manages all orgs, Carjam integration, global Stripe, SMTP/SMS config, storage pricing, subscription plans, and Carjam usage billing per org.

Org Admin — Manages their own organisation's branding, services, user accounts, storage, billing view, and settings.

Salesperson — Creates customers, vehicles, invoices. Takes payments. Emails invoices. Cannot access org settings.



5\. Module Detail

5.1 Authentication \& User Management



Secure login with email + password (JWT-based sessions)

Password reset via email

Multi-org support (a user belongs to one org)

Role-based access control (Global Admin / Org Admin / Salesperson)

Session timeout and audit logging of login activity



Gap identified: You'll need email verification on account creation and a mechanism for Global Admin to invite Org Admins when provisioning a new organisation.



5.2 Organisation Management



Each org has: name, logo, address, GST number, GST percentage (default 15%), contact details, custom invoice branding (colours, header/footer text)

Org Admin can configure all the above from Settings

Org is provisioned by Global Admin upon subscription activation

Each org has a unique subdomain or ID for data isolation



Gap identified: You need an onboarding flow — when a new workshop signs up, they go through a setup wizard (branding, GST, first service types) before going live.



5.3 Customer Management



Search existing customers by name, phone, email while creating an invoice

If found, auto-populate; if not, prompt to create inline

Customer fields: first name, last name, email, phone, optional address

After creating customer, optionally add a vehicle to their profile

Customer profile shows full invoice history





5.4 Vehicle \& Carjam Integration



Rego lookup triggers automatically when rego is typed

System checks Global Vehicle Database first — if found, no API call is made and the org is not charged

If not in global database, Carjam API is called, data is stored in Global Vehicle Database, and the org's Carjam usage counter increments

Vehicle data stored: make, model, year, colour, body type, fuel type, odometer (if available), WOF/registration expiry

Carjam is configured only at Global Admin level (single API key)

Carjam usage per org is tracked and can be billed separately as an add-on charge

Each org can see their Carjam lookup count in their billing dashboard



Gap identified: You need a manual vehicle entry fallback for cases where Carjam returns no result or the vehicle is not NZ-registered. Also consider a "refresh vehicle data" button to re-pull from Carjam if data is stale.



5.5 Invoice Management

Invoice creation flow:



Salesperson starts a new invoice

Selects or creates customer

Types rego → vehicle auto-populated

Adds line items (services, parts, labour)

Reviews totals (ex-GST, GST amount, GST-inclusive total)

Sends or saves



Invoice line items:



Predefined services (WOF, COF, Standard Service, Premium Service) — configured by Org Admin in settings

Custom line items: description, quantity, unit price

Parts: description, part number (optional), quantity, unit price

Warranty notes (optional free text field per line item)



Invoice fields:



Invoice number (auto-incremented, configurable prefix per org e.g. INV-0001)

Issue date, due date

Customer info

Vehicle info (rego, make, model, year, odometer at time of service)

Line items with GST

Payment status: Unpaid / Paid / Partially Paid

Payment method: Cash / Stripe

Notes field (internal and customer-facing)

Custom branding (logo, colours, footer)



Search: Invoices can be searched by invoice number, rego, customer name, phone, or email.

Gap identified: You need an invoice status for "Overdue" with configurable payment terms (e.g. 7 days, 14 days, 30 days). Also consider a "Draft" status so salespeople can save mid-creation without issuing the invoice yet.

Gap identified: There is no mention of credit notes or invoice cancellation. Workshops will need to be able to void or partially credit an invoice — this is critical for accounting integrity.



5.6 Payment Processing



Cash payments: Salesperson marks as paid manually, records date

Stripe payments: Org configures their own Stripe keys in org settings; payment link sent to customer or processed in-person via Stripe terminal (future phase)

Payment confirmation triggers invoice status update and email receipt to customer

Partial payments supported (deposit scenarios)



Gap identified: Stripe requires organisations to connect their own Stripe account. You'll need a Stripe Connect integration so orgs can onboard their own Stripe within your platform, rather than managing their keys manually (which creates compliance risk).



5.7 Service \& Parts Catalogue (Org Admin Settings)



Org Admin can create service types: name, description, default price, GST applicable yes/no

Examples: WOF ($69), COF ($120), Standard Service ($149), Premium Service ($249), Brake Pad Replacement (variable)

Services appear as selectable items when creating an invoice

Parts are ad-hoc per invoice but can optionally be saved to a parts catalogue

All prices are editable per invoice line (override the default)





5.8 Storage \& Document Management



Invoices stored as compressed JSON in the database; PDF is rendered on-demand in browser

Customer receives a PDF version via email

Each org has a storage quota assigned based on their plan (e.g. Starter: 5GB, Pro: 20GB, Enterprise: 100GB)

At 80% usage: yellow warning shown in dashboard

At 90% usage: prominent red warning, emails sent to Org Admin

At 100%: invoice creation blocked until storage is increased or old invoices are deleted

Dashboard shows: current usage, estimated invoices remaining based on average compressed size, plan limit

Org Admin can purchase additional storage as an add-on (e.g. +5GB for $X/month)

Storage add-on is billed immediately via Stripe, added to next monthly invoice, and takes effect instantly

Global Admin can configure storage tier pricing and default quotas per plan



Gap identified: You need a bulk invoice archive or export feature — so orgs can export and locally store old invoices then delete them from the platform to free up space, without losing records.



5.9 Notifications Module

Email:



Global SMTP or relay configured by Global Admin (e.g. Brevo/SendGrid)

Orgs can optionally configure their own sender name and reply-to address

Invoice email template is customisable per org (logo, colours, footer, body text)

Triggers: Invoice issued, Payment received, Payment overdue reminder, Storage warning, Subscription billing



SMS:



Global Twilio or Firebase configured by Global Admin

Orgs can opt in and configure SMS reminders

SMS templates editable per org

Triggers: Invoice issued (optional), Payment overdue reminder, WOF/registration expiry reminder (future feature)



Gap identified: You mentioned reminders but haven't defined a reminder schedule. You need configurable reminder rules — e.g. send overdue reminder at 3 days, 7 days, 14 days after due date. This should be configurable per org.

Gap identified: WOF expiry reminders are an obvious high-value feature for workshops since you're already storing WOF expiry dates from Carjam. A scheduled job to notify customers X days before WOF expiry would be a strong selling point.



5.10 Subscription \& Billing (Global)



Global Admin configures subscription plans: name, price, features, storage quota, Carjam lookup limit, user seats

Orgs are billed monthly via Global Admin's Stripe account

Subscription billing is fully automated (Stripe Subscriptions/Billing)

Add-ons (extra storage, Carjam usage overage) are metered and added to the monthly invoice automatically

Org Admin has a Billing page showing: current plan, next invoice date, estimated next invoice amount, usage summary, payment method management

Global Admin has a view of all orgs, their plan, billing status, and overdue accounts



Gap identified: You need a free trial or grace period mechanism for new orgs signing up. Also define what happens if an org's payment fails — grace period, feature lockdown, data retention period before deletion.

Gap identified: You need a plan upgrade/downgrade flow that is self-serve from Org Admin settings, with proration handled by Stripe.



5.11 Reporting \& Analytics

Org-level reports:



Revenue by period (daily, weekly, monthly, yearly)

Invoice count and average invoice value

Top services by revenue

Outstanding/overdue invoice report

GST summary report (for filing with IRD)

Carjam usage report



Global Admin reports:



Total MRR (monthly recurring revenue)

Org-level revenue and usage

Carjam API cost vs billable usage per org

Storage usage across all orgs

Churn and new subscriber tracking



Gap identified: For NZ workshops, a GST return summary report (showing total sales, GST collected, GST periods) is essential. This should be exportable as PDF or CSV.



5.12 Global Admin Console



Manage all organisations (create, suspend, delete)

Configure Carjam API key and monitor usage per org

Configure global Stripe (platform billing)

Configure global SMTP/SMS settings

Set subscription plans and pricing

Set storage pricing and quotas

View Global Vehicle Database (size, lookup count, most searched regos)

View platform-wide error logs and health status

Manually trigger billing events or apply credits to orgs





6\. Gaps \& Improvements Summary

Here are all the additional gaps identified beyond what you described:

Accounting \& Compliance



Credit notes and invoice voiding (essential for GST compliance)

GST return summary report for IRD filing

Audit trail / change log on invoices (who modified what and when)

Invoice number sequencing must be tamper-evident and contiguous for accounting compliance



Customer \& Vehicle



Manual vehicle entry fallback when Carjam returns no result

Stale data refresh button for vehicle records

WOF/registration expiry reminders to customers (high-value feature)

Vehicle service history view per rego (all invoices across time for that vehicle)



Invoicing



Draft invoice status (save before issuing)

Overdue status with configurable payment terms

Invoice duplication/template feature (for repeat jobs)

Bulk invoice actions (mark multiple as paid, export)



Payments



Stripe Connect for org-level payment setup (safer than manual key entry)

Refund handling tied to credit notes



Subscriptions \& Billing



Free trial period for new signups

Payment failure handling with grace period and dunning emails

Self-serve plan upgrade/downgrade with proration

Invoice history for orgs to download their own subscription invoices



Notifications



Configurable overdue reminder schedule per org

Email delivery status tracking (sent, delivered, bounced, opened)



Storage



Bulk export and archive old invoices before deletion

Per-org storage usage graph over time



Security \& Compliance



GDPR/Privacy Act 2020 compliance (right to access, right to deletion for customer records)

Two-factor authentication option for Org Admin accounts

IP-based login alerting for unusual access





7\. Suggested Development Phases

Phase 1 — MVP (Months 1–4)

Core authentication, org setup, customer management, Carjam integration, invoice creation, cash payments, PDF generation, basic email sending, Global Admin console.

Phase 2 — Payments \& Billing (Months 5–6)

Stripe Connect for orgs, Global Stripe subscription billing, storage quotas and enforcement, storage add-on purchasing, Carjam usage billing.

Phase 3 — Notifications \& Reporting (Months 7–8)

SMS integration, notification templates per org, overdue reminders, GST report, revenue reports, Global Admin analytics.

Phase 4 — Polish \& Growth Features (Months 9–12)

WOF expiry reminders, invoice templates/duplication, vehicle service history, two-factor authentication, mobile-optimised UI, self-serve plan management, audit trails.



8\. Tech Stack Recommendations

Backend: FastAPI (Python) — suits your existing expertise

Frontend: React with Tailwind CSS

Database: PostgreSQL (per-org schema isolation or row-level tenancy)

Global Vehicle DB: Shared PostgreSQL table with caching layer (Redis)

File Storage: Compressed JSON in database; PDF generated server-side on demand (e.g. WeasyPrint or Puppeteer)

Payments: Stripe (Stripe Connect for orgs, Stripe Subscriptions for platform billing)

Email: Brevo (transactional) or SendGrid with global SMTP fallback

SMS: Twilio

Hosting: Start with your existing Pi infrastructure for non-financial layers; use managed Postgres (Supabase or Railway) for financial data

Auth: JWT with refresh tokens; consider Supabase Auth or roll your own



This plan covers your original spec plus all identified gaps. The next step would be to turn this into a detailed technical specification with database schema, API endpoint design, and UI wireframes per module.dont tell me gaps fill the gaps dont tell me phases or anything i need info till your 6 points . with gap filled and you are right we need MFA settings sms based TOTP and email based code. multi MFA software . passkey login. login with google option . any other security features or admin features for this kind of app needs to be added . frontend needs to be compatible with all the devices configurable terms and conditons or payment terms global admin needs to have comphresive error logging to speciically collect erros if any . needs to use postgres DB it should frinedly GUI and easy to use like what apple does with OS and its devices that kind of approach18:09Check frontend design skillCheck frontend design skillThis is going to be a large, thorough document. Let me write it all out properly.Ran 3 commands, created a fileRan 3 commands, created a fileCheck docx skill filesScriptCheck scripts availableScriptCopy scripts to working directoryScriptGenerate the comprehensive software development plan documentjavascriptconst {

&nbsp; Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,

&nbsp; HeadingLevel, AlignmentType, BorderStyle, WidthType, ShadingType,

&nbsp; LevelFormat, Header, Footer, TabStopType, TabStopPosition, PageNumber

} = require('docx');

const fs = require('fs');



const C = {

&nbsp; primary: '0F2D52',

&nbsp; accent: '1565C0',

&nbsp; accentLight: '1976D2',

&nbsp; highlight: '0288D1',

&nbsp; light: 'E3F2FD',

&nbsp; mid: 'BBDEFB',

&nbsp; green: '2E7D32',

&nbsp; greenLight: 'E8F5E9',

&nbsp; orange: Claude's response was interruptedRetrywhy again writing code just give me in txt18:10You're right, sorry. Here it is.



WorkshopPro NZ — SaaS Platform: Software Development Plan

Version 2.0 | March 2026



1\. Product Overview

WorkshopPro is a New Zealand-focused SaaS invoicing and business management platform built specifically for workshops, garages, and service stations. It operates on a multi-tenant subscription model where each subscribing organisation gets their own isolated environment with custom branding, GST configuration, service catalogues, and billing. The platform is designed with an Apple-like philosophy — every interaction should feel obvious, fast, and frictionless. No training manual should be needed. Every screen, every flow, every error message is written in plain language, and the UI adapts perfectly to any device from a desktop monitor to a mobile phone used at a service counter.

The platform is built as a collection of independently deployable modules so features can be enabled, disabled, or extended per organisation plan without affecting the core system. PostgreSQL is the sole database engine across the platform, used for all relational data, structured JSON storage, audit logs, and vehicle records.



2\. System Architecture Overview

The platform operates across three distinct tiers, each with clear responsibilities and access boundaries.

The Global Admin Layer is operated exclusively by the platform owner. It manages all organisations, global integrations (Carjam, Stripe, SMTP, SMS, error logging), subscription plans, storage pricing, and platform health. Global Admins never interact with org-level invoice or customer data directly — they manage infrastructure and billing only.

The Organisation Layer is the workshop environment. Each organisation is fully isolated with its own branding, service catalogue, user accounts, customers, vehicles, invoices, and billing view. Org Admins configure the environment; Salespeople operate within it.

The End User Layer consists of two roles per organisation — Org Admin and Salesperson — each with clearly scoped permissions so a salesperson can never accidentally change pricing structures or billing settings.

The entire frontend is a single responsive React application that renders correctly and comfortably on desktop, tablet, and mobile. No feature is hidden or degraded on smaller screens. The layout reflows intelligently so a salesperson can create a full invoice on a phone at the workshop counter without pinching or zooming. Touch targets are large, forms are single-column on mobile, and critical actions like "Issue Invoice" and "Mark as Paid" are always thumb-reachable.

The backend is FastAPI (Python), connecting to a single PostgreSQL cluster. Tenant isolation is enforced at the row level using organisation IDs on every table, with database-level row security policies as a secondary enforcement layer. Redis is used for session caching and Carjam lookup rate limiting. PDF invoices are generated server-side on demand and never stored as files — only the structured JSON data is persisted, compressed in PostgreSQL. PDFs are rendered in the browser from that JSON and emailed as generated attachments.



3\. Module Overview

The platform is composed of the following modules, each independently configurable per organisation plan:



Authentication, Security \& Identity

Organisation Management \& Branding

Customer Management

Vehicle Management \& Carjam Integration

Invoice Management

Payment Processing

Service \& Parts Catalogue

Storage \& Document Management

Notifications (Email \& SMS)

Subscription \& Billing

Reporting \& Analytics

Global Admin Console \& Error Logging





4\. User Roles \& Permissions

Global Admin is the platform owner role. There can be multiple Global Admins. They access a completely separate admin portal (not the same interface as org users). They configure Carjam, global Stripe, SMTP, Twilio, error logging, subscription plans, storage tiers, and org provisioning. They can view aggregate usage data across all organisations but cannot read individual customer or invoice records. Global Admin accounts require MFA — no exceptions.

Org Admin manages a single organisation. They configure branding, GST settings, payment terms, service catalogue, user accounts, notification templates, storage purchases, and can view their own billing and subscription status. They have full access to all invoices and customers within their org. They can also perform everything a Salesperson can.

Salesperson creates and manages customers, vehicles, and invoices. They can issue invoices, record payments, email invoices to customers, and search existing records. They cannot access org settings, billing, user management, or service catalogue configuration.

Permission enforcement happens at both the API level (every endpoint checks role and org membership) and the UI level (restricted menu items and actions are completely hidden, not just greyed out, so the interface never confuses salespeople with options they cannot use).



5\. Module Detail

5.1 Authentication, Security \& Identity

The authentication system is designed to be as secure as a banking application while feeling as simple as signing into an Apple device. Every method of authentication is available and configurable.

Login Methods

Users can authenticate via standard email and password, Google OAuth (Sign in with Google), or a hardware/biometric Passkey using the WebAuthn standard. Passkeys allow a salesperson to log in with Face ID, Touch ID, or a device PIN — no password required. This is the recommended login method for workshop floor use on tablets or mobile devices. Google OAuth is ideal for organisations already using Google Workspace. All three methods can coexist for the same user account.

Multi-Factor Authentication

MFA is configurable per organisation by the Org Admin and is mandatory for all Global Admin accounts. The following MFA methods are supported and users can enrol in more than one, with a fallback chain if the primary method is unavailable:

TOTP (Time-based One-Time Password) via any authenticator app such as Google Authenticator, Authy, or 1Password. The user scans a QR code during setup and enters a 6-digit rotating code at login.

SMS-based OTP where a 6-digit code is sent to the user's registered mobile number via Twilio. This uses the same global Twilio integration as the notification module.

Email-based OTP where a 6-digit code is sent to the user's registered email address. This uses the same global SMTP integration as the notification module.

Passkeys inherently satisfy MFA because they combine possession (the device) with biometric or PIN verification, so a user logging in with a Passkey is not prompted for a second factor.

Org Admins can configure MFA as optional or mandatory for their organisation. If mandatory, users who have not enrolled are redirected to MFA setup on their next login and cannot access the application until setup is complete. Backup codes (a set of 10 single-use recovery codes) are generated at MFA enrolment and can be downloaded or printed. These allow account recovery if all MFA methods are unavailable.

Session Management

Sessions are JWT-based with short-lived access tokens (15 minutes) and longer-lived refresh tokens (7 days for standard sessions, 30 days if the user selects "Remember this device"). Refresh tokens are rotated on every use and stored securely in an httpOnly cookie. If a refresh token is used more than once (indicating theft), the entire session family is invalidated immediately and the user is notified by email.

Concurrent session limits can be configured per organisation. By default, a user can have up to 5 active sessions across devices. A user can view all active sessions in their profile settings and remotely terminate any of them.

Account Security

Login attempts are rate-limited. After 5 failed attempts the account is temporarily locked for 15 minutes. After 10 failed attempts a manual unlock email is sent to the user. Org Admins can also manually lock and unlock user accounts instantly.

Every successful and failed login is logged with timestamp, IP address, device type, and browser. Unusual login events — such as a new country, a new device, or a login at an unusual time — trigger an email alert to the user with a "This wasn't me" link that instantly revokes that session and locks the account.

Password requirements enforce a minimum of 12 characters with complexity rules. Passwords are checked against a database of known breached passwords (using the HaveIBeenPwned API with k-anonymity so the actual password is never transmitted). Users are notified if their password appears in a known breach and are prompted to change it.

Configurable Terms \& Conditions and Payment Terms

Global Admin sets platform-wide terms and conditions that all users agree to on first login and whenever updated. Org Admins set their own payment terms (e.g. payment due within 7, 14, or 30 days, or a custom number of days) that appear on every invoice. Org Admins can also write a custom terms and conditions block that appears at the bottom of every invoice PDF sent to their customers. Both the platform T\&C and the org-level invoice T\&C support rich text editing with headings, bold, bullet lists, and links so they can be formatted professionally.

Additional Security Features

IP allowlisting is available as an optional setting per organisation. Org Admins can restrict logins to specific IP ranges (useful for orgs that only want staff to log in from the workshop network or a known VPN).

HTTPS is enforced across all endpoints with HSTS headers. All API responses include appropriate security headers (Content-Security-Policy, X-Frame-Options, X-Content-Type-Options). CSRF protection is applied to all state-changing endpoints.

All data at rest in PostgreSQL is encrypted using AES-256. All data in transit uses TLS 1.3. Carjam API keys, Stripe keys, Twilio credentials, and SMTP passwords are stored encrypted in the database using envelope encryption — they are never logged, never returned in API responses, and only decrypted server-side at the moment of use.

A complete, tamper-evident audit log records every action taken by every user in the system. Each log entry captures: who did it, what they did, what changed (before and after values for edits), when it happened, and from what IP and device. Audit logs are append-only at the database level — no application code can delete or modify them. Org Admins can view their own org's audit log. Global Admins can view platform-wide logs. The audit log is the foundation of the error logging system described in Section 5.12.



5.2 Organisation Management \& Branding

Each organisation on the platform is a fully self-contained workspace. When a new organisation is provisioned by Global Admin, an Org Admin account is created and an onboarding wizard guides the Org Admin through the following setup steps before the workspace goes live: organisation name and contact details, logo upload, brand colour selection, GST number entry, GST percentage (defaulting to 15%), invoice numbering prefix and starting number, default payment terms, and adding at least one service type.

The onboarding wizard uses a clean step-by-step interface — one screen per step, a visible progress indicator, and clear plain-language prompts. Any step can be skipped and completed later from Settings. The workspace is usable immediately after the wizard regardless of completion state.

Organisation Settings covers everything the Org Admin can configure:

Branding — logo (PNG or SVG, shown on all invoice PDFs and in the application header), primary colour, secondary colour, invoice header text, invoice footer text, and a custom email signature used in all outgoing emails from this org.

GST Configuration — GST number (validated against the IRD format), GST percentage, and a toggle to show prices as GST-inclusive or GST-exclusive by default on invoices.

Invoice Settings — invoice number prefix (e.g. "INV-", "WS-", "AUTO-"), starting invoice number, default due date (number of days from issue date), default notes (pre-filled on every new invoice but editable per invoice), and whether to show the vehicle details section on invoices.

Payment Terms — the payment due period in days, a custom payment terms statement that appears on invoice PDFs, and whether to allow partial payments.

User Management — Org Admins can invite new users via email, assign them as Org Admin or Salesperson, and deactivate accounts. Invited users receive an email with a secure signup link valid for 48 hours. Org Admins can also configure whether MFA is optional or mandatory for all users in their org.

Multi-location support is built in from the start even if not immediately used — each organisation can have multiple branch locations (e.g. a workshop group with three sites). Each branch has its own address and phone number which appears on invoices for jobs done at that branch. Users can be assigned to one or more branches.



5.3 Customer Management

Customers exist within an organisation and are never shared across organisations. Every customer record contains: first name, last name, email address, phone number, optional physical address, and an internal notes field for the org's use. Customer records are linked to their vehicle(s) and their full invoice history is visible on their profile.

When a Salesperson starts a new invoice, they type into a customer search field. The search is live and queries against name, phone number, and email simultaneously. Results appear as a dropdown as the user types — showing the customer name, phone, and email so they can identify the right person quickly even with a common name. If no match is found, a clearly visible "Create new customer" option appears directly in the dropdown — clicking it opens a minimal inline form (first name, last name, email, phone, optional address) without leaving the invoice creation flow. After the customer is created they are instantly linked to the invoice and the search field updates to show them.

Customers can be tagged with a vehicle during creation or at any time from their profile. On the customer profile page, Org Admins and Salespeople can see all vehicles linked to that customer, the full invoice history across all those vehicles, total spend, and outstanding balance. They can also send a one-off email or SMS directly from the customer profile.

Customer records can be merged if duplicates are created accidentally. Merging combines invoice history, vehicles, and contact details into a single record, with a confirmation screen showing exactly what will be combined before the action is committed.

For Privacy Act 2020 compliance, any customer can request deletion of their record. The Org Admin can process this from the customer profile. Invoice records linked to that customer are anonymised rather than deleted (the customer name is replaced with "Anonymised Customer" and contact details are cleared) so financial records remain intact for accounting purposes while personal data is removed.



5.4 Vehicle Management \& Carjam Integration

Global Vehicle Database

Every vehicle lookup result from Carjam is stored permanently in a shared PostgreSQL table accessible to all organisations on the platform. This table is owned at the global level and is never part of any org's isolated data. When any user on any org types a rego number, the system checks this global table first. If a match is found, the vehicle data is returned instantly and the org's Carjam usage counter is not incremented — it costs them nothing. Only if the rego is not in the global database does the system make a live Carjam API call, store the result in the global database, and increment that org's Carjam usage counter.

This shared caching approach means that popular vehicles (fleet vehicles, common NZ models, vehicles serviced across multiple workshops) are almost always already in the database, dramatically reducing real API costs across the platform.

The global vehicle record stores: rego, make, model, year, colour, body type, fuel type, engine size, number of seats, current WOF expiry date, current registration expiry date, odometer at last recorded point, and the timestamp of when the data was last pulled from Carjam. A "refresh" button is available on any vehicle record for users who suspect the data is stale — clicking it forces a new Carjam API call, updates the global record, and charges the org for one lookup.

Vehicle Linking

Vehicles in the global database are linked to customer records within each org's workspace. The same global vehicle record can be linked to different customers across different orgs without conflict — each org sees only their own customer-vehicle associations. Within a single org, a vehicle can be linked to multiple customers (e.g. a family sharing a car).

If Carjam returns no result for a rego (unregistered vehicle, motorbike not covered, import not yet registered), the user is presented with a clean manual entry form to input make, model, year, colour, and any other known details. Manually entered vehicles are stored in the org's own vehicle records rather than the global database and are clearly marked as "manually entered" so users know the data was not verified.

Vehicle Profile

Each vehicle has a profile page within the org showing: all Carjam data, the customer(s) it is linked to, odometer at each service visit (pulled from invoice entries), full service history (all invoices for that rego in chronological order), and upcoming WOF and registration expiry dates with a visual indicator (green for more than 60 days, amber for 30–60 days, red for under 30 days or expired).

Carjam Usage Monitoring

The Global Admin console shows a real-time table of Carjam API usage broken down by organisation: total lookups this month, lookups included in their plan, overage lookups, and the overage charge being accrued. This overage is automatically added to the org's next monthly Stripe invoice. Org Admins can see their own Carjam usage on their billing dashboard so they are never surprised by the charge.



5.5 Invoice Management

Invoice Creation Flow

Creating an invoice is designed to be a fast, single-screen experience. The form is laid out in a logical top-to-bottom flow that mirrors how a service advisor naturally works: first the customer, then the vehicle, then what was done, then the total, then payment. On desktop the form is a clean two-column layout. On mobile it collapses to a single column with large touch-friendly inputs.

The flow: the user searches for or creates a customer, then types the vehicle rego which auto-populates all vehicle fields, then adds line items from the service catalogue or as custom entries, then reviews the auto-calculated totals, then issues the invoice or saves it as a draft.

Invoice Statuses

Draft — saved but not yet issued. Not visible to the customer. Can be edited freely. Does not consume invoice number until issued.

Issued — formally created with an assigned invoice number. Sent or ready to send to the customer. Locked from structural edits (items, pricing) but notes can be updated.

Partially Paid — one or more payments have been recorded but the balance is not yet cleared.

Paid — balance is fully cleared.

Overdue — issued invoice whose due date has passed with no payment or incomplete payment. Status updates automatically at midnight on the due date.

Voided — cancelled invoice. The invoice number is retained in sequence for accounting integrity but the invoice is marked void and excluded from revenue reporting. A reason for voiding is required and recorded in the audit log.

Invoice Fields

Every invoice contains: auto-assigned sequential invoice number with org prefix, issue date, due date (auto-calculated from org's default payment terms, editable per invoice), customer name and contact details, vehicle rego, make, model, year, and odometer at time of service (editable on the invoice regardless of what Carjam holds), line items, subtotal excluding GST, GST amount, GST-inclusive total, payment status, payment history, org branding (logo, colours, footer), and the org's payment terms and T\&C text.

Line Items

Each line item has a type: Service, Part, or Labour. Service items are selected from the org's service catalogue (WOF, COF, Standard Service, etc.) with the catalogue price pre-filled but fully editable. Part items have a description field, an optional part number field, quantity, and unit price. Labour items have a description, hours, and hourly rate. Any line item can have a warranty note attached — a free-text field that appears under that line on the invoice PDF (e.g. "12 month / 12,000km warranty on parts supplied").

GST is calculated automatically on all applicable line items. Individual line items can be marked as GST-exempt if needed (e.g. a third-party charge being passed through).

Discounts can be applied per line item as a percentage or fixed amount, or as an invoice-level discount applied to the subtotal.

Credit Notes

When a Paid or Issued invoice needs to be corrected or refunded, a Credit Note is raised against it rather than editing the original. The Credit Note is a separate document linked to the original invoice, with its own reference number (e.g. CN-0001 linked to INV-0047), showing what is being credited and why. The system automatically updates the net balance on the original invoice and adjusts revenue reporting to reflect the credit. If a Stripe payment was involved, the credit note flow prompts the user to process a refund through Stripe for the credited amount.

Invoice Search

The invoice search page allows searching across: invoice number, rego, customer name, customer phone, customer email, and date range. Results load instantly as the user types. Filters can be stacked (e.g. show all overdue invoices for a specific rego). Search results show the invoice number, customer name, rego, total, status, and issue date in a clean scannable list.

Invoice Duplication

Any invoice can be duplicated with one click to create a new draft pre-filled with the same customer, vehicle, and line items. Useful for repeat services or recurring jobs. The duplicate starts as a Draft with a new (not yet assigned) invoice number.



5.6 Payment Processing

Cash Payments

The Salesperson clicks "Record Payment", selects Cash as the method, enters the amount received (which can be partial), and the system records the payment with a timestamp and the user who recorded it. If the amount clears the balance the invoice moves to Paid. If partial, it moves to Partially Paid and the outstanding balance is shown clearly.

Stripe Payments

Each organisation connects their own Stripe account using Stripe Connect. This is done from the Org Admin settings page with a single "Connect Stripe Account" button that redirects the Org Admin through Stripe's secure OAuth flow. Once connected, the org can accept card payments. The platform never handles raw card data — all card input is handled by Stripe's hosted fields (Stripe.js) embedded in the payment form.

When an invoice is ready for card payment, the Salesperson can either generate a payment link (a secure URL sent to the customer via email or SMS that opens a branded payment page) or process the payment in person using a Stripe payment terminal if the org has one configured. Payment confirmation is instant — the invoice status updates in real time via a webhook from Stripe, and a payment receipt is automatically emailed to the customer.

Payment History

Every invoice shows a full payment history: each payment recorded with date, amount, method, and the user who recorded it. This is visible to both Org Admin and Salesperson and is included in the audit log.

Refunds

Refunds for Stripe payments are initiated from the Credit Note flow or directly from the invoice's payment history. The refund is processed via the Stripe API and the invoice balance is updated. Refunds for cash payments are recorded manually with a note.



5.7 Service \& Parts Catalogue

The service catalogue is configured per organisation by the Org Admin. It is the master list of services that can be added to invoices.

Each service entry contains: service name, description, default price (ex-GST), GST applicability toggle, service category (e.g. Warrant, Service, Repair, Diagnostic), and an active/inactive toggle (inactive services are hidden from the invoice creation form but retained for historical invoice display).

Typical entries for a NZ workshop would include: Warrant of Fitness ($69), Certificate of Fitness ($120), Standard Service ($149), Premium Service ($249), Oil Change ($89), Tyre Rotation ($45), Brake Inspection ($65) — all configurable to the org's actual pricing.

When a Salesperson adds a service to an invoice, the catalogue price populates automatically but is editable on the invoice. The catalogue price is never locked — workshops frequently price jobs based on the specific vehicle or customer.

A parts catalogue is optional. Orgs can pre-load common parts (filters, belts, fluids) with a default price and part number, which then auto-fill when selected in an invoice line item. Parts can also be added ad-hoc per invoice without pre-loading.

Labour rates can be configured per org (e.g. standard labour rate $120/hr, specialist rate $160/hr) and selected when adding a Labour line item to an invoice.



5.8 Storage \& Document Management

Invoices are stored in the PostgreSQL database as compressed JSON objects. No PDF files are stored on disk or in object storage. When a user views an invoice or emails it to a customer, the PDF is generated on-the-fly server-side from the JSON data using a templating engine, returned as a binary stream, and never written to permanent storage. This means every invoice PDF always reflects the current org branding even if the logo or colours were updated after the invoice was created.

Each organisation is assigned a storage quota based on their subscription plan. Storage is calculated from the total size of all compressed invoice JSON records, customer records, and vehicle records belonging to that org. Logos and branding assets are stored separately and do not count toward the quota.

At 80% of quota, a persistent but non-intrusive amber banner appears at the top of the dashboard for Org Admin users and an email notification is sent to all Org Admins.

At 90% of quota, the amber banner becomes a prominent red alert visible to all users in the org (not just Org Admin), and an urgent email is sent to all Org Admins. The alert includes the current usage, the limit, an estimated number of additional invoices that can still be created before the limit is reached (calculated from the org's average invoice JSON size), and a direct button to purchase additional storage.

At 100% of quota, invoice creation is blocked. All other functionality continues. A full-page interstitial is shown to Salespeople explaining that the storage limit has been reached and prompting them to contact their Org Admin. Org Admins see the same interstitial with the option to purchase more storage immediately.

Storage add-ons are purchased by the Org Admin from the Billing page. Available increments are configurable by Global Admin (e.g. +5GB, +20GB, +50GB) with their corresponding monthly prices. When the Org Admin clicks to purchase an add-on, a confirmation dialog shows the exact additional monthly charge and the new total monthly cost. On confirmation, the Stripe charge is applied immediately to the org's stored payment method, the quota is increased instantly, and a confirmation email is sent. The add-on cost is added as a line item on the next monthly subscription invoice so the org's billing is consolidated.

Org Admins can bulk-export invoices (as a ZIP of individual PDFs or a single CSV of invoice data) filtered by date range, then permanently delete those invoices from the platform to free up space. The deletion requires a confirmation step showing exactly how many invoices will be deleted and how much space will be recovered. Deleted invoices are irrecoverable. The export-then-delete workflow is presented as the recommended approach with clear guidance so orgs never accidentally delete records they still need.



5.9 Notifications Module

All notification sending is handled by a dedicated notification service that queues and dispatches messages asynchronously. Failed sends are retried up to 3 times with exponential backoff. After 3 failures the notification is marked as failed and the failure is logged in the Global Admin error log with full details (recipient, template, error message from the sending provider).

Email

Global Admin configures a single platform-wide SMTP or email relay (e.g. Brevo, SendGrid, or any SMTP server) used as the sending infrastructure for all orgs. Each org's emails appear to come from their own configured sender name and reply-to address even though they route through the global sending infrastructure.

Each organisation can customise all email templates from their Settings. Templates use a visual block editor (not raw HTML) with drag-and-drop sections for logo, header text, body text, and footer. Template variables (e.g. {{customer\_first\_name}}, {{invoice\_number}}, {{total\_due}}, {{due\_date}}, {{payment\_link}}) are available and documented in the editor with a preview mode showing a rendered example.

The following email templates are available per org: Invoice Issued, Payment Received, Payment Overdue Reminder, Invoice Voided, Storage Warning (80%), Storage Critical (90%), Storage Full (100%), Subscription Renewal Reminder, Subscription Payment Failed, WOF Expiry Reminder, Registration Expiry Reminder, User Invitation, Password Reset, MFA Enrolment, Login Alert (new device or location), and Account Locked.

Every sent email is logged with: recipient address, template used, timestamp, delivery status (queued, sent, delivered, bounced, opened if supported by provider), and the rendered subject line. Org Admins can see the email log for their org to confirm invoices were received. Bounced or failed email addresses are flagged on the customer record with a warning so the Salesperson knows to use a different contact method.

SMS

Global Admin configures Twilio credentials in the Global Settings. SMS is an optional feature that each org can enable or disable from their settings. Orgs configure their sender name or number and can edit SMS templates using a simple text editor with the same variable system as email templates.

SMS templates available per org: Invoice Issued (with a short payment link), Payment Overdue Reminder, WOF Expiry Reminder, and Registration Expiry Reminder. SMS messages are kept under 160 characters where possible and the system warns the editor if a template exceeds this limit. Sent SMS messages are logged similarly to emails.

Automated Reminders

Overdue payment reminders are scheduled automatically based on each org's configured reminder schedule. Orgs can set up to three reminder rules (e.g. send reminder 3 days after due date, again at 7 days, again at 14 days). Each reminder rule can be set to send via email, SMS, or both. Reminder rules are configured in the Notifications section of Org Settings with a simple interface: rule 1 — X days after due date — email and/or SMS. Reminders are not sent to invoices that have been voided or fully paid.

WOF and registration expiry reminders are sent to the customer linked to a vehicle where the expiry date is approaching. Orgs configure how many days in advance to send these (default 30 days). These reminders include the vehicle rego, what is expiring, the expiry date, and the workshop's contact details. WOF and registration expiry reminders can be toggled on or off per org.



5.10 Subscription \& Billing

Plans

Global Admin creates and manages subscription plans from the Global Admin console. Each plan defines: plan name, monthly price (NZD), number of user seats included, storage quota, Carjam lookups included per month, and which feature modules are enabled. Plans can be marked as public (visible on the signup page) or private (only assignable by Global Admin, for custom enterprise arrangements).

Example plan structure: Starter (1–3 users, 5GB storage, 100 Carjam lookups/month), Professional (1–10 users, 20GB storage, 500 Carjam lookups/month), Enterprise (unlimited users, 100GB storage, 2,000 Carjam lookups/month, custom pricing). All configurable by Global Admin without a code deployment.

New Organisation Signup

The public-facing signup page allows a new workshop to select a plan, create their Org Admin account, and enter payment details. A 14-day free trial is available on all plans — credit card details are collected upfront (Stripe SetupIntent) but not charged until the trial ends. A trial countdown is visible in the Org Admin dashboard. At the end of the trial, the first charge is automatically processed. Three days before the trial ends, a reminder email is sent.

Billing Lifecycle

Subscriptions are managed via Stripe Subscriptions. Billing runs monthly on the anniversary of the org's signup date. The monthly invoice includes: the base plan fee, any storage add-ons, and any Carjam overage charges accrued that month (metered via Stripe metered billing). Org Admins receive the Stripe-generated invoice PDF by email and can view all past invoices from their Billing page.

If a payment fails, Stripe automatically retries according to the platform's configured retry schedule (immediately, then 3 days, then 7 days). Concurrently, dunning emails are sent to the Org Admin at each retry. If payment is not recovered after the final retry (14 days), the org's account enters a grace period of 7 days where the org can still log in and view data but cannot create new invoices or process payments. After the grace period the org is suspended — users can log in and see a suspension notice but cannot access any functionality. Data is retained for 90 days after suspension before permanent deletion, with warning emails sent at 30 days and 7 days remaining.

Plan Changes

Org Admins can upgrade or downgrade their plan at any time from the Billing page. Upgrades take effect immediately with prorated charges applied to the current billing period. Downgrades take effect at the start of the next billing period. If a downgrade would leave the org over the new plan's storage or user limit, a clear warning is shown listing exactly what would need to be resolved before the downgrade can proceed.

Org Admin Billing Dashboard

The Billing page within Org Admin settings shows: current plan name and features, next billing date, estimated next invoice amount (broken down into plan fee, storage add-ons, and accrued Carjam usage), current storage usage with a visual bar and estimated invoices remaining, current Carjam usage this month versus the plan's included amount, all past invoices with download links, and the option to update the payment method. Everything is in plain language — no accounting jargon.



5.11 Reporting \& Analytics

All reports load quickly and are designed with the same clean visual language as the rest of the application. Charts are simple, readable, and mobile-friendly. Every report can be exported as a PDF or CSV.

Org-Level Reports available to Org Admin:

Revenue Summary — total revenue for a selected period (day, week, month, quarter, year or custom range), broken down by service category. Shown as a bar chart and a summary table.

Invoice Status Report — count and value of invoices in each status (Draft, Issued, Partially Paid, Paid, Overdue, Voided) for a selected period.

Outstanding Invoices — a list of all unpaid and partially paid invoices, sortable by amount due and days overdue, with a one-click button to send a payment reminder for any invoice on the list.

Top Services Report — the ten highest-revenue service types in a selected period, by total revenue and by invoice count.

Vehicle Service History — all invoices for a specific rego, in date order, showing what was done and what was charged each visit.

Customer Statement — a printable or emailable PDF statement for a specific customer showing all invoices and payments in a date range, with the outstanding balance. Useful for account customers.

GST Return Summary — total sales, total GST collected, and net GST for any date range. Exportable as a PDF formatted to support manual IRD GST return filing. Separate columns for standard-rated and zero-rated items.

Carjam Usage Report — monthly Carjam lookup count, included lookups, overage lookups, and estimated overage charge.

Storage Report — storage usage over time as a simple line graph, current usage versus quota, and a table of the largest invoice records.

Global Admin Reports:

Platform MRR — total monthly recurring revenue across all organisations, with a breakdown by plan type and a month-over-month trend line.

Organisation Overview — a table of all organisations showing plan, signup date, trial status, billing status, storage usage, Carjam usage this month, and last login date for any user in that org.

Carjam Cost vs Revenue — total Carjam API cost incurred by the platform versus total Carjam overage billed to orgs, showing the net position.

Global Vehicle Database Stats — total vehicle records in the global database, total lookups served from cache (no API call) versus lookups that required a Carjam API call, cache hit rate percentage.

Churn Report — organisations that cancelled or were suspended in a date range, with plan type and the subscription duration at time of cancellation.

Error Summary — a high-level view of system errors in a date range, categorised by module, with a drill-down to the full error log (covered in Section 5.12).



5.12 Global Admin Console \& Error Logging

The Global Admin console is a completely separate application from the org-facing platform. It is accessible only to accounts with the Global Admin role and requires MFA on every login regardless of device trust state.

Organisation Management

Global Admin can: view all organisations in a sortable and searchable table, provision a new organisation (creates the org record, assigns a plan, generates an Org Admin invitation email), suspend an organisation immediately (useful for payment issues or terms violations), reinstate a suspended organisation, permanently delete an organisation with a multi-step confirmation process, and move an organisation between plans.

When suspending or deleting an organisation, the Global Admin must enter a reason which is stored in the audit log and can optionally be included in the automated email sent to the Org Admin.

Global Integrations Configuration

All third-party integrations are configured in a dedicated Integrations section of the Global Admin console. Each integration has its own configuration page with a connection test button that verifies the credentials are valid before saving.

Carjam — API key, endpoint URL, per-lookup cost (used to calculate the platform's cost vs billed revenue), and a global rate limit (maximum API calls per minute across the entire platform to prevent accidental runaway usage).

Global Stripe — the platform's own Stripe account for collecting subscription fees. Webhook endpoint configuration and signing secret management are handled here.

SMTP / Email — provider selection (Brevo, SendGrid, or custom SMTP), API key or SMTP credentials, sending domain, from name, and reply-to address. A test email button sends a real email to the Global Admin's address to confirm delivery.

Twilio — account SID, auth token, and default sender number. A test SMS button sends a real SMS to a number the Global Admin enters.

Error Logging

The error logging system captures every exception, integration failure, background job failure, and unexpected application state across the entire platform. It is the operational heartbeat of the platform and is designed so the Global Admin can quickly identify, understand, and resolve any issue without needing to dig through server logs.

Every error record contains: a unique error ID, timestamp, severity level (Info, Warning, Error, Critical), the module and function where the error occurred, the full stack trace, the organisation ID and user ID involved (if applicable — some errors are system-level with no org context), the HTTP request details (method, endpoint, sanitised request body with secrets redacted), the error message in plain English, and the system's automatic categorisation of the error type.

Errors are categorised into: Payment Errors (Stripe webhook failures, charge failures, refund errors), Integration Errors (Carjam API failures, Twilio send failures, SMTP failures), Storage Errors (quota enforcement failures, PDF generation failures), Authentication Errors (JWT failures, MFA failures, OAuth errors), Data Errors (validation failures, constraint violations, unexpected null values), Background Job Errors (reminder scheduling failures, invoice status update job failures), and Application Errors (uncaught exceptions, timeout errors, anything else).

The error log dashboard displays: a real-time count of errors in the last hour, 24 hours, and 7 days broken down by severity and category, a live feed of the most recent errors with colour-coded severity (red for Critical, orange for Error, yellow for Warning, blue for Info), and a search and filter interface allowing Global Admin to filter by organisation, severity, category, date range, and keyword.

Critical errors (those that affect an org's ability to invoice or accept payments) trigger an immediate push notification to all logged-in Global Admin users in the console and an email alert to all Global Admin email addresses, so issues are never missed.

Each error record has a detail view showing the full stack trace in a clean formatted code block, the context (which org, which user, what they were doing), the raw request and response if applicable, and a status field (Open, Investigating, Resolved) with a notes field where Global Admin can document what was done to fix it. This turns the error log into a lightweight incident management system.

Errors are retained in the database for 12 months before being automatically archived. Global Admin can export error logs in CSV or JSON format for any date range.

Global Settings

Beyond integrations, the Global Admin console manages: subscription plan definitions (create, edit, archive plans), storage tier pricing (price per GB per month for storage add-ons), the global vehicle database (view record count, search any rego, force-refresh a record from Carjam, delete stale records), platform-wide terms and conditions (with version history — whenever updated, all users are prompted to re-accept on next login), and the platform announcement banner (a global notice that appears for all org users, used for maintenance notices or feature announcements).



6\. Security, Compliance \& Data Governance Summary

The platform is built with security as a structural property rather than an add-on. Every module is designed with the principle of least privilege — users and systems only access what they need for the task at hand, nothing more.

Data residency is New Zealand. All PostgreSQL instances, application servers, and backup storage are hosted in NZ or Australian data centres to satisfy Privacy Act 2020 obligations. Backup retention is 30 days with point-in-time recovery available to the minute. Backups are encrypted and stored in a geographically separate location from primary data.

All personally identifiable information (customer names, email addresses, phone numbers, physical addresses) is treated as sensitive data throughout the codebase. It is never written to application logs. It is never included in error reports sent to external services. It is never cached without encryption. API responses are filtered so only the data required for the requesting user's role is returned.

The platform is designed to be compliant with the New Zealand Privacy Act 2020. This includes: a documented data retention policy (configurable by Global Admin), the ability to fulfil customer data access requests (Org Admin can export all data for a specific customer in JSON format), the ability to fulfil erasure requests (as described in Section 5.3), a privacy policy and data processing agreement available to all subscribing organisations, and an internal record of all data processing activities.

Security assessments including penetration testing are recommended prior to public launch and at least annually thereafter. The modular architecture and clean separation between global and org data makes these assessments straightforward to scope and conduct.  

