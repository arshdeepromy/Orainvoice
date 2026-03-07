OraInvoice — Universal Trades \& Business SaaS Platform: Enhancement Development Plan

Version 3.0 | March 2026 | Prepared for Development Team



1\. Overview \& Strategic Direction

OraInvoice is being expanded from a New Zealand workshop invoicing platform into a globally capable, multi-trade, multi-industry SaaS invoicing and business management platform. The core architecture, authentication system, security model, PostgreSQL database layer, Carjam integration, and billing infrastructure built in Version 1 remain intact. This enhancement plan layers on top of that foundation rather than replacing it.

The expanded platform serves any self-employed trade, service business, retail shop, restaurant, or contractor anywhere in the world. A plumber in Auckland, a freelance graphic designer in London, a restaurant in Sydney, and an electrical contractor in Toronto should all find OraInvoice immediately useful and appropriately configured for their specific work — without seeing features irrelevant to them.

The guiding design philosophy remains unchanged: every interaction should feel obvious, fast, and frictionless. The expansion must not introduce complexity for existing users. The vehicle and workshop features remain fully intact. New trade types and modules are layered in, and each organisation only ever sees what applies to their configured trade category.

The platform name across all touchpoints — application header, invoice footers, email templates, marketing pages, receipts, and legal documents — is OraInvoice.



2\. Trade Category System \& Onboarding Setup Wizard

2.1 Trade Category Registry

The foundation of the universal expansion is a Trade Category Registry managed by Global Admin. This registry defines every supported trade type, its associated default service items, its invoice template layout preferences, its recommended modules, and its terminology overrides. The registry is not hardcoded — Global Admin can add new trade categories, edit existing ones, and retire obsolete ones without a code deployment.

The following trade categories are supported at launch, drawn from self-employed and business-operating trades across all major markets. These are grouped into logical families:

Automotive \& Transport — Vehicle Workshop (existing), Mobile Mechanic, Tyre \& Exhaust Specialist, Panel Beating \& Spray Painting, Automotive Electrical, Windscreen Repair, Caravan \& Trailer Service, Motorcycle Workshop, Heavy Vehicle \& Truck Service.

Electrical \& Mechanical — Electrician, Electrical Contractor, Solar \& Battery Installer, Air Conditioning \& HVAC Technician, Refrigeration Technician, Lift \& Escalator Technician, Fire Alarm \& Security System Installer.

Plumbing \& Gas — Plumber, Gasfitter, Drainlayer, Irrigation Specialist, Roofing Plumber, Hot Water System Specialist.

Building \& Construction — Builder, Carpenter, Concreter, Plasterer, Tiler, Bricklayer, Steel Fixer, Demolition Contractor, Scaffold Contractor, Quantity Surveyor, Project Manager (Construction).

Landscaping \& Outdoor — Landscaper, Arborist \& Tree Surgeon, Irrigation Installer, Fencing Contractor, Lawn Mowing \& Garden Maintenance, Pest Control, Swimming Pool Service \& Maintenance.

Cleaning \& Facilities — Commercial Cleaner, Residential Cleaner, Window Cleaner, Carpet \& Upholstery Cleaner, Pressure Washer, Waste Removal \& Skip Hire, Property Maintenance.

IT \& Technology — IT Support \& Managed Services, Computer Repair, Network Installation, Web Developer, Software Developer, Cybersecurity Consultant, AV \& Home Automation Installer, CCTV \& Security Installer.

Creative \& Professional Services — Graphic Designer, Photographer, Videographer, Copywriter, Marketing Consultant, Social Media Manager, Event Planner, Translator.

Accounting, Legal \& Financial — Bookkeeper, Accountant, Tax Advisor, Financial Planner, Business Consultant, Mortgage Broker.

Health \& Wellness (Self-Employed) — Physiotherapist (private practice), Massage Therapist, Personal Trainer, Nutritionist, Optometrist (independent), Veterinarian (independent practice), Dentist (independent practice).

Food \& Hospitality — Restaurant, Café, Food Truck, Bakery, Catering Company, Bar \& Pub, Takeaway \& Fast Food.

Retail — General Retail Store, Clothing Boutique, Pharmacy (independent), Hardware Store, Automotive Parts Retailer, Electronics Retailer, Online Store.

Hair, Beauty \& Personal Care — Hairdresser, Barber, Beauty Therapist, Nail Technician, Tattoo Artist, Mobile Beauty Therapist.

Trades Support \& Hire — Equipment Hire, Tool Hire, Event Equipment Hire, Party Hire.

Freelancing \& Contracting — General Freelancer, Independent Contractor, Consultant (General).

2.2 Organisation Setup Wizard

