/**
 * Unit tests for the typed PPSR API client.
 *
 * Covers:
 *   - Happy-path: `search` returns the response payload directly.
 *   - 402 `ppsr_quota_exceeded`: rejection bubbles up untouched.
 *   - 422 `s241_purpose_required` / `carjam_not_configured`: rejection
 *     bubbles up untouched.
 *   - `listSearches` defaults to `{ items: [], total: 0 }` on empty
 *     response and forwards `params` + `signal` to axios.
 *   - `exportPdf` requests a blob (`responseType: 'blob'`) and returns it.
 *   - `forgetSearch` issues DELETE and resolves to void.
 *   - `linkVehicle` posts the payload and resolves to void.
 *   - `getQuota` defaults to safe zeros when fields are absent.
 *
 * **Validates: PPSR module spec task D1**
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ---------------------------------------------------------------------------
// Mock the apiClient module BEFORE importing the SUT.
// ---------------------------------------------------------------------------

const { mockGet, mockPost, mockPatch, mockDelete } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockDelete: vi.fn(),
}))

vi.mock('../client', () => ({
  default: {
    get: mockGet,
    post: mockPost,
    patch: mockPatch,
    delete: mockDelete,
  },
}))

// Imports must come after the mock is registered.
import {
  search,
  listSearches,
  getSearch,
  exportPdf,
  forgetSearch,
  linkVehicle,
  getQuota,
  ppsrApi,
  type PpsrSearchRequest,
  type PpsrSearchResult,
  type PpsrSearchListResponse,
  type PpsrQuotaResponse,
} from '../ppsr'

beforeEach(() => {
  mockGet.mockReset()
  mockPost.mockReset()
  mockPatch.mockReset()
  mockDelete.mockReset()
})

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const SEARCH_ID = '00000000-0000-0000-0000-000000000abc'
const ORG_VEHICLE_ID = '00000000-0000-0000-0000-000000000def'

function makeFreshResult(): PpsrSearchResult {
  return {
    search_id: SEARCH_ID,
    rego: 'ABC123',
    cached: false,
    cached_at: null,
    source_search_id: null,
    match: 'N',
    match_description: 'No match',
    statement_count: 0,
    ppsr_details: [],
    ownership_history: null,
    current_owner: null,
    warnings: [],
    basic: { make: 'Toyota', model: 'Hilux' },
    not_found: false,
    charges_cents: 50,
    carjam_request_id: 'cj-12345',
  }
}

/** Build the axios-style rejection payload that bubbles up unchanged. */
function makeAxiosError(status: number, detail: unknown): Error & {
  response: { status: number; data: { detail: unknown } }
} {
  const err = new Error(`Request failed with status ${status}`) as Error & {
    response: { status: number; data: { detail: unknown } }
  }
  err.response = { status, data: { detail } }
  return err
}

// ===========================================================================
// search — happy path
// ===========================================================================

describe('search — happy path', () => {
  it('returns the response data directly', async () => {
    const result = makeFreshResult()
    mockPost.mockResolvedValueOnce({ data: result })

    const payload: PpsrSearchRequest = {
      rego: 'ABC123',
      include_warnings: true,
    }
    const got = await search(payload)

    expect(got).toEqual(result)
    expect(got.cached).toBe(false)
    expect(got.match).toBe('N')
  })

  it('uses the absolute /api/v2/ppsr/search path and forwards body + signal', async () => {
    mockPost.mockResolvedValueOnce({ data: makeFreshResult() })

    const controller = new AbortController()
    const payload: PpsrSearchRequest = {
      rego: 'ABC123',
      include_ownership_history: true,
      include_current_owner: true,
      include_warnings: true,
      include_fws: false,
      check_hidden_plates: false,
      s241_purpose: 'Selling vehicle',
      force_refresh: true,
    }

    await search(payload, controller.signal)

    expect(mockPost).toHaveBeenCalledTimes(1)
    expect(mockPost.mock.calls[0][0]).toBe('/api/v2/ppsr/search')
    expect(mockPost.mock.calls[0][1]).toEqual(payload)
    expect(mockPost.mock.calls[0][2]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    )
  })

  it('preserves a cached result on the typed surface', async () => {
    const cached: PpsrSearchResult = {
      ...makeFreshResult(),
      cached: true,
      cached_at: '2026-06-01T14:32:00Z',
      source_search_id: SEARCH_ID,
    }
    mockPost.mockResolvedValueOnce({ data: cached })

    const got = await search({ rego: 'ABC123' })

    expect(got.cached).toBe(true)
    expect(got.cached_at).toBe('2026-06-01T14:32:00Z')
    expect(got.source_search_id).toBe(SEARCH_ID)
  })
})

// ===========================================================================
// search — 402 quota exceeded
// ===========================================================================

