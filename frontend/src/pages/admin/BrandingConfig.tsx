import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { Spinner } from '@/components/ui/Spinner'
import { AlertBanner } from '@/components/ui/AlertBanner'
import { ToastContainer, useToast } from '@/components/ui/Toast'
import apiClient from '@/api/client'
import { THEMES } from '@/themes/registry'

export interface PlatformBranding {
  id: string
  platform_name: string
  logo_url: string | null
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
        <h1 className="text-2xl font-semibold text-gray-900">Platform Branding</h1>
        <Badge variant="info">Global</Badge>
      </div>
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Form */}
        <div className="lg:col-span-2 space-y-6">
          {/* Identity */}
          <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Identity</h2>
            <Input
              label="Platform name"
              id="platform_name"
              value={branding.platform_name}
              onChange={(e) => handleChange('platform_name', e.target.value)}
            />
            <Input
              label="Logo URL"
              id="logo_url"
              value={branding.logo_url || ''}
              onChange={(e) => handleChange('logo_url', e.target.value)}
              placeholder="https://example.com/logo.png"
            />
          </section>

          {/* Colours */}
          <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Colours</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label htmlFor="primary_colour" className="block text-sm font-medium text-gray-700 mb-1">
                  Primary colour
                </label>
                <div className="flex items-center gap-3">
                  <input
                    id="primary_colour"
                    type="color"
                    value={branding.primary_colour}
                    onChange={(e) => handleChange('primary_colour', e.target.value)}
                    className="h-10 w-14 rounded border border-gray-300 cursor-pointer p-0.5"
                  />
                  <span className="text-sm font-mono text-gray-600">{branding.primary_colour}</span>
                </div>
              </div>
              <div>
                <label htmlFor="secondary_colour" className="block text-sm font-medium text-gray-700 mb-1">
                  Secondary colour
                </label>
                <div className="flex items-center gap-3">
                  <input
                    id="secondary_colour"
                    type="color"
                    value={branding.secondary_colour}
                    onChange={(e) => handleChange('secondary_colour', e.target.value)}
                    className="h-10 w-14 rounded border border-gray-300 cursor-pointer p-0.5"
                  />
                  <span className="text-sm font-mono text-gray-600">{branding.secondary_colour}</span>
                </div>
              </div>
            </div>
          </section>

          {/* URLs & Contact */}
          <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">URLs &amp; Contact</h2>
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
          <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Platform Theme</h2>
            <p className="text-sm text-gray-500">Choose the visual theme applied across the entire platform. Changes take effect on next page load for all users.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {THEMES.map((theme) => {
                const isSelected = (branding.platform_theme || 'classic') === theme.id
                return (
                  <button
                    key={theme.id}
                    type="button"
                    onClick={() => handleChange('platform_theme', theme.id)}
                    className={`relative flex items-start gap-4 rounded-xl border-2 p-4 text-left transition-all ${
                      isSelected
                        ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                        : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  >
                    {/* Color swatch preview */}
                    <div className="flex flex-col gap-1 shrink-0">
                      <div
                        className="h-10 w-10 rounded-lg shadow-sm border border-gray-200"
                        style={{ backgroundColor: theme.previewColors.sidebar }}
                      />
                      <div
                        className="h-3 w-10 rounded-full"
                        style={{ backgroundColor: theme.previewColors.primary }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-gray-900">{theme.label}</span>
                        {isSelected && (
                          <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-700">Active</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5">{theme.description}</p>
                    </div>
                  </button>
                )
              })}
            </div>
          </section>

          {/* Options */}
          <section className="rounded-lg border border-gray-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Options</h2>
            <label htmlFor="auto_detect_domain" className="flex items-center gap-3 cursor-pointer">
              <input
                id="auto_detect_domain"
                type="checkbox"
                checked={branding.auto_detect_domain}
                onChange={(e) => handleChange('auto_detect_domain', e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm text-gray-700">Auto-detect domain for white-label branding</span>
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
            <h2 className="text-lg font-semibold text-gray-900 mb-3">Preview</h2>
            <div
              role="region"
              aria-label="branding preview"
              className="rounded-lg border border-gray-200 bg-white overflow-hidden"
            >
              {/* Header preview */}
              <div
                className="flex items-center gap-3 px-4 py-3"
                style={{ backgroundColor: branding.primary_colour }}
              >
                {branding.logo_url ? (
                  <img
                    src={branding.logo_url}
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
              <div className="p-6 text-center bg-white">
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

              {/* Footer preview */}
              <div className="px-4 py-3 bg-gray-50 border-t border-gray-200 text-center">
                <p className="text-xs text-gray-500">
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