When a new organisation signs up for OraInvoice (or when the platform upgrade is pushed to existing organisations), they enter a multi-step setup wizard before accessing the application. The wizard is friendly, visually clean, and takes under three minutes. Each step is one screen. Progress is shown as a simple step indicator at the top. Any step can be revisited later from Settings.

Step 1 — Welcome \& Country Selection. The user selects their country from a searchable dropdown. This sets the default currency, tax label (GST for NZ/AU, VAT for UK/EU, Tax for US/Canada, etc.), default tax rate for their region, date format, and time zone. It also determines which compliance features are surfaced (e.g. NZ-specific GST return reports, UK VAT return format).

Step 2 — Trade Area Selection. A clean visual grid of trade family icons (Automotive, Electrical, Plumbing, Building, IT, Food \& Hospitality, Retail, Professional Services, and so on). The user taps or clicks their trade family which expands to show specific trade types within that family. They select the one that best describes their business. If none match exactly, a "Custom / Other" option is available which gives them a blank slate with all modules available to manually configure. Organisations that serve multiple trade types (e.g. a business that does both electrical and plumbing) can select up to three trade categories.

Step 3 — Business Details. Business name, trading name (if different), business registration number (optional, shown on invoices if entered), country-appropriate tax number (GST number, VAT number, ABN, etc.), phone, address, and website.

Step 4 — Branding. Logo upload, primary brand colour, and invoice accent colour. A live preview of a sample invoice updates in real time as they make choices.

Step 5 — Module Selection. Based on the trade type selected in Step 2, a recommended set of modules is pre-selected. The user sees a clear visual checklist of available modules with a plain-language description of what each does. They can enable or disable any module. This is not a permanent decision — modules can be toggled at any time from Settings. This step makes OraInvoice feel tailor-made rather than generic.

Step 6 — First Service or Product. The wizard pre-populates a list of suggested services or products typical for their trade (e.g. for an electrician: Callout Fee, Hourly Labour Rate, Switchboard Inspection; for a restaurant: Dine-In Order, Takeaway Order, Catering Package). The user can accept these as-is, edit them, delete them, or add their own. At least one must be saved to proceed. This means their service catalogue is populated before they create their first invoice.

Step 7 — Ready. A confirmation screen showing what has been set up with edit links to each section. A single "Go to Dashboard" button completes the wizard.

2.3 Trade-Specific Terminology \& Template Adaptation

Once a trade category is selected, OraInvoice adapts its language throughout the interface. For example, vehicle workshops use "Rego" and "Vehicle" and have the vehicle information block on invoices. Builders use "Job Site Address" instead of a vehicle field. IT support companies use "Device / Asset" fields. Restaurants see "Table Number" and "Cover Count" on their transaction records. Cleaners see "Property Address." Freelancers see "Project Name" and "Milestone."

These terminology mappings are stored in the Trade Category Registry and applied at the organisation level. The underlying data structure is the same for all trades — only the labels change. This means Global Admin can update terminology for any trade type without a code change.

Invoice layouts also adapt per trade. A restaurant receipt is compact and optimised for thermal printing. A builder's invoice is detailed with job site information, variation descriptions, and retention tracking. An IT consultant's invoice shows project names, hourly rates, and timesheet entries. A retailer's invoice looks like a POS receipt with a product grid. All of these render from the same core invoice data model with trade-specific display templates.



3\. Module Selection System

3.1 Module Architecture

Every feature group in OraInvoice is a module. Modules can be enabled or disabled per organisation at any time by the Org Admin from Settings > Modules. When a module is disabled, all associated menu items, buttons, and form fields for that module are completely hidden from all users in that org — they are not greyed out or locked, they simply do not appear. This keeps the interface clean for every trade type.

The following modules are available for selection. Not all modules are relevant to all trades — the setup wizard recommends the appropriate subset, and the Trade Category Registry defines which modules are compatible with which trade types. Global Admin can restrict which modules are available on which subscription plans.

Core Modules (always on, cannot be disabled) — Authentication \& Users, Invoice Management, Customer Management, Payments, Notifications, Billing \& Subscription.

Optional Modules:

Vehicle \& Asset Tracking — the original Carjam-integrated vehicle module for workshops, extended to support any asset type (device serial numbers for IT, equipment IDs for hire companies, vessel registrations for marine trades). Carjam integration is only available when the trade category is automotive.

Inventory \& Stock Management — described in full in Section 4.

Quotes \& Estimates — create a formal quote document with the same line-item structure as an invoice. Quotes can be accepted by customers (via an emailed approval link) and converted to invoices in one click. Quotes have their own numbering sequence and status flow (Draft, Sent, Accepted, Declined, Expired, Converted).

Job \& Work Order Management — described in full in Section 5.

Recurring Invoices — set any invoice as a recurring template that automatically generates and issues a new invoice on a configured schedule (weekly, fortnightly, monthly, quarterly, annually). Used by cleaning companies billing regular clients, IT managed service providers billing monthly retainers, and any business with subscription-style client relationships.

