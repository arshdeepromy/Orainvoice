/**
 * Tests for TemplatePalette (B8):
 *   - Renders templates with aria-pressed toggle on click.
 *   - Re-clicking the selected template clears it.
 *
 * Validates: R6.1, R6.2, R6.10.
 */

import { render, screen, waitFor, fireEvent, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  return { default: { get: mockGet } }
})

import apiClient from '@/api/client'
import TemplatePalette from '../components/TemplatePalette'
import type { ShiftTemplateResponse } from '@/types/schedule'

const get = apiClient.get as ReturnType<typeof vi.fn>

const sampleTemplates: ShiftTemplateResponse[] = [
  {
    id: 't1',
    org_id: 'o',
    name: 'Morning shift',
    start_time: '09:00:00',
    end_time: '13:00:00',
    entry_type: 'job',
    created_at: '',
  },
  {
    id: 't2',
    org_id: 'o',
    name: 'Evening shift',
    start_time: '14:00:00',
    end_time: '22:00:00',
    entry_type: 'job',
    created_at: '',
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  get.mockResolvedValue({
    data: { templates: sampleTemplates, total: sampleTemplates.length },
  })
})

afterEach(() => cleanup())

describe('TemplatePalette', () => {
  it('renders templates and toggles selection on click', async () => {
    let selected: ShiftTemplateResponse | null = null
    const onSelect = (t: ShiftTemplateResponse | null) => {
      selected = t
    }
    const { rerender } = render(
      <MemoryRouter>
        <TemplatePalette selectedTemplate={null} onSelect={onSelect} />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText('Morning shift')).toBeInTheDocument(),
    )
    const morning = screen.getByText('Morning shift').closest('button')!
    expect(morning).toHaveAttribute('aria-pressed', 'false')

    fireEvent.click(morning)
    const result = selected as ShiftTemplateResponse | null
    expect(result?.id).toBe('t1')

    rerender(
      <MemoryRouter>
        <TemplatePalette
          selectedTemplate={sampleTemplates[0]}
          onSelect={onSelect}
        />
      </MemoryRouter>,
    )

    const morningAgain = screen.getByText('Morning shift').closest('button')!
    expect(morningAgain).toHaveAttribute('aria-pressed', 'true')

    // Click again → clears.
    fireEvent.click(morningAgain)
    expect(selected).toBeNull()
  })

  it('shows empty state with link when no templates exist', async () => {
    get.mockResolvedValue({ data: { templates: [], total: 0 } })
    render(
      <MemoryRouter>
        <TemplatePalette selectedTemplate={null} onSelect={() => {}} />
      </MemoryRouter>,
    )
    await waitFor(() =>
      expect(screen.getByText(/No shift templates/i)).toBeInTheDocument(),
    )
    const link = screen.getByRole('link', { name: /create one in settings/i })
    expect(link).toHaveAttribute('href', '/settings/shift-templates')
  })
})
