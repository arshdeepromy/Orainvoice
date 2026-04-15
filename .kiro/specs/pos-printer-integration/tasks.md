# Tasks — POS Printer Integration

## Task 1: Expand ConnectionType and add driver interface
- [x] 1.1 Update `ConnectionType` in `frontend/src/utils/printerConnection.ts` to include `star_webprnt`, `epson_epos`, `generic_http`, `browser_print`
- [x] 1.2 Create `frontend/src/utils/printerDrivers.ts` with `PrinterDriver` interface (`type`, `send(data, options)`) and `PrintOptions` type
- [x] 1.3 Add `resolveConnectionType()` function that maps legacy `network` → `generic_http` and passes other types through
- [x] 1.4 Add `uint8ArrayToBase64()` helper utility function

## Task 2: Implement Star WebPRNT driver
- [x] 2.1 Create `StarWebPRNTDriver` class implementing `PrinterDriver` — builds `<StarWebPrint>` XML with Base64-encoded ESC/POS data, POSTs to `/StarWebPRNT/SendMessage` with `Content-Type: text/xml; charset=utf-8` and 10s AbortController timeout
- [x] 2.2 Add `buildStarWebPRNTXml(base64: string): string` pure function that constructs the XML payload
- [x] 2.3 Add error handling: throw with HTTP status + response body on non-OK response

## Task 3: Implement Epson ePOS driver
- [x] 3.1 Create `EpsonEPOSDriver` class implementing `PrinterDriver` — builds SOAP envelope with Base64-encoded ESC/POS data, POSTs to `/cgi-bin/epos/service.cgi` with `Content-Type: text/xml; charset=utf-8` and 10s AbortController timeout
- [x] 3.2 Add `buildEpsonSoapEnvelope(base64: string): string` pure function that constructs the SOAP XML
- [x] 3.3 Add `extractSoapFault(xml: string): string` function to parse fault code and fault string from SOAP fault responses
- [x] 3.4 Add success check: parse response for `success="true"`, throw with fault details otherwise

## Task 4: Implement Generic HTTP driver
- [x] 4.1 Create `GenericHTTPDriver` class implementing `PrinterDriver` — sends raw Uint8Array as POST body with `Content-Type: application/octet-stream` and 10s AbortController timeout
- [x] 4.2 Add error handling: throw with HTTP status code + status text on non-2xx response

## Task 5: Implement Browser Print driver
- [x] 5.1 Create `BrowserPrintDriver` class implementing `PrinterDriver`
- [x] 5.2 Add `buildReceiptHtml(data: Uint8Array, paperWidthMm: number): string` function that generates styled HTML with `@media print` CSS rules setting page width, monospace font, and no default margins
- [x] 5.3 Implement iframe lifecycle: create hidden iframe, write HTML, call `window.print()`, remove iframe in finally block

## Task 6: Extend ESCPOSBuilder for custom paper widths
- [x] 6.1 Change `PaperWidth` type from `58 | 80` union to `number` and add `charsPerLine(widthMm: number): number` function that returns 32 for 58mm, 48 for 80mm, and `floor(width / 1.667)` for other widths
- [x] 6.2 Update `ESCPOSBuilder` constructor to accept any integer width and use `charsPerLine()` for line width calculation

## Task 7: Implement Protocol Detector
- [x] 7.1 Create `frontend/src/utils/protocolDetector.ts` with `detectProtocol(address: string): Promise<DetectedProtocol>` function
- [x] 7.2 Implement `probeEndpoint(url: string, signal: AbortSignal): Promise<boolean>` — returns true for 2xx or 405 status, false otherwise
- [x] 7.3 Implement parallel probing of Star and Epson endpoints with `Promise.allSettled`, 5-second total AbortController timeout, fallback to `generic_http`

