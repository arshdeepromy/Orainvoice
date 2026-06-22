/**
 * Public self-service onboarding form (staff-onboarding-link feature).
 *
 * Route: ``/onboard/:token`` (no auth — sits OUTSIDE RequireAuth/GuestOnly,
 * exactly like ``/public/staff-roster/:token``).
 *
 * API (all token-gated, no auth):
 *   - GET  /api/v2/public/staff-onboarding/{token}        → prefill + resume draft
 *   - POST /api/v2/public/staff-onboarding/{token}        → multipart submit
 *   - PUT  /api/v2/public/staff-onboarding/{token}/draft  → save/autosave draft
 *
 * TRANSPORT — raw ``axios``, never the shared ``apiClient`` (R11.1, R11.4).
 * The shared ``apiClient`` has a 401 response interceptor that redirects to
 * ``/login`` plus a ``/api/v1`` baseURL and auth / branch / CSRF header
 * injection — all wrong for a logged-out public visitor. We mirror
 * ``StaffRosterPublicView`` and use raw ``axios`` for every call here.
 *
 * The staff member opens the emailed link without logging in and fills a
 * sectioned form (Personal, Bank, IRD & Tax, Residency, Documents). On a
 * 200 submit we swap to a thank-you confirmation (R9.5). Progress can be
 * saved as a draft (explicit button + debounced autosave-on-blur) and
 * resumed from any device (R12).
 *
 * **Validates: Requirements 4.1, 4.2, 4.3, 5.1, 6.1, 6.4, 7.1, 7.4, 8.1,
 * 8.2, 8.3, 9.2, 9.5, 11.3, 11.4, 12.1, 12.2, 12.3, 12.5**
 */

import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import {
  STAFF_DOC_TYPES,
  docTypeConfig,
  detailOptionLabel,
} from '@/utils/staffDocumentTypes'

// ---------------------------------------------------------------------------
// Wire types — mirror app/modules/staff/schemas.py.
// ---------------------------------------------------------------------------

interface OnboardingDraftFields {
  last_name: string | null
  phone: string | null
  emergency_contact_name: string | null
  emergency_contact_phone: string | null
  tax_code: string | null
  student_loan: boolean | null
  kiwisaver_enrolled: boolean | null
  kiwisaver_employee_rate: number | string | null
  residency_type: string | null
  visa_expiry_date: string | null
  ird_number: string | null // masked on the wire
  has_ird: boolean
  bank_account_number: string | null // masked on the wire
  has_bank: boolean
  documents_staged_count: number
}

interface PrefillResponse {
  first_name: string
  email: string
  org_name: string
  tax_code_options: string[]
  residency_options: string[]
  kiwisaver_rate_options: number[]
  bank_account_required: boolean
  draft: OnboardingDraftFields | null
  completion_percentage: number | null
  last_saved_at: string | null
}

interface SubmitErrorBody {
  ok: false
  message?: string
  errors?: Record<string, { message: string; code: string }>
}

interface DraftResponse {
  ok: boolean
  completion_percentage: number
  last_saved_at: string
}

type ErrorKind =
  | 'not_found'
  | 'expired'
  | 'revoked'
  | 'consumed'
  | 'staff_inactive'
  | 'unknown'

interface PageErrorState {
  kind: ErrorKind
  title: string
  message: string
}

// ---------------------------------------------------------------------------
// Local form state.
// ---------------------------------------------------------------------------

interface FormState {
  last_name: string
  phone: string
  emergency_contact_name: string
  emergency_contact_phone: string
  bank_account_number: string
  ird_number: string
  tax_code: string
  student_loan: boolean
  kiwisaver_enrolled: boolean
  kiwisaver_employee_rate: string
  residency_type: string
  visa_expiry_date: string
}

const EMPTY_FORM: FormState = {
  last_name: '',
  phone: '',
  emergency_contact_name: '',
  emergency_contact_phone: '',
  bank_account_number: '',
  ird_number: '',
  tax_code: '',
  student_loan: false,
  kiwisaver_enrolled: false,
  kiwisaver_employee_rate: '',
  residency_type: '',
  visa_expiry_date: '',
}

// Residency types that require a visa-expiry date (R8.2).
const VISA_RESIDENCY_TYPES = ['work_visa', 'student_visa']

const RESIDENCY_LABELS: Record<string, string> = {
  citizen: 'NZ Citizen',
  permanent_resident: 'Permanent Resident',
  work_visa: 'Work Visa',
  student_visa: 'Student Visa',
  other: 'Other',
}

// Document picker constraints (R7.2, R7.3).
const ACCEPTED_DOC_TYPES = 'application/pdf,image/jpeg,image/png'
const ACCEPTED_DOC_MIMES = ['application/pdf', 'image/jpeg', 'image/png']
const MAX_DOC_COUNT = 3

// Profile photo picker constraints (image only).
const ACCEPTED_PHOTO_TYPES = 'image/jpeg,image/png,image/webp'
const ACCEPTED_PHOTO_MIMES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_PHOTO_BYTES = 10 * 1024 * 1024 // 10 MB
const MAX_DOC_BYTES = 10 * 1024 * 1024 // 10 MB

const AUTOSAVE_DEBOUNCE_MS = 800

// ---------------------------------------------------------------------------
// Masked-secret heuristic — replicated from OverviewTab.tsx so a field left
// showing the masked placeholder is NOT re-sent unless the staff retypes it
// (R12.3).
// ---------------------------------------------------------------------------

export const MASKED_IRD_RE = /^\*+\d{0,3}$/
export const MASKED_BANK_RE = /^\*+\d{0,4}$/

// A masked display value always contains asterisks; a real, freshly-typed
// value never does. Treating "contains an asterisk" as masked is robust to the
// exact mask layout the backend emits (e.g. `**-****-****NN-**` for bank,
// `***NNN` for IRD — see app/modules/staff/security.py) and avoids regex drift.
export function isMaskedIrd(v: string | null | undefined): boolean {
  return !!v && v.includes('*')
}
export function isMaskedBank(v: string | null | undefined): boolean {
  return !!v && v.includes('*')
}

