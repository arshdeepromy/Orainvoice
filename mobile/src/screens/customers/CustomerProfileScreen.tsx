import type { ReactNode } from 'react'
import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Page,
  Card,
  Block,
  List,
  ListItem,
  Sheet,
  ListInput,
  Preloader,
  Segmented,
  SegmentedButton,
  BlockTitle,
} from 'konsta/react'
import { useApiDetail } from '@/hooks/useApiDetail'
import { useApiList } from '@/hooks/useApiList'
import { KonstaNavbar } from '@/components/konsta/KonstaNavbar'
import StatusBadge from '@/components/konsta/StatusBadge'
import HapticButton from '@/components/konsta/HapticButton'
import { useModules } from '@/contexts/ModuleContext'
import apiClient from '@/api/client'

/* ------------------------------------------------------------------ */
/* Types — matches CustomerProfileResponse from backend               */
/* ------------------------------------------------------------------ */

interface Address {
  street?: string | null
  city?: string | null
  state?: string | null
  postal_code?: string | null
  country?: string | null
}

interface ContactPerson {
  salutation?: string | null
  first_name: string
  last_name: string
  email?: string | null
  work_phone?: string | null
  mobile_phone?: string | null
  designation?: string | null
  is_primary?: boolean
}

interface CustomerProfile {
  id: string
  customer_type: string
  salutation?: string | null
  first_name: string
  last_name: string
  company_name?: string | null
  display_name?: string | null
  email?: string | null
  phone?: string | null
  work_phone?: string | null
  mobile_phone?: string | null
  currency: string
  language: string
  payment_terms: string
  billing_address?: Address | null
  shipping_address?: Address | null
  contact_persons?: ContactPerson[] | null
  notes?: string | null
  remarks?: string | null
  is_anonymised: boolean
  created_at: string
  updated_at: string
  vehicles?: unknown[]
  invoices?: unknown[]
  total_spend?: string
  outstanding_balance?: string
}

/* ------------------------------------------------------------------ */
/* Linked entity types (for tabs)                                     */
/* ------------------------------------------------------------------ */

interface LinkedInvoice {
  id: string
  invoice_number: string
  status: string
  total: number
  due_date: string
}

interface LinkedVehicle {
  id: string
  rego: string
  make?: string | null
  model?: string | null
  year?: number | null
  colour?: string | null
}

interface ReminderConfig {
  id?: string
  type: string
  enabled: boolean
  interval_days?: number | null
  next_due?: string | null
}

interface HistoryEntry {
  id?: string
  action: string
  description?: string | null
  created_at: string
  user_name?: string | null
}

type ProfileTab = 'profile' | 'invoices' | 'vehicles' | 'reminders' | 'history'

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function getDisplayName(c: CustomerProfile): string {
  if (c.display_name) return c.display_name
  const parts = [c.first_name, c.last_name].filter(Boolean)
  if (parts.length > 0) return parts.join(' ')
  return c.company_name ?? 'Unnamed'
}

