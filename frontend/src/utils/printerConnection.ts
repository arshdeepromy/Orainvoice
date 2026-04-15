/**
 * Printer connection utilities for WebUSB, Web Bluetooth, and network printers.
 *
 * **Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
 */

import type { PrinterDriver, PrintOptions } from './printerDrivers';
import { resolveConnectionType } from './printerDrivers';
import { StarWebPRNTDriver } from './starWebPRNTDriver';
import { EpsonEPOSDriver } from './epsonEPOSDriver';
import { GenericHTTPDriver } from './genericHTTPDriver';
import { BrowserPrintDriver } from './browserPrintDriver';
import { ESCPOSBuilder } from './escpos';

export type ConnectionType =
  | 'usb' | 'bluetooth' | 'network'
  | 'star_webprnt' | 'epson_epos' | 'generic_http' | 'browser_print';

export interface PrinterConnection {
  type: ConnectionType;
  connected: boolean;
  send(data: Uint8Array): Promise<void>;
  disconnect(): Promise<void>;
}

// ---------------------------------------------------------------------------
// WebUSB Printer Connection (Task 30.5)
// ---------------------------------------------------------------------------

/** Common USB printer class/subclass/protocol for ESC/POS printers. */
const USB_PRINTER_FILTERS: Array<{ classCode: number }> = [
  { classCode: 7 }, // Printer class
];

export async function connectUSBPrinter(): Promise<PrinterConnection> {
  if (!(navigator as any).usb) {
    throw new Error('WebUSB is not supported in this browser');
  }

  const device = await (navigator as any).usb.requestDevice({ filters: USB_PRINTER_FILTERS });
  await device.open();

  // Select the first configuration if not already selected
  if (device.configuration === null) {
    await device.selectConfiguration(1);
  }

  // Find the printer interface and claim it
  const iface = device.configuration?.interfaces.find((i: any) =>
    i.alternates.some((a: any) => a.interfaceClass === 7),
  );
  if (!iface) throw new Error('No printer interface found on USB device');

  await device.claimInterface(iface.interfaceNumber);

  // Find the OUT endpoint for sending data
  const alt = iface.alternates.find((a: any) => a.interfaceClass === 7);
  const outEndpoint = alt?.endpoints.find((e: any) => e.direction === 'out');
  if (!outEndpoint) throw new Error('No OUT endpoint found on printer interface');

  const endpointNumber = outEndpoint.endpointNumber;

  const conn: PrinterConnection = {
    type: 'usb',
    connected: true,
    async send(data: Uint8Array) {
      // Send in chunks of 64 bytes (common USB packet size)
      const CHUNK_SIZE = 64;
      for (let offset = 0; offset < data.length; offset += CHUNK_SIZE) {
        const chunk = data.slice(offset, offset + CHUNK_SIZE);
        await device.transferOut(endpointNumber, chunk);
      }
    },
    async disconnect() {
      await device.releaseInterface(iface.interfaceNumber);
      await device.close();
      conn.connected = false;
    },
  };
  return conn;
}

// ---------------------------------------------------------------------------
// Web Bluetooth Printer Connection (Task 30.6)
// ---------------------------------------------------------------------------

/** Common Bluetooth SPP (Serial Port Profile) service UUID. */
const BT_PRINTER_SERVICE = '000018f0-0000-1000-8000-00805f9b34fb';
const BT_PRINTER_CHARACTERISTIC = '00002af1-0000-1000-8000-00805f9b34fb';

export async function connectBluetoothPrinter(): Promise<PrinterConnection> {
  if (!(navigator as any).bluetooth) {
    throw new Error('Web Bluetooth is not supported in this browser');
  }

  const device = await (navigator as any).bluetooth.requestDevice({
    filters: [{ services: [BT_PRINTER_SERVICE] }],
    optionalServices: [BT_PRINTER_SERVICE],
  });

  const server = await device.gatt!.connect();
  const service = await server.getPrimaryService(BT_PRINTER_SERVICE);
  const characteristic = await service.getCharacteristic(BT_PRINTER_CHARACTERISTIC);

  const conn: PrinterConnection = {
    type: 'bluetooth',
    connected: true,
    async send(data: Uint8Array) {
      // BLE has a max write size (~20 bytes default, up to 512 with MTU negotiation)
      const CHUNK_SIZE = 20;
      for (let offset = 0; offset < data.length; offset += CHUNK_SIZE) {
        const chunk = data.slice(offset, offset + CHUNK_SIZE);
        await characteristic.writeValueWithoutResponse(chunk);
      }
    },
    async disconnect() {
      server.disconnect();
      conn.connected = false;
    },
  };
  return conn;
}

