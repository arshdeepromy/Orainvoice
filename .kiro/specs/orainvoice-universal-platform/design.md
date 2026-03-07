# Technical Design Document

## Overview

This document describes the technical design for the OraInvoice Universal Platform enhancement. The platform expands from a NZ workshop invoicing SaaS into a globally capable, multi-trade, multi-industry invoicing and business management platform. The design layers on top of the existing V1 foundation (FastAPI, PostgreSQL, React/TypeScript, Celery/Redis, Stripe, Carjam) without replacing it.

### Architecture Principles

1. **Additive Enhancement** — All new features layer on top of V1. No existing tables, endpoints, or UI components are removed or renamed.
2. **Module Isolation** — Each feature module is self-contained with its own models, routers, services, and frontend pages. Disabled modules are invisible at every layer.
3. **Tenant Isolation** — All data is scoped to an organisation via `org_id` foreign keys. Cross-tenant access is impossible at the ORM level.
4. **API Versioning** — New endpoints live under `/api/v2/`. V1 endpoints remain unchanged with deprecation headers.
5. **Feature Flags** — All new modules are gated behind feature flags for gradual rollout.
6. **Eventual Consistency for Side Effects** — Core data mutations are transactional. Notifications, sync, and reporting are async via Celery.

## System Architecture

### High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENTS                                   │
│  React SPA │ Customer Portal │ POS (PWA) │ Kitchen Display │ API │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────▼──────────────────────────────────────┐
│                     NGINX / ALB                                  │
│              TLS termination, rate limiting                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   FastAPI Application                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────────┐   │
│  │ /api/v1/ │ │ /api/v2/ │ │ Webhooks │ │ Module Middleware │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Module Router Registry                       │   │
│  │  trade_categories │ inventory │ jobs │ pos │ ecommerce   │   │
│  │  quotes │ time_tracking │ projects │ expenses │ staff    │   │
│  │  scheduling │ bookings │ tipping │ tables │ kitchen      │   │
│  │  retentions │ progress_claims │ variations │ compliance  │   │
│  │  multi_currency │ loyalty │ franchise │ branding         │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              Core Services                                │   │
│  │  auth │ tenant │ feature_flags │ terminology │ modules   │   │
│  │  audit │ encryption │ storage │ pdf │ notifications      │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│  PostgreSQL  │  │    Redis     │  │    Celery     │
│  (per-region)│  │  (cache +    │  │  (workers)    │
│              │  │   flags +    │  │              │
│              │  │   sessions)  │  │              │
└──────────────┘  └──────────────┘  └──────────────┘
          │                                │
          ▼                                ▼