// ---------------------------------------------------------------------------
// Client-side validators — mirror the server (NZ bank, IRD length, emergency
// contact both-or-neither). The server is authoritative; these are for fast
// feedback on SUBMIT only and are intentionally NOT applied to draft saves
// (R12.5).
// ---------------------------------------------------------------------------

export const NZ_BANK_RE = /^\d{2}-\d{4}-\d{7}-\d{2,3}$/

export function validateNzBankAccount(s: string): boolean {
  return NZ_BANK_RE.test(s.trim())
}

export function validateIrdLength(s: string): boolean {
  const digits = s.replace(/\D/g, '')
  return digits.length === 8 || digits.length === 9
}

// ---------------------------------------------------------------------------
// Live input formatters — insert the conventional NZ dashes as the user types.
// Both are no-ops on a masked placeholder (contains '*') so a resumed masked
// value is left untouched and the masked heuristic still suppresses re-sending.
// ---------------------------------------------------------------------------

/**
 * Format an NZ bank account number as ``BB-bbbb-aaaaaaa-ss`` while typing:
 * bank (2) - branch (4) - account (7) - suffix (2–3). Non-digits are stripped
 * and the value is capped at 16 digits (2+4+7+3).
 */
export function formatNzBankAccount(value: string): string {
  if (value.includes('*')) return value // masked placeholder — leave as-is
  const digits = value.replace(/\D/g, '').slice(0, 16)
  const sizes = [2, 4, 7, 3]
  const parts: string[] = []
  let i = 0
  for (const size of sizes) {
    if (i >= digits.length) break
    parts.push(digits.slice(i, i + size))
    i += size
  }
  return parts.join('-')
}

/**
 * Format an NZ IRD number while typing. IRD numbers are 8 or 9 digits and are
 * conventionally shown grouped in threes from the right (``XX-XXX-XXX`` for 8,
 * ``XXX-XXX-XXX`` for 9). Non-digits are stripped and capped at 9 digits.
 */
export function formatIrdNumber(value: string): string {
  if (value.includes('*')) return value // masked placeholder — leave as-is
  const digits = value.replace(/\D/g, '').slice(0, 9)
  if (digits.length <= 3) return digits
  const parts: string[] = []
  let rest = digits
  while (rest.length > 3) {
    parts.unshift(rest.slice(-3))
    rest = rest.slice(0, -3)
  }
  parts.unshift(rest)
  return parts.join('-')
}