Time Tracking — log billable hours against jobs or customers. Time entries can be added manually or started/stopped with a running timer. At invoice time, unbilled time entries for the customer are shown and can be added to the invoice as Labour line items with one click.

Project Management — group jobs, invoices, quotes, time entries, and expenses under a named project. Shows project-level profitability (total invoiced vs total costs). Used by builders, IT consultants, event planners, and any business that works in project cycles.

Expenses \& Costs — log business expenses (materials purchased, subcontractor costs, fuel, consumables) against jobs or projects. Used for profitability reporting and optionally shown as pass-through charges on invoices.

Purchase Orders — raise a purchase order to a supplier, receive goods or services against it, and link the cost to a job or project. Integrates with the Inventory module for stock receiving.

Staff \& Contractor Management — add staff members (beyond app users) for scheduling and job assignment purposes. Record hourly rates and track labour costs per job. Used by businesses that employ tradespeople, cleaners, or drivers who do not need app access.

Scheduling \& Calendar — a visual calendar showing jobs, appointments, and bookings. Jobs can be dragged and rescheduled. Used by service businesses that book time slots (cleaners, IT support, beauty therapists, personal trainers, pest control).

Booking \& Appointments — a customer-facing booking page where clients can self-book appointments or jobs from available time slots. Confirmations sent automatically by email and SMS. Integrates with the Scheduling module.

Tipping — for restaurants and hospitality businesses. A tip amount can be added to any transaction, split across staff if configured. Tips are tracked separately in reporting.

Table \& Seat Management — for restaurants and cafes. A visual floor plan showing tables, their status (empty, occupied, reserved), and current order/invoice totals. Tap a table to view the current order and add items.

Kitchen Display — for restaurants. A simple display screen (second monitor or tablet) showing order line items as they are added, with a tick-off interface for kitchen staff when items are prepared.

Retentions — for builders and construction contractors. A configurable retention percentage held back on progress claims, released upon practical completion. Retention values are tracked per project and shown clearly on invoices with the net payable amount.

Progress Claims — for builders, civil contractors, and large project trades. Issue a progress claim invoice against a contract value showing: original contract amount, variations to date, amount claimed to date, amount paid to date, and current claim amount.

Variations \& Change Orders — formally track scope changes on construction or project-based work. Each variation has a description, cost breakdown, and approval status. Approved variations automatically update the contract value in the Progress Claims module.

Compliance \& Certifications — for trades that issue compliance documentation alongside invoices (electricians issuing Electrical Safety Certificates, gasfitters issuing Gas Safety Certificates, building inspectors issuing reports). Compliance documents are generated as PDFs linked to the invoice.

Multi-Currency — accept invoices in multiple currencies with configurable exchange rates. All reporting consolidates to the org's base currency. Used by businesses that work internationally or accept payment from overseas clients.

Ecommerce \& WooCommerce Integration — described in full in Section 6.

POS \& Receipt Printer Integration — described in full in Section 7.

Loyalty \& Memberships — for retail, hospitality, and service businesses. Customers can accumulate loyalty points with each purchase, redeemable against future invoices. Membership tiers (e.g. Silver, Gold) unlock configured discounts. Membership status shown on the customer profile and applied automatically at invoice creation.

Tips on Invoices — add optional tip or gratuity lines to invoices, common in hospitality.

Franchise \& Multi-Location — for businesses operating multiple sites under one brand. Each location has its own invoice numbering, address, and staff but shares a central customer database and reporting rolls up to a head-office dashboard. Described further in Section 9.



4\. Inventory \& Stock Management Module

4.1 Product Catalogue

The Inventory module introduces a full product catalogue alongside the existing service catalogue. Products are physical or digital items that are sold, consumed, or used in the delivery of services. The distinction between a Service item and a Product item is meaningful: services are what the business does, products are what the business sells or uses.

Each product record contains: product name, SKU (stock keeping unit, can be auto-generated or manually entered), barcode (EAN-13, QR, or custom — used for POS scanning), category, description, unit of measure (each, kg, litre, metre, hour, box, pack, etc.), sale price excluding tax, tax applicability, cost price (what the business paid for it), stock quantity on hand, low stock alert threshold, reorder quantity, supplier name, supplier SKU, and product images.

Products can be organised into categories and subcategories with no depth limit. Categories are configured by the Org Admin and appear in the invoice item search so salespeople can browse by category when adding items to an invoice.

4.2 Stock Levels \& Movement

Every time a product is added to an invoice, the stock on hand count decrements automatically. Every time stock is received (via the Purchase Orders module or via a manual stock adjustment), the count increments. Every change to stock level creates a stock movement record showing: the date, the type of movement (Sale, Purchase, Manual Adjustment, Write-Off, Return), the quantity change, the resulting on-hand quantity, and the user who triggered it. This gives a complete stock history for any product.

