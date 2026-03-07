/**
 * I18n configuration and translation loading.
 *
 * Provides a lightweight i18n system compatible with React hooks.
 * Translations are loaded from JSON files matching the backend's
 * app/i18n/ directory structure.
 *
 * Supported locales: en, mi, fr, es, de, pt, zh, ja, ar, hi
 *
 * @validates Requirement 32
 */

import en from './locales/en.json'
import mi from './locales/mi.json'
import fr from './locales/fr.json'
import es from './locales/es.json'
import de from './locales/de.json'
import pt from './locales/pt.json'
import zh from './locales/zh.json'
import ja from './locales/ja.json'
import ar from './locales/ar.json'
import hi from './locales/hi.json'

export const SUPPORTED_LOCALES = [
  'en', 'mi', 'fr', 'es', 'de', 'pt', 'zh', 'ja', 'ar', 'hi',
] as const

export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number]

export const RTL_LOCALES: ReadonlySet<string> = new Set(['ar'])

export const LOCALE_NAMES: Record<SupportedLocale, string> = {
  en: 'English',
  mi: 'Te Reo Māori',
  fr: 'Français',
  es: 'Español',
  de: 'Deutsch',
  pt: 'Português',
  zh: '简体中文',
  ja: '日本語',
  ar: 'العربية',
  hi: 'हिन्दी',
}

type TranslationMap = Record<string, string>

const translations: Record<string, TranslationMap> = {
  en, mi, fr, es, de, pt, zh, ja, ar, hi,
}

export function getTranslations(locale: string): TranslationMap {
  return translations[locale] ?? translations.en
}

export function t(key: string, locale: string = 'en', vars?: Record<string, string>): string {
  const map = getTranslations(locale)
  let value = map[key] ?? translations.en[key] ?? key

  if (vars) {
    for (const [k, v] of Object.entries(vars)) {
      value = value.replace(new RegExp(`\\{${k}\\}`, 'g'), v)
    }
  }

  return value
}

export function isRtl(locale: string): boolean {
  return RTL_LOCALES.has(locale)
}

export function getDirection(locale: string): 'ltr' | 'rtl' {
  return isRtl(locale) ? 'rtl' : 'ltr'
}

export default translations
