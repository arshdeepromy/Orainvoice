/**
 * Printer driver interface and shared utilities for protocol-aware printer drivers.
 *
 * **Validates: Requirement 7 — Connection Type Expansion**
 * **Validates: Requirement 10 — Backward Compatibility**
 */

import type { ConnectionType } from './printerConnection';

export interface PrintOptions {
  paperWidthMm?: number;
}

export interface PrinterDriver {
  readonly type: ConnectionType;
  send(data: Uint8Array, options?: PrintOptions): Promise<void>;
}

/**
 * Map legacy connection type values to current types.
 * `network` → `generic_http`; all others pass through.
 */
export function resolveConnectionType(type: string): ConnectionType {
  if (type === 'network') return 'generic_http';
  return type as ConnectionType;
}

/**
 * Convert a Uint8Array to a Base64-encoded string.
 */
export function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}
