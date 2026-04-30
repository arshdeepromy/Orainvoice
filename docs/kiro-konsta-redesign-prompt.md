# Kiro Prompt — OraInvoice Mobile Redesign with Konsta UI

> Paste this entire prompt into Kiro. Do not abbreviate, do not let it skip sections.

---

## Mission

Redesign the OraInvoice mobile app (Capacitor) frontend using **Konsta UI v5** with **Tailwind CSS 4** to achieve a beautiful, native-feeling mobile experience on both iOS and Android. Replace the current basic design completely. Preserve all existing business logic, module gating, calculations, contexts, and data flows exactly as they are.

This is a **frontend-only redesign**. Do not modify the FastAPI backend. Do not change API contracts. Do not change auth flow logic. Only replace the UI layer.

---

## Critical Constraints (Read First)

### 1. EXCLUSIONS — Do NOT build mobile screens for these
- All global admin pages (anything under AdminLayout)
- Org administrative settings: org branding, branch management, billing, integrations admin, security/MFA admin, modules admin, webhooks, invoice template editor, printer settings
- The `/settings` hub page for `org_admin` role configuration screens
- Onboarding wizard, setup guide
- Branch transfers (`/branch-transfers`), staff schedule (`/staff-schedule`) — both `adminOnly`
- Franchise admin pages (`/franchise/*`)
- Data import/export bulk operations (`/data`)
- Accounting admin (chart of accounts editor, journal entries) — keep view-only if at all
- Banking admin (reconciliation dashboard) — keep view-only if at all
- Tax admin (GST period filing) — view-only

### 2. PRESERVATION — Must keep working exactly as-is
- **All eight contexts**: AuthContext, ModuleContext, BranchContext, TenantContext, FeatureFlagContext, LocaleContext, ThemeContext, PlatformBrandingContext
- **Module gating system**: `ModuleProvider`, `ModuleRoute`, `ModuleGate`, `useModules().isEnabled(slug)`
- **Sidebar filter logic**: `module enabled + feature flag + trade family + user role`
- **Auth flow**: JWT in memory, refresh token in httpOnly cookie, 401 mutex refresh, MFA, passkeys, Google OAuth
- **Branch scoping**: `X-Branch-Id` header injection from localStorage
- **Safe API consumption**: `res.data?.items ?? []`, `?? 0`, AbortController cleanup in useEffect
- **All invoice calculations**: subtotal, discount (% or $), GST (inclusive/exclusive/exempt per line), shipping, adjustment, total — exact formulas in section "Frontend Logic to Preserve" below
- **Status colour mapping** for invoices, jobs, etc.
- **Currency formatting**: `formatNZD()` — `NZD1,234.56`
- **Job card sorting**: `in_progress` first, then `open`, then by created_at desc
- **Credit note / refund computations**: `computeCreditableAmount()`, `computePaymentSummary()`
- **Invoice template styling**: `resolveTemplateStyles()` for org-customized colours

### 3. STACK — Use exactly this
- React 18 + TypeScript + Vite 6 (existing)
- **Add: Konsta UI v5** (`konsta` package)
- **Tailwind CSS 4** (upgrade from current default Tailwind if needed)
- Capacitor 6 (existing, keep)
- React Router DOM v7 (existing, keep)
- Axios (existing, keep)
- **Add Capacitor plugins**: `@capacitor/camera`, `@capacitor/geolocation`, `@capacitor/push-notifications`, `@capacitor/preferences`, `@capacitor/network`, `@capacitor/haptics`, `@capacitor/status-bar`, `@capacitor/splash-screen`

### 4. THEME — Use existing brand colours, do not invent new ones
```css
--konsta-primary: #2563EB        /* blue-600, primary brand */
--konsta-primary-rgb: 37 99 235
--konsta-success: #059669        /* emerald-600, paid */
--konsta-warning: #D97706        /* amber-600, partial */
--konsta-danger: #DC2626         /* red-600, overdue */
--konsta-info: #2563EB           /* blue-600, issued */
--konsta-neutral: #6B7280        /* gray-500, draft */

/* Dark surfaces */
--konsta-bg-dark: #0F172A        /* slate-900 */
--konsta-bg-darker: #312E81      /* indigo-900 hero */

/* Text */
--konsta-text-primary: #111827   /* gray-900 */
--konsta-text-secondary: #4B5563 /* gray-600 */
--konsta-text-muted: #9CA3AF     /* gray-400 */

/* Surfaces */
--konsta-card-border: #E5E7EB    /* gray-200 */
--konsta-section-bg: #F9FAFB     /* gray-50 */
```

