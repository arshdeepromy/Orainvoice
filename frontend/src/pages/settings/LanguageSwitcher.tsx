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
    <div className="rounded-lg border border-gray-200 bg-white p-6" dir={direction}>
      <h3 className="text-lg font-medium text-gray-900 mb-1">
        {t('settings.language')}
      </h3>
      <p className="text-sm text-gray-500 mb-4">
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
                flex flex-col items-center justify-center rounded-lg border-2 p-3
                transition-colors duration-150
                ${isSelected
                  ? 'border-blue-500 bg-blue-50 text-blue-700'
                  : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300 hover:bg-gray-50'
                }
              `}
              aria-pressed={isSelected}
              aria-label={`Select ${LOCALE_NAMES[loc as SupportedLocale]} language`}
            >
              <span className="text-sm font-medium">
                {LOCALE_NAMES[loc as SupportedLocale]}
              </span>
              <span className="text-xs text-gray-400 mt-0.5 uppercase">
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
