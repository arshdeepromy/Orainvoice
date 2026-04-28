# Requirements Document

## Introduction

OraInvoice currently redirects unauthenticated visitors at `/` straight to `/login`, offering no public-facing information about the product. This feature adds a professional marketing landing page at `/` for unauthenticated users, showcasing OraInvoice as a purpose-built invoicing and business management platform for automotive small-to-medium businesses. The landing page highlights the "Mech Pro Plan" feature set, includes clear calls-to-action for signup and login, and links to a dedicated Privacy Policy page at `/privacy` that satisfies the NZ Privacy Act 2020.

The landing page and privacy page are new React components and routes within the existing SPA. The landing page also fetches branding information from a public backend API endpoint and supports a "Request Free Demo" flow that submits to a public backend endpoint which sends an email via the configured SMTP provider. Both public pages are accessible without authentication and use the existing Tailwind CSS setup with no additional CSS frameworks.

## Glossary

- **Landing_Page**: The public-facing marketing page rendered at `/` for unauthenticated visitors, showcasing OraInvoice features and pricing.
- **Privacy_Page**: The public-facing privacy policy page rendered at `/privacy`, detailing how OraInvoice handles personal and business data under the NZ Privacy Act 2020.
- **Landing_Header**: The top navigation bar on public pages containing the OraInvoice logo, navigation links, and Login/Signup buttons.
- **Hero_Section**: The prominent top section of the Landing_Page containing the primary headline, subheadline, and call-to-action buttons.
- **Feature_Section**: A section of the Landing_Page that displays a group of related product features with icons and descriptions.
- **Pricing_Card**: A UI card on the Landing_Page that displays the Mech Pro Plan name, price, and included features.
- **Testimonial_Section**: A section of the Landing_Page displaying customer testimonials (placeholder content for initial release).
- **CTA_Section**: A call-to-action section with a prominent button encouraging visitors to sign up.
- **Landing_Footer**: The bottom section of public pages containing links to Privacy Policy, Terms, Contact, and copyright information.
- **Mech_Pro_Plan**: The primary subscription plan for automotive businesses, bundling all automotive-relevant modules.
- **IPP**: Information Privacy Principle — one of the 13 principles defined in the NZ Privacy Act 2020 governing how agencies collect, store, use, and disclose personal information.
- **Privacy_Officer**: The designated contact person responsible for handling privacy enquiries and complaints under the NZ Privacy Act 2020.
- **Unauthenticated_Visitor**: A user who has not logged in and has no active session.
- **Authenticated_User**: A user with an active session (JWT token present).
- **Branding_API**: The public backend API endpoint (e.g., `GET /api/v1/public/branding`) that returns platform branding information (logo URL, platform name) configured by the global admin.
- **Demo_Request_API**: The public backend API endpoint (e.g., `POST /api/v1/public/demo-request`) that accepts demo request form submissions and sends an email notification to the Oraflows team.
- **Demo_Request_Form**: A modal popup form on the Landing_Page that collects visitor details (name, business name, email, phone, message) for requesting a free demo.
- **Oraflows_Limited**: The New Zealand registered company that owns and operates the OraInvoice platform.
- **Trades_Page**: The public-facing page rendered at `/trades` that lists all supported trade industries with their availability status (Available, Coming Soon).

## Requirements

### Requirement 1: Public Route for Landing Page

**User Story:** As an unauthenticated visitor, I want to see a marketing page when I visit the root URL, so that I can learn about OraInvoice before deciding to sign up or log in.

#### Acceptance Criteria

1. WHEN an Unauthenticated_Visitor navigates to `/`, THE Landing_Page SHALL render the public marketing page.
2. WHEN an Authenticated_User navigates to `/`, THE Landing_Page SHALL redirect to `/dashboard` for org-level users or `/admin/dashboard` for global admin users, preserving the existing authenticated routing behaviour.
3. THE Landing_Page SHALL be accessible without authentication and SHALL NOT require a JWT token.
4. THE Landing_Page SHALL be a new React component registered as a route in the existing `App.tsx` routing configuration.
5. WHEN an Unauthenticated_Visitor navigates to `/privacy`, THE Privacy_Page SHALL render the privacy policy page without requiring authentication.
6. WHEN an Unauthenticated_Visitor navigates to `/trades`, THE Trades_Page SHALL render the supported trades page without requiring authentication.

### Requirement 2: Landing Page Header