┌──────────────┐                  ┌──────────────┐
│  S3 / Blob   │                  │  External    │
│  (per-region)│                  │  Services    │
│  file storage│                  │  Stripe,     │
│              │                  │  WooCommerce,│
│              │                  │  Carjam, etc │
└──────────────┘                  └──────────────┘
```

### Data Residency Architecture

Each data residency region (NZ/AU, UK/EU, North America) has its own:
- PostgreSQL instance (primary + read replica)
- S3-compatible object storage bucket
- Redis cluster for caching

A global routing layer maps each organisation to its region based on the `data_residency_region` field set during onboarding. The application connects to the correct regional database using a connection router middleware.

### API Versioning Strategy

- `/api/v1/*` — Existing V1 endpoints, unchanged. Deprecation headers added pointing to v2 equivalents.
- `/api/v2/*` — New universal platform endpoints. All new modules register here.
- Both versions share the same authentication middleware and tenant resolution.
- V1 endpoints are maintained for 12 months post-v2 GA, then return HTTP 410.

## Database Schema

### New Core Tables

#### trade_families
```sql
CREATE TABLE trade_families (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    icon VARCHAR(100),
    display_order INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### trade_categories
```sql
CREATE TABLE trade_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    family_id UUID REFERENCES trade_families(id) NOT NULL,
    icon VARCHAR(100),
    description TEXT,
    invoice_template_layout VARCHAR(100) DEFAULT 'standard',
    recommended_modules JSONB DEFAULT '[]',
    terminology_overrides JSONB DEFAULT '{}',
    default_services JSONB DEFAULT '[]',
    default_products JSONB DEFAULT '[]',
    default_expense_categories JSONB DEFAULT '[]',
    default_job_templates JSONB DEFAULT '[]',
    compliance_notes JSONB DEFAULT '{}',
    seed_data_version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE,
    is_retired BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_trade_categories_family ON trade_categories(family_id);
CREATE INDEX idx_trade_categories_active ON trade_categories(is_active, is_retired);
```

#### feature_flags
```sql
CREATE TABLE feature_flags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    default_value BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    targeting_rules JSONB DEFAULT '[]',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### module_registry
```sql
CREATE TABLE module_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(100) UNIQUE NOT NULL,
    display_name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(100),
    is_core BOOLEAN DEFAULT FALSE,
    dependencies JSONB DEFAULT '[]',
    incompatibilities JSONB DEFAULT '[]',
    status VARCHAR(20) DEFAULT 'available',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### org_modules (enabled modules per org)
```sql
CREATE TABLE org_modules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    module_slug VARCHAR(100) NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    enabled_at TIMESTAMPTZ DEFAULT NOW(),
    enabled_by UUID REFERENCES users(id),
    UNIQUE(org_id, module_slug)
);
CREATE INDEX idx_org_modules_org ON org_modules(org_id);
```

#### org_terminology_overrides
```sql
CREATE TABLE org_terminology_overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    generic_key VARCHAR(100) NOT NULL,
    custom_label VARCHAR(255) NOT NULL,
    UNIQUE(org_id, generic_key)
);
```

#### organisations table extensions (ALTER TABLE)
```sql
ALTER TABLE organisations ADD COLUMN trade_category_id UUID REFERENCES trade_categories(id);
ALTER TABLE organisations ADD COLUMN secondary_trade_ids UUID[] DEFAULT '{}';
ALTER TABLE organisations ADD COLUMN country_code VARCHAR(2);
ALTER TABLE organisations ADD COLUMN data_residency_region VARCHAR(20) DEFAULT 'nz-au';
ALTER TABLE organisations ADD COLUMN base_currency VARCHAR(3) DEFAULT 'NZD';
ALTER TABLE organisations ADD COLUMN locale VARCHAR(10) DEFAULT 'en-NZ';
ALTER TABLE organisations ADD COLUMN tax_label VARCHAR(20) DEFAULT 'GST';
ALTER TABLE organisations ADD COLUMN default_tax_rate DECIMAL(5,2) DEFAULT 15.00;
ALTER TABLE organisations ADD COLUMN tax_inclusive_default BOOLEAN DEFAULT TRUE;
ALTER TABLE organisations ADD COLUMN date_format VARCHAR(20) DEFAULT 'dd/MM/yyyy';
ALTER TABLE organisations ADD COLUMN number_format VARCHAR(20) DEFAULT 'en-NZ';
ALTER TABLE organisations ADD COLUMN timezone VARCHAR(50) DEFAULT 'Pacific/Auckland';
ALTER TABLE organisations ADD COLUMN compliance_profile_id UUID REFERENCES compliance_profiles(id);
ALTER TABLE organisations ADD COLUMN setup_wizard_state JSONB DEFAULT '{}';
ALTER TABLE organisations ADD COLUMN is_multi_location BOOLEAN DEFAULT FALSE;
ALTER TABLE organisations ADD COLUMN franchise_group_id UUID REFERENCES franchise_groups(id);
ALTER TABLE organisations ADD COLUMN white_label_enabled BOOLEAN DEFAULT FALSE;
ALTER TABLE organisations ADD COLUMN storage_used_bytes BIGINT DEFAULT 0;
ALTER TABLE organisations ADD COLUMN storage_quota_bytes BIGINT DEFAULT 5368709120;
```

#### compliance_profiles
```sql
CREATE TABLE compliance_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    country_code VARCHAR(2) UNIQUE NOT NULL,
    country_name VARCHAR(100) NOT NULL,
    tax_label VARCHAR(20) NOT NULL,
    default_tax_rates JSONB NOT NULL,
    tax_number_label VARCHAR(50),
    tax_number_regex VARCHAR(255),
    tax_inclusive_default BOOLEAN DEFAULT TRUE,
    date_format VARCHAR(20) NOT NULL,
    number_format VARCHAR(20) NOT NULL,
    currency_code VARCHAR(3) NOT NULL,
    report_templates JSONB DEFAULT '[]',
    gdpr_applicable BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### setup_wizard_progress
```sql
CREATE TABLE setup_wizard_progress (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) UNIQUE NOT NULL,
    step_1_complete BOOLEAN DEFAULT FALSE,
    step_2_complete BOOLEAN DEFAULT FALSE,
    step_3_complete BOOLEAN DEFAULT FALSE,
    step_4_complete BOOLEAN DEFAULT FALSE,
    step_5_complete BOOLEAN DEFAULT FALSE,
    step_6_complete BOOLEAN DEFAULT FALSE,
    step_7_complete BOOLEAN DEFAULT FALSE,
    wizard_completed BOOLEAN DEFAULT FALSE,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Inventory Module Tables

#### product_categories
```sql
CREATE TABLE product_categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    parent_id UUID REFERENCES product_categories(id),
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_product_categories_org ON product_categories(org_id);
CREATE INDEX idx_product_categories_parent ON product_categories(parent_id);
```

#### products
```sql
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    name VARCHAR(255) NOT NULL,
    sku VARCHAR(100),
    barcode VARCHAR(100),
    category_id UUID REFERENCES product_categories(id),
    description TEXT,
    unit_of_measure VARCHAR(20) DEFAULT 'each',
    sale_price DECIMAL(12,2) NOT NULL DEFAULT 0,
    cost_price DECIMAL(12,2) DEFAULT 0,
    tax_applicable BOOLEAN DEFAULT TRUE,
    tax_rate_override DECIMAL(5,2),
    stock_quantity DECIMAL(12,3) DEFAULT 0,
    low_stock_threshold DECIMAL(12,3) DEFAULT 0,
    reorder_quantity DECIMAL(12,3) DEFAULT 0,
    allow_backorder BOOLEAN DEFAULT FALSE,
    supplier_id UUID REFERENCES suppliers(id),
    supplier_sku VARCHAR(100),
    images JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, sku)
);
CREATE INDEX idx_products_org ON products(org_id);
CREATE INDEX idx_products_barcode ON products(org_id, barcode);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_location ON products(location_id);
```

#### stock_movements
```sql
CREATE TABLE stock_movements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    product_id UUID REFERENCES products(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    movement_type VARCHAR(20) NOT NULL,
    quantity_change DECIMAL(12,3) NOT NULL,
    resulting_quantity DECIMAL(12,3) NOT NULL,
    reference_type VARCHAR(50),
    reference_id UUID,
    notes TEXT,
    performed_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_stock_movements_product ON stock_movements(product_id);
CREATE INDEX idx_stock_movements_org_date ON stock_movements(org_id, created_at);
```

#### suppliers
```sql
CREATE TABLE suppliers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    contact_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(50),
    address TEXT,
    notes TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_suppliers_org ON suppliers(org_id);
```

#### pricing_rules
```sql
CREATE TABLE pricing_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    product_id UUID REFERENCES products(id),
    rule_type VARCHAR(30) NOT NULL,
    priority INTEGER DEFAULT 0,
    customer_id UUID REFERENCES customers(id),
    customer_tag VARCHAR(100),
    min_quantity DECIMAL(12,3),
    max_quantity DECIMAL(12,3),
    start_date DATE,
    end_date DATE,
    price_override DECIMAL(12,2),
    discount_percent DECIMAL(5,2),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_pricing_rules_product ON pricing_rules(product_id);
CREATE INDEX idx_pricing_rules_org ON pricing_rules(org_id);
```

### Job Module Tables

#### jobs
```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    job_number VARCHAR(50) NOT NULL,
    customer_id UUID REFERENCES customers(id),
    asset_id UUID REFERENCES assets(id),
    project_id UUID REFERENCES projects(id),
    quote_id UUID REFERENCES quotes(id),
    status VARCHAR(20) DEFAULT 'enquiry',
    site_address TEXT,
    description TEXT,
    checklist JSONB DEFAULT '[]',
    internal_notes TEXT,
    customer_notes TEXT,
    scheduled_start TIMESTAMPTZ,
    scheduled_end TIMESTAMPTZ,
    actual_start TIMESTAMPTZ,
    actual_end TIMESTAMPTZ,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, job_number)
);
CREATE INDEX idx_jobs_org_status ON jobs(org_id, status);
CREATE INDEX idx_jobs_customer ON jobs(customer_id);
CREATE INDEX idx_jobs_project ON jobs(project_id);
```

#### job_staff_assignments
```sql
CREATE TABLE job_staff_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) NOT NULL,
    staff_id UUID REFERENCES staff_members(id) NOT NULL,
    role_label VARCHAR(50) DEFAULT 'assigned',
    assigned_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(job_id, staff_id)
);
```

#### job_attachments
```sql
CREATE TABLE job_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_type VARCHAR(50),
    file_size BIGINT,
    file_data BYTEA,
    storage_key VARCHAR(500),
    include_in_invoice BOOLEAN DEFAULT FALSE,
    uploaded_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_job_attachments_job ON job_attachments(job_id);
```

#### job_status_history
```sql
CREATE TABLE job_status_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) NOT NULL,
    previous_status VARCHAR(20),
    new_status VARCHAR(20) NOT NULL,
    reason TEXT,
    changed_by UUID REFERENCES users(id),
    changed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_job_status_history_job ON job_status_history(job_id);
```

### Quote Module Tables

#### quotes
```sql
CREATE TABLE quotes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    quote_number VARCHAR(50) NOT NULL,
    customer_id UUID REFERENCES customers(id) NOT NULL,
    project_id UUID REFERENCES projects(id),
    status VARCHAR(20) DEFAULT 'draft',
    expiry_date DATE,
    terms TEXT,
    internal_notes TEXT,
    version_number INTEGER DEFAULT 1,
    previous_version_id UUID REFERENCES quotes(id),
    converted_invoice_id UUID REFERENCES invoices(id),
    acceptance_token VARCHAR(255),
    accepted_at TIMESTAMPTZ,
    total_amount DECIMAL(12,2) DEFAULT 0,
    tax_amount DECIMAL(12,2) DEFAULT 0,
    currency VARCHAR(3),
    exchange_rate DECIMAL(12,6),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, quote_number)
);
CREATE INDEX idx_quotes_org_status ON quotes(org_id, status);
CREATE INDEX idx_quotes_customer ON quotes(customer_id);
```

### Time Tracking Tables

#### time_entries
```sql
CREATE TABLE time_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    user_id UUID REFERENCES users(id) NOT NULL,
    staff_id UUID REFERENCES staff_members(id),
    job_id UUID REFERENCES jobs(id),
    project_id UUID REFERENCES projects(id),
    description TEXT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_minutes INTEGER,
    is_billable BOOLEAN DEFAULT TRUE,
    hourly_rate DECIMAL(10,2),
    is_invoiced BOOLEAN DEFAULT FALSE,
    invoice_line_id UUID,
    is_timer_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_time_entries_org_user ON time_entries(org_id, user_id);
CREATE INDEX idx_time_entries_job ON time_entries(job_id);
CREATE INDEX idx_time_entries_project ON time_entries(project_id);
CREATE INDEX idx_time_entries_date ON time_entries(org_id, start_time);
```

### Project Module Tables

#### projects
```sql
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    customer_id UUID REFERENCES customers(id),
    description TEXT,
    budget_amount DECIMAL(12,2),
    contract_value DECIMAL(12,2),
    revised_contract_value DECIMAL(12,2),
    retention_percentage DECIMAL(5,2) DEFAULT 0,
    start_date DATE,
    target_end_date DATE,
    status VARCHAR(20) DEFAULT 'active',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_projects_org ON projects(org_id);
CREATE INDEX idx_projects_customer ON projects(customer_id);
```

### Expense Module Tables

#### expenses
```sql
CREATE TABLE expenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    job_id UUID REFERENCES jobs(id),
    project_id UUID REFERENCES projects(id),
    date DATE NOT NULL,
    description TEXT NOT NULL,
    amount DECIMAL(12,2) NOT NULL,
    tax_amount DECIMAL(12,2) DEFAULT 0,
    category VARCHAR(100),
    receipt_file_key VARCHAR(500),
    is_pass_through BOOLEAN DEFAULT FALSE,
    is_invoiced BOOLEAN DEFAULT FALSE,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_expenses_org ON expenses(org_id);
CREATE INDEX idx_expenses_job ON expenses(job_id);
CREATE INDEX idx_expenses_project ON expenses(project_id);
```

### Purchase Order Tables

#### purchase_orders
```sql
CREATE TABLE purchase_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    po_number VARCHAR(50) NOT NULL,
    supplier_id UUID REFERENCES suppliers(id) NOT NULL,
    job_id UUID REFERENCES jobs(id),
    project_id UUID REFERENCES projects(id),
    status VARCHAR(20) DEFAULT 'draft',
    expected_delivery DATE,
    total_amount DECIMAL(12,2) DEFAULT 0,
    notes TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, po_number)
);
```

#### purchase_order_lines
```sql
CREATE TABLE purchase_order_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    po_id UUID REFERENCES purchase_orders(id) NOT NULL,
    product_id UUID REFERENCES products(id) NOT NULL,
    quantity_ordered DECIMAL(12,3) NOT NULL,
    quantity_received DECIMAL(12,3) DEFAULT 0,
    unit_cost DECIMAL(12,2) NOT NULL,
    line_total DECIMAL(12,2) NOT NULL
);
```

### Staff Module Tables

#### staff_members
```sql
CREATE TABLE staff_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    user_id UUID REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    role_type VARCHAR(20) DEFAULT 'employee',
    hourly_rate DECIMAL(10,2),
    overtime_rate DECIMAL(10,2),
    availability JSONB DEFAULT '{}',
    skills JSONB DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_staff_members_org ON staff_members(org_id);
```

#### staff_location_assignments
```sql
CREATE TABLE staff_location_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    staff_id UUID REFERENCES staff_members(id) NOT NULL,
    location_id UUID REFERENCES locations(id) NOT NULL,
    UNIQUE(staff_id, location_id)
);
```

### Scheduling & Booking Tables

#### schedule_entries
```sql
CREATE TABLE schedule_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    staff_id UUID REFERENCES staff_members(id),
    job_id UUID REFERENCES jobs(id),
    booking_id UUID REFERENCES bookings(id),
    location_id UUID REFERENCES locations(id),
    title VARCHAR(255),
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    entry_type VARCHAR(20) DEFAULT 'job',
    status VARCHAR(20) DEFAULT 'scheduled',
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_schedule_entries_org_date ON schedule_entries(org_id, start_time, end_time);
CREATE INDEX idx_schedule_entries_staff ON schedule_entries(staff_id, start_time);
```

#### bookings
```sql
CREATE TABLE bookings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    customer_id UUID REFERENCES customers(id),
    location_id UUID REFERENCES locations(id),
    staff_id UUID REFERENCES staff_members(id),
    service_id UUID REFERENCES catalogue_items(id),
    customer_name VARCHAR(255) NOT NULL,
    customer_email VARCHAR(255),
    customer_phone VARCHAR(50),
    booking_date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    status VARCHAR(20) DEFAULT 'confirmed',
    notes TEXT,
    confirmation_token VARCHAR(255),
    cancellation_token VARCHAR(255),
    converted_job_id UUID REFERENCES jobs(id),
    converted_invoice_id UUID REFERENCES invoices(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_bookings_org_date ON bookings(org_id, booking_date);
```

#### booking_rules
```sql
CREATE TABLE booking_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    min_advance_hours INTEGER DEFAULT 2,
    max_advance_days INTEGER DEFAULT 90,
    default_slot_minutes INTEGER DEFAULT 60,
    buffer_minutes INTEGER DEFAULT 15,
    available_days JSONB DEFAULT '[1,2,3,4,5]',
    available_hours JSONB DEFAULT '{"start":"09:00","end":"17:00"}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### POS Tables

#### pos_sessions
```sql
CREATE TABLE pos_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    user_id UUID REFERENCES users(id) NOT NULL,
    opened_at TIMESTAMPTZ DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    opening_cash DECIMAL(12,2) DEFAULT 0,
    closing_cash DECIMAL(12,2),
    status VARCHAR(20) DEFAULT 'open'
);
```

#### pos_transactions
```sql
CREATE TABLE pos_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    session_id UUID REFERENCES pos_sessions(id),
    invoice_id UUID REFERENCES invoices(id),
    customer_id UUID REFERENCES customers(id),
    table_id UUID REFERENCES restaurant_tables(id),
    offline_transaction_id VARCHAR(100),
    payment_method VARCHAR(20) NOT NULL,
    subtotal DECIMAL(12,2) NOT NULL,
    tax_amount DECIMAL(12,2) NOT NULL,
    discount_amount DECIMAL(12,2) DEFAULT 0,
    tip_amount DECIMAL(12,2) DEFAULT 0,
    total DECIMAL(12,2) NOT NULL,
    cash_tendered DECIMAL(12,2),
    change_given DECIMAL(12,2),
    is_offline_sync BOOLEAN DEFAULT FALSE,
    sync_status VARCHAR(20),
    sync_conflicts JSONB,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_pos_transactions_org ON pos_transactions(org_id, created_at);
CREATE INDEX idx_pos_transactions_offline ON pos_transactions(offline_transaction_id);
```

### Hospitality Module Tables

#### restaurant_tables
```sql
CREATE TABLE restaurant_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    table_number VARCHAR(20) NOT NULL,
    seat_count INTEGER DEFAULT 4,
    position_x DECIMAL(8,2) DEFAULT 0,
    position_y DECIMAL(8,2) DEFAULT 0,
    width DECIMAL(8,2) DEFAULT 100,
    height DECIMAL(8,2) DEFAULT 100,
    status VARCHAR(20) DEFAULT 'available',
    merged_with_id UUID REFERENCES restaurant_tables(id),
    floor_plan_id UUID REFERENCES floor_plans(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### floor_plans
```sql
CREATE TABLE floor_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    name VARCHAR(100) DEFAULT 'Main Floor',
    width DECIMAL(8,2) DEFAULT 800,
    height DECIMAL(8,2) DEFAULT 600,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### table_reservations
```sql
CREATE TABLE table_reservations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    table_id UUID REFERENCES restaurant_tables(id) NOT NULL,
    customer_name VARCHAR(255) NOT NULL,
    party_size INTEGER NOT NULL,
    reservation_date DATE NOT NULL,
    reservation_time TIME NOT NULL,
    duration_minutes INTEGER DEFAULT 90,
    notes TEXT,
    status VARCHAR(20) DEFAULT 'confirmed',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### kitchen_orders
```sql
CREATE TABLE kitchen_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    pos_transaction_id UUID REFERENCES pos_transactions(id),
    table_id UUID REFERENCES restaurant_tables(id),
    item_name VARCHAR(255) NOT NULL,
    quantity INTEGER DEFAULT 1,
    modifications TEXT,
    station VARCHAR(50) DEFAULT 'main',
    status VARCHAR(20) DEFAULT 'pending',
    prepared_at TIMESTAMPTZ,
    prepared_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_kitchen_orders_org_status ON kitchen_orders(org_id, status);
```

#### tips
```sql
CREATE TABLE tips (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    pos_transaction_id UUID REFERENCES pos_transactions(id),
    invoice_id UUID REFERENCES invoices(id),
    amount DECIMAL(12,2) NOT NULL,
    payment_method VARCHAR(20),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### tip_allocations
```sql
CREATE TABLE tip_allocations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tip_id UUID REFERENCES tips(id) NOT NULL,
    staff_id UUID REFERENCES staff_members(id) NOT NULL,
    amount DECIMAL(12,2) NOT NULL
);
```

### Construction Module Tables

#### progress_claims
```sql
CREATE TABLE progress_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    project_id UUID REFERENCES projects(id) NOT NULL,
    claim_number INTEGER NOT NULL,
    contract_value DECIMAL(14,2) NOT NULL,
    variations_to_date DECIMAL(14,2) DEFAULT 0,
    revised_contract_value DECIMAL(14,2) NOT NULL,
    work_completed_this_period DECIMAL(14,2) NOT NULL,
    work_completed_to_date DECIMAL(14,2) NOT NULL,
    retention_withheld DECIMAL(14,2) DEFAULT 0,
    previous_claims_total DECIMAL(14,2) DEFAULT 0,
    amount_due DECIMAL(14,2) NOT NULL,
    completion_percentage DECIMAL(5,2),
    status VARCHAR(20) DEFAULT 'draft',
    invoice_id UUID REFERENCES invoices(id),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, claim_number)
);
```

#### variation_orders
```sql
CREATE TABLE variation_orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    project_id UUID REFERENCES projects(id) NOT NULL,
    variation_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    cost_impact DECIMAL(14,2) NOT NULL,
    status VARCHAR(20) DEFAULT 'draft',
    submitted_date DATE,
    approval_date DATE,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, variation_number)
);
```

#### retention_releases
```sql
CREATE TABLE retention_releases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) NOT NULL,
    amount DECIMAL(14,2) NOT NULL,
    release_date DATE NOT NULL,
    payment_id UUID REFERENCES payments(id),
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Ecommerce Module Tables

#### woocommerce_connections
```sql
CREATE TABLE woocommerce_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) UNIQUE NOT NULL,
    store_url VARCHAR(500) NOT NULL,
    consumer_key_encrypted BYTEA NOT NULL,
    consumer_secret_encrypted BYTEA NOT NULL,
    sync_frequency_minutes INTEGER DEFAULT 15,
    auto_create_invoices BOOLEAN DEFAULT TRUE,
    invoice_status_on_import VARCHAR(20) DEFAULT 'draft',
    last_sync_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### ecommerce_sync_log
```sql
CREATE TABLE ecommerce_sync_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    direction VARCHAR(10) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(100),
    status VARCHAR(20) NOT NULL,
    error_details TEXT,
    retry_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ecommerce_sync_org ON ecommerce_sync_log(org_id, created_at);
```

#### sku_mappings
```sql
CREATE TABLE sku_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    external_sku VARCHAR(100) NOT NULL,
    internal_product_id UUID REFERENCES products(id) NOT NULL,
    source VARCHAR(50) NOT NULL,
    UNIQUE(org_id, external_sku, source)
);
```

#### api_credentials
```sql
CREATE TABLE api_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    api_key VARCHAR(100) UNIQUE NOT NULL,
    api_secret_hash VARCHAR(255) NOT NULL,
    name VARCHAR(100),
    rate_limit_per_minute INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Franchise & Multi-Location Tables

#### locations
```sql
CREATE TABLE locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    phone VARCHAR(50),
    email VARCHAR(255),
    invoice_prefix VARCHAR(20),
    has_own_inventory BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_locations_org ON locations(org_id);
```

#### stock_transfers
```sql
CREATE TABLE stock_transfers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    from_location_id UUID REFERENCES locations(id) NOT NULL,
    to_location_id UUID REFERENCES locations(id) NOT NULL,
    product_id UUID REFERENCES products(id) NOT NULL,
    quantity DECIMAL(12,3) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    requested_by UUID REFERENCES users(id),
    approved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
```

#### franchise_groups
```sql
CREATE TABLE franchise_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Loyalty Module Tables

#### loyalty_config
```sql
CREATE TABLE loyalty_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) UNIQUE NOT NULL,
    earn_rate DECIMAL(8,4) DEFAULT 1.0,
    redemption_rate DECIMAL(8,4) DEFAULT 0.01,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### loyalty_tiers
```sql
CREATE TABLE loyalty_tiers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    name VARCHAR(100) NOT NULL,
    threshold_points INTEGER NOT NULL,
    discount_percent DECIMAL(5,2) DEFAULT 0,
    benefits JSONB DEFAULT '{}',
    display_order INTEGER DEFAULT 0
);
```

#### loyalty_transactions
```sql
CREATE TABLE loyalty_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    customer_id UUID REFERENCES customers(id) NOT NULL,
    transaction_type VARCHAR(20) NOT NULL,
    points INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
    reference_type VARCHAR(50),
    reference_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_loyalty_tx_customer ON loyalty_transactions(customer_id);
```

### Multi-Currency Tables

#### exchange_rates
```sql
CREATE TABLE exchange_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    base_currency VARCHAR(3) NOT NULL,
    target_currency VARCHAR(3) NOT NULL,
    rate DECIMAL(12,6) NOT NULL,
    source VARCHAR(50) DEFAULT 'manual',
    effective_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(base_currency, target_currency, effective_date)
);
```

#### org_currencies
```sql
CREATE TABLE org_currencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    currency_code VARCHAR(3) NOT NULL,
    is_enabled BOOLEAN DEFAULT TRUE,
    UNIQUE(org_id, currency_code)
);
```

### Compliance Module Tables

#### compliance_documents
```sql
CREATE TABLE compliance_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    document_type VARCHAR(50) NOT NULL,
    description TEXT,
    file_key VARCHAR(500) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    expiry_date DATE,
    invoice_id UUID REFERENCES invoices(id),
    job_id UUID REFERENCES jobs(id),
    uploaded_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_compliance_docs_org ON compliance_documents(org_id);
CREATE INDEX idx_compliance_docs_expiry ON compliance_documents(expiry_date);
```

### Recurring Invoice Tables

#### recurring_schedules
```sql
CREATE TABLE recurring_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    customer_id UUID REFERENCES customers(id) NOT NULL,
    line_items JSONB NOT NULL,
    frequency VARCHAR(20) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE,
    next_generation_date DATE NOT NULL,
    auto_issue BOOLEAN DEFAULT FALSE,
    auto_email BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) DEFAULT 'active',
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_recurring_next ON recurring_schedules(next_generation_date, status);
```

### Branding Tables

#### platform_branding
```sql
CREATE TABLE platform_branding (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform_name VARCHAR(100) DEFAULT 'OraInvoice',
    logo_url VARCHAR(500),
    primary_colour VARCHAR(7) DEFAULT '#2563EB',
    secondary_colour VARCHAR(7) DEFAULT '#1E40AF',
    website_url VARCHAR(500),
    signup_url VARCHAR(500),
    support_email VARCHAR(255),
    terms_url VARCHAR(500),
    auto_detect_domain BOOLEAN DEFAULT TRUE,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Webhook Management Tables

#### outbound_webhooks
```sql
CREATE TABLE outbound_webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    target_url VARCHAR(500) NOT NULL,
    event_types JSONB NOT NULL,
    secret_encrypted BYTEA NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    consecutive_failures INTEGER DEFAULT 0,
    last_delivery_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### webhook_delivery_log
```sql
CREATE TABLE webhook_delivery_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    webhook_id UUID REFERENCES outbound_webhooks(id) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    payload JSONB,
    response_status INTEGER,
    response_time_ms INTEGER,
    retry_count INTEGER DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    error_details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_webhook_delivery_webhook ON webhook_delivery_log(webhook_id, created_at);
```

### Asset Tracking Extension

#### assets (extends existing vehicles table concept)
```sql
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    customer_id UUID REFERENCES customers(id),
    asset_type VARCHAR(50) NOT NULL,
    identifier VARCHAR(100),
    make VARCHAR(100),
    model VARCHAR(100),
    year INTEGER,
    description TEXT,
    serial_number VARCHAR(100),
    location TEXT,
    custom_fields JSONB DEFAULT '{}',
    carjam_data JSONB,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_assets_org ON assets(org_id);
CREATE INDEX idx_assets_customer ON assets(customer_id);
CREATE INDEX idx_assets_identifier ON assets(org_id, identifier);
```

### Notification Enhancements

#### platform_notifications
```sql
CREATE TABLE platform_notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_type VARCHAR(30) NOT NULL,
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    severity VARCHAR(20) DEFAULT 'info',
    target_filter JSONB DEFAULT '{}',
    starts_at TIMESTAMPTZ,
    ends_at TIMESTAMPTZ,
    is_dismissible BOOLEAN DEFAULT TRUE,
    learn_more_url VARCHAR(500),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### notification_dismissals
```sql
CREATE TABLE notification_dismissals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID REFERENCES platform_notifications(id) NOT NULL,
    user_id UUID REFERENCES users(id) NOT NULL,
    dismissed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(notification_id, user_id)
);
```

### Receipt Printer Configuration

#### printer_configs
```sql
CREATE TABLE printer_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    location_id UUID REFERENCES locations(id),
    name VARCHAR(100) NOT NULL,
    connection_type VARCHAR(20) NOT NULL,
    address VARCHAR(255),
    paper_width INTEGER DEFAULT 80,
    is_default BOOLEAN DEFAULT FALSE,
    is_kitchen_printer BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Print Queue

#### print_jobs
```sql
CREATE TABLE print_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID REFERENCES organisations(id) NOT NULL,
    printer_id UUID REFERENCES printer_configs(id),
    job_type VARCHAR(20) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    error_details TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX idx_print_jobs_pending ON print_jobs(status, created_at) WHERE status = 'pending';
```

### Idempotency Keys

#### idempotency_keys
```sql
CREATE TABLE idempotency_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key VARCHAR(255) UNIQUE NOT NULL,
    org_id UUID REFERENCES organisations(id) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    response_status INTEGER,
    response_body JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_idempotency_expires ON idempotency_keys(expires_at);
```

## API Design

### V2 API Endpoint Structure

All new endpoints are under `/api/v2/` and require authentication via JWT Bearer token. Tenant resolution is automatic from the token's `org_id` claim.

#### Trade Categories & Setup
```
GET    /api/v2/trade-families                    # List trade families
GET    /api/v2/trade-categories                  # List trade categories (filterable by family)
GET    /api/v2/trade-categories/{slug}           # Get trade category details with seed data
POST   /api/v2/admin/trade-families              # Create trade family (Global Admin)
POST   /api/v2/admin/trade-categories            # Create trade category (Global Admin)
PUT    /api/v2/admin/trade-categories/{slug}     # Update trade category (Global Admin)
POST   /api/v2/setup-wizard/step/{step_number}   # Submit wizard step data
GET    /api/v2/setup-wizard/progress             # Get wizard completion state
```

#### Feature Flags
```
GET    /api/v2/flags                             # Get active flags for current org context
GET    /api/v2/admin/flags                       # List all flags (Global Admin)
POST   /api/v2/admin/flags                       # Create flag (Global Admin)
PUT    /api/v2/admin/flags/{key}                 # Update flag (Global Admin)
DELETE /api/v2/admin/flags/{key}                 # Archive flag (Global Admin)
```

#### Module Management
```
GET    /api/v2/modules                           # List available modules with enabled state
PUT    /api/v2/modules/{slug}/enable             # Enable module for current org
PUT    /api/v2/modules/{slug}/disable            # Disable module for current org
```

#### Inventory & Products
```
GET    /api/v2/products                          # List products (paginated, filterable)
POST   /api/v2/products                          # Create product
GET    /api/v2/products/{id}                     # Get product detail
PUT    /api/v2/products/{id}                     # Update product
DELETE /api/v2/products/{id}                     # Soft-delete product
GET    /api/v2/products/barcode/{barcode}        # Lookup by barcode
POST   /api/v2/products/import                   # CSV bulk import
GET    /api/v2/products/import/template          # Download sample CSV
GET    /api/v2/product-categories                # List categories (tree)
POST   /api/v2/product-categories                # Create category
GET    /api/v2/stock-movements                   # List stock movements
POST   /api/v2/stock-adjustments                 # Manual stock adjustment
POST   /api/v2/stocktakes                        # Start stocktake
PUT    /api/v2/stocktakes/{id}/commit            # Commit stocktake
GET    /api/v2/pricing-rules                     # List pricing rules
POST   /api/v2/pricing-rules                     # Create pricing rule
PUT    /api/v2/pricing-rules/{id}                # Update pricing rule
DELETE /api/v2/pricing-rules/{id}                # Delete pricing rule
GET    /api/v2/suppliers                         # List suppliers
POST   /api/v2/suppliers                         # Create supplier
```

#### Jobs
```
GET    /api/v2/jobs                              # List jobs (filterable by status, customer, staff)
POST   /api/v2/jobs                              # Create job
GET    /api/v2/jobs/{id}                         # Get job detail
PUT    /api/v2/jobs/{id}                         # Update job
PUT    /api/v2/jobs/{id}/status                  # Change job status
POST   /api/v2/jobs/{id}/attachments             # Upload attachment
POST   /api/v2/jobs/{id}/convert-to-invoice      # Convert job to invoice
GET    /api/v2/job-templates                     # List job templates
POST   /api/v2/job-templates                     # Create job template
```

#### Quotes
```
GET    /api/v2/quotes                            # List quotes
POST   /api/v2/quotes                            # Create quote
GET    /api/v2/quotes/{id}                       # Get quote detail
PUT    /api/v2/quotes/{id}                       # Update quote
PUT    /api/v2/quotes/{id}/send                  # Send quote to customer
POST   /api/v2/quotes/{id}/convert-to-invoice    # Convert to invoice
POST   /api/v2/quotes/{id}/revise                # Create new version
GET    /api/v2/quotes/accept/{token}             # Customer acceptance endpoint (public)
```

#### Time Tracking
```
GET    /api/v2/time-entries                      # List time entries
POST   /api/v2/time-entries                      # Create time entry
PUT    /api/v2/time-entries/{id}                 # Update time entry
POST   /api/v2/time-entries/timer/start          # Start timer
POST   /api/v2/time-entries/timer/stop           # Stop timer
GET    /api/v2/time-entries/timer/active          # Get active timer
GET    /api/v2/time-entries/timesheet             # Weekly timesheet view
```

#### Projects
```
GET    /api/v2/projects                          # List projects
POST   /api/v2/projects                          # Create project
GET    /api/v2/projects/{id}                     # Get project with profitability
PUT    /api/v2/projects/{id}                     # Update project
GET    /api/v2/projects/{id}/activity            # Activity feed
```

#### Expenses
```
GET    /api/v2/expenses                          # List expenses
POST   /api/v2/expenses                          # Create expense
PUT    /api/v2/expenses/{id}                     # Update expense
DELETE /api/v2/expenses/{id}                     # Delete expense
```

#### Purchase Orders
```
GET    /api/v2/purchase-orders                   # List POs
POST   /api/v2/purchase-orders                   # Create PO
GET    /api/v2/purchase-orders/{id}              # Get PO detail
PUT    /api/v2/purchase-orders/{id}              # Update PO
POST   /api/v2/purchase-orders/{id}/receive      # Receive goods
PUT    /api/v2/purchase-orders/{id}/send         # Send PO to supplier
```

#### Staff
```
GET    /api/v2/staff                             # List staff members
POST   /api/v2/staff                             # Create staff member
PUT    /api/v2/staff/{id}                        # Update staff member
GET    /api/v2/staff/{id}/utilisation            # Staff utilisation report
```

#### Scheduling & Bookings
```
GET    /api/v2/schedule                          # Get schedule entries (date range)
POST   /api/v2/schedule                          # Create schedule entry
PUT    /api/v2/schedule/{id}                     # Update (reschedule)
GET    /api/v2/bookings                          # List bookings
POST   /api/v2/bookings                          # Create booking (internal)
GET    /api/v2/public/bookings/{org_slug}        # Public booking page data
POST   /api/v2/public/bookings/{org_slug}        # Submit public booking
GET    /api/v2/public/bookings/{org_slug}/slots  # Available time slots
PUT    /api/v2/bookings/{id}/cancel              # Cancel booking
POST   /api/v2/bookings/{id}/convert-to-job      # Convert to job
GET    /api/v2/booking-rules                     # Get booking rules
PUT    /api/v2/booking-rules                     # Update booking rules
```

#### POS
```
POST   /api/v2/pos/sessions/open                 # Open POS session
POST   /api/v2/pos/sessions/close                # Close POS session
POST   /api/v2/pos/transactions                  # Complete POS transaction
POST   /api/v2/pos/transactions/sync             # Sync offline transactions (batch)
GET    /api/v2/pos/sync-status                   # Get sync status
```

#### Hospitality
```
GET    /api/v2/floor-plans                       # List floor plans
POST   /api/v2/floor-plans                       # Create floor plan
GET    /api/v2/tables                            # List tables with status
PUT    /api/v2/tables/{id}/status                # Update table status
POST   /api/v2/tables/{id}/merge                 # Merge tables
POST   /api/v2/tables/{id}/split                 # Split merged table
GET    /api/v2/reservations                      # List reservations
POST   /api/v2/reservations                      # Create reservation
GET    /api/v2/kitchen/orders                    # Get kitchen orders
PUT    /api/v2/kitchen/orders/{id}/prepared      # Mark item prepared
```

#### Construction
```
GET    /api/v2/progress-claims                   # List progress claims
POST   /api/v2/progress-claims                   # Create progress claim
PUT    /api/v2/progress-claims/{id}              # Update progress claim
PUT    /api/v2/progress-claims/{id}/approve      # Approve claim
GET    /api/v2/variations                        # List variation orders
POST   /api/v2/variations                        # Create variation
PUT    /api/v2/variations/{id}/approve           # Approve variation
POST   /api/v2/retentions/{project_id}/release   # Release retention
```

#### Ecommerce
```
POST   /api/v2/ecommerce/woocommerce/connect     # Connect WooCommerce store
POST   /api/v2/ecommerce/woocommerce/sync        # Trigger manual sync
GET    /api/v2/ecommerce/sync-log                # Get sync log
GET    /api/v2/ecommerce/sku-mappings            # List SKU mappings
POST   /api/v2/ecommerce/sku-mappings            # Create SKU mapping
POST   /api/v2/ecommerce/webhook/{org_id}        # Inbound webhook receiver
```

#### Multi-Currency
```
GET    /api/v2/currencies                        # List enabled currencies
POST   /api/v2/currencies/enable                 # Enable currency
GET    /api/v2/exchange-rates                    # Get exchange rates
POST   /api/v2/exchange-rates                    # Set manual rate
POST   /api/v2/exchange-rates/refresh            # Fetch latest rates from provider
```

#### Loyalty
```
GET    /api/v2/loyalty/config                    # Get loyalty config
PUT    /api/v2/loyalty/config                    # Update loyalty config
GET    /api/v2/loyalty/tiers                     # List tiers
POST   /api/v2/loyalty/tiers                     # Create tier
GET    /api/v2/loyalty/customers/{id}/balance    # Customer loyalty balance
POST   /api/v2/loyalty/redeem                    # Redeem points on invoice
```

#### Franchise & Locations
```
GET    /api/v2/locations                         # List locations
POST   /api/v2/locations                         # Create location
PUT    /api/v2/locations/{id}                    # Update location
POST   /api/v2/stock-transfers                   # Create stock transfer
PUT    /api/v2/stock-transfers/{id}/approve      # Approve transfer
GET    /api/v2/franchise/dashboard               # Franchise aggregate dashboard
```

#### Compliance
```
GET    /api/v2/compliance-documents              # List compliance docs
POST   /api/v2/compliance-documents              # Upload compliance doc
GET    /api/v2/compliance-documents/expiring     # Expiring documents
```

#### Webhooks
```
GET    /api/v2/webhooks                          # List outbound webhooks
POST   /api/v2/webhooks                          # Register webhook
PUT    /api/v2/webhooks/{id}                     # Update webhook
DELETE /api/v2/webhooks/{id}                     # Delete webhook
POST   /api/v2/webhooks/{id}/test                # Send test event
GET    /api/v2/webhooks/{id}/deliveries          # Delivery log
```

#### Branding (Global Admin)
```
GET    /api/v2/admin/branding                    # Get platform branding
PUT    /api/v2/admin/branding                    # Update platform branding
```

#### Notifications (Global Admin)
```
GET    /api/v2/admin/notifications               # List platform notifications
POST   /api/v2/admin/notifications               # Create notification
GET    /api/v2/notifications/active              # Get active notifications for current user
POST   /api/v2/notifications/{id}/dismiss        # Dismiss notification
```

#### Migration (Global Admin)
```
POST   /api/v2/admin/migration/start             # Start migration
GET    /api/v2/admin/migration/status            # Get migration progress
POST   /api/v2/admin/migration/cutover           # Execute cutover
POST   /api/v2/admin/migration/rollback          # Rollback migration
GET    /api/v2/admin/migration/report            # Get migration report
```

#### Terminology
```
GET    /api/v2/terminology                       # Get terminology map for current org
PUT    /api/v2/terminology                       # Override terminology entries
```

#### Reporting (Enhanced)
```
GET    /api/v2/reports/inventory-valuation        # Inventory valuation
GET    /api/v2/reports/job-profitability          # Job profitability
GET    /api/v2/reports/project-profitability      # Project profitability
GET    /api/v2/reports/staff-utilisation          # Staff utilisation
GET    /api/v2/reports/time-tracking-summary      # Time tracking summary
GET    /api/v2/reports/expense-summary            # Expense summary
GET    /api/v2/reports/pos-summary                # POS transaction summary
GET    /api/v2/reports/loyalty-summary            # Loyalty program report
GET    /api/v2/reports/progress-claims            # Progress claim summary
GET    /api/v2/reports/tax-return                 # Tax return (compliance profile format)
POST   /api/v2/reports/schedule                   # Schedule automated report
```

#### API Access (Zapier-compatible)
```
POST   /api/v2/api-keys                          # Generate API credentials
GET    /api/v2/api-keys                          # List API keys
DELETE /api/v2/api-keys/{id}                     # Revoke API key
```

## Core Service Designs

### Module Enablement Middleware

Every API request passes through the module middleware which checks if the requested module is enabled for the organisation:

```python
# app/middleware/modules.py
MODULE_ENDPOINT_MAP = {
    "inventory": ["/api/v2/products", "/api/v2/stock-", "/api/v2/pricing-rules", "/api/v2/suppliers"],
    "jobs": ["/api/v2/jobs"],
    "quotes": ["/api/v2/quotes"],
    "time_tracking": ["/api/v2/time-entries"],
    "projects": ["/api/v2/projects"],
    "expenses": ["/api/v2/expenses"],
    "purchase_orders": ["/api/v2/purchase-orders"],
    "staff": ["/api/v2/staff"],
    "scheduling": ["/api/v2/schedule"],
    "bookings": ["/api/v2/bookings", "/api/v2/public/bookings", "/api/v2/booking-rules"],
    "pos": ["/api/v2/pos"],
    "tables": ["/api/v2/floor-plans", "/api/v2/tables", "/api/v2/reservations"],
    "kitchen_display": ["/api/v2/kitchen"],
    "tipping": [],  # Tipping is checked inline on POS/invoice endpoints
    "ecommerce": ["/api/v2/ecommerce"],
    "multi_currency": ["/api/v2/currencies", "/api/v2/exchange-rates"],
    "loyalty": ["/api/v2/loyalty"],
    "franchise": ["/api/v2/locations", "/api/v2/stock-transfers", "/api/v2/franchise"],
    "compliance": ["/api/v2/compliance-documents"],
    "recurring": [],  # Checked inline on invoice creation
    "progress_claims": ["/api/v2/progress-claims"],
    "variations": ["/api/v2/variations"],
    "retentions": ["/api/v2/retentions"],
}
```

The middleware resolves the module from the request path, checks `org_modules` for the org, and returns HTTP 403 if disabled. Module state is cached in Redis per org with 60s TTL.

### Feature Flag Evaluation Service

```python
# app/core/feature_flags.py
class FeatureFlagService:
    TARGETING_PRIORITY = [
        "org_override",      # Specific org ID match
        "trade_category",    # Trade category match
        "trade_family",      # Trade family match
        "country",           # Country code match
        "plan_tier",         # Subscription plan match
        "percentage",        # Random percentage rollout
    ]

    async def evaluate(self, flag_key: str, org_context: OrgContext) -> bool:
        # 1. Check Redis cache
        cached = await redis.get(f"flag:{flag_key}:{org_context.org_id}")
        if cached is not None:
            return cached == "1"

        # 2. Load flag from DB
        flag = await db.get_flag(flag_key)
        if not flag or not flag.is_active:
            return flag.default_value if flag else False

        # 3. Evaluate targeting rules in priority order
        result = flag.default_value
        for rule in sorted(flag.targeting_rules, key=lambda r: self.TARGETING_PRIORITY.index(r["type"])):
            if self._matches_rule(rule, org_context):
                result = rule["enabled"]
                break

        # 4. Cache result
        await redis.setex(f"flag:{flag_key}:{org_context.org_id}", 60, "1" if result else "0")
        return result
```

### Terminology Resolution Service

```python
# app/core/terminology.py
class TerminologyService:
    DEFAULT_TERMS = {
        "asset_label": "Asset",
        "work_unit_label": "Job",
        "customer_label": "Customer",
        "line_item_service": "Service",
        "line_item_product": "Product",
        "line_item_labour": "Labour",
    }

    async def get_terminology_map(self, org_id: UUID) -> dict:
        # 1. Start with defaults
        terms = dict(self.DEFAULT_TERMS)

        # 2. Apply trade category overrides
        org = await db.get_org(org_id)
        if org.trade_category:
            category = await db.get_trade_category(org.trade_category_id)
            terms.update(category.terminology_overrides)

        # 3. Apply org-level overrides (highest priority)
        overrides = await db.get_org_terminology_overrides(org_id)
        for override in overrides:
            terms[override.generic_key] = override.custom_label

        return terms
```

### Module Dependency Resolver

```python
# app/core/modules.py
DEPENDENCY_GRAPH = {
    "pos": ["inventory"],
    "kitchen_display": ["tables", "pos"],
    "tipping": [],  # Requires pos OR invoice (always available)
    "progress_claims": ["projects"],
    "retentions": ["progress_claims"],
    "variations": ["progress_claims"],
    "expenses": [],  # Requires jobs OR projects
    "purchase_orders": ["inventory"],
    "staff": ["scheduling"],
    "ecommerce": ["inventory"],
}

class ModuleService:
    async def enable_module(self, org_id: UUID, module_slug: str) -> list[str]:
        # Auto-enable dependencies, return list of additionally enabled modules
        additionally_enabled = []
        deps = DEPENDENCY_GRAPH.get(module_slug, [])
        for dep in deps:
            if not await self.is_enabled(org_id, dep):
                await self._enable(org_id, dep)
                additionally_enabled.append(dep)
        await self._enable(org_id, module_slug)
        return additionally_enabled

    async def disable_module(self, org_id: UUID, module_slug: str) -> list[str]:
        # Check for dependents, return list of modules that would also need disabling
        dependents = []
        for mod, deps in DEPENDENCY_GRAPH.items():
            if module_slug in deps and await self.is_enabled(org_id, mod):
                dependents.append(mod)
        return dependents
```

### Cross-Module Transaction Pattern

All operations that span multiple modules use a transactional service pattern:

```python
# app/core/transactions.py
class TransactionalOperation:
    async def issue_invoice_with_inventory(self, invoice_id: UUID):
        async with db.transaction() as txn:
            # 1. Update invoice status (Invoice Module)
            invoice = await invoice_service.set_status(invoice_id, "issued", txn=txn)

            # 2. Decrement stock for product line items (Inventory Module)
            if await module_service.is_enabled(invoice.org_id, "inventory"):
                for line in invoice.lines:
                    if line.product_id:
                        await inventory_service.decrement_stock(
                            line.product_id, line.quantity, 
                            reference_type="invoice", reference_id=invoice_id,
                            txn=txn
                        )

            # 3. Record payment if POS (Payment Module)
            if invoice.payment_data:
                await payment_service.record_payment(invoice, txn=txn)

            # 4. Award loyalty points if enabled (Loyalty Module)
            if await module_service.is_enabled(invoice.org_id, "loyalty"):
                await loyalty_service.award_points(invoice, txn=txn)

        # 5. Async side effects (outside transaction)
        await celery_app.send_task("send_invoice_notification", args=[invoice_id])
        await celery_app.send_task("dispatch_webhooks", args=[invoice.org_id, "invoice.issued", invoice_id])
        if invoice.print_receipt:
            await celery_app.send_task("queue_print_job", args=[invoice_id])
```

### Offline POS Sync Service

```python
# app/modules/pos/sync_service.py
class OfflineSyncService:
    async def sync_transactions(self, org_id: UUID, transactions: list[dict]) -> SyncReport:
        report = SyncReport()
        # Process in chronological order
        for txn in sorted(transactions, key=lambda t: t["timestamp"]):
            try:
                conflicts = []
                for item in txn["line_items"]:
                    product = await product_service.get(item["product_id"])
                    if not product or not product.is_active:
                        conflicts.append({"type": "product_inactive", "product_id": item["product_id"]})
                    elif product.sale_price != item["price"]:
                        conflicts.append({"type": "price_changed", "product_id": item["product_id"],
                                          "offline_price": item["price"], "current_price": product.sale_price})

                # Always create the invoice with offline values
                invoice = await self._create_invoice_from_offline(org_id, txn)

                if conflicts:
                    report.add_conflict(txn["offline_id"], conflicts)
                else:
                    report.add_success(txn["offline_id"], invoice.id)

            except Exception as e:
                report.add_failure(txn["offline_id"], str(e))

        return report
```

### Extended RBAC Model

```python
# app/middleware/rbac.py (extended)
ROLE_PERMISSIONS = {
    "global_admin": ["*"],
    "franchise_admin": ["franchise.read", "reports.read"],
    "org_admin": ["org.*", "users.*", "modules.*", "settings.*", "reports.*", "billing.*"],
    "location_manager": [
        "invoices.*", "customers.*", "jobs.*", "inventory.*", "staff.*",
        "scheduling.*", "bookings.*", "pos.*", "reports.read"
    ],
    "salesperson": [
        "invoices.create", "invoices.read", "invoices.update",
        "customers.create", "customers.read", "customers.update",
        "jobs.create", "jobs.read", "jobs.update",
        "quotes.create", "quotes.read", "quotes.update",
        "time_entries.create", "time_entries.read", "time_entries.update",
        "expenses.create", "expenses.read",
        "pos.transact", "bookings.read",
    ],
    "staff_member": [
        "jobs.read_assigned", "time_entries.own", "schedule.own",
        "job_attachments.upload",
    ],
}

# Location scoping for Location_Manager
class LocationScopedPermission:
    async def check(self, user: User, resource_org_id: UUID, resource_location_id: UUID = None):
        if user.role == "location_manager":
            if resource_location_id and resource_location_id not in user.assigned_location_ids:
                raise PermissionDenied("Access restricted to assigned locations")
```

## Frontend Architecture

### Module-Aware Routing

The React frontend uses a module-aware router that conditionally renders routes based on enabled modules:

```typescript
// frontend/src/router/ModuleRouter.tsx
const MODULE_ROUTES: Record<string, RouteConfig[]> = {
  inventory: [
    { path: '/inventory/products', component: ProductList },
    { path: '/inventory/categories', component: CategoryTree },
    { path: '/inventory/stock-movements', component: StockMovements },
    { path: '/inventory/stocktake', component: StockTake },
    { path: '/inventory/suppliers', component: SupplierList },
  ],
  jobs: [
    { path: '/jobs', component: JobBoard },
    { path: '/jobs/:id', component: JobDetail },
  ],
  quotes: [
    { path: '/quotes', component: QuoteList },
    { path: '/quotes/:id', component: QuoteDetail },
  ],
  time_tracking: [
    { path: '/time', component: TimeSheet },
  ],
  projects: [
    { path: '/projects', component: ProjectList },
    { path: '/projects/:id', component: ProjectDashboard },
  ],
  pos: [
    { path: '/pos', component: POSScreen },
  ],
  tables: [
    { path: '/floor-plan', component: FloorPlan },
  ],
  kitchen_display: [
    { path: '/kitchen', component: KitchenDisplay },
  ],
  scheduling: [
    { path: '/schedule', component: ScheduleCalendar },
  ],
  bookings: [
    { path: '/bookings', component: BookingList },
  ],
  // ... additional module routes
};

function ModuleRouter() {
  const { enabledModules } = useModules();
  return (
    <Routes>
      {/* Core routes always available */}
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/invoices/*" element={<InvoiceRoutes />} />
      <Route path="/customers/*" element={<CustomerRoutes />} />
      {/* Module routes conditionally rendered */}
      {Object.entries(MODULE_ROUTES).map(([module, routes]) =>
        enabledModules.includes(module) &&
        routes.map(r => <Route key={r.path} path={r.path} element={<r.component />} />)
      )}
    </Routes>
  );
}
```

### Terminology Context Provider

```typescript
// frontend/src/contexts/TerminologyContext.tsx
const TerminologyContext = createContext<Record<string, string>>({});

