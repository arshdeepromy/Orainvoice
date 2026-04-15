/**
 * Unit tests for POS printer drivers.
 *
 * Covers happy paths, Content-Type headers, AbortController timeouts,
 * BrowserPrintDriver iframe lifecycle, protocol detection fallback,
 * and backward compatibility.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { StarWebPRNTDriver } from '../starWebPRNTDriver';
import { EpsonEPOSDriver } from '../epsonEPOSDriver';
import { GenericHTTPDriver } from '../genericHTTPDriver';
import { BrowserPrintDriver } from '../browserPrintDriver';
import { detectProtocol } from '../protocolDetector';
import { createDriver } from '../printerConnection';
import { resolveConnectionType } from '../printerDrivers';

// ---------------------------------------------------------------------------
// 12.1 — Happy path tests
// ---------------------------------------------------------------------------

describe('12.1 — Driver happy paths', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('StarWebPRNTDriver: mock fetch → 200 OK → send resolves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200 }),
    );

    const driver = new StarWebPRNTDriver('192.168.1.100');
    await expect(driver.send(new Uint8Array([0x1b, 0x40]))).resolves.toBeUndefined();
  });

  it('EpsonEPOSDriver: mock fetch → 200 OK with success="true" → send resolves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        text: () => Promise.resolve('<response success="true"/>'),
      }),
    );

    const driver = new EpsonEPOSDriver('192.168.1.101');
    await expect(driver.send(new Uint8Array([0x1b, 0x40]))).resolves.toBeUndefined();
  });

  it('GenericHTTPDriver: mock fetch → 200 OK → send resolves', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200 }),
    );

    const driver = new GenericHTTPDriver('192.168.1.102');
    await expect(driver.send(new Uint8Array([0x1b, 0x40]))).resolves.toBeUndefined();
  });

  it('BrowserPrintDriver: mock document/iframe → send resolves', async () => {
    const mockPrint = vi.fn();
    const mockWrite = vi.fn();
    const mockOpen = vi.fn();
    const mockClose = vi.fn();

    const mockIframe = {
      style: { cssText: '' },
      contentDocument: {
        open: mockOpen,
        write: mockWrite,
        close: mockClose,
      },
      contentWindow: { print: mockPrint },
    } as unknown as HTMLIFrameElement;

    vi.spyOn(document, 'createElement').mockReturnValue(mockIframe);
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockIframe);
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockIframe);

    const driver = new BrowserPrintDriver();
    await expect(driver.send(new Uint8Array([0x48, 0x69]))).resolves.toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// 12.2 — Content-Type headers and AbortController timeouts
// ---------------------------------------------------------------------------

describe('12.2 — Content-Type headers and AbortController', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('StarWebPRNTDriver: fetch called with Content-Type text/xml; charset=utf-8', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', mockFetch);

    const driver = new StarWebPRNTDriver('192.168.1.100');
    await driver.send(new Uint8Array([0x1b, 0x40]));

    expect(mockFetch).toHaveBeenCalledOnce();
    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[1].headers['Content-Type']).toBe('text/xml; charset=utf-8');
  });

  it('EpsonEPOSDriver: fetch called with Content-Type text/xml; charset=utf-8', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve('<response success="true"/>'),
    });
    vi.stubGlobal('fetch', mockFetch);

    const driver = new EpsonEPOSDriver('192.168.1.101');
    await driver.send(new Uint8Array([0x1b, 0x40]));

    expect(mockFetch).toHaveBeenCalledOnce();
    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[1].headers['Content-Type']).toBe('text/xml; charset=utf-8');
  });

  it('GenericHTTPDriver: fetch called with Content-Type application/octet-stream', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', mockFetch);

    const driver = new GenericHTTPDriver('192.168.1.102');
    await driver.send(new Uint8Array([0x1b, 0x40]));

    expect(mockFetch).toHaveBeenCalledOnce();
    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[1].headers['Content-Type']).toBe('application/octet-stream');
  });

  it('StarWebPRNTDriver: AbortController signal is passed to fetch', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', mockFetch);

    const driver = new StarWebPRNTDriver('192.168.1.100');
    await driver.send(new Uint8Array([0x1b, 0x40]));

    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[1].signal).toBeInstanceOf(AbortSignal);
  });

  it('EpsonEPOSDriver: AbortController signal is passed to fetch', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => Promise.resolve('<response success="true"/>'),
    });
    vi.stubGlobal('fetch', mockFetch);

    const driver = new EpsonEPOSDriver('192.168.1.101');
    await driver.send(new Uint8Array([0x1b, 0x40]));

    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[1].signal).toBeInstanceOf(AbortSignal);
  });

  it('GenericHTTPDriver: AbortController signal is passed to fetch', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal('fetch', mockFetch);

    const driver = new GenericHTTPDriver('192.168.1.102');
    await driver.send(new Uint8Array([0x1b, 0x40]));

    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[1].signal).toBeInstanceOf(AbortSignal);
  });
});


// ---------------------------------------------------------------------------
// 12.3 — BrowserPrintDriver iframe lifecycle
// ---------------------------------------------------------------------------

describe('12.3 — BrowserPrintDriver iframe lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('iframe is created and appended to document.body', async () => {
    const mockPrint = vi.fn();
    const mockIframe = {
      style: { cssText: '' },
      contentDocument: {
        open: vi.fn(),
        write: vi.fn(),
        close: vi.fn(),
      },
      contentWindow: { print: mockPrint },
    } as unknown as HTMLIFrameElement;

    const createSpy = vi.spyOn(document, 'createElement').mockReturnValue(mockIframe);
    const appendSpy = vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockIframe);
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockIframe);

    const driver = new BrowserPrintDriver();
    await driver.send(new Uint8Array([0x48, 0x69]));

    expect(createSpy).toHaveBeenCalledWith('iframe');
    expect(appendSpy).toHaveBeenCalledWith(mockIframe);
  });

  it('iframe.contentDocument.write is called with HTML', async () => {
    const mockWrite = vi.fn();
    const mockPrint = vi.fn();
    const mockIframe = {
      style: { cssText: '' },
      contentDocument: {
        open: vi.fn(),
        write: mockWrite,
        close: vi.fn(),
      },
      contentWindow: { print: mockPrint },
    } as unknown as HTMLIFrameElement;

    vi.spyOn(document, 'createElement').mockReturnValue(mockIframe);
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockIframe);
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockIframe);

    const driver = new BrowserPrintDriver();
    await driver.send(new Uint8Array([0x48, 0x69]));

    expect(mockWrite).toHaveBeenCalledOnce();
    const html = mockWrite.mock.calls[0][0] as string;
    expect(html).toContain('<!DOCTYPE html>');
    expect(html).toContain('Hi'); // 0x48=H, 0x69=i
  });

  it('iframe.contentWindow.print is called', async () => {
    const mockPrint = vi.fn();
    const mockIframe = {
      style: { cssText: '' },
      contentDocument: {
        open: vi.fn(),
        write: vi.fn(),
        close: vi.fn(),
      },
      contentWindow: { print: mockPrint },
    } as unknown as HTMLIFrameElement;

    vi.spyOn(document, 'createElement').mockReturnValue(mockIframe);
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockIframe);
    vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockIframe);

    const driver = new BrowserPrintDriver();
    await driver.send(new Uint8Array([0x48, 0x69]));

    expect(mockPrint).toHaveBeenCalledOnce();
  });

  it('iframe is removed from document.body in finally block (even on error)', async () => {
    const mockIframe = {
      style: { cssText: '' },
      contentDocument: {
        open: vi.fn(),
        write: vi.fn(() => { throw new Error('write failed'); }),
        close: vi.fn(),
      },
      contentWindow: { print: vi.fn() },
    } as unknown as HTMLIFrameElement;

    vi.spyOn(document, 'createElement').mockReturnValue(mockIframe);
    vi.spyOn(document.body, 'appendChild').mockImplementation(() => mockIframe);
    const removeSpy = vi.spyOn(document.body, 'removeChild').mockImplementation(() => mockIframe);

    const driver = new BrowserPrintDriver();
    await expect(driver.send(new Uint8Array([0x48, 0x69]))).rejects.toThrow('write failed');

    expect(removeSpy).toHaveBeenCalledWith(mockIframe);
  });
});

// ---------------------------------------------------------------------------
// 12.4 — Protocol detection fallback to generic_http
// ---------------------------------------------------------------------------

describe('12.4 — Protocol detection fallback', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('both Star and Epson probes fail → detectProtocol returns generic_http', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new Error('Network error')),
    );

    const result = await detectProtocol('192.168.1.200');
    expect(result).toBe('generic_http');
  });

  it('Star probe succeeds → returns star_webprnt', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('StarWebPRNT')) {
          return Promise.resolve({ status: 200 });
        }
        return Promise.reject(new Error('Network error'));
      }),
    );

    const result = await detectProtocol('192.168.1.200');
    expect(result).toBe('star_webprnt');
  });

  it('Epson probe succeeds → returns epson_epos', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation((url: string) => {
        if (url.includes('cgi-bin/epos')) {
          return Promise.resolve({ status: 200 });
        }
        return Promise.reject(new Error('Network error'));
      }),
    );

    const result = await detectProtocol('192.168.1.200');
    expect(result).toBe('epson_epos');
  });
});

// ---------------------------------------------------------------------------
// 12.5 — Backward compatibility
// ---------------------------------------------------------------------------

describe('12.5 — Backward compatibility', () => {
  it("createDriver('usb') returns driver with type 'usb'", () => {
    const driver = createDriver('usb');
    expect(driver.type).toBe('usb');
  });

  it("createDriver('bluetooth') returns driver with type 'bluetooth'", () => {
    const driver = createDriver('bluetooth');
    expect(driver.type).toBe('bluetooth');
  });

  it("createDriver('network', '192.168.1.1') returns driver with type 'generic_http'", () => {
    const driver = createDriver('network', '192.168.1.1');
    expect(driver.type).toBe('generic_http');
  });

  it("resolveConnectionType('network') returns 'generic_http'", () => {
    expect(resolveConnectionType('network')).toBe('generic_http');
  });

  it("resolveConnectionType('usb') returns 'usb'", () => {
    expect(resolveConnectionType('usb')).toBe('usb');
  });
});
