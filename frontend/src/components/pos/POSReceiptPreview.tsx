import type { ReceiptData } from '../../utils/escpos';

interface POSReceiptPreviewProps {
  receiptData: ReceiptData;
  paperWidth: number;
}

/** Map paper roll width (mm) to printable area (mm). */
function printableWidth(paperWidth: number): string {
  if (paperWidth === 58) return '48mm';
  return '72mm'; // 80mm default
}

/** Format a number as currency with $ prefix and 2 decimal places. */
function fmt(amount: number | string | null | undefined): string {
  return '$' + Number(amount ?? 0).toFixed(2);
}

export default function POSReceiptPreview({ receiptData, paperWidth }: POSReceiptPreviewProps) {
  const maxWidth = printableWidth(paperWidth);
  const d = receiptData;

  return (
    <div
      className="mx-auto border border-dashed border-gray-300 bg-white p-4 text-xs leading-relaxed text-gray-900"
      style={{ maxWidth, fontFamily: "'Courier New', monospace" }}
    >
      {/* Org header */}
      <div className="text-center">
        <div className="text-sm font-bold">{d.orgName}</div>
        {d.orgAddress && <div>{d.orgAddress}</div>}

        {d.orgPhone && <div>{d.orgPhone}</div>}
        {d.gstNumber && <div>GST: {d.gstNumber}</div>}
      </div>

      <Separator />

      {/* Invoice info */}
      {d.receiptNumber && <Row left="Receipt #:" right={d.receiptNumber} />}
      <Row left="Date:" right={d.date} />
      {d.customerName && <Row left="Customer:" right={d.customerName} />}

      <Separator />

      {/* Line items */}
      {(d.items ?? []).map((item, i) => (
        <div key={i}>
          <div>{item.name}</div>
          <Row left={'  ' + item.quantity + ' x ' + fmt(item.unitPrice)} right={fmt(item.total)} />
        </div>
      ))}

      <Separator />

      {/* Totals */}
      <Row left="Subtotal:" right={fmt(d.subtotal)} />
      {d.discountAmount != null && d.discountAmount > 0 && (
        <Row left="Discount:" right={'-' + fmt(d.discountAmount)} />
      )}
      <Row left={d.taxLabel ?? 'Tax:'} right={fmt(d.taxAmount)} />

      <SeparatorDouble />

      <Row left="TOTAL:" right={fmt(d.total)} bold />

      <SeparatorDouble />

      {/* Payment */}
      <Row left="Payment:" right={(d.paymentMethod ?? '').toUpperCase()} />
      {(d.paymentBreakdown ?? []).map((entry, i) => (
        <Row key={i} left={entry.method + ':'} right={fmt(entry.amount)} />
      ))}
      {d.cashTendered != null && <Row left="Tendered:" right={fmt(d.cashTendered)} />}
      {d.changeGiven != null && d.changeGiven > 0 && (
        <Row left="Change:" right={fmt(d.changeGiven)} />
      )}
      {d.amountPaid != null && <Row left="Amount Paid:" right={fmt(d.amountPaid)} />}
      {d.totalRefunded != null && d.totalRefunded > 0 && (
        <Row left="Refunded:" right={fmt(d.totalRefunded)} />
      )}
      {d.balanceDue != null && d.balanceDue > 0 && (
        <Row left="BALANCE DUE:" right={fmt(d.balanceDue)} bold />
      )}

      {/* Footer */}
      <div className="mt-3 text-center">
        {d.footer ?? 'Thank you for your business!'}
      </div>
    </div>
  );
}

/* ---- tiny helper sub-components ---- */

function Row({ left, right, bold }: { left: string; right: string; bold?: boolean }) {
  return (
    <div className={'flex justify-between' + (bold ? ' font-bold' : '')}>
      <span>{left}</span>
      <span>{right}</span>
    </div>
  );
}

function Separator() {
  return <div className="my-1 border-t border-dashed border-gray-400" />;
}

function SeparatorDouble() {
  return <div className="my-1 border-t-2 border-double border-gray-400" />;
}
