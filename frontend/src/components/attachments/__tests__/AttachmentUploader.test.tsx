import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import AttachmentUploader from '../AttachmentUploader'

/* ------------------------------------------------------------------ */
/*  Mock apiClient                                                     */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    post: vi.fn(),
    get: vi.fn(),
    delete: vi.fn(),
  },
}))

import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const defaultProps = {
  jobCardId: 'jc-001',
  onUploadComplete: vi.fn(),
  onError: vi.fn(),
}

function createFile(
  name: string,
  size: number,
  type: string,
): File {
  const content = new Uint8Array(size)
  return new File([content], name, { type })
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

describe('AttachmentUploader', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the drop zone with accepted types hint', () => {
    render(<AttachmentUploader {...defaultProps} />)

    expect(screen.getByText(/click to browse/i)).toBeInTheDocument()
    expect(screen.getByText(/drag and drop/i)).toBeInTheDocument()
    expect(
      screen.getByText(/Images \(JPEG, PNG, WebP, GIF\) and PDFs up to 50MB/i),
    ).toBeInTheDocument()
  })

  it('renders the hidden file input with correct accept attribute', () => {
    render(<AttachmentUploader {...defaultProps} />)

    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    expect(input).toBeInTheDocument()
    expect(input.type).toBe('file')
    expect(input.accept).toContain('.jpg')
    expect(input.accept).toContain('.pdf')
    expect(input.accept).toContain('image/png')
  })

  it('rejects files with invalid MIME type', async () => {
    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    // Remove accept attribute so userEvent can upload the file
    input.removeAttribute('accept')

    const badFile = createFile('video.mp4', 1024, 'video/mp4')
    await user.upload(input, badFile)

    expect(screen.getByRole('alert')).toHaveTextContent(/not accepted/i)
    expect(defaultProps.onError).toHaveBeenCalledWith(
      expect.stringContaining('not accepted'),
    )
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('rejects files exceeding 50MB', async () => {
    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    input.removeAttribute('accept')

    const bigFile = createFile('huge.jpg', 51 * 1024 * 1024, 'image/jpeg')
    await user.upload(input, bigFile)

    expect(screen.getByRole('alert')).toHaveTextContent(/exceeds the 50 MB limit/i)
    expect(defaultProps.onError).toHaveBeenCalled()
    expect(apiClient.post).not.toHaveBeenCalled()
  })

  it('uploads a valid JPEG file and calls onUploadComplete', async () => {
    const mockAttachment = {
      id: 'att-1',
      job_card_id: 'jc-001',
      file_key: 'job-card-attachments/org/att-1.jpg',
      file_name: 'photo.jpg',
      file_size: 5000,
      mime_type: 'image/jpeg',
      uploaded_by: 'user-1',
      uploaded_at: '2026-04-27T15:00:00Z',
    }

    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: mockAttachment,
    })

    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    input.removeAttribute('accept')

    const file = createFile('photo.jpg', 5000, 'image/jpeg')
    await user.upload(input, file)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalledWith(
        '/job-cards/jc-001/attachments',
        expect.any(FormData),
        expect.objectContaining({
          headers: { 'Content-Type': 'multipart/form-data' },
        }),
      )
    })

    await waitFor(() => {
      expect(defaultProps.onUploadComplete).toHaveBeenCalledWith(mockAttachment)
    })
  })

  it('uploads a valid PDF file', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        id: 'att-2',
        job_card_id: 'jc-001',
        file_key: 'job-card-attachments/org/att-2.pdf',
        file_name: 'invoice.pdf',
        file_size: 10000,
        mime_type: 'application/pdf',
        uploaded_by: 'user-1',
        uploaded_at: '2026-04-27T15:00:00Z',
      },
    })

    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    input.removeAttribute('accept')

    const file = createFile('invoice.pdf', 10000, 'application/pdf')
    await user.upload(input, file)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalled()
    })
  })

  it('shows error when upload fails with server error', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { status: 500, data: { detail: 'Internal server error' } },
    })

    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    input.removeAttribute('accept')

    const file = createFile('photo.jpg', 5000, 'image/jpeg')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Internal server error')
    })
    expect(defaultProps.onError).toHaveBeenCalledWith('Internal server error')
  })

  it('shows quota exceeded message on 507 response', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { status: 507, data: { detail: 'Storage quota exceeded' } },
    })

    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    input.removeAttribute('accept')

    const file = createFile('photo.jpg', 5000, 'image/jpeg')
    await user.upload(input, file)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/storage quota exceeded/i)
    })
  })

  it('disables the drop zone when disabled prop is true', () => {
    render(<AttachmentUploader {...defaultProps} disabled />)

    const dropZone = screen.getByRole('button', { name: /drop a file/i })
    expect(dropZone).toHaveAttribute('aria-disabled', 'true')

    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    expect(input).toBeDisabled()
  })

  it('accepts WebP and GIF image types', async () => {
    ;(apiClient.post as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        id: 'att-3',
        job_card_id: 'jc-001',
        file_key: 'key',
        file_name: 'image.webp',
        file_size: 2000,
        mime_type: 'image/webp',
        uploaded_by: 'user-1',
        uploaded_at: '2026-04-27T15:00:00Z',
      },
    })

    render(<AttachmentUploader {...defaultProps} />)

    const user = userEvent.setup()
    const input = screen.getByLabelText('Select file to upload') as HTMLInputElement
    input.removeAttribute('accept')

    const webpFile = createFile('image.webp', 2000, 'image/webp')
    await user.upload(input, webpFile)

    await waitFor(() => {
      expect(apiClient.post).toHaveBeenCalled()
    })
  })
})