## Task 8: Refactor PrinterConnectionManager
- [x] 8.1 Add `createDriver(type: ConnectionType, address?: string): PrinterDriver` factory function that dispatches to the correct driver class
- [x] 8.2 Create `LegacyConnectionAdapter` that wraps existing `connectUSBPrinter` and `connectBluetoothPrinter` functions in the `PrinterDriver` interface
- [x] 8.3 Add `buildTestReceipt(printerName: string, paperWidth: number): Uint8Array` function that generates a test receipt containing printer name, "TEST PRINT" heading, "Printer is working!" message, and current date/time

## Task 9: Update backend schemas and model
- [x] 9.1 Update `PrinterConfigCreate` schema: expand `connection_type` pattern to accept `star_webprnt|epson_epos|generic_http|browser_print`, change `paper_width` range to `ge=30, le=120`
- [x] 9.2 Update `PrinterConfigUpdate` schema with same pattern and range changes
- [x] 9.3 Update `CONNECTION_TYPES` constant in `models.py` to include new types
- [x] 9.4 Update backend router/service to accept legacy `network` value — add a Pydantic validator or pre-processing step that allows `network` in reads but maps it for new writes

## Task 10: Update PrinterSettings UI
- [x] 10.1 Update connection type dropdown to show all 6 options: USB, Bluetooth, Star WebPRNT, Epson ePOS, Generic HTTP, Browser Print
- [x] 10.2 Add conditional address field visibility: show for `star_webprnt`, `epson_epos`, `generic_http`; hide for `usb`, `bluetooth`, `browser_print`
- [x] 10.3 Add paper width selector with 58mm, 80mm, and Custom options; show numeric input (min=30, max=120) when Custom is selected
- [x] 10.4 Integrate protocol auto-detection: trigger `detectProtocol()` on address field blur when connection type is a network type, show loading indicator, pre-select detected protocol
- [x] 10.5 Update test print handler to use `createDriver()` and `buildTestReceipt()`, show success/error messages, disable button with "Testing…" during print

## Task 11: Property-based tests
- [x] 11.1 Install `fast-check` as dev dependency
- [x] 11.2 Write property test P1: Star WebPRNT XML Base64 round-trip — for any Uint8Array, `buildStarWebPRNTXml` → parse XML → decode Base64 === original
- [x] 11.3 Write property test P2: Star error contains status and body — for any 4xx/5xx status and body string, thrown error includes both
- [x] 11.4 Write property test P3: Epson SOAP Base64 round-trip — for any Uint8Array, `buildEpsonSoapEnvelope` → parse XML → decode Base64 === original
- [x] 11.5 Write property test P4: Epson fault extraction — for any fault code and string, `extractSoapFault` returns string containing both
- [x] 11.6 Write property test P5: Generic HTTP error contains status and text — for any non-2xx status and text, thrown error includes both
- [x] 11.7 Write property test P6: Receipt HTML paper width — for any width 30–120, generated HTML contains correct CSS width and monospace font
- [x] 11.8 Write property test P7: chars-per-line calculation — for any width 30–120, returns 32 for 58, 48 for 80, floor(w/1.667) otherwise
- [x] 11.9 Write property test P8: probe endpoint classification — for any status code, returns true for 2xx/405, false otherwise
- [x] 11.10 Write property test P9: driver factory dispatch — for any connection type including 'network', returns driver with correct resolved type
- [x] 11.11 Write property test P10: test receipt fields — for any printer name and date, receipt contains all required fields

## Task 12: Unit tests and integration tests
- [x] 12.1 Write unit tests for each driver's happy path (mock fetch → success → resolves)
- [x] 12.2 Write unit tests for Content-Type headers and AbortController timeouts
- [x] 12.3 Write unit tests for BrowserPrintDriver iframe lifecycle
- [x] 12.4 Write unit tests for protocol detection fallback to generic_http
- [x] 12.5 Write unit tests for backward compatibility (USB, Bluetooth unchanged; `network` → `generic_http`)
- [x] 12.6 Write integration tests for backend printer config CRUD with new connection types and paper width range
