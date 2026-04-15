import { useState } from 'react';
import { Modal } from '../ui/Modal';

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
      <div className="mb-4 rounded bg-red-50 p-3 text-sm text-red-700">
        {errorMessage}
      </div>

      {/* Fallback checkbox */}
      <label className="mb-4 flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
        <input
          type="checkbox"
          checked={enableFallback}
          onChange={(e) => setEnableFallback(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
        Enable Browser Print for Future Prints
      </label>

      {/* Actions */}
      <div className="flex items-center justify-between pt-2">
        <a
          href="/settings/printers"
          className="text-sm text-blue-600 hover:text-blue-800 hover:underline"
        >
          Go to Printer Settings
        </a>

        <button
          type="button"
          onClick={() => onBrowserPrint(enableFallback)}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          Use Browser Print
        </button>
      </div>
    </Modal>
  );
}
