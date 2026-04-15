/**
 * Protocol auto-detector for network receipt printers.
 *
 * Probes Star WebPRNT and Epson ePOS endpoints in parallel to determine
 * which protocol a printer supports. Falls back to `generic_http` if
 * neither endpoint responds within the 5-second timeout.
 *
 * **Validates: Requirement 6 — Printer Protocol Auto-Detection**
 */

export type DetectedProtocol = 'star_webprnt' | 'epson_epos' | 'generic_http';

/**
 * Probe a single HTTP endpoint. Returns `true` when the endpoint exists
 * (2xx or 405 status), `false` for any other status or network error.
 */
export async function probeEndpoint(url: string, signal: AbortSignal): Promise<boolean> {
  try {
    const res = await fetch(url, { method: 'GET', signal });
    return (res.status >= 200 && res.status < 300) || res.status === 405;
  } catch {
    return false;
  }
}

/**
 * Detect the printer protocol by probing Star and Epson endpoints in
 * parallel with a 5-second total timeout. Returns the first protocol
 * whose endpoint responds, or `generic_http` as fallback.
 */
export async function detectProtocol(address: string): Promise<DetectedProtocol> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 5_000);

  try {
    const [starResult, epsonResult] = await Promise.allSettled([
      probeEndpoint(`http://${address}/StarWebPRNT/SendMessage`, controller.signal),
      probeEndpoint(`http://${address}/cgi-bin/epos/service.cgi`, controller.signal),
    ]);

    if (starResult.status === 'fulfilled' && starResult.value) return 'star_webprnt';
    if (epsonResult.status === 'fulfilled' && epsonResult.value) return 'epson_epos';
    return 'generic_http';
  } finally {
    clearTimeout(timeoutId);
  }
}