**User Story:** As a visitor, I want a clear navigation header with login and signup options, so that I can quickly access the app if I already have an account or want to create one.

#### Acceptance Criteria

1. THE Landing_Header SHALL display the OraInvoice logo or brand name on the left side.
2. THE Landing_Header SHALL display a "Login" button that navigates to `/login` when clicked.
3. THE Landing_Header SHALL display a "Sign Up" button that navigates to `/signup` when clicked.
4. THE Landing_Header SHALL use a dark background with a gradient or solid colour that contrasts with the page content.
5. THE Landing_Header SHALL remain visible at the top of the viewport as the user scrolls (sticky positioning).
6. THE Landing_Header SHALL be responsive, adapting its layout for viewports narrower than 768 pixels by collapsing navigation items into a mobile menu.
7. THE Landing_Header SHALL fetch branding information (logo URL, platform name) from the Global Admin branding settings via the public branding API endpoint, so that the landing page reflects the branding configured by the global admin.
8. THE Landing_Header SHALL include navigation links to "Features" (anchor scroll on Landing_Page), "Trades" (`/trades`), "Pricing" (anchor scroll on Landing_Page), and "Privacy" (`/privacy`).

### Requirement 3: Hero Section

**User Story:** As a visitor, I want to immediately understand what OraInvoice does and who it is for, so that I can decide if it is relevant to my business.

#### Acceptance Criteria

1. THE Hero_Section SHALL display a primary headline that communicates OraInvoice is built for automotive businesses.
2. THE Hero_Section SHALL display a subheadline that summarises the key value proposition (invoicing, job management, and business operations for workshops).
3. THE Hero_Section SHALL display a primary call-to-action button labelled "Get Started" or equivalent that navigates to `/signup`.
4. THE Hero_Section SHALL display a secondary call-to-action link labelled "Learn More" or equivalent that scrolls to the Feature_Section.
5. THE Hero_Section SHALL use a dark background with a gradient to create visual contrast with subsequent sections.
6. THE Hero_Section SHALL be responsive, stacking content vertically on viewports narrower than 768 pixels.

### Requirement 4: Feature Sections

**User Story:** As a visitor, I want to see all the features included in the Mech Pro Plan organised by category, so that I can understand the full scope of what OraInvoice offers for my automotive business.

#### Acceptance Criteria

1. THE Landing_Page SHALL display Feature_Sections grouped into the following categories: Core, Automotive-Specific, Sales and Quoting, Operations, Inventory, Finance, Compliance, and Additional.
2. EACH Feature_Section SHALL display a category heading and a list of features belonging to that category.
3. EACH feature item SHALL display an icon, a feature name, and a one-to-two sentence description of the feature.
4. THE Feature_Sections SHALL include the following features at minimum: Invoicing, Customer Management, Notifications, Vehicle Database (with CarJam integration mention), Job Cards, Service Types, Quotes and Estimates, Bookings and Appointments, Scheduling, Staff Management, Time Tracking, Inventory and Products, Purchase Orders, Items Catalogue, Recurring Invoices, Multi-Currency, Online Payments, Accounting, Expenses, Compliance Documents, Reports, Data Import/Export, Customer Portal, Mobile App, Multi-Branch, and MFA Security.
5. THE Feature_Sections SHALL use a grid or card layout that displays two or three feature items per row on viewports wider than 1024 pixels and one item per row on viewports narrower than 768 pixels.
6. EACH Feature_Section SHALL use alternating background colours (white and light grey) to visually separate categories.

### Requirement 5: Pricing Card

**User Story:** As a visitor, I want to see the pricing for the Mech Pro Plan with a clear list of what is included, so that I can evaluate the cost before signing up.

#### Acceptance Criteria

1. THE Landing_Page SHALL display a Pricing_Card for the Mech Pro Plan.
2. THE Pricing_Card SHALL display the plan name "Mech Pro Plan".
3. THE Pricing_Card SHALL display a placeholder price (e.g., "$99/month + GST") with a code comment indicating the price should be updated from the database or configuration.
4. THE Pricing_Card SHALL display a list of key included features as bullet points or checkmarks.
5. THE Pricing_Card SHALL display a call-to-action button labelled "Start Free Trial" or equivalent that navigates to `/signup`.
6. THE Pricing_Card SHALL use a visually prominent design (elevated card, border highlight, or background colour) to draw attention.
7. THE Pricing_Card SHALL display a note indicating that pricing is in NZD and excludes GST.
8. THE Pricing_Card SHALL display a "Request Free Demo" button alongside the existing signup CTA.

