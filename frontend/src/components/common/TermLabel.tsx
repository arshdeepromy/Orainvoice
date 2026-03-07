import { useTerm } from '@/contexts/TerminologyContext'

interface TermLabelProps {
  /** The terminology key to look up (e.g. 'asset_label', 'work_unit_label') */
  termKey: string
  /** Fallback text if the term is not found */
  fallback: string
  /** Optional HTML element to render as (defaults to span) */
  as?: keyof JSX.IntrinsicElements
  /** Optional className */
  className?: string
}

export function TermLabel({
  termKey,
  fallback,
  as: Component = 'span',
  className,
}: TermLabelProps) {
  const label = useTerm(termKey, fallback)
  return <Component className={className}>{label}</Component>
}
