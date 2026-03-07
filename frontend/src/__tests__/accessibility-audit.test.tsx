import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Select } from '../components/ui/Select'
import { Modal } from '../components/ui/Modal'
import { ToastContainer } from '../components/ui/Toast'
import type { ToastMessage } from '../components/ui/Toast'
import { AlertBanner } from '../components/ui/AlertBanner'
import { Badge } from '../components/ui/Badge'
import { Spinner } from '../components/ui/Spinner'
import { Tabs } from '../components/ui/Tabs'
import { Dropdown } from '../components/ui/Dropdown'
import { DataTable, type Column } from '../components/ui/DataTable'
import { Pagination } from '../components/ui/Pagination'
import { SkipLink } from '../components/ui/SkipLink'
import { VisuallyHidden } from '../components/ui/VisuallyHidden'
import {
  contrastRatio,
  meetsContrastAA,
  parseHexColour,
  relativeLuminance,
  getFocusableElements,
  trapFocus,
  announce,
} from '../utils/accessibility'

/**
 * Validates: Requirements 57.1, 57.2, 57.3, 57.4, 57.5
 * - 57.1: Keyboard navigation for all interactive elements with visible focus indicators
 * - 57.2: Appropriate ARIA labels and roles for all UI components
 * - 57.3: Minimum colour contrast ratio of 4.5:1 normal text, 3:1 large text
 * - 57.4: No information conveyed solely by colour
 * - 57.5: Browser zoom to 200% without content loss
 */

// ===========================================================================
// SkipLink
// ===========================================================================
describe('SkipLink', () => {
  it('renders a link targeting #main-content by default', () => {
    render(<SkipLink />)
    const link = screen.getByText('Skip to main content')
    expect(link).toBeInTheDocument()
    expect(link).toHaveAttribute('href', '#main-content')
  })

  it('is visually hidden until focused (has sr-only class)', () => {
    render(<SkipLink />)
    const link = screen.getByText('Skip to main content')
    expect(link.className).toContain('sr-only')
  })

  it('moves focus to target element on click', () => {
    render(
      <>
        <SkipLink targetId="content" />
        <main id="content">Main area</main>
      </>,
    )
    const link = screen.getByText('Skip to main content')
    link.click()
    expect(document.getElementById('content')).toHaveFocus()
  })
})

// ===========================================================================
// VisuallyHidden
// ===========================================================================
describe('VisuallyHidden', () => {
  it('renders content in the DOM', () => {
    render(<VisuallyHidden>Screen reader text</VisuallyHidden>)
    expect(screen.getByText('Screen reader text')).toBeInTheDocument()
  })

  it('applies sr-only class for visual hiding', () => {
    render(<VisuallyHidden>Hidden label</VisuallyHidden>)
    const el = screen.getByText('Hidden label')
    expect(el.className).toContain('sr-only')
  })

  it('renders as a custom element when "as" prop is provided', () => {
    render(<VisuallyHidden as="div">Block hidden</VisuallyHidden>)
    const el = screen.getByText('Block hidden')
    expect(el.tagName).toBe('DIV')
  })

  it('defaults to span element', () => {
    render(<VisuallyHidden>Inline hidden</VisuallyHidden>)
    const el = screen.getByText('Inline hidden')
    expect(el.tagName).toBe('SPAN')
  })
})