export function TerminologyProvider({ children }: { children: React.ReactNode }) {
  const { data: terms } = useQuery(['terminology'], () => api.get('/api/v2/terminology'));
  return (
    <TerminologyContext.Provider value={terms || {}}>
      {children}
    </TerminologyContext.Provider>
  );
}

export function useTerm(key: string, fallback: string): string {
  const terms = useContext(TerminologyContext);
  return terms[key] || fallback;
}

// Usage in components:
// const assetLabel = useTerm('asset_label', 'Asset');
// <h2>{assetLabel} Details</h2>
```

### Setup Wizard Component Structure

```
frontend/src/pages/setup/
├── SetupWizard.tsx           # Main wizard container with step navigation
├── steps/
│   ├── CountryStep.tsx       # Step 1: Country selection with searchable dropdown
│   ├── TradeStep.tsx         # Step 2: Trade family grid → trade category selection
│   ├── BusinessStep.tsx      # Step 3: Business details form with tax ID validation
│   ├── BrandingStep.tsx      # Step 4: Logo upload, colours, live invoice preview
│   ├── ModulesStep.tsx       # Step 5: Module checklist with dependency warnings
│   ├── CatalogueStep.tsx     # Step 6: Pre-populated services/products editor
│   └── ReadyStep.tsx         # Step 7: Summary with edit links
└── components/
    ├── StepIndicator.tsx     # Progress bar showing current step
    └── InvoicePreview.tsx    # Live invoice PDF preview component
