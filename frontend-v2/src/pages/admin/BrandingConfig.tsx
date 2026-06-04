import { useEffect, useState, useRef, useCallback } from 'react'
import Button from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import Badge from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { THEMES } from '@/themes/registry'

export interface PlatformBranding {
  id: string
  platform_name: string
  logo_url: string | null
  dark_logo_url: string | null
  favicon_url: string | null
  primary_colour: string
  secondary_colour: string
  website_url: string | null
  signup_url: string | null
  support_email: string | null
  terms_url: string | null
  auto_detect_domain: boolean
  platform_theme: string
  created_at: string
  updated_at: string
}

/* ── Image Upload Drop Zone ── */

interface ImageUploadProps {
  label: string
  currentUrl: string | null
  onUrlChange: (url: string) => void
  uploadEndpoint: string
  accept: string
  maxSizeLabel: string
  previewSize: string
  onUploadSuccess: (url: string) => void
  onError: (msg: string) => void
}

function ImageUpload({
  label,
  currentUrl,
  onUrlChange,
  uploadEndpoint,
  accept,
  maxSizeLabel,
  previewSize,
  onUploadSuccess,
  onError,
}: ImageUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [useUrl, setUseUrl] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(
    async (file: File) => {
      setUploading(true)
      try {
        const formData = new FormData()
        formData.append('file', file)
        const res = await apiClient.post<{ url: string; message: string }>(
          uploadEndpoint,
          formData,
          { headers: { 'Content-Type': 'multipart/form-data' } },
        )
        const url = res.data?.url ?? ''
        if (url) {
          onUploadSuccess(url)
        }
      } catch (err: unknown) {
        const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } }
        const detail = axiosErr?.response?.data?.detail
        onError(detail || `Failed to upload ${label.toLowerCase()}`)
      } finally {
        setUploading(false)
      }
    },
    [uploadEndpoint, label, onUploadSuccess, onError],
  )

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      const file = e.dataTransfer.files[0]
      if (file) handleFile(file)
    },
    [handleFile],
  )

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) handleFile(file)
      // Reset so the same file can be re-selected
      e.target.value = ''
    },
    [handleFile],
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-text">{label}</label>
        <button
          type="button"
          onClick={() => setUseUrl(!useUrl)}
          className="text-xs text-accent hover:text-accent-press underline"
        >
          {useUrl ? 'Upload file instead' : 'Use URL instead'}
        </button>
      </div>

      {useUrl ? (
        <Input
          label=""
          id={`${label.toLowerCase().replace(/\s/g, '_')}_url`}
          value={currentUrl || ''}
          onChange={(e) => onUrlChange(e.target.value)}
          placeholder="https://example.com/image.png"
        />
      ) : (
        <div
          role="button"
          tabIndex={0}
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') fileInputRef.current?.click()
          }}
          className={`relative flex flex-col items-center justify-center rounded-card border-2 border-dashed p-6 cursor-pointer transition-colors ${
            dragOver
              ? 'border-accent bg-accent-soft'
              : 'border-border hover:border-border-strong hover:bg-canvas'
          }`}
        >
          {uploading ? (
            <Spinner label={`Uploading ${label.toLowerCase()}...`} />
          ) : (
            <>
              {currentUrl ? (
                <img
                  src={currentUrl}
                  alt={`Current ${label.toLowerCase()}`}
                  className={`${previewSize} object-contain mb-3 rounded`}
                />
              ) : (
                <div className={`${previewSize} flex items-center justify-center mb-3 rounded bg-canvas text-muted-2`}>
                  <svg className="h-8 w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
                  </svg>
                </div>
              )}
              <p className="text-sm text-muted">
                <span className="font-medium text-accent">Click to upload</span> or drag and drop
              </p>
              <p className="text-xs text-muted-2 mt-1">
                PNG, JPG, WebP, SVG{label.toLowerCase().includes('favicon') ? ', ICO' : ''} — max {maxSizeLabel}
              </p>
            </>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={accept}
            onChange={handleFileSelect}
            className="hidden"
            aria-label={`Upload ${label.toLowerCase()}`}
          />
        </div>
      )}

      {currentUrl && !useUrl && (
        <p className="text-xs text-muted-2 truncate" title={currentUrl}>
          Current: {currentUrl}
        </p>
      )}
    </div>
  )
}

/* ── Main Branding Config Page ── */

