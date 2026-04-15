/**
 * Epson ePOS printer driver.
 *
 * Sends ESC/POS data as Base64-encoded content within a SOAP XML envelope
 * to the printer's built-in web server at `/cgi-bin/epos/service.cgi`.
 *
 * **Validates: Requirement 2 — Epson ePOS Protocol Support**
 */

import type { PrinterDriver, PrintOptions } from './printerDrivers';
import { uint8ArrayToBase64 } from './printerDrivers';

/**
 * Build the Epson ePOS SOAP envelope containing Base64-encoded ESC/POS data.
 *
 * This is a pure function exported separately for property-based testing.
 */
export function buildEpsonSoapEnvelope(base64: string): string {
  return [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">',
    '  <soap:Body>',
    '    <epos-print xmlns="http://www.epson-biz.com/pos/epos/service.cgi">',
    `      <command>${base64}</command>`,
    '    </epos-print>',
    '  </soap:Body>',
    '</soap:Envelope>',
  ].join('\n');
}

/**
 * Extract fault code and fault string from a SOAP fault response.
 *
 * Uses simple regex matching — no full XML parser needed.
 * Returns a string containing both the fault code and fault string if found.
 */
export function extractSoapFault(xml: string): string {
  const codeMatch = xml.match(/<faultcode>([\s\S]*?)<\/faultcode>/);
  const stringMatch = xml.match(/<faultstring>([\s\S]*?)<\/faultstring>/);

  const code = codeMatch?.[1]?.trim() ?? 'unknown';
  const message = stringMatch?.[1]?.trim() ?? 'unknown';

  return `${code}: ${message}`;
}

/**
 * Driver for Epson TM series printers using the ePOS protocol.
 *
 * Posts a SOAP envelope to `http://<address>/cgi-bin/epos/service.cgi` with a
 * 10-second AbortController timeout. Checks the response for `success="true"`;
 * throws with SOAP fault details otherwise.
 */
export class EpsonEPOSDriver implements PrinterDriver {
  readonly type = 'epson_epos' as const;

  constructor(private address: string) {}

  async send(data: Uint8Array, _options?: PrintOptions): Promise<void> {
    const base64 = uint8ArrayToBase64(data);
    const soap = buildEpsonSoapEnvelope(base64);
    const url = `http://${this.address}/cgi-bin/epos/service.cgi`;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10_000);

    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'text/xml; charset=utf-8' },
        body: soap,
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`Epson ePOS HTTP error: ${res.status}`);
      }

      const text = await res.text();
      if (!text.includes('success="true"')) {
        const fault = extractSoapFault(text);
        throw new Error(`Epson ePOS error: ${fault}`);
      }
    } finally {
      clearTimeout(timeoutId);
    }
  }
}
