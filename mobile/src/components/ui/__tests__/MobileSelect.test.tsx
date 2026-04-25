import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect } from 'vitest'
import { MobileSelect } from '../MobileSelect'

const options = [
  { value: 'nz', label: 'New Zealand' },
  { value: 'au', label: 'Australia' },
  { value: 'us', label: 'United States' },
]

describe('MobileSelect', () => {
  it('renders with label and options', () => {
    render(<MobileSelect label="Country" options={options} />)
    expect(screen.getByLabelText('Country')).toBeInTheDocument()
    expect(screen.getByText('New Zealand')).toBeInTheDocument()
    expect(screen.getByText('Australia')).toBeInTheDocument()
  })

  it('has 44px min height for touch target', () => {
    render(<MobileSelect label="Country" options={options} />)
    const select = screen.getByLabelText('Country')
    expect(select.className).toContain('min-h-[44px]')
  })

  it('shows placeholder option', () => {
    render(
      <MobileSelect label="Country" options={options} placeholder="Select a country" />,
    )
    expect(screen.getByText('Select a country')).toBeInTheDocument()
  })

  it('shows error message and sets aria-invalid', () => {
    render(<MobileSelect label="Country" options={options} error="Required" />)
    const select = screen.getByLabelText('Country')
    expect(select.getAttribute('aria-invalid')).toBe('true')
    expect(screen.getByRole('alert')).toHaveTextContent('Required')
  })

  it('allows selecting an option', async () => {
    const user = userEvent.setup()
    render(<MobileSelect label="Country" options={options} />)
    const select = screen.getByLabelText('Country')
    await user.selectOptions(select, 'au')
    expect(select).toHaveValue('au')
  })

  it('shows required asterisk', () => {
    render(<MobileSelect label="Country" options={options} required />)
    expect(screen.getByText('*')).toBeInTheDocument()
  })
})