```

### POS Offline Architecture

```typescript
// frontend/src/utils/posOfflineStore.ts
// Uses IndexedDB via idb library for offline transaction storage

interface OfflineTransaction {
  offlineId: string;          // UUID generated client-side
  timestamp: string;          // ISO timestamp
  userId: string;
  lineItems: OfflineLineItem[];
  paymentMethod: string;
  subtotal: number;
  taxAmount: number;
  discountAmount: number;
  tipAmount: number;
  total: number;
  cashTendered?: number;
  changeGiven?: number;
  customerId?: string;
  tableId?: string;
}

// Sync manager runs on connectivity restore
class POSSyncManager {
  async syncPendingTransactions(): Promise<SyncReport> {
    const pending = await offlineStore.getPending();
    const sorted = pending.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    const report = await api.post('/api/v2/pos/transactions/sync', { transactions: sorted });
    for (const success of report.successes) {
      await offlineStore.markSynced(success.offlineId);
    }
    return report;
  }
}
```

### Kitchen Display Real-Time Updates

The Kitchen Display uses WebSocket connections for real-time order updates:

```typescript
// frontend/src/pages/kitchen/KitchenDisplay.tsx
// Connects to WebSocket at /ws/kitchen/{org_id}/{station}
// Receives: new_order, item_update, order_cancelled events
// Sends: item_prepared, item_started events
```

The backend uses FastAPI WebSocket endpoints with Redis pub/sub for cross-instance message distribution.

## Background Task Architecture

### Celery Task Queues

Tasks are distributed across priority queues:

```python
# app/tasks/__init__.py (extended)
CELERY_TASK_QUEUES = {
    "critical": ["pos_sync", "payment_processing", "webhook_delivery"],
    "default": ["invoice_generation", "recurring_invoices", "stock_alerts", "notification_send"],
    "bulk": ["report_generation", "csv_import", "woocommerce_sync", "data_export"],
    "migration": ["db_migration", "v1_org_migration"],
}
```

### New Celery Tasks

```python
# app/tasks/modules.py
@celery_app.task(queue="default")
def generate_recurring_invoices():
    """Runs daily. Finds recurring schedules where next_generation_date <= today."""

