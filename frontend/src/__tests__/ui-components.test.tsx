import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Tabs } from '../components/ui/Tabs'
import { Badge } from '../components/ui/Badge'
import { Spinner } from '../components/ui/Spinner'
import { Modal } from '../components/ui/Modal'
import { DataTable, type Column } from '../components/ui/DataTable'

/**
 * Validates: Requirements 57.1, 57.2, 55.1
 * - 57.1: Keyboard navigation for all interactive elements with visible focus indicators
 * - 57.2: Appropriate ARIA labels and roles for all UI components
 * - 55.1: Responsive React application that displays correctly on all screens
 */

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------
describe('Button', () => {
  it('renders with text content', () => {
    render(<Button>Save</Button>)
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('applies disabled state and aria-disabled', () => {
    render(<Button disabled>Submit</Button>)
    const btn = screen.getByRole('button', { name: 'Submit' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('aria-disabled', 'true')
  })

  it('shows loading state with aria-busy', () => {
    render(<Button loading>Processing</Button>)
    const btn = screen.getByRole('button', { name: 'Processing' })
    expect(btn).toBeDisabled()
    expect(btn).toHaveAttribute('aria-busy', 'true')
  })

  it('activates on Enter key press', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    render(<Button onClick={onClick}>Go</Button>)
    const btn = screen.getByRole('button', { name: 'Go' })
    btn.focus()
    await user.keyboard('{Enter}')
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('activates on Space key press', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    render(<Button onClick={onClick}>Go</Button>)
    const btn = screen.getByRole('button', { name: 'Go' })
    btn.focus()
    await user.keyboard(' ')
    expect(onClick).toHaveBeenCalledTimes(1)
  })
})

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------
describe('Input', () => {
  it('renders with associated label', () => {
    render(<Input label="Email" />)
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })

  it('sets aria-invalid and aria-describedby when error is present', () => {
    render(<Input label="Email" error="Required field" />)
    const input = screen.getByLabelText('Email')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-describedby', expect.stringContaining('error'))
  })

  it('displays error message with alert role', () => {
    render(<Input label="Email" error="Required field" />)
    expect(screen.getByRole('alert')).toHaveTextContent('Required field')
  })

  it('links aria-describedby to helper text when no error', () => {
    render(<Input label="Name" helperText="Enter your full name" />)
    const input = screen.getByLabelText('Name')
    expect(input).toHaveAttribute('aria-describedby', expect.stringContaining('helper'))
  })
})

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
describe('Tabs', () => {
  const tabData = [
    { id: 'details', label: 'Details', content: <p>Details content</p> },
    { id: 'history', label: 'History', content: <p>History content</p> },
    { id: 'notes', label: 'Notes', content: <p>Notes content</p> },
  ]

  it('renders tablist, tab, and tabpanel roles', () => {
    render(<Tabs tabs={tabData} />)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
    expect(screen.getAllByRole('tab')).toHaveLength(3)
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('sets aria-selected on the active tab', () => {
    render(<Tabs tabs={tabData} />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[1]).toHaveAttribute('aria-selected', 'false')
  })

  it('navigates tabs with ArrowRight key', async () => {
    const user = userEvent.setup()
    render(<Tabs tabs={tabData} />)
    const tabs = screen.getAllByRole('tab')
    tabs[0].focus()
    await user.keyboard('{ArrowRight}')
    expect(tabs[1]).toHaveFocus()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('History content')
  })

  it('navigates tabs with ArrowLeft key and wraps around', async () => {
    const user = userEvent.setup()
    render(<Tabs tabs={tabData} />)
    const tabs = screen.getAllByRole('tab')
    tabs[0].focus()
    await user.keyboard('{ArrowLeft}')
    expect(tabs[2]).toHaveFocus()
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Notes content')
  })

  it('links tab to tabpanel via aria-controls', () => {
    render(<Tabs tabs={tabData} />)
    const firstTab = screen.getAllByRole('tab')[0]
    const panelId = firstTab.getAttribute('aria-controls')
    expect(panelId).toBeTruthy()
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', panelId)
  })
})

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------
describe('Badge', () => {
  it('renders text content', () => {
    render(<Badge>Paid</Badge>)
    expect(screen.getByText('Paid')).toBeInTheDocument()
  })

  it('includes a non-colour icon indicator with aria-hidden', () => {
    const { container } = render(<Badge variant="success">Done</Badge>)
    const icon = container.querySelector('[aria-hidden="true"]')
    expect(icon).toBeInTheDocument()
    expect(icon).toHaveTextContent('✓')
  })
})

// ---------------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------------
describe('Spinner', () => {
  it('has role status and aria-label', () => {
    render(<Spinner />)
    const spinner = screen.getByRole('status')
    expect(spinner).toHaveAttribute('aria-label', 'Loading')
  })

  it('accepts a custom label', () => {
    render(<Spinner label="Saving data" />)
    expect(screen.getByRole('status')).toHaveAttribute('aria-label', 'Saving data')
  })
})

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
describe('Modal', () => {
  it('renders with dialog role and aria-labelledby', () => {
    render(
      <Modal open={true} onClose={() => {}} title="Confirm">
        <p>Are you sure?</p>
      </Modal>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toBeInTheDocument()
    expect(dialog).toHaveAttribute('aria-labelledby', 'modal-title')
  })

  it('calls onClose when Escape is pressed', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <Modal open={true} onClose={onClose} title="Confirm">
        <p>Content</p>
      </Modal>,
    )
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('has a close button with aria-label', () => {
    render(
      <Modal open={true} onClose={() => {}} title="Info">
        <p>Details</p>
      </Modal>,
    )
    expect(screen.getByRole('button', { name: 'Close dialog' })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// DataTable
// ---------------------------------------------------------------------------
describe('DataTable', () => {
  type Row = { id: string; name: string; status: string }

  const columns: Column<Row>[] = [
    { key: 'name', header: 'Name', sortable: true },
    { key: 'status', header: 'Status' },
  ]

  const data: Row[] = [
    { id: '1', name: 'Alice', status: 'Active' },
    { id: '2', name: 'Bob', status: 'Inactive' },
  ]

  it('renders with grid role', () => {
    render(<DataTable columns={columns} data={data} keyField="id" />)
    expect(screen.getByRole('grid')).toBeInTheDocument()
  })

  it('renders sortable column headers with keyboard activation', async () => {
    const user = userEvent.setup()
    render(<DataTable columns={columns} data={data} keyField="id" />)
    const nameHeader = screen.getByText('Name').closest('th')!
    expect(nameHeader).toHaveAttribute('tabIndex', '0')
    nameHeader.focus()
    await user.keyboard('{Enter}')
    expect(nameHeader).toHaveAttribute('aria-sort', 'ascending')
  })

  it('sets aria-sort on sorted column', async () => {
    const user = userEvent.setup()
    render(<DataTable columns={columns} data={data} keyField="id" />)
    const nameHeader = screen.getByText('Name').closest('th')!
    await user.click(nameHeader)
    expect(nameHeader).toHaveAttribute('aria-sort', 'ascending')
    await user.click(nameHeader)
    expect(nameHeader).toHaveAttribute('aria-sort', 'descending')
  })

  it('renders caption for screen readers when provided', () => {
    render(
      <DataTable columns={columns} data={data} keyField="id" caption="Invoice list" />,
    )
    expect(screen.getByText('Invoice list')).toBeInTheDocument()
  })
})