### Requirement 6: Testimonials Section

**User Story:** As a visitor, I want to see what other automotive businesses think of OraInvoice, so that I can build confidence in the product.

#### Acceptance Criteria

1. THE Landing_Page SHALL display a Testimonial_Section with placeholder testimonial content.
2. THE Testimonial_Section SHALL display at least three placeholder testimonials, each containing a quote, a name, and a business name.
3. THE Testimonial_Section SHALL include a code comment indicating that testimonial content should be replaced with real customer testimonials.
4. THE Testimonial_Section SHALL use a card or blockquote layout with visual quotation marks or icons.

### Requirement 7: Call-to-Action Section

**User Story:** As a visitor who has scrolled through the features, I want a final prompt to sign up, so that I have a clear next step after reviewing the product.

#### Acceptance Criteria

1. THE Landing_Page SHALL display a CTA_Section near the bottom of the page, above the Landing_Footer.
2. THE CTA_Section SHALL display a compelling heading encouraging the visitor to get started.
3. THE CTA_Section SHALL display a primary button that navigates to `/signup`.
4. THE CTA_Section SHALL use a dark or gradient background to visually distinguish it from the preceding content.

### Requirement 8: Landing Page Footer

**User Story:** As a visitor, I want a footer with links to important pages like the privacy policy, so that I can find legal and contact information.

#### Acceptance Criteria

1. THE Landing_Footer SHALL display a link to the Privacy_Page at `/privacy`.
2. THE Landing_Footer SHALL display a link labelled "Terms of Service" (placeholder — can link to `/privacy` or a future `/terms` route).
3. THE Landing_Footer SHALL display contact information or a "Contact Us" link.
4. THE Landing_Footer SHALL display a copyright notice with the current year and "OraInvoice" or "Oraflows Ltd".
5. THE Landing_Footer SHALL be responsive, stacking columns vertically on viewports narrower than 768 pixels.

### Requirement 9: Privacy Policy Page — Structure and Accessibility

**User Story:** As a visitor, I want to read a clearly structured privacy policy, so that I understand how my data is handled before I sign up.

#### Acceptance Criteria

1. THE Privacy_Page SHALL be rendered at the `/privacy` route as a standalone public page.
2. THE Privacy_Page SHALL display the Landing_Header at the top with Login and Signup buttons.
3. THE Privacy_Page SHALL display the Landing_Footer at the bottom.
4. THE Privacy_Page SHALL display a "Last Updated" date at the top of the policy content.
5. THE Privacy_Page SHALL use a table of contents or anchor links at the top that link to each major section of the policy.
6. THE Privacy_Page SHALL use clear headings, numbered lists, and readable typography (maximum content width of 768 pixels, minimum body font size of 16 pixels).

### Requirement 10: Privacy Policy — Data Collection Disclosure

**User Story:** As a visitor, I want to know exactly what data OraInvoice collects, so that I can make an informed decision about using the platform.

#### Acceptance Criteria

1. THE Privacy_Page SHALL list all categories of personal information collected: name, email address, phone number, business name, and business address.
2. THE Privacy_Page SHALL list all categories of business data collected: invoices, quotes, job cards, customer records, vehicle records, staff records, inventory records, financial transactions, and accounting data.
3. THE Privacy_Page SHALL list all categories of vehicle data collected: registration number, make, model, year, VIN, odometer readings, WOF expiry, and registration expiry.
4. THE Privacy_Page SHALL list all categories of payment data collected: Stripe payment tokens and transaction records, noting that full card numbers are not stored by OraInvoice.
5. THE Privacy_Page SHALL list all categories of technical data collected: IP addresses, browser type, JWT session tokens, and login timestamps.
6. THE Privacy_Page SHALL state that OraInvoice does not use third-party tracking cookies.

### Requirement 11: Privacy Policy — NZ Privacy Act 2020 Information Privacy Principles

**User Story:** As a New Zealand business owner, I want the privacy policy to address all 13 Information Privacy Principles, so that I know OraInvoice complies with NZ law.

#### Acceptance Criteria

