import { describe, it, expect, vi, beforeAll } from 'vitest'
import { useState } from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MobileBodyEditor, stripFullDocumentChrome } from '../MobileBodyEditor'
import type { SenderPreview } from '../types'

/**
 * jsdom lacks the layout APIs ProseMirror calls while applying an edit
 * transaction (`elementFromPoint`, `getClientRects`, `getBoundingClientRect`).
 * Without them, typing into the real TipTap editor throws mid-transaction and
 * `onUpdate` never fires. Inert stubs let the Rich-mode edit path complete so we
 * can assert the `onChange` contract — the documented jsdom/TipTap limitation
 * noted in the spec (Task 6.4).
 */
beforeAll(() => {
  if (!document.elementFromPoint) {
    document.elementFromPoint = () => null
  }
  const emptyRectList = () =>
    Object.assign([], { item: () => null }) as unknown as DOMRectList
  if (!Element.prototype.getClientRects) {
    Element.prototype.getClientRects = emptyRectList as unknown as () => DOMRectList
  }
  if (!Range.prototype.getClientRects) {
    Range.prototype.getClientRects = emptyRectList as unknown as () => DOMRectList
  }
  if (!Range.prototype.getBoundingClientRect) {
    // @ts-expect-error jsdom stub
    Range.prototype.getBoundingClientRect = () => ({
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
    })
  }
})

/**
 * MobileBodyEditor dual-mode tests — email-preview-body-mismatch, Task 6.4.
 *
 * Mirrors the web `BodyEditor.dualmode.test.tsx` against the REAL TipTap
 * `MobileBodyEditor`:
 *
 *   - Property 6 — Rich↔HTML round-trip preserves the inner-body fragment.
 *   - HTML-mode paste of a FULL document degrades to its body fragment before
 *     reaching `onChange` (`stripFullDocumentChrome`, Requirement 2.1).
 *   - `body_was_edited` flips in BOTH modes (onChange diverges from the default).
 *   - Reset restores the fragment in the active mode.
 *   - Touch targets ≥44px + dark-mode classes on the new mode toggle.
 *
 * The editor is controlled by its parent, so a small stateful `Harness` mirrors
 * how `SendEmailSheet` drives it.
 */

const SENDER: SenderPreview = {
  from_name: 'Kerikeri Motors',
  from_email: 'billing@kerikerimotors.test',
  reply_to: null,
}

const FRAGMENT = '<p>Hi Jane,</p><p>Your invoice is ready.</p>'

/** Last argument passed to an onChange spy (avoids Array.prototype.at for lib compat). */
function lastEmitted(spy: ReturnType<typeof vi.fn>): string {
  const calls = spy.mock.calls
  return calls[calls.length - 1][0] as string
}

function Harness({
  initial = FRAGMENT,
  onChangeSpy,
}: {
  initial?: string
  onChangeSpy?: (html: string) => void
}) {
  const [html, setHtml] = useState(initial)
  return (
    <MobileBodyEditor
      valueHtml={html}
      defaultHtml={initial}
      onChange={(next) => {
        onChangeSpy?.(next)
        setHtml(next)
      }}
      onResetToDefault={() => setHtml(initial)}
      senderPreview={SENDER}
      locale="en"
    />
  )
}

async function waitForEditor() {
  await waitFor(() => {
    expect(document.querySelector('.tiptap.ProseMirror')).not.toBeNull()
  })
}

describe('MobileBodyEditor dual-mode — Rich↔HTML round-trip (Property 6)', () => {
  it('shows editor.getHTML() in HTML mode and preserves the fragment across toggles', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()

    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    expect(screen.getByLabelText('HTML source')).toHaveValue(FRAGMENT)

    await userEvent.click(screen.getByRole('button', { name: 'Rich text' }))
    await waitForEditor()
    expect((document.querySelector('.tiptap.ProseMirror') as HTMLElement).textContent).toContain(
      'Your invoice is ready.',
    )

    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    expect(screen.getByLabelText('HTML source')).toHaveValue(FRAGMENT)
  })

  it('the fragment never contains <title>/<head> chrome', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const value = (screen.getByLabelText('HTML source') as HTMLTextAreaElement).value
    expect(value).not.toMatch(/<!doctype|<head|<title|<html|<body/i)
  })
})

