import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { DragDrop } from '../DragDrop'
import type { DragDropItem, DragDropColumnConfig } from '../DragDrop'

interface TestItem extends DragDropItem {
  title: string
}

const columns: DragDropColumnConfig[] = [
  { id: 'todo', label: 'To Do', color: 'bg-gray-400' },
  { id: 'in-progress', label: 'In Progress', color: 'bg-blue-400' },
  { id: 'done', label: 'Done', color: 'bg-green-400' },
]

const items: TestItem[] = [
  { id: '1', columnId: 'todo', title: 'Task A' },
  { id: '2', columnId: 'todo', title: 'Task B' },
  { id: '3', columnId: 'in-progress', title: 'Task C' },
]

const renderItem = (item: TestItem, isDragging: boolean) => (
  <div data-testid={`item-${item.id}`} className={isDragging ? 'dragging' : ''}>
    {item.title}
  </div>
)

describe('DragDrop', () => {
  it('renders all columns', () => {
    render(
      <DragDrop
        columns={columns}
        items={items}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    expect(screen.getByText('To Do')).toBeInTheDocument()
    expect(screen.getByText('In Progress')).toBeInTheDocument()
    expect(screen.getByText('Done')).toBeInTheDocument()
  })

  it('renders items in their respective columns', () => {
    render(
      <DragDrop
        columns={columns}
        items={items}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    expect(screen.getByText('Task A')).toBeInTheDocument()
    expect(screen.getByText('Task B')).toBeInTheDocument()
    expect(screen.getByText('Task C')).toBeInTheDocument()
  })

  it('shows item count per column', () => {
    render(
      <DragDrop
        columns={columns}
        items={items}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    // To Do has 2 items, In Progress has 1, Done has 0
    const counts = screen.getAllByText(/^[0-3]$/)
    expect(counts.length).toBeGreaterThanOrEqual(3)
  })

  it('shows empty state for columns with no items', () => {
    render(
      <DragDrop
        columns={columns}
        items={items}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    expect(screen.getByText('No items')).toBeInTheDocument()
  })

  it('has accessible kanban board label', () => {
    render(
      <DragDrop
        columns={columns}
        items={items}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    expect(screen.getByRole('group', { name: 'Kanban board' })).toBeInTheDocument()
  })

  it('has accessible column labels', () => {
    render(
      <DragDrop
        columns={columns}
        items={items}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    expect(screen.getByRole('region', { name: 'To Do column' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'In Progress column' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Done column' })).toBeInTheDocument()
  })

  it('renders with empty items array', () => {
    render(
      <DragDrop
        columns={columns}
        items={[]}
        renderItem={renderItem}
        onDrop={vi.fn()}
      />,
    )
    const emptyMessages = screen.getAllByText('No items')
    expect(emptyMessages).toHaveLength(3)
  })
})