function formatNZD(value: string | number | null | undefined): string {
  const num = typeof value === 'string' ? parseFloat(value) : (value ?? 0)
  return `NZD${Number(isNaN(num) ? 0 : num).toLocaleString('en-NZ', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatPaymentTerms(terms: string | null | undefined): string {
  const map: Record<string, string> = {
    due_on_receipt: 'DUE ON RECEIPT',
    net_7: 'NET 7',
    net_15: 'NET 15',
    net_30: 'NET 30',
    net_45: 'NET 45',
    net_60: 'NET 60',
    net_90: 'NET 90',
  }
  return map[terms ?? ''] ?? 'DUE ON RECEIPT'
}

function formatAddress(addr: Address | null | undefined): string | null {
  if (!addr) return null
  const parts = [addr.street, addr.city, addr.state, addr.postal_code, addr.country].filter(Boolean)
  return parts.length > 0 ? parts.join(', ') : null
}

function formatDate(dateStr: string | undefined | null): string {
  if (!dateStr) return ''
  try {
    return new Date(dateStr).toLocaleDateString('en-NZ', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })
  } catch {
    return dateStr ?? ''
  }
}

const AVATAR_COLORS = [
  'bg-blue-500', 'bg-green-500', 'bg-purple-500', 'bg-orange-500',
  'bg-pink-500', 'bg-teal-500', 'bg-indigo-500', 'bg-red-500',
]

function getAvatarColor(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length] ?? AVATAR_COLORS[0]
}

function getInitials(c: CustomerProfile): string {
  const first = (c.first_name ?? '').charAt(0).toUpperCase()
  const last = (c.last_name ?? '').charAt(0).toUpperCase()
  if (first && last) return `${first}${last}`
  if (first) return first
  if (c.company_name) return c.company_name.charAt(0).toUpperCase()
  return '?'
}

/* ------------------------------------------------------------------ */
/* Inline SVG icons                                                   */
/* ------------------------------------------------------------------ */

function PhoneIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z" />
    </svg>
  )
}

function MailIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect width="20" height="16" x="2" y="4" rx="2" />
      <path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7" />
    </svg>
  )
}

function MessageIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* CustomerProfileScreen                                              */
/* ------------------------------------------------------------------ */

/**
 * Customer profile screen — Konsta UI redesign with:
 * - KonstaNavbar with back button and overflow menu
 * - Header card: avatar initials, name, company, contact buttons
 *   (call via tel:, email via mailto:, SMS via sms:)
 * - Tabs using Konsta Segmented: Profile, Invoices, Vehicles
 *   (if vehicles + automotive trade), Reminders, History
 * - Profile tab: read-only fields with "Edit" button opening modal form
 * - Invoices tab: list of customer's invoices with status and total
 * - Vehicles tab: linked vehicles (only if vehicles module + automotive-transport trade)
 * - Reminders tab: WOF/service reminder configuration
 * - Calls GET /customers/:id, GET /invoices?customer_id=:id,
 *   GET /vehicles?customer_id=:id with safe API consumption
 *
 * Requirements: 23.1, 23.2, 23.3, 23.4, 23.5, 23.6, 23.7
 */
export default function CustomerProfileScreen() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { isModuleEnabled, tradeFamily } = useModules()

  const showVehiclesTab =
    isModuleEnabled('vehicles') && tradeFamily === 'automotive-transport'

  const [activeTab, setActiveTab] = useState<ProfileTab>('profile')
  const [showEditSheet, setShowEditSheet] = useState(false)
  const [showActionSheet, setShowActionSheet] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [toast, setToast] = useState<{
    message: string
    variant: 'success' | 'error'
  } | null>(null)

  /* ── API: Customer detail ─────────────────────────────────────── */
  const {
    data: customer,
    isLoading,
    error,
    refetch,
  } = useApiDetail<CustomerProfile>({
    endpoint: `/api/v1/customers/${id}`,
    enabled: !!id,
  })

  /* ── API: Linked invoices ─────────────────────────────────────── */
  const invoiceList = useApiList<LinkedInvoice>({
    endpoint: '/api/v1/invoices',
    dataKey: 'invoices',
    initialFilters: { customer_id: id ?? '' },
  })

  /* ── API: Linked vehicles ─────────────────────────────────────── */
  const vehicleList = useApiList<LinkedVehicle>({
    endpoint: '/api/v1/vehicles',
    dataKey: 'vehicles',
    initialFilters: { customer_id: id ?? '' },
  })

  /* ── API: Reminders ───────────────────────────────────────────── */
  const reminderList = useApiList<ReminderConfig>({
    endpoint: `/api/v1/customers/${id}/reminders`,
    dataKey: 'reminders',
  })

  /* ── API: History ─────────────────────────────────────────────── */
  const historyList = useApiList<HistoryEntry>({
    endpoint: `/api/v1/customers/${id}/history`,
    dataKey: 'history',
  })

  /* ── Handlers ─────────────────────────────────────────────────── */

  const handleDelete = useCallback(async () => {
    if (!id) return
    setIsDeleting(true)
    try {
      await apiClient.delete(`/api/v1/customers/${id}`)
      navigate('/customers', { replace: true })
    } catch {
      setToast({ message: 'Failed to delete customer', variant: 'error' })
    } finally {
      setIsDeleting(false)
      setShowDeleteConfirm(false)
      setShowActionSheet(false)
    }
  }, [id, navigate])

  /* ── Loading state ────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <Page data-testid="customer-profile-page">
        <KonstaNavbar title="Customer" showBack />
        <div className="flex flex-1 items-center justify-center p-8">
          <Preloader />
        </div>
      </Page>
    )
  }

  if (error || !customer) {
    return (
      <Page data-testid="customer-profile-page">
        <KonstaNavbar title="Customer" showBack />
        <Block>
          <div className="py-8 text-center text-red-600 dark:text-red-400">
            {error ?? 'Customer not found'}
          </div>
        </Block>
      </Page>
    )
  }

  /* ── Derived data ─────────────────────────────────────────────── */

  const displayNameStr = getDisplayName(customer)
  const primaryPhone = customer.mobile_phone ?? customer.phone ?? null
  const billingAddr = formatAddress(customer.billing_address as Address | null)
  const shippingAddr = formatAddress(customer.shipping_address as Address | null)
  const contactPersons = (customer.contact_persons ?? []) as ContactPerson[]

  /* ── Build tab list ───────────────────────────────────────────── */

  const tabs: { key: ProfileTab; label: string }[] = [
    { key: 'profile', label: 'Profile' },
    { key: 'invoices', label: 'Invoices' },
  ]
  if (showVehiclesTab) {
    tabs.push({ key: 'vehicles', label: 'Vehicles' })
  }
  tabs.push({ key: 'reminders', label: 'Reminders' })
  tabs.push({ key: 'history', label: 'History' })

  /* ── Overflow menu (•••) ──────────────────────────────────────── */

  const overflowButton = (
    <button
      type="button"
      onClick={() => setShowActionSheet(true)}
      className="flex min-h-[44px] min-w-[44px] items-center justify-center text-lg text-primary"
      aria-label="More actions"
      data-testid="overflow-menu-button"
    >
      •••
    </button>
  )

  return (
    <Page data-testid="customer-profile-page">
      {/* ── Navbar ──────────────────────────────────────────────── */}
      <KonstaNavbar
        title={displayNameStr}
        showBack
        rightActions={overflowButton}
      />

      <div className="flex flex-col gap-4 pb-24">
        {/* ── Toast ───────────────────────────────────────────────── */}
        {toast && (
          <div
            className={`mx-4 mt-2 rounded-lg p-3 text-sm ${
              toast.variant === 'success'
                ? 'bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-300'
                : 'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300'
            }`}
            role="alert"
          >
            {toast.message}
            <button
              type="button"
              onClick={() => setToast(null)}
              className="ml-2 font-medium underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* ── Header Card: Avatar, Name, Company, Contact Buttons ── */}
        <Card className="mx-4 mt-2" data-testid="customer-header-card">
          <div className="flex flex-col items-center gap-3 p-4">
            {/* Avatar with initials */}
            <div
              className={`flex h-16 w-16 items-center justify-center rounded-full text-xl font-bold text-white ${getAvatarColor(displayNameStr)}`}
              aria-hidden="true"
              data-testid="customer-avatar"
            >
              {getInitials(customer)}
            </div>

            {/* Name and company */}
            <div className="text-center">
              <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
                {displayNameStr}
              </h2>
              {customer.company_name && (
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {customer.company_name}
                </p>
              )}
            </div>

            {/* Contact action buttons */}
            <div className="flex gap-4 pt-1">
              <ContactButton
                icon={<PhoneIcon className="h-5 w-5" />}
                label="Call"
                disabled={!primaryPhone}
                onTap={() =>
                  primaryPhone && window.open(`tel:${primaryPhone}`, '_system')
                }
              />
              <ContactButton
                icon={<MailIcon className="h-5 w-5" />}
                label="Email"
                disabled={!customer.email}
                onTap={() =>
                  customer.email &&
                  window.open(`mailto:${customer.email}`, '_system')
                }
              />
              <ContactButton
                icon={<MessageIcon className="h-5 w-5" />}
                label="SMS"
                disabled={!primaryPhone}
                onTap={() =>
                  primaryPhone && window.open(`sms:${primaryPhone}`, '_system')
                }
              />
            </div>
          </div>
        </Card>

        {/* ── Segmented Tab Bar ────────────────────────────────────── */}
        <div className="px-4">
          <Segmented strong data-testid="profile-tabs">
            {tabs.map((tab) => (
              <SegmentedButton
                key={tab.key}
                active={activeTab === tab.key}
                onClick={() => setActiveTab(tab.key)}
                data-testid={`tab-${tab.key}`}
              >
                {tab.label}
              </SegmentedButton>
            ))}
          </Segmented>
        </div>

        {/* ── Tab Content ──────────────────────────────────────────── */}
        <div role="tabpanel" data-testid={`tabpanel-${activeTab}`}>
          {activeTab === 'profile' && (
            <ProfileTabContent
              customer={customer}
              billingAddr={billingAddr}
              shippingAddr={shippingAddr}
              contactPersons={contactPersons}
              onEdit={() => setShowEditSheet(true)}
            />
          )}
          {activeTab === 'invoices' && (
            <InvoicesTabContent
              items={invoiceList.items}
              isLoading={invoiceList.isLoading}
              onTap={(inv) => navigate(`/invoices/${inv.id}`)}
            />
          )}
          {activeTab === 'vehicles' && showVehiclesTab && (
            <VehiclesTabContent
              items={vehicleList.items}
              isLoading={vehicleList.isLoading}
              onTap={(v) => navigate(`/vehicles/${v.id}`)}
            />
          )}
          {activeTab === 'reminders' && (
            <RemindersTabContent
              items={reminderList.items}
              isLoading={reminderList.isLoading}
            />
          )}
          {activeTab === 'history' && (
            <HistoryTabContent
              items={historyList.items}
              isLoading={historyList.isLoading}
            />
          )}
        </div>
      </div>

      {/* ── Edit Customer Sheet ─────────────────────────────────── */}
      <EditCustomerSheet
        isOpen={showEditSheet}
        onClose={() => setShowEditSheet(false)}
        customer={customer}
        customerId={id ?? ''}
        onSuccess={async () => {
          setShowEditSheet(false)
          setToast({ message: 'Customer updated', variant: 'success' })
          await refetch()
        }}
      />

      {/* ── Actions Sheet ───────────────────────────────────────── */}
      <Sheet
        opened={showActionSheet}
        onBackdropClick={() => setShowActionSheet(false)}
        data-testid="actions-sheet"
      >
        <Block>
          <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
            Actions
          </h3>
          <List strongIos outlineIos dividersIos>
            <ListItem
              link
              title="New Invoice"
              onClick={() => {
                setShowActionSheet(false)
                navigate(`/invoices/new?customer_id=${id}`)
              }}
            />
            <ListItem
              link
              title="Customer Statement"
              onClick={() => {
                setShowActionSheet(false)
                navigate(`/reports/customer-statement?customer_id=${id}`)
              }}
            />
            <ListItem
              link
              title="Delete Customer"
              onClick={() => {
                setShowActionSheet(false)
                setShowDeleteConfirm(true)
              }}
              className="text-red-600 dark:text-red-400"
            />
          </List>
          <div className="mt-3">
            <HapticButton
              outline
              large
              onClick={() => setShowActionSheet(false)}
              className="w-full"
            >
              Cancel
            </HapticButton>
          </div>
        </Block>
      </Sheet>

      {/* ── Delete Confirmation Sheet ───────────────────────────── */}
      <Sheet
        opened={showDeleteConfirm}
        onBackdropClick={() => setShowDeleteConfirm(false)}
        data-testid="delete-confirm-sheet"
      >
        <Block>
          <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
            Delete Customer
          </h3>
          <p className="mb-4 text-sm text-gray-600 dark:text-gray-300">
            Are you sure you want to delete this customer? This action will
            anonymise their data and cannot be undone.
          </p>
          <div className="flex gap-3">
            <HapticButton
              outline
              onClick={() => setShowDeleteConfirm(false)}
              className="flex-1"
            >
              Cancel
            </HapticButton>
            <HapticButton
              hapticStyle="heavy"
              onClick={handleDelete}
              disabled={isDeleting}
              className="flex-1"
              colors={{ fillBgIos: 'bg-red-500', fillBgMaterial: 'bg-red-500' }}
            >
              {isDeleting ? 'Deleting…' : 'Delete'}
            </HapticButton>
          </div>
        </Block>
      </Sheet>
    </Page>
  )
}


/* ------------------------------------------------------------------ */
/* Sub-components                                                     */
/* ------------------------------------------------------------------ */

/** Contact action button (call, email, SMS) */
function ContactButton({
  icon,
  label,
  disabled,
  onTap,
}: {
  icon: ReactNode
  label: string
  disabled?: boolean
  onTap: () => void
}) {
  return (
    <button
      type="button"
      onClick={onTap}
      disabled={disabled}
      className={`flex min-h-[44px] min-w-[44px] flex-col items-center gap-1 ${
        disabled
          ? 'opacity-30'
          : 'text-primary active:opacity-70'
      }`}
      aria-label={label}
      data-testid={`contact-btn-${label.toLowerCase()}`}
    >
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-primary/10 dark:bg-primary/20">
        {icon}
      </div>
      <span className="text-xs font-medium">{label}</span>
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Profile Tab                                                        */
/* ------------------------------------------------------------------ */

function ProfileTabContent({
  customer,
  billingAddr,
  shippingAddr,
  contactPersons,
  onEdit,
}: {
  customer: CustomerProfile
  billingAddr: string | null
  shippingAddr: string | null
  contactPersons: ContactPerson[]
  onEdit: () => void
}) {
  return (
    <div className="flex flex-col gap-2">
      {/* Edit button */}
      <Block className="flex justify-end">
        <HapticButton small outline onClick={onEdit} data-testid="edit-customer-btn">
          Edit
        </HapticButton>
      </Block>

      {/* Contact details */}
      <BlockTitle>Contact Details</BlockTitle>
      <List strongIos outlineIos dividersIos>
        <ListItem
          title="Name"
          after={
            <span className="text-sm text-gray-900 dark:text-gray-100">
              {[customer.salutation, customer.first_name, customer.last_name]
                .filter(Boolean)
                .join(' ') || '—'}
            </span>
          }
        />
        {customer.company_name && (
          <ListItem
            title="Company"
            after={
              <span className="text-sm text-gray-900 dark:text-gray-100">
                {customer.company_name}
              </span>
            }
          />
        )}
        {customer.email && (
          <ListItem
            title="Email"
            after={
              <span className="text-sm text-primary">{customer.email}</span>
            }
          />
        )}
        {customer.phone && (
          <ListItem
            title="Phone"
            after={
              <span className="text-sm text-gray-900 dark:text-gray-100">
                {customer.phone}
              </span>
            }
          />
        )}
        {customer.mobile_phone && (
          <ListItem
            title="Mobile"
            after={
              <span className="text-sm text-gray-900 dark:text-gray-100">
                {customer.mobile_phone}
              </span>
            }
          />
        )}
        {customer.work_phone && (
          <ListItem
            title="Work Phone"
            after={
              <span className="text-sm text-gray-900 dark:text-gray-100">
                {customer.work_phone}
              </span>
            }
          />
        )}
      </List>

      {/* Financial info */}
      <BlockTitle>Financial</BlockTitle>
      <List strongIos outlineIos dividersIos>
        <ListItem
          title="Outstanding"
          after={
            <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
              {formatNZD(customer.outstanding_balance)}
            </span>
          }
        />
        <ListItem
          title="Total Spend"
          after={
            <span className="text-sm text-gray-900 dark:text-gray-100">
              {formatNZD(customer.total_spend)}
            </span>
          }
        />
        <ListItem
          title="Payment Terms"
          after={
            <span className="text-sm text-gray-900 dark:text-gray-100">
              {formatPaymentTerms(customer.payment_terms)}
            </span>
          }
        />
        <ListItem
          title="Currency"
          after={
            <span className="text-sm text-gray-900 dark:text-gray-100">
              {customer.currency ?? 'NZD'}
            </span>
          }
        />
      </List>

      {/* Addresses */}
      {(billingAddr || shippingAddr) && (
        <>
          <BlockTitle>Addresses</BlockTitle>
          <List strongIos outlineIos dividersIos>
            {billingAddr && (
              <ListItem
                title="Billing"
                subtitle={
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {billingAddr}
                  </span>
                }
              />
            )}
            {shippingAddr && (
              <ListItem
                title="Shipping"
                subtitle={
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {shippingAddr}
                  </span>
                }
              />
            )}
          </List>
        </>
      )}

      {/* Contact persons */}
      {contactPersons.length > 0 && (
        <>
          <BlockTitle>Contact Persons</BlockTitle>
          <List strongIos outlineIos dividersIos>
            {contactPersons.map((cp, idx) => (
              <ListItem
                key={idx}
                title={
                  [cp.salutation, cp.first_name, cp.last_name]
                    .filter(Boolean)
                    .join(' ')
                }
                subtitle={
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {[cp.email, cp.mobile_phone ?? cp.work_phone]
                      .filter(Boolean)
                      .join(' · ') || cp.designation || undefined}
                  </span>
                }
                after={
                  cp.is_primary ? (
                    <span className="text-xs font-medium text-primary">
                      Primary
                    </span>
                  ) : undefined
                }
              />
            ))}
          </List>
        </>
      )}

      {/* Notes */}
      {(customer.notes || customer.remarks) && (
        <>
          <BlockTitle>Notes</BlockTitle>
          <Card className="mx-4">
            <div className="p-4 text-sm text-gray-700 dark:text-gray-300">
              {customer.notes ?? customer.remarks}
            </div>
          </Card>
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Invoices Tab                                                       */
/* ------------------------------------------------------------------ */

function InvoicesTabContent({
  items,
  isLoading,
  onTap,
}: {
  items: LinkedInvoice[]
  isLoading: boolean
  onTap: (inv: LinkedInvoice) => void
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Preloader />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <Block className="text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">No invoices</p>
      </Block>
    )
  }
  return (
    <List strongIos outlineIos dividersIos data-testid="invoices-tab-list">
      {items.map((inv) => (
        <ListItem
          key={inv.id}
          link
          onClick={() => onTap(inv)}
          title={
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {inv.invoice_number ?? 'Invoice'}
            </span>
          }
          subtitle={
            <span className="text-xs text-gray-500 dark:text-gray-400">
              Due {formatDate(inv.due_date)}
            </span>
          }
          after={
            <div className="flex flex-col items-end gap-1">
              <span className="text-sm font-medium tabular-nums text-gray-900 dark:text-gray-100">
                {formatNZD(inv.total ?? 0)}
              </span>
              <StatusBadge status={inv.status} size="sm" />
            </div>
          }
        />
      ))}
    </List>
  )
}

/* ------------------------------------------------------------------ */
/* Vehicles Tab                                                       */
/* ------------------------------------------------------------------ */

function VehiclesTabContent({
  items,
  isLoading,
  onTap,
}: {
  items: LinkedVehicle[]
  isLoading: boolean
  onTap: (v: LinkedVehicle) => void
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Preloader />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <Block className="text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">
          No linked vehicles
        </p>
      </Block>
    )
  }
  return (
    <List strongIos outlineIos dividersIos data-testid="vehicles-tab-list">
      {items.map((v) => (
        <ListItem
          key={v.id}
          link
          onClick={() => onTap(v)}
          title={
            <span className="font-mono font-bold text-gray-900 dark:text-gray-100">
              {v.rego}
            </span>
          }
          subtitle={
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {[v.make, v.model, v.year].filter(Boolean).join(' ') || '—'}
            </span>
          }
        />
      ))}
    </List>
  )
}

/* ------------------------------------------------------------------ */
/* Reminders Tab                                                      */
/* ------------------------------------------------------------------ */

function RemindersTabContent({
  items,
  isLoading,
}: {
  items: ReminderConfig[]
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Preloader />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <Block className="text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">
          No reminders configured
        </p>
      </Block>
    )
  }
  return (
    <List strongIos outlineIos dividersIos data-testid="reminders-tab-list">
      {items.map((r, idx) => (
        <ListItem
          key={r.id ?? idx}
          title={r.type}
          subtitle={
            r.next_due ? (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Next due: {formatDate(r.next_due)}
              </span>
            ) : undefined
          }
          after={
            <span
              className={`text-xs font-medium ${
                r.enabled
                  ? 'text-emerald-600 dark:text-emerald-400'
                  : 'text-gray-400 dark:text-gray-500'
              }`}
            >
              {r.enabled ? 'Active' : 'Inactive'}
            </span>
          }
        />
      ))}
    </List>
  )
}

/* ------------------------------------------------------------------ */
/* History Tab                                                        */
/* ------------------------------------------------------------------ */

function HistoryTabContent({
  items,
  isLoading,
}: {
  items: HistoryEntry[]
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <Preloader />
      </div>
    )
  }
  if (items.length === 0) {
    return (
      <Block className="text-center">
        <p className="text-sm text-gray-400 dark:text-gray-500">No history</p>
      </Block>
    )
  }
  return (
    <List strongIos outlineIos dividersIos data-testid="history-tab-list">
      {items.map((h, idx) => (
        <ListItem
          key={h.id ?? idx}
          title={h.action}
          subtitle={
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {h.description ?? ''}
              {h.user_name ? ` — ${h.user_name}` : ''}
            </span>
          }
          after={
            <span className="text-xs text-gray-400 dark:text-gray-500">
              {formatDate(h.created_at)}
            </span>
          }
        />
      ))}
    </List>
  )
}

/* ------------------------------------------------------------------ */
/* Edit Customer Sheet (modal form)                                   */
/* ------------------------------------------------------------------ */

function EditCustomerSheet({
  isOpen,
  onClose,
  customer,
  customerId,
  onSuccess,
}: {
  isOpen: boolean
  onClose: () => void
  customer: CustomerProfile
  customerId: string
  onSuccess: () => void
}) {
  const [form, setForm] = useState({
    first_name: customer.first_name ?? '',
    last_name: customer.last_name ?? '',
    company_name: customer.company_name ?? '',
    email: customer.email ?? '',
    phone: customer.phone ?? '',
    mobile_phone: customer.mobile_phone ?? '',
    work_phone: customer.work_phone ?? '',
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const updateField = useCallback(
    (field: string, value: string) => {
      setForm((prev) => ({ ...prev, [field]: value }))
      setError(null)
    },
    [],
  )

  const handleSubmit = useCallback(async () => {
    if (!form.first_name.trim()) {
      setError('First name is required')
      return
    }
    setIsSubmitting(true)
    setError(null)
    try {
      await apiClient.put(`/api/v1/customers/${customerId}`, {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim() || undefined,
        company_name: form.company_name.trim() || undefined,
        email: form.email.trim() || undefined,
        phone: form.phone.trim() || undefined,
        mobile_phone: form.mobile_phone.trim() || undefined,
        work_phone: form.work_phone.trim() || undefined,
      })
      onSuccess()
    } catch {
      setError('Failed to update customer')
    } finally {
      setIsSubmitting(false)
    }
  }, [form, customerId, onSuccess])

  return (
    <Sheet
      opened={isOpen}
      onBackdropClick={onClose}
      data-testid="edit-customer-sheet"
      className="pb-safe"
    >
      <Block>
        <h3 className="mb-3 text-lg font-semibold text-gray-900 dark:text-gray-100">
          Edit Customer
        </h3>
      </Block>
      <List strongIos outlineIos>
        <ListInput
          label="First Name"
          type="text"
          placeholder="First name"
          value={form.first_name}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('first_name', e.target.value)
          }
          inputClassName="min-h-[44px]"
          required
        />
        <ListInput
          label="Last Name"
          type="text"
          placeholder="Last name"
          value={form.last_name}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('last_name', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />
        <ListInput
          label="Company"
          type="text"
          placeholder="Company name"
          value={form.company_name}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('company_name', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />
        <ListInput
          label="Email"
          type="email"
          placeholder="email@example.com"
          value={form.email}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('email', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />
        <ListInput
          label="Phone"
          type="tel"
          placeholder="Phone"
          value={form.phone}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('phone', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />
        <ListInput
          label="Mobile"
          type="tel"
          placeholder="Mobile phone"
          value={form.mobile_phone}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('mobile_phone', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />
        <ListInput
          label="Work Phone"
          type="tel"
          placeholder="Work phone"
          value={form.work_phone}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
            updateField('work_phone', e.target.value)
          }
          inputClassName="min-h-[44px]"
        />
      </List>
      {error && (
        <Block>
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        </Block>
      )}
      <Block className="flex gap-3">
        <HapticButton
          outline
          onClick={onClose}
          disabled={isSubmitting}
          className="flex-1"
        >
          Cancel
        </HapticButton>
        <HapticButton
          onClick={handleSubmit}
          disabled={isSubmitting}
          className="flex-1"
        >
          {isSubmitting ? 'Saving…' : 'Save'}
        </HapticButton>
      </Block>
    </Sheet>
  )
}