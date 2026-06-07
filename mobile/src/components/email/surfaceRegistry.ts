/**
 * Send Email — surface registry re-export (mobile).
 *
 * Re-exports the frozen `SURFACE_REGISTRY` from the web module (single source of
 * truth, R1.10 / R12.1). Importing the registry is pure data/types, so this is a
 * straight re-export through the `@email-contract` alias — no parallel definition.
 */
export { SURFACE_REGISTRY } from '@email-contract/surfaceRegistry'
