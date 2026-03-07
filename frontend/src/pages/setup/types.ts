/** Shared types for the setup wizard. */

export interface CountryOption {
  code: string
  name: string
  currency: string
  taxLabel: string
  taxRate: number
  dateFormat: string
  numberFormat: string
  timezone: string
  taxNumberLabel: string
  taxNumberRegex: string
}

export interface TradeFamily {
  slug: string
  display_name: string
  icon: string
}

export interface TradeCategory {
  slug: string
  display_name: string
  family_slug: string
  icon: string
  description: string
  recommended_modules: string[]
  terminology_overrides: Record<string, string>
  default_services: CatalogueItemData[]
  default_products: CatalogueItemData[]
}

export interface CatalogueItemData {
  name: string
  description?: string
  price: number
  unit_of_measure: string
  item_type: 'service' | 'product'
}

export interface ModuleInfo {
  slug: string
  display_name: string
  description: string
  category: string
  is_core: boolean
  dependencies: string[]
}

export interface WizardData {
  // Step 1: Country
  countryCode: string
  currency: string
  taxLabel: string
  taxRate: number
  dateFormat: string
  timezone: string
  taxNumberLabel: string
  taxNumberRegex: string

  // Step 2: Trade
  tradeCategorySlug: string
  tradeFamilySlug: string
  selectedTradeCategories: string[]

  // Step 3: Business
  businessName: string
  tradingName: string
  registrationNumber: string
  taxNumber: string
  phone: string
  address: string
  website: string

  // Step 4: Branding
  logoUrl: string
  logoFile: File | null
  primaryColour: string
  secondaryColour: string

  // Step 5: Modules
  enabledModules: string[]

  // Step 6: Catalogue
  catalogueItems: CatalogueItemData[]
}

export const INITIAL_WIZARD_DATA: WizardData = {
  countryCode: '',
  currency: 'NZD',
  taxLabel: 'GST',
  taxRate: 15,
  dateFormat: 'dd/MM/yyyy',
  timezone: 'Pacific/Auckland',
  taxNumberLabel: 'GST Number',
  taxNumberRegex: '',

  tradeCategorySlug: '',
  tradeFamilySlug: '',
  selectedTradeCategories: [],

  businessName: '',
  tradingName: '',
  registrationNumber: '',
  taxNumber: '',
  phone: '',
  address: '',
  website: '',

  logoUrl: '',
  logoFile: null,
  primaryColour: '#2563eb',
  secondaryColour: '#1e40af',

  enabledModules: [],

  catalogueItems: [],
}

export const COUNTRIES: CountryOption[] = [
  { code: 'NZ', name: 'New Zealand', currency: 'NZD', taxLabel: 'GST', taxRate: 15, dateFormat: 'dd/MM/yyyy', numberFormat: 'en-NZ', timezone: 'Pacific/Auckland', taxNumberLabel: 'GST Number', taxNumberRegex: '^\\d{8,9}$' },
  { code: 'AU', name: 'Australia', currency: 'AUD', taxLabel: 'GST', taxRate: 10, dateFormat: 'dd/MM/yyyy', numberFormat: 'en-AU', timezone: 'Australia/Sydney', taxNumberLabel: 'ABN', taxNumberRegex: '^\\d{11}$' },
  { code: 'GB', name: 'United Kingdom', currency: 'GBP', taxLabel: 'VAT', taxRate: 20, dateFormat: 'dd/MM/yyyy', numberFormat: 'en-GB', timezone: 'Europe/London', taxNumberLabel: 'VAT Number', taxNumberRegex: '^GB\\d{9}$' },
  { code: 'US', name: 'United States', currency: 'USD', taxLabel: 'Tax', taxRate: 0, dateFormat: 'MM/dd/yyyy', numberFormat: 'en-US', timezone: 'America/New_York', taxNumberLabel: 'EIN', taxNumberRegex: '^\\d{2}-\\d{7}$' },
  { code: 'CA', name: 'Canada', currency: 'CAD', taxLabel: 'GST/HST', taxRate: 5, dateFormat: 'yyyy-MM-dd', numberFormat: 'en-CA', timezone: 'America/Toronto', taxNumberLabel: 'BN', taxNumberRegex: '^\\d{9}$' },
  { code: 'IE', name: 'Ireland', currency: 'EUR', taxLabel: 'VAT', taxRate: 23, dateFormat: 'dd/MM/yyyy', numberFormat: 'en-IE', timezone: 'Europe/Dublin', taxNumberLabel: 'VAT Number', taxNumberRegex: '^IE\\d{7}[A-Z]{1,2}$' },
  { code: 'ZA', name: 'South Africa', currency: 'ZAR', taxLabel: 'VAT', taxRate: 15, dateFormat: 'yyyy/MM/dd', numberFormat: 'en-ZA', timezone: 'Africa/Johannesburg', taxNumberLabel: 'VAT Number', taxNumberRegex: '^\\d{10}$' },
  { code: 'SG', name: 'Singapore', currency: 'SGD', taxLabel: 'GST', taxRate: 9, dateFormat: 'dd/MM/yyyy', numberFormat: 'en-SG', timezone: 'Asia/Singapore', taxNumberLabel: 'GST Reg No', taxNumberRegex: '^\\d{9}[A-Z]$' },
  { code: 'DE', name: 'Germany', currency: 'EUR', taxLabel: 'MwSt', taxRate: 19, dateFormat: 'dd.MM.yyyy', numberFormat: 'de-DE', timezone: 'Europe/Berlin', taxNumberLabel: 'USt-IdNr', taxNumberRegex: '^DE\\d{9}$' },
  { code: 'FR', name: 'France', currency: 'EUR', taxLabel: 'TVA', taxRate: 20, dateFormat: 'dd/MM/yyyy', numberFormat: 'fr-FR', timezone: 'Europe/Paris', taxNumberLabel: 'TVA Number', taxNumberRegex: '^FR\\d{11}$' },
]

export const STEP_LABELS = [
  'Country',
  'Trade',
  'Business Details',
  'Branding',
  'Modules',
  'Catalogue',
  'Ready',
] as const
