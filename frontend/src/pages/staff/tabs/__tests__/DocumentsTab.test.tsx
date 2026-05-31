/**
 * DocumentsTab — Staff Detail tabbed shell, task E5.
 *
 * Validates: Requirement R5 (Employment Agreement Upload Slot).
 *
 * Cases covered:
 *   1. Renders empty drop-zone when no agreement is attached.
 *   2. Renders filename + View + Replace once an agreement is on file.
 *   3. File picker triggers the two-step upload flow
 *      (POST /uploads/attachments → POST /staff/:id/employment-agreement)
 *      and refreshes the tab to the attached state.
 *   4. Files larger than 10 MB show a clear error and do not call the
 *      upload endpoint.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/api/client', () => {
  const mockGet = vi.fn()
  const mockPost = vi.fn()
  return {
    default: { get: mockGet, post: mockPost },
  }
})

import apiClient from '@/api/client'
import DocumentsTab from '../DocumentsTab'

const STAFF_ID = '11111111-2222-3333-4444-555555555555'
// hex form of the upload uuid, matching what the /uploads/attachments
// endpoint would emit at the tail of `attachments/{org}/{hex}{ext}`.
const UPLOAD_HEX = '0123456789abcdef0123456789abcdef'
const UPLOAD_UUID = '01234567-89ab-cdef-0123-456789abcdef'
const ORG_ID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

function emptyStaffResponse() {
  return {
    data: {
      id: STAFF_ID,
      employment_agreement_upload_id: null,
    },
  }
}

function attachedStaffResponse(uploadUuid = UPLOAD_UUID) {
  return {
    data: {
      id: STAFF_ID,
      employment_agreement_upload_id: uploadUuid,
    },
  }
}

function uploadResponse(name = 'agreement.pdf') {
  return {
    data: {
      file_key: `attachments/${ORG_ID}/${UPLOAD_HEX}.pdf`,
      file_name: name,
      file_size: 1234,
    },
  }
}

describe('DocumentsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the drop-zone when no agreement is attached', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      emptyStaffResponse(),
    )

    render(<DocumentsTab staffId={STAFF_ID} />)

    expect(await screen.findByTestId('dropzone')).toBeInTheDocument()
    expect(screen.queryByTestId('agreement-attached')).not.toBeInTheDocument()
    expect(
      screen.getByText(/Drag a PDF, JPG, or PNG here/i),
    ).toBeInTheDocument()
  })

  it('renders filename + View + Replace once an agreement is attached', async () => {
    ;(apiClient.get as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      attachedStaffResponse(),
    )

    render(<DocumentsTab staffId={STAFF_ID} />)

    expect(await screen.findByTestId('agreement-attached')).toBeInTheDocument()
    // No file_key yet (page just loaded), so only the upload_id renders +
    // the Replace button. The View button only appears once we have a
    // fresh file_key from a same-session upload.
    expect(screen.getByTestId('agreement-upload-id')).toHaveTextContent(
      UPLOAD_UUID,
    )
    expect(screen.queryByRole('button', { name: 'View' })).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Replace' }),
    ).toBeInTheDocument()
  })

  it('runs the two-step upload + attach flow when a file is picked', async () => {
    const get = apiClient.get as ReturnType<typeof vi.fn>
    const post = apiClient.post as ReturnType<typeof vi.fn>
    get.mockResolvedValueOnce(emptyStaffResponse())
    post
      .mockResolvedValueOnce(uploadResponse('signed-agreement.pdf'))
      .mockResolvedValueOnce(attachedStaffResponse())

    const user = userEvent.setup()
    render(<DocumentsTab staffId={STAFF_ID} />)

    await screen.findByTestId('dropzone')

    const fileInput = screen.getByTestId('file-input') as HTMLInputElement
    const file = new File(['%PDF-1.4 stub'], 'signed-agreement.pdf', {
      type: 'application/pdf',
    })
    await user.upload(fileInput, file)

    // Step 1: upload to /uploads/attachments with FormData
    await waitFor(() => {
      expect(post).toHaveBeenNthCalledWith(
        1,
        '/api/v2/uploads/attachments',
        expect.any(FormData),
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'multipart/form-data',
          }),
        }),
      )
    })

    // Step 2: attach to staff with the converted UUID
    await waitFor(() => {
      expect(post).toHaveBeenNthCalledWith(
        2,
        `/api/v2/staff/${STAFF_ID}/employment-agreement`,
        { upload_id: UPLOAD_UUID },
      )
    })

    // UI swaps to attached state with the fresh filename + View button
    expect(await screen.findByTestId('agreement-attached')).toBeInTheDocument()
    expect(screen.getByTestId('agreement-filename')).toHaveTextContent(
      'signed-agreement.pdf',
    )
    expect(screen.getByRole('button', { name: 'View' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Replace' })).toBeInTheDocument()
  })

  it('shows a too-large error and does not call the upload endpoint', async () => {
    const get = apiClient.get as ReturnType<typeof vi.fn>
    const post = apiClient.post as ReturnType<typeof vi.fn>
    get.mockResolvedValueOnce(emptyStaffResponse())

    const user = userEvent.setup()
    render(<DocumentsTab staffId={STAFF_ID} />)

    await screen.findByTestId('dropzone')

    // Build a 11 MB file (over the 10 MB cap).
    const oversize = new File(
      [new Uint8Array(11 * 1024 * 1024)],
      'huge.pdf',
      { type: 'application/pdf' },
    )
    const fileInput = screen.getByTestId('file-input') as HTMLInputElement
    await user.upload(fileInput, oversize)

    expect(
      await screen.findByText(/File too large\. Maximum size is 10 MB\./i),
    ).toBeInTheDocument()
    expect(post).not.toHaveBeenCalled()
  })
})