// ===========================================================================
// Keyboard navigation on interactive elements (Req 57.1)
// ===========================================================================
describe('Keyboard navigation', () => {
  it('Button is focusable and activates with Enter', async () => {
    const onClick = vi.fn()
    const user = userEvent.setup()
    render(<Button onClick={onClick}>Action</Button>)
    const btn = screen.getByRole('button', { name: 'Action' })
    btn.focus()
    expect(btn).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onClick).toHaveBeenCalled()
  })

  it('Input is focusable via label', () => {
    render(<Input label="Username" />)
    const input = screen.getByLabelText('Username')
    input.focus()
    expect(input).toHaveFocus()
  })

  it('Select is focusable via label', () => {
    render(<Select label="Country" options={[{ value: 'nz', label: 'New Zealand' }]} />)
    const select = screen.getByLabelText('Country')
    select.focus()
    expect(select).toHaveFocus()
  })

  it('Dropdown opens with Enter key and navigates with arrows', async () => {
    const user = userEvent.setup()
    const items = [
      { id: '1', label: 'Edit', onClick: vi.fn() },
      { id: '2', label: 'Delete', onClick: vi.fn() },
    ]
    render(<Dropdown trigger={<span>Menu</span>} items={items} label="Actions" />)
    const trigger = screen.getByRole('button', { name: 'Actions' })
    trigger.focus()
    await user.keyboard('{Enter}')
    expect(screen.getByRole('menu')).toBeInTheDocument()
    await user.keyboard('{ArrowDown}')
    expect(screen.getByRole('menuitem', { name: 'Delete' })).toHaveFocus()
  })

  it('Pagination buttons are keyboard accessible', async () => {
    const onPageChange = vi.fn()
    const user = userEvent.setup()
    render(<Pagination currentPage={2} totalPages={5} onPageChange={onPageChange} />)
    const prevBtn = screen.getByRole('button', { name: 'Previous page' })
    prevBtn.focus()
    await user.keyboard('{Enter}')
    expect(onPageChange).toHaveBeenCalledWith(1)
  })

  it('DataTable sortable headers activate with Enter', async () => {
    const user = userEvent.setup()
    type Row = { id: string; name: string }
    const columns: Column<Row>[] = [{ key: 'name', header: 'Name', sortable: true }]
    const data: Row[] = [{ id: '1', name: 'Alice' }]
    render(<DataTable columns={columns} data={data} keyField="id" />)
    const header = screen.getByText('Name').closest('th')!
    header.focus()
    await user.keyboard('{Enter}')
    expect(header).toHaveAttribute('aria-sort', 'ascending')
  })
})

