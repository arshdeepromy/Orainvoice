/**
 * TranslatedText — renders a translated string using the current locale.
 *
 * Usage:
 *   <TranslatedText tKey="common.save" />
 *   <TranslatedText tKey="email.invoice_subject" vars={{ invoice_number: "INV-001" }} />
 *
 * @validates Requirement 32
 */

import { useTranslation } from '@/contexts/LocaleContext'
import type { ElementType } from 'react'

interface TranslatedTextProps {
  tKey: string
  vars?: Record<string, string>
  as?: ElementType
  className?: string
}

export function TranslatedText({
  tKey,
  vars,
  as: Component = 'span',
  className,
}: TranslatedTextProps) {
  const { t } = useTranslation()
  return <Component className={className}>{t(tKey, vars)}</Component>
}

export default TranslatedText