When a product's stock level falls below the configured low-stock threshold, an alert appears in the Org Admin dashboard and an email notification is sent. If the stock level reaches zero and a salesperson tries to add that product to an invoice, a clear warning is shown — they can proceed if the org allows selling on backorder (configurable in settings) or they are blocked until stock is replenished.

Stock takes (full physical inventory counts) can be conducted from the Inventory module. The user is shown the current system stock level for each product and enters the physically counted quantity. Discrepancies are flagged and must be reviewed before being committed as a Manual Adjustment. A stocktake report is generated showing all variances.

4.3 CSV Import \& Sample Templates

Products can be imported in bulk via CSV upload. A sample CSV file is available to download directly from the import page, pre-formatted with correct column headers and populated with example data for the org's trade type so the user can see exactly what format is expected before building their own file.

The CSV import supports: creating new products, updating existing products (matched by SKU), and optionally archiving products not present in the import file. Before the import is committed, a preview screen shows exactly what will be created, updated, or archived with a row count and the first ten rows rendered as a readable table. The user must confirm before the import runs. Import results are shown on completion: records created, records updated, records skipped (with reasons), and any rows that failed validation with specific error messages pointing to the row and column.

The sample CSV is generated dynamically based on the org's trade type so a restaurant gets a food and beverage product template while an electrician gets a materials and components template.

4.4 Pricing Rules \& Tiered Pricing

Beyond a single sale price, products and services support configurable pricing rules. Rules are evaluated in priority order and the first matching rule wins:

Customer-specific pricing — a fixed price or discount percentage applied when invoicing a specific customer. Used for account customers or trade pricing.

Volume pricing — tiered pricing based on quantity in a single invoice line (e.g. 1–9 units at $10 each, 10–49 units at $8.50 each, 50+ units at $7 each).

Date-based pricing — a promotional price active between two dates that reverts automatically after the end date.

Trade category pricing — a discount or markup applied to all customers with a specific tag (e.g. "Trade" or "Wholesale").

When creating an invoice, if a pricing rule applies to any line item, the applicable price is shown with a small indicator noting which rule is active. The salesperson can always override the rule price if they have the permission to do so (configurable by Org Admin).



5\. Job \& Work Order Management Module

5.1 Job Lifecycle

A Job is the operational unit of work in OraInvoice for trade businesses. For a workshop, a Job is a repair or service visit. For an electrician, it is an installation or fault-finding callout. For a cleaner, it is a scheduled clean. Jobs connect scheduling, time tracking, expenses, and invoicing into a single workflow.

