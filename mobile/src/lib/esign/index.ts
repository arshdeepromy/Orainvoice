/**
 * esign pure core (mobile) — shared coordinate mapping, send-validation, and
 * dependency-graph logic for the mobile field-placement editor (R16).
 *
 * APPROACH (task 23.1): **verbatim duplication**, not a shared `@shared/esign/`
 * package. Rationale:
 *   - `frontend-v2/vite.config.ts` deliberately makes the web app self-contained
 *     ("no '@shared' alias into the repo root. All shared code is copied in,
 *     not imported (FR-3)"). Adding a `@shared` alias there to host this core
 *     would contradict that documented architecture decision.
 *   - The repo's root `shared/` dir holds *types only*; the established
 *     cross-app code-sharing precedent is the `@email-contract` alias that
 *     points *into* `frontend-v2/`, not a bidirectional shared module package.
 *   - `fieldValidation.ts` depends on frontend-v2-internal modules
 *     (`@/api/esign`, the editor `useFieldSet` hook), so a true shared
 *     extraction would force a much larger refactor of those too.
 *
 * The canonical sources stay in `frontend-v2/`:
 *   - `frontend-v2/src/components/esign/fieldplacement/lib/coordinateMapping.ts`
 *   - `frontend-v2/src/components/esign/fieldplacement/lib/fieldValidation.ts`
 *   - `frontend-v2/src/components/esign/lib/dependencyGraph.ts`
 *
 * `coordinateMapping.ts` and `dependencyGraph.ts` are byte-for-byte copies.
 * `fieldValidation.ts` is identical except for two import specifiers (the
 * contract symbols are re-homed to the self-contained `./fieldSetTypes`); the
 * validation rule set is byte-for-byte the same. Task 23.2's parity test proves
 * the web and mobile copies produce identical results over generated inputs
 * (R16.9). Keep the copies in sync when the canonical sources change.
 */

export * from './coordinateMapping'
export * from './dependencyGraph'
export * from './fieldValidation'
export * from './fieldSetTypes'
