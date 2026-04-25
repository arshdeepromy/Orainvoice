import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { PullRefresh } from '../PullRefresh'

describe('PullRefresh', () => {
  it('renders children', () => {
    render(
      <PullRefresh onRefresh={vi.fn().mockResolvedValue(undefined)} isRefreshing={false}>
        <div>List content</div>
      </PullRefresh>,
    )
    expect(screen.getByText('List content')).toBeInTheDocument()
  })

  it('shows spinner when isRefreshing is true', () => {
    render(
      <PullRefresh onRefresh={vi.fn().mockResolvedValue(undefined)} isRefreshing={true}>
        <div>List content</div>
      </PullRefresh>,
    )
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('does not show spinner when not refreshing and not pulling', () => {
    render(
      <PullRefresh onRefresh={vi.fn().mockResolvedValue(undefined)} isRefreshing={false}>
        <div>List content</div>
      </PullRefresh>,
    )
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('has scrollable container', () => {
    const { container } = render(
      <PullRefresh onRefresh={vi.fn().mockResolvedValue(undefined)} isRefreshing={false}>
        <div>Content</div>
      </PullRefresh>,
    )
    const scrollContainer = container.querySelector('.overflow-y-auto')
    expect(scrollContainer).toBeInTheDocument()
  })

  it('accepts custom threshold prop', () => {
    // Just verifying it renders without error with custom threshold
    const { container } = render(
      <PullRefresh
        onRefresh={vi.fn().mockResolvedValue(undefined)}
        isRefreshing={false}
        threshold={100}
      >
        <div>Content</div>
      </PullRefresh>,
    )
    expect(container).toBeTruthy()
  })
})
