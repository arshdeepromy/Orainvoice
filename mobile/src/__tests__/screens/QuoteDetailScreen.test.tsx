import { describe, it, expect, vi, beforeEach } from 'vitest'
import { convertQuoteToInvoice, sendQuote } from '@/screens/quotes/QuoteDetailScreen'

/**
 * Unit tests for QuoteDetailScreen Convert to Invoice flow.
 * Requirements: 9.5
 */

// Mock apiClient
vi.mock('@/api/client', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
  },
}))

import apiClient from '@/api/client'

const mockedPost = vi.mocked(apiClient.post)

describe('QuoteDetailScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('convertQuoteToInvoice', () => {
    it('should POST to the convert endpoint and return the new invoice ID', async () => {
      mockedPost.mockResolvedValueOnce({ data: { id: 'inv-123' } })

      const result = await convertQuoteToInvoice('quote-456')

      expect(mockedPost).toHaveBeenCalledWith('/api/v1/quotes/quote-456/convert')
      expect(result).toBe('inv-123')
    })

    it('should return null when the API call fails', async () => {
      mockedPost.mockRejectedValueOnce(new Error('Network error'))

      const result = await convertQuoteToInvoice('quote-456')

      expect(result).toBeNull()
    })

    it('should return null when response has no id field', async () => {
      mockedPost.mockResolvedValueOnce({ data: {} })

      const result = await convertQuoteToInvoice('quote-456')

      expect(result).toBeNull()
    })

    it('should return null when response data is null', async () => {
      mockedPost.mockResolvedValueOnce({ data: null })

      const result = await convertQuoteToInvoice('quote-456')

      expect(result).toBeNull()
    })
  })

  describe('sendQuote', () => {
    it('should POST to the send endpoint and return true on success', async () => {
      mockedPost.mockResolvedValueOnce({ data: {} })

      const result = await sendQuote('quote-789')

      expect(mockedPost).toHaveBeenCalledWith('/api/v1/quotes/quote-789/send')
      expect(result).toBe(true)
    })

    it('should return false when the API call fails', async () => {
      mockedPost.mockRejectedValueOnce(new Error('Server error'))

      const result = await sendQuote('quote-789')

      expect(result).toBe(false)
    })
  })
})