A Job record contains: job number (auto-sequential with prefix), status (Enquiry, Scheduled, In Progress, On Hold, Completed, Invoiced, Cancelled), customer, location (job site address, which can differ from the customer's billing address), assigned staff or contractor, scheduled start and end date/time, actual start and end (logged when status changes), job description, checklist items (configurable per trade), notes (internal and customer-facing), attached photos and files, linked quote (if the job originated from a quote), linked invoices, time entries, and expenses.

5.2 Job Status Flow

Jobs move through a clear status pipeline. Enquiry means a potential job has been logged but not yet confirmed or scheduled. Scheduled means it is booked on the calendar with a time slot. In Progress means work has started (set manually or automatically when the scheduled start time passes). On Hold means work has been paused (reason required). Completed means the work is done and the job is ready to be invoiced. Invoiced means at least one invoice has been raised against this job. Cancelled means the job will not proceed (reason required).

The Org Admin can view all jobs in a pipeline board view (a Kanban-style column for each status) or a list view sortable by status, date, customer, or assigned staff. Salespeople see only jobs assigned to them or all jobs depending on the permission configuration.

5.3 Photo \& Document Attachments

Any job can have photos, PDFs, or other documents attached. For trades this is critical — a plumber photographs the fault before and after repair, a builder photographs site progress, an electrician attaches a compliance certificate. Attachments are stored in the database as binary objects and count toward the org's storage quota. Attachments on jobs can optionally be included in the invoice email to the customer.

5.4 Job to Invoice Conversion

When a job is marked Completed, a prominent "Create Invoice" button appears on the job record. Clicking it opens the invoice creation form pre-populated with the customer, job site address (as the service location), all time entries as Labour line items, all expenses that were flagged as billable as pass-through line items, and any materials used from inventory as Product line items. The salesperson reviews, adjusts, and issues. The job status automatically moves to Invoiced when the invoice is issued.



6\. Ecommerce \& WooCommerce Integration Module

6.1 WooCommerce Integration

Organisations with a WooCommerce-powered online store can connect their store to OraInvoice from the Integrations section of Org Settings. The connection is made via the WooCommerce REST API — the user enters their store URL and generates a key/secret pair from their WooCommerce admin, which OraInvoice stores encrypted.

Once connected, OraInvoice syncs in both directions on a configurable schedule (minimum every 15 minutes, or triggered by a webhook from WooCommerce on each new order):

Orders from WooCommerce are pulled into OraInvoice as invoices automatically. The order's customer is matched to an existing OraInvoice customer record by email address, or a new customer is created. The order's line items (products and quantities) are mapped to OraInvoice inventory items where SKUs match. The invoice status is set based on the WooCommerce order status (Processing becomes Issued, Completed becomes Paid, Refunded triggers a Credit Note).

Products from OraInvoice inventory can be pushed to WooCommerce — name, description, price, SKU, and stock level. Stock level changes in OraInvoice (from in-person sales or stock adjustments) sync to WooCommerce so online availability is always accurate.

A sync log is available in Org Settings showing every sync event, how many orders were imported, how many products were updated, and any errors (e.g. a WooCommerce product SKU that has no match in OraInvoice inventory). Errors do not block the sync — they are flagged for manual review.

6.2 General Ecommerce \& API Integrations

Beyond WooCommerce, OraInvoice provides a general-purpose webhook and API integration layer. Any ecommerce platform that can send an HTTP webhook on new orders (Shopify, Squarespace, Wix, BigCommerce, and others) can push order data to OraInvoice via a configurable webhook endpoint generated per org. The endpoint URL is available in Org Settings > Integrations > Webhook Receiver with documentation on the expected JSON payload format.

A Zapier-compatible REST API is available to all organisations, allowing integration with thousands of third-party tools without custom development. The API covers: create customer, create invoice, create product, get invoice status, and mark invoice as paid. API credentials (client ID and secret) are generated in Org Settings > API Access. All API usage is logged and rate-limited per org.



7\. POS \& Receipt Printer Integration Module

7.1 Point of Sale Mode

For organisations that operate a physical counter (retail shops, cafes, restaurants, auto parts stores, beauty salons), OraInvoice includes a Point of Sale mode accessible from the main navigation. POS mode is a full-screen, touch-optimised interface designed for fast transaction entry at a counter.

The POS screen is divided into two panels. The left panel is a product browser — a grid of product and service tiles organised by category, with a search bar at the top. Products show their name, image (if uploaded), and price. Tapping a product tile adds it to the current order. The right panel is the current order — a running list of items, quantities, and line totals, with a visible subtotal, tax amount, and grand total.

Quantity adjustment on any line item is done by tapping the quantity which opens a number input — no mouse required. Removing an item is a swipe-left or a delete button. Applying a discount to a line item or the whole order is a single tap with a percentage or dollar amount input.

When the order is ready, the salesperson taps "Charge". They select the payment method (cash, card via Stripe terminal, or split payment across methods). The transaction is processed, a receipt is generated, and the order is recorded as a paid invoice in the system. The entire flow from blank screen to receipt is designed to take under 20 seconds for a standard transaction.

POS mode works offline — if the device loses internet connectivity, transactions are queued locally and synced automatically when connectivity is restored. The offline queue is displayed clearly so staff know how many transactions are pending sync.

7.2 Receipt Printer Integration

OraInvoice supports ESC/POS receipt printers — the industry standard protocol used by Epson, Star Micronics, Bixolon, and most other thermal receipt printer brands. Receipt printers connect via USB, Ethernet (LAN), Bluetooth, or WiFi depending on the printer model.

Connection is configured in Org Settings > Hardware. The user selects their connection type and enters the printer's IP address (for network printers) or selects the USB/Bluetooth device from a browser device picker (using WebUSB and Web Bluetooth APIs for Chrome-based browsers). A test print button sends a sample receipt to confirm the connection is working.

When an invoice or POS transaction is completed and the user selects "Print Receipt", OraInvoice generates an ESC/POS-formatted receipt and sends it directly to the printer. The receipt includes: org logo (as a monochrome bitmap), org name and address, transaction date and time, itemised line items with quantities and prices, subtotal, tax, total, payment method, change given (for cash transactions), invoice or receipt number, and the "Powered by OraInvoice" footer. Receipt width is configurable (58mm or 80mm paper rolls, the two standard sizes).

For restaurants using the Table Management module, printing a table's bill sends it to the receipt printer automatically. Kitchen order dockets (for the Kitchen Display module) can also be printed to a second ESC/POS printer designated as the kitchen printer, with large text for readability.

A cloud printing option is available for organisations that need printing across multiple locations or devices without direct USB/network connection. This uses a lightweight print agent (a small software service that runs on a computer connected to the printer) that polls OraInvoice for pending print jobs and forwards them to the local printer. The print agent is a downloadable installer for Windows and macOS.



8\. Global Branding \& "Powered By" System

8.1 Global Admin Branding Configuration

In the Global Admin console under Settings > Platform Branding, the Global Admin configures OraInvoice's own platform brand identity as it appears across all organisations. This configuration includes: the platform name (OraInvoice, or a white-label name if the platform is resold under a different brand), the platform logo, the platform primary and secondary colours, the platform website URL (used in the Powered By link), and the signup URL (the URL a new customer would visit to sign up — used in the Powered By promotional link).

The signup URL can be entered manually or set to "Auto-detect from domain" in which case OraInvoice uses the domain from which the application is being served. This means if a reseller deploys OraInvoice under their own domain, the Powered By link automatically points to their signup page.

8.2 Powered By Footer on All Outgoing Documents

Every invoice PDF generated by any organisation on the platform includes a footer line at the very bottom of the document, visually separated from the org's own content. This footer reads: "Powered by OraInvoice — \[platform URL]" using the globally configured platform name and signup URL. The org's branding appears above this line — their logo, colours, and footer text. The platform footer is below it, smaller and in the platform's configured accent colour, so it is visible but does not compete with the org's brand.

This footer cannot be removed by Org Admins. It is a platform-level element. Global Admin can configure its appearance (font size, colour, label text) but cannot disable it for any org below their subscription tier. Enterprise-tier plans can optionally have it removed if the Global Admin grants that org the white-label permission — a per-org toggle in the Global Admin console.

8.3 Powered By in Email Templates

Every email sent through OraInvoice's notification system includes the platform footer in the email body. The email footer contains the platform logo, the text "Invoicing powered by OraInvoice", and a hyperlink to the configured signup URL. This appears below the org's own custom email footer content. The styling matches the platform brand colours and is consistent across all email types (invoice emails, payment receipts, reminders, appointment confirmations, etc.).

The signup link in the Powered By footer uses UTM parameters automatically appended by the platform so the Global Admin can track how many new signups originate from the Powered By links across all orgs, visible as a metric in the Global Admin analytics dashboard.



9\. Enterprise, Multi-Location \& Franchise Support

9.1 Multi-Location Organisations

An organisation can operate across multiple physical locations or branches under one OraInvoice account. Each location has its own: name, address, phone number, email (for invoices sent from that location), assigned users, and invoice number prefix (optional — some orgs prefer a single sequence across all locations, others want location-specific prefixes like AKL-0001 or SYD-0001).

The Org Admin has a head-office view showing aggregate metrics across all locations. Each location manager (a sub-role available when the Multi-Location module is enabled) sees only their own location's data. Customers and vehicles are shared across all locations — a customer who visits Location A and then Location B is recognised as the same customer with a unified invoice history.

Inventory can be managed per-location (each location has its own stock levels for each product) or shared (a single stock pool across all locations). Stock transfers between locations are logged as stock movements.

9.2 Franchise Support

For franchise networks (e.g. a franchise automotive group, a franchise cleaning company), OraInvoice supports a Franchise Admin role above Org Admin. The Franchise Admin has read-only reporting access across all franchisee organisations that are linked to the franchise group. They cannot edit any franchisee's data but can view aggregate revenue, invoice counts, customer counts, and module usage across the group.

Franchise groups are configured by Global Admin who links individual organisations together into a franchise group and assigns a Franchise Admin account. Each franchisee organisation remains independently billed and operated. The Franchise Admin view is an additional layer, not a replacement for the Org Admin of each franchisee.



10\. Multi-Currency \& Internationalisation

OraInvoice operates globally with full internationalisation support. The following are configurable per organisation:

Language — the interface language. At launch: English (NZ), English (AU), English (UK), English (US), Spanish, French, German, Portuguese, Dutch, and Japanese. Language files are managed externally and new languages can be added without code changes. The invoice PDF and email templates honour the org's selected language.

Currency — the org's base currency. All financial values are stored in the base currency. When the Multi-Currency module is enabled, individual invoices can be denominated in a different currency with a configurable exchange rate. The rate can be entered manually or pulled from an open exchange rate API on invoice creation. Revenue reporting always converts to base currency using the rate recorded at the time of invoicing.

Tax System — the tax label (GST, VAT, Tax, IVA, MwSt., etc.), the default tax rate, and whether tax is included in displayed prices by default or shown separately. Organisations can have multiple tax rates (e.g. standard rate, reduced rate, zero rate) and assign each to specific products or services.

Date \& Number Formats — date format (DD/MM/YYYY for NZ/AU/UK, MM/DD/YYYY for US), thousands separator (comma or period), decimal separator, and currency symbol position.

These settings default intelligently based on the country selected during the setup wizard but can all be overridden in Org Settings > Localisation.



11\. Global Admin Console Enhancements

11.1 Multi-Trade Analytics Dashboard

The Global Admin analytics dashboard gains a trade category dimension across all its metrics. In addition to the existing views (total MRR, org count, storage usage, error summary), the following trade-segmented views are added:

Trade Group Overview — a table and pie chart showing the distribution of active organisations across trade families. Shows how many orgs are in each trade group, their aggregate MRR contribution, average revenue per org by trade, and average storage usage per org by trade. This gives the Global Admin a clear picture of which trades are the most valuable customer segments.

Trade Group Growth — a time-series chart showing new organisation signups per trade group over the last 12 months. Useful for identifying which trades are growing fastest and where marketing investment is working.

Feature Module Adoption — a heatmap showing which modules are most enabled across the platform, broken down by trade group. Helps prioritise which modules to invest in next and which are being ignored.

Conversion by Trade — for organisations on free trials, a breakdown of trial-to-paid conversion rates by trade group. Identifies which trades convert well (product-market fit is strong) versus those with high trial abandonment (may need onboarding improvements).

11.2 Organisation Alerts \& Maintenance Notifications

Global Admin can send system-wide or targeted notifications to organisations through the console. These notifications appear as a banner inside the OraInvoice application for all affected users and are simultaneously sent as an email to all Org Admin accounts in the targeted organisations.

Notification types available to Global Admin:

Maintenance Window — a scheduled downtime notice. The Global Admin sets the start time, expected duration, and a description. The in-app banner appears 48 hours before the maintenance window (configurable lead time) and changes to a countdown banner in the final hour. If the maintenance window is for a specific module (e.g. the payment processing module), only orgs with that module enabled receive the notification.

Platform Update — an announcement of new features or changes. Includes a title, description, and an optional "Learn more" URL. Displayed as an informational banner that users can dismiss.

Urgent Alert — for critical issues affecting the platform. Displayed as a red banner that cannot be dismissed until the Global Admin clears it. Triggers immediate email to all Org Admin accounts.

Targeted Notification — Global Admin can filter organisations by trade group, plan type, country, or specific org IDs and send a notification to only that subset. Useful for trade-specific announcements (e.g. announcing a new compliance certificate feature specifically to electricians and gasfitters).

All sent notifications are logged with timestamp, target audience, delivery count (how many orgs and how many users received it), and email delivery status from the notification system.

11.3 Database Migration Tool

The Global Admin console includes a built-in database migration tool that allows the platform's PostgreSQL data to be migrated to a new server, a new region, or a new cloud provider without requiring developer intervention for routine migrations.

The migration tool supports two modes:

Full Migration — a complete export of all data from the current PostgreSQL instance, transfer to a new instance, validation, and cutover. Used for planned infrastructure moves (e.g. moving from one cloud provider to another, scaling up to a larger database instance, or changing data residency region).

Live Migration — a continuous replication approach where changes to the source database are streamed to the destination database in near-real-time while the migration is in progress. Once the destination is caught up to within a few seconds of the source, a cutover is performed with minimal downtime (typically under 30 seconds). Live Migration uses PostgreSQL logical replication under the hood.

The migration interface guides the Global Admin through the following steps: enter the destination database connection string (verified and tested before the migration begins), choose Full or Live Migration mode, review a pre-migration checklist (backup confirmed, destination storage sufficient, network connectivity verified), start the migration, and monitor progress.

The progress screen shows: tables completed versus total tables, rows migrated, data volume transferred, elapsed time, estimated time remaining (calculated from the rate of transfer for the current session), and a live log of migration events. For Live Migration mode, a replication lag indicator shows how many seconds behind the destination database is from the source.

Throughout the migration, a status banner is visible to all Global Admin users in the console. The Global Admin can send a Maintenance Window notification to all orgs before starting a Full Migration. Live Migration can proceed without a maintenance window since the application remains fully operational.

At the point of cutover (both modes), the migration tool:

Pauses all write operations to the source database for a period of under 30 seconds, applies any remaining pending changes to the destination, verifies row counts across all tables match between source and destination, updates the application's database connection configuration to point to the new instance, resumes write operations now directed to the destination database, and runs a post-migration integrity check.

If the integrity check fails at any point, the migration tool automatically rolls back to the source database and raises a Critical error in the error log with full details of what failed. The application never enters a state where it is connected to a partially migrated database.

Post-migration, a full migration report is generated showing: start time, end time, total data migrated, table-by-table row count verification results, cutover duration, and whether any errors were encountered. This report is downloadable as a PDF and stored in the Global Admin audit log permanently.



12\. Security, Compliance \& Data Governance Enhancements

The security model from Version 1 remains fully intact and is extended for the global, multi-trade platform:

Global Compliance Profiles — the platform supports multiple tax and compliance frameworks simultaneously. Each org's reporting is scoped to their country's requirements. GST return format for NZ, BAS preparation format for AU, VAT return format for UK, and a generic tax summary for all other countries. These are generated as part of the Reporting module.

Data Residency Selection — when a new organisation signs up, they select their preferred data residency region (currently: NZ/AU, UK/EU, North America). Their customer, invoice, and vehicle data is stored in the PostgreSQL instance hosted in that region. Global Admin configures which database instances serve which regions in the console. The global vehicle database and the platform's billing data remain in a single primary instance.

GDPR Compliance — for organisations in the UK and EU, additional GDPR-specific features are active: a configurable data retention policy (invoices and customer records older than the configured period are automatically flagged for review), a data processing agreement available for org admins to digitally accept, a cookie consent configuration for the customer-facing booking and payment pages, and data subject access request handling from the customer management module.

SOC 2 Readiness — the audit log, access controls, encryption standards, and error logging are architected to support a future SOC 2 Type II assessment. Global Admin can export a compliance evidence pack (audit logs, access control reports, encryption configuration documentation) from the console.

Penetration Testing Mode — Global Admin can enable a sandbox environment for security testing that mirrors the production configuration but uses synthetic data. This allows scheduled penetration tests to be conducted without risk to real customer data.



13\. UX \& Design System

The expansion to multiple trades and multiple device types requires a formalised design system that developers and future designers work within. This design system is documented in the codebase and applied consistently across all new modules.

The OraInvoice design system follows the Apple-inspired principle of the original: clarity, depth, and deference. The interface should feel like it gets out of the way and lets the user do their work. Every screen has one primary action. Secondary actions are available but visually subordinate. Destructive actions (delete, void, cancel) are always red, always require confirmation, and are never the primary button on any screen.

All interactive elements have a minimum touch target size of 44x44 points in compliance with WCAG 2.1 AA accessibility guidelines. Colour contrast ratios meet AA standards. All form fields have visible labels (never placeholder-only labels). Error messages are always in plain language and explain what the user should do, not just what went wrong.

The responsive layout system uses a mobile-first approach with four breakpoints: mobile (under 640px), tablet (640–1024px), desktop (1024–1440px), and wide desktop (above 1440px). Every module is tested at all four breakpoints before release. POS mode is specifically optimised for tablet use in landscape orientation.

Loading states use skeleton screens (a shimmering placeholder that matches the shape of the content being loaded) rather than spinners, so the user always understands what is coming. Data is loaded progressively — the page structure appears immediately and data fills in as it loads, rather than the entire page waiting behind a loading screen.

Every destructive or irreversible action in the system presents a confirmation dialog that clearly states what will happen in plain language, shows the quantity or name of affected records, and requires the user to type a confirmation word or the record name for high-stakes operations (like deleting an organisation or voiding a paid invoice). This pattern is consistent across all modules.



14\. Summary of All Gaps Filled in This Plan

Beyond what was specified, the following gaps have been identified and addressed within this document:

The setup wizard collects country and locale settings upfront so that currency, tax label, date format, and compliance features are correct from the first invoice. Without this, international organisations would face misconfigured tax outputs.

Trade category terminology adaptation ensures the interface does not feel generic. A builder should not see "vehicle" fields and a restaurant should not see "rego" fields.

The Module Selection system gives organisations fine-grained control over their experience without requiring Global Admin involvement for every configuration change.

Quotes and Estimates were absent from the original plan. The majority of trade businesses quote before invoicing — the absence of a quoting module would have been a significant gap for builders, electricians, and any project-based trade.

Time Tracking is essential for any hourly-billing business (IT consultants, lawyers, accountants, freelancers). Without it, these users cannot accurately build invoices from their actual time spent.

Job-to-invoice conversion creates a seamless operational flow for field service businesses. Without it, time tracking and job management would be disconnected from invoicing.

Barcode scanning support in the POS and inventory modules is required for retail and parts-based businesses to operate efficiently.

Offline POS capability addresses the real-world scenario of intermittent internet connectivity in workshops, markets, food trucks, and outdoor trade environments.

The cloud print agent addresses the reality that not all printing scenarios can use direct browser-to-printer WebUSB connections, particularly in multi-computer environments.

Franchise and multi-location support was not in the original plan but is essential for any growth path where workshop groups, cleaning franchises, or retail chains adopt the platform.

The Powered By footer with UTM-tracked signup links turns every invoice and email sent by any org into a passive acquisition channel for OraInvoice, compounding in value as the platform grows.

The database migration tool removes the need for developer intervention on infrastructure moves, making OraInvoice genuinely operable by a non-technical Global Admin for all routine operations.

Loyalty and membership features address the retail, hospitality, and beauty segments where customer retention programmes are standard expectations.

Progress claims, retentions, and variations are non-negotiable for the construction trade segment where these are standard contractual mechanisms — omitting them would exclude builders from the platform.

The pre-migration checklist and automatic rollback in the database migration tool protect against data loss during infrastructure changes, which is the single highest-risk operation a SaaS platform can perform.