@celery_app.task(queue="bulk")
def sync_woocommerce(org_id: str):
    """Bidirectional WooCommerce sync for a single org."""

@celery_app.task(queue="default")
def check_quote_expiry():
    """Runs daily. Marks expired quotes."""

@celery_app.task(queue="default")
def check_compliance_expiry():
    """Runs daily. Sends reminders for expiring compliance documents."""

@celery_app.task(queue="default")
def refresh_exchange_rates():
    """Runs daily. Fetches latest exchange rates from configured provider."""

@celery_app.task(queue="critical")
def deliver_webhook(webhook_id: str, event_type: str, payload: dict):
    """Delivers a single webhook with retry logic."""

@celery_app.task(queue="default")
def check_low_stock_alerts(org_id: str):
    """Checks all products for low stock and sends alerts."""

@celery_app.task(queue="bulk")
def generate_scheduled_report(report_config_id: str):
    """Generates a scheduled report and emails it."""
```

### Dead Letter Queue

Failed tasks after max retries are moved to a dead letter queue table:

```sql
CREATE TABLE dead_letter_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name VARCHAR(255) NOT NULL,
    task_args JSONB,
    task_kwargs JSONB,
    error_message TEXT,
    traceback TEXT,
    retry_count INTEGER DEFAULT 0,
    first_failed_at TIMESTAMPTZ NOT NULL,
    last_failed_at TIMESTAMPTZ NOT NULL,
    resolved BOOLEAN DEFAULT FALSE,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES users(id)
);
```

## V1 Migration Design

### Migration Strategy

The V1 to V2 migration follows a three-phase approach:

1. **Schema Extension** — New tables are added alongside existing tables. No existing tables are modified except for adding nullable columns to `organisations`.

2. **Data Backfill** — A migration script populates new tables from existing data:
   - Existing orgs get `trade_category_id` set to "vehicle-workshop"
   - Existing catalogue items are copied to the products table where applicable
   - Existing vehicles are copied to the assets table
   - Module enablement records are created based on existing feature usage

3. **Dual-Write Period** — During rolling migration, both V1 and V2 code paths are active per org. A `migration_status` field on the org controls which path is used. Once all orgs are migrated, V1 code paths are deprecated.

### Migration Integrity Checks

```python
# app/tasks/migration.py
INTEGRITY_CHECKS = [
    ("organisations", "SELECT COUNT(*) FROM organisations"),
    ("customers", "SELECT COUNT(*) FROM customers WHERE org_id = :org_id"),
    ("invoices", "SELECT COUNT(*), SUM(total_amount) FROM invoices WHERE org_id = :org_id"),
    ("payments", "SELECT COUNT(*), SUM(amount) FROM payments WHERE org_id = :org_id"),
    ("vehicles_to_assets", "SELECT COUNT(*) FROM vehicles WHERE org_id = :org_id"),
]
```

## Security Design

### Webhook Signature Verification

```python
# app/core/webhook_security.py
import hmac
import hashlib