describe('search — 402 quota exceeded', () => {
  it('rejects with the original axios error so callers can inspect status + body', async () => {
    const err = makeAxiosError(402, {
      detail: 'ppsr_quota_exceeded',
      used: 50,
      included: 50,
    })
    mockPost.mockRejectedValueOnce(err)

    await expect(search({ rego: 'ABC123' })).rejects.toMatchObject({
      response: {
        status: 402,
        data: { detail: { detail: 'ppsr_quota_exceeded', used: 50, included: 50 } },
      },
    })
  })
})

// ===========================================================================
// search — 422 unprocessable
// ===========================================================================

describe('search — 422 unprocessable', () => {
  it('rejects with the original axios error for s241_purpose_required', async () => {
    const err = makeAxiosError(422, { detail: 's241_purpose_required' })
    mockPost.mockRejectedValueOnce(err)

    await expect(
      search({
        rego: 'ABC123',
        include_current_owner: true,
        // s241_purpose deliberately missing — server rejects with 422.
      }),
    ).rejects.toMatchObject({
      response: { status: 422 },
    })
  })

  it('rejects with the original axios error for carjam_not_configured', async () => {
    const err = makeAxiosError(422, {
      detail: 'carjam_not_configured',
      help_url: '/admin/integrations',
    })
    mockPost.mockRejectedValueOnce(err)

    await expect(search({ rego: 'ABC123' })).rejects.toMatchObject({
      response: {
        status: 422,
        data: {
          detail: { detail: 'carjam_not_configured', help_url: '/admin/integrations' },
        },
      },
    })
  })
})

// ===========================================================================
// listSearches
// ===========================================================================

describe('listSearches', () => {
  it('returns { items: [], total: 0 } when response body is missing', async () => {
    mockGet.mockResolvedValueOnce({ data: undefined })

    const got = await listSearches()

    expect(got).toEqual({ items: [], total: 0 })
    expect(mockGet).toHaveBeenCalledTimes(1)
  })

  it('returns { items: [], total: 0 } when items/total are absent', async () => {
    mockGet.mockResolvedValueOnce({ data: {} })

    const got = await listSearches()

    expect(got.items).toEqual([])
    expect(got.total).toBe(0)
  })

  it('forwards the populated body untouched', async () => {
    const body: PpsrSearchListResponse = {
      items: [
        {
          id: SEARCH_ID,
          rego: 'ABC123',
          match: 'N',
          match_description: 'No match',
          statement_count: 0,
          has_warnings: false,
          has_ownership_data: false,
          not_found: false,
          forgotten_at: null,
          org_vehicle_id: null,
          user_id: '00000000-0000-0000-0000-000000000999',
          created_at: '2026-06-01T14:32:00Z',
        },
      ],
      total: 1,
    }
    mockGet.mockResolvedValueOnce({ data: body })

    const got = await listSearches()

    expect(got.total).toBe(1)
    expect(got.items).toHaveLength(1)
    expect(got.items[0].rego).toBe('ABC123')
  })

  it('forwards params and signal to axios via the request config', async () => {
    mockGet.mockResolvedValueOnce({ data: { items: [], total: 0 } })

    const controller = new AbortController()
    await listSearches(
      {
        rego: 'ABC123',
        match: 'Y',
        user_id: '00000000-0000-0000-0000-000000000007',
        date_from: '2026-05-01T00:00:00Z',
        date_to: '2026-06-01T00:00:00Z',
        offset: 25,
        limit: 50,
      },
      controller.signal,
    )

    expect(mockGet).toHaveBeenCalledWith(
      '/api/v2/ppsr/searches',
      expect.objectContaining({
        params: {
          rego: 'ABC123',
          match: 'Y',
          user_id: '00000000-0000-0000-0000-000000000007',
          date_from: '2026-05-01T00:00:00Z',
          date_to: '2026-06-01T00:00:00Z',
          offset: 25,
          limit: 50,
        },
        signal: controller.signal,
      }),
    )
  })
})

// ===========================================================================
// getSearch
// ===========================================================================

describe('getSearch', () => {
  it('GETs the absolute detail path and returns response.data', async () => {
    const result = makeFreshResult()
    mockGet.mockResolvedValueOnce({ data: result })

    const got = await getSearch(SEARCH_ID)

    expect(got).toEqual(result)
    expect(mockGet.mock.calls[0][0]).toBe(`/api/v2/ppsr/searches/${SEARCH_ID}`)
  })

  it('forwards the abort signal', async () => {
    mockGet.mockResolvedValueOnce({ data: makeFreshResult() })
    const controller = new AbortController()

    await getSearch(SEARCH_ID, controller.signal)

    expect(mockGet.mock.calls[0][1]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    )
  })

  it('rejects with HTTP 410 when the search has been forgotten', async () => {
    const err = makeAxiosError(410, {
      detail: 'search_forgotten',
      forgotten_at: '2026-06-02T10:00:00Z',
    })
    mockGet.mockRejectedValueOnce(err)

    await expect(getSearch(SEARCH_ID)).rejects.toMatchObject({
      response: { status: 410 },
    })
  })
})

