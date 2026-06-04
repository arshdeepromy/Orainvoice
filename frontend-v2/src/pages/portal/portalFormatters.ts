/**
 * Locale-aware formatting utilities for portal components.
 * All functions accept a locale string (e.g. 'en-NZ', 'mi-NZ') and use it
 * for Intl.DateTimeFormat / Intl.NumberFormat instead of hardcoding 'en-NZ'.
 */

export function formatCurrency(
  amount: number,
  locale: string,
  currency: string = 'NZD',
): string {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount)
}

export function formatDate(dateStr: string, locale: string): string {
  return new Date(dateStr).toLocaleDateString(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

export function formatDateTime(dateStr: string, locale: string): string {
  return new Date(dateStr).toLocaleDateString(locale, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatTime(dateStr: string, locale: string): string {
  return new Date(dateStr).toLocaleTimeString(locale, {
    hour: '2-digit',
    minute: '2-digit',
  })
}
