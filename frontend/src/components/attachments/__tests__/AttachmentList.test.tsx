import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import AttachmentList from '../AttachmentList'
import type { Attachment } from '../AttachmentUploader'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function makeAttachment(overrides: Partial<Attachment> = {}): Attachment {
  return {
    id: 'att-1',
    job_card_id: 'jc-001',
    file_key: 'job-card-attachments/org/att-1.jpg',
    file_name: 'photo.jpg',
    file_size: 5120,
    mime_type: 'image/jpeg',
    uploaded_by: 'user-1',
    uploaded_at: '2026-04-27T15:00:00Z',
    ...overrides,
  }
}

const imageAttachment = makeAttachment()

const pdfAttachment = makeAttachment({
  id: 'att-2',
  file_key: 'job-card-attachments/org/att-2.pdf',
  file_name: 'invoice.pdf',
  file_size: 2_500_000,
  mime_type: 'application/pdf',
})

const largeAttachment = makeAttachment({
  id: 'att-3',
  file_name: 'big-image.png',
  file_size: 10_485_760, // 10 MB
  mime_type: 'image/png',
})

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('AttachmentList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders nothing when attachments array is empty', () => {
    const { container } = render(
      <AttachmentList attachments={[]} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when attachments is undefined (safe fallback)', () => {
    const { container } = render(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      <AttachmentList attachments={undefined as any} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('displays filename and human-readable file size for each attachment', () => {
    render(
      <AttachmentList attachments={[imageAttachment, pdfAttachment]} />,
    )

    expect(screen.getByText('photo.jpg')).toBeInTheDocument()
    expect(screen.getByText('5.0 KB')).toBeInTheDocument()

    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText('2.4 MB')).toBeInTheDocument()
  })

  it('renders an image thumbnail for image attachments', () => {
    render(<AttachmentList attachments={[imageAttachment]} />)

    const img = screen.getByAltText('photo.jpg')
    expect(img).toBeInTheDocument()
    expect(img.tagName).toBe('IMG')
    expect(img).toHaveAttribute(
      'src',
      '/api/v1/job-cards/jc-001/attachments/att-1',
    )
  })

  it('renders a PDF icon (not an img) for PDF attachments', () => {
    render(<AttachmentList attachments={[pdfAttachment]} />)

    // No <img> should be rendered for a PDF
    expect(screen.queryByRole('img')).toBeNull()
    // The filename should still be visible
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
  })

  it('opens attachment in a new tab when clicked', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    const user = userEvent.setup()

    render(<AttachmentList attachments={[imageAttachment]} />)

    const viewButton = screen.getByRole('button', { name: /view photo\.jpg/i })
    await user.click(viewButton)

    expect(windowOpen).toHaveBeenCalledWith(
      '/api/v1/job-cards/jc-001/attachments/att-1',
      '_blank',
      'noopener,noreferrer',
    )

    windowOpen.mockRestore()
  })

  it('opens PDF in a new tab when clicked', async () => {
    const windowOpen = vi.spyOn(window, 'open').mockImplementation(() => null)
    const user = userEvent.setup()

    render(<AttachmentList attachments={[pdfAttachment]} />)

    const viewButton = screen.getByRole('button', { name: /view invoice\.pdf/i })
    await user.click(viewButton)

    expect(windowOpen).toHaveBeenCalledWith(
      '/api/v1/job-cards/jc-001/attachments/att-2',
      '_blank',
      'noopener,noreferrer',
    )

    windowOpen.mockRestore()
  })

  it('shows delete button when not readOnly and onDelete is provided', () => {
    const onDelete = vi.fn()

    render(
      <AttachmentList
        attachments={[imageAttachment]}
        onDelete={onDelete}
        readOnly={false}
      />,
    )

    expect(
      screen.getByRole('button', { name: /delete photo\.jpg/i }),
    ).toBeInTheDocument()
  })

  it('hides delete button when readOnly is true', () => {
    const onDelete = vi.fn()

    render(
      <AttachmentList
        attachments={[imageAttachment]}
        onDelete={onDelete}
        readOnly
      />,
    )

    expect(
      screen.queryByRole('button', { name: /delete/i }),
    ).not.toBeInTheDocument()
  })

  it('hides delete button when onDelete is not provided', () => {
    render(
      <AttachmentList attachments={[imageAttachment]} />,
    )

    expect(
      screen.queryByRole('button', { name: /delete/i }),
    ).not.toBeInTheDocument()
  })

  it('calls onDelete with the attachment id when delete is clicked', async () => {
    const onDelete = vi.fn()
    const user = userEvent.setup()

    render(
      <AttachmentList
        attachments={[imageAttachment]}
        onDelete={onDelete}
      />,
    )

    const deleteBtn = screen.getByRole('button', { name: /delete photo\.jpg/i })
    await user.click(deleteBtn)

    expect(onDelete).toHaveBeenCalledTimes(1)
    expect(onDelete).toHaveBeenCalledWith('att-1')
  })

  it('formats file sizes correctly (B, KB, MB)', () => {
    const tinyAttachment = makeAttachment({
      id: 'att-tiny',
      file_name: 'tiny.jpg',
      file_size: 512,
    })

    render(
      <AttachmentList
        attachments={[tinyAttachment, imageAttachment, largeAttachment]}
      />,
    )

    expect(screen.getByText('512 B')).toBeInTheDocument()
    expect(screen.getByText('5.0 KB')).toBeInTheDocument()
    expect(screen.getByText('10.0 MB')).toBeInTheDocument()
  })

  it('renders a list with the correct number of items', () => {
    render(
      <AttachmentList
        attachments={[imageAttachment, pdfAttachment, largeAttachment]}
      />,
    )

    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(3)
  })
})
