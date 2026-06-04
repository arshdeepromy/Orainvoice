/**
 * cx — tiny className-merging helper (a minimal clsx).
 *
 * `clsx`/`tailwind-merge` are NOT declared in frontend-v2's package.json
 * (clsx only exists transitively under node_modules, so importing it would be
 * relying on an undeclared dep). Per Task 11's guidance — "if present use it,
 * else a tiny local `cx` helper — don't add deps unnecessarily" — we ship this
 * dependency-free helper instead.
 *
 * It joins truthy class values and supports the common clsx input shapes:
 *   cx('a', cond && 'b', ['c', 'd'], { e: true, f: false }) → 'a b c d e'
 *
 * Note: this does NOT de-duplicate or resolve conflicting Tailwind utilities
 * (that's `tailwind-merge`'s job). The UI primitives are written so the caller's
 * `className` is appended last, letting later utilities win via source order /
 * specificity — sufficient for the overrides these components need.
 */
export type ClassDictionary = Record<string, boolean | null | undefined>
export type ClassValue =
  | string
  | number
  | boolean
  | null
  | undefined
  | ClassDictionary
  | ClassValue[]

export function cx(...inputs: ClassValue[]): string {
  const out: string[] = []
  for (const input of inputs) {
    if (input == null || input === false || input === true || input === '') continue
    if (typeof input === 'string' || typeof input === 'number') {
      out.push(String(input))
    } else if (Array.isArray(input)) {
      const nested = cx(...input)
      if (nested) out.push(nested)
    } else if (typeof input === 'object') {
      for (const key in input) {
        if (input[key]) out.push(key)
      }
    }
  }
  return out.join(' ')
}

export default cx