describe('MobileBodyEditor dual-mode — HTML paste degrades a full document (Requirement 2.1)', () => {
  it('stripFullDocumentChrome reduces a full document to its body fragment', () => {
    const fullDoc =
      '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">' +
      '<title>Invoice SPINV-0057 from SP Automotive</title></head>' +
      '<body><div><p>Hi Jane,</p><p>Your invoice is ready.</p></div></body></html>'
    const out = stripFullDocumentChrome(fullDoc)
    expect(out).not.toMatch(/<!doctype|<head|<title|<html|<body/i)
    expect(out).not.toContain('Invoice SPINV-0057 from SP Automotive')
    expect(out).toContain('Hi Jane,')
    expect(out).toContain('Your invoice is ready.')
  })

  it('passes a partial fragment through unchanged', () => {
    const fragment = '<table><tr><td>Styled button</td></tr></table>'
    expect(stripFullDocumentChrome(fragment)).toBe(fragment)
  })

  it('a full-document paste into the HTML textarea reaches onChange as a body fragment', async () => {
    const onChangeSpy = vi.fn()
    render(<Harness initial="<p></p>" onChangeSpy={onChangeSpy} />)
    await waitForEditor()
    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source')

    const fullDoc =
      '<!DOCTYPE html><html><head><title>LEAKED SUBJECT</title></head>' +
      '<body><div><p>Pasted body</p></div></body></html>'
    fireEvent.paste(textarea, {
      clipboardData: {
        getData: (type: string) => (type === 'text/html' ? fullDoc : ''),
      },
    })

    await waitFor(() => expect(onChangeSpy).toHaveBeenCalled())
    const emitted = lastEmitted(onChangeSpy)
    expect(emitted).not.toMatch(/<!doctype|<head|<title|<html|<body/i)
    expect(emitted).not.toContain('LEAKED SUBJECT')
    expect(emitted).toContain('Pasted body')
  })
})

describe('MobileBodyEditor dual-mode — body_was_edited flips in both modes', () => {
  it('HTML-mode editing emits a value that diverges from the default fragment', async () => {
    const onChangeSpy = vi.fn()
    render(<Harness initial={FRAGMENT} onChangeSpy={onChangeSpy} />)
    await waitForEditor()

    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source')
    await userEvent.clear(textarea)
    await userEvent.type(textarea, '<p>Edited in HTML mode</p>')

    await waitFor(() => expect(onChangeSpy).toHaveBeenCalled())
    const emitted = lastEmitted(onChangeSpy)
    expect(emitted).not.toBe(FRAGMENT)
    expect(emitted).toContain('Edited in HTML mode')
  })

  it('Rich-mode editing emits a value that diverges from the default fragment', async () => {
    const onChangeSpy = vi.fn()
    render(<Harness initial={FRAGMENT} onChangeSpy={onChangeSpy} />)
    await waitForEditor()

    const pm = document.querySelector('.tiptap.ProseMirror') as HTMLElement
    await userEvent.click(pm)
    await userEvent.type(pm, 'Z')

    await waitFor(() => {
      expect(onChangeSpy).toHaveBeenCalled()
      const emitted = lastEmitted(onChangeSpy)
      expect(emitted).not.toBe(FRAGMENT)
    })
  })
})

describe('MobileBodyEditor dual-mode — reset restores the fragment in the active mode', () => {
  it('reset restores the original fragment while in HTML mode', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()

    await userEvent.click(screen.getByRole('button', { name: 'HTML' }))
    const textarea = screen.getByLabelText('HTML source')
    await userEvent.clear(textarea)
    await userEvent.type(textarea, '<p>throwaway</p>')
    expect(textarea).toHaveValue('<p>throwaway</p>')

    await userEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByLabelText('HTML source')).toHaveValue(FRAGMENT)
  })
})

describe('MobileBodyEditor dual-mode — mobile affordances', () => {
  it('the mode toggle buttons meet the ≥44px touch target and carry dark-mode classes', async () => {
    render(<Harness initial={FRAGMENT} />)
    await waitForEditor()
    const htmlBtn = screen.getByRole('button', { name: 'HTML' })
    expect(htmlBtn.className).toContain('min-h-[44px]')
    expect(htmlBtn.className).toMatch(/dark:/)
  })
})
