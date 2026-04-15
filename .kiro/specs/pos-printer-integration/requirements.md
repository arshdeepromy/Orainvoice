# Requirements Document

## Introduction

OraInvoice's POS module currently supports USB and Bluetooth receipt printers via WebUSB and Web Bluetooth APIs. The network printer implementation is broken: it sends raw ESC/POS bytes via `fetch()` HTTP POST to the printer's IP address, which fails because LAN receipt printers (Star TSP100III, Epson TM series) do not accept raw byte POSTs. These printers expose proprietary web servers with vendor-specific protocols (Star WebPRNT XML, Epson ePOS SOAP). Additionally, browsers cannot open raw TCP sockets to port 9100.

This feature replaces the broken network printer connection with protocol-aware printer drivers, adds a browser print fallback for printers without web servers, exposes paper width configuration in the Add Printer form, and implements protocol auto-detection so users don't need to know which protocol their printer speaks.

All print data transmission happens browser-side. The cloud-hosted backend cannot reach the customer's LAN, so the backend stores printer configuration only; the frontend handles all communication with the physical printer.

## Glossary

- **Printer_Connection_Manager**: The frontend module (`printerConnection.ts`) responsible for establishing connections to printers and sending print data via the correct protocol.
- **ESCPOSBuilder**: The frontend class (`escpos.ts`) that constructs binary ESC/POS command buffers for receipt formatting.
- **Star_WebPRNT_Driver**: A frontend driver that sends print commands to Star printers via their built-in web server at `http://<ip>/StarWebPRNT/SendMessage` using XML-encoded ESC/POS data.
- **Epson_ePOS_Driver**: A frontend driver that sends print commands to Epson printers via their built-in web server at `http://<ip>/cgi-bin/epos/service.cgi` using SOAP/XML-encoded ESC/POS data.
- **Generic_HTTP_Driver**: A frontend driver that sends raw ESC/POS bytes via HTTP POST to printers that expose a simple HTTP endpoint accepting `application/octet-stream`.
- **Browser_Print_Driver**: A frontend driver that renders a styled HTML receipt and prints it using `window.print()` via a hidden iframe, for printers without a web server.
- **Protocol_Detector**: A frontend utility that probes a printer's IP address to determine which protocol (Star WebPRNT, Epson ePOS, or Generic HTTP) the printer supports.
- **Printer_Settings_UI**: The React settings page (`PrinterSettings.tsx`) where users add, edit, test, and manage printer configurations.
- **Connection_Type**: The protocol/transport used to communicate with a printer. Values: `usb`, `bluetooth`, `star_webprnt`, `epson_epos`, `generic_http`, `browser_print`.
- **Paper_Width**: The physical paper width of the receipt roll in millimeters (58mm, 80mm, or a custom value).

## Requirements

### Requirement 1: Star WebPRNT Protocol Support

**User Story:** As a POS operator using a Star TSP100III LAN printer, I want OraInvoice to send print commands using the Star WebPRNT protocol, so that my network receipt printer actually prints receipts.

#### Acceptance Criteria

1. WHEN a printer is configured with connection type `star_webprnt`, THE Star_WebPRNT_Driver SHALL send ESC/POS data as Base64-encoded content within a `<StarWebPrint>` XML request body to `http://<address>/StarWebPRNT/SendMessage` via HTTP POST.
2. WHEN the Star printer's web server returns a successful response, THE Star_WebPRNT_Driver SHALL resolve the send operation as successful.
3. IF the Star printer's web server returns an error response or the HTTP request fails, THEN THE Star_WebPRNT_Driver SHALL throw an error containing the HTTP status code and any error message from the response body.
4. THE Star_WebPRNT_Driver SHALL set the HTTP `Content-Type` header to `text/xml; charset=utf-8` on every request.
5. WHEN sending to a Star printer, THE Star_WebPRNT_Driver SHALL include a timeout of 10 seconds on the HTTP request using an AbortController signal.

### Requirement 2: Epson ePOS Protocol Support

**User Story:** As a POS operator using an Epson TM series LAN printer, I want OraInvoice to send print commands using the Epson ePOS protocol, so that my Epson network printer works correctly.

#### Acceptance Criteria