**Honour TenantContext CSS variables** (`--color-primary`, `--color-secondary`, `--sidebar-bg` etc) — these are org-customizable. Theme tokens above are defaults; per-org overrides from TenantContext must still apply.

---

## Step 1 — Install Dependencies

```bash
npm install konsta
npm install -D tailwindcss@latest @tailwindcss/postcss
npm install @capacitor/camera @capacitor/geolocation @capacitor/push-notifications @capacitor/preferences @capacitor/network @capacitor/haptics @capacitor/status-bar @capacitor/splash-screen
npx cap sync
```

Configure `tailwind.config.js` for Konsta:

```js
const konstaConfig = require('konsta/config');

module.exports = konstaConfig({
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: 'var(--color-primary, #2563EB)',
        secondary: 'var(--color-secondary, #1E40AF)',
      }
    }
  }
});
```

Wrap the app root with Konsta's `App` component, theme auto-detected from platform:

```tsx
// main.tsx or App.tsx
import { App as KonstaApp } from 'konsta/react';
import { Capacitor } from '@capacitor/core';

const platform = Capacitor.getPlatform(); // 'ios' | 'android' | 'web'
const theme = platform === 'ios' ? 'ios' : 'material';

<KonstaApp theme={theme} safeAreas>
  {/* existing providers: Auth, Module, Branch, Tenant, FeatureFlag, Locale, Theme, PlatformBranding */}
  {/* existing Router */}
</KonstaApp>
```

Konsta auto-renders iOS-style components on iPhone and Material Design on Android — same component code.

---

## Step 2 — Mobile Navigation Architecture

Replace `OrgLayout` (sidebar nav) with a **mobile-native hybrid pattern**:

### Bottom Tab Bar — 5 tabs only
Always-visible core actions. Use Konsta `Tabbar` + `TabbarLink`.

| Tab | Icon (Ionicons) | Route | Module Gate |
|-----|-----------------|-------|-------------|
| Home | home-outline | `/dashboard` | none |
| Invoices | document-text-outline | `/invoices` | none |
| Customers | people-outline | `/customers` | none |
| Jobs | construct-outline | `/jobs` or `/job-cards` | `jobs` (hide tab if disabled — fall back to Quotes if `quotes` enabled, else Bookings) |
| More | menu-outline | opens drawer | none |

If `jobs` module disabled, the 4th slot dynamically picks the highest-priority enabled module from: `quotes` → `bookings` → `pos` → fallback to "Reports".

### Drawer / Sheet — Everything Else
Triggered by "More" tab. Use Konsta `Sheet` (bottom sheet) or `Panel` (side drawer). **Apply identical filtering logic to existing sidebar**:

```tsx
const visibleNavItems = allNavItems.filter(item => {
  if (item.module && !isEnabled(item.module)) return false;
  if (item.flagKey && !flags[item.flagKey]) return false;
  if (item.tradeFamily && tradeFamily !== item.tradeFamily) return false;
  if (item.adminOnly && role !== 'org_admin') return false;
  return true;
});
```

Show in this order, grouped by category, with section headers:

**Sales**: Quotes, POS, Recurring, Bookings
**Operations**: Job Cards, Schedule, Time Tracking, Inventory, Items, Purchase Orders
**People**: Staff, Customers (already in tab bar but include for completeness)
**Industry-specific** (only show relevant to trade family):
  - Automotive: Vehicles
  - Construction: Progress Claims, Variations, Retentions
  - Hospitality: Floor Plan, Kitchen Display
**Assets & Compliance**: Assets, Compliance Docs
**Communications**: SMS, Notifications
**Finance**: Reports, Expenses
**Other**: Loyalty, Ecommerce, Claims, Franchise (if enabled)
**Account**: Profile, Logout

Each row: Konsta `ListItem` with leading icon, title, optional badge (e.g. compliance count), chevron, on tap navigate.

### Header (Konsta `Navbar`)
- **Left**: Back button (auto on detail pages) OR menu button (on root pages)
- **Centre**: Page title (truncate long names)
- **Right**: Page-specific actions (search, filter, +, etc)
- **Subtitle slot**: Branch selector pill when `branch_management` module enabled — tap opens branch picker sheet

### Floating Action Button (FAB)
On list pages (`/invoices`, `/customers`, `/job-cards`, `/quotes`, `/bookings`): bottom-right Konsta-styled FAB → primary creation action for that screen.