// ===========================================================================
// exportPdf
// ===========================================================================

describe('exportPdf', () => {
  it('requests responseType=blob and returns the Blob', async () => {
    const blob = new Blob(['%PDF-1.4 ...'], { type: 'application/pdf' })
    mockGet.mockResolvedValueOnce({ data: blob })

    const got = await exportPdf(SEARCH_ID)

    expect(got).toBe(blob)
    expect(mockGet).toHaveBeenCalledWith(
      `/api/v2/ppsr/searches/${SEARCH_ID}/export`,
      expect.objectContaining({ responseType: 'blob' }),
    )
  })

  it('forwards the abort signal alongside responseType', async () => {
    const blob = new Blob([''], { type: 'application/pdf' })
    mockGet.mockResolvedValueOnce({ data: blob })
    const controller = new AbortController()

    await exportPdf(SEARCH_ID, controller.signal)

    expect(mockGet.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        responseType: 'blob',
        signal: controller.signal,
      }),
    )
  })
})

// ===========================================================================
// forgetSearch
// ===========================================================================

describe('forgetSearch', () => {
  it('issues DELETE on the forget path and resolves to void', async () => {
    mockDelete.mockResolvedValueOnce({ data: undefined })

    const got = await forgetSearch(SEARCH_ID)

    expect(got).toBeUndefined()
    expect(mockDelete).toHaveBeenCalledWith(
      `/api/v2/ppsr/searches/${SEARCH_ID}/forget`,
      expect.any(Object),
    )
  })

  it('forwards the abort signal', async () => {
    mockDelete.mockResolvedValueOnce({ data: undefined })
    const controller = new AbortController()

    await forgetSearch(SEARCH_ID, controller.signal)

    expect(mockDelete.mock.calls[0][1]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    )
  })
})

// ===========================================================================
// linkVehicle
// ===========================================================================

describe('linkVehicle', () => {
  it('POSTs the payload and resolves to void', async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: 'linked',
        search_id: SEARCH_ID,
        org_vehicle_id: ORG_VEHICLE_ID,
      },
    })

    const got = await linkVehicle(SEARCH_ID, { org_vehicle_id: ORG_VEHICLE_ID })

    expect(got).toBeUndefined()
    expect(mockPost.mock.calls[0][0]).toBe(
      `/api/v2/ppsr/searches/${SEARCH_ID}/link-vehicle`,
    )
    expect(mockPost.mock.calls[0][1]).toEqual({ org_vehicle_id: ORG_VEHICLE_ID })
  })

  it('forwards the abort signal', async () => {
    mockPost.mockResolvedValueOnce({
      data: {
        status: 'linked',
        search_id: SEARCH_ID,
        org_vehicle_id: ORG_VEHICLE_ID,
      },
    })
    const controller = new AbortController()

    await linkVehicle(SEARCH_ID, { org_vehicle_id: ORG_VEHICLE_ID }, controller.signal)

    expect(mockPost.mock.calls[0][2]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    )
  })
})

// ===========================================================================
// getQuota
// ===========================================================================

describe('getQuota', () => {
  it('GETs the quota path and returns the populated response', async () => {
    const body: PpsrQuotaResponse = {
      used: 7,
      included: 50,
      hidden_plate_used: 1,
      hidden_plate_included: 5,
      resets_at: '2026-07-01T00:00:00Z',
    }
    mockGet.mockResolvedValueOnce({ data: body })

    const got = await getQuota()

    expect(got).toEqual(body)
    expect(mockGet.mock.calls[0][0]).toBe('/api/v2/ppsr/quota')
  })

  it('defaults missing fields to safe zeros / null', async () => {
    mockGet.mockResolvedValueOnce({ data: undefined })

    const got = await getQuota()

    expect(got).toEqual({
      used: 0,
      included: 0,
      hidden_plate_used: 0,
      hidden_plate_included: 0,
      resets_at: null,
    })
  })

  it('forwards the abort signal', async () => {
    mockGet.mockResolvedValueOnce({ data: undefined })
    const controller = new AbortController()

    await getQuota(controller.signal)

    expect(mockGet.mock.calls[0][1]).toEqual(
      expect.objectContaining({ signal: controller.signal }),
    )
  })
})

// ===========================================================================
// Default export — namespace-style API
// ===========================================================================

describe('ppsrApi default export', () => {
  it('exposes every method on the namespace object', () => {
    expect(ppsrApi.search).toBe(search)
    expect(ppsrApi.listSearches).toBe(listSearches)
    expect(ppsrApi.getSearch).toBe(getSearch)
    expect(ppsrApi.exportPdf).toBe(exportPdf)
    expect(ppsrApi.forgetSearch).toBe(forgetSearch)
    expect(ppsrApi.linkVehicle).toBe(linkVehicle)
    expect(ppsrApi.getQuota).toBe(getQuota)
  })
})