1. WHEN a printer is configured with connection type `epson_epos`, THE Epson_ePOS_Driver SHALL send ESC/POS data as Base64-encoded content within a SOAP XML envelope to `http://<address>/cgi-bin/epos/service.cgi` via HTTP POST.
2. WHEN the Epson printer's web server returns a successful SOAP response with `<response success="true">`, THE Epson_ePOS_Driver SHALL resolve the send operation as successful.
3. IF the Epson printer's web server returns a SOAP fault or the HTTP request fails, THEN THE Epson_ePOS_Driver SHALL throw an error containing the fault code and fault string from the response.
4. THE Epson_ePOS_Driver SHALL set the HTTP `Content-Type` header to `text/xml; charset=utf-8` on every request.
5. WHEN sending to an Epson printer, THE Epson_ePOS_Driver SHALL include a timeout of 10 seconds on the HTTP request using an AbortController signal.

### Requirement 3: Generic ESC/POS over HTTP Support

**User Story:** As a POS operator using a network printer that exposes a simple HTTP endpoint, I want OraInvoice to send raw ESC/POS bytes over HTTP, so that my printer receives commands it understands.

#### Acceptance Criteria

1. WHEN a printer is configured with connection type `generic_http`, THE Generic_HTTP_Driver SHALL send the raw ESC/POS byte buffer as the HTTP POST body with `Content-Type: application/octet-stream` to `http://<address>`.
2. WHEN the HTTP response status is 2xx, THE Generic_HTTP_Driver SHALL resolve the send operation as successful.
3. IF the HTTP response status is not 2xx or the request fails, THEN THE Generic_HTTP_Driver SHALL throw an error containing the HTTP status code and status text.
4. WHEN sending to a generic HTTP printer, THE Generic_HTTP_Driver SHALL include a timeout of 10 seconds on the HTTP request using an AbortController signal.

### Requirement 4: Browser Print Fallback

**User Story:** As a POS operator whose printer does not have a built-in web server, I want OraInvoice to print a styled receipt using the browser's native print dialog, so that I can still print receipts from any printer connected to my computer.

#### Acceptance Criteria

1. WHEN a printer is configured with connection type `browser_print`, THE Browser_Print_Driver SHALL generate an HTML document containing the receipt content styled for the configured paper width.
2. WHEN the Browser_Print_Driver sends a print command, THE Browser_Print_Driver SHALL create a hidden iframe, write the receipt HTML into the iframe, and invoke `window.print()` on the iframe's content window.
3. THE Browser_Print_Driver SHALL apply CSS `@media print` rules that set the page width to the configured paper width (58mm, 80mm, or custom) and remove browser default margins.
4. WHEN the print dialog is closed (whether the user printed or cancelled), THE Browser_Print_Driver SHALL remove the hidden iframe from the DOM.
5. THE Browser_Print_Driver SHALL use a monospace font in the receipt HTML to preserve column alignment consistent with ESC/POS output.

### Requirement 5: Paper Width Configuration

**User Story:** As a POS operator, I want to select the paper width (58mm, 80mm, or a custom width) when adding or editing a printer, so that receipts are formatted correctly for my paper rolls.

#### Acceptance Criteria

1. THE Printer_Settings_UI SHALL display a paper width selector with options for 58mm, 80mm, and "Custom" when adding a new printer.
2. WHEN the user selects "Custom" paper width, THE Printer_Settings_UI SHALL display a numeric input field where the user can enter a width between 30mm and 120mm.
3. THE Printer_Settings_UI SHALL display the paper width selector with the current value pre-filled when editing an existing printer.
4. WHEN a printer configuration is saved with a custom paper width, THE Printer_Settings_UI SHALL send the numeric width value to the backend API.
5. THE ESCPOSBuilder SHALL accept any integer paper width and calculate the characters-per-line as `floor(paper_width_mm / 1.667)` for widths other than 58mm and 80mm.

### Requirement 6: Printer Protocol Auto-Detection

**User Story:** As a POS operator, I want OraInvoice to automatically detect which protocol my network printer uses when I enter its IP address, so that I don't need to know the technical details of my printer.

#### Acceptance Criteria