1. THE Privacy_Page SHALL address IPP 1 (Purpose of collection) by stating the specific purposes for which personal information is collected.
2. THE Privacy_Page SHALL address IPP 2 (Source of information) by stating that information is collected directly from the individual or their authorised representative.
3. THE Privacy_Page SHALL address IPP 3 (Collection of information from subject) by stating that individuals are informed at the time of collection about the purpose, intended recipients, and consequences of not providing the information.
4. THE Privacy_Page SHALL address IPP 4 (Manner of collection) by stating that information is collected by lawful means that are fair and not unreasonably intrusive.
5. THE Privacy_Page SHALL address IPP 5 (Storage and security) by stating that data is encrypted at rest, stored in PostgreSQL with row-level security, and hosted entirely in New Zealand. No data leaves New Zealand.
6. THE Privacy_Page SHALL address IPP 6 (Access to personal information) by stating that users can access their personal information through the platform's data export functionality or by contacting the Privacy_Officer.
7. THE Privacy_Page SHALL address IPP 7 (Correction of personal information) by stating that users can correct their personal information through the platform interface or by contacting the Privacy_Officer.
8. THE Privacy_Page SHALL address IPP 8 (Accuracy of information) by stating that OraInvoice takes reasonable steps to ensure personal information is accurate, up to date, and not misleading before use.
9. THE Privacy_Page SHALL address IPP 9 (Retention of personal information) by stating the data retention period and that data is not kept longer than necessary for the purpose it was collected.
10. THE Privacy_Page SHALL address IPP 10 (Limits on use) by stating that personal information is used only for the purpose for which it was collected or a directly related purpose.
11. THE Privacy_Page SHALL address IPP 11 (Limits on disclosure) by listing all third parties to whom data may be disclosed: Stripe (payment processing), CarJam (vehicle lookups), Xero (accounting sync), and Connexus (SMS notifications).
12. THE Privacy_Page SHALL address IPP 12 (Cross-border transfers) by stating that OraInvoice does NOT transfer any personal data outside New Zealand. All data, including the application itself, is hosted in New Zealand. Payment processing via Stripe uses Stripe's NZ infrastructure. No cross-border data transfers occur.
13. THE Privacy_Page SHALL address IPP 13 (Unique identifiers) by stating that OraInvoice assigns internal UUIDs for system purposes and does not use government-issued identifiers as primary keys.

### Requirement 12: Privacy Policy — Breach Notification

**User Story:** As a user, I want to know how OraInvoice will handle a data breach, so that I can trust the platform to act responsibly if my data is compromised.

#### Acceptance Criteria

1. THE Privacy_Page SHALL state that OraInvoice will notify the Office of the Privacy Commissioner of any notifiable privacy breach as required by Part 6 of the NZ Privacy Act 2020.
2. THE Privacy_Page SHALL state that affected individuals will be notified of a breach that is likely to cause serious harm, including the nature of the breach, the information involved, and steps being taken to respond.
3. THE Privacy_Page SHALL state the expected timeframe for breach notification (as soon as practicable after becoming aware of the breach).

### Requirement 13: Privacy Policy — Data Portability and Deletion

**User Story:** As a user, I want to know that I can export or delete my data, so that I retain control over my information.

#### Acceptance Criteria

1. THE Privacy_Page SHALL state that users can export their data in CSV format using the platform's Data Import/Export feature.
2. THE Privacy_Page SHALL state that users can request deletion of their account and associated data by contacting the Privacy_Officer.
3. THE Privacy_Page SHALL state the expected timeframe for processing deletion requests (e.g., within 30 business days).
4. THE Privacy_Page SHALL state any data that may be retained after deletion for legal or regulatory purposes (e.g., financial transaction records required by NZ tax law).

### Requirement 14: Privacy Policy — Contact and Complaints

**User Story:** As a user, I want to know how to contact the privacy officer and how to make a complaint, so that I have a clear path for resolving privacy concerns.

#### Acceptance Criteria

1. THE Privacy_Page SHALL display the title "Privacy Officer" and the contact email address privacy@oraflows.co.nz (or arshdeep.romy@gmail.com as interim) for privacy enquiries.
2. THE Privacy_Page SHALL state that OraInvoice is operated by Oraflows Limited, a locally owned New Zealand registered company.
3. THE Privacy_Page SHALL state that users can make a complaint to the Privacy_Officer if they believe their privacy has been breached.
4. THE Privacy_Page SHALL state that if the complaint is not resolved satisfactorily, the user can escalate to the Office of the Privacy Commissioner at privacy.org.nz.

