/**
 * Locale context providing i18n support throughout the app.
 *
 * Provides:
 * - useLocale() — current locale, direction, and setLocale
 * - useTranslation() — translation function t(key, vars?)
 * - LocaleProvider — wraps the app to provide locale state
 *
 * @validates Requirement 32
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
} from 'react'
import type { ReactNode } from 'react'
import {
  getTranslations,
  getDirection,
  isRtl,
  SUPPORTED_LOCALES,
  LOCALE_NAMES,
  type SupportedLocale,
} from '@/i18n'

interface LocaleContextValue {
  locale: SupportedLocale
  direction: 'ltr' | 'rtl'
  isRtl: boolean
  setLocale: (locale: SupportedLocale) => void
  supportedLocales: readonly string[]
  localeNames: Record<string, string>
}

interface TranslationContextValue {
  t: (key: string, vars?: Record<string, string>) => string
  translations: Record<string, string>
}

const LocaleContext = createContext<LocaleContextValue | null>(null)
const TranslationContext = createContext<TranslationContextValue | null>(null)

const LOCALE_STORAGE_KEY = 'orainvoice_locale'

function getInitialLocale(): SupportedLocale {
  try {
    const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
    if (stored && (SUPPORTED_LOCALES as readonly string[]).includes(stored)) {
      return stored as SupportedLocale
    }
  } catch {
    // localStorage not available
  }
  return 'en'
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext)
  if (!ctx) throw new Error('useLocale must be used within LocaleProvider')
  return ctx
}

export function useTranslation(): TranslationContextValue {
  const ctx = useContext(TranslationContext)
  if (!ctx) throw new Error('useTranslation must be used within LocaleProvider')
  return ctx
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<SupportedLocale>(getInitialLocale)

  const setLocale = useCallback((newLocale: SupportedLocale) => {
    setLocaleState(newLocale)
    try {
      localStorage.setItem(LOCALE_STORAGE_KEY, newLocale)
    } catch {
      // localStorage not available
    }
  }, [])

  // Update document direction and lang attribute when locale changes
  useEffect(() => {
    const dir = getDirection(locale)
    document.documentElement.setAttribute('dir', dir)
    document.documentElement.setAttribute('lang', locale)
  }, [locale])

  const localeValue = useMemo<LocaleContextValue>(
    () => ({
      locale,
      direction: getDirection(locale),
      isRtl: isRtl(locale),
      setLocale,
      supportedLocales: SUPPORTED_LOCALES,
      localeNames: LOCALE_NAMES,
    }),
    [locale, setLocale],
  )

  const translations = useMemo(() => getTranslations(locale), [locale])
  const enTranslations = useMemo(() => getTranslations('en'), [])

  const t = useCallback(
    (key: string, vars?: Record<string, string>): string => {
      let value = translations[key] ?? enTranslations[key] ?? key

      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          value = value.replace(new RegExp(`\\{${k}\\}`, 'g'), v)
        }
      }

      return value
    },
    [translations, enTranslations],
  )

  const translationValue = useMemo<TranslationContextValue>(
    () => ({ t, translations }),
    [t, translations],
  )

  return (
    <LocaleContext.Provider value={localeValue}>
      <TranslationContext.Provider value={translationValue}>
        {children}
      </TranslationContext.Provider>
    </LocaleContext.Provider>
  )
}
