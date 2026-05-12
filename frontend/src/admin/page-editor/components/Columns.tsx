/**
 * Columns — 1/2/3/4 column layout with configurable gap. Each column is
 * a Puck slot so arbitrary components can be dropped inside.
 */
import type { ComponentConfig, Slot } from '@puckeditor/core'

export type ColumnCount = 1 | 2 | 3 | 4
export type ColumnGap = 'sm' | 'md' | 'lg'

export interface ColumnsProps {
  columns: ColumnCount
  gap: ColumnGap
  column1: Slot
  column2: Slot
  column3: Slot
  column4: Slot
}

const GRID_CLASSES: Record<ColumnCount, string> = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 md:grid-cols-2',
  3: 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3',
  4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4',
}

const GAP_CLASSES: Record<ColumnGap, string> = {
  sm: 'gap-4',
  md: 'gap-6',
  lg: 'gap-10',
}

export const ColumnsComponent: ComponentConfig<ColumnsProps> = {
  label: 'Columns',
  fields: {
    columns: {
      type: 'select',
      label: 'Column count',
      options: [
        { label: '1 column', value: 1 },
        { label: '2 columns', value: 2 },
        { label: '3 columns', value: 3 },
        { label: '4 columns', value: 4 },
      ],
    },
    gap: {
      type: 'select',
      label: 'Gap',
      options: [
        { label: 'Small', value: 'sm' },
        { label: 'Medium', value: 'md' },
        { label: 'Large', value: 'lg' },
      ],
    },
    column1: { type: 'slot' },
    column2: { type: 'slot' },
    column3: { type: 'slot' },
    column4: { type: 'slot' },
  },
  defaultProps: {
    columns: 2,
    gap: 'md',
    column1: [],
    column2: [],
    column3: [],
    column4: [],
  },
  render: ({ columns, gap, column1: C1, column2: C2, column3: C3, column4: C4 }) => {
    const gridClass = GRID_CLASSES[columns] ?? GRID_CLASSES[2]
    const gapClass = GAP_CLASSES[gap] ?? GAP_CLASSES.md
    const slots = [C1, C2, C3, C4].slice(0, columns)
    return (
      <div className={`grid ${gridClass} ${gapClass}`}>
        {slots.map((Slot, idx) => (
          <div key={idx}>
            <Slot />
          </div>
        ))}
      </div>
    )
  },
}
