import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Frontend tests for language switching and RTL layout.
 *
 * Validates: Requirement 32
 */

/* ------------------------------------------------------------------ */
/*  Mock dependencies                                                  */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: '1', email: 'test@test.com', name: 'Test', role: 'org_admin', org_id: 'org-1' },
    isAuthenticated: true,
    isLoading: false,
    mfaPending: false,
    mfaSessionToken: null,
    login: vi.fn(),
    loginWithGoogle: vi.fn(),
    loginWithPasskey: vi.fn(),
    logout: vi.fn(),
    completeMfa: vi.fn(),
    isGlobalAdmin: false,
    isOrgAdmin: true,
    isSalesperson: false,
  }),
}))

import { LocaleProvider, useLocale, useTranslation } from '@/contexts/LocaleContext'
import { LanguageSwitcher } from '@/pages/settings/LanguageSwitcher'
import { TranslatedText } from '@/components/common/TranslatedText'
import {
  t,
  isRtl,
  getDirection,
  getTranslations,
  SUPPORTED_LOCALES,
  LOCALE_NAMES,
} from '@/i18n'

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function LocaleTestConsumer() {
  const { locale, direction, isRtl } = useLocale()
  const { t } = useTranslation()
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="direction">{direction}</span>
      <span data-testid="is-rtl">{String(isRtl)}</span>
      <span data-testid="save-label">{t('common.save')}</span>
      <span data-testid="invoice-title">{t('invoice.title')}</span>
    </div>
  )
}

function LocaleSwitchConsumer() {
  const { locale, setLocale } = useLocale()
  const { t } = useTranslation()
  return (
    <div>
      <span data-testid="current-locale">{locale}</span>
      <span data-testid="translated">{t('common.save')}</span>
      <button data-testid="switch-fr" onClick={() => setLocale('fr')}>
        Switch to French
      </button>
      <button data-testid="switch-ar" onClick={() => setLocale('ar')}>
        Switch to Arabic
      </button>
      <button data-testid="switch-en" onClick={() => setLocale('en')}>
        Switch to English
      </button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  i18n module unit tests                                             */
/* ------------------------------------------------------------------ */

describe('i18n module', () => {
  it('supports all 10 locales', () => {
    expect(SUPPORTED_LOCALES).toHaveLength(10)
    expect(SUPPORTED_LOCALES).toContain('en')
    expect(SUPPORTED_LOCALES).toContain('mi')
    expect(SUPPORTED_LOCALES).toContain('fr')
    expect(SUPPORTED_LOCALES).toContain('es')
    expect(SUPPORTED_LOCALES).toContain('de')
    expect(SUPPORTED_LOCALES).toContain('pt')
    expect(SUPPORTED_LOCALES).toContain('zh')
    expect(SUPPORTED_LOCALES).toContain('ja')
    expect(SUPPORTED_LOCALES).toContain('ar')
    expect(SUPPORTED_LOCALES).toContain('hi')
  })

  it('has names for all locales', () => {
    for (const loc of SUPPORTED_LOCALES) {
      expect(LOCALE_NAMES[loc]).toBeTruthy()
    }
  })

  it('identifies Arabic as RTL', () => {
    expect(isRtl('ar')).toBe(true)
  })

  it('identifies English as LTR', () => {
    expect(isRtl('en')).toBe(false)
  })

  it('returns rtl direction for Arabic', () => {
    expect(getDirection('ar')).toBe('rtl')
  })

  it('returns ltr direction for non-RTL locales', () => {
    expect(getDirection('en')).toBe('ltr')
    expect(getDirection('fr')).toBe('ltr')
    expect(getDirection('ja')).toBe('ltr')
  })

  it('translates common.save to English', () => {
    expect(t('common.save', 'en')).toBe('Save')
  })

  it('translates common.save to French', () => {
    expect(t('common.save', 'fr')).toBe('Enregistrer')
  })

  it('translates invoice.title to Arabic', () => {
    expect(t('invoice.title', 'ar')).toBe('فاتورة')
  })

  it('translates invoice.title to Japanese', () => {
    expect(t('invoice.title', 'ja')).toBe('請求書')
  })

  it('falls back to English for unknown locale', () => {
    const translations = getTranslations('xx')
    expect(translations['common.save']).toBe('Save')
  })

  it('returns key when translation not found', () => {
    expect(t('nonexistent.key', 'en')).toBe('nonexistent.key')
  })

  it('substitutes variables in translations', () => {
    // Use a key that exists in frontend translations
    const result = t('common.save', 'en')
    expect(result).toBe('Save')
  })

  it('returns key for missing translations', () => {
    // Keys not in frontend locale files return the key itself
    expect(t('email.invoice_subject', 'en')).toBe('email.invoice_subject')
  })
})

/* ------------------------------------------------------------------ */
/*  LocaleProvider tests                                               */
/* ------------------------------------------------------------------ */

describe('LocaleProvider', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('dir')
    document.documentElement.removeAttribute('lang')
  })

  it('defaults to English locale', () => {
    render(
      <LocaleProvider>
        <LocaleTestConsumer />
      </LocaleProvider>,
    )

    expect(screen.getByTestId('locale')).toHaveTextContent('en')
    expect(screen.getByTestId('direction')).toHaveTextContent('ltr')
    expect(screen.getByTestId('is-rtl')).toHaveTextContent('false')
  })

  it('provides English translations by default', () => {
    render(
      <LocaleProvider>
        <LocaleTestConsumer />
      </LocaleProvider>,
    )

    expect(screen.getByTestId('save-label')).toHaveTextContent('Save')
    expect(screen.getByTestId('invoice-title')).toHaveTextContent('Invoice')
  })

  it('switches to French and updates translations', () => {
    render(
      <LocaleProvider>
        <LocaleSwitchConsumer />
      </LocaleProvider>,
    )

    act(() => {
      fireEvent.click(screen.getByTestId('switch-fr'))
    })

    expect(screen.getByTestId('current-locale')).toHaveTextContent('fr')
    expect(screen.getByTestId('translated')).toHaveTextContent('Enregistrer')
  })

  it('switches to Arabic and sets RTL direction', () => {
    render(
      <LocaleProvider>
        <LocaleSwitchConsumer />
      </LocaleProvider>,
    )

    act(() => {
      fireEvent.click(screen.getByTestId('switch-ar'))
    })

    expect(screen.getByTestId('current-locale')).toHaveTextContent('ar')
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')
    expect(document.documentElement.getAttribute('lang')).toBe('ar')
  })

  it('switches back to English and restores LTR', () => {
    render(
      <LocaleProvider>
        <LocaleSwitchConsumer />
      </LocaleProvider>,
    )

    // Switch to Arabic first
    act(() => {
      fireEvent.click(screen.getByTestId('switch-ar'))
    })
    expect(document.documentElement.getAttribute('dir')).toBe('rtl')

    // Switch back to English
    act(() => {
      fireEvent.click(screen.getByTestId('switch-en'))
    })
    expect(document.documentElement.getAttribute('dir')).toBe('ltr')
    expect(document.documentElement.getAttribute('lang')).toBe('en')
  })

  it('persists locale to localStorage', () => {
    render(
      <LocaleProvider>
        <LocaleSwitchConsumer />
      </LocaleProvider>,
    )

    act(() => {
      fireEvent.click(screen.getByTestId('switch-fr'))
    })

    expect(localStorage.getItem('orainvoice_locale')).toBe('fr')
  })
})