export function validateEmergencyContact(name: string, phone: string): boolean {
  const hasName = name.trim().length > 0
  const hasPhone = phone.trim().length > 0
  return hasName === hasPhone
}

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('en-NZ', {
      hour: 'numeric',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

/**
 * Map a prefill/submit token-state error to a distinct, friendly page error
 * (R11.4). Mirrors StaffRosterPublicView: guard with axios.isAxiosError,
 * read err.response?.status and the humanized {message, code} detail.
 */
function mapPrefillError(err: unknown): PageErrorState {
  const status = axios.isAxiosError(err) ? err.response?.status : undefined
  const detail = axios.isAxiosError(err)
    ? (err.response?.data as { detail?: { message?: string; code?: string } } | undefined)
        ?.detail
    : undefined
  const code = detail?.code
  const serverMessage = detail?.message

  if (status === 404 || code === 'onboarding_token_not_found') {
    return {
      kind: 'not_found',
      title: 'Onboarding link not valid',
      message:
        serverMessage ??
        'This onboarding link is not valid. Please check the link in your email, or contact your employer for a new one.',
    }
  }
  if (code === 'onboarding_token_expired') {
    return {
      kind: 'expired',
      title: 'Onboarding link expired',
      message:
        serverMessage ??
        'This onboarding link has expired. Please contact your employer to have a new link sent to you.',
    }
  }
  if (code === 'onboarding_token_revoked') {
    return {
      kind: 'revoked',
      title: 'Onboarding link cancelled',
      message:
        serverMessage ??
        'This onboarding link has been cancelled. Please contact your employer for a new link.',
    }
  }
  if (code === 'onboarding_token_consumed') {
    return {
      kind: 'consumed',
      title: 'Onboarding already submitted',
      message:
        serverMessage ??
        'This onboarding form has already been submitted. There is nothing more to do — contact your employer if you need to make changes.',
    }
  }
  if (code === 'onboarding_token_staff_inactive') {
    return {
      kind: 'staff_inactive',
      title: 'Onboarding link no longer active',
      message:
        serverMessage ??
        'This onboarding link is no longer active. Please contact your employer for assistance.',
    }
  }
  if (status === 410) {
    return {
      kind: 'expired',
      title: 'Onboarding link unavailable',
      message:
        serverMessage ??
        'This onboarding link is no longer available. Please contact your employer for a new one.',
    }
  }
  if (status === 429) {
    return {
      kind: 'unknown',
      title: 'Too many requests',
      message: 'Please wait a moment and refresh the page to try again.',
    }
  }
  return {
    kind: 'unknown',
    title: 'Could not load onboarding form',
    message:
      'Something went wrong loading your onboarding form. Please try again later.',
  }
}

function rateToOption(
  rate: number | string | null | undefined,
): string {
  if (rate === null || rate === undefined || rate === '') return ''
  const n = Number(rate)
  if (Number.isNaN(n)) return ''
  return String(Math.round(n))
}

function draftToForm(draft: OnboardingDraftFields): FormState {
  return {
    last_name: draft.last_name ?? '',
    phone: draft.phone ?? '',
    emergency_contact_name: draft.emergency_contact_name ?? '',
    emergency_contact_phone: draft.emergency_contact_phone ?? '',
    // Sensitive fields rehydrate as the MASKED placeholder; the masked
    // heuristic keeps them out of the next save/submit unless retyped.
    bank_account_number: draft.bank_account_number ?? '',
    ird_number: draft.ird_number ?? '',
    tax_code: draft.tax_code ?? '',
    student_loan: !!draft.student_loan,
    kiwisaver_enrolled: !!draft.kiwisaver_enrolled,
    kiwisaver_employee_rate: rateToOption(draft.kiwisaver_employee_rate),
    residency_type: draft.residency_type ?? '',
    visa_expiry_date: draft.visa_expiry_date ?? '',
  }
}

export default function OnboardingFormPage() {
  const { token } = useParams<{ token: string }>()

  const [loading, setLoading] = useState(true)
  const [pageError, setPageError] = useState<PageErrorState | null>(null)
  const [prefill, setPrefill] = useState<PrefillResponse | null>(null)

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [files, setFiles] = useState<File[]>([])
  // Per-file document metadata, aligned with `files` by index.
  const [docMeta, setDocMeta] = useState<
    { type: string; detailSelect: string; detailText: string }[]
  >([])
  // Optional profile photo + its object-URL preview.
  const [photo, setPhoto] = useState<File | null>(null)
  const [photoPreview, setPhotoPreview] = useState<string | null>(null)
  const [photoError, setPhotoError] = useState<string | null>(null)
  // Number of docs staged in a previous session that must be re-attached
  // before submit (R12.3 — files themselves are not stored in the draft).
  const [resumedDocCount, setResumedDocCount] = useState(0)

  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [docError, setDocError] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [confirmationMessage, setConfirmationMessage] = useState<string>('')

  // Draft state.
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const [completionPct, setCompletionPct] = useState<number | null>(null)
  const [savingDraft, setSavingDraft] = useState(false)
  const [draftNote, setDraftNote] = useState<string | null>(null)

  // The masked placeholders we received on resume — used by the masked
  // heuristic to decide whether to re-send IRD / bank.
  const irdOriginalRef = useRef<string>('')
  const bankOriginalRef = useRef<string>('')

  // Debounce timer + always-fresh refs for the autosave-on-unmount flush.
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const formRef = useRef<FormState>(form)
  formRef.current = form
  const filesRef = useRef<File[]>(files)
  filesRef.current = files
  const photoPreviewRef = useRef<string | null>(null)
  photoPreviewRef.current = photoPreview
  const submittedRef = useRef(false)
  submittedRef.current = submitted

  // ------------------------------------------------------------------
  // Mount-time prefill + resume (R4.2, R11.4, R12.3).
  // ------------------------------------------------------------------
  useEffect(() => {
    const controller = new AbortController()

    const fetchPrefill = async () => {
      if (!token) {
        setPageError({
          kind: 'not_found',
          title: 'Onboarding unavailable',
          message: 'This onboarding link is not valid.',
        })
        setLoading(false)
        return
      }

      setLoading(true)
      setPageError(null)
      try {
        const res = await axios.get<PrefillResponse>(
          `/api/v2/public/staff-onboarding/${token}`,
          { signal: controller.signal },
        )
        if (controller.signal.aborted) return
        const data = res.data ?? null
        setPrefill(data)
        if (data?.draft) {
          setForm(draftToForm(data.draft))
          irdOriginalRef.current = data.draft.ird_number ?? ''
          bankOriginalRef.current = data.draft.bank_account_number ?? ''
          setResumedDocCount(data.draft.documents_staged_count ?? 0)
        }
        setCompletionPct(data?.completion_percentage ?? null)
        setSavedAt(data?.last_saved_at ?? null)
      } catch (err) {
        if (controller.signal.aborted) return
        setPageError(mapPrefillError(err))
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    void fetchPrefill()
    return () => controller.abort()
  }, [token])

  // Flush any pending autosave on unmount (R12.2 — latest pending save).
  useEffect(() => {
    return () => {
      if (autosaveTimer.current) {
        clearTimeout(autosaveTimer.current)
        autosaveTimer.current = null
        if (!submittedRef.current) {
          void saveDraft(formRef.current, filesRef.current, { silent: true })
        }
      }
      // Release any object-URL for the photo preview to avoid a leak.
      if (photoPreviewRef.current) {
        URL.revokeObjectURL(photoPreviewRef.current)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const showVisaExpiry = VISA_RESIDENCY_TYPES.includes(form.residency_type)

  // ------------------------------------------------------------------
  // Field updates.
  // ------------------------------------------------------------------
  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
    // Clear the inline error for this field as soon as the user edits it,
    // but keep the rest of the entered data intact (R9.2).
    setFieldErrors((prev) => {
      if (!(key in prev)) return prev
      const next = { ...prev }
      delete next[key as string]
      return next
    })
  }

  // ------------------------------------------------------------------
  // Draft payload — applies the masked heuristic for IRD/bank (R12.3).
  // ------------------------------------------------------------------
  function buildDraftPayload(
    f: FormState,
    stagedFiles: File[],
  ): Record<string, unknown> {
    const payload: Record<string, unknown> = {
      last_name: f.last_name.trim() || null,
      phone: f.phone.trim() || null,
      emergency_contact_name: f.emergency_contact_name.trim() || null,
      emergency_contact_phone: f.emergency_contact_phone.trim() || null,
      tax_code: f.tax_code || null,
      student_loan: f.student_loan,
      kiwisaver_enrolled: f.kiwisaver_enrolled,
      kiwisaver_employee_rate: f.kiwisaver_enrolled
        ? f.kiwisaver_employee_rate || null
        : null,
      residency_type: f.residency_type || null,
      visa_expiry_date: showVisaExpiry ? f.visa_expiry_date || null : null,
      documents_staged_count: stagedFiles.length || resumedDocCount,
    }

    // IRD: only send a freshly typed value. A value left as the masked
    // placeholder we received on resume is NOT re-sent (R12.3).
    const ird = f.ird_number.trim()
    if (ird && !(ird === irdOriginalRef.current && isMaskedIrd(ird)) && !isMaskedIrd(ird)) {
      payload.ird_number = ird
    }
    const bank = f.bank_account_number.trim()
    if (
      bank &&
      !(bank === bankOriginalRef.current && isMaskedBank(bank)) &&
      !isMaskedBank(bank)
    ) {
      payload.bank_account_number = bank
    }
    return payload
  }

  // ------------------------------------------------------------------
  // Save draft — explicit button + debounced autosave. Raw axios PUT,
  // NOT subject to submit-time validation (R12.1, R12.2, R12.5). Errors
  // surface quietly and never block typing.
  // ------------------------------------------------------------------
  async function saveDraft(
    f: FormState,
    stagedFiles: File[],
    opts: { silent?: boolean } = {},
  ): Promise<void> {
    if (!token || submittedRef.current) return
    if (!opts.silent) setSavingDraft(true)
    setDraftNote(null)
    try {
      const res = await axios.put<DraftResponse>(
        `/api/v2/public/staff-onboarding/${token}/draft`,
        buildDraftPayload(f, stagedFiles),
      )
      const data = res.data
      if (data?.last_saved_at) setSavedAt(data.last_saved_at)
      if (typeof data?.completion_percentage === 'number') {
        setCompletionPct(data.completion_percentage)
      }
    } catch (err) {
      // Draft-save errors surface the server message quietly (non-blocking).
      const msg =
        (axios.isAxiosError(err) &&
          (err.response?.data as { detail?: { message?: string } } | undefined)
            ?.detail?.message) ||
        'Could not save your progress just now. Your details are still here — we will retry as you continue.'
      setDraftNote(msg)
    } finally {
      if (!opts.silent) setSavingDraft(false)
    }
  }

  function scheduleAutosave() {
    if (!token || submittedRef.current) return
    if (autosaveTimer.current) clearTimeout(autosaveTimer.current)
    autosaveTimer.current = setTimeout(() => {
      autosaveTimer.current = null
      void saveDraft(formRef.current, filesRef.current, { silent: true })
    }, AUTOSAVE_DEBOUNCE_MS)
  }

  function handleSaveDraftClick() {
    if (autosaveTimer.current) {
      clearTimeout(autosaveTimer.current)
      autosaveTimer.current = null
    }
    void saveDraft(form, files)
  }

  // ------------------------------------------------------------------
  // Document picker (R7.4).
  // ------------------------------------------------------------------
  function handleAddFiles(selected: FileList | null) {
    if (!selected || selected.length === 0) return
    setDocError(null)
    const incoming = Array.from(selected)
    const accepted: File[] = []
    for (const file of incoming) {
      if (!ACCEPTED_DOC_MIMES.includes(file.type)) {
        setDocError(
          `"${file.name}" is not a supported file type. Please upload PDF, JPEG or PNG files only.`,
        )
        continue
      }
      if (file.size > MAX_DOC_BYTES) {
        setDocError(`"${file.name}" is larger than 10 MB. Please upload a smaller file.`)
        continue
      }
      accepted.push(file)
    }
    setFiles((prev) => {
      const combined = [...prev, ...accepted]
      const capped = combined.length > MAX_DOC_COUNT
      if (capped) setDocError(`You can upload up to ${MAX_DOC_COUNT} documents.`)
      return capped ? combined.slice(0, MAX_DOC_COUNT) : combined
    })
    // Keep per-file metadata aligned: append a default entry per accepted file.
    setDocMeta((prev) => {
      const defaults = accepted.map(() => ({
        type: 'working_rights',
        detailSelect: '',
        detailText: '',
      }))
      const combined = [...prev, ...defaults]
      return combined.length > MAX_DOC_COUNT
        ? combined.slice(0, MAX_DOC_COUNT)
        : combined
    })
    // A freshly attached file clears the "re-attach previous" reminder.
    setResumedDocCount(0)
    scheduleAutosave()
  }

  /** Update one attached file's document metadata. */
  function updateDocMeta(
    index: number,
    patch: Partial<{ type: string; detailSelect: string; detailText: string }>,
  ) {
    setDocMeta((prev) =>
      prev.map((m, i) => (i === index ? { ...m, ...patch } : m)),
    )
  }

  function handleRemoveFile(index: number) {
    setFiles((prev) => prev.filter((_, i) => i !== index))
    setDocMeta((prev) => prev.filter((_, i) => i !== index))
    scheduleAutosave()
  }

  /** Resolve the human-readable detail string for one attached document. */
  function resolveDocDescription(meta: {
    type: string
    detailSelect: string
    detailText: string
  }): string {
    const cfg = docTypeConfig(meta.type)
    if (!cfg?.detail) return ''
    if (cfg.detail.options) {
      if (!meta.detailSelect) return ''
      if (meta.detailSelect === 'other') return meta.detailText.trim()
      return detailOptionLabel(meta.type, meta.detailSelect)
    }
    return meta.detailText.trim()
  }

  // ------------------------------------------------------------------
  // Profile photo picker (optional). Image only, ≤ 10 MB.
  // ------------------------------------------------------------------
  function handleSelectPhoto(selected: FileList | null) {
    const file = selected?.[0]
    if (!file) return
    setPhotoError(null)
    if (!ACCEPTED_PHOTO_MIMES.includes(file.type)) {
      setPhotoError('Please choose a JPEG, PNG or WebP image.')
      return
    }
    if (file.size > MAX_PHOTO_BYTES) {
      setPhotoError('That image is larger than 10 MB. Please choose a smaller one.')
      return
    }
    setPhoto(file)
    setPhotoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return URL.createObjectURL(file)
    })
  }

  function handleRemovePhoto() {
    setPhoto(null)
    setPhotoPreview((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return null
    })
    setPhotoError(null)
  }

  // ------------------------------------------------------------------
  // Client-side submit validation (mirror server; server authoritative).
  // ------------------------------------------------------------------
  function validateForSubmit(): Record<string, string> {
    const errs: Record<string, string> = {}

    if (
      !validateEmergencyContact(
        form.emergency_contact_name,
        form.emergency_contact_phone,
      )
    ) {
      const msg =
        'Please provide both an emergency contact name and phone, or leave both empty.'
      if (!form.emergency_contact_name.trim()) {
        errs.emergency_contact_name = msg
      }
      if (!form.emergency_contact_phone.trim()) {
        errs.emergency_contact_phone = msg
      }
    }

    // Bank: validate format when a fresh (non-masked) value is present, or
    // when the org requires it (R5.2, R5.4).
    const bank = form.bank_account_number.trim()
    const bankFresh = bank.length > 0 && !isMaskedBank(bank)
    if (bankFresh && !validateNzBankAccount(bank)) {
      errs.bank_account_number =
        'Enter a valid NZ bank account number (e.g. 01-0234-0567890-00).'
    } else if (prefill?.bank_account_required && !bank) {
      errs.bank_account_number =
        'A bank account number is required to complete onboarding.'
    }

    // IRD: length check on a fresh value (R6.2, R6.3).
    const ird = form.ird_number.trim()
    if (ird.length > 0 && !isMaskedIrd(ird) && !validateIrdLength(ird)) {
      errs.ird_number = 'IRD number must be 8 or 9 digits.'
    }

    // Visa expiry: work/student visas require a valid FUTURE date (R8.2, R8.3).
    // A missing, past, or current-dated value blocks submission. Compared in
    // UTC (YYYY-MM-DD) to match the server's UTC `now.date()` check.
    if (VISA_RESIDENCY_TYPES.includes(form.residency_type)) {
      const todayUtc = new Date().toISOString().slice(0, 10)
      const v = form.visa_expiry_date
      if (!v || v <= todayUtc) {
        errs.visa_expiry_date =
          'Enter a valid visa expiry date in the future — work and student visas require current working rights.'
      }
    }

    return errs
  }

  // ------------------------------------------------------------------
  // Submit — raw axios multipart POST. Body MUST be FormData; let axios set
  // the multipart Content-Type/boundary automatically (R9). On 422 map
  // errors inline without clearing inputs (R9.2); on 200 show thank-you
  // (R9.5).
  // ------------------------------------------------------------------
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!token) return

    setSubmitError(null)
    setWarnings([])
    const clientErrors = validateForSubmit()
    if (Object.keys(clientErrors).length > 0) {
      setFieldErrors(clientErrors)
      return
    }
    setFieldErrors({})

    // Cancel any pending autosave so it cannot race the submit.
    if (autosaveTimer.current) {
      clearTimeout(autosaveTimer.current)
      autosaveTimer.current = null
    }

    const fd = new FormData()
    const appendIf = (key: string, value: string) => {
      const v = value.trim()
      if (v) fd.append(key, v)
    }
    appendIf('last_name', form.last_name)
    appendIf('phone', form.phone)
    appendIf('emergency_contact_name', form.emergency_contact_name)
    appendIf('emergency_contact_phone', form.emergency_contact_phone)
    appendIf('tax_code', form.tax_code)
    appendIf('residency_type', form.residency_type)
    if (showVisaExpiry) appendIf('visa_expiry_date', form.visa_expiry_date)
    fd.append('student_loan', form.student_loan ? 'true' : 'false')
    fd.append('kiwisaver_enrolled', form.kiwisaver_enrolled ? 'true' : 'false')
    if (form.kiwisaver_enrolled && form.kiwisaver_employee_rate) {
      fd.append('kiwisaver_employee_rate', form.kiwisaver_employee_rate)
    }

    // IRD / bank — only send a freshly typed (non-masked) value so a resumed
    // masked placeholder does not overwrite the stored secret (R12.3).
    const ird = form.ird_number.trim()
    if (ird && !isMaskedIrd(ird)) fd.append('ird_number', ird)
    const bank = form.bank_account_number.trim()
    if (bank && !isMaskedBank(bank)) fd.append('bank_account_number', bank)

    for (let i = 0; i < Math.min(files.length, MAX_DOC_COUNT); i += 1) {
      const file = files[i]
      const meta = docMeta[i] ?? { type: 'working_rights', detailSelect: '', detailText: '' }
      fd.append('documents', file, file.name)
      fd.append('document_types', meta.type || 'working_rights')
      fd.append('document_descriptions', resolveDocDescription(meta))
    }

    if (photo) {
      fd.append('profile_photo', photo, photo.name)
    }

    setSubmitting(true)
    try {
      // Do NOT set Content-Type — axios derives multipart/form-data + boundary
      // from the FormData body automatically.
      const res = await axios.post<{ ok: boolean; message?: string; warnings?: string[] }>(
        `/api/v2/public/staff-onboarding/${token}`,
        fd,
      )
      const data = res.data
      setConfirmationMessage(
        data?.message || 'Thanks — your details have been submitted.',
      )
      setWarnings(data?.warnings ?? [])
      setSubmitted(true)
    } catch (err) {
      handleSubmitError(err)
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmitError(err: unknown) {
    if (!axios.isAxiosError(err)) {
      setSubmitError('Something went wrong submitting your form. Please try again.')
      return
    }
    const status = err.response?.status
    const body = err.response?.data as
      | (SubmitErrorBody & { detail?: { message?: string; code?: string } })
      | undefined

    if (status === 422 && body?.errors) {
      const mapped: Record<string, string> = {}
      for (const [field, info] of Object.entries(body.errors)) {
        mapped[field] = info?.message ?? 'This field is invalid.'
      }
      setFieldErrors(mapped)
      setSubmitError(
        body.message ?? 'Please fix the highlighted fields and try again.',
      )
      return
    }

    if (status === 404 || status === 410) {
      // Token went invalid between load and submit — surface as a page error.
      setPageError(mapPrefillError(err))
      return
    }

    if (status === 429) {
      setSubmitError('Too many requests. Please wait a moment and try again.')
      return
    }

    const detailMsg = body?.detail?.message || body?.message
    setSubmitError(
      detailMsg || 'Something went wrong submitting your form. Please try again.',
    )
  }

  // ------------------------------------------------------------------
  // Render — shared Tailwind classes (plain public-page chrome, mirroring
  // StaffRosterPublicView's gray palette).
  // ------------------------------------------------------------------
  const inputCls =
    'mt-1 block w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500'
  const labelCls = 'block text-sm font-medium text-gray-700'
  const readonlyCls =
    'mt-1 block w-full rounded-md border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600'
  const cardCls = 'rounded-lg border border-gray-200 bg-white p-5 shadow-sm'
  const sectionTitleCls = 'text-base font-semibold text-gray-900'

  function FieldError({ field }: { field: string }) {
    const msg = fieldErrors[field]
    if (!msg) return null
    return (
      <p id={`${field}-error`} role="alert" className="mt-1 text-xs text-red-600">
        {msg}
      </p>
    )
  }

  /* ── Loading state ── */
  if (loading) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4"
        style={{ minHeight: '100vh' }}
        role="status"
        aria-label="Loading onboarding form"
      >
        <p className="text-sm text-gray-500">Loading…</p>
      </div>
    )
  }

  /* ── Page error state (invalid / expired / revoked / consumed) ── */
  if (pageError) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4 py-8"
        style={{ minHeight: '100vh' }}
      >
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 text-center shadow-sm">
          <h1 className="text-lg font-semibold text-gray-900">{pageError.title}</h1>
          <p className="mt-2 text-sm text-gray-600">{pageError.message}</p>
        </div>
      </div>
    )
  }

  /* ── Thank-you confirmation (R9.5) ── */
  if (submitted) {
    return (
      <div
        className="flex items-center justify-center bg-gray-50 px-4 py-8"
        style={{ minHeight: '100vh' }}
      >
        <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-6 text-center shadow-sm">
          <h1 className="text-lg font-semibold text-gray-900">Onboarding complete</h1>
          <p className="mt-2 text-sm text-gray-600">{confirmationMessage}</p>
          {warnings.length > 0 && (
            <ul className="mt-4 space-y-1 rounded-md bg-amber-50 p-3 text-left text-xs text-amber-700">
              {warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    )
  }

  if (!prefill) return null

  /* ── Form ── */
  return (
    <div className="min-h-screen bg-gray-50 px-4 py-8">
      <div className="mx-auto max-w-2xl">
        <header className="mb-6">
          <p className="text-xs uppercase tracking-wide text-gray-500">
            {prefill.org_name}
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-gray-900">
            Complete your onboarding
          </h1>
          <p className="mt-1 text-sm text-gray-600">
            Please fill in your details below. You can save your progress and
            come back any time using the same link.
          </p>
          {(savedAt || completionPct !== null) && (
            <p className="mt-2 text-xs text-gray-500" aria-live="polite">
              {completionPct !== null && <span>{completionPct}% complete</span>}
              {completionPct !== null && savedAt && <span> · </span>}
              {savedAt && <span>Saved {formatTimestamp(savedAt)}</span>}
            </p>
          )}
        </header>

        {submitError && (
          <div
            role="alert"
            className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            {submitError}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5" noValidate>
          {/* ── Personal ── */}
          <section className={cardCls} aria-labelledby="sec-personal">
            <h2 id="sec-personal" className={sectionTitleCls}>
              Personal details
            </h2>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="first_name" className={labelCls}>
                  First name
                </label>
                <input
                  id="first_name"
                  type="text"
                  value={prefill.first_name}
                  readOnly
                  aria-readonly="true"
                  className={readonlyCls}
                />
              </div>
              <div>
                <label htmlFor="email" className={labelCls}>
                  Email
                </label>
                <input
                  id="email"
                  type="email"
                  value={prefill.email}
                  readOnly
                  aria-readonly="true"
                  className={readonlyCls}
                />
              </div>
              <div>
                <label htmlFor="last_name" className={labelCls}>
                  Last name
                </label>
                <input
                  id="last_name"
                  type="text"
                  value={form.last_name}
                  onChange={(e) => updateField('last_name', e.target.value)}
                  onBlur={scheduleAutosave}
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="phone" className={labelCls}>
                  Phone number
                </label>
                <input
                  id="phone"
                  type="tel"
                  value={form.phone}
                  onChange={(e) => updateField('phone', e.target.value)}
                  onBlur={scheduleAutosave}
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="emergency_contact_name" className={labelCls}>
                  Emergency contact name
                </label>
                <input
                  id="emergency_contact_name"
                  type="text"
                  value={form.emergency_contact_name}
                  onChange={(e) =>
                    updateField('emergency_contact_name', e.target.value)
                  }
                  onBlur={scheduleAutosave}
                  aria-invalid={!!fieldErrors.emergency_contact_name}
                  aria-describedby={
                    fieldErrors.emergency_contact_name
                      ? 'emergency_contact_name-error'
                      : undefined
                  }
                  className={inputCls}
                />
                <FieldError field="emergency_contact_name" />
              </div>
              <div>
                <label htmlFor="emergency_contact_phone" className={labelCls}>
                  Emergency contact phone
                </label>
                <input
                  id="emergency_contact_phone"
                  type="tel"
                  value={form.emergency_contact_phone}
                  onChange={(e) =>
                    updateField('emergency_contact_phone', e.target.value)
                  }
                  onBlur={scheduleAutosave}
                  aria-invalid={!!fieldErrors.emergency_contact_phone}
                  aria-describedby={
                    fieldErrors.emergency_contact_phone
                      ? 'emergency_contact_phone-error'
                      : undefined
                  }
                  className={inputCls}
                />
                <FieldError field="emergency_contact_phone" />
              </div>
            </div>
          </section>

          {/* ── Bank ── */}
          <section className={cardCls} aria-labelledby="sec-bank">
            <h2 id="sec-bank" className={sectionTitleCls}>
              Bank account
            </h2>
            <div className="mt-4">
              <label htmlFor="bank_account_number" className={labelCls}>
                NZ bank account number
                {prefill.bank_account_required && (
                  <span className="text-red-600"> *</span>
                )}
              </label>
              <input
                id="bank_account_number"
                type="text"
                inputMode="numeric"
                placeholder="01-0234-0567890-00"
                value={form.bank_account_number}
                onChange={(e) =>
                  updateField('bank_account_number', formatNzBankAccount(e.target.value))
                }
                onBlur={scheduleAutosave}
                aria-invalid={!!fieldErrors.bank_account_number}
                aria-describedby={
                  fieldErrors.bank_account_number
                    ? 'bank_account_number-error'
                    : 'bank_account_number-help'
                }
                className={inputCls}
              />
              <p id="bank_account_number-help" className="mt-1 text-xs text-gray-500">
                Format: XX-XXXX-XXXXXXX-XX
                {prefill.bank_account_required ? '' : ' (optional)'}
              </p>
              <FieldError field="bank_account_number" />
            </div>
          </section>

          {/* ── IRD & Tax ── */}
          <section className={cardCls} aria-labelledby="sec-tax">
            <h2 id="sec-tax" className={sectionTitleCls}>
              IRD &amp; tax
            </h2>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="ird_number" className={labelCls}>
                  IRD number
                </label>
                <input
                  id="ird_number"
                  type="text"
                  inputMode="numeric"
                  value={form.ird_number}
                  onChange={(e) => updateField('ird_number', formatIrdNumber(e.target.value))}
                  onBlur={scheduleAutosave}
                  aria-invalid={!!fieldErrors.ird_number}
                  aria-describedby={
                    fieldErrors.ird_number ? 'ird_number-error' : 'ird_number-help'
                  }
                  className={inputCls}
                />
                <p id="ird_number-help" className="mt-1 text-xs text-gray-500">
                  8 or 9 digits (optional)
                </p>
                <FieldError field="ird_number" />
              </div>
              <div>
                <label htmlFor="tax_code" className={labelCls}>
                  Tax code
                </label>
                <select
                  id="tax_code"
                  value={form.tax_code}
                  onChange={(e) => updateField('tax_code', e.target.value)}
                  onBlur={scheduleAutosave}
                  className={inputCls}
                >
                  <option value="">Select…</option>
                  {(prefill.tax_code_options ?? []).map((code) => (
                    <option key={code} value={code}>
                      {code}
                    </option>
                  ))}
                </select>
                <FieldError field="tax_code" />
              </div>
              <div className="flex items-center gap-2">
                <input
                  id="student_loan"
                  type="checkbox"
                  checked={form.student_loan}
                  onChange={(e) => {
                    updateField('student_loan', e.target.checked)
                    scheduleAutosave()
                  }}
                  className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <label htmlFor="student_loan" className="text-sm text-gray-700">
                  I have a student loan
                </label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  id="kiwisaver_enrolled"
                  type="checkbox"
                  checked={form.kiwisaver_enrolled}
                  onChange={(e) => {
                    updateField('kiwisaver_enrolled', e.target.checked)
                    scheduleAutosave()
                  }}
                  className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                <label htmlFor="kiwisaver_enrolled" className="text-sm text-gray-700">
                  I am enrolled in KiwiSaver
                </label>
              </div>
              {/* KiwiSaver rate — shown only when enrolled AND no validation
                  errors are present (R6.4). */}
              {form.kiwisaver_enrolled &&
                Object.keys(fieldErrors).length === 0 && (
                <div>
                  <label htmlFor="kiwisaver_employee_rate" className={labelCls}>
                    KiwiSaver contribution rate
                  </label>
                  <select
                    id="kiwisaver_employee_rate"
                    value={form.kiwisaver_employee_rate}
                    onChange={(e) =>
                      updateField('kiwisaver_employee_rate', e.target.value)
                    }
                    onBlur={scheduleAutosave}
                    className={inputCls}
                  >
                    <option value="">Select…</option>
                    {(prefill.kiwisaver_rate_options ?? []).map((rate) => (
                      <option key={rate} value={String(rate)}>
                        {rate}%
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </section>

          {/* ── Residency ── */}
          <section className={cardCls} aria-labelledby="sec-residency">
            <h2 id="sec-residency" className={sectionTitleCls}>
              Residency
            </h2>
            <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="residency_type" className={labelCls}>
                  Residency type
                </label>
                <select
                  id="residency_type"
                  value={form.residency_type}
                  onChange={(e) => updateField('residency_type', e.target.value)}
                  onBlur={scheduleAutosave}
                  className={inputCls}
                >
                  <option value="">Select…</option>
                  {(prefill.residency_options ?? []).map((opt) => (
                    <option key={opt} value={opt}>
                      {RESIDENCY_LABELS[opt] ?? opt}
                    </option>
                  ))}
                </select>
                <FieldError field="residency_type" />
              </div>
              {/* Visa expiry — only for work/student visa (R8.2). */}
              {showVisaExpiry && (
                <div>
                  <label htmlFor="visa_expiry_date" className={labelCls}>
                    Visa expiry date
                  </label>
                  <input
                    id="visa_expiry_date"
                    type="date"
                    value={form.visa_expiry_date}
                    onChange={(e) =>
                      updateField('visa_expiry_date', e.target.value)
                    }
                    onBlur={scheduleAutosave}
                    aria-invalid={!!fieldErrors.visa_expiry_date}
                    aria-describedby={
                      fieldErrors.visa_expiry_date
                        ? 'visa_expiry_date-error'
                        : undefined
                    }
                    className={inputCls}
                  />
                  {/* A missing/past/current-dated value blocks submission (R8.3). */}
                  <FieldError field="visa_expiry_date" />
                </div>
              )}
            </div>
          </section>

          {/* ── Profile photo ── */}
          <section className={cardCls} aria-labelledby="sec-photo">
            <h2 id="sec-photo" className={sectionTitleCls}>
              Profile photo
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Add a clear, passport-style photo of your face. JPEG, PNG or WebP,
              up to 10 MB (optional). It will be shown on your staff profile and
              the time-clock.
            </p>
            <div className="mt-3 flex items-center gap-4">
              <div className="h-20 w-20 shrink-0 overflow-hidden rounded-full border border-gray-200 bg-gray-50">
                {photoPreview ? (
                  <img
                    src={photoPreview}
                    alt="Selected profile preview"
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-gray-300">
                    <svg
                      className="h-10 w-10"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={1.5}
                      aria-hidden="true"
                    >
                      <circle cx="12" cy="8" r="4" />
                      <path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
                    </svg>
                  </div>
                )}
              </div>
              <div>
                <label
                  htmlFor="profile_photo"
                  className="inline-flex cursor-pointer items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
                >
                  {photo ? 'Change photo' : 'Add photo'}
                </label>
                <input
                  id="profile_photo"
                  type="file"
                  accept={ACCEPTED_PHOTO_TYPES}
                  onChange={(e) => {
                    handleSelectPhoto(e.target.files)
                    e.target.value = ''
                  }}
                  className="sr-only"
                />
                {photo && (
                  <button
                    type="button"
                    onClick={handleRemovePhoto}
                    className="ml-3 text-xs font-medium text-red-600 hover:text-red-700"
                  >
                    Remove
                  </button>
                )}
                {photo && (
                  <p className="mt-1 truncate text-xs text-gray-500">{photo.name}</p>
                )}
              </div>
            </div>
            {photoError && (
              <p role="alert" className="mt-2 text-xs text-red-600">
                {photoError}
              </p>
            )}
          </section>

          {/* ── Documents ── */}
          <section className={cardCls} aria-labelledby="sec-docs">
            <h2 id="sec-docs" className={sectionTitleCls}>
              Working-rights documents
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              Upload your passport, visa or work permit. PDF, JPEG or PNG, up to
              10 MB each, maximum {MAX_DOC_COUNT} files (optional).
            </p>
            {resumedDocCount > 0 && (
              <p role="status" className="mt-2 text-xs text-amber-600">
                You previously staged {resumedDocCount} document
                {resumedDocCount === 1 ? '' : 's'}. Please re-attach
                {resumedDocCount === 1 ? ' it' : ' them'} before submitting.
              </p>
            )}
            <div className="mt-3">
              <label
                htmlFor="documents"
                className="inline-flex cursor-pointer items-center rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50"
              >
                Add documents
              </label>
              <input
                id="documents"
                type="file"
                multiple
                accept={ACCEPTED_DOC_TYPES}
                onChange={(e) => {
                  handleAddFiles(e.target.files)
                  e.target.value = ''
                }}
                disabled={files.length >= MAX_DOC_COUNT}
                className="sr-only"
              />
            </div>
            {docError && (
              <p role="alert" className="mt-2 text-xs text-red-600">
                {docError}
              </p>
            )}
            {files.length > 0 && (
              <ul className="mt-3 space-y-3">
                {files.map((file, idx) => {
                  const meta =
                    docMeta[idx] ?? { type: 'working_rights', detailSelect: '', detailText: '' }
                  const cfg = docTypeConfig(meta.type)
                  return (
                    <li
                      key={`${file.name}-${idx}`}
                      className="rounded-md border border-gray-200 p-3 text-sm"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="min-w-0 flex-1 truncate font-medium text-gray-800">
                          {file.name}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleRemoveFile(idx)}
                          className="shrink-0 text-xs font-medium text-red-600 hover:text-red-700"
                          aria-label={`Remove ${file.name}`}
                        >
                          Remove
                        </button>
                      </div>

                      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                        <div>
                          <label className="block text-xs font-medium text-gray-600">
                            Document type
                          </label>
                          <select
                            value={meta.type}
                            onChange={(e) =>
                              updateDocMeta(idx, {
                                type: e.target.value,
                                detailSelect: '',
                                detailText: '',
                              })
                            }
                            className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                          >
                            {STAFF_DOC_TYPES.map((t) => (
                              <option key={t.value} value={t.value}>
                                {t.label}
                              </option>
                            ))}
                          </select>
                        </div>

                        {cfg?.detail && (
                          <div>
                            <label className="block text-xs font-medium text-gray-600">
                              {cfg.detail.label}
                            </label>
                            {cfg.detail.options ? (
                              <>
                                <select
                                  value={meta.detailSelect}
                                  onChange={(e) =>
                                    updateDocMeta(idx, { detailSelect: e.target.value })
                                  }
                                  className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                >
                                  <option value="">Select…</option>
                                  {cfg.detail.options.map((o) => (
                                    <option key={o.value} value={o.value}>
                                      {o.label}
                                    </option>
                                  ))}
                                  {cfg.detail.allowOther && (
                                    <option value="other">Other…</option>
                                  )}
                                </select>
                                {meta.detailSelect === 'other' && (
                                  <input
                                    type="text"
                                    value={meta.detailText}
                                    onChange={(e) =>
                                      updateDocMeta(idx, { detailText: e.target.value })
                                    }
                                    placeholder="Describe the document"
                                    className="mt-2 block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                  />
                                )}
                              </>
                            ) : (
                              <input
                                type="text"
                                value={meta.detailText}
                                onChange={(e) =>
                                  updateDocMeta(idx, { detailText: e.target.value })
                                }
                                placeholder={cfg.detail.placeholder ?? ''}
                                className="mt-1 block w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                              />
                            )}
                          </div>
                        )}
                      </div>

                      {meta.type === 'identity' && meta.detailSelect === 'passport' && (
                        <p className="mt-2 text-xs text-gray-500">
                          An NZ/Australian passport also proves your right to work — you
                          don't need to upload a separate working-rights document.
                        </p>
                      )}
                    </li>
                  )
                })}
              </ul>
            )}
          </section>

          {/* ── Actions ── */}
          {draftNote && (
            <p role="status" className="text-xs text-amber-600">
              {draftNote}
            </p>
          )}
          <div className="flex flex-wrap items-center justify-end gap-3">
            <button
              type="button"
              onClick={handleSaveDraftClick}
              disabled={savingDraft}
              className="min-h-[44px] rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-50"
            >
              {savingDraft ? 'Saving…' : 'Save as draft'}
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="min-h-[44px] rounded-md bg-indigo-600 px-5 py-2 text-sm font-medium text-white shadow-sm hover:bg-indigo-700 disabled:opacity-50"
            >
              {submitting ? 'Submitting…' : 'Submit'}
            </button>
          </div>
        </form>

        <footer className="mt-6 text-center text-xs text-gray-400">
          Your information is transmitted securely and used only for your
          employment records.
        </footer>
      </div>
    </div>
  )
}