1. WHEN the user enters an IP address or hostname in the printer address field and the connection type is a network type, THE Protocol_Detector SHALL probe the address to detect the printer protocol.
2. THE Protocol_Detector SHALL probe the Star WebPRNT endpoint (`http://<address>/StarWebPRNT/SendMessage`) with an HTTP GET or OPTIONS request and consider the printer a Star printer if the endpoint responds with a 2xx or 405 status.
3. THE Protocol_Detector SHALL probe the Epson ePOS endpoint (`http://<address>/cgi-bin/epos/service.cgi`) with an HTTP GET or OPTIONS request and consider the printer an Epson printer if the endpoint responds with a 2xx or 405 status.
4. IF neither the Star nor Epson endpoint responds, THEN THE Protocol_Detector SHALL default to `generic_http` as the detected protocol.
5. WHEN auto-detection completes, THE Printer_Settings_UI SHALL pre-select the detected connection type in the form and display a message indicating the detected protocol.
6. THE Protocol_Detector SHALL complete all probes within 5 seconds total, using an AbortController to cancel pending requests after the timeout.
7. WHILE auto-detection is in progress, THE Printer_Settings_UI SHALL display a loading indicator next to the address field.

### Requirement 7: Connection Type Expansion

**User Story:** As a POS operator, I want to select the specific printer protocol when adding a printer, so that OraInvoice uses the correct communication method for my printer.

#### Acceptance Criteria

1. THE Printer_Settings_UI SHALL display the following connection type options: USB, Bluetooth, Star WebPRNT, Epson ePOS, Generic HTTP, and Browser Print.
2. WHEN the user selects Star WebPRNT, Epson ePOS, or Generic HTTP, THE Printer_Settings_UI SHALL display the IP address / URL input field.
3. WHEN the user selects USB, THE Printer_Settings_UI SHALL hide the address field (USB uses WebUSB device picker).
4. WHEN the user selects Bluetooth, THE Printer_Settings_UI SHALL hide the address field (Bluetooth uses Web Bluetooth device picker).
5. WHEN the user selects Browser Print, THE Printer_Settings_UI SHALL hide the address field (browser print uses the OS print dialog).
6. THE backend printer schema SHALL accept connection type values: `usb`, `bluetooth`, `star_webprnt`, `epson_epos`, `generic_http`, `browser_print`.
7. THE backend printer schema SHALL continue to accept the legacy value `network` and treat it as `generic_http` for backward compatibility with existing printer configurations.

### Requirement 8: Test Print

**User Story:** As a POS operator, I want to send a test print that uses the correct protocol for my printer, so that I can verify my printer is configured correctly before printing real receipts.

#### Acceptance Criteria

1. WHEN the user clicks the Test button for a printer, THE Printer_Connection_Manager SHALL connect using the protocol matching the printer's connection type and send a test receipt.
2. THE test receipt SHALL contain the printer name, a "TEST PRINT" heading, the text "Printer is working!", and the current date and time.
3. WHEN the test print completes successfully, THE Printer_Settings_UI SHALL display a success message.
4. IF the test print fails, THEN THE Printer_Settings_UI SHALL display an error message containing the failure reason.
5. WHILE a test print is in progress, THE Printer_Settings_UI SHALL disable the Test button for that printer and display a "Testing…" label.

### Requirement 9: Browser-Side Print Execution

**User Story:** As a business owner using a cloud-hosted invoicing platform, I want all print data to be sent directly from the browser to the printer, so that my LAN printers remain accessible without exposing them to the internet.

#### Acceptance Criteria

1. THE Printer_Connection_Manager SHALL send all print data directly from the browser to the printer without routing through the backend server.
2. THE backend API SHALL store printer configuration (name, connection type, address, paper width) only and SHALL NOT send print data to printers.
3. WHEN a print job is initiated, THE Printer_Connection_Manager SHALL retrieve the printer configuration from the frontend state and establish a direct browser-to-printer connection.

### Requirement 10: Backward Compatibility

**User Story:** As an existing user with printers already configured, I want my existing printer configurations to continue working after the update, so that I don't need to reconfigure my printers.

#### Acceptance Criteria

1. WHEN the application loads a printer configuration with connection type `network`, THE Printer_Connection_Manager SHALL treat it as `generic_http` and use the Generic_HTTP_Driver.
2. WHEN the application loads a printer configuration with connection type `usb`, THE Printer_Connection_Manager SHALL continue to use the existing WebUSB connection logic.
3. WHEN the application loads a printer configuration with connection type `bluetooth`, THE Printer_Connection_Manager SHALL continue to use the existing Web Bluetooth connection logic.
4. THE database migration for the expanded connection types SHALL NOT modify existing rows in the `printer_configs` table.
