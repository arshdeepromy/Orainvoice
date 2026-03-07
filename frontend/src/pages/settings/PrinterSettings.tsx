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

  if (loading) return <p aria-live="polite">Loading printers…</p>;

  return (
    <section aria-label="Printer Settings">
      <h2>Printer Settings</h2>
      {error && (
        <div role="alert" className="error-banner">
          {error}
          <button onClick={() => setError(null)} aria-label="Dismiss error">×</button>
        </div>
      )}

      {testResult && (
        <div role="status" aria-label="Test print result" data-testid="test-result">
          {testResult === 'success' ? '✓ Test print sent successfully' : '✗ Test print failed'}
        </div>
      )}

      {/* Printer list */}
      <table aria-label="Configured printers">
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Address</th>
            <th>Paper</th>
            <th>Default</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {printers.filter((p) => p.is_active).map((printer) => (
            <tr key={printer.id} data-testid={`printer-row-${printer.id}`}>
              <td>{printer.name}</td>
              <td>{printer.connection_type}</td>
              <td>{printer.address ?? '—'}</td>
              <td>{printer.paper_width}mm</td>
              <td>{printer.is_default ? '✓' : ''}</td>
              <td>
                <button
                  onClick={() => handleTestPrint(printer)}
                  disabled={testingId === printer.id}
                  aria-label={`Test print ${printer.name}`}
                >
                  {testingId === printer.id ? 'Testing…' : 'Test Print'}
                </button>
                {!printer.is_default && (
                  <button
                    onClick={() => handleSetDefault(printer.id)}
                    aria-label={`Set ${printer.name} as default`}
                  >
                    Set Default
                  </button>
                )}
                <button
                  onClick={() => handleDeactivate(printer.id)}
                  aria-label={`Remove ${printer.name}`}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
          {printers.filter((p) => p.is_active).length === 0 && (
            <tr>
              <td colSpan={6}>No printers configured.</td>
            </tr>
          )}
        </tbody>
      </table>

      {/* Add printer form */}
      {!showAddForm ? (
        <button onClick={() => setShowAddForm(true)} aria-label="Add printer">
          Add Printer
        </button>
      ) : (
        <form onSubmit={handleAdd} aria-label="Add printer form">
          <div>
            <label htmlFor="printer-name">Printer Name</label>
            <input
              id="printer-name"
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </div>
          <div>
            <label htmlFor="connection-type">Connection Type</label>
            <select
              id="connection-type"
              value={form.connection_type}
              onChange={(e) => setForm({ ...form, connection_type: e.target.value as ConnectionType })}
            >
              <option value="usb">USB</option>
              <option value="bluetooth">Bluetooth</option>
              <option value="network">Network</option>
            </select>
          </div>
          {form.connection_type === 'network' && (
            <div>
              <label htmlFor="printer-address">IP Address / URL</label>
              <input
                id="printer-address"
                type="text"
                value={form.address}
                onChange={(e) => setForm({ ...form, address: e.target.value })}
                placeholder="192.168.1.100:9100"
                required
              />
            </div>
          )}
          <div>
            <label htmlFor="paper-width">Paper Width</label>
            <select
              id="paper-width"
              value={form.paper_width}
              onChange={(e) => setForm({ ...form, paper_width: Number(e.target.value) })}
            >
              <option value={80}>80mm</option>
              <option value={58}>58mm</option>
            </select>
          </div>
          <div>
            <label>
              <input
                type="checkbox"
                checked={form.is_default}
                onChange={(e) => setForm({ ...form, is_default: e.target.checked })}
              />
              Set as default printer
            </label>
          </div>
          <div>
            <label>
              <input
                type="checkbox"
                checked={form.is_kitchen_printer}
                onChange={(e) => setForm({ ...form, is_kitchen_printer: e.target.checked })}
              />
              Kitchen printer
            </label>
          </div>
          <button type="submit" aria-label="Save printer">Save</button>
          <button type="button" onClick={() => setShowAddForm(false)} aria-label="Cancel add printer">
            Cancel
          </button>
        </form>
      )}
    </section>
  );
}
