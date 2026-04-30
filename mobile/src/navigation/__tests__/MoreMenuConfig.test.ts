import { describe, it, expect } from 'vitest'
import {
  MORE_MENU_ITEMS,
  CATEGORY_ORDER,
  filterMoreMenuItems,
  isMoreMenuItemVisible,
  groupByCategory,
} from '../MoreMenuConfig'
import type { MoreMenuItem } from '../MoreMenuConfig'

// ─── Helper to build a minimal item ─────────────────────────────────────────

function makeItem(overrides: Partial<MoreMenuItem> = {}): MoreMenuItem {
  return {
    id: 'test-item',
    label: 'Test',
    icon: 'M0 0',
    path: '/test',
    moduleSlug: null,
    tradeFamily: null,
    allowedRoles: [],
    adminOnly: false,
    category: 'Other',
    ...overrides,
  }
}

// ─── isMoreMenuItemVisible ──────────────────────────────────────────────────

describe('isMoreMenuItemVisible', () => {
  it('returns true for an item with no gates', () => {
    const item = makeItem()
    expect(isMoreMenuItemVisible(item, [], null, 'salesperson')).toBe(true)
  })

  it('returns false when moduleSlug is set but not in enabledModules', () => {
    const item = makeItem({ moduleSlug: 'inventory' })
    expect(isMoreMenuItemVisible(item, [], null, 'salesperson')).toBe(false)
  })

  it('returns true when moduleSlug is set and is in enabledModules', () => {
    const item = makeItem({ moduleSlug: 'inventory' })
    expect(isMoreMenuItemVisible(item, ['inventory'], null, 'salesperson')).toBe(true)
  })

  it('returns false when tradeFamily does not match', () => {
    const item = makeItem({ tradeFamily: 'automotive-transport' })
    expect(isMoreMenuItemVisible(item, [], 'food-hospitality', 'salesperson')).toBe(false)
  })

  it('returns true when tradeFamily matches', () => {
    const item = makeItem({ tradeFamily: 'automotive-transport' })
    expect(isMoreMenuItemVisible(item, [], 'automotive-transport', 'salesperson')).toBe(true)
  })

  it('returns true when tradeFamily is null (no gate)', () => {
    const item = makeItem({ tradeFamily: null })
    expect(isMoreMenuItemVisible(item, [], 'automotive-transport', 'salesperson')).toBe(true)
  })

  it('returns false when allowedRoles is set and user role is not included', () => {
    const item = makeItem({ allowedRoles: ['owner', 'admin'] })
    expect(isMoreMenuItemVisible(item, [], null, 'salesperson')).toBe(false)
  })

  it('returns true when allowedRoles includes the user role', () => {
    const item = makeItem({ allowedRoles: ['owner', 'admin'] })
    expect(isMoreMenuItemVisible(item, [], null, 'owner')).toBe(true)
  })

  it('returns true when allowedRoles is empty (no role gate)', () => {
    const item = makeItem({ allowedRoles: [] })
    expect(isMoreMenuItemVisible(item, [], null, 'technician')).toBe(true)
  })

  it('returns false when adminOnly is true and user is not admin', () => {
    const item = makeItem({ adminOnly: true, allowedRoles: ['owner', 'admin', 'org_admin'] })
    expect(isMoreMenuItemVisible(item, [], null, 'salesperson')).toBe(false)
  })

  it('returns true when adminOnly is true and user is owner', () => {
    const item = makeItem({ adminOnly: true, allowedRoles: ['owner', 'admin', 'org_admin'] })
    expect(isMoreMenuItemVisible(item, [], null, 'owner')).toBe(true)
  })

  it('returns true when adminOnly is true and user is org_admin', () => {
    const item = makeItem({ adminOnly: true, allowedRoles: ['owner', 'admin', 'org_admin'] })
    expect(isMoreMenuItemVisible(item, [], null, 'org_admin')).toBe(true)
  })

  it('requires all gates to pass (module + tradeFamily + role)', () => {
    const item = makeItem({
      moduleSlug: 'vehicles',
      tradeFamily: 'automotive-transport',
      allowedRoles: ['owner'],
    })
    // All pass
    expect(
      isMoreMenuItemVisible(item, ['vehicles'], 'automotive-transport', 'owner'),
    ).toBe(true)
    // Module fails
    expect(
      isMoreMenuItemVisible(item, [], 'automotive-transport', 'owner'),
    ).toBe(false)
    // Trade family fails
    expect(
      isMoreMenuItemVisible(item, ['vehicles'], 'food-hospitality', 'owner'),
    ).toBe(false)
    // Role fails
    expect(
      isMoreMenuItemVisible(item, ['vehicles'], 'automotive-transport', 'salesperson'),
    ).toBe(false)
  })
})

// ─── filterMoreMenuItems ────────────────────────────────────────────────────