### Requirement 15: Responsive Design and Visual Quality

**User Story:** As a visitor on any device, I want the landing page to look professional and be easy to navigate, so that I have confidence in the product.

#### Acceptance Criteria

1. THE Landing_Page SHALL be fully responsive across viewports from 320 pixels to 1920 pixels wide.
2. THE Landing_Page SHALL use only the existing Tailwind CSS setup with no additional CSS frameworks or libraries.
3. THE Landing_Page SHALL use a consistent colour palette with dark tones for the header, hero, and CTA sections, and light tones for feature and content sections.
4. THE Landing_Page SHALL use smooth scroll behaviour when navigating to anchor sections within the page.
5. THE Landing_Page SHALL load without any visible layout shift or flash of unstyled content.
6. THE Landing_Page SHALL meet WCAG 2.1 Level AA colour contrast requirements for all text elements.
7. THE Landing_Page SHALL use semantic HTML elements (nav, main, section, footer, h1-h3) for accessibility and SEO.

### Requirement 16: Children's Data Statement

**User Story:** As a privacy-conscious visitor, I want to know the platform's stance on children's data, so that I understand the intended audience.

#### Acceptance Criteria

1. THE Privacy_Page SHALL state that OraInvoice is a business-to-business platform not intended for use by individuals under 16 years of age.
2. THE Privacy_Page SHALL state that OraInvoice does not knowingly collect personal information from children.
3. IF OraInvoice becomes aware that personal information has been collected from a child, THEN THE Privacy_Page SHALL state that the information will be deleted promptly.


### Requirement 17: Platform Branding from Global Admin Settings

**User Story:** As a platform administrator, I want the landing page to use the branding I configured in Global Admin settings, so that the public-facing page matches our brand identity.

#### Acceptance Criteria

1. THE Landing_Page SHALL fetch branding information from the public branding API endpoint (e.g., `GET /api/v1/public/branding` or the existing platform branding endpoint).
2. THE Landing_Page SHALL display the platform logo from the branding settings if one is configured, falling back to the text "OraInvoice" if no logo is set.
3. THE Landing_Page SHALL display the platform name from the branding settings in the header and footer.
4. THE Privacy_Page SHALL use the same branding information as the Landing_Page for consistency.
5. IF the branding API call fails, THEN THE Landing_Page SHALL gracefully fall back to hardcoded defaults: logo text "OraInvoice", company name "Oraflows Limited".

### Requirement 18: Request Free Demo Modal and Email

**User Story:** As a potential customer, I want to request a free demo of OraInvoice by filling out a simple form, so that someone from the Oraflows team can set up a dedicated walkthrough session for my business.

#### Acceptance Criteria

1. THE Landing_Page SHALL display a "Request Free Demo" button in the Hero_Section and the Pricing_Card.
2. WHEN a visitor clicks "Request Free Demo", THE Landing_Page SHALL open a modal popup containing a Demo_Request_Form.
3. THE Demo_Request_Form SHALL contain the following fields: Full Name (required, text input), Business Name (required, text input), Email Address (required, email input with validation), Phone Number (optional, text input), and Message / Additional Notes (optional, textarea).
4. THE Demo_Request_Form SHALL display a description explaining: "Request a free demo — someone from the Oraflows team will set up a dedicated session to walk you through the app. Feel free to share feedback on features you'd like, and we can work around that at no additional cost."
5. WHEN the visitor submits the Demo_Request_Form with valid data, THE Landing_Page SHALL call the Demo_Request_API endpoint (e.g., `POST /api/v1/public/demo-request`) to send the demo request.
6. THE Demo_Request_API SHALL send an email to arshdeep.romy@gmail.com containing all the form field values, using the SMTP settings already configured in the Global Admin Email Providers page.
7. THE Demo_Request_API SHALL NOT require authentication (it is a public endpoint).
8. THE Demo_Request_API SHALL implement basic rate limiting (e.g., max 5 requests per IP per hour) to prevent spam.
9. AFTER successful submission, THE Demo_Request_Form modal SHALL display a success message: "Thank you! Our team will be in touch within 24 hours to schedule your demo."
10. IF the email fails to send, THEN THE Demo_Request_Form modal SHALL display an error message: "Something went wrong. Please email us directly at arshdeep.romy@gmail.com"
11. THE Demo_Request_Form SHALL include a honeypot field (hidden from real users) to filter out bot submissions.

### Requirement 19: NZ Data Sovereignty Statement