def sign_webhook_payload(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = sign_webhook_payload(payload, secret)
    return hmac.compare_digest(expected, signature)
```

### Idempotency Middleware

```python
# app/middleware/idempotency.py
class IdempotencyMiddleware:
    async def __call__(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            idem_key = request.headers.get("Idempotency-Key")
            if idem_key:
                existing = await db.get_idempotency_key(idem_key, request.state.org_id)
                if existing and not existing.is_expired:
                    return JSONResponse(
                        status_code=existing.response_status,
                        content=existing.response_body
                    )
        response = await call_next(request)
        if idem_key:
            await db.store_idempotency_key(idem_key, request.state.org_id,
                                            request.url.path, response.status_code,
                                            response.body, expires_in=timedelta(hours=24))
        return response
```

### API Rate Limiting (Enhanced)

```python
# app/middleware/rate_limit.py (extended)
PLAN_RATE_LIMITS = {
    "starter": 1000,
    "professional": 5000,
    "enterprise": 10000,
}

# Uses Redis sliding window counter per org_id
# Returns 429 with Retry-After header when exceeded
```

## Project File Structure (New Additions)

```
app/
├── core/
│   ├── feature_flags.py          # Feature flag evaluation service
│   ├── modules.py                # Module dependency resolver
│   ├── terminology.py            # Terminology resolution service
│   ├── transactions.py           # Cross-module transaction patterns
│   ├── webhook_security.py       # Webhook signing/verification
│   └── data_residency.py         # Data residency routing
├── middleware/
│   ├── modules.py                # Module enablement middleware
│   ├── idempotency.py            # Idempotency key middleware
│   └── api_version.py            # API version routing + deprecation headers
├── modules/
│   ├── trade_categories/         # Trade category registry CRUD
│   │   ├── models.py
│   │   ├── router.py
│   │   ├── service.py
│   │   └── schemas.py
│   ├── setup_wizard/             # Setup wizard endpoints
│   ├── products/                 # Product catalogue (inventory)
│   ├── stock/                    # Stock movements, stocktakes
│   ├── pricing_rules/            # Pricing rule engine
│   ├── suppliers/                # Supplier management
│   ├── purchase_orders/          # Purchase order lifecycle
│   ├── jobs_v2/                  # Enhanced job management
│   ├── quotes_v2/                # Quote management with versioning
│   ├── time_tracking_v2/         # Enhanced time tracking with timer
│   ├── projects/                 # Project management
│   ├── expenses/                 # Expense tracking
│   ├── staff/                    # Staff & contractor management
│   ├── scheduling_v2/            # Enhanced scheduling
│   ├── bookings_v2/              # Enhanced bookings with public page
│   ├── pos/                      # Point of sale
│   ├── receipt_printer/          # ESC/POS printer integration
│   ├── tables/                   # Table & floor plan management
│   ├── kitchen_display/          # Kitchen display system
│   ├── tipping/                  # Tip management
│   ├── progress_claims/          # Construction progress claims
│   ├── variations/               # Variation orders
│   ├── retentions/               # Retention tracking
│   ├── compliance_docs/          # Compliance document management
│   ├── multi_currency/           # Multi-currency support
│   ├── ecommerce/                # WooCommerce + webhook receiver
│   ├── loyalty/                  # Loyalty points & memberships
│   ├── franchise/                # Multi-location & franchise
│   ├── branding/                 # Platform branding
│   ├── platform_notifications/   # Global admin notifications
│   ├── migration_tool/           # Database migration tool
│   ├── assets/                   # Extended asset tracking
│   ├── recurring_invoices/       # Recurring invoice schedules
│   └── api_access/               # API key management
├── tasks/
│   ├── modules.py                # Module-specific background tasks
│   ├── sync.py                   # WooCommerce & ecommerce sync
│   ├── webhooks.py               # Webhook delivery
│   └── migration.py              # Migration tasks
└── templates/
    └── pdf/
        ├── invoice_standard.html
        ├── invoice_restaurant.html
        ├── invoice_construction.html
        ├── invoice_retail.html
        ├── quote.html
        ├── progress_claim.html
        ├── purchase_order.html
        ├── variation_order.html
        └── receipt_58mm.html
        └── receipt_80mm.html

frontend/src/
├── contexts/
│   ├── TerminologyContext.tsx
│   ├── ModuleContext.tsx
│   └── FeatureFlagContext.tsx
├── pages/
│   ├── setup/                    # Setup wizard
│   ├── pos/                      # POS interface
│   ├── kitchen/                  # Kitchen display
│   ├── floor-plan/               # Table management
│   ├── jobs/                     # Job management
│   ├── quotes/                   # Quote management
│   ├── projects/                 # Project management
│   ├── time-tracking/            # Time tracking
│   ├── expenses/                 # Expense tracking
│   ├── staff/                    # Staff management
│   ├── schedule/                 # Calendar/scheduling
│   ├── bookings/                 # Booking management
│   ├── inventory/                # Product catalogue & stock
│   ├── purchase-orders/          # Purchase orders
│   ├── loyalty/                  # Loyalty management
│   ├── compliance/               # Compliance documents
│   ├── ecommerce/                # Ecommerce integrations
│   ├── franchise/                # Multi-location management
│   └── construction/             # Progress claims, variations
├── components/
│   ├── pos/                      # POS-specific components
│   ├── kitchen/                  # Kitchen display components
│   └── common/
│       ├── ModuleGate.tsx        # Conditionally render based on module
│       ├── TermLabel.tsx         # Terminology-aware label component
│       └── FeatureGate.tsx       # Feature flag gate component
└── utils/
    ├── posOfflineStore.ts        # IndexedDB offline storage
    ├── posSyncManager.ts         # Offline sync manager
    ├── barcodeScanner.ts         # Barcode scanning utility
    └── escpos.ts                 # ESC/POS command builder
```

## Alembic Migration Strategy

New migrations are added sequentially after existing V1 migrations:

```
alembic/versions/
├── 2025_01_15_0001-0007  (existing V1 migrations)
├── 2026_03_10_0008-0008_add_trade_category_tables.py
├── 2026_03_10_0009-0009_add_feature_flags.py
├── 2026_03_10_0010-0010_add_module_registry.py
├── 2026_03_10_0011-0011_extend_organisations.py
├── 2026_03_10_0012-0012_add_compliance_profiles.py
├── 2026_03_10_0013-0013_add_inventory_tables.py
├── 2026_03_10_0014-0014_add_job_tables.py
├── 2026_03_10_0015-0015_add_quote_tables.py
├── 2026_03_10_0016-0016_add_time_tracking_tables.py
├── 2026_03_10_0017-0017_add_project_expense_tables.py
├── 2026_03_10_0018-0018_add_po_staff_tables.py
├── 2026_03_10_0019-0019_add_scheduling_booking_tables.py
├── 2026_03_10_0020-0020_add_pos_tables.py
├── 2026_03_10_0021-0021_add_hospitality_tables.py
├── 2026_03_10_0022-0022_add_construction_tables.py
├── 2026_03_10_0023-0023_add_ecommerce_tables.py
├── 2026_03_10_0024-0024_add_franchise_location_tables.py
├── 2026_03_10_0025-0025_add_loyalty_tables.py
├── 2026_03_10_0026-0026_add_multi_currency_tables.py
├── 2026_03_10_0027-0027_add_compliance_doc_tables.py
├── 2026_03_10_0028-0028_add_recurring_tables.py
├── 2026_03_10_0029-0029_add_branding_webhook_tables.py
├── 2026_03_10_0030-0030_add_asset_tables.py
├── 2026_03_10_0031-0031_add_notification_tables.py
├── 2026_03_10_0032-0032_add_printer_print_queue_tables.py
├── 2026_03_10_0033-0033_add_idempotency_dead_letter.py
├── 2026_03_10_0034-0034_seed_trade_families_categories.py
├── 2026_03_10_0035-0035_seed_compliance_profiles.py
├── 2026_03_10_0036-0036_seed_module_registry.py
└── 2026_03_10_0037-0037_seed_platform_branding.py
```

## Correctness Properties

The following properties must hold for the system to be considered correct. These will be validated using property-based testing (Hypothesis for Python, fast-check for TypeScript).

### Property 1: Module Isolation
For any organisation O with module M disabled, no API endpoint associated with M returns a 2xx response. All requests to M's endpoints return HTTP 403.

### Property 2: Tenant Data Isolation
For any two organisations O1 and O2, a user authenticated as O1 cannot read, write, or delete any data belonging to O2 through any API endpoint.

### Property 3: Stock Movement Consistency
For any product P, the sum of all stock_movement quantity_change values equals the product's current stock_quantity. No stock operation can leave the stock_quantity in a state inconsistent with the movement history.

### Property 4: Invoice Financial Integrity
For any invoice I, the total_amount equals the sum of (line_item_quantity × line_item_unit_price) for all line items, minus any discount, plus tax. This holds regardless of currency, pricing rules, or module interactions.

### Property 5: Job Status Transition Validity
For any job J, the sequence of status transitions recorded in job_status_history follows only valid transitions as defined in the status pipeline. No invalid transition (e.g. Enquiry → Completed) exists in the history.

### Property 6: Quote-to-Invoice Referential Integrity
For any quote Q with status "Converted", exactly one invoice I exists with a reference to Q, and Q.converted_invoice_id = I.id. The invoice's line items match the quote's line items at the time of conversion.

### Property 7: Pricing Rule Determinism
For any product P and context C (customer, quantity, date), the pricing rule evaluation always returns the same price. The evaluation is deterministic given the same rule set and context.

### Property 8: Feature Flag Evaluation Consistency
For any feature flag F and organisation context C, the evaluation result is the same whether served from cache or computed fresh from the database (within the cache TTL window).

### Property 9: Offline Transaction Sync Completeness
For any set of offline transactions T synced to the server, every transaction in T results in either a created invoice or an explicit error/conflict record. No transaction is silently dropped.

### Property 10: Module Dependency Integrity
For any organisation O, if module M is enabled and M has dependencies [D1, D2], then D1 and D2 are also enabled. No module can be in an enabled state while any of its dependencies are disabled.

### Property 11: Progress Claim Financial Consistency
For any project P with progress claims, the sum of all claim amounts_due plus retention_withheld equals work_completed_to_date on the latest claim. The cumulative claimed amount never exceeds the revised_contract_value.

### Property 12: Variation Contract Value Consistency
For any project P, the revised_contract_value equals the original contract_value plus the sum of cost_impact for all approved variation orders.

### Property 13: Loyalty Points Balance Consistency
For any customer C, the customer's loyalty points balance equals the sum of all loyalty_transaction points values (positive for earn, negative for redeem).

### Property 14: Multi-Currency Exchange Rate Locking
For any invoice I issued in a non-base currency, the exchange_rate recorded at issue time is used for all subsequent calculations. Changing the exchange rate table does not retroactively affect issued invoices.

### Property 15: Webhook Delivery Completeness
For any event E that matches a webhook subscription, a delivery attempt is recorded in webhook_delivery_log. Failed deliveries are retried up to the configured maximum.

### Property 16: Idempotency Key Consistency
For any two requests R1 and R2 with the same idempotency key K to the same endpoint, the response to R2 is identical to the response to R1 (same status code and body).

### Property 17: Location Data Scoping
For any Location_Manager user U assigned to location L, all data returned by API queries is scoped to location L. No data from other locations within the same organisation is accessible.

### Property 18: Terminology Map Completeness
For any organisation O with trade category T, the terminology map returned by the API contains entries for all keys in the DEFAULT_TERMS dictionary. No key is missing.

### Property 19: Setup Wizard Idempotency
Submitting the same wizard step data multiple times for the same organisation produces the same result as submitting it once. No duplicate records are created.

### Property 20: Retention Release Consistency
For any project P, the sum of all retention_release amounts never exceeds the total retention_withheld across all progress claims for that project.

## Testing Strategy

### Property-Based Tests (Hypothesis)

```python
# tests/property/test_module_isolation.py
@given(org_id=st.uuids(), module=st.sampled_from(OPTIONAL_MODULES))
def test_disabled_module_returns_403(org_id, module):
    # Disable module for org, attempt API call, assert 403

# tests/property/test_stock_consistency.py
@given(movements=st.lists(st.tuples(st.sampled_from(MOVEMENT_TYPES), st.decimals(min_value=-1000, max_value=1000))))
def test_stock_movements_sum_to_current_quantity(movements):
    # Apply movements, verify final quantity matches sum

# tests/property/test_pricing_determinism.py
@given(customer_id=st.uuids(), quantity=st.integers(min_value=1, max_value=1000), date=st.dates())
def test_pricing_rule_evaluation_is_deterministic(customer_id, quantity, date):
    # Evaluate pricing twice with same inputs, assert same result

# tests/property/test_job_transitions.py
@given(transitions=st.lists(st.sampled_from(JOB_STATUSES)))
def test_only_valid_job_transitions_succeed(transitions):
    # Attempt each transition, verify only valid ones succeed

# tests/property/test_offline_sync.py
@given(transactions=st.lists(offline_transaction_strategy()))
def test_all_offline_transactions_produce_result(transactions):
    # Sync transactions, verify each has success or conflict/error record
```

### Integration Tests

Each module has integration tests that verify end-to-end flows:
- Job creation → time tracking → expense logging → invoice conversion
- Quote creation → customer acceptance → invoice conversion → payment
- POS transaction → inventory decrement → receipt printing
- WooCommerce order webhook → invoice creation → stock update
- Progress claim → variation approval → contract value update → retention calculation
- Booking → job creation → scheduling → invoice

### Frontend Tests

- Setup wizard step navigation and validation
- POS offline mode: create transactions offline, verify IndexedDB storage, verify sync on reconnect
- Module-aware routing: verify hidden routes when modules disabled
- Terminology rendering: verify labels change based on trade category
- Kitchen display: verify real-time order updates via WebSocket mock