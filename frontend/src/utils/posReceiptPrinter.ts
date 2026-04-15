/**
 * POS Receipt Printer service module.
 *
 * Orchestrates default printer resolution, ESC/POS data generation,
 * driver dispatch, fallback mode, and error handling.
 *
 * Task 4.1: Fallback mode management + type exports.
 * Task 4.2: Print orchestration (resolveDefaultPrinter, printReceipt, etc.)
 */

import apiClient from '@/api/client';
import { createDriver } from './printerConnection';
import { resolveConnectionType } from './printerDrivers';
import { BrowserPrintDriver } from './browserPrintDriver';
import { buildReceipt } from './escpos';
import { invoiceToReceiptData } from './invoiceReceiptMapper';
import type { ReceiptData } from './escpos';

// Re-export for consumers
export type { ReceiptData };

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FALLBACK_MODE_KEY = 'pos_printer_fallback_mode';
const DEFAULT_PAPER_WIDTH = 80;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface PrintResult {
  success: boolean;
  method: 'printer' | 'browser';
  error?: string;
}

export interface PrinterInfo {
  id: string;
  connection_type: string;
  address: string | null;
  paper_width: number;
  name: string;
}

export class NoPrinterError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NoPrinterError';
  }
}

// ---------------------------------------------------------------------------
// Fallback Mode Management (Requirements 3.4, 3.5)
// ---------------------------------------------------------------------------

/**
 * Check whether browser-print fallback mode is active.
 *
 * Reads from localStorage; returns `false` when storage is unavailable
 * (e.g. private browsing).
 */
export function isFallbackModeActive(): boolean {
  try {
    return localStorage.getItem(FALLBACK_MODE_KEY) === 'true';
  } catch {
    return false;
  }
}

/**
 * Enable or disable browser-print fallback mode.
 *
 * When `active` is true the key is written; when false the key is removed.
 * Silently ignores errors when localStorage is unavailable.
 */
export function setFallbackMode(active: boolean): void {
  try {
    if (active) {
      localStorage.setItem(FALLBACK_MODE_KEY, 'true');
    } else {
      localStorage.removeItem(FALLBACK_MODE_KEY);
    }
  } catch {
    // localStorage unavailable (private browsing) — ignore
  }
}

/**
 * Convenience wrapper that disables fallback mode.
 */
export function clearFallbackMode(): void {
  setFallbackMode(false);
}

// ---------------------------------------------------------------------------
// Default Printer Resolution (Requirements 2.1)
// ---------------------------------------------------------------------------

/**
 * Fetch the list of printers from the API and return the first one that is
 * both `is_default` and `is_active`. Returns `null` when no such printer
 * exists.
 */
export async function resolveDefaultPrinter(): Promise<PrinterInfo | null> {
  const res = await apiClient.get('/api/v2/printers');
  const printers = res.data?.items ?? res.data ?? [];
  const defaultPrinter = printers.find(
    (p: any) => p.is_default === true && p.is_active === true,
  );
  return defaultPrinter ?? null;
}

// ---------------------------------------------------------------------------
// Print Orchestration (Requirements 2.2, 2.3, 2.4, 3.4)
// ---------------------------------------------------------------------------

/**
 * Print a receipt via the default physical printer, or fall back to browser
 * print when fallback mode is active.
 *
 * 1. If fallback mode → BrowserPrintDriver immediately.
 * 2. Otherwise resolve the default printer from the API.
 * 3. Build ESC/POS bytes via `buildReceipt()`.
 * 4. Dispatch via `createDriver()`.
 *
 * Throws `NoPrinterError` when no default printer is configured and fallback
 * mode is off.
 */
export async function printReceipt(
  receiptData: ReceiptData,
  paperWidth?: number,
): Promise<PrintResult> {
  const width = paperWidth ?? DEFAULT_PAPER_WIDTH;
  const bytes = buildReceipt(receiptData, width);

  // If fallback mode is active, go straight to browser print
  if (isFallbackModeActive()) {
    const driver = new BrowserPrintDriver();
    await driver.send(bytes, { paperWidthMm: width });
    return { success: true, method: 'browser' };
  }

  // Resolve default printer
  const printer = await resolveDefaultPrinter();
  if (!printer) {
    throw new NoPrinterError('No default printer configured');
  }

  // Print via physical driver
  const resolved = resolveConnectionType(printer.connection_type);
  const driver = createDriver(resolved, printer.address ?? undefined);
  await driver.send(bytes, { paperWidthMm: width });
  return { success: true, method: 'printer' };
}

/**
 * High-level helper: convert an invoice object to receipt data, resolve the
 * paper width from the default printer, and print.
 */
export async function printInvoiceReceipt(invoice: any): Promise<PrintResult> {
  const receiptData = invoiceToReceiptData(invoice);

  // Determine paper width from the default printer when not in fallback mode
  let paperWidth = DEFAULT_PAPER_WIDTH;
  if (!isFallbackModeActive()) {
    try {
      const printer = await resolveDefaultPrinter();
      if (printer) {
        paperWidth = printer.paper_width ?? DEFAULT_PAPER_WIDTH;
      }
    } catch {
      // Will be caught in the main print flow
    }
  }

  return printReceipt(receiptData, paperWidth);
}

/**
 * Manual browser-print fallback. Builds ESC/POS bytes and dispatches them
 * through the `BrowserPrintDriver` (opens the browser print dialog).
 */
export async function browserPrintReceipt(
  receiptData: ReceiptData,
  paperWidth?: number,
): Promise<void> {
  const width = paperWidth ?? DEFAULT_PAPER_WIDTH;
  const bytes = buildReceipt(receiptData, width);
  const driver = new BrowserPrintDriver();
  await driver.send(bytes, { paperWidthMm: width });
}