**User Story:** As a New Zealand business owner, I want to know that all my data stays in New Zealand, so that I can trust the platform with my business information.

#### Acceptance Criteria

1. THE Landing_Page SHALL display a prominent "100% NZ Hosted" badge or statement in the Hero_Section or a dedicated trust section.
2. THE Landing_Page SHALL state that OraInvoice is built and operated by Oraflows Limited, a locally owned New Zealand company.
3. THE Landing_Page SHALL state that all data is stored and processed entirely within New Zealand — no data leaves the country.
4. THE Privacy_Page SHALL include a dedicated "Data Sovereignty" section stating that all servers, databases, and application infrastructure are located in New Zealand.
5. THE Privacy_Page SHALL state that Oraflows Limited is registered in New Zealand and operates under New Zealand law.

### Requirement 20: Supported Trades Page

**User Story:** As a visitor, I want to see which trade industries OraInvoice supports, so that I can understand whether the platform is relevant to my specific trade and what features are available or coming soon.

#### Acceptance Criteria

1. THE Landing_Page system SHALL include a Trades_Page rendered at the `/trades` route, accessible without authentication.
2. THE Trades_Page SHALL display the Landing_Header and Landing_Footer for design consistency.
3. THE Trades_Page SHALL display a hero section with a heading that communicates OraInvoice supports multiple trade industries.
4. THE Trades_Page SHALL display the following trade categories, each as a card or section with an icon, trade name, status badge, and description:

   **Available Now:**
   - **Automotive & Transport** — Status: "Available". Description: Full trade-specific features including vehicle database with CarJam integration, WOF/rego expiry tracking, odometer history, job cards with vehicle linking, automotive service types, parts and fluids catalogue. List key automotive-specific features.
   - **General Invoicing** — Status: "Available". Description: Core invoicing, quoting, customer management, payments, accounting, reports, and all non-trade-specific modules are available for any business type regardless of trade.

   **Coming Soon:**
   - **Plumbing & Gas** — Status: "Coming Soon". Description: Trade-specific features for plumbers, gasfitters, and drainlayers including compliance tracking, gas certification management, and plumbing-specific service types.
   - **Electrical & Mechanical** — Status: "Coming Soon". Description: Trade-specific features for electricians, solar installers, and mechanical engineers including electrical certification tracking and trade-specific service types.

5. EACH trade card with "Available" status SHALL display a "Get Started" button that navigates to `/signup`.
6. EACH trade card with "Coming Soon" status SHALL display a "Notify Me" or "Request Free Demo" button that opens the Demo_Request_Form modal.
7. THE Trades_Page SHALL display a section below the trade cards explaining that OraInvoice's core invoicing, quoting, customer management, and accounting features work for any business type — trade-specific features add specialised tools on top.
8. THE Trades_Page SHALL be linked from the Landing_Header navigation and from the Landing_Footer.
9. THE Trades_Page SHALL use the same design system (typography, colours, spacing, responsive breakpoints) as the Landing_Page and Privacy_Page.

### Requirement 21: Editable Privacy Policy via Global Admin

**User Story:** As a global admin, I want to edit the privacy policy content from the admin panel, so that I can update legal text without deploying code changes.

#### Acceptance Criteria

1. THE Global Admin Settings page SHALL include a "Privacy Policy" section or tab where the global admin can edit the privacy policy content.
2. THE privacy policy editor SHALL support rich text or Markdown input, allowing headings, lists, bold, links, and paragraphs.
3. THE backend SHALL store the privacy policy content in the database (e.g., in `platform_settings` or a dedicated table) so it persists across deployments.
4. THE backend SHALL expose a public API endpoint (e.g., `GET /api/v1/public/privacy-policy`) that returns the stored privacy policy content without requiring authentication.
5. THE Privacy_Page SHALL fetch the privacy policy content from the public API endpoint and render it.
6. IF no custom privacy policy has been saved by the global admin, THEN THE Privacy_Page SHALL render the default hardcoded privacy policy content (the NZ Privacy Act 2020 compliant policy from Requirements 10–14, 16, 19).
7. THE privacy policy editor SHALL display a "Last Updated" timestamp that is automatically set when the content is saved.
8. THE Privacy_Page SHALL display the "Last Updated" date from the stored content, or the deployment date if using the default.
9. THE backend endpoint SHALL include the `last_updated` timestamp in the API response alongside the content.