### Pull-to-refresh
On every list page. Use Konsta `Page` `ptr` prop wired to refetch.

### Haptics
On every primary tap, use `@capacitor/haptics` `Haptics.impact({ style: ImpactStyle.Light })`.

---

## Step 3 — Page-by-Page Mobile Redesign

For **each** of the following pages, generate a Konsta UI mobile screen. Preserve all data fields, all actions, all module gates. The screens listed below are the complete set — do not skip any. Do not "simplify" by removing fields.

### 3.1 Authentication and Public

#### `/login` — Login
- Konsta `Page` with hero header (gradient slate-900 → indigo-900)
- Org logo (placeholder OraInvoice logo)
- `List` with Konsta `ListInput` for email + password
- Primary `Button` "Sign In" (full width, large)
- Divider with "or"
- Secondary buttons: "Continue with Google", "Sign in with Passkey"
- Footer links: "Forgot password?", "Create account"
- Dark/light aware
- POSTs to existing `POST /auth/login` — flow unchanged
- Native: store nothing in localStorage that wasn't there before; use `@capacitor/preferences` for persistence ONLY of branch selection and locale

#### `/login/mfa` — MFA Verify
- Page with `Block` for instructions
- 6-digit code input (single Konsta `ListInput` with numeric keyboard, autoFocus)
- Method selector segmented control (TOTP, SMS, Email, Passkey, Backup)
- "Verify" primary button
- "Try another method" link
- POSTs to `POST /auth/mfa/verify` — unchanged

#### `/signup` — Signup Wizard
- Multi-step Konsta page with progress dots
- Step 1: Account (name, email, password, business name)
- Step 2: Plan selection (Mech Pro Plan card, $60 NZD/month)
- Step 3: Stripe Elements (CardForm component, embed in Konsta `Block`)
- Step 4: Confirmation
- Stripe integration unchanged

#### `/forgot-password`, `/reset-password`, `/verify-email`
- Simple single-form Konsta pages, primary button per page
- API calls unchanged

#### `/` — Landing Page (mobile-optimized marketing)
- Hero with gradient bg, headline, CTA buttons (Sign Up, Login)
- Feature cards in vertical stack (was horizontal grid on desktop)
- Pricing card
- Footer

