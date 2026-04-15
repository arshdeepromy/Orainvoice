/**
 * Browser Print driver.
 *
 * Renders receipt content as styled HTML in a hidden iframe and invokes
 * `window.print()` for printers without a built-in web server.
 *
 * **Validates: Requirement 4 — Browser Print Fallback**
 */

import type { PrinterDriver, PrintOptions } from './printerDrivers';

/**
 * Build a complete HTML document for printing a receipt.
 *
 * Converts the raw ESC/POS byte data to a text string and wraps it in an HTML
 * page with `@media print` CSS rules that set the page width, use a monospace
 * font, and remove browser default margins.
 *
 * This is a pure function exported separately for property-based testing (P6).
 */
export function buildReceiptHtml(data: Uint8Array, paperWidthMm: number): string {
  const decoder = new TextDecoder();
  const text = decoder.decode(data);

  return [
    '<!DOCTYPE html>',
    '<html>',
    '<head>',
    '<meta charset="utf-8">',
    '<style>',
    '  @media print {',
    `    @page { size: ${paperWidthMm}mm auto; margin: 0; }`,
    '  }',
    '  * { margin: 0; padding: 0; }',
    '  body {',
    "    font-family: 'Courier New', Courier, monospace;",
    '    font-size: 12px;',
    `    width: ${paperWidthMm}mm;`,
    '  }',
    '  pre {',
    '    white-space: pre-wrap;',
    '    word-wrap: break-word;',
    "    font-family: 'Courier New', Courier, monospace;",
    '  }',
    '</style>',
    '</head>',
    '<body>',
    `<pre>${text}</pre>`,
    '</body>',
    '</html>',
  ].join('\n');
}

/**
 * Driver that prints receipts via the browser's native print dialog.
 *
 * Creates a hidden iframe off-screen, writes the receipt HTML into it,
 * waits briefly for styles to apply, then calls `window.print()` on the
 * iframe's content window. The iframe is always removed in a finally block.
 */
export class BrowserPrintDriver implements PrinterDriver {
  readonly type = 'browser_print' as const;

  async send(data: Uint8Array, options?: PrintOptions): Promise<void> {
    const html = buildReceiptHtml(data, options?.paperWidthMm ?? 80);

    const iframe = document.createElement('iframe');
    iframe.style.cssText = 'position:fixed;left:-9999px;top:-9999px;width:0;height:0;';
    document.body.appendChild(iframe);

    try {
      const doc = iframe.contentDocument!;
      doc.open();
      doc.write(html);
      doc.close();

      // Allow a brief delay for styles to apply before printing
      await new Promise(resolve => setTimeout(resolve, 100));

      iframe.contentWindow!.print();
    } finally {
      document.body.removeChild(iframe);
    }
  }
}