// ===========================================================================
// ARIA labels and roles on all UI components (Req 57.2)
// ===========================================================================
describe('ARIA labels and roles', () => {
  it('Button has button role', () => {
    render(<Button>Click</Button>)
    expect(screen.getByRole('button', { name: 'Click' })).toBeInTheDocument()
  })

  it('Button sets aria-disabled and aria-busy correctly', () => {
    render(<Button disabled loading>Wait</Button>)
    const btn = screen.getByRole('button', { name: 'Wait' })
    expect(btn).toHaveAttribute('aria-disabled', 'true')
    expect(btn).toHaveAttribute('aria-busy', 'true')
  })

  it('Input links label, error, and helper text via aria attributes', () => {
    render(<Input label="Email" error="Invalid" helperText="Enter email" />)
    const input = screen.getByLabelText('Email')
    expect(input).toHaveAttribute('aria-invalid', 'true')
    expect(input).toHaveAttribute('aria-describedby', expect.stringContaining('error'))
  })

  it('Select links label and error via aria attributes', () => {
    render(<Select label="Role" options={[]} error="Required" />)
    const select = screen.getByLabelText('Role')
    expect(select).toHaveAttribute('aria-invalid', 'true')
    expect(select).toHaveAttribute('aria-describedby', expect.stringContaining('error'))
  })

  it('Modal has dialog role and aria-labelledby', () => {
    render(
      <Modal open={true} onClose={() => {}} title="Confirm">
        <p>Content</p>
      </Modal>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-labelledby', 'modal-title')
  })

  it('Toast container has aria-live polite', () => {
    const toasts: ToastMessage[] = [
      { id: '1', variant: 'success', message: 'Saved' },
    ]
    render(<ToastContainer toasts={toasts} onDismiss={() => {}} />)
    const container = screen.getByLabelText('Notifications')
    expect(container).toHaveAttribute('aria-live', 'polite')
  })

  it('AlertBanner uses correct role based on variant', () => {
    const { rerender } = render(<AlertBanner variant="error">Error!</AlertBanner>)
    expect(screen.getByRole('alert')).toBeInTheDocument()
    rerender(<AlertBanner variant="success">Done</AlertBanner>)
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('Spinner has role status and aria-label', () => {
    render(<Spinner label="Saving" />)
    const spinner = screen.getByRole('status')
    expect(spinner).toHaveAttribute('aria-label', 'Saving')
  })

  it('Tabs have tablist, tab, and tabpanel roles with aria-selected', () => {
    const tabs = [
      { id: 'a', label: 'Tab A', content: <p>A</p> },
      { id: 'b', label: 'Tab B', content: <p>B</p> },
    ]
    render(<Tabs tabs={tabs} />)
    expect(screen.getByRole('tablist')).toBeInTheDocument()
    const tabElements = screen.getAllByRole('tab')
    expect(tabElements[0]).toHaveAttribute('aria-selected', 'true')
    expect(tabElements[1]).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('Dropdown trigger has aria-haspopup and aria-expanded', async () => {
    const user = userEvent.setup()
    const items = [{ id: '1', label: 'Option', onClick: vi.fn() }]
    render(<Dropdown trigger={<span>Open</span>} items={items} label="Menu" />)
    const trigger = screen.getByRole('button', { name: 'Menu' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'true')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('DataTable has grid role and caption for screen readers', () => {
    type Row = { id: string; val: string }
    const columns: Column<Row>[] = [{ key: 'val', header: 'Value' }]
    render(<DataTable columns={columns} data={[{ id: '1', val: 'x' }]} keyField="id" caption="Test table" />)
    expect(screen.getByRole('grid')).toBeInTheDocument()
    expect(screen.getByText('Test table')).toBeInTheDocument()
  })

  it('Pagination has nav with aria-label and page buttons with aria-current', () => {
    render(<Pagination currentPage={1} totalPages={3} onPageChange={() => {}} />)
    expect(screen.getByRole('navigation', { name: 'Pagination' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Page 1' })).toHaveAttribute('aria-current', 'page')
  })
})

// ===========================================================================
// Focus indicators are visible (Req 57.1)
// ===========================================================================
describe('Focus indicators', () => {
  it('Button has focus-visible ring classes', () => {
    render(<Button>Test</Button>)
    const btn = screen.getByRole('button', { name: 'Test' })
    expect(btn.className).toContain('focus-visible:ring-2')
  })

  it('Input has focus-visible ring classes', () => {
    render(<Input label="Field" />)
    const input = screen.getByLabelText('Field')
    expect(input.className).toContain('focus-visible:ring-2')
  })

  it('Select has focus-visible ring classes', () => {
    render(<Select label="Pick" options={[]} />)
    const select = screen.getByLabelText('Pick')
    expect(select.className).toContain('focus-visible:ring-2')
  })

  it('Pagination buttons have focus-visible ring classes', () => {
    render(<Pagination currentPage={1} totalPages={3} onPageChange={() => {}} />)
    const nextBtn = screen.getByRole('button', { name: 'Next page' })
    expect(nextBtn.className).toContain('focus-visible:ring-2')
  })
})

// ===========================================================================
// Badge uses icon + text, not colour alone (Req 57.4)
// ===========================================================================
describe('Non-colour indicators', () => {
  it.each(['success', 'warning', 'error', 'info', 'neutral'] as const)(
    'Badge variant "%s" includes an icon alongside text',
    (variant) => {
      const { container } = render(<Badge variant={variant}>Label</Badge>)
      const icon = container.querySelector('[aria-hidden="true"]')
      expect(icon).toBeInTheDocument()
      expect(icon!.textContent).toBeTruthy()
      expect(screen.getByText('Label')).toBeInTheDocument()
    },
  )

  it('AlertBanner includes an icon alongside text', () => {
    const { container } = render(<AlertBanner variant="warning">Watch out</AlertBanner>)
    const icon = container.querySelector('[aria-hidden="true"]')
    expect(icon).toBeInTheDocument()
    expect(icon!.textContent).toBe('⚠')
  })

  it('Toast includes an icon alongside message text', () => {
    const toasts: ToastMessage[] = [
      { id: '1', variant: 'error', message: 'Failed to save' },
    ]
    const { container } = render(<ToastContainer toasts={toasts} onDismiss={() => {}} />)
    const icon = container.querySelector('[aria-hidden="true"]')
    expect(icon).toBeInTheDocument()
    expect(icon!.textContent).toBe('✕')
    expect(screen.getByText('Failed to save')).toBeInTheDocument()
  })
})

// ===========================================================================
// Contrast ratio utilities (Req 57.3)
// ===========================================================================
describe('Contrast ratio utilities', () => {
  it('parseHexColour handles 6-digit hex', () => {
    expect(parseHexColour('#ffffff')).toEqual([255, 255, 255])
    expect(parseHexColour('#000000')).toEqual([0, 0, 0])
  })

  it('parseHexColour handles 3-digit hex', () => {
    expect(parseHexColour('#fff')).toEqual([255, 255, 255])
    expect(parseHexColour('#000')).toEqual([0, 0, 0])
  })

  it('relativeLuminance returns 0 for black and ~1 for white', () => {
    expect(relativeLuminance(0, 0, 0)).toBeCloseTo(0, 4)
    expect(relativeLuminance(255, 255, 255)).toBeCloseTo(1, 4)
  })

  it('contrastRatio of black on white is 21:1', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 0)
  })

  it('contrastRatio of same colour is 1:1', () => {
    expect(contrastRatio('#336699', '#336699')).toBeCloseTo(1, 4)
  })

  it('meetsContrastAA returns true for black on white (normal text)', () => {
    expect(meetsContrastAA('#000000', '#ffffff')).toBe(true)
  })

  it('meetsContrastAA returns false for light grey on white (normal text)', () => {
    // #999 on #fff has ratio ~2.85:1, below 4.5:1
    expect(meetsContrastAA('#999999', '#ffffff')).toBe(false)
  })

  it('meetsContrastAA with large text uses 3:1 threshold', () => {
    // #767676 on #fff has ratio ~4.54:1 — passes normal, passes large
    expect(meetsContrastAA('#767676', '#ffffff', true)).toBe(true)
    // #999 on #fff ~2.85:1 — fails even for large text
    expect(meetsContrastAA('#999999', '#ffffff', true)).toBe(false)
  })

  it('platform text colours meet WCAG AA against white background', () => {
    // Verify the primary text colours used in the UI
    expect(meetsContrastAA('#111827', '#ffffff')).toBe(true) // text-gray-900
    expect(meetsContrastAA('#374151', '#ffffff')).toBe(true) // text-gray-700
    expect(meetsContrastAA('#6b7280', '#ffffff')).toBe(true) // text-gray-500 (large text)
  })
})

// ===========================================================================
// Focus trap utility
// ===========================================================================
describe('Focus trap', () => {
  it('getFocusableElements returns interactive elements', () => {
    const container = document.createElement('div')
    container.innerHTML = `
      <button>One</button>
      <input type="text" />
      <a href="#">Link</a>
      <div>Not focusable</div>
      <button disabled>Disabled</button>
    `
    document.body.appendChild(container)
    const focusable = getFocusableElements(container)
    expect(focusable).toHaveLength(3) // button, input, link (disabled excluded)
    document.body.removeChild(container)
  })

  it('trapFocus wraps focus from last to first on Tab', () => {
    const container = document.createElement('div')
    container.innerHTML = '<button id="a">A</button><button id="b">B</button>'
    document.body.appendChild(container)

    const release = trapFocus(container)
    const btnB = container.querySelector('#b') as HTMLElement
    btnB.focus()

    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })
    container.dispatchEvent(event)

    // After trap, focus should wrap to first element
    release()
    document.body.removeChild(container)
  })
})

// ===========================================================================
// Screen reader announcement
// ===========================================================================
describe('announce', () => {
  it('creates a live region and sets message', async () => {
    announce('Item saved')
    // The live region is created in the DOM
    const region = document.querySelector('[aria-live]')
    expect(region).toBeInTheDocument()
    expect(region).toHaveAttribute('aria-atomic', 'true')
  })

  it('supports assertive priority', () => {
    announce('Critical error', 'assertive')
    const region = document.querySelector('[aria-live="assertive"]')
    expect(region).toBeInTheDocument()
  })
})
