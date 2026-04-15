/**
 * Feature: pos-invoice-receipt-print, Property 8
 * **Validates: Requirements 2.1**
 *
 * Property 8: Default printer resolution from printer list
 *
 * For any array of printer configuration objects with varying `is_default`
 * and `is_active` boolean flags, the default printer resolution logic SHALL
 * return the first printer where both `is_default` and `is_active` are true,
 * or null when no such printer exists.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as fc from 'fast-check';

/* ------------------------------------------------------------------ */
/*  Mock apiClient                                                     */
/* ------------------------------------------------------------------ */

vi.mock('@/api/client', () => {
  const mockGet = vi.fn();
  return { default: { get: mockGet } };
});

// Also mock the other imports that posReceiptPrinter.ts pulls in,
// so the module can load without side-effects from real drivers.
vi.mock('../utils/printerConnection', () => ({
  createDriver: vi.fn(),
}));
vi.mock('../utils/printerDrivers', () => ({
  resolveConnectionType: vi.fn(),
}));
vi.mock('../utils/browserPrintDriver', () => ({
  BrowserPrintDriver: vi.fn(),
}));
vi.mock('../utils/escpos', () => ({
  buildReceipt: vi.fn(),
}));
vi.mock('../utils/invoiceReceiptMapper', () => ({
  invoiceToReceiptData: vi.fn(),
}));

import apiClient from '@/api/client';
import { resolveDefaultPrinter } from '../utils/posReceiptPrinter';

const mockGet = vi.mocked(apiClient.get);

/* ------------------------------------------------------------------ */
/*  Generators                                                         */
/* ------------------------------------------------------------------ */

const printerArb = fc.record({
  id: fc.uuid(),
  is_default: fc.boolean(),
  is_active: fc.boolean(),
  connection_type: fc.constantFrom('star_webprnt', 'epson_epos', 'generic_http', 'browser'),
  address: fc.option(fc.string()),
  paper_width: fc.constantFrom(58, 80),
  name: fc.string(),
});

const printerListArb = fc.array(printerArb);

/* ------------------------------------------------------------------ */
/*  Property 8: Default printer resolution from printer list           */
/* ------------------------------------------------------------------ */

describe('Property 8: Default printer resolution from printer list', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('returns the first printer where both is_default and is_active are true, or null', async () => {
    await fc.assert(
      fc.asyncProperty(printerListArb, async (printers) => {
        mockGet.mockResolvedValue({ data: { items: printers } });

        const result = await resolveDefaultPrinter();

        const expected =
          printers.find(
            (p) => p.is_default === true && p.is_active === true,
          ) ?? null;

        if (expected === null) {
          expect(result).toBeNull();
        } else {
          expect(result).toEqual(expected);
        }
      }),
      { numRuns: 100 },
    );
  });

  it('returns null when no printer has both is_default and is_active true', async () => {
    const noBothTrueArb = fc
      .array(printerArb)
      .filter((arr) => !arr.some((p) => p.is_default && p.is_active));

    await fc.assert(
      fc.asyncProperty(noBothTrueArb, async (printers) => {
        mockGet.mockResolvedValue({ data: { items: printers } });

        const result = await resolveDefaultPrinter();
        expect(result).toBeNull();
      }),
      { numRuns: 100 },
    );
  });

  it('returns the FIRST matching printer when multiple have both flags true', async () => {
    const multiMatchArb = fc
      .array(printerArb, { minLength: 2 })
      .map((arr) => {
        const patched = [...arr];
        patched[0] = { ...patched[0], is_default: true, is_active: true };
        patched[patched.length - 1] = {
          ...patched[patched.length - 1],
          is_default: true,
          is_active: true,
        };
        return patched;
      });

    await fc.assert(
      fc.asyncProperty(multiMatchArb, async (printers) => {
        mockGet.mockResolvedValue({ data: { items: printers } });

        const result = await resolveDefaultPrinter();

        const firstMatch = printers.find(
          (p) => p.is_default === true && p.is_active === true,
        );
        expect(result).toEqual(firstMatch);
      }),
      { numRuns: 100 },
    );
  });
});


/* ------------------------------------------------------------------ */
/*  Property 9: Fallback mode bypasses physical printer                */
/*  Feature: pos-invoice-receipt-print, Property 9                     */
/*  **Validates: Requirements 3.4**                                    */
/* ------------------------------------------------------------------ */

