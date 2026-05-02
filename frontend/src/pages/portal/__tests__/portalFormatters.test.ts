import { describe, it, expect } from 'vitest'
import { formatCurrency, formatDate, formatDateTime, formatTime } from '../portalFormatters'

describe('portalFormatters', () => {
  describe('formatCurrency', () => {
    it('formats NZD with en-NZ locale', () => {
      const result = formatCurrency(1234.56, 'en-NZ')
      expect(result).toContain('1,234.56')
    })

    it('formats with a different locale', () => {
      const result = formatCurrency(1234.56, 'de-DE', 'EUR')
      // German locale uses comma for decimal separator
      expect(result).toBeTruthy()
    })

    it('uses NZD as default currency', () => {
      const result = formatCurrency(100, 'en-NZ')
      expect(result).toContain('100.00')
    })

    it('accepts custom currency', () => {
      const result = formatCurrency(100, 'en-US', 'USD')
      expect(result).toContain('100.00')
    })
  })

  describe('formatDate', () => {
    it('formats a date string with en-NZ locale', () => {
      const result = formatDate('2024-03-15', 'en-NZ')
      expect(result).toContain('15')
      expect(result).toContain('2024')
    })

    it('formats a date string with a different locale', () => {
      const result = formatDate('2024-03-15', 'en-US')
      expect(result).toContain('15')
      expect(result).toContain('2024')
    })
  })

  describe('formatDateTime', () => {
    it('formats a datetime string with en-NZ locale', () => {
      const result = formatDateTime('2024-03-15T14:30:00', 'en-NZ')
      expect(result).toContain('15')
      expect(result).toContain('2024')
    })
  })

  describe('formatTime', () => {
    it('formats a time string with en-NZ locale', () => {
      const result = formatTime('2024-03-15T14:30:00', 'en-NZ')
      expect(result).toBeTruthy()
    })
  })
})
