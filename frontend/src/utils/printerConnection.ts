/**
 * Printer connection utilities for WebUSB, Web Bluetooth, and network printers.
 *
 * **Validates: Requirement 22 — POS Module (Receipt Printer Integration)**
 */

export type ConnectionType = 'usb' | 'bluetooth' | 'network';

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
// Factory
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
