/**
 * Pure utility functions for time tracking calculations.
 * Extracted for property-based testing (Properties 12, 13, 14).
 */

export interface TimeRange {
  start: Date;
  end: Date;
}

export interface OverlapPair {
  index1: number;
  index2: number;
}

/**
 * Detect all overlapping pairs among time entries.
 * Two entries overlap when start1 < end2 AND start2 < end1.
 *
 * Property 12: Time entry overlap detection
 * Validates: Requirements 7.6
 */
export function detectOverlap(entries: TimeRange[]): OverlapPair[] {
  const pairs: OverlapPair[] = [];
  for (let i = 0; i < entries.length; i++) {
    for (let j = i + 1; j < entries.length; j++) {
      const a = entries[i];
      const b = entries[j];
      if (a.start < b.end && b.start < a.end) {
        pairs.push({ index1: i, index2: j });
      }
    }
  }
  return pairs;
}

export interface AggregationEntry {
  project_id: string;
  hours: number;
  billable: boolean;
  rate: number;
}

export interface ProjectAggregation {
  totalHours: number;
  billableHours: number;
  nonBillableHours: number;
  totalCost: number;
}

/**
 * Aggregate time entries by project.
 *
 * Property 13: Time entry aggregation is correct
 * Validates: Requirements 7.3, 7.4
 */
export function aggregateTimeByProject(
  entries: AggregationEntry[],
): Record<string, ProjectAggregation> {
  const result: Record<string, ProjectAggregation> = {};
  for (const entry of entries) {
    if (!result[entry.project_id]) {
      result[entry.project_id] = {
        totalHours: 0,
        billableHours: 0,
        nonBillableHours: 0,
        totalCost: 0,
      };
    }
    const agg = result[entry.project_id];
    agg.totalHours += entry.hours;
    if (entry.billable) {
      agg.billableHours += entry.hours;
      agg.totalCost += entry.hours * entry.rate;
    } else {
      agg.nonBillableHours += entry.hours;
    }
  }
  return result;
}

/**
 * Check whether a time entry can be converted to an invoice line item.
 * Returns true only if the entry is billable and not already invoiced.
 *
 * Property 14: Invoiced time entries cannot be double-billed
 * Validates: Requirements 7.5
 */
export function canConvertToInvoice(entry: {
  billable: boolean;
  status: string;
}): boolean {
  return entry.billable && entry.status !== 'invoiced';
}
