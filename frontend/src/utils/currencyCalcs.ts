/**
 * Pure utility functions for multi-currency calculations.
 * Extracted for property-based testing.
 *
 * Validates: Requirements 13.6, 13.7
 */

/* ------------------------------------------------------------------ */
/*  ISO 4217 Currency Registry                                         */
/* ------------------------------------------------------------------ */

export interface CurrencyFormat {
  code: string
  symbol: string
  decimalPlaces: number
  symbolPosition: 'before' | 'after'
  thousandsSeparator: string
  decimalSeparator: string
}

/**
 * ISO 4217 currency definitions — mirrors the backend CURRENCY_REGISTRY
 * in app/modules/multi_currency/formatting.py.
 */
export const CURRENCY_REGISTRY: Record<string, CurrencyFormat> = {
  NZD: { code: 'NZD', symbol: '$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  AUD: { code: 'AUD', symbol: 'A$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  USD: { code: 'USD', symbol: '$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  GBP: { code: 'GBP', symbol: '£', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  EUR: { code: 'EUR', symbol: '€', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: '.', decimalSeparator: ',' },
  JPY: { code: 'JPY', symbol: '¥', decimalPlaces: 0, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  CAD: { code: 'CAD', symbol: 'C$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  CHF: { code: 'CHF', symbol: 'CHF', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: "'", decimalSeparator: '.' },
  CNY: { code: 'CNY', symbol: '¥', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  SGD: { code: 'SGD', symbol: 'S$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  HKD: { code: 'HKD', symbol: 'HK$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  KRW: { code: 'KRW', symbol: '₩', decimalPlaces: 0, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  INR: { code: 'INR', symbol: '₹', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  MXN: { code: 'MXN', symbol: '$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  BRL: { code: 'BRL', symbol: 'R$', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: '.', decimalSeparator: ',' },
  ZAR: { code: 'ZAR', symbol: 'R', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ' ', decimalSeparator: '.' },
  SEK: { code: 'SEK', symbol: 'kr', decimalPlaces: 2, symbolPosition: 'after', thousandsSeparator: ' ', decimalSeparator: ',' },
  NOK: { code: 'NOK', symbol: 'kr', decimalPlaces: 2, symbolPosition: 'after', thousandsSeparator: ' ', decimalSeparator: ',' },
  DKK: { code: 'DKK', symbol: 'kr', decimalPlaces: 2, symbolPosition: 'after', thousandsSeparator: '.', decimalSeparator: ',' },
  THB: { code: 'THB', symbol: '฿', decimalPlaces: 2, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  KWD: { code: 'KWD', symbol: 'KD', decimalPlaces: 3, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  BHD: { code: 'BHD', symbol: 'BD', decimalPlaces: 3, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
  OMR: { code: 'OMR', symbol: 'OMR', decimalPlaces: 3, symbolPosition: 'before', thousandsSeparator: ',', decimalSeparator: '.' },
}

/**
 * Get the format definition for a currency code.
 * Falls back to a generic 2-decimal format for unknown codes.
 */
export function getCurrencyFormat(currencyCode: string): CurrencyFormat {
  const code = currencyCode.toUpperCase()
  const fmt = CURRENCY_REGISTRY[code]
  if (fmt) return fmt
  return {
    code,
    symbol: code,
    decimalPlaces: 2,
    symbolPosition: 'before',
    thousandsSeparator: ',',
    decimalSeparator: '.',
  }
}

/* ------------------------------------------------------------------ */
/*  Formatting                                                         */
/* ------------------------------------------------------------------ */

/**
 * Format integer part with thousands separator.
 */
function formatIntegerPart(intPart: number, separator: string): string {
  const str = Math.abs(intPart).toString()
  if (str.length <= 3) return str
  const parts: string[] = []
  let i = str.length
  while (i > 0) {
    const start = Math.max(0, i - 3)
    parts.unshift(str.slice(start, i))
    i = start
  }
  return parts.join(separator)
}

/**
 * Format a numeric amount per ISO 4217 standard for the given currency code.
 *
 * Uses correct decimal places, symbol, thousands separator, and symbol position.
 *
 * Examples:
 *   formatCurrencyAmount(1234.56, 'NZD') → '$1,234.56'
 *   formatCurrencyAmount(1234.56, 'EUR') → '€1.234,56'
 *   formatCurrencyAmount(1234, 'JPY')    → '¥1,234'
 *   formatCurrencyAmount(1234.56, 'SEK') → '1 234,56 kr'
 *   formatCurrencyAmount(1234.567, 'KWD') → 'KD1,234.567'
 */
export function formatCurrencyAmount(amount: number, currencyCode: string): string {
  const fmt = getCurrencyFormat(currencyCode)
  const sign = amount < 0 ? '-' : ''
  const absAmount = Math.abs(amount)

  // Round to correct decimal places
  const factor = Math.pow(10, fmt.decimalPlaces)
  const rounded = Math.round(absAmount * factor) / factor

  // Split into integer and decimal parts
  const intPart = Math.floor(rounded)
  const intStr = formatIntegerPart(intPart, fmt.thousandsSeparator)

  let numberStr: string
  if (fmt.decimalPlaces > 0) {
    const decRaw = Math.round((rounded - intPart) * factor)
    const decStr = decRaw.toString().padStart(fmt.decimalPlaces, '0')
    numberStr = `${intStr}${fmt.decimalSeparator}${decStr}`
  } else {
    numberStr = intStr
  }

  if (fmt.symbolPosition === 'after') {
    return `${sign}${numberStr} ${fmt.symbol}`
  }
  return `${sign}${fmt.symbol}${numberStr}`
}

/* ------------------------------------------------------------------ */
/*  Exchange Rate Validation                                           */
/* ------------------------------------------------------------------ */

/**
 * Returns true if a non-base currency has no exchange rate available.
 * The base currency always has an implicit rate of 1, so it never "misses" a rate.
 *
 * @param currencyCode - The currency to check
 * @param rates - Map of currency code → exchange rate (number > 0)
 * @param baseCurrency - The organisation's base currency code
 */
export function isMissingExchangeRate(
  currencyCode: string,
  rates: Record<string, number>,
  baseCurrency: string,
): boolean {
  const code = currencyCode.toUpperCase()
  const base = baseCurrency.toUpperCase()

  // Base currency always has an implicit rate of 1
  if (code === base) return false

  const rate = rates[code]
  return rate === undefined || rate === null || rate <= 0
}

/* ------------------------------------------------------------------ */
/*  ISO 4217 Full List (for currency search/enablement)                */
/* ------------------------------------------------------------------ */

export interface ISO4217Currency {
  code: string
  name: string
  symbol: string
  decimalPlaces: number
}

/** Subset of ISO 4217 currencies for the enablement search. */
export const ISO_4217_CURRENCIES: ISO4217Currency[] = [
  { code: 'AED', name: 'UAE Dirham', symbol: 'د.إ', decimalPlaces: 2 },
  { code: 'AUD', name: 'Australian Dollar', symbol: 'A$', decimalPlaces: 2 },
  { code: 'BHD', name: 'Bahraini Dinar', symbol: 'BD', decimalPlaces: 3 },
  { code: 'BRL', name: 'Brazilian Real', symbol: 'R$', decimalPlaces: 2 },
  { code: 'CAD', name: 'Canadian Dollar', symbol: 'C$', decimalPlaces: 2 },
  { code: 'CHF', name: 'Swiss Franc', symbol: 'CHF', decimalPlaces: 2 },
  { code: 'CNY', name: 'Chinese Yuan', symbol: '¥', decimalPlaces: 2 },
  { code: 'DKK', name: 'Danish Krone', symbol: 'kr', decimalPlaces: 2 },
  { code: 'EUR', name: 'Euro', symbol: '€', decimalPlaces: 2 },
  { code: 'FJD', name: 'Fijian Dollar', symbol: 'FJ$', decimalPlaces: 2 },
  { code: 'GBP', name: 'British Pound', symbol: '£', decimalPlaces: 2 },
  { code: 'HKD', name: 'Hong Kong Dollar', symbol: 'HK$', decimalPlaces: 2 },
  { code: 'IDR', name: 'Indonesian Rupiah', symbol: 'Rp', decimalPlaces: 2 },
  { code: 'INR', name: 'Indian Rupee', symbol: '₹', decimalPlaces: 2 },
  { code: 'JPY', name: 'Japanese Yen', symbol: '¥', decimalPlaces: 0 },
  { code: 'KRW', name: 'South Korean Won', symbol: '₩', decimalPlaces: 0 },
  { code: 'KWD', name: 'Kuwaiti Dinar', symbol: 'KD', decimalPlaces: 3 },
  { code: 'MXN', name: 'Mexican Peso', symbol: '$', decimalPlaces: 2 },
  { code: 'MYR', name: 'Malaysian Ringgit', symbol: 'RM', decimalPlaces: 2 },
  { code: 'NOK', name: 'Norwegian Krone', symbol: 'kr', decimalPlaces: 2 },
  { code: 'NZD', name: 'New Zealand Dollar', symbol: '$', decimalPlaces: 2 },
  { code: 'OMR', name: 'Omani Rial', symbol: 'OMR', decimalPlaces: 3 },
  { code: 'PHP', name: 'Philippine Peso', symbol: '₱', decimalPlaces: 2 },
  { code: 'PKR', name: 'Pakistani Rupee', symbol: '₨', decimalPlaces: 2 },
  { code: 'SEK', name: 'Swedish Krona', symbol: 'kr', decimalPlaces: 2 },
  { code: 'SGD', name: 'Singapore Dollar', symbol: 'S$', decimalPlaces: 2 },
  { code: 'THB', name: 'Thai Baht', symbol: '฿', decimalPlaces: 2 },
  { code: 'TWD', name: 'Taiwan Dollar', symbol: 'NT$', decimalPlaces: 2 },
  { code: 'USD', name: 'US Dollar', symbol: '$', decimalPlaces: 2 },
  { code: 'ZAR', name: 'South African Rand', symbol: 'R', decimalPlaces: 2 },
]
