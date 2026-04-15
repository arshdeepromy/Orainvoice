/**
 * ESC/POS command builder for receipt printers.
 *
 * Supports 58mm (32 chars/line) and 80mm (48 chars/line) paper widths.
 * Builds binary command buffers for USB, Bluetooth, and network printers.
 *
 * **Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
 */

// ESC/POS command constants
const ESC = 0x1b;
const GS = 0x1d;
const LF = 0x0a;

const CMD = {
  INIT: [ESC, 0x40],
  ALIGN_LEFT: [ESC, 0x61, 0x00],
  ALIGN_CENTER: [ESC, 0x61, 0x01],
  ALIGN_RIGHT: [ESC, 0x61, 0x02],
  BOLD_ON: [ESC, 0x45, 0x01],
  BOLD_OFF: [ESC, 0x45, 0x00],
  DOUBLE_HEIGHT_ON: [ESC, 0x21, 0x10],
  DOUBLE_WIDTH_ON: [ESC, 0x21, 0x20],
  DOUBLE_SIZE_ON: [ESC, 0x21, 0x30],
  NORMAL_SIZE: [ESC, 0x21, 0x00],
  UNDERLINE_ON: [ESC, 0x2d, 0x01],
  UNDERLINE_OFF: [ESC, 0x2d, 0x00],
  CUT_PAPER: [GS, 0x56, 0x00],
  PARTIAL_CUT: [GS, 0x56, 0x01],
  FEED_LINES: (n: number) => [ESC, 0x64, n],
  OPEN_DRAWER: [ESC, 0x70, 0x00, 0x19, 0xfa],
} as const;

export type PaperWidth = number;

/**
 * Calculate characters per line for a given paper width in mm.
 * Returns 32 for 58mm, 48 for 80mm, and floor(width / 1.667) for other widths.
 */
export function charsPerLine(widthMm: number): number {
  if (widthMm === 58) return 32;
  if (widthMm === 80) return 48;
  return Math.floor(widthMm / 1.667);
}

export interface ReceiptLineItem {
  name: string;
  quantity: number;
  unitPrice: number;
  total: number;
}

export interface ReceiptData {
  orgName: string;
  orgAddress?: string;
  orgPhone?: string;
  receiptNumber?: string;
  date: string;
  items: ReceiptLineItem[];
  subtotal: number;
  taxLabel?: string;
  taxAmount: number;
  discountAmount?: number;
  total: number;
  paymentMethod: string;
  cashTendered?: number;
  changeGiven?: number;
  footer?: string;
  // Invoice receipt fields
  customerName?: string;
  gstNumber?: string;
  amountPaid?: number;
  balanceDue?: number;
  totalRefunded?: number;
  paymentBreakdown?: Array<{ method: string; amount: number }>;
}

/**
 * ESC/POS receipt builder. Accumulates commands into a byte buffer.
 */
export class ESCPOSBuilder {
  private buffer: number[] = [];
  private lineWidth: number;

  constructor(paperWidth: PaperWidth = 80) {
    this.lineWidth = charsPerLine(paperWidth);
    this.buffer.push(...CMD.INIT);
  }

  /** Add raw bytes to the buffer. */
  raw(bytes: readonly number[]): this {
    this.buffer.push(...bytes);
    return this;
  }

  /** Print a line of text. */
  text(str: string): this {
    const encoder = new TextEncoder();
    this.buffer.push(...encoder.encode(str), LF);
    return this;
  }

  /** Center-aligned text. */
  center(str: string): this {
    return this.raw(CMD.ALIGN_CENTER).text(str).raw(CMD.ALIGN_LEFT);
  }

  /** Right-aligned text. */
  right(str: string): this {
    return this.raw(CMD.ALIGN_RIGHT).text(str).raw(CMD.ALIGN_LEFT);
  }

  /** Bold text. */
  bold(str: string): this {
    return this.raw(CMD.BOLD_ON).text(str).raw(CMD.BOLD_OFF);
  }

  /** Double-size text (centered). */
  doubleSize(str: string): this {
    return this.raw(CMD.ALIGN_CENTER)
      .raw(CMD.DOUBLE_SIZE_ON)
      .text(str)
      .raw(CMD.NORMAL_SIZE)
      .raw(CMD.ALIGN_LEFT);
  }

  /** Print a separator line. */
  separator(char = '-'): this {
    return this.text(char.repeat(this.lineWidth));
  }

