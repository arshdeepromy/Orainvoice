import { useState } from 'react';
import { Modal } from '@/components/ui';

/**
 * PrinterErrorModal — Task 20 port of frontend/src/components/pos/PrinterErrorModal.tsx.
 *
 * All logic (the "enable fallback for future prints" checkbox + browser-print
 * action) is copied VERBATIM. Styling is remapped onto the design-system tokens
 * (danger-soft alert surface, accent link/button, ctl radii) to match the new
 * aesthetic per FR-2b — the prototype has no printer-error dialog.
 */
interface PrinterErrorModalProps {
  open: boolean;
  onClose: () => void;
  errorMessage: string;
  onBrowserPrint: (enableFallback: boolean) => void;
}

export default function PrinterErrorModal({
  open,
  onClose,
  errorMessage,
  onBrowserPrint,
}: PrinterErrorModalProps) {
  const [enableFallback, setEnableFallback] = useState(false);

  return (
    <Modal open={open} onClose={onClose} title="Printer Error">
      {/* Error message */}
      <div className="mb-4 rounded-ctl bg-danger-soft p-3 text-sm text-danger">
        {errorMessage}
      </div>

      {/* Fallback checkbox */}
      <label className="mb-4 flex items-center gap-2 text-sm text-text cursor-pointer">
        <input
          type="checkbox"
          checked={enableFallback}
          onChange={(e) => setEnableFallback(e.target.checked)}
          className="h-4 w-4 rounded border-border text-accent focus:ring-accent"
        />
        Enable Browser Print for Future Prints
      </label>

      {/* Actions */}
      <div className="flex items-center justify-between pt-2">
        <a
          href="/settings/printers"
          className="text-sm text-accent hover:text-accent-press hover:underline"
        >
          Go to Printer Settings
        </a>

        <button
          type="button"
          onClick={() => onBrowserPrint(enableFallback)}
          className="rounded-ctl bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-press focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1"
        >
          Use Browser Print
        </button>
      </div>
    </Modal>
  );
}
