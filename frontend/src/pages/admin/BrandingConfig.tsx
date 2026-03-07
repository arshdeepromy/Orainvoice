import React, { useEffect, useState } from 'react'
import apiClient from '@/api/client'

/**
 * Validates: Requirement 1 — Platform Rebranding
 * Global Admin branding configuration page.
 */

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
  created_at: string
  updated_at: string
}

export function BrandingConfig() {
  const [branding, setBranding] = useState<PlatformBranding | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    apiClient
      .get('/admin/branding')
      .then((res) => {
        setBranding(res.data)
        setLoading(false)
      })
      .catch(() => {
        setError('Could not load branding configuration')
        setLoading(false)
      })
  }, [])

  const handleChange = (field: keyof PlatformBranding, value: string | boolean) => {
    if (!branding) return
    setBranding({ ...branding, [field]: value })
    setSaved(false)
  }

  const handleSave = async () => {
    if (!branding) return
    setSaving(true)
    setSaved(false)
    try {
      const res = await apiClient.put('/admin/branding', {
        platform_name: branding.platform_name,
        logo_url: branding.logo_url,
        primary_colour: branding.primary_colour,
        secondary_colour: branding.secondary_colour,
        website_url: branding.website_url,
        signup_url: branding.signup_url,
        support_email: branding.support_email,
        terms_url: branding.terms_url,
        auto_detect_domain: branding.auto_detect_domain,
      })
      setBranding(res.data)
      setSaved(true)
    } catch {
      setError('Failed to save branding')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div role="status" aria-label="loading branding">
        Loading branding configuration…
      </div>
    )
  }

  if (error && !branding) {
    return <div role="alert">{error}</div>
  }

  if (!branding) return null

  return (
    <div>
      <h1>Platform Branding</h1>
      {error && <div role="alert">{error}</div>}
      {saved && <div role="status">Branding saved successfully</div>}

      <div>
        <label htmlFor="platform_name">Platform name</label>
        <input
          id="platform_name"
          value={branding.platform_name}
          onChange={(e) => handleChange('platform_name', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="logo_url">Logo URL</label>
        <input
          id="logo_url"
          value={branding.logo_url || ''}
          onChange={(e) => handleChange('logo_url', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="primary_colour">Primary colour</label>
        <input
          id="primary_colour"
          type="color"
          value={branding.primary_colour}
          onChange={(e) => handleChange('primary_colour', e.target.value)}
        />
        <span>{branding.primary_colour}</span>
      </div>

      <div>
        <label htmlFor="secondary_colour">Secondary colour</label>
        <input
          id="secondary_colour"
          type="color"
          value={branding.secondary_colour}
          onChange={(e) => handleChange('secondary_colour', e.target.value)}
        />
        <span>{branding.secondary_colour}</span>
      </div>

      <div>
        <label htmlFor="signup_url">Signup URL</label>
        <input
          id="signup_url"
          value={branding.signup_url || ''}
          onChange={(e) => handleChange('signup_url', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="website_url">Website URL</label>
        <input
          id="website_url"
          value={branding.website_url || ''}
          onChange={(e) => handleChange('website_url', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="support_email">Support email</label>
        <input
          id="support_email"
          value={branding.support_email || ''}
          onChange={(e) => handleChange('support_email', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="terms_url">Terms URL</label>
        <input
          id="terms_url"
          value={branding.terms_url || ''}
          onChange={(e) => handleChange('terms_url', e.target.value)}
        />
      </div>

      <div>
        <label htmlFor="auto_detect_domain">
          <input
            id="auto_detect_domain"
            type="checkbox"
            checked={branding.auto_detect_domain}
            onChange={(e) => handleChange('auto_detect_domain', e.target.checked)}
          />
          Auto-detect domain for white-label
        </label>
      </div>

      <div style={{ marginTop: 16 }}>
        <h2>Preview</h2>
        <div
          role="region"
          aria-label="branding preview"
          style={{
            padding: 16,
            border: '1px solid #e5e7eb',
            borderRadius: 8,
            textAlign: 'center',
          }}
        >
          {branding.logo_url && (
            <img
              src={branding.logo_url}
              alt={branding.platform_name}
              style={{ height: 40, marginBottom: 8 }}
            />
          )}
          <div style={{ fontSize: 20, fontWeight: 700, color: branding.primary_colour }}>
            {branding.platform_name}
          </div>
          <div style={{ fontSize: 12, color: branding.secondary_colour }}>
            Powered by {branding.platform_name}
          </div>
        </div>
      </div>

      <button onClick={handleSave} disabled={saving} style={{ marginTop: 16 }}>
        {saving ? 'Saving…' : 'Save branding'}
      </button>
    </div>
  )
}
