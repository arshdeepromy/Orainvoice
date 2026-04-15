/**
 * Generic HTTP printer driver.
 *
 * Sends raw ESC/POS bytes as `application/octet-stream` POST to the printer's
 * HTTP endpoint.
 *
 * **Validates: Requirement 3 — Generic ESC/POS over HTTP Support**
 */

import type { PrinterDriver, PrintOptions } from './printerDrivers';

/**
 * Driver for printers that accept raw ESC/POS bytes via a simple HTTP endpoint.
 *
 * Posts raw Uint8Array to the printer address with a 10-second AbortController
 * timeout. Throws on non-2xx responses with HTTP status code and status text.
 */
export class GenericHTTPDriver implements PrinterDriver {
  readonly type = 'generic_http' as const;

  constructor(private address: string) {}

  async send(data: Uint8Array, _options?: PrintOptions): Promise<void> {
    const url = this.address.startsWith('http') ? this.address : `http://${this.address}`;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10_000);

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: data as unknown as BodyInit,
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`Printer error: ${res.status} ${res.statusText}`);
      }
    } finally {
      clearTimeout(timeoutId);
    }
  }
}
