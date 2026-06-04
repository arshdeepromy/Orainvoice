/**
 * Tiny helper for generating local-only optimistic UUIDs.  We do NOT
 * pull in a UUID dependency — see CODE-GAP-13 / spec rules.
 */
export function genId(): string {
  return `optimistic-${Math.random().toString(36).slice(2)}`
}
