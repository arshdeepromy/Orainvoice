# OraInvoice - Database Tables Reference

**Generated from live database `workshoppro`**

**Total tables: 117**

**Current Alembic revision: `0094`** (migration `0095` pending)

---

## Table of Contents

1. [accounting_integrations](#accounting-integrations)
2. [accounting_sync_log](#accounting-sync-log)
3. [alembic_version](#alembic-version)
4. [api_credentials](#api-credentials)
5. [assets](#assets)
6. [audit_log](#audit-log)
7. [booking_rules](#booking-rules)
8. [bookings](#bookings)
9. [branches](#branches)
10. [compliance_documents](#compliance-documents)
11. [compliance_profiles](#compliance-profiles)
12. [coupons](#coupons)
13. [credit_note_sequences](#credit-note-sequences)
14. [credit_notes](#credit-notes)
15. [customer_vehicles](#customer-vehicles)
16. [customers](#customers)
17. [dead_letter_queue](#dead-letter-queue)
18. [discount_rules](#discount-rules)
19. [ecommerce_sync_log](#ecommerce-sync-log)
20. [email_providers](#email-providers)
21. [error_log](#error-log)
22. [exchange_rates](#exchange-rates)
23. [expenses](#expenses)
24. [feature_flags](#feature-flags)
25. [fleet_accounts](#fleet-accounts)
26. [floor_plans](#floor-plans)
27. [franchise_groups](#franchise-groups)
28. [global_vehicles](#global-vehicles)
29. [idempotency_keys](#idempotency-keys)
30. [integration_configs](#integration-configs)
31. [invoice_sequences](#invoice-sequences)
32. [invoices](#invoices)
33. [items_catalogue](#items-catalogue)
34. [job_attachments](#job-attachments)
35. [job_card_items](#job-card-items)
36. [job_cards](#job-cards)
37. [job_staff_assignments](#job-staff-assignments)
38. [job_status_history](#job-status-history)
39. [job_templates](#job-templates)
40. [jobs](#jobs)
41. [kitchen_orders](#kitchen-orders)
42. [labour_rates](#labour-rates)
43. [line_items](#line-items)
44. [locations](#locations)
45. [loyalty_config](#loyalty-config)
46. [loyalty_tiers](#loyalty-tiers)
47. [loyalty_transactions](#loyalty-transactions)
48. [module_registry](#module-registry)
49. [notification_dismissals](#notification-dismissals)
50. [notification_log](#notification-log)
51. [notification_preferences](#notification-preferences)
52. [notification_templates](#notification-templates)
53. [odometer_readings](#odometer-readings)
54. [org_currencies](#org-currencies)
55. [org_modules](#org-modules)
56. [org_storage_addons](#org-storage-addons)
57. [org_terminology_overrides](#org-terminology-overrides)
58. [org_vehicles](#org-vehicles)
59. [organisation_coupons](#organisation-coupons)
60. [organisations](#organisations)
61. [outbound_webhooks](#outbound-webhooks)
62. [overdue_reminder_rules](#overdue-reminder-rules)
63. [part_suppliers](#part-suppliers)
64. [parts_catalogue](#parts-catalogue)
65. [payments](#payments)
66. [platform_branding](#platform-branding)
67. [platform_notifications](#platform-notifications)
68. [platform_settings](#platform-settings)
69. [pos_sessions](#pos-sessions)
70. [pos_transactions](#pos-transactions)
71. [pricing_rules](#pricing-rules)
72. [print_jobs](#print-jobs)
73. [printer_configs](#printer-configs)
74. [product_categories](#product-categories)
75. [products](#products)
76. [progress_claims](#progress-claims)
77. [projects](#projects)
78. [public_holidays](#public-holidays)
79. [purchase_order_lines](#purchase-order-lines)
80. [purchase_orders](#purchase-orders)
81. [quote_line_items](#quote-line-items)
82. [quote_sequences](#quote-sequences)
83. [quotes](#quotes)
84. [recurring_schedules](#recurring-schedules)
85. [reminder_queue](#reminder-queue)
86. [reminder_rules](#reminder-rules)
87. [report_schedules](#report-schedules)
88. [restaurant_tables](#restaurant-tables)
89. [retention_releases](#retention-releases)
90. [schedule_entries](#schedule-entries)
91. [sessions](#sessions)
92. [setup_wizard_progress](#setup-wizard-progress)
93. [sku_mappings](#sku-mappings)
94. [sms_conversations](#sms-conversations)
95. [sms_messages](#sms-messages)
96. [sms_package_purchases](#sms-package-purchases)
97. [sms_verification_providers](#sms-verification-providers)
98. [staff_location_assignments](#staff-location-assignments)
99. [staff_members](#staff-members)
100. [stock_movements](#stock-movements)
101. [stock_transfers](#stock-transfers)
102. [storage_packages](#storage-packages)
103. [subscription_plans](#subscription-plans)
104. [suppliers](#suppliers)
105. [table_reservations](#table-reservations)
106. [time_entries](#time-entries)
107. [tip_allocations](#tip-allocations)
108. [tips](#tips)
109. [trade_categories](#trade-categories)
110. [trade_families](#trade-families)
111. [user_permission_overrides](#user-permission-overrides)
112. [users](#users)
113. [variation_orders](#variation-orders)
114. [webhook_deliveries](#webhook-deliveries)
115. [webhook_delivery_log](#webhook-delivery-log)
116. [webhooks](#webhooks)
117. [woocommerce_connections](#woocommerce-connections)

---

## accounting_integrations

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| provider | character varying | NO | - |
| access_token_encrypted | bytea | YES | - |
| refresh_token_encrypted | bytea | YES | - |
| token_expires_at | timestamp with time zone | YES | - |
| is_connected | boolean | NO | false |
| last_sync_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `accounting_integrations_pkey`, `uq_accounting_integrations_org_provider`

---

## accounting_sync_log

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| provider | character varying | NO | - |
| entity_type | character varying | NO | - |
| entity_id | uuid | NO | - |
| external_id | character varying | YES | - |
| status | character varying | NO | - |
| error_message | text | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `accounting_sync_log_pkey`

---

## alembic_version

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| version_num | character varying | NO | - |

**Indexes:** `alembic_version_pkc`

---

## api_credentials

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| api_key_hash | character varying | NO | - |
| name | character varying | NO | - |
| scopes | jsonb | NO | '["read"]'::jsonb |
| rate_limit_per_minute | integer | NO | 100 |
| is_active | boolean | NO | true |
| last_used_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `api_credentials_pkey`, `idx_api_credentials_org`

---

## assets

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | YES | - |
| asset_type | character varying | NO | - |
| identifier | character varying | YES | - |
| make | character varying | YES | - |
| model | character varying | YES | - |
| year | integer | YES | - |
| description | text | YES | - |
| serial_number | character varying | YES | - |
| location | text | YES | - |
| custom_fields | jsonb | NO | '{}'::jsonb |
| carjam_data | jsonb | YES | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `assets_pkey`, `idx_assets_customer`, `idx_assets_identifier`, `idx_assets_org`

---

## audit_log

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | YES | - |
| user_id | uuid | YES | - |
| action | character varying | NO | - |
| entity_type | character varying | NO | - |
| entity_id | uuid | YES | - |
| before_value | jsonb | YES | - |
| after_value | jsonb | YES | - |
| ip_address | inet | YES | - |
| device_info | character varying | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `audit_log_pkey`, `idx_audit_log_entity`, `idx_audit_log_org`

---

## booking_rules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| service_type | character varying | YES | - |
| duration_minutes | integer | NO | 60 |
| min_advance_hours | integer | NO | 2 |
| max_advance_days | integer | NO | 90 |
| buffer_minutes | integer | NO | 15 |
| available_days | jsonb | NO | '[1, 2, 3, 4, 5]'::jsonb |
| available_hours | jsonb | NO | '{"end": "17:00", "start": "09:00"}'::jsonb |
| max_per_day | integer | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `booking_rules_pkey`, `idx_booking_rules_org`

---

## bookings

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_name | character varying | NO | - |
| customer_email | character varying | YES | - |
| customer_phone | character varying | YES | - |
| staff_id | uuid | YES | - |
| service_type | character varying | YES | - |
| start_time | timestamp with time zone | NO | - |
| end_time | timestamp with time zone | NO | - |
| status | character varying | NO | 'pending'::character varying |
| notes | text | YES | - |
| confirmation_token | character varying | YES | - |
| converted_job_id | uuid | YES | - |
| converted_invoice_id | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| service_catalogue_id | uuid | YES | - |
| service_price | numeric | YES | - |
| send_email_confirmation | boolean | NO | false |
| send_sms_confirmation | boolean | NO | false |
| reminder_offset_hours | numeric | YES | - |
| reminder_scheduled_at | timestamp with time zone | YES | - |
| reminder_cancelled | boolean | NO | false |
| vehicle_rego | character varying | YES | - |

**Indexes:** `bookings_pkey`, `idx_bookings_org_date`, `idx_bookings_staff`, `idx_bookings_status`

---

## branches

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| address | text | YES | - |
| phone | character varying | YES | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `branches_pkey`

---

## compliance_documents

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| document_type | character varying | NO | - |
| description | text | YES | - |
| file_key | character varying | NO | - |
| file_name | character varying | NO | - |
| expiry_date | date | YES | - |
| invoice_id | uuid | YES | - |
| job_id | uuid | YES | - |
| uploaded_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `compliance_documents_pkey`, `idx_compliance_docs_expiry`, `idx_compliance_docs_org`

---

## compliance_profiles

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| country_code | character varying | NO | - |
| country_name | character varying | NO | - |
| tax_label | character varying | NO | - |
| default_tax_rates | jsonb | NO | - |
| tax_number_label | character varying | YES | - |
| tax_number_regex | character varying | YES | - |
| tax_inclusive_default | boolean | NO | true |
| date_format | character varying | NO | - |
| number_format | character varying | NO | - |
| currency_code | character varying | NO | - |
| report_templates | jsonb | NO | '[]'::jsonb |
| gdpr_applicable | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `compliance_profiles_pkey`, `uq_compliance_profiles_country_code`

---

## coupons

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| code | character varying | NO | - |
| description | character varying | YES | - |
| discount_type | character varying | NO | - |
| discount_value | numeric | NO | - |
| duration_months | integer | YES | - |
| usage_limit | integer | YES | - |
| times_redeemed | integer | NO | 0 |
| is_active | boolean | NO | true |
| starts_at | timestamp with time zone | YES | - |
| expires_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `coupons_code_key`, `coupons_pkey`, `ix_coupons_code`

---

## credit_note_sequences

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| last_number | integer | NO | 0 |

**Indexes:** `credit_note_sequences_pkey`, `uq_credit_note_sequences_org_id`

---

## credit_notes

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| invoice_id | uuid | NO | - |
| credit_note_number | character varying | NO | - |
| amount | numeric | NO | - |
| reason | text | NO | - |
| items | jsonb | NO | '[]'::jsonb |
| stripe_refund_id | character varying | YES | - |
| created_by | uuid | NO | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `credit_notes_pkey`

---

## customer_vehicles

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | NO | - |
| global_vehicle_id | uuid | YES | - |
| org_vehicle_id | uuid | YES | - |
| odometer_at_link | integer | YES | - |
| linked_at | timestamp with time zone | NO | now() |

**Indexes:** `customer_vehicles_pkey`

---

## customers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| first_name | character varying | NO | - |
| last_name | character varying | NO | - |
| email | character varying | YES | - |
| phone | character varying | YES | - |
| address | text | YES | - |
| notes | text | YES | - |
| fleet_account_id | uuid | YES | - |
| is_anonymised | boolean | NO | false |
| email_bounced | boolean | NO | false |
| tags | jsonb | NO | '[]'::jsonb |
| portal_token | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| customer_type | character varying | NO | 'individual'::character varying |
| salutation | character varying | YES | - |
| company_name | character varying | YES | - |
| display_name | character varying | YES | - |
| currency | character varying | NO | 'NZD'::character varying |
| work_phone | character varying | YES | - |
| mobile_phone | character varying | YES | - |
| language | character varying | NO | 'en'::character varying |
| tax_rate_id | uuid | YES | - |
| company_id | character varying | YES | - |
| payment_terms | character varying | NO | 'due_on_receipt'::character varying |
| enable_bank_payment | boolean | NO | false |
| enable_portal | boolean | NO | false |
| billing_address | jsonb | YES | '{}'::jsonb |
| shipping_address | jsonb | YES | '{}'::jsonb |
| contact_persons | jsonb | NO | '[]'::jsonb |
| custom_fields | jsonb | NO | '{}'::jsonb |
| remarks | text | YES | - |
| documents | jsonb | NO | '[]'::jsonb |
| owner_user_id | uuid | YES | - |

**Indexes:** `customers_pkey`, `idx_customers_company`, `idx_customers_org`, `idx_customers_org_name`, `idx_customers_search`, `idx_customers_type`, `uq_customers_portal_token`

---

## dead_letter_queue

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | YES | - |
| task_name | character varying | NO | - |
| task_args | jsonb | NO | '{}'::jsonb |
| error_message | text | YES | - |
| retry_count | integer | NO | 0 |
| max_retries | integer | NO | 3 |
| next_retry_at | timestamp with time zone | YES | - |
| status | character varying | NO | 'pending'::character varying |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `dead_letter_queue_pkey`, `idx_dead_letter_queue_status`

---

## discount_rules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| rule_type | character varying | NO | - |
| threshold_value | numeric | YES | - |
| discount_type | character varying | NO | - |
| discount_value | numeric | NO | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `discount_rules_pkey`

---

## ecommerce_sync_log

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| direction | character varying | NO | - |
| entity_type | character varying | NO | - |
| entity_id | character varying | YES | - |
| status | character varying | NO | - |
| error_details | text | YES | - |
| retry_count | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `ecommerce_sync_log_pkey`, `idx_ecommerce_sync_org`

---

## email_providers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| provider_key | character varying | NO | - |
| display_name | character varying | NO | - |
| description | text | YES | - |
| smtp_host | character varying | YES | - |
| smtp_port | integer | YES | - |
| is_active | boolean | NO | false |
| credentials_encrypted | bytea | YES | - |
| credentials_set | boolean | NO | false |
| config | jsonb | YES | '{}'::jsonb |
| setup_guide | text | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| smtp_encryption | character varying | YES | 'tls'::character varying |
| priority | integer | NO | 1 |

**Indexes:** `email_providers_pkey`, `email_providers_provider_key_key`

---

## error_log

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| severity | character varying | NO | - |
| category | character varying | NO | - |
| module | character varying | NO | - |
| function_name | character varying | YES | - |
| message | text | NO | - |
| stack_trace | text | YES | - |
| org_id | uuid | YES | - |
| user_id | uuid | YES | - |
| http_method | character varying | YES | - |
| http_endpoint | character varying | YES | - |
| request_body_sanitised | jsonb | YES | - |
| response_body_sanitised | jsonb | YES | - |
| status | character varying | NO | 'open'::character varying |
| resolution_notes | text | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `error_log_pkey`, `idx_error_log_category`, `idx_error_log_org`, `idx_error_log_severity`

---

## exchange_rates

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| base_currency | character varying | NO | - |
| target_currency | character varying | NO | - |
| rate | numeric | NO | - |
| source | character varying | NO | 'manual'::character varying |
| effective_date | date | NO | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `exchange_rates_pkey`, `uq_exchange_rate_pair_date`

---

## expenses

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| job_id | uuid | YES | - |
| project_id | uuid | YES | - |
| invoice_id | uuid | YES | - |
| date | date | NO | - |
| description | text | NO | - |
| amount | numeric | NO | - |
| tax_amount | numeric | NO | 0 |
| category | character varying | YES | - |
| receipt_file_key | character varying | YES | - |
| is_pass_through | boolean | NO | false |
| is_invoiced | boolean | NO | false |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `expenses_pkey`, `idx_expenses_category`, `idx_expenses_date`, `idx_expenses_job`, `idx_expenses_org`, `idx_expenses_project`

---

## feature_flags

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| key | character varying | NO | - |
| display_name | character varying | NO | - |
| description | text | YES | - |
| default_value | boolean | NO | false |
| is_active | boolean | NO | true |
| targeting_rules | jsonb | NO | '[]'::jsonb |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| category | character varying | NO | 'Core'::character varying |
| access_level | character varying | NO | 'all_users'::character varying |
| dependencies | jsonb | NO | '[]'::jsonb |
| updated_by | uuid | YES | - |

**Indexes:** `feature_flags_pkey`, `ix_feature_flags_category`, `ix_feature_flags_is_active`, `uq_feature_flags_key`

---

## fleet_accounts

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| primary_contact_name | character varying | YES | - |
| primary_contact_email | character varying | YES | - |
| primary_contact_phone | character varying | YES | - |
| billing_address | text | YES | - |
| notes | text | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `fleet_accounts_pkey`

---

## floor_plans

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| location_id | uuid | YES | - |
| name | character varying | NO | 'Main Floor'::character varying |
| width | numeric | NO | 800 |
| height | numeric | NO | 600 |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `floor_plans_pkey`, `idx_floor_plans_org`

---

## franchise_groups

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| name | character varying | NO | - |
| description | text | YES | - |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `franchise_groups_pkey`

---

## global_vehicles

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| rego | character varying | NO | - |
| make | character varying | YES | - |
| model | character varying | YES | - |
| year | integer | YES | - |
| colour | character varying | YES | - |
| body_type | character varying | YES | - |
| fuel_type | character varying | YES | - |
| engine_size | character varying | YES | - |
| num_seats | integer | YES | - |
| wof_expiry | date | YES | - |
| registration_expiry | date | YES | - |
| odometer_last_recorded | integer | YES | - |
| last_pulled_at | timestamp with time zone | NO | now() |
| created_at | timestamp with time zone | NO | now() |
| vin | character varying | YES | - |
| chassis | character varying | YES | - |
| engine_no | character varying | YES | - |
| transmission | character varying | YES | - |
| country_of_origin | character varying | YES | - |
| number_of_owners | integer | YES | - |
| vehicle_type | character varying | YES | - |
| reported_stolen | character varying | YES | - |
| power_kw | integer | YES | - |
| tare_weight | integer | YES | - |
| gross_vehicle_mass | integer | YES | - |
| date_first_registered_nz | date | YES | - |
| plate_type | character varying | YES | - |
| submodel | character varying | YES | - |
| second_colour | character varying | YES | - |
| lookup_type | character varying | YES | 'basic'::character varying |
| service_due_date | date | YES | - |

**Indexes:** `global_vehicles_pkey`, `idx_global_vehicles_rego`, `idx_global_vehicles_vin`, `uq_global_vehicles_rego`

---

## idempotency_keys

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| key | character varying | NO | - |
| org_id | uuid | NO | - |
| endpoint | character varying | NO | - |
| method | character varying | NO | - |
| response_status | integer | YES | - |
| response_body | jsonb | YES | - |
| created_at | timestamp with time zone | NO | now() |
| expires_at | timestamp with time zone | NO | - |

**Indexes:** `idempotency_keys_pkey`, `idx_idempotency_keys_expires_at`, `uq_idempotency_keys_key`

---

## integration_configs

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| name | character varying | NO | - |
| config_encrypted | bytea | NO | - |
| is_verified | boolean | NO | false |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `integration_configs_pkey`, `uq_integration_configs_name`

---

## invoice_sequences

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| last_number | integer | NO | 0 |

**Indexes:** `invoice_sequences_pkey`, `uq_invoice_sequences_org_id`

---

## invoices

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | NO | - |
| invoice_number | character varying | YES | - |
| vehicle_rego | character varying | YES | - |
| vehicle_make | character varying | YES | - |
| vehicle_model | character varying | YES | - |
| vehicle_year | integer | YES | - |
| vehicle_odometer | integer | YES | - |
| branch_id | uuid | YES | - |
| status | character varying | NO | 'draft'::character varying |
| issue_date | date | YES | - |
| due_date | date | YES | - |
| currency | character varying | NO | 'NZD'::character varying |
| subtotal | numeric | NO | 0 |
| discount_amount | numeric | NO | 0 |
| discount_type | character varying | YES | - |
| discount_value | numeric | YES | - |
| gst_amount | numeric | NO | 0 |
| total | numeric | NO | 0 |
| amount_paid | numeric | NO | 0 |
| balance_due | numeric | NO | 0 |
| notes_internal | text | YES | - |
| notes_customer | text | YES | - |
| void_reason | text | YES | - |
| voided_at | timestamp with time zone | YES | - |
| voided_by | uuid | YES | - |
| recurring_schedule_id | uuid | YES | - |
| job_card_id | uuid | YES | - |
| quote_id | uuid | YES | - |
| invoice_data_json | jsonb | NO | '{}'::jsonb |
| created_by | uuid | NO | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| exchange_rate_to_nzd | numeric | NO | 1.000000 |

**Indexes:** `idx_invoices_customer`, `idx_invoices_due_date`, `idx_invoices_number`, `idx_invoices_org`, `idx_invoices_org_status_date`, `idx_invoices_rego`, `idx_invoices_status`, `invoices_pkey`

---

## items_catalogue

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| description | text | YES | - |
| default_price | numeric | NO | - |
| is_gst_exempt | boolean | NO | false |
| category | character varying | NO | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `service_catalogue_pkey`

---

## job_attachments

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| job_id | uuid | NO | - |
| file_key | character varying | NO | - |
| file_name | character varying | NO | - |
| file_size | bigint | NO | - |
| content_type | character varying | YES | - |
| uploaded_by | uuid | YES | - |
| uploaded_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_job_attachments_job`, `job_attachments_pkey`

---

## job_card_items

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| job_card_id | uuid | NO | - |
| org_id | uuid | NO | - |
| item_type | character varying | NO | - |
| description | character varying | NO | - |
| quantity | numeric | NO | 1 |
| unit_price | numeric | NO | - |
| is_completed | boolean | NO | false |
| sort_order | integer | NO | 0 |
| catalogue_item_id | uuid | YES | - |

**Indexes:** `idx_job_card_items_job_card`, `job_card_items_pkey`

---

## job_cards

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | NO | - |
| vehicle_rego | character varying | YES | - |
| status | character varying | NO | 'open'::character varying |
| description | text | YES | - |
| notes | text | YES | - |
| assigned_to | uuid | YES | - |
| created_by | uuid | NO | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `job_cards_pkey`

---

## job_staff_assignments

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| job_id | uuid | NO | - |
| user_id | uuid | NO | - |
| role | character varying | NO | 'assigned'::character varying |
| assigned_at | timestamp with time zone | NO | now() |

**Indexes:** `job_staff_assignments_pkey`, `uq_job_staff_job_user`

---

## job_status_history

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| job_id | uuid | NO | - |
| from_status | character varying | YES | - |
| to_status | character varying | NO | - |
| changed_by | uuid | YES | - |
| changed_at | timestamp with time zone | NO | now() |
| notes | text | YES | - |

**Indexes:** `idx_job_status_history_job`, `job_status_history_pkey`

---

## job_templates

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| trade_category_slug | character varying | YES | - |
| description | text | YES | - |
| checklist | jsonb | NO | '[]'::jsonb |
| default_line_items | jsonb | NO | '[]'::jsonb |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_job_templates_org`, `job_templates_pkey`

---

## jobs

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | YES | - |
| location_id | uuid | YES | - |
| project_id | uuid | YES | - |
| template_id | uuid | YES | - |
| converted_invoice_id | uuid | YES | - |
| job_number | character varying | NO | - |
| title | character varying | NO | - |
| description | text | YES | - |
| status | character varying | NO | 'draft'::character varying |
| priority | character varying | NO | 'normal'::character varying |
| site_address | text | YES | - |
| scheduled_start | timestamp with time zone | YES | - |
| scheduled_end | timestamp with time zone | YES | - |
| actual_start | timestamp with time zone | YES | - |
| actual_end | timestamp with time zone | YES | - |
| checklist | jsonb | NO | '[]'::jsonb |
| internal_notes | text | YES | - |
| customer_notes | text | YES | - |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_jobs_customer`, `idx_jobs_org_status`, `idx_jobs_org_status_v2`, `idx_jobs_project`, `jobs_pkey`, `uq_jobs_org_job_number`

---

## kitchen_orders

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| pos_transaction_id | uuid | YES | - |
| table_id | uuid | YES | - |
| item_name | character varying | NO | - |
| quantity | integer | NO | 1 |
| modifications | text | YES | - |
| station | character varying | NO | 'main'::character varying |
| status | character varying | NO | 'pending'::character varying |
| created_at | timestamp with time zone | NO | now() |
| prepared_at | timestamp with time zone | YES | - |

**Indexes:** `idx_kitchen_orders_org_station`, `kitchen_orders_pkey`

---

## labour_rates

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| hourly_rate | numeric | NO | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `labour_rates_pkey`

---

## line_items

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| invoice_id | uuid | NO | - |
| org_id | uuid | NO | - |
| item_type | character varying | NO | - |
| description | character varying | NO | - |
| catalogue_item_id | uuid | YES | - |
| part_number | character varying | YES | - |
| quantity | numeric | NO | 1 |
| unit_price | numeric | NO | - |
| hours | numeric | YES | - |
| hourly_rate | numeric | YES | - |
| discount_type | character varying | YES | - |
| discount_value | numeric | YES | - |
| is_gst_exempt | boolean | NO | false |
| warranty_note | text | YES | - |
| line_total | numeric | NO | - |
| sort_order | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_line_items_invoice`, `line_items_pkey`

---

## locations

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| address | text | YES | - |
| phone | character varying | YES | - |
| email | character varying | YES | - |
| invoice_prefix | character varying | YES | - |
| has_own_inventory | boolean | NO | false |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_locations_org`, `locations_pkey`

---

## loyalty_config

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| earn_rate | numeric | NO | 1.0 |
| redemption_rate | numeric | NO | 0.01 |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `loyalty_config_pkey`, `uq_loyalty_config_org`

---

## loyalty_tiers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| threshold_points | integer | NO | - |
| discount_percent | numeric | NO | '0'::numeric |
| benefits | jsonb | NO | '{}'::jsonb |
| display_order | integer | NO | 0 |

**Indexes:** `idx_loyalty_tiers_org`, `loyalty_tiers_pkey`

---

## loyalty_transactions

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | NO | - |
| transaction_type | character varying | NO | - |
| points | integer | NO | - |
| balance_after | integer | NO | - |
| reference_type | character varying | YES | - |
| reference_id | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_loyalty_tx_customer`, `idx_loyalty_tx_org`, `loyalty_transactions_pkey`

---

## module_registry

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| slug | character varying | NO | - |
| display_name | character varying | NO | - |
| description | text | YES | - |
| category | character varying | YES | - |
| is_core | boolean | NO | false |
| dependencies | jsonb | NO | '[]'::jsonb |
| incompatibilities | jsonb | NO | '[]'::jsonb |
| status | character varying | NO | 'available'::character varying |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `module_registry_pkey`, `uq_module_registry_slug`

---

## notification_dismissals

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| notification_id | uuid | NO | - |
| user_id | uuid | NO | - |
| dismissed_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_notification_dismissals_notification`, `idx_notification_dismissals_user`, `notification_dismissals_pkey`, `uq_notification_user_dismissal`

---

## notification_log

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| channel | character varying | NO | - |
| recipient | character varying | NO | - |
| template_type | character varying | NO | - |
| subject | character varying | YES | - |
| status | character varying | NO | 'queued'::character varying |
| retry_count | integer | NO | 0 |
| error_message | text | YES | - |
| sent_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_notification_log_org`, `notification_log_pkey`

---

## notification_preferences

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| notification_type | character varying | NO | - |
| is_enabled | boolean | NO | false |
| channel | character varying | NO | 'email'::character varying |
| config | jsonb | NO | '{}'::jsonb |

**Indexes:** `notification_preferences_pkey`, `uq_notification_preferences_org_type`

---

## notification_templates

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| template_type | character varying | NO | - |
| channel | character varying | NO | - |
| subject | character varying | YES | - |
| body_blocks | jsonb | NO | '[]'::jsonb |
| is_enabled | boolean | NO | false |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `notification_templates_pkey`, `uq_notification_templates_org_type_channel`

---

## odometer_readings

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| global_vehicle_id | uuid | NO | - |
| reading_km | integer | NO | - |
| source | character varying | NO | - |
| recorded_by | uuid | YES | - |
| invoice_id | uuid | YES | - |
| org_id | uuid | YES | - |
| notes | text | YES | - |
| recorded_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_odometer_readings_vehicle`, `odometer_readings_pkey`

---

## org_currencies

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| currency_code | character varying | NO | - |
| is_base | boolean | NO | false |
| enabled | boolean | NO | true |

**Indexes:** `idx_org_currencies_org`, `org_currencies_pkey`, `uq_org_currency`

---

## org_modules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| module_slug | character varying | NO | - |
| is_enabled | boolean | NO | true |
| enabled_at | timestamp with time zone | NO | now() |
| enabled_by | uuid | YES | - |

**Indexes:** `idx_org_modules_org`, `org_modules_pkey`, `uq_org_modules_org_slug`

---

## org_storage_addons

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| storage_package_id | uuid | YES | - |
| quantity_gb | integer | NO | - |
| price_nzd_per_month | numeric | NO | - |
| is_custom | boolean | NO | false |
| purchased_at | timestamp with time zone | NO | - |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `ix_org_storage_addons_org_id`, `ix_org_storage_addons_storage_package_id`, `org_storage_addons_pkey`, `uq_org_storage_addons_org_id`

---

## org_terminology_overrides

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| generic_key | character varying | NO | - |
| custom_label | character varying | NO | - |

**Indexes:** `org_terminology_overrides_pkey`, `uq_org_terminology_overrides_org_key`

---

## org_vehicles

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| rego | character varying | NO | - |
| make | character varying | YES | - |
| model | character varying | YES | - |
| year | integer | YES | - |
| colour | character varying | YES | - |
| body_type | character varying | YES | - |
| fuel_type | character varying | YES | - |
| engine_size | character varying | YES | - |
| num_seats | integer | YES | - |
| is_manual_entry | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `org_vehicles_pkey`

---

## organisation_coupons

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| coupon_id | uuid | NO | - |
| applied_at | timestamp with time zone | NO | - |
| billing_months_used | integer | NO | 0 |
| is_expired | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `ix_organisation_coupons_coupon_id`, `ix_organisation_coupons_org_id`, `organisation_coupons_pkey`, `uq_organisation_coupons_org_coupon`

---

## organisations

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| name | character varying | NO | - |
| plan_id | uuid | NO | - |
| status | character varying | NO | 'active'::character varying |
| trial_ends_at | timestamp with time zone | YES | - |
| stripe_customer_id | character varying | YES | - |
| stripe_subscription_id | character varying | YES | - |
| stripe_connect_account_id | character varying | YES | - |
| storage_quota_gb | integer | NO | - |
| storage_used_bytes | bigint | NO | 0 |
| carjam_lookups_this_month | integer | NO | 0 |
| carjam_lookups_reset_at | timestamp with time zone | YES | - |
| settings | jsonb | NO | '{}'::jsonb |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| trade_category_id | uuid | YES | - |
| country_code | character varying | YES | - |
| data_residency_region | character varying | NO | 'nz-au'::character varying |
| base_currency | character varying | NO | 'NZD'::character varying |
| locale | character varying | NO | 'en-NZ'::character varying |
| tax_label | character varying | NO | 'GST'::character varying |
| default_tax_rate | numeric | NO | 15.00 |
| tax_inclusive_default | boolean | NO | true |
| date_format | character varying | NO | 'dd/MM/yyyy'::character varying |
| number_format | character varying | NO | 'en-NZ'::character varying |
| timezone | character varying | NO | 'Pacific/Auckland'::character varying |
| compliance_profile_id | uuid | YES | - |
| setup_wizard_state | jsonb | NO | '{}'::jsonb |
| is_multi_location | boolean | NO | false |
| franchise_group_id | uuid | YES | - |
| white_label_enabled | boolean | NO | false |
| storage_quota_bytes | bigint | NO | '5368709120'::bigint |
| sms_sent_this_month | integer | NO | 0 |
| sms_sent_reset_at | timestamp with time zone | YES | - |

**Indexes:** `organisations_pkey`

---

## outbound_webhooks

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| target_url | character varying | NO | - |
| event_types | jsonb | NO | - |
| secret_encrypted | bytea | NO | - |
| is_active | boolean | NO | true |
| consecutive_failures | integer | NO | 0 |
| last_delivery_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_outbound_webhooks_org`, `outbound_webhooks_pkey`

---

## overdue_reminder_rules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| days_after_due | integer | NO | - |
| send_email | boolean | NO | true |
| send_sms | boolean | NO | false |
| sort_order | integer | NO | 0 |
| is_enabled | boolean | NO | false |

**Indexes:** `overdue_reminder_rules_pkey`, `uq_overdue_reminder_rules_org_days`

---

## part_suppliers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| part_id | uuid | NO | - |
| supplier_id | uuid | NO | - |
| supplier_part_number | character varying | YES | - |
| supplier_cost | numeric | YES | - |
| is_preferred | boolean | NO | false |

**Indexes:** `part_suppliers_pkey`, `uq_part_suppliers_part_supplier`

---

## parts_catalogue

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| part_number | character varying | YES | - |
| default_price | numeric | NO | - |
| current_stock | integer | NO | 0 |
| min_stock_threshold | integer | NO | 0 |
| reorder_quantity | integer | NO | 0 |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `parts_catalogue_pkey`

---

## payments

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| invoice_id | uuid | NO | - |
| amount | numeric | NO | - |
| method | character varying | NO | - |
| stripe_payment_intent_id | character varying | YES | - |
| is_refund | boolean | NO | false |
| refund_note | text | YES | - |
| recorded_by | uuid | NO | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_payments_invoice`, `payments_pkey`

---

## platform_branding

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| platform_name | character varying | NO | 'OraInvoice'::character varying |
| logo_url | character varying | YES | - |
| primary_colour | character varying | NO | '#2563EB'::character varying |
| secondary_colour | character varying | NO | '#1E40AF'::character varying |
| website_url | character varying | YES | - |
| signup_url | character varying | YES | - |
| support_email | character varying | YES | - |
| terms_url | character varying | YES | - |
| auto_detect_domain | boolean | NO | true |
| updated_at | timestamp with time zone | NO | now() |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `platform_branding_pkey`

---

## platform_notifications

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| notification_type | character varying | NO | - |
| title | character varying | NO | - |
| message | text | NO | - |
| severity | character varying | NO | 'info'::character varying |
| target_type | character varying | NO | 'all'::character varying |
| target_value | character varying | YES | - |
| scheduled_at | timestamp with time zone | YES | - |
| published_at | timestamp with time zone | YES | - |
| expires_at | timestamp with time zone | YES | - |
| maintenance_start | timestamp with time zone | YES | - |
| maintenance_end | timestamp with time zone | YES | - |
| is_active | boolean | NO | true |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_platform_notifications_active`, `idx_platform_notifications_scheduled`, `idx_platform_notifications_type`, `platform_notifications_pkey`

---

## platform_settings

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| key | character varying | NO | - |
| value | jsonb | NO | - |
| version | integer | NO | 1 |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `platform_settings_pkey`

---

## pos_sessions

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| location_id | uuid | YES | - |
| user_id | uuid | NO | - |
| opened_at | timestamp with time zone | NO | now() |
| closed_at | timestamp with time zone | YES | - |
| opening_cash | numeric | NO | 0 |
| closing_cash | numeric | YES | - |
| status | character varying | NO | 'open'::character varying |

**Indexes:** `idx_pos_sessions_org`, `idx_pos_sessions_user`, `pos_sessions_pkey`

---

## pos_transactions

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| session_id | uuid | YES | - |
| invoice_id | uuid | YES | - |
| customer_id | uuid | YES | - |
| table_id | uuid | YES | - |
| offline_transaction_id | character varying | YES | - |
| payment_method | character varying | NO | - |
| subtotal | numeric | NO | - |
| tax_amount | numeric | NO | - |
| discount_amount | numeric | NO | 0 |
| tip_amount | numeric | NO | 0 |
| total | numeric | NO | - |
| cash_tendered | numeric | YES | - |
| change_given | numeric | YES | - |
| is_offline_sync | boolean | NO | false |
| sync_status | character varying | YES | - |
| sync_conflicts | jsonb | YES | - |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_pos_transactions_offline`, `idx_pos_transactions_org`, `pos_transactions_pkey`

---

## pricing_rules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| product_id | uuid | YES | - |
| rule_type | character varying | NO | - |
| priority | integer | NO | 0 |
| customer_id | uuid | YES | - |
| customer_tag | character varying | YES | - |
| min_quantity | numeric | YES | - |
| max_quantity | numeric | YES | - |
| start_date | date | YES | - |
| end_date | date | YES | - |
| price_override | numeric | YES | - |
| discount_percent | numeric | YES | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_pricing_rules_org`, `idx_pricing_rules_product_active`, `pricing_rules_pkey`

---

## print_jobs

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| printer_id | uuid | YES | - |
| job_type | character varying | NO | - |
| payload | jsonb | NO | - |
| status | character varying | NO | 'pending'::character varying |
| retry_count | integer | NO | 0 |
| error_details | text | YES | - |
| created_at | timestamp with time zone | NO | now() |
| completed_at | timestamp with time zone | YES | - |

**Indexes:** `idx_print_jobs_pending`, `print_jobs_pkey`

---

## printer_configs

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| location_id | uuid | YES | - |
| name | character varying | NO | - |
| connection_type | character varying | NO | - |
| address | character varying | YES | - |
| paper_width | integer | NO | 80 |
| is_default | boolean | NO | false |
| is_kitchen_printer | boolean | NO | false |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_printer_configs_org`, `printer_configs_pkey`

---

## product_categories

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| parent_id | uuid | YES | - |
| display_order | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_product_categories_org`, `idx_product_categories_parent`, `product_categories_pkey`

---

## products

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| location_id | uuid | YES | - |
| name | character varying | NO | - |
| sku | character varying | YES | - |
| barcode | character varying | YES | - |
| category_id | uuid | YES | - |
| description | text | YES | - |
| unit_of_measure | character varying | NO | 'each'::character varying |
| sale_price | numeric | NO | 0 |
| cost_price | numeric | YES | 0 |
| tax_applicable | boolean | NO | true |
| tax_rate_override | numeric | YES | - |
| stock_quantity | numeric | NO | 0 |
| low_stock_threshold | numeric | YES | 0 |
| reorder_quantity | numeric | YES | 0 |
| allow_backorder | boolean | NO | false |
| supplier_id | uuid | YES | - |
| supplier_sku | character varying | YES | - |
| images | jsonb | NO | '[]'::jsonb |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_products_barcode`, `idx_products_category`, `idx_products_location`, `idx_products_org`, `idx_products_org_sku`, `idx_products_supplier`, `products_pkey`, `uq_products_org_sku`

---

## progress_claims

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| project_id | uuid | NO | - |
| claim_number | integer | NO | - |
| contract_value | numeric | NO | - |
| variations_to_date | numeric | NO | 0 |
| revised_contract_value | numeric | NO | - |
| work_completed_to_date | numeric | NO | - |
| work_completed_previous | numeric | NO | 0 |
| work_completed_this_period | numeric | NO | - |
| materials_on_site | numeric | NO | 0 |
| retention_withheld | numeric | NO | 0 |
| amount_due | numeric | NO | - |
| completion_percentage | numeric | NO | - |
| status | character varying | NO | 'draft'::character varying |
| invoice_id | uuid | YES | - |
| submitted_at | timestamp with time zone | YES | - |
| approved_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_progress_claims_org`, `idx_progress_claims_project`, `idx_progress_claims_status`, `progress_claims_pkey`, `uq_progress_claims_org_project_claim`

---

## projects

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| customer_id | uuid | YES | - |
| description | text | YES | - |
| budget_amount | numeric | YES | - |
| contract_value | numeric | YES | - |
| revised_contract_value | numeric | YES | - |
| retention_percentage | numeric | NO | 0 |
| start_date | date | YES | - |
| target_end_date | date | YES | - |
| status | character varying | NO | 'active'::character varying |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_projects_customer`, `idx_projects_org`, `projects_pkey`

---

## public_holidays

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| country_code | character varying | NO | - |
| holiday_date | date | NO | - |
| name | character varying | NO | - |
| local_name | character varying | YES | - |
| year | integer | NO | - |
| is_fixed | boolean | NO | false |
| synced_at | timestamp with time zone | NO | now() |

**Indexes:** `ix_public_holidays_country_year`, `public_holidays_pkey`, `uq_public_holidays_country_date_name`

---

## purchase_order_lines

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| po_id | uuid | NO | - |
| product_id | uuid | NO | - |
| description | text | YES | - |
| quantity_ordered | numeric | NO | - |
| quantity_received | numeric | NO | 0 |
| unit_cost | numeric | NO | - |
| line_total | numeric | NO | - |

**Indexes:** `idx_po_lines_po`, `idx_po_lines_product`, `purchase_order_lines_pkey`

---

## purchase_orders

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| po_number | character varying | NO | - |
| supplier_id | uuid | NO | - |
| job_id | uuid | YES | - |
| project_id | uuid | YES | - |
| status | character varying | NO | 'draft'::character varying |
| expected_delivery | date | YES | - |
| total_amount | numeric | NO | 0 |
| notes | text | YES | - |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_purchase_orders_org`, `idx_purchase_orders_status`, `idx_purchase_orders_supplier`, `purchase_orders_pkey`, `uq_purchase_orders_org_po_number`

---

## quote_line_items

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| quote_id | uuid | NO | - |
| org_id | uuid | NO | - |
| item_type | character varying | NO | - |
| description | character varying | NO | - |
| quantity | numeric | NO | 1 |
| unit_price | numeric | NO | - |
| hours | numeric | YES | - |
| hourly_rate | numeric | YES | - |
| is_gst_exempt | boolean | NO | false |
| warranty_note | text | YES | - |
| line_total | numeric | NO | - |
| sort_order | integer | NO | 0 |

**Indexes:** `idx_quote_line_items_quote`, `quote_line_items_pkey`

---

## quote_sequences

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| last_number | integer | NO | 0 |

**Indexes:** `quote_sequences_pkey`, `uq_quote_sequences_org_id`

---

## quotes

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| quote_number | character varying | NO | - |
| customer_id | uuid | NO | - |
| project_id | uuid | YES | - |
| status | character varying | NO | 'draft'::character varying |
| expiry_date | date | YES | - |
| terms | text | YES | - |
| internal_notes | text | YES | - |
| line_items | jsonb | NO | '[]'::jsonb |
| subtotal | numeric | NO | 0 |
| tax_amount | numeric | NO | 0 |
| total | numeric | NO | 0 |
| currency | character varying | YES | - |
| version_number | integer | NO | 1 |
| previous_version_id | uuid | YES | - |
| converted_invoice_id | uuid | YES | - |
| acceptance_token | character varying | YES | - |
| accepted_at | timestamp with time zone | YES | - |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| valid_until | date | YES | - |
| notes | text | YES | - |
| gst_amount | numeric | YES | 0 |
| vehicle_rego | character varying | YES | - |
| vehicle_make | character varying | YES | - |
| vehicle_model | character varying | YES | - |
| vehicle_year | integer | YES | - |
| subject | character varying | YES | - |
| discount_type | character varying | YES | 'percentage'::character varying |
| discount_value | numeric | NO | '0'::numeric |
| discount_amount | numeric | NO | '0'::numeric |
| shipping_charges | numeric | NO | '0'::numeric |
| adjustment | numeric | NO | '0'::numeric |

**Indexes:** `idx_quotes_acceptance_token`, `idx_quotes_customer`, `idx_quotes_expiry`, `idx_quotes_org_status`, `quotes_pkey`, `uq_quotes_org_quote_number`

---

## recurring_schedules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | NO | - |
| line_items | jsonb | NO | '[]'::jsonb |
| frequency | character varying | NO | - |
| start_date | date | NO | - |
| end_date | date | YES | - |
| next_generation_date | date | NO | - |
| auto_issue | boolean | NO | false |
| auto_email | boolean | NO | false |
| status | character varying | NO | 'active'::character varying |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_recurring_schedules_next`, `idx_recurring_schedules_org`, `recurring_schedules_pkey`

---

## reminder_queue

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| customer_id | uuid | NO | - |
| vehicle_id | uuid | YES | - |
| reminder_type | character varying | NO | - |
| channel | character varying | NO | - |
| recipient | character varying | NO | - |
| subject | character varying | YES | - |
| body | text | NO | - |
| status | character varying | NO | 'pending'::character varying |
| retry_count | integer | NO | 0 |
| max_retries | integer | NO | 3 |
| error_message | text | YES | - |
| scheduled_date | date | NO | CURRENT_DATE |
| scheduled_for | timestamp with time zone | NO | now() |
| locked_at | timestamp with time zone | YES | - |
| locked_by | character varying | YES | - |
| completed_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_reminder_queue_dedup`, `idx_reminder_queue_pending`, `reminder_queue_pkey`

---

## reminder_rules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| reminder_type | character varying | NO | - |
| target | character varying | NO | 'customer'::character varying |
| days_offset | integer | NO | 0 |
| timing | character varying | NO | 'after'::character varying |
| reference_date | character varying | NO | 'due_date'::character varying |
| send_email | boolean | NO | true |
| send_sms | boolean | NO | false |
| is_enabled | boolean | NO | false |
| sort_order | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `reminder_rules_pkey`

---

## report_schedules

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| report_type | character varying | NO | - |
| frequency | character varying | NO | 'daily'::character varying |
| filters | jsonb | NO | '{}'::jsonb |
| recipients | jsonb | NO | '[]'::jsonb |
| is_active | boolean | NO | true |
| last_generated_at | timestamp with time zone | YES | - |
| created_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_report_schedules_active`, `idx_report_schedules_org`, `report_schedules_pkey`

---

## restaurant_tables

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| location_id | uuid | YES | - |
| table_number | character varying | NO | - |
| seat_count | integer | NO | 4 |
| position_x | numeric | NO | 0 |
| position_y | numeric | NO | 0 |
| width | numeric | NO | 100 |
| height | numeric | NO | 100 |
| status | character varying | NO | 'available'::character varying |
| merged_with_id | uuid | YES | - |
| floor_plan_id | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_restaurant_tables_floor_plan`, `idx_restaurant_tables_org`, `restaurant_tables_pkey`

---

## retention_releases

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| project_id | uuid | NO | - |
| amount | numeric | NO | - |
| release_date | date | NO | - |
| payment_id | uuid | YES | - |
| notes | text | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_retention_releases_project`, `retention_releases_pkey`

---

## schedule_entries

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| staff_id | uuid | YES | - |
| job_id | uuid | YES | - |
| booking_id | uuid | YES | - |
| location_id | uuid | YES | - |
| title | character varying | YES | - |
| description | text | YES | - |
| start_time | timestamp with time zone | NO | - |
| end_time | timestamp with time zone | NO | - |
| entry_type | character varying | NO | 'job'::character varying |
| status | character varying | NO | 'scheduled'::character varying |
| notes | text | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_schedule_entries_org_date`, `idx_schedule_entries_staff`, `schedule_entries_pkey`

---

## sessions

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| user_id | uuid | NO | - |
| org_id | uuid | YES | - |
| refresh_token_hash | character varying | NO | - |
| family_id | uuid | NO | - |
| device_type | character varying | YES | - |
| browser | character varying | YES | - |
| ip_address | inet | YES | - |
| last_activity_at | timestamp with time zone | NO | now() |
| expires_at | timestamp with time zone | NO | - |
| is_revoked | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_sessions_expires_at`, `idx_sessions_family_id`, `idx_sessions_refresh_token_hash`, `idx_sessions_user_id`, `sessions_pkey`

---

## setup_wizard_progress

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| step_1_complete | boolean | NO | false |
| step_2_complete | boolean | NO | false |
| step_3_complete | boolean | NO | false |
| step_4_complete | boolean | NO | false |
| step_5_complete | boolean | NO | false |
| step_6_complete | boolean | NO | false |
| step_7_complete | boolean | NO | false |
| wizard_completed | boolean | NO | false |
| completed_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `setup_wizard_progress_pkey`, `uq_setup_wizard_progress_org_id`

---

## sku_mappings

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| external_sku | character varying | NO | - |
| internal_product_id | uuid | YES | - |
| platform | character varying | NO | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `sku_mappings_pkey`, `uq_sku_mapping_org_sku_platform`

---

## sms_conversations

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| phone_number | character varying | NO | - |
| contact_name | character varying | YES | - |
| last_message_at | timestamp with time zone | NO | - |
| last_message_preview | character varying | NO | - |
| unread_count | integer | NO | 0 |
| is_archived | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `ix_sms_conversations_org_last_msg`, `sms_conversations_pkey`, `uq_sms_conversations_org_phone`

---

## sms_messages

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| conversation_id | uuid | NO | - |
| org_id | uuid | NO | - |
| direction | character varying | NO | - |
| body | text | NO | - |
| from_number | character varying | NO | - |
| to_number | character varying | NO | - |
| external_message_id | character varying | YES | - |
| status | character varying | NO | 'pending'::character varying |
| parts_count | integer | NO | 1 |
| cost_nzd | numeric | YES | - |
| sent_at | timestamp with time zone | YES | - |
| delivered_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `ix_sms_messages_conv_created`, `ix_sms_messages_external_id`, `sms_messages_pkey`

---

## sms_package_purchases

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| tier_name | character varying | NO | - |
| sms_quantity | integer | NO | - |
| price_nzd | numeric | NO | - |
| credits_remaining | integer | NO | - |
| purchased_at | timestamp with time zone | NO | now() |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `sms_package_purchases_pkey`

---

## sms_verification_providers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| provider_key | character varying | NO | - |
| display_name | character varying | NO | - |
| description | text | YES | - |
| icon | character varying | YES | - |
| is_active | boolean | NO | false |
| is_default | boolean | NO | false |
| priority | integer | NO | 0 |
| credentials_encrypted | bytea | YES | - |
| credentials_set | boolean | NO | false |
| config | jsonb | YES | '{}'::jsonb |
| setup_guide | text | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `sms_verification_providers_pkey`, `sms_verification_providers_provider_key_key`

---

## staff_location_assignments

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| staff_id | uuid | NO | - |
| location_id | uuid | NO | - |
| assigned_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_staff_loc_location`, `idx_staff_loc_staff`, `staff_location_assignments_pkey`, `uq_staff_location_assignment`

---

## staff_members

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| user_id | uuid | YES | - |
| name | character varying | NO | - |
| email | character varying | YES | - |
| phone | character varying | YES | - |
| role_type | character varying | NO | 'employee'::character varying |
| hourly_rate | numeric | YES | - |
| overtime_rate | numeric | YES | - |
| is_active | boolean | NO | true |
| availability_schedule | jsonb | NO | '{}'::jsonb |
| skills | jsonb | NO | '[]'::jsonb |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| first_name | character varying | NO | ''::character varying |
| last_name | character varying | YES | - |
| employee_id | character varying | YES | - |
| position | character varying | YES | - |
| reporting_to | uuid | YES | - |
| shift_start | character varying | YES | - |
| shift_end | character varying | YES | - |

**Indexes:** `idx_staff_members_active`, `idx_staff_members_employee_id`, `idx_staff_members_org`, `staff_members_pkey`

---

## stock_movements

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| product_id | uuid | NO | - |
| location_id | uuid | YES | - |
| movement_type | character varying | NO | - |
| quantity_change | numeric | NO | - |
| resulting_quantity | numeric | NO | - |
| reference_type | character varying | YES | - |
| reference_id | uuid | YES | - |
| notes | text | YES | - |
| performed_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_stock_movements_org_date`, `idx_stock_movements_product`, `idx_stock_movements_product_date`, `stock_movements_pkey`

---

## stock_transfers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| from_location_id | uuid | NO | - |
| to_location_id | uuid | NO | - |
| product_id | uuid | NO | - |
| quantity | numeric | NO | - |
| status | character varying | NO | 'pending'::character varying |
| requested_by | uuid | YES | - |
| approved_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |
| completed_at | timestamp with time zone | YES | - |

**Indexes:** `idx_stock_transfers_org`, `stock_transfers_pkey`

---

## storage_packages

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| name | character varying | NO | - |
| storage_gb | integer | NO | - |
| price_nzd_per_month | numeric | NO | - |
| description | character varying | YES | - |
| is_active | boolean | NO | true |
| sort_order | integer | NO | 0 |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `storage_packages_pkey`

---

## subscription_plans

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| name | character varying | NO | - |
| monthly_price_nzd | numeric | NO | - |
| user_seats | integer | NO | - |
| storage_quota_gb | integer | NO | - |
| carjam_lookups_included | integer | NO | - |
| enabled_modules | jsonb | NO | '[]'::jsonb |
| is_public | boolean | NO | true |
| is_archived | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| storage_tier_pricing | jsonb | YES | '{}'::jsonb |
| trial_duration | integer | NO | 0 |
| trial_duration_unit | character varying | NO | 'days'::character varying |
| sms_included | boolean | NO | false |
| per_sms_cost_nzd | numeric | NO | '0'::numeric |
| sms_included_quota | integer | NO | 0 |
| sms_package_pricing | jsonb | YES | '[]'::jsonb |

**Indexes:** `subscription_plans_pkey`

---

## suppliers

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| name | character varying | NO | - |
| contact_name | character varying | YES | - |
| email | character varying | YES | - |
| phone | character varying | YES | - |
| address | text | YES | - |
| account_number | character varying | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| notes | text | YES | - |
| is_active | boolean | NO | true |

**Indexes:** `idx_suppliers_org`, `idx_suppliers_org_active`, `suppliers_pkey`

---

## table_reservations

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| table_id | uuid | NO | - |
| customer_name | character varying | NO | - |
| party_size | integer | NO | - |
| reservation_date | date | NO | - |
| reservation_time | time without time zone | NO | - |
| duration_minutes | integer | NO | 90 |
| notes | text | YES | - |
| status | character varying | NO | 'confirmed'::character varying |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_table_reservations_org_date`, `idx_table_reservations_table`, `table_reservations_pkey`

---

## time_entries

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| user_id | uuid | NO | - |
| staff_id | uuid | YES | - |
| job_id | uuid | YES | - |
| project_id | uuid | YES | - |
| description | text | YES | - |
| start_time | timestamp with time zone | NO | - |
| end_time | timestamp with time zone | YES | - |
| duration_minutes | integer | YES | - |
| is_billable | boolean | NO | true |
| hourly_rate | numeric | YES | - |
| is_invoiced | boolean | NO | false |
| invoice_id | uuid | YES | - |
| is_timer_active | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_time_entries_date`, `idx_time_entries_job`, `idx_time_entries_org_user`, `idx_time_entries_project`, `time_entries_pkey`

---

## tip_allocations

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| tip_id | uuid | NO | - |
| staff_member_id | uuid | NO | - |
| amount | numeric | NO | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_tip_allocations_staff`, `idx_tip_allocations_tip`, `tip_allocations_pkey`

---

## tips

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| invoice_id | uuid | YES | - |
| pos_transaction_id | uuid | YES | - |
| amount | numeric | NO | - |
| payment_method | character varying | NO | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_tips_org`, `idx_tips_org_created`, `tips_pkey`

---

## trade_categories

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| slug | character varying | NO | - |
| display_name | character varying | NO | - |
| family_id | uuid | NO | - |
| icon | character varying | YES | - |
| description | text | YES | - |
| invoice_template_layout | character varying | NO | 'standard'::character varying |
| recommended_modules | jsonb | NO | '[]'::jsonb |
| terminology_overrides | jsonb | NO | '{}'::jsonb |
| default_services | jsonb | NO | '[]'::jsonb |
| default_products | jsonb | NO | '[]'::jsonb |
| default_expense_categories | jsonb | NO | '[]'::jsonb |
| default_job_templates | jsonb | NO | '[]'::jsonb |
| compliance_notes | jsonb | NO | '{}'::jsonb |
| seed_data_version | integer | NO | 1 |
| is_active | boolean | NO | true |
| is_retired | boolean | NO | false |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_trade_categories_active`, `idx_trade_categories_family`, `trade_categories_pkey`, `uq_trade_categories_slug`

---

## trade_families

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| slug | character varying | NO | - |
| display_name | character varying | NO | - |
| icon | character varying | YES | - |
| display_order | integer | NO | 0 |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `trade_families_pkey`, `uq_trade_families_slug`

---

## user_permission_overrides

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| user_id | uuid | NO | - |
| permission_key | character varying | NO | - |
| is_granted | boolean | NO | - |
| granted_by | uuid | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_user_permission_overrides_user`, `uq_user_permission_overrides_user_perm`, `user_permission_overrides_pkey`

---

## users

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | YES | - |
| email | character varying | NO | - |
| password_hash | character varying | YES | - |
| role | character varying | NO | - |
| is_active | boolean | NO | true |
| is_email_verified | boolean | NO | false |
| mfa_methods | jsonb | NO | '[]'::jsonb |
| backup_codes_hash | jsonb | YES | - |
| passkey_credentials | jsonb | NO | '[]'::jsonb |
| google_oauth_id | character varying | YES | - |
| branch_ids | jsonb | NO | '[]'::jsonb |
| last_login_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |
| assigned_location_ids | jsonb | NO | '[]'::jsonb |
| franchise_group_id | uuid | YES | - |
| failed_login_count | integer | NO | 0 |
| locked_until | timestamp with time zone | YES | - |

**Indexes:** `idx_users_email`, `idx_users_org`, `uq_users_email`, `users_pkey`

---

## variation_orders

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| project_id | uuid | NO | - |
| variation_number | integer | NO | - |
| description | text | NO | - |
| cost_impact | numeric | NO | - |
| status | character varying | NO | 'draft'::character varying |
| submitted_at | timestamp with time zone | YES | - |
| approved_at | timestamp with time zone | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_variation_orders_org`, `idx_variation_orders_project`, `idx_variation_orders_status`, `uq_variation_orders_org_project_number`, `variation_orders_pkey`

---

## webhook_deliveries

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| webhook_id | uuid | NO | - |
| event_type | character varying | NO | - |
| payload | jsonb | NO | - |
| response_status | integer | YES | - |
| retry_count | integer | NO | 0 |
| status | character varying | NO | 'pending'::character varying |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `webhook_deliveries_pkey`

---

## webhook_delivery_log

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| webhook_id | uuid | NO | - |
| event_type | character varying | NO | - |
| payload | jsonb | YES | - |
| response_status | integer | YES | - |
| response_time_ms | integer | YES | - |
| retry_count | integer | NO | 0 |
| status | character varying | NO | - |
| error_details | text | YES | - |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `idx_webhook_delivery_webhook`, `webhook_delivery_log_pkey`

---

## webhooks

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| event_type | character varying | NO | - |
| url | character varying | NO | - |
| secret_encrypted | bytea | NO | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |

**Indexes:** `webhooks_pkey`

---

## woocommerce_connections

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| id | uuid | NO | gen_random_uuid() |
| org_id | uuid | NO | - |
| store_url | character varying | NO | - |
| consumer_key_encrypted | bytea | NO | - |
| consumer_secret_encrypted | bytea | NO | - |
| sync_frequency_minutes | integer | NO | 15 |
| auto_create_invoices | boolean | NO | true |
| invoice_status_on_import | character varying | NO | 'draft'::character varying |
| last_sync_at | timestamp with time zone | YES | - |
| is_active | boolean | NO | true |
| created_at | timestamp with time zone | NO | now() |
| updated_at | timestamp with time zone | NO | now() |

**Indexes:** `woocommerce_connections_org_id_key`, `woocommerce_connections_pkey`

---


## Appendix: Migration Coverage Audit

### Current State
- **Alembic head in DB:** `0094`
- **Pending migration:** `0095` (add `payment_pending` to organisations status constraint)
- **Total migrations:** 95 files (0001-0095)

### Migration-to-Table Mapping

| Migration | Description | Tables Affected |
|-----------|-------------|-----------------|
| 0001 | Create global tables | organisations, subscription_plans, users, platform_settings, platform_branding, integration_configs |
| 0002 | Create tenant-scoped tables | customers, branches, sessions, audit_log, error_log |
| 0003 | Create vehicle tables | global_vehicles, org_vehicles, customer_vehicles |
| 0004 | Create catalogue/inventory tables | items_catalogue, parts_catalogue, part_suppliers, labour_rates |
| 0005 | Create invoice/payment tables | invoices, line_items, payments, invoice_sequences, recurring_schedules |
| 0006 | Create quote/jobcard/booking tables | quotes, job_cards, job_card_items, bookings, booking_rules |
| 0007 | Create notification/audit/webhook tables | notification_log, notification_templates, notification_preferences, webhooks, webhook_deliveries, webhook_delivery_log |
| 0008 | Create RLS policies | (policies only) |
| 0009 | Create trade families | trade_families, trade_categories |
| 0010 | Create feature flags | feature_flags |
| 0011 | Create module registry | module_registry, org_modules |
| 0012 | Create compliance profiles | compliance_profiles |
| 0013 | Alter organisations | (add columns to organisations) |
| 0014 | Create setup wizard | setup_wizard_progress |
| 0015 | Create org terminology | org_terminology_overrides |
| 0016 | Create idempotency keys | idempotency_keys |
| 0017 | Create dead letter queue | dead_letter_queue |
| 0018-0022 | Seed data | (data only - trade families, categories, compliance, modules, branding) |
| 0023 | Create user permission overrides | user_permission_overrides |
| 0024 | Add user RBAC columns | (alter users) |
| 0025 | Create product categories | product_categories |
| 0026 | Create suppliers | suppliers |
| 0027 | Create products | products |
| 0028 | Create stock movements | stock_movements |
| 0029 | Create pricing rules | pricing_rules, discount_rules |
| 0030 | Create jobs | jobs, job_staff_assignments, job_status_history, job_templates |
| 0031 | Create quotes | (alter quotes - add fields) |
| 0032 | Create time entries | time_entries |
| 0033 | Create projects | projects |
| 0034 | Create expenses | expenses |
| 0035 | Create purchase orders | purchase_orders, purchase_order_lines |
| 0036 | Create staff members | staff_members, staff_location_assignments |
| 0037 | Create schedule entries | schedule_entries |
| 0038 | Create bookings | (alter bookings) |
| 0039 | Create POS sessions | pos_sessions |
| 0040 | Create POS transactions | pos_transactions |
| 0041 | Create printer configs | printer_configs |
| 0042 | Create print jobs | print_jobs |
| 0043 | Create floor plans | floor_plans, restaurant_tables, table_reservations |
| 0044 | Create kitchen orders | kitchen_orders |
| 0045 | Create tips tables | tips, tip_allocations |
| 0046 | Create recurring schedules | (alter recurring_schedules) |
| 0047 | Create progress claims | progress_claims |
| 0048 | Create variation orders | variation_orders |
| 0049 | Create retention releases | retention_releases |
| 0050 | Create compliance documents | compliance_documents |
| 0051 | Create ecommerce tables | woocommerce_connections, sku_mappings, ecommerce_sync_log |
| 0052 | Create multi-currency tables | org_currencies, exchange_rates |
| 0053 | Create loyalty tables | loyalty_config, loyalty_tiers, loyalty_transactions |
| 0054 | Create outbound webhooks | outbound_webhooks |
| 0055 | Create franchise/location tables | franchise_groups, locations, fleet_accounts, stock_transfers |
| 0056 | Add branding created_at | (alter platform_branding) |
| 0057 | Create assets table | assets |
| 0058 | Migrate vehicles to assets | (data migration) |
| 0059 | Create platform notifications | platform_notifications, notification_dismissals |
| 0060 | Add performance indexes | (indexes only) |
| 0061 | Org default values | (alter organisations) |
| 0062 | Create report schedules | report_schedules |
| 0063 | Add storage tier pricing | (alter subscription_plans) |
| 0064 | Create SMS verification providers | sms_verification_providers |
| 0065 | Create email providers | email_providers |
| 0066 | Enhance feature flags schema | (alter feature_flags) |
| 0067 | Seed comprehensive feature flags | (data only) |
| 0068 | Add missing module registry entries | (data only) |
| 0069 | Add trial period to plans | (alter subscription_plans) |
| 0070 | Add SMS included to plans | (alter subscription_plans) |
| 0071 | Add SMS billing fields | (alter organisations, subscription_plans) |
| 0073 | Add exchange rate to invoices | (alter invoices) |
| 0074 | Add email provider encryption/priority | (alter email_providers) |
| 2221e | Add failed login tracking | (alter users) |
| 202603 | Add extended vehicle fields | (alter global_vehicles) |
| lookup | Add lookup type field | (alter global_vehicles) |
| 0072 | Enhance customer fields | (alter customers) |
| 0075 | Add odometer readings | odometer_readings |
| 0076 | Add quote discount fields | (alter quotes) |
| 0077 | Create quote line items | quote_line_items, quote_sequences |
| 0078 | Add subject to quotes | (alter quotes) |
| 0080 | Enhance staff members | (alter staff_members) |
| 0076b | Register vehicles module | (data only) |
| 0081 | Booking modal enhancements | (alter bookings) |
| 0082 | Universal items catalogue | (alter items_catalogue) |
| 0083 | Add vehicle rego to bookings | (alter bookings) |
| 0084 | Job cards assigned to staff | (alter job_cards) |
| 0085 | Job card items catalogue ref | (alter job_card_items) |
| 0086 | Add vehicle service due date | (alter global_vehicles) |
| 0087 | Create SMS conversations/messages | sms_conversations, sms_messages |
| 0088 | Create reminder rules | reminder_rules, overdue_reminder_rules |
| 0089 | Create reminder queue | reminder_queue |
| 0090 | Create public holidays | public_holidays |
| 0091 | Add refunded status | (alter invoices constraint) |
| 0092 | Fix invoice FK cascade | (alter FKs) |
| 0093 | Create coupon tables | coupons, organisation_coupons, credit_notes, credit_note_sequences |
| 0094 | Create storage package tables | storage_packages, org_storage_addons, sms_package_purchases |
| 0095 | Add payment_pending status | (alter organisations constraint) - **NOT YET APPLIED** |

### Tables Created Outside Migrations (via raw SQL or manual)

Based on cross-referencing, the following tables exist in the DB and appear to be covered by migrations:

- `api_credentials` - created in migration 0001 (global tables)
- `job_attachments` - created in migration 0006 or 0030

### Notes

1. Migration `0095` needs to be applied: `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T app alembic upgrade head`
2. The `alembic_version` table currently shows revision `0094`
3. All 117 tables appear to have corresponding migrations
4. Some migrations have non-sequential revision IDs (e.g., `2221e0371bbc`, `202603091536`) but are properly chained via `revises` directives