// ---------------------------------------------------------------------------
// Network Printer Connection (Task 30.7)
// ---------------------------------------------------------------------------

export async function connectNetworkPrinter(address: string): Promise<PrinterConnection> {
  // Normalise address to include protocol
  const url = address.startsWith('http') ? address : `http://${address}`;

  const conn: PrinterConnection = {
    type: 'network',
    connected: true,
    async send(data: Uint8Array) {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: data as unknown as BodyInit,
      });
      if (!response.ok) {
        throw new Error(`Network printer error: ${response.status} ${response.statusText}`);
      }
    },
    async disconnect() {
      conn.connected = false;
    },
  };
  return conn;
}

// ---------------------------------------------------------------------------
// Legacy Connection Factory (preserved for backward compatibility)
// ---------------------------------------------------------------------------

/**
 * Connect to a printer by connection type.
 */
export async function connectPrinter(
  type: ConnectionType,
  address?: string,
): Promise<PrinterConnection> {
  switch (type) {
    case 'usb':
      return connectUSBPrinter();
    case 'bluetooth':
      return connectBluetoothPrinter();
    case 'network':
      if (!address) throw new Error('Network printer requires an address');
      return connectNetworkPrinter(address);
    default:
      throw new Error(`Unsupported connection type: ${type}`);
  }
}

// ---------------------------------------------------------------------------
// LegacyConnectionAdapter (Task 8.2)
// ---------------------------------------------------------------------------

/**
 * Wraps existing `connectUSBPrinter` and `connectBluetoothPrinter` functions
 * in the `PrinterDriver` interface so they can be used through `createDriver`.
 *
 * **Validates: Requirement 10 — Backward Compatibility**
 */
export class LegacyConnectionAdapter implements PrinterDriver {
  readonly type: ConnectionType;

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  constructor(type: 'usb' | 'bluetooth', _address?: string) {
    this.type = type;
  }

  async send(data: Uint8Array, _options?: PrintOptions): Promise<void> {
    if (this.type === 'usb') {
      const conn = await connectUSBPrinter();
      await conn.send(data);
    } else {
      const conn = await connectBluetoothPrinter();
      await conn.send(data);
    }
  }
}

// ---------------------------------------------------------------------------
// Driver Factory (Task 8.1)
// ---------------------------------------------------------------------------

/**
 * Create a `PrinterDriver` for the given connection type.
 *
 * Handles the legacy `network` type by resolving it to `generic_http` before
 * dispatching. Network-based drivers require an `address` parameter.
 *
 * **Validates: Requirement 8.1, 10.1**
 */
export function createDriver(type: ConnectionType | string, address?: string): PrinterDriver {
  const resolved = resolveConnectionType(type);

  switch (resolved) {
    case 'star_webprnt':
      if (!address) throw new Error('Star WebPRNT requires an address');
      return new StarWebPRNTDriver(address);
    case 'epson_epos':
      if (!address) throw new Error('Epson ePOS requires an address');
      return new EpsonEPOSDriver(address);
    case 'generic_http':
      if (!address) throw new Error('Generic HTTP requires an address');
      return new GenericHTTPDriver(address);
    case 'browser_print':
      return new BrowserPrintDriver();
    case 'usb':
    case 'bluetooth':
      return new LegacyConnectionAdapter(resolved, address);
    default:
      throw new Error(`Unsupported connection type: ${resolved}`);
  }
}

// ---------------------------------------------------------------------------
// Test Receipt Builder (Task 8.3)
// ---------------------------------------------------------------------------

/**
 * Generate a test receipt containing the printer name, "TEST PRINT" heading,
 * "Printer is working!" message, and the current date/time.
 *
 * **Validates: Requirement 8.2**
 */
export function buildTestReceipt(printerName: string, paperWidth: number): Uint8Array {
  const builder = new ESCPOSBuilder(paperWidth);
  builder
    .center(printerName)
    .center('TEST PRINT')
    .text('Printer is working!')
    .text(new Date().toLocaleString())
    .cut();
  return builder.build();
}
