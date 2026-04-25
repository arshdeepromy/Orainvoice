/**
 * Property-based tests for offline queue pure functions.
 *
 * Uses fast-check with vitest.
 */
import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  addMutation,
  getReplayOrder,
  serializeQueue,
  deserializeQueue,
  type OfflineQueueState,
  type OfflineMutation,
  type OfflineMutationType,
  type OfflineMutationMethod,
} from '../useOfflineQueue'

/* ------------------------------------------------------------------ */
/* Generators                                                         */
/* ------------------------------------------------------------------ */

const mutationTypeArb: fc.Arbitrary<OfflineMutationType> = fc.constantFrom(
  'create',
  'update',
  'delete',
)

const mutationMethodArb: fc.Arbitrary<OfflineMutationMethod> = fc.constantFrom(
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
)

const entityTypeArb = fc.constantFrom(
  'invoice',
  'customer',
  'expense',
  'quote',
  'job',
  'booking',
  'payment',
)

const mutationInputArb = fc.record({
  timestamp: fc.nat({ max: 1_000_000_000 }),
  type: mutationTypeArb,
  endpoint: fc.stringMatching(/^\/api\/v1\/[a-z]+$/),
  method: mutationMethodArb,
  body: fc.oneof(
    fc.constant(null),
    fc.dictionary(fc.string({ minLength: 1, maxLength: 10 }), fc.jsonValue()),
  ) as fc.Arbitrary<Record<string, unknown> | null>,
  entityType: entityTypeArb,
  entityLabel: fc.string({ minLength: 1, maxLength: 30 }),
})

const offlineMutationArb: fc.Arbitrary<OfflineMutation> = fc.record({
  id: fc.uuid(),
  timestamp: fc.nat({ max: 1_000_000_000 }),
  type: mutationTypeArb,
  endpoint: fc.stringMatching(/^\/api\/v1\/[a-z]+$/),
  method: mutationMethodArb,
  body: fc.oneof(
    fc.constant(null),
    fc.dictionary(fc.string({ minLength: 1, maxLength: 10 }), fc.jsonValue()),
  ) as fc.Arbitrary<Record<string, unknown> | null>,
  entityType: entityTypeArb,
  entityLabel: fc.string({ minLength: 1, maxLength: 30 }),
  status: fc.constant('pending' as const),
  retryCount: fc.constant(0),
})

const queueStateArb: fc.Arbitrary<OfflineQueueState> = fc
  .array(offlineMutationArb, { minLength: 0, maxLength: 20 })
  .map((mutations) => ({ mutations }))

/* ------------------------------------------------------------------ */
/* Property 5: Offline queue stores all mutations with correct metadata */
/* ------------------------------------------------------------------ */

describe('Property 5: Offline queue stores all mutations with correct metadata', () => {
  /**
   * **Validates: Requirements 30.3**
   *
   * For any sequence of mutations added to the queue, the queue contains
   * entries with correct metadata and monotonically non-decreasing timestamps.
   */
  it('stores all mutations with correct metadata and non-decreasing timestamps', () => {
    fc.assert(
      fc.property(
        fc.array(mutationInputArb, { minLength: 1, maxLength: 20 }),
        (inputs) => {
          let queue: OfflineQueueState = { mutations: [] }

          for (const input of inputs) {
            queue = addMutation(queue, input)
          }

          // All mutations are stored
          expect(queue.mutations).toHaveLength(inputs.length)

          // Each mutation has correct metadata
          for (let i = 0; i < inputs.length; i++) {
            const stored = queue.mutations[i]
            const input = inputs[i]

            expect(stored.endpoint).toBe(input.endpoint)
            expect(stored.method).toBe(input.method)
            expect(stored.type).toBe(input.type)
            expect(stored.entityType).toBe(input.entityType)
            expect(stored.entityLabel).toBe(input.entityLabel)
            expect(stored.status).toBe('pending')
            expect(stored.retryCount).toBe(0)
            expect(typeof stored.id).toBe('string')
            expect(stored.id.length).toBeGreaterThan(0)

            // Body should match (deep equality)
            if (input.body === null) {
              expect(stored.body).toBeNull()
            } else {
              expect(stored.body).toEqual(input.body)
            }
          }

          // Timestamps are monotonically non-decreasing
          for (let i = 1; i < queue.mutations.length; i++) {
            expect(queue.mutations[i].timestamp).toBeGreaterThanOrEqual(
              queue.mutations[i - 1].timestamp,
            )
          }
        },
      ),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/* Property 6: Offline queue replays mutations in chronological order  */
/* ------------------------------------------------------------------ */

describe('Property 6: Offline queue replays mutations in chronological order', () => {
  /**
   * **Validates: Requirements 30.4**
   *
   * For any sequence of mutations with arbitrary timestamps, replay order
   * is strictly non-decreasing by timestamp.
   */
  it('replays mutations in non-decreasing timestamp order', () => {
    fc.assert(
      fc.property(queueStateArb, (queue) => {
        const replayOrder = getReplayOrder(queue)

        for (let i = 1; i < replayOrder.length; i++) {
          expect(replayOrder[i].timestamp).toBeGreaterThanOrEqual(
            replayOrder[i - 1].timestamp,
          )
        }
      }),
      { numRuns: 100 },
    )
  })
})

/* ------------------------------------------------------------------ */
/* Property 7: Offline queue persistence round-trip preserves all      */
/* ------------------------------------------------------------------ */

describe('Property 7: Offline queue persistence round-trip preserves all mutations', () => {
  /**
   * **Validates: Requirements 30.7**
   *
   * For any queue state, serializing and deserializing produces a deeply
   * equal queue.
   */
  it('round-trip preserves all mutations', () => {
    fc.assert(
      fc.property(queueStateArb, (queue) => {
        const serialized = serializeQueue(queue)
        const deserialized = deserializeQueue(serialized)

        expect(deserialized.mutations).toHaveLength(queue.mutations.length)

        for (let i = 0; i < queue.mutations.length; i++) {
          const original = queue.mutations[i]
          const restored = deserialized.mutations[i]

          expect(restored.id).toBe(original.id)
          expect(restored.timestamp).toBe(original.timestamp)
          expect(restored.type).toBe(original.type)
          expect(restored.endpoint).toBe(original.endpoint)
          expect(restored.method).toBe(original.method)
          expect(restored.entityType).toBe(original.entityType)
          expect(restored.entityLabel).toBe(original.entityLabel)
          expect(restored.status).toBe(original.status)
          expect(restored.retryCount).toBe(original.retryCount)
          expect(restored.body).toEqual(original.body)
        }
      }),
      { numRuns: 100 },
    )
  })
})