#### `/pay/:token` — Public Invoice Payment
- Page with invoice summary card (org logo, invoice #, customer, line items collapsed, total)
- Konsta `Block` with Stripe Elements card form
- "Pay NZD X,XXX.XX" primary button
- API: `GET /public/invoice/:token`, Stripe Elements unchanged

---

### 3.2 Dashboard (`/dashboard`)

- **Header**: "Hello, {first_name}" + branch selector subtitle
- **Stat cards** (Konsta `Card`, 2-column grid on phone, swipeable carousel if more than 4):
  - Revenue (this month) — green if up, red if down vs last month
  - Outstanding receivables
  - Overdue count (red badge if > 0)
  - Active jobs (only if `jobs` module enabled)
- **Quick actions row**: scrollable horizontal Konsta `Chip` buttons → New Invoice, New Customer, New Quote (if `quotes`), New Job (if `jobs`), New Booking (if `bookings`)
- **Recent invoices** section — `BlockTitle "Recent Invoices"` + Konsta `List` of last 5 invoices, tap to navigate
- **Overdue alerts** — `BlockTitle "Needs Attention"` + list of overdue invoices with red status indicator
- **Compliance alerts** (if `compliance_docs` module + any expiring) — yellow card with count
- API: `GET /dashboard/stats`, `GET /invoices?status=overdue` — unchanged
- Pull-to-refresh

---

### 3.3 Invoices

#### `/invoices` — Invoice List
**Replace the desktop split-pane (sidebar list + right detail) with mobile pattern**: full-screen list, tap row → push to detail screen.

- Header: title "Invoices", right action: search icon + filter icon
- Search: tapping opens Konsta `Searchbar` with status filter chips below (All, Draft, Issued, Partially Paid, Paid, Overdue, Voided, Refunded, Partially Refunded)
- List items (Konsta `ListItem` with custom layout):
  - Top line: Customer name (bold) + Invoice number (muted)
  - Middle line: NZD total (right-aligned, large)
  - Bottom line: Status badge (colored chip) + Due date + Stripe icon + paperclip if `attachment_count > 0`
  - Swipe-left actions: Mark Sent, Email, Void
  - Swipe-right actions: Record Payment, Duplicate
- Infinite scroll pagination (25 per page), not numbered pages
- FAB: "+ New Invoice" → `/invoices/new`
- Pull-to-refresh
- API endpoints unchanged

#### `/invoices/:id` — Invoice Detail (NEW screen — mobile equivalent of right pane)
- Header: invoice number + back button + overflow menu (•••)
- Hero card: Customer name, vehicle (if any), status badge large, total NZD large, balance due
- Sections (Konsta `Block`):
  - **Vehicles**: rego, make, model, odometer (if vehicles module enabled)
  - **Line items**: collapsible list, qty × rate = amount
  - **Totals**: subtotal, discount, GST, shipping, adjustment, total — exact same logic
  - **Payments**: list of `PaymentRecord` items (date, method, amount)
  - **Credit notes**: if any, list
  - **Attachments**: thumbnail row, tap to view, + button to add (uses **Capacitor Camera** for new)
  - **Notes**: customer-visible + internal (if user role allows)
- Bottom sheet action menu (overflow tap): Email, Mark Sent, Void, Duplicate, Download PDF, Print, Print POS Receipt, Record Payment, Create Credit Note, Process Refund, Share Link, Send Reminder, Delete
- All actions hit existing API endpoints
- Use Konsta `Sheet` for modals (record payment, void reason, credit note, refund)

#### `/invoices/new` and `/invoices/:id/edit` — Invoice Create/Edit
**Largest form in the app — must be split into mobile-native steps OR use a single-page accordion. Recommended: stepper.**

Steps (Konsta `Block` per step, "Next" button between):
1. **Customer & Vehicle**
   - Customer selector — searchable list (Konsta `Searchbar` + `List` of results from `GET /customers?search=`)
   - Vehicles selector — searchable, multi-select chip pills (Konsta `Chip` removable). Show vehicle search via existing `VehicleLiveSearch` component. CarJam lookup integration preserved (only if `vehicles` module + automotive-transport trade).
2. **Dates & Meta**
   - Issue date (Konsta date input)
   - Due date
   - Payment terms (Konsta `ListInput` type select)
   - Salesperson (Konsta select, populated from `GET /org/salespeople`)
   - Subject text
   - Order number
   - GST number (auto from org, read-only)
3. **Line Items**
   - List of line items (Konsta `Card` per item)
   - Each item: description, qty, rate, tax mode (incl/excl/exempt), discount, amount (computed)
   - "Add from Catalogue" button → opens sheet with `GET /catalogue/items` searchable list
   - "Add from Inventory" button → opens sheet with `GET /inventory/stock-items` (only if `inventory` module enabled)
   - "Add Labour" button → opens sheet with `GET /catalogue/labour-rates`
   - "Add Empty Line" → adds blank line item
   - **Calculations live-updated using exact existing logic** (see Frontend Logic section below)
4. **Adjustments**
   - Discount (% or $ toggle)
   - Shipping charges
   - Adjustment
5. **Notes & Attachments**
   - Customer notes (textarea)
   - Internal notes (textarea)
   - Terms & conditions (textarea)
   - Attachments: file upload + **Camera button** (uses `@capacitor/camera` to take photo of receipt/invoice and attach). Max 5 files, 20MB each.
6. **Review & Save**
   - Summary card
   - Buttons: "Save as Draft", "Save & Send" (email), "Mark Paid & Email" (only if balance is zero), "Make Recurring" toggle (creates recurring template)
   - Payment method selector (cash/eftpos/bank_transfer/stripe) if recording payment now

API endpoints unchanged: `POST /invoices`, `PUT /invoices/:id`, `GET /catalogue/items`, `GET /org/salespeople`, `GET /inventory/stock-items`, `GET /catalogue/labour-rates`, `POST /invoices/:id/attachments`, `GET /payments/online-payments/status`.

---

### 3.4 Customers

#### `/customers` — Customer List
- Konsta `Searchbar` (sticky)
- Konsta `List` with `ListItem` per customer:
  - Title: display_name or `${first_name} ${last_name}`
  - After: receivables badge (red if > 0)
  - Subtitle: company_name or phone
- Infinite scroll
- FAB: "+ New Customer"
- Tap row → `/customers/:id`

#### `/customers/new` — Customer Create
- Single-page Konsta form
- Fields: First Name (required), Last Name, Company Name, Email, Phone, Mobile Phone, Work Phone, Address (textarea)
- "Save" + "Save & Add Another" buttons
- POST `/customers` unchanged

#### `/customers/:id` — Customer Profile
- Header card: avatar (initials), name, company, primary contact buttons (call, email, SMS — open native via `tel:`, `mailto:`, `sms:`)
- Tabs (Konsta `Segmented`): Profile · Invoices · Vehicles · Reminders · History
- **Profile tab**: read-only fields, "Edit" button → modal form
- **Invoices tab**: list of customer's invoices with status, total
- **Vehicles tab**: list of linked_vehicles (only if `vehicles` module + automotive trade)
- **Reminders tab**: WOF reminders, service reminders config (existing `GET /customers/:id/reminders`)
- **History tab**: communication log
- API endpoints unchanged

---

### 3.5 Quotes (gated: `quotes`)

#### `/quotes` — Quote List
- Same pattern as invoice list
- Status filters: Draft, Sent, Accepted, Declined, Expired
- FAB: "+ New Quote"

#### `/quotes/new` — Quote Create
- Same stepper pattern as invoice create but simpler:
  1. Customer
  2. Line items
  3. Discount, terms, notes, expiry date
  4. Save / Send

#### `/quotes/:id` — Quote Detail
- Hero card with customer, total, status
- Line items list
- Bottom action sheet: Send, Convert to Invoice, Edit, Duplicate
- API unchanged

---

### 3.6 Job Cards (gated: `jobs`)

#### `/job-cards` — Job Card List
- List with sorting: in_progress first, open second, completed/invoiced last (preserve `statusOrder` logic)
- Status colour pill
- Subtitle: vehicle rego + customer name
- After: assigned-to avatar
- Filter: status, assigned to me toggle
- FAB: "+ New Job Card"

#### `/job-cards/new` — Job Card Create
- Stepper:
  1. Customer & Vehicle (same selectors as invoice)
  2. Description, service type, assigned staff
  3. Parts (from inventory, only if `inventory` module)
  4. Labour entries (from labour rates)
  5. Save

#### `/job-cards/:id` — Job Card Detail
- Hero: customer, vehicle, status, assigned staff
- Sections: Parts, Labour, Notes, Attachments (with **Camera** button for photos), Status History
- Bottom actions: Edit, Add Parts, Add Labour, Upload Attachment, **Complete Job** (creates invoice — links to invoice on completion), Reassign

#### `/jobs` — Active Jobs Board (timer screen)
- Card-based view of in-progress + open jobs
- Each card: customer, vehicle, **live timer** (HH:MM:SS, updates every second) if started
- Buttons per card:
  - Start Timer / Stop Timer (toggle)
  - Assign to Me
  - Take Over (if assigned to other)
  - Confirm Done → triggers complete flow
- Use Konsta `Card` with prominent timer
- API endpoints unchanged: `POST /job-cards/:id/start-timer`, `POST /job-cards/:id/stop-timer`, etc.
- **Optionally request GPS** (`@capacitor/geolocation`) on Start Timer to log job site location — wire to backend if endpoint accepts it, otherwise skip silently
- Haptics on timer start/stop

---

### 3.7 Vehicles (gated: `vehicles` + automotive-transport trade)

#### `/vehicles` — Vehicle List
- Searchbar (search by rego)
- List items: rego (large, monospace), make/model/year, owner name, WOF expiry pill (red if expired, amber if <30 days)
- FAB: not needed (vehicles created from customer or invoice flow)

#### `/vehicles/:id` — Vehicle Profile
- Hero: large rego, make/model/year/colour
- Stats: WOF expiry, rego expiry, odometer, service due date
- Sections: Service History (linked invoices/jobs), Linked Customer
- "Edit" button for dates

---

### 3.8 Bookings (gated: `bookings`)

#### `/bookings` — Booking Calendar
- Konsta-styled calendar view (use Konsta-compatible calendar lib like `react-day-picker` styled to match)
- List of bookings for selected date below calendar
- Tap booking → edit sheet
- FAB: "+ New Booking"
- Drag-and-drop reschedule **dropped on mobile** — use long-press menu instead with date picker
- "Create Job from Booking" action in booking detail sheet

---

### 3.9 Inventory (gated: `inventory`)

#### `/inventory` — Inventory
- Konsta tabs: Stock Levels · Usage History · Update Log · Reorder Alerts · Suppliers
- **Stock Levels tab**: searchable list, columns reduced for mobile (item name, available qty, sell price, brand-as-subtitle)
- Tap item → detail sheet with all StockItem fields, "Adjust Stock" action
- Reorder Alerts: red-bordered cards
- CSV import: keep button, opens file picker (Capacitor Filesystem if needed)

#### `/items` — Catalogue Items
- Tabs: Items · Labour Rates · Service Types
- List of CatalogueItem with name, default_price, GST applicable badge
- Tap → edit sheet
- FAB: "+ Add Item"

---

### 3.10 Other Modules (Mobile Patterns)

For each of these, follow the same pattern: list → detail → form. Preserve module gates, all fields, all API endpoints.

- **`/staff`** (gated: `staff`) — staff list, role badges, edit sheet
- **`/projects`** (gated: `projects`) — project list with progress bars, dashboard with budget/tasks
- **`/expenses`** (gated: `expenses`) — expense list, **Camera button for receipt** in create form, category picker
- **`/time-tracking`** (gated: `time_tracking`) — clock-in/clock-out big buttons, today's entries list, manual entry form
- **`/schedule`** (gated: `scheduling`) — calendar view of staff/bay schedule
- **`/pos`** (gated: `pos`) — full-screen mobile POS layout: product grid (Konsta `Card` grid 2 col), order panel as bottom sheet (drag up to expand), payment as final sheet. Uses existing catalogue items, posts invoice + cash payment.
- **`/recurring`** (gated: `recurring_invoices`) — list of templates with frequency badge, pause/resume swipe action
- **`/purchase-orders`** (gated: `purchase_orders`) — list with status, detail with line items, receive stock action
- **Construction** (gated by trade `construction`):
  - `/progress-claims` — claim list, create form
  - `/variations` — variation list with cost impact
  - `/retentions` — retention summary by project, release action
- **Hospitality** (gated by trade `hospitality`):
  - `/floor-plan` — visual table layout (use SVG or canvas), tap table to seat customer
  - `/kitchen` — full-screen kitchen display, large cards, tap to mark ready, auto-refresh every 5s
- **`/assets`** (gated: `assets`) — asset list, depreciation schedule, maintenance log
- **`/compliance`** (gated: `compliance_docs`) — document list with expiry pills, upload via **Camera or file picker**, summary cards at top (count by status: valid, expiring, expired)
- **`/sms`** (gated: `sms`) — chat-style conversation list (Konsta `Messages` component), conversation thread view with send composer
- **`/reports`** — report hub with category cards (Sales, Finance, Operations, Industry), select report → date range picker → run → display chart/table → export buttons (PDF, CSV)
- **`/notifications`** — preferences list with toggles (Konsta `Toggle`), overdue rules, reminder templates editor
- **`/portal`** (public customer self-service) — keep existing logic, restyle to Konsta
- **`/kiosk`** — large-button check-in screen, designed for tablet but must work on phone

### Excluded from Mobile (per requirements)
- `/settings` and all org admin sub-pages
- `/branch-transfers`, `/staff-schedule` (adminOnly)
- `/franchise/*` (admin)
- `/data` (bulk import/export)
- `/accounting`, `/accounting/journals`, `/banking/*`, `/tax/*` — view-only pages may stay if needed for end-user reporting, but not the editors

---

## Step 4 — Native Mobile Features

Wire these into the relevant pages:

### Camera (`@capacitor/camera`)
Used for:
- Invoice attachments (`/invoices/:id`, `/invoices/new` step 5)
- Job card attachments (`/job-cards/:id`)
- Compliance document upload (`/compliance`)
- Expense receipts (`/expenses/new`)

```ts
import { Camera, CameraResultType, CameraSource } from '@capacitor/camera';

const photo = await Camera.getPhoto({
  quality: 85,
  resultType: CameraResultType.Uri,
  source: CameraSource.Prompt,  // user picks camera or gallery
});
// Upload photo.webPath as multipart to existing /attachments endpoint
```

iOS Info.plist needs:
```xml
<key>NSCameraUsageDescription</key>
<string>Capture invoice attachments, receipts and compliance documents</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>Select photos for attachments and receipts</string>
```

Android `AndroidManifest.xml`:
```xml
<uses-permission android:name="android.permission.CAMERA" />
```

### Geolocation (`@capacitor/geolocation`)
Used for:
- Logging job site location on `/jobs` start timer
- Optional: logging customer creation location

```ts
import { Geolocation } from '@capacitor/geolocation';
const pos = await Geolocation.getCurrentPosition({ enableHighAccuracy: false, timeout: 5000 });
// Send pos.coords.latitude, pos.coords.longitude with start-timer call IF backend accepts it
```

Permission strings:
- iOS: `NSLocationWhenInUseUsageDescription` — "Tag job locations for accurate site tracking"
- Android: `ACCESS_COARSE_LOCATION`, `ACCESS_FINE_LOCATION`

Wire silently — if backend doesn't accept geo, just don't send. Don't break existing flows.

### Push Notifications (`@capacitor/push-notifications`)
Used for:
- New invoice paid online (Stripe)
- Invoice overdue alerts
- Job assigned to me
- Booking reminders
- Compliance document expiring soon
- New SMS received

Setup:
```ts
import { PushNotifications } from '@capacitor/push-notifications';

await PushNotifications.requestPermissions();
await PushNotifications.register();

PushNotifications.addListener('registration', async (token) => {
  // POST token.value to your FastAPI backend, e.g. /notifications/register-device
  // Backend stores per-user, used to send via FCM
});

PushNotifications.addListener('pushNotificationReceived', (notif) => {
  // In-app foreground notification — show Konsta Toast
});

PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
  // Deep-link based on action.notification.data.route
  // e.g. { route: '/invoices/abc123' } → router.push(...)
});
```

Backend integration: add a new endpoint `POST /notifications/devices/register` accepting `{ token, platform }`. Store linked to user_id. When events fire (invoice paid, overdue, etc), backend dispatches via Firebase Cloud Messaging using stored tokens.

Do NOT implement the backend FCM dispatcher in this task — only the device-side registration and listeners. Flag the backend work as a follow-up TODO.

### Network awareness (`@capacitor/network`)
- Show offline banner (Konsta `Block` red) at top of app when offline
- Queue mutations? — out of scope for this redesign, just show banner

### Haptics (`@capacitor/haptics`)
- Light impact on every primary button tap
- Medium impact on toggle changes, status changes
- Heavy impact on destructive confirmations (delete, void)
- Selection on swipe action

### Status Bar + Splash Screen
- Configure splash screen with org logo, primary brand colour background
- Status bar: dark on light backgrounds, light on slate-900 hero screens

---

## Step 5 — Frontend Logic to Preserve (Verbatim)

These calculations and helpers MUST be preserved exactly. Copy them from the existing codebase to the new mobile components.

### Invoice subtotal/discount/GST/total
```typescript
const subTotal = lineItems.reduce((sum, item) => sum + item.amount, 0);

const discountAmount = discountType === 'percentage'
  ? (subTotal * discountValue / 100)
  : discountValue;

const afterDiscount = subTotal - discountAmount;

const taxAmount = lineItems.reduce((sum, item) => {
  if (item.tax_rate <= 0) return sum;
  if (item.gst_inclusive && item.inclusive_price) {
    const inclTotal = Math.round(item.quantity * item.inclusive_price * 100) / 100;
    const gst = Math.round((inclTotal - item.amount) * 100) / 100;
    return sum + gst;
  }
  return sum + Math.round(item.amount * item.tax_rate) / 100;
}, 0);

const total = afterDiscount + taxAmount + shippingCharges + adjustment;
```

### Status colour map (use across list items, badges, hero cards)
```typescript
const STATUS_CONFIG = {
  draft:              { label: 'DRAFT',              color: 'text-gray-500',     bg: 'bg-gray-100' },
  issued:             { label: 'ISSUED',             color: 'text-blue-600',     bg: 'bg-blue-100' },
  partially_paid:     { label: 'PARTIALLY PAID',     color: 'text-amber-600',    bg: 'bg-amber-100' },
  paid:               { label: 'PAID',               color: 'text-emerald-600',  bg: 'bg-emerald-100' },
  overdue:            { label: 'OVERDUE',            color: 'text-red-600',      bg: 'bg-red-100' },
  voided:             { label: 'VOIDED',             color: 'text-gray-400',     bg: 'bg-gray-50' },
  refunded:           { label: 'REFUNDED',           color: 'text-orange-600',   bg: 'bg-orange-100' },
  partially_refunded: { label: 'PARTIALLY REFUNDED', color: 'text-orange-600',   bg: 'bg-orange-100' },
};
```

### Job card sorting
```typescript
const statusOrder = (s: string) => (s === 'in_progress' ? 0 : s === 'open' ? 1 : 2);
const sortedJobs = [...jobs].sort((a, b) => {
  const orderDiff = statusOrder(a.status) - statusOrder(b.status);
  if (orderDiff !== 0) return orderDiff;
  return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
});
```

### Currency formatting
```typescript
function formatNZD(amount: number | null | undefined): string {
  return `NZD${Number(amount ?? 0).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}
```

### Safe API consumption (mandatory, every request)
```typescript
useEffect(() => {
  const controller = new AbortController();
  api.get('/invoices', { signal: controller.signal })
    .then(res => setItems(res.data?.items ?? []))
    .catch(err => { if (!axios.isCancel(err)) handleError(err); });
  return () => controller.abort();
}, [deps]);
```

### Module gating in components
```typescript
const { isEnabled } = useModules();
if (!isEnabled('jobs')) return null;
```

### Branch header injection (existing axios interceptor — do not change)
```typescript
api.interceptors.request.use((config) => {
  const branchId = localStorage.getItem('selectedBranchId');
  if (branchId) config.headers['X-Branch-Id'] = branchId;
  return config;
});
```

### Credit note / refund computations
Preserve `computeCreditableAmount(total, creditNoteAmounts)` and `computePaymentSummary(payments)` helpers exactly.

### Invoice template styling
Preserve `resolveTemplateStyles(templateId, colours)` for org-customized invoice colours in the public invoice payment view.

---

## Step 6 — Acceptance Criteria

The redesign is done when:

1. ✅ Konsta UI v5 is installed and the app root is wrapped in `<App theme={ios|material} safeAreas>`
2. ✅ Bottom tab nav with 5 tabs renders, "More" tab opens a sheet with all enabled module nav items
3. ✅ Sheet/drawer filters items using identical `module + flag + trade + role` logic
4. ✅ Every page listed in section 3 has a Konsta-styled mobile screen
5. ✅ All eight contexts still wrap the app and function unchanged
6. ✅ All `ModuleRoute` and `ModuleGate` usages still gate routes and components
7. ✅ All API endpoints from section 11 of the inventory report are called identically (no signature changes)
8. ✅ All invoice calculations match the existing logic byte-for-byte
9. ✅ Pull-to-refresh on every list page
10. ✅ FAB on every list page that supports creation
11. ✅ Camera plugin wired into invoice attachments, job card attachments, compliance, expenses
12. ✅ Push notification registration on login, listener on receive
13. ✅ Geolocation called on job timer start (silent, optional)
14. ✅ Haptics on all primary actions
15. ✅ Capacitor Info.plist and AndroidManifest.xml updated with all required permissions
16. ✅ Status bar style adapts per screen
17. ✅ Splash screen configured
18. ✅ App tested on iOS simulator and Android emulator before declaring done
19. ✅ TenantContext brand-colour overrides still apply (test by changing org primary colour)
20. ✅ Excluded screens are not built (admin, org admin, branch transfers, staff schedule, franchise admin, data import/export, accounting/banking/tax editors)

---

## Step 7 — Final Checks Before Commit

Run through this checklist:

- [ ] No screen in the inventory report (section 2) is missing from the mobile build, except those listed in "Excluded from Mobile"
- [ ] No data field in section 3 (Data Models) is omitted from any screen — all fields render somewhere
- [ ] No API endpoint in section 11 has a changed call signature
- [ ] All 27 module slugs (section 8) are honoured — every gated screen wrapped in `ModuleRoute`
- [ ] Trade-family filtering applies (automotive, construction, hospitality)
- [ ] Role-based filtering applies (org_admin sees admin items; salesperson does not)
- [ ] Branch context still scopes all data
- [ ] Auth flow (login → MFA → JWT in memory → refresh on 401) untouched
- [ ] All forms in section 5 build to mobile screens with all listed fields and validation rules

---

## Notes for Kiro

- **Do not abbreviate.** Generate every screen listed. If context is exhausted, generate them in batches of 5 and continue in subsequent runs — but do not skip.
- **Do not invent new fields or new API endpoints.** Use only what's in the inventory report.
- **Do not "simplify"** by removing actions, fields, or modules.
- **If unclear** whether something is admin-only or end-user, default to **end-user** but flag it in a TODO comment.
- **Match the visual quality** of native iOS Mail, Notes, Reminders apps for iOS theme; Material Design 3 for Android theme. Generic-looking output is a fail.
- **Code organisation**: place new mobile screens in `src/mobile/pages/`, mobile components in `src/mobile/components/`, keep desktop screens untouched in `src/pages/`. Use a build flag or runtime check (`Capacitor.isNativePlatform()`) to switch which version renders.

End of prompt.
