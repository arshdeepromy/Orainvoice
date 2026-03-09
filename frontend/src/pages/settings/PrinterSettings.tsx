/**
 * Printer configuration UI for organisation settings.
 *
 * Features: add printer, test print, set default, edit, deactivate.
 *
 * **Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
 */

import React, { useCallback, useEffect, useState } from 'react';
import apiClient from '@/api/client';
import { connectPrinter, type ConnectionType, type PrinterConnection } from '@/utils/printerConnection';
import { ESCPOSBuilder } from '@/utils/escpos';

interface PrinterConfig {
  id: string;
  org_id: string;
  location_id: string | null;
  name: string;
  connection_type: ConnectionType;
  address: string | null;
  paper_width: number;
  is_default: boolean;
  is_kitchen_printer: boolean;
  is_active: boolean;
  created_at: string;
}

interface AddPrinterForm {
  name: string;
  connection_type: ConnectionType;
  address: string;
  paper_width: number;
  is_default: boolean;
  is_kitchen_printer: boolean;
}

const EMPTY_FORM: AddPrinterForm = {
  name: '',
  connection_type: 'usb',
  address: '',
  paper_width: 80,
  is_default: false,
  is_kitchen_printer: false,
};

export default function PrinterSettings() {
  const [printers, setPrinters] = useState<PrinterConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [form, setForm] = useState<AddPrinterForm>({ ...EMPTY_FORM });
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const fetchPrinters = useCallback(async () => {
    try {
      setLoading(true);
      const res = await apiClient.get('/api/v2/printers');
      setPrinters(res.data);
    } catch {
      setError('Failed to load printers');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchPrinters();
  }, [fetchPrinters]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await apiClient.post('/api/v2/printers', {
        name: form.name,
        connection_type: form.connection_type,
        address: form.address || null,
        paper_width: form.paper_width,
        is_default: form.is_default,
        is_kitchen_printer: form.is_kitchen_printer,
      });
      setForm({ ...EMPTY_FORM });
      setShowAddForm(false);
      await fetchPrinters();
    } catch {
      setError('Failed to add printer');
    }
  };

  const handleSetDefault = async (printerId: string) => {
    try {
      await apiClient.put(`/api/v2/printers/${printerId}`, { is_default: true });
      await fetchPrinters();
    } catch {
      setError('Failed to set default printer');
    }
  };

  const handleDeactivate = async (printerId: string) => {
    try {
      await apiClient.delete(`/api/v2/printers/${printerId}`);
      await fetchPrinters();
    } catch {
      setError('Failed to deactivate printer');
    }
  };

  const handleTestPrint = async (printer: PrinterConfig) => {
    setTestingId(printer.id);
    setTestResult(null);
    try {
      // Queue test job on server
      await apiClient.post('/api/v2/printers/test', { printer_id: printer.id });

      // Attempt to send test page directly to printer via browser APIs
      const conn: PrinterConnection = await connectPrinter(
        printer.connection_type,
        printer.address ?? undefined,
      );
      const builder = new ESCPOSBuilder(printer.paper_width as 58 | 80);
      builder
        .doubleSize(printer.name)
        .separator('=')
        .center('TEST PRINT')
        .separator()
        .center('Printer is working!')
        .separator('=')
        .cut();
      await conn.send(builder.build());
      await conn.disconnect();
      setTestResult('success');
    } catch {
      setTestResult('failed');
    } finally {
      setTestingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-gray-600">Loading printers…</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Printer Settings</h1>
        {!showAddForm && (
          <button
            onClick={() => setShowAddForm(true)}
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label="Add printer"
          >
            Add Printer
          </button>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-red-50 p-4" role="alert">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3 flex-1">
              <p className="text-sm text-red-800">{error}</p>
            </div>
            <div className="ml-auto pl-3">
              <button
                onClick={() => setError(null)}
                className="inline-flex rounded-md bg-red-50 p-1.5 text-red-500 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-600 focus:ring-offset-2 focus:ring-offset-red-50"
                aria-label="Dismiss error"
              >
                <span className="sr-only">Dismiss</span>
                <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}

      {testResult && (
        <div
          className={`rounded-md p-4 ${testResult === 'success' ? 'bg-green-50' : 'bg-red-50'}`}
          role="status"
          aria-label="Test print result"
          data-testid="test-result"
        >
          <div className="flex">
            <div className="flex-shrink-0">
              {testResult === 'success' ? (
                <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              ) : (
                <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              )}
            </div>
            <div className="ml-3">
              <p className={`text-sm ${testResult === 'success' ? 'text-green-800' : 'text-red-800'}`}>
                {testResult === 'success' ? 'Test print sent successfully' : 'Test print failed'}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Add printer form */}
      {showAddForm && (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Add New Printer</h3>
          <form onSubmit={handleAdd} className="space-y-4" aria-label="Add printer form">
            <div>
              <label htmlFor="printer-name" className="block text-sm font-medium text-gray-700 mb-1">
                Printer Name
              </label>
              <input
                id="printer-name"
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                required
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label htmlFor="connection-type" className="block text-sm font-medium text-gray-700 mb-1">
                Connection Type
              </label>
              <select
                id="connection-type"
                value={form.connection_type}
                onChange={(e) => setForm({ ...form, connection_type: e.target.value as ConnectionType })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value="usb">USB</option>
                <option value="bluetooth">Bluetooth</option>
                <option value="network">Network</option>
              </select>
            </div>
            {form.connection_type === 'network' && (
              <div>
                <label htmlFor="printer-address" className="block text-sm font-medium text-gray-700 mb-1">
                  IP Address / URL
                </label>
                <input
                  id="printer-address"
                  type="text"
                  value={form.address}
                  onChange={(e) => setForm({ ...form, address: e.target.value })}
                  placeholder="192.168.1.100:9100"
                  required
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
            )}
            <div>
              <label htmlFor="paper-width" className="block text-sm font-medium text-gray-700 mb-1">
                Paper Width
              </label>
              <select
                id="paper-width"
                value={form.paper_width}
                onChange={(e) => setForm({ ...form, paper_width: Number(e.target.value) })}
                className="w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                <option value={80}>80mm</option>
                <option value={58}>58mm</option>
              </select>
            </div>
            <div className="flex items-center">
              <input
                id="is-default"
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <label htmlFor="is-default" className="ml-2 block text-sm text-gray-900">
                Set as default printer
              </label>
            </div>
            <div className="flex items-center">
              <input
                id="is-kitchen"
                type="checkbox"
                checked={form.is_kitchen_printer}
                onChange={(e) => setForm({ ...form, is_kitchen_printer: e.target.checked })}
                className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <label htmlFor="is-kitchen" className="ml-2 block text-sm text-gray-900">
                Kitchen printer
              </label>
            </div>
            <div className="flex gap-3 pt-4">
              <button
                type="submit"
                className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                aria-label="Save printer"
              >
                Save
              </button>
              <button
                type="button"
                onClick={() => setShowAddForm(false)}
                className="rounded-md border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                aria-label="Cancel add printer"
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Printer list */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
        <table className="min-w-full divide-y divide-gray-200" aria-label="Configured printers">
          <thead className="bg-gray-50">
            <tr>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Name
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Type
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Address
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Paper
              </th>
              <th scope="col" className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Default
              </th>
              <th scope="col" className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 bg-white">
            {printers.filter((p) => p.is_active).map((printer) => (
              <tr key={printer.id} data-testid={`printer-row-${printer.id}`}>
                <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                  {printer.name}
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {printer.connection_type}
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {printer.address ?? '—'}
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {printer.paper_width}mm
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">
                  {printer.is_default && (
                    <span className="inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800">
                      Default
                    </span>
                  )}
                </td>
                <td className="whitespace-nowrap px-6 py-4 text-right text-sm font-medium">
                  <div className="flex justify-end gap-2">
                    <button
                      onClick={() => handleTestPrint(printer)}
                      disabled={testingId === printer.id}
                      className="text-blue-600 hover:text-blue-900 disabled:text-gray-400"
                      aria-label={`Test print ${printer.name}`}
                    >
                      {testingId === printer.id ? 'Testing…' : 'Test'}
                    </button>
                    {!printer.is_default && (
                      <button
                        onClick={() => handleSetDefault(printer.id)}
                        className="text-blue-600 hover:text-blue-900"
                        aria-label={`Set ${printer.name} as default`}
                      >
                        Set Default
                      </button>
                    )}
                    <button
                      onClick={() => handleDeactivate(printer.id)}
                      className="text-red-600 hover:text-red-900"
                      aria-label={`Remove ${printer.name}`}
                    >
                      Remove
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {printers.filter((p) => p.is_active).length === 0 && (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-sm text-gray-500">
                  No printers configured.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
