/**
 * Language switcher component for user settings.
 *
 * Allows users to select their preferred language from the 10 supported
 * locales. Updates the locale context and persists the choice to localStorage.
 *
 * @validates Requirement 32
 */

import { useLocale, useTranslation } from '@/contexts/LocaleContext'
import { LOCALE_NAMES, type SupportedLocale } from '@/i18n'

export function LanguageSwitcher() {
  const { locale, setLocale, supportedLocales, direction } = useLocale()
  const { t } = useTranslation()

  return (
    <div className="rounded-card border border-border bg-card p-6" dir={direction}>
      <h3 className="text-lg font-medium text-text mb-1">
        {t('settings.language')}
      </h3>
      <p className="text-sm text-muted-2 mb-4">
        {t('settings.language_description')}
      </p>

      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {supportedLocales.map((loc) => {
          const isSelected = loc === locale
          return (
            <button
              key={loc}
              type="button"
              onClick={() => setLocale(loc as SupportedLocale)}
              className={`
                flex flex-col items-center justify-center rounded-ctl border-2 p-3
                transition-colors duration-150
                ${isSelected
                  ? 'border-accent bg-accent-soft text-accent'
                  : 'border-border bg-card text-muted hover:border-border-strong hover:bg-canvas'
                }
              `}
              aria-pressed={isSelected}
              aria-label={`Select ${LOCALE_NAMES[loc as SupportedLocale]} language`}
            >
              <span className="text-sm font-medium">
                {LOCALE_NAMES[loc as SupportedLocale]}
              </span>
              <span className="text-xs text-muted-2 mt-0.5 uppercase">
                {loc}
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default LanguageSwitcher
