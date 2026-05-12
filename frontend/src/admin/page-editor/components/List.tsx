/**
 * List — bullet or numbered list of text items.
 */
import type { ComponentConfig } from '@puckeditor/core'

export interface ListItem {
  text: string
}

export interface ListProps {
  style: 'bullet' | 'numbered'
  items: ListItem[]
}

export const ListComponent: ComponentConfig<ListProps> = {
  label: 'List',
  fields: {
    style: {
      type: 'radio',
      label: 'Style',
      options: [
        { label: 'Bullet', value: 'bullet' },
        { label: 'Numbered', value: 'numbered' },
      ],
    },
    items: {
      type: 'array',
      label: 'Items',
      arrayFields: {
        text: { type: 'text', label: 'Item text' },
      },
      defaultItemProps: { text: 'List item' },
      getItemSummary: (item) => item.text || 'Item',
    },
  },
  defaultProps: {
    style: 'bullet',
    items: [{ text: 'First item' }, { text: 'Second item' }, { text: 'Third item' }],
  },
  render: ({ style, items }) => {
    const safeItems = items ?? []
    if (safeItems.length === 0) return <></>
    const className = 'space-y-2 text-base leading-relaxed text-gray-700'
    if (style === 'numbered') {
      return (
        <ol className={`list-decimal pl-6 ${className}`}>
          {safeItems.map((item, idx) => (
            <li key={idx}>{item.text}</li>
          ))}
        </ol>
      )
    }
    return (
      <ul className={`list-disc pl-6 ${className}`}>
        {safeItems.map((item, idx) => (
          <li key={idx}>{item.text}</li>
        ))}
      </ul>
    )
  },
}
