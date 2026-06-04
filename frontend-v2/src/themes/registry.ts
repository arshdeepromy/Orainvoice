/** Theme registry — add new themes here.
 *
 * Each theme needs a matching [data-theme="<id>"] block in
 * frontend/src/styles/themes.css defining the CSS custom properties.
 */

export interface ThemeDefinition {
  id: string
  label: string
  description: string
  previewColors: {
    sidebar: string
    primary: string
    content: string
  }
}

export const THEMES: ThemeDefinition[] = [
  {
    id: 'classic',
    label: 'Classic',
    description: 'Clean white sidebar with blue accents — the original look.',
    previewColors: {
      sidebar: '#ffffff',
      primary: '#2563eb',
      content: '#f9fafb',
    },
  },
  {
    id: 'violet',
    label: 'Violet',
    description: 'Dark indigo sidebar with purple accents — modern and bold.',
    previewColors: {
      sidebar: '#1e1b4b',
      primary: '#7c3aed',
      content: '#f8fafc',
    },
  },
]

export const DEFAULT_THEME = 'classic'

export function getTheme(id: string): ThemeDefinition | undefined {
  return THEMES.find(t => t.id === id)
}