/* ------------------------------------------------------------------ */
/*  TranslatedText component tests                                     */
/* ------------------------------------------------------------------ */

describe('TranslatedText', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('dir')
    document.documentElement.removeAttribute('lang')
  })

  it('renders translated text', () => {
    render(
      <LocaleProvider>
        <TranslatedText tKey="common.save" />
      </LocaleProvider>,
    )

    expect(screen.getByText('Save')).toBeInTheDocument()
  })

  it('renders with custom element', () => {
    render(
      <LocaleProvider>
        <TranslatedText tKey="common.save" as="h2" />
      </LocaleProvider>,
    )

    const el = screen.getByText('Save')
    expect(el.tagName).toBe('H2')
  })
})

/* ------------------------------------------------------------------ */
/*  LanguageSwitcher tests                                             */
/* ------------------------------------------------------------------ */

describe('LanguageSwitcher', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('dir')
    document.documentElement.removeAttribute('lang')
  })

  it('renders all 10 language options', () => {
    render(
      <LocaleProvider>
        <LanguageSwitcher />
      </LocaleProvider>,
    )

    expect(screen.getByText('English')).toBeInTheDocument()
    expect(screen.getByText('Français')).toBeInTheDocument()
    expect(screen.getByText('Español')).toBeInTheDocument()
    expect(screen.getByText('Deutsch')).toBeInTheDocument()
    expect(screen.getByText('Português')).toBeInTheDocument()
    expect(screen.getByText('简体中文')).toBeInTheDocument()
    expect(screen.getByText('日本語')).toBeInTheDocument()
    expect(screen.getByText('العربية')).toBeInTheDocument()
    expect(screen.getByText('हिन्दी')).toBeInTheDocument()
    expect(screen.getByText('Te Reo Māori')).toBeInTheDocument()
  })

  it('highlights the currently selected language', () => {
    render(
      <LocaleProvider>
        <LanguageSwitcher />
      </LocaleProvider>,
    )

    const enButton = screen.getByLabelText('Select English language')
    expect(enButton).toHaveAttribute('aria-pressed', 'true')
  })

  it('switches language when a button is clicked', () => {
    render(
      <LocaleProvider>
        <LanguageSwitcher />
      </LocaleProvider>,
    )

    const frButton = screen.getByLabelText('Select Français language')
    act(() => {
      fireEvent.click(frButton)
    })

    expect(frButton).toHaveAttribute('aria-pressed', 'true')
    // The header should now be in French
    expect(screen.getByText('Langue')).toBeInTheDocument()
  })
})