import { printReceipt } from '../utils/posReceiptPrinter';
import { BrowserPrintDriver } from '../utils/browserPrintDriver';
import { buildReceipt } from '../utils/escpos';

const mockBrowserSend = vi.fn();

// Wire the BrowserPrintDriver constructor mock to return our spy
vi.mocked(BrowserPrintDriver).mockImplementation(function (this: any) {
  this.type = 'browser_print';
  this.send = mockBrowserSend;
  return this;
} as any);

// Wire buildReceipt to return a valid Uint8Array
vi.mocked(buildReceipt).mockReturnValue(new Uint8Array([0x1b, 0x40]));

/* Generator: random ReceiptData-like objects */
const receiptLineItemArb = fc.record({
  name: fc.string({ minLength: 1 }),
  quantity: fc.nat({ max: 1000 }),
  unitPrice: fc.float({ min: 0, max: 100000, noNaN: true }),
  total: fc.float({ min: 0, max: 100000, noNaN: true }),
});

const receiptDataArb = fc.record({
  orgName: fc.string(),
  orgAddress: fc.option(fc.string(), { nil: undefined }),
  orgPhone: fc.option(fc.string(), { nil: undefined }),
  receiptNumber: fc.option(fc.string(), { nil: undefined }),
  date: fc.string({ minLength: 1 }),
  items: fc.array(receiptLineItemArb, { minLength: 0, maxLength: 10 }),
  subtotal: fc.float({ min: 0, max: 100000, noNaN: true }),
  taxLabel: fc.option(fc.string(), { nil: undefined }),
  taxAmount: fc.float({ min: 0, max: 100000, noNaN: true }),
  discountAmount: fc.option(fc.float({ min: 0, max: 100000, noNaN: true }), { nil: undefined }),
  total: fc.float({ min: 0, max: 100000, noNaN: true }),
  paymentMethod: fc.string(),
  footer: fc.option(fc.string(), { nil: undefined }),
});

const paperWidthArb = fc.constantFrom(58, 80);

describe('Property 9: Fallback mode bypasses physical printer', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockBrowserSend.mockReset();
    mockBrowserSend.mockResolvedValue(undefined);
    localStorage.setItem('pos_printer_fallback_mode', 'true');
  });

  afterEach(() => {
    localStorage.removeItem('pos_printer_fallback_mode');
  });

  it('returns method "browser" and success true without calling apiClient.get', async () => {
    await fc.assert(
      fc.asyncProperty(receiptDataArb, paperWidthArb, async (receiptData, paperWidth) => {
        mockGet.mockReset();
        mockBrowserSend.mockReset();
        mockBrowserSend.mockResolvedValue(undefined);

        const result = await printReceipt(receiptData as any, paperWidth);

        // Must return browser method with success
        expect(result).toEqual({ success: true, method: 'browser' });

        // Must NOT have attempted to resolve a physical printer
        expect(mockGet).not.toHaveBeenCalled();
      }),
      { numRuns: 100 },
    );
  });
});


/* ------------------------------------------------------------------ */
/*  Property 10: Fallback mode localStorage round-trip                 */
/*  Feature: pos-invoice-receipt-print, Property 10                    */
/*  **Validates: Requirements 3.5**                                    */
/* ------------------------------------------------------------------ */

import {
  setFallbackMode,
  isFallbackModeActive,
  clearFallbackMode,
} from '../utils/posReceiptPrinter';

describe('Property 10: Fallback mode localStorage round-trip', () => {
  afterEach(() => {
    localStorage.removeItem('pos_printer_fallback_mode');
  });

  it('setFallbackMode(value) then isFallbackModeActive() returns that value', () => {
    fc.assert(
      fc.property(fc.boolean(), (value) => {
        setFallbackMode(value);
        expect(isFallbackModeActive()).toBe(value);
      }),
      { numRuns: 100 },
    );
  });

  it('clearFallbackMode() then isFallbackModeActive() always returns false', () => {
    fc.assert(
      fc.property(fc.boolean(), (initialValue) => {
        // Set to an arbitrary value first
        setFallbackMode(initialValue);
        // Clear it
        clearFallbackMode();
        // Must always be false after clearing
        expect(isFallbackModeActive()).toBe(false);
      }),
      { numRuns: 100 },
    );
  });
});
