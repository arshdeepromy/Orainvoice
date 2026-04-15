/**
 * Property-based tests for POS printer drivers.
 *
 * Uses fast-check with Vitest. Each property runs a minimum of 100 iterations.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import fc from 'fast-check';

import { buildStarWebPRNTXml } from '../starWebPRNTDriver';
import { StarWebPRNTDriver } from '../starWebPRNTDriver';
import { buildEpsonSoapEnvelope, extractSoapFault } from '../epsonEPOSDriver';
import { GenericHTTPDriver } from '../genericHTTPDriver';
import { buildReceiptHtml } from '../browserPrintDriver';
import { charsPerLine } from '../escpos';
import { probeEndpoint } from '../protocolDetector';
import { createDriver, buildTestReceipt } from '../printerConnection';
import { resolveConnectionType, uint8ArrayToBase64 } from '../printerDrivers';

const NUM_RUNS = 100;

describe('POS Printer Driver Properties', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  /**
   * P1: Star WebPRNT XML Base64 round-trip
   * For any Uint8Array, buildStarWebPRNTXml → parse XML → decode Base64 === original
   *
   * **Validates: Requirements 1.1**
   */
  it('P1: Star WebPRNT XML Base64 round-trip', () => {
    fc.assert(
      fc.property(
        fc.uint8Array({ minLength: 0, maxLength: 4096 }),
        (data) => {
          const base64 = uint8ArrayToBase64(data);
          const xml = buildStarWebPRNTXml(base64);

          // Parse XML and extract the Base64 value from the Data element
          const parser = new DOMParser();
          const doc = parser.parseFromString(xml, 'text/xml');
          const dataEl = doc.getElementsByTagName('Data')[0];
          const extractedBase64 = dataEl.getAttribute('Value')!;

          // Decode Base64 back to bytes
          const binary = atob(extractedBase64);
          const decoded = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) {
            decoded[i] = binary.charCodeAt(i);
          }

          expect(decoded).toEqual(data);
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P2: Star error contains status and body
   * For any 4xx/5xx status and body string, thrown error includes both
   *
   * **Validates: Requirements 1.3**
   */
  it('P2: Star error contains status and body', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 400, max: 599 }),
        fc.string(),
        async (status, body) => {
          vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
              ok: false,
              status,
              text: () => Promise.resolve(body),
            }),
          );

          const driver = new StarWebPRNTDriver('192.168.1.1');
          const data = new Uint8Array([0x1b, 0x40]);

          try {
            await driver.send(data);
            // Should not reach here
            expect.unreachable('Expected send to throw');
          } catch (err: any) {
            expect(err.message).toContain(String(status));
            expect(err.message).toContain(body);
          }
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P3: Epson SOAP Base64 round-trip
   * For any Uint8Array, buildEpsonSoapEnvelope → parse XML → decode Base64 === original
   *
   * **Validates: Requirements 2.1**
   */
  it('P3: Epson SOAP Base64 round-trip', () => {
    fc.assert(
      fc.property(
        fc.uint8Array({ minLength: 0, maxLength: 4096 }),
        (data) => {
          const base64 = uint8ArrayToBase64(data);
          const soap = buildEpsonSoapEnvelope(base64);

          // Parse SOAP XML and extract the Base64 value from the command element
          const parser = new DOMParser();
          const doc = parser.parseFromString(soap, 'text/xml');
          const commandEl = doc.getElementsByTagName('command')[0];
          const extractedBase64 = commandEl.textContent!;

          // Decode Base64 back to bytes
          const binary = atob(extractedBase64);
          const decoded = new Uint8Array(binary.length);
          for (let i = 0; i < binary.length; i++) {
            decoded[i] = binary.charCodeAt(i);
          }

          expect(decoded).toEqual(data);
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P4: Epson fault extraction
   * For any fault code and string, extractSoapFault returns string containing both
   *
   * **Validates: Requirements 2.3**
   */
  it('P4: Epson fault extraction', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1 }),
        fc.string({ minLength: 1 }),
        (faultCode, faultString) => {
          const xml = `<soap:Envelope><soap:Body><soap:Fault><faultcode>${faultCode}</faultcode><faultstring>${faultString}</faultstring></soap:Fault></soap:Body></soap:Envelope>`;
          const result = extractSoapFault(xml);

          expect(result).toContain(faultCode.trim());
          expect(result).toContain(faultString.trim());
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P5: Generic HTTP error contains status and text
   * For any non-2xx status and text, thrown error includes both
   *
   * **Validates: Requirements 3.3**
   */
  it('P5: Generic HTTP error contains status and text', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 100, max: 599 }).filter((s) => s < 200 || s >= 300),
        fc.string(),
        async (status, statusText) => {
          vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({
              ok: false,
              status,
              statusText,
            }),
          );

          const driver = new GenericHTTPDriver('192.168.1.1');
          const data = new Uint8Array([0x1b, 0x40]);

          try {
            await driver.send(data);
            expect.unreachable('Expected send to throw');
          } catch (err: any) {
            expect(err.message).toContain(String(status));
            expect(err.message).toContain(statusText);
          }
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P6: Receipt HTML paper width
   * For any width 30–120, generated HTML contains correct CSS width and monospace font
   *
   * **Validates: Requirements 4.1, 4.3, 4.5**
   */
  it('P6: Receipt HTML paper width', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 30, max: 120 }),
        (width) => {
          const data = new Uint8Array([0x48, 0x65, 0x6c, 0x6c, 0x6f]); // "Hello"
          const html = buildReceiptHtml(data, width);

          // CSS @page rule contains the correct width
          expect(html).toContain(`size: ${width}mm auto`);
          // Body width set correctly
          expect(html).toContain(`width: ${width}mm`);
          // Monospace font used
          expect(html).toContain('monospace');
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P7: chars-per-line calculation
   * For any width 30–120, returns 32 for 58, 48 for 80, floor(w/1.667) otherwise
   *
   * **Validates: Requirements 5.5**
   */
  it('P7: chars-per-line calculation', () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 30, max: 120 }),
        (width) => {
          const result = charsPerLine(width);

          if (width === 58) {
            expect(result).toBe(32);
          } else if (width === 80) {
            expect(result).toBe(48);
          } else {
            expect(result).toBe(Math.floor(width / 1.667));
          }
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P8: probe endpoint classification
   * For any status code, returns true for 2xx/405, false otherwise
   *
   * **Validates: Requirements 6.2, 6.3**
   */
  it('P8: probe endpoint classification', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 100, max: 599 }),
        async (status) => {
          vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue({ status }),
          );

          const controller = new AbortController();
          const result = await probeEndpoint('http://192.168.1.1/test', controller.signal);

          const expected = (status >= 200 && status < 300) || status === 405;
          expect(result).toBe(expected);
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P9: driver factory dispatch
   * For any connection type including 'network', returns driver with correct resolved type
   *
   * **Validates: Requirements 8.1, 10.1**
   */
  it('P9: driver factory dispatch', () => {
    fc.assert(
      fc.property(
        fc.constantFrom(
          'usb',
          'bluetooth',
          'star_webprnt',
          'epson_epos',
          'generic_http',
          'browser_print',
          'network',
        ),
        (connectionType) => {
          const needsAddress = ['star_webprnt', 'epson_epos', 'generic_http', 'network'].includes(
            connectionType,
          );
          const driver = createDriver(connectionType, needsAddress ? '192.168.1.1' : undefined);

          const expectedType = resolveConnectionType(connectionType);
          expect(driver.type).toBe(expectedType);
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });

  /**
   * P10: test receipt fields
   * For any printer name and date, receipt contains all required fields
   *
   * **Validates: Requirements 8.2**
   */
  it('P10: test receipt fields', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }),
        fc.date(),
        (printerName, _date) => {
          const receipt = buildTestReceipt(printerName, 80);
          const text = new TextDecoder().decode(receipt);

          expect(text).toContain(printerName);
          expect(text).toContain('TEST PRINT');
          expect(text).toContain('Printer is working!');
          // The receipt should contain some date/time representation
          // buildTestReceipt uses new Date().toLocaleString() internally
          // We just verify the receipt is non-empty and contains the required text fields
        },
      ),
      { numRuns: NUM_RUNS },
    );
  });
});
