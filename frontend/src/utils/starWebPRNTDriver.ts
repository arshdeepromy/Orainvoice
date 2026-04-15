/**
 * Star WebPRNT printer driver.
 *
 * Sends ESC/POS data as Base64-encoded content within a <StarWebPrint> XML
 * request body to the printer's built-in web server.
 *
 * **Validates: Requirement 1 — Star WebPRNT Protocol Support**
 */

import type { PrinterDriver, PrintOptions } from './printerDrivers';
import { uint8ArrayToBase64 } from './printerDrivers';

/**
 * Build the Star WebPRNT XML payload containing Base64-encoded ESC/POS data.
 *
 * This is a pure function exported separately for property-based testing.
 */
export function buildStarWebPRNTXml(base64: string): string {
  return [
    '<StarWebPrint xmlns="http://www.star-m.jp/2011/StarWebPrint">',
    '  <Request>',
    '    <SetRequest>',
    `      <Data Type="raw" Value="${base64}"/>`,
    '    </SetRequest>',
    '  </Request>',
    '</StarWebPrint>',
  ].join('\n');
}

/**
 * Driver for Star TSP series printers using the WebPRNT protocol.
 *
 * Posts XML to `http://<address>/StarWebPRNT/SendMessage` with a 10-second
 * AbortController timeout. Throws on non-OK responses with HTTP status and
 * response body.
 */
export class StarWebPRNTDriver implements PrinterDriver {
  readonly type = 'star_webprnt' as const;

  constructor(private address: string) {}

  async send(data: Uint8Array, _options?: PrintOptions): Promise<void> {
    const base64 = uint8ArrayToBase64(data);
    const xml = buildStarWebPRNTXml(base64);
    const url = `http://${this.address}/StarWebPRNT/SendMessage`;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10_000);

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'text/xml; charset=utf-8' },
        body: xml,
        signal: controller.signal,
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`Star WebPRNT error: ${res.status} ${body}`);
      }
    } finally {
      clearTimeout(timeoutId);
    }
  }
}