  /** Print two columns: left-aligned label, right-aligned value. */
  columns(left: string, right: string): this {
    const gap = this.lineWidth - left.length - right.length;
    if (gap < 1) {
      // Truncate left side if too long
      const maxLeft = this.lineWidth - right.length - 1;
      return this.text(left.slice(0, maxLeft) + ' ' + right);
    }
    return this.text(left + ' '.repeat(gap) + right);
  }

  /** Feed n lines. */
  feed(lines = 1): this {
    this.buffer.push(...CMD.FEED_LINES(lines));
    return this;
  }

  /** Cut paper. */
  cut(partial = true): this {
    this.feed(3);
    this.buffer.push(...(partial ? CMD.PARTIAL_CUT : CMD.CUT_PAPER));
    return this;
  }

  /** Open cash drawer. */
  openDrawer(): this {
    this.buffer.push(...CMD.OPEN_DRAWER);
    return this;
  }

  /**
   * Print a raster bitmap image (logo).
   * Accepts raw monochrome bitmap data (1 bit per pixel, MSB first).
   */
  bitmap(data: Uint8Array, widthPixels: number, heightPixels: number): this {
    const bytesPerLine = Math.ceil(widthPixels / 8);
    // GS v 0 — raster bit image
    this.buffer.push(
      GS, 0x76, 0x30, 0x00,
      bytesPerLine & 0xff, (bytesPerLine >> 8) & 0xff,
      heightPixels & 0xff, (heightPixels >> 8) & 0xff,
    );
    this.buffer.push(...data);
    return this;
  }

  /** Get the built command buffer as Uint8Array. */
  build(): Uint8Array {
    return new Uint8Array(this.buffer);
  }

  /** Get the line width for the configured paper. */
  getLineWidth(): number {
    return this.lineWidth;
  }
}

/** Format a number as currency string. */
function formatCurrency(amount: number): string {
  return `$${amount.toFixed(2)}`;
}

/**
 * Build a complete receipt from structured data.
 */
export function buildReceipt(data: ReceiptData, paperWidth: PaperWidth = 80): Uint8Array {
  const b = new ESCPOSBuilder(paperWidth);

  // Header — org name
  b.doubleSize(data.orgName);
  if (data.orgAddress) b.center(data.orgAddress);
  if (data.orgPhone) b.center(data.orgPhone);
  if (data.gstNumber != null) b.center(`GST: ${data.gstNumber}`);
  b.separator('=');

  // Receipt info
  if (data.receiptNumber) b.columns('Receipt #:', data.receiptNumber);
  b.columns('Date:', data.date);
  if (data.customerName != null) b.columns('Customer:', data.customerName);
  b.separator();

  // Line items
  for (const item of data.items) {
    const qtyPrice = `${item.quantity} x ${formatCurrency(item.unitPrice)}`;
    b.text(item.name);
    b.columns(`  ${qtyPrice}`, formatCurrency(item.total));
  }
  b.separator();

  // Totals
  b.columns('Subtotal:', formatCurrency(data.subtotal));
  if (data.discountAmount && data.discountAmount > 0) {
    b.columns('Discount:', `-${formatCurrency(data.discountAmount)}`);
  }
  b.columns(data.taxLabel ?? 'Tax:', formatCurrency(data.taxAmount));
  b.separator('=');
  b.raw(CMD.BOLD_ON);
  b.columns('TOTAL:', formatCurrency(data.total));
  b.raw(CMD.BOLD_OFF);
  b.separator('=');

  // Payment
  b.columns('Payment:', data.paymentMethod.toUpperCase());
  if (data.paymentBreakdown != null) {
    for (const entry of data.paymentBreakdown) {
      b.columns(`${entry.method}:`, formatCurrency(entry.amount));
    }
  }
  if (data.cashTendered != null) {
    b.columns('Tendered:', formatCurrency(data.cashTendered));
  }
  if (data.changeGiven != null && data.changeGiven > 0) {
    b.columns('Change:', formatCurrency(data.changeGiven));
  }
  if (data.amountPaid != null) {
    b.columns('Amount Paid:', formatCurrency(data.amountPaid));
  }
  if (data.balanceDue != null && data.balanceDue > 0) {
    b.raw(CMD.BOLD_ON);
    b.columns('BALANCE DUE:', formatCurrency(data.balanceDue));
    b.raw(CMD.BOLD_OFF);
  }

  // Footer
  b.feed(1);
  if (data.footer) {
    b.center(data.footer);
  } else {
    b.center('Thank you for your business!');
  }

  b.cut();
  return b.build();
}