export function BrandingConfig() {
  const [branding, setBranding] = useState<PlatformBranding | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const { toasts, addToast, dismissToast } = useToast()

  useEffect(() => {
    apiClient
      .get('/api/v2/admin/branding')
      .then((res) => {
        setBranding(res.data)
        setLoading(false)
      })
      .catch(() => {
        addToast('error', 'Could not load branding configuration')
        setLoading(false)
      })
  }, [])

  const handleChange = (field: keyof PlatformBranding, value: string | boolean) => {
    if (!branding) return
    setBranding({ ...branding, [field]: value })
  }

  const handleSave = async () => {
    if (!branding) return
    setSaving(true)
    try {
      const res = await apiClient.put('/api/v2/admin/branding', {
        platform_name: branding.platform_name,
        logo_url: branding.logo_url,
        dark_logo_url: branding.dark_logo_url,
        favicon_url: branding.favicon_url,
        primary_colour: branding.primary_colour,
        secondary_colour: branding.secondary_colour,
        website_url: branding.website_url,
        signup_url: branding.signup_url,
        support_email: branding.support_email,
        terms_url: branding.terms_url,
        auto_detect_domain: branding.auto_detect_domain,
        platform_theme: branding.platform_theme,
      })
      setBranding(res.data)
      addToast('success', 'Branding saved successfully')
    } catch {
      addToast('error', 'Failed to save branding')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spinner label="Loading branding configuration" />
      </div>
    )
  }

  if (!branding) {
    return (
      <AlertBanner variant="error" title="Something went wrong">
        We couldn't load the branding configuration. Please refresh the page.
      </AlertBanner>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-text">Platform Branding</h1>
        <Badge variant="info">Global</Badge>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Form */}
        <div className="lg:col-span-2 space-y-6">
          {/* Identity */}
          <section className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
            <h2 className="text-lg font-semibold text-text">Identity</h2>
            <Input
              label="Platform name"
              id="platform_name"
              value={branding.platform_name}
              onChange={(e) => handleChange('platform_name', e.target.value)}
            />

            {/* Logo upload */}
            <ImageUpload
              label="Logo"
              currentUrl={branding.logo_url}
              onUrlChange={(url) => handleChange('logo_url', url)}
              uploadEndpoint="/api/v2/admin/branding/upload-logo"
              accept="image/png,image/jpeg,image/webp,image/svg+xml"
              maxSizeLabel="2 MB"
              previewSize="h-16 w-16"
              onUploadSuccess={(url) => {
                handleChange('logo_url', url)
                addToast('success', 'Logo uploaded')
              }}
              onError={(msg) => addToast('error', msg)}
            />

            {/* Dark mode logo upload */}
            <ImageUpload
              label="Dark Mode Logo"
              currentUrl={branding.dark_logo_url}
              onUrlChange={(url) => handleChange('dark_logo_url', url)}
              uploadEndpoint="/api/v2/admin/branding/upload-dark-logo"
              accept="image/png,image/jpeg,image/webp,image/svg+xml"
              maxSizeLabel="2 MB"
              previewSize="h-16 w-16"
              onUploadSuccess={(url) => {
                handleChange('dark_logo_url', url)
                addToast('success', 'Dark mode logo uploaded')
              }}
              onError={(msg) => addToast('error', msg)}
            />

            {/* Favicon upload */}
            <ImageUpload
              label="Favicon"
              currentUrl={branding.favicon_url}
              onUrlChange={(url) => handleChange('favicon_url', url)}
              uploadEndpoint="/api/v2/admin/branding/upload-favicon"
              accept="image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon,image/vnd.microsoft.icon"
              maxSizeLabel="512 KB"
              previewSize="h-10 w-10"
              onUploadSuccess={(url) => {
                handleChange('favicon_url', url)
                addToast('success', 'Favicon uploaded')
              }}
              onError={(msg) => addToast('error', msg)}
            />
          </section>

          {/* Colours */}
          <section className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
            <h2 className="text-lg font-semibold text-text">Colours</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label htmlFor="primary_colour" className="block text-sm font-medium text-text mb-1">
                  Primary colour
                </label>
                <div className="flex items-center gap-3">
                  <input
                    id="primary_colour"
                    type="color"
                    value={branding.primary_colour}
                    onChange={(e) => handleChange('primary_colour', e.target.value)}
                    className="h-10 w-14 rounded border border-border cursor-pointer p-0.5"
                  />
                  <span className="text-sm mono text-muted">{branding.primary_colour}</span>
                </div>
              </div>
              <div>
                <label htmlFor="secondary_colour" className="block text-sm font-medium text-text mb-1">
                  Secondary colour
                </label>
                <div className="flex items-center gap-3">
                  <input
                    id="secondary_colour"
                    type="color"
                    value={branding.secondary_colour}
                    onChange={(e) => handleChange('secondary_colour', e.target.value)}
                    className="h-10 w-14 rounded border border-border cursor-pointer p-0.5"
                  />
                  <span className="text-sm mono text-muted">{branding.secondary_colour}</span>
                </div>
              </div>
            </div>
          </section>

          {/* URLs & Contact */}
          <section className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
            <h2 className="text-lg font-semibold text-text">URLs &amp; Contact</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <Input
                label="Signup URL"
                id="signup_url"
                value={branding.signup_url || ''}
                onChange={(e) => handleChange('signup_url', e.target.value)}
                placeholder="https://example.com/signup"
              />
              <Input
                label="Website URL"
                id="website_url"
                value={branding.website_url || ''}
                onChange={(e) => handleChange('website_url', e.target.value)}
                placeholder="https://example.com"
              />
              <Input
                label="Support email"
                id="support_email"
                type="email"
                value={branding.support_email || ''}
                onChange={(e) => handleChange('support_email', e.target.value)}
                placeholder="support@example.com"
              />
              <Input
                label="Terms URL"
                id="terms_url"
                value={branding.terms_url || ''}
                onChange={(e) => handleChange('terms_url', e.target.value)}
                placeholder="https://example.com/terms"
              />
            </div>
          </section>

          {/* Theme */}
          <section className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
            <h2 className="text-lg font-semibold text-text">Platform Theme</h2>
            <p className="text-sm text-muted">Choose the visual theme applied across the entire platform. Changes take effect on next page load for all users.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {THEMES.map((theme) => {
                const isSelected = (branding.platform_theme || 'classic') === theme.id
                return (
                  <button
                    key={theme.id}
                    type="button"
                    onClick={() => handleChange('platform_theme', theme.id)}
                    className={`relative flex items-start gap-4 rounded-card border-2 p-4 text-left transition-all ${
                      isSelected
                        ? 'border-accent bg-accent-soft ring-2 ring-accent/20'
                        : 'border-border hover:border-border-strong hover:bg-canvas'
                    }`}
                  >
                    {/* Color swatch preview */}
                    <div className="flex flex-col gap-1 shrink-0">
                      <div
                        className="h-10 w-10 rounded-lg shadow-sm border border-border"
                        style={{ backgroundColor: theme.previewColors.sidebar }}
                      />
                      <div
                        className="h-3 w-10 rounded-full"
                        style={{ backgroundColor: theme.previewColors.primary }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-text">{theme.label}</span>
                        {isSelected && (
                          <span className="inline-flex items-center rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">Active</span>
                        )}
                      </div>
                      <p className="text-xs text-muted mt-0.5">{theme.description}</p>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>

          {/* Options */}
          <section className="rounded-card border border-border bg-card p-5 space-y-4 shadow-card">
            <h2 className="text-lg font-semibold text-text">Options</h2>
            <label htmlFor="auto_detect_domain" className="flex items-center gap-3 cursor-pointer">
              <input
                id="auto_detect_domain"
                type="checkbox"
                checked={branding.auto_detect_domain}
                onChange={(e) => handleChange('auto_detect_domain', e.target.checked)}
                className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
              />
              <span className="text-sm text-text">Auto-detect domain for white-label branding</span>
            </label>
          </section>

          {/* Save */}
          <div className="flex justify-end">
            <Button onClick={handleSave} loading={saving}>
              Save branding
            </Button>
          </div>
        </div>

        {/* Preview sidebar */}
        <div className="lg:col-span-1">
          <div className="sticky top-6">
            <h2 className="text-lg font-semibold text-text mb-3">Preview</h2>
            <div
              role="region"
              aria-label="branding preview"
              className="rounded-card border border-border bg-card overflow-hidden shadow-card"
            >
              {/* Header preview */}
              <div
                className="flex items-center gap-3 px-4 py-3"
                style={{ backgroundColor: branding.primary_colour }}
              >
                {(branding.dark_logo_url || branding.logo_url) ? (
                  <img
                    src={branding.dark_logo_url || branding.logo_url || ''}
                    alt={branding.platform_name}
                    className="h-8 w-8 rounded object-contain bg-white/20"
                  />
                ) : (
                  <div className="h-8 w-8 rounded bg-white/20 flex items-center justify-center text-white text-sm font-bold">
                    {branding.platform_name.charAt(0).toUpperCase()}
                  </div>
                )}
                <span className="text-white font-semibold text-sm truncate">
                  {branding.platform_name}
                </span>
              </div>

              {/* Body preview */}
              <div className="p-6 text-center bg-card">
                {branding.logo_url && (
                  <img
                    src={branding.logo_url}
                    alt=""
                    className="h-12 mx-auto mb-3 object-contain"
                  />
                )}
                <p className="text-xl font-bold" style={{ color: branding.primary_colour }}>
                  {branding.platform_name}
                </p>
                <p className="text-xs mt-1" style={{ color: branding.secondary_colour }}>
                  Powered by {branding.platform_name}
                </p>
              </div>

              {/* Favicon preview */}
              {branding.favicon_url && (
                <div className="px-4 py-3 border-t border-border flex items-center gap-2">
                  <img
                    src={branding.favicon_url}
                    alt="Favicon"
                    className="h-4 w-4 object-contain"
                  />
                  <span className="text-xs text-muted">Favicon preview</span>
                </div>
              )}

              {/* Footer preview */}
              <div className="px-4 py-3 bg-canvas border-t border-border text-center">
                <p className="text-xs text-muted">
                  {branding.website_url && (
                    <span className="mr-3">{branding.website_url}</span>
                  )}
                  {branding.support_email && (
                    <span>{branding.support_email}</span>
                  )}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