describe('filterMoreMenuItems', () => {
  it('returns only items that pass all gates', () => {
    const items = [
      makeItem({ id: 'a', moduleSlug: 'inventory' }),
      makeItem({ id: 'b', moduleSlug: null }),
      makeItem({ id: 'c', moduleSlug: 'pos' }),
    ]
    const result = filterMoreMenuItems(items, ['inventory'], null, 'salesperson')
    expect(result.map((i) => i.id)).toEqual(['a', 'b'])
  })

  it('returns empty array when no items pass', () => {
    const items = [
      makeItem({ id: 'a', moduleSlug: 'inventory' }),
      makeItem({ id: 'b', moduleSlug: 'pos' }),
    ]
    const result = filterMoreMenuItems(items, [], null, 'salesperson')
    expect(result).toEqual([])
  })

  it('returns all items when all pass', () => {
    const items = [
      makeItem({ id: 'a' }),
      makeItem({ id: 'b' }),
    ]
    const result = filterMoreMenuItems(items, [], null, 'salesperson')
    expect(result).toHaveLength(2)
  })

  it('filters by trade family correctly', () => {
    const items = [
      makeItem({ id: 'vehicles', tradeFamily: 'automotive-transport' }),
      makeItem({ id: 'construction', tradeFamily: 'building-construction' }),
      makeItem({ id: 'general', tradeFamily: null }),
    ]
    const result = filterMoreMenuItems(items, [], 'automotive-transport', 'salesperson')
    expect(result.map((i) => i.id)).toEqual(['vehicles', 'general'])
  })

  it('filters settings to admin roles only', () => {
    const settingsItem = MORE_MENU_ITEMS.find((i) => i.id === 'settings')!
    expect(settingsItem).toBeDefined()

    const asOwner = filterMoreMenuItems([settingsItem], [], null, 'owner')
    expect(asOwner).toHaveLength(1)

    const asSalesperson = filterMoreMenuItems([settingsItem], [], null, 'salesperson')
    expect(asSalesperson).toHaveLength(0)
  })
})

// ─── groupByCategory ────────────────────────────────────────────────────────

describe('groupByCategory', () => {
  it('groups items by category in CATEGORY_ORDER', () => {
    const items = [
      makeItem({ id: 'a', category: 'Finance' }),
      makeItem({ id: 'b', category: 'Sales' }),
      makeItem({ id: 'c', category: 'Finance' }),
      makeItem({ id: 'd', category: 'Operations' }),
    ]
    const result = groupByCategory(items)
    expect(result.map(([cat]) => cat)).toEqual(['Sales', 'Operations', 'Finance'])
    expect(result[0][1].map((i) => i.id)).toEqual(['b'])
    expect(result[1][1].map((i) => i.id)).toEqual(['d'])
    expect(result[2][1].map((i) => i.id)).toEqual(['a', 'c'])
  })

  it('omits empty categories', () => {
    const items = [makeItem({ id: 'a', category: 'Account' })]
    const result = groupByCategory(items)
    expect(result).toHaveLength(1)
    expect(result[0][0]).toBe('Account')
  })

  it('returns empty array for empty input', () => {
    expect(groupByCategory([])).toEqual([])
  })

  it('preserves item order within a category', () => {
    const items = [
      makeItem({ id: 'first', category: 'Sales' }),
      makeItem({ id: 'second', category: 'Sales' }),
      makeItem({ id: 'third', category: 'Sales' }),
    ]
    const result = groupByCategory(items)
    expect(result[0][1].map((i) => i.id)).toEqual(['first', 'second', 'third'])
  })
})

// ─── MORE_MENU_ITEMS data integrity ────────────────────────────────────────

describe('MORE_MENU_ITEMS', () => {
  it('has unique IDs', () => {
    const ids = MORE_MENU_ITEMS.map((i) => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('all items have valid categories', () => {
    for (const item of MORE_MENU_ITEMS) {
      expect(CATEGORY_ORDER).toContain(item.category)
    }
  })

  it('all items have non-empty labels and paths', () => {
    for (const item of MORE_MENU_ITEMS) {
      expect(item.label.length).toBeGreaterThan(0)
      expect(item.path.length).toBeGreaterThan(0)
      expect(item.path.startsWith('/')).toBe(true)
    }
  })

  it('all items have non-empty icon paths', () => {
    for (const item of MORE_MENU_ITEMS) {
      expect(item.icon.length).toBeGreaterThan(0)
    }
  })

  it('contains expected key items', () => {
    const ids = MORE_MENU_ITEMS.map((i) => i.id)
    expect(ids).toContain('quotes')
    expect(ids).toContain('inventory')
    expect(ids).toContain('staff')
    expect(ids).toContain('vehicles')
    expect(ids).toContain('settings')
    expect(ids).toContain('reports')
    expect(ids).toContain('sms')
    expect(ids).toContain('compliance')
  })
})
