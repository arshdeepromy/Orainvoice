# Requirements Document

## Introduction

Integration of physical EFTPOS terminals (Verifone or similar) with the cloud-hosted OraInvoice system. Merchants install a lightweight Bridge Agent application on a local computer sharing the same network as their EFTPOS terminal. The Bridge Agent connects outbound to OraInvoice via WebSocket, relaying payment commands between the cloud platform and the local terminal. When a staff member clicks "Charge via EFTPOS" on an invoice, the payment amount is sent to the terminal, the customer taps or swipes their card, and the result flows back to automatically update the invoice status. Configuration is managed through a new EFTPOS Connect section under Settings > Integrations, accessible only to the Org Admin role. The Bridge Agent is distributed as pre-built binaries for Windows, macOS (Intel and Apple Silicon), Linux (x64), Linux ARM, and Raspberry Pi, with each download pre-configured with the organisation's encrypted API key.

## Glossary

- **EFTPOS_Config**: The `eftpos_configs` database table storing per-organisation EFTPOS terminal configuration including terminal IP, port, brand, API key, and enabled status.
- **EFTPOS_Transaction_Log**: The `eftpos_transaction_logs` database table recording every EFTPOS payment attempt with status, amount, card type, authorisation code, and timestamps.
- **Bridge_Agent**: A standalone Python application compiled via PyInstaller that merchants install on a local computer on the same network as their EFTPOS terminal. The Bridge_Agent connects outbound to OraInvoice cloud via WebSocket and relays payment commands between the cloud and the local terminal.
- **Bridge_WebSocket**: The WebSocket endpoint at `/ws/eftpos/{org_id}` that the Bridge_Agent connects to and maintains a persistent connection with the OraInvoice cloud server.

- **EFTPOS_API_Key**: A unique, auto-generated API key stored encrypted in the EFTPOS_Config table using the existing `EncryptedString` column type. Used to authenticate Bridge_Agent connections.
- **EFTPOS_Settings_Page**: The frontend settings section under Settings > Integrations for configuring EFTPOS terminal details, testing connectivity, and downloading the Bridge_Agent.
- **EFTPOS_Router**: The backend FastAPI router at `/api/v2/eftpos` providing endpoints for EFTPOS configuration, payment triggering, result handling, and bridge status.
- **Payment_Service**: The existing `app/modules/payments/service.py` module responsible for recording payments against invoices.
- **Invoice_Service**: The existing `app/modules/invoices/service.py` module responsible for invoice lifecycle operations including status updates and email dispatch.
- **Org_Admin**: The `org_admin` role as defined in `app/modules/auth/rbac.py`, the only role permitted to access EFTPOS configuration endpoints.
- **Terminal_Brand**: An enumeration of supported EFTPOS terminal brands (e.g. Verifone, Ingenico, PAX) stored in the EFTPOS_Config.

## Requirements

### Requirement 1: EFTPOS Configuration Storage

**User Story:** As an Org Admin, I want to store my EFTPOS terminal configuration per organisation, so that the system knows how to communicate with my terminal.

#### Acceptance Criteria

1. THE EFTPOS_Config table SHALL store terminal_ip (string), terminal_port (integer), terminal_brand (string), api_key (encrypted string), is_enabled (boolean), and org_id (UUID foreign key to organisations) for each organisation.
2. THE EFTPOS_Config table SHALL enforce a unique constraint on org_id so that each organisation has at most one EFTPOS configuration record.
3. WHEN an Org_Admin enables EFTPOS for the first time, THE EFTPOS_Router SHALL auto-generate a cryptographically secure EFTPOS_API_Key and store it encrypted in the EFTPOS_Config record using the existing `EncryptedString` column type.
4. THE EFTPOS_Config table SHALL store created_at and updated_at timestamps with timezone.
5. THE EFTPOS_Config table SHALL have Row-Level Security (RLS) enabled, scoped to org_id, following the same RLS pattern used by existing organisation-scoped tables.

### Requirement 2: EFTPOS Configuration API

**User Story:** As an Org Admin, I want to create, read, update, and regenerate my EFTPOS configuration via API endpoints, so that I can manage my terminal settings.

#### Acceptance Criteria

1. THE EFTPOS_Router SHALL expose a GET endpoint at `/api/v2/eftpos/config` that returns the current EFTPOS_Config for the authenticated organisation.
2. THE EFTPOS_Router SHALL expose a PUT endpoint at `/api/v2/eftpos/config` that creates or updates the EFTPOS_Config for the authenticated organisation.
3. THE EFTPOS_Router SHALL expose a POST endpoint at `/api/v2/eftpos/config/regenerate-key` that generates a new EFTPOS_API_Key, stores it encrypted, and returns the new plaintext key to the caller exactly once.
4. WHEN a non-Org_Admin role calls any EFTPOS configuration endpoint, THE EFTPOS_Router SHALL return HTTP 403 with a descriptive error message.
5. THE EFTPOS_Router SHALL validate that terminal_ip is a valid IPv4 address and terminal_port is an integer between 1 and 65535 before saving.
6. THE EFTPOS_Router SHALL validate that terminal_brand is one of the supported Terminal_Brand values before saving.


### Requirement 3: Bridge Agent WebSocket Connection

**User Story:** As a merchant, I want my Bridge Agent to maintain a persistent WebSocket connection to OraInvoice cloud, so that payment commands can be relayed in real time without port forwarding.

#### Acceptance Criteria

1. THE Bridge_WebSocket endpoint SHALL accept WebSocket connections at `/ws/eftpos/{org_id}` and authenticate the connection using the EFTPOS_API_Key provided in the WebSocket handshake headers.
2. IF a Bridge_Agent connects with an invalid or missing EFTPOS_API_Key, THEN THE Bridge_WebSocket SHALL reject the connection with WebSocket close code 4001 and reason "Authentication failed".
3. WHILE a Bridge_Agent is connected to the Bridge_WebSocket, THE EFTPOS_Router SHALL track the connection status as "connected" for the corresponding organisation.
4. WHEN a Bridge_Agent disconnects from the Bridge_WebSocket, THE EFTPOS_Router SHALL update the connection status to "disconnected" for the corresponding organisation.
5. THE Bridge_WebSocket SHALL send periodic ping frames every 30 seconds to detect stale connections.
6. THE Bridge_WebSocket SHALL support only one active Bridge_Agent connection per organisation at a time; IF a second Bridge_Agent connects for the same organisation, THEN THE Bridge_WebSocket SHALL close the previous connection with close code 4002 and reason "Replaced by new connection".

### Requirement 4: Payment Trigger and Result Flow

**User Story:** As a staff member, I want to trigger an EFTPOS payment from an invoice and receive the result automatically, so that I do not need to manually reconcile terminal payments.

#### Acceptance Criteria

1. THE EFTPOS_Router SHALL expose a POST endpoint at `/api/v2/eftpos/charge` that accepts an invoice_id and amount, validates the invoice exists and belongs to the authenticated organisation, and sends a payment command to the connected Bridge_Agent via the Bridge_WebSocket.
2. IF no Bridge_Agent is connected for the organisation when a charge is requested, THEN THE EFTPOS_Router SHALL return HTTP 409 with the message "EFTPOS terminal not connected".
3. WHEN the Bridge_Agent receives a payment command, THE Bridge_Agent SHALL forward the payment request to the local EFTPOS terminal using the configured terminal_ip and terminal_port.
4. WHEN the EFTPOS terminal returns an approved result, THE Bridge_Agent SHALL send the approval response (including authorisation code, card type, and masked card number) back to the OraInvoice cloud via the Bridge_WebSocket.
5. WHEN the OraInvoice cloud receives an approved payment result, THE EFTPOS_Router SHALL record the payment against the invoice using the existing Payment_Service, update the invoice status to "paid" using the existing Invoice_Service, and trigger the paid invoice email to the customer.
6. WHEN the EFTPOS terminal returns a declined result, THE Bridge_Agent SHALL send the decline response (including decline reason) back to the OraInvoice cloud via the Bridge_WebSocket.
7. WHEN the OraInvoice cloud receives a declined payment result, THE EFTPOS_Router SHALL return the declined status and reason to the frontend without recording a payment.
8. IF the Bridge_Agent does not respond within 120 seconds of a charge request, THEN THE EFTPOS_Router SHALL return a timeout error to the frontend.


### Requirement 5: EFTPOS Transaction Logging

**User Story:** As an Org Admin, I want all EFTPOS payment attempts logged with full details, so that I have an audit trail for reconciliation and troubleshooting.

#### Acceptance Criteria

1. THE EFTPOS_Transaction_Log table SHALL store org_id, invoice_id, amount, status (pending, approved, declined, timeout, error), card_type, masked_card_number, auth_code, decline_reason, terminal_brand, created_at, and completed_at for each transaction attempt.
2. WHEN a charge request is initiated, THE EFTPOS_Router SHALL create an EFTPOS_Transaction_Log record with status "pending".
3. WHEN a payment result is received (approved, declined, or error), THE EFTPOS_Router SHALL update the corresponding EFTPOS_Transaction_Log record with the final status, card details, and completed_at timestamp.
4. IF a charge request times out, THEN THE EFTPOS_Router SHALL update the corresponding EFTPOS_Transaction_Log record with status "timeout" and completed_at timestamp.
5. THE EFTPOS_Transaction_Log table SHALL have Row-Level Security (RLS) enabled, scoped to org_id.
6. THE EFTPOS_Router SHALL expose a GET endpoint at `/api/v2/eftpos/transactions` that returns paginated EFTPOS_Transaction_Log records for the authenticated organisation, accessible to Org_Admin role only.

### Requirement 6: Bridge Status Endpoint

**User Story:** As a frontend application, I want to check whether the Bridge Agent is currently connected, so that I can show the correct UI state to the user.

#### Acceptance Criteria

1. THE EFTPOS_Router SHALL expose a GET endpoint at `/api/v2/eftpos/bridge-status` that returns the current connection status ("connected" or "disconnected") and the last_seen timestamp for the authenticated organisation's Bridge_Agent.
2. THE bridge-status endpoint SHALL be accessible to any authenticated organisation member (Org_Admin, Salesperson, Location_Manager, Staff_Member).
3. WHEN the Bridge_Agent is connected, THE bridge-status endpoint SHALL return `{"status": "connected", "last_seen": "<ISO timestamp>"}`.
4. WHEN no Bridge_Agent is connected, THE bridge-status endpoint SHALL return `{"status": "disconnected", "last_seen": "<ISO timestamp or null>"}`.

### Requirement 7: Connection Test Endpoint

**User Story:** As an Org Admin, I want to test the connection between OraInvoice cloud and my Bridge Agent, so that I can verify the setup is working before processing real payments.

#### Acceptance Criteria

1. THE EFTPOS_Router SHALL expose a POST endpoint at `/api/v2/eftpos/test-connection` that sends a ping command to the connected Bridge_Agent and waits for a pong response.
2. WHEN the Bridge_Agent responds to the ping within 10 seconds, THE test-connection endpoint SHALL return `{"status": "success", "latency_ms": <round-trip time>}`.
3. IF no Bridge_Agent is connected, THEN THE test-connection endpoint SHALL return HTTP 409 with the message "Bridge Agent not connected".
4. IF the Bridge_Agent does not respond within 10 seconds, THEN THE test-connection endpoint SHALL return `{"status": "timeout"}`.
5. THE test-connection endpoint SHALL be accessible to Org_Admin role only.


### Requirement 8: EFTPOS Settings Page

**User Story:** As an Org Admin, I want a dedicated EFTPOS Connect section in the Settings page where I can configure my terminal, test the connection, and download the Bridge Agent, so that I can set up EFTPOS integration from one place.

#### Acceptance Criteria

1. THE EFTPOS_Settings_Page SHALL appear as a new navigation item labelled "EFTPOS" with icon "💳" in the Settings sidebar, positioned after the "Accounting" item.
2. THE EFTPOS_Settings_Page SHALL only be visible and accessible to users with the Org_Admin role; non-Org_Admin users SHALL NOT see the EFTPOS navigation item.
3. THE EFTPOS_Settings_Page SHALL display input fields for Terminal IP address, Terminal Port (defaulting to 8000), and Terminal Brand (dropdown with supported brands).
4. THE EFTPOS_Settings_Page SHALL display a connection status badge showing "Connected" (green) or "Disconnected" (red) based on the bridge-status endpoint, polling every 10 seconds.
5. THE EFTPOS_Settings_Page SHALL display a "Test Connection" button that calls the test-connection endpoint and shows the result (success with latency, timeout, or not connected).
6. THE EFTPOS_Settings_Page SHALL display a "Regenerate API Key" button with a confirmation dialog warning that the current Bridge Agent will need to be re-downloaded.
7. THE EFTPOS_Settings_Page SHALL display a "Save" button that persists the terminal configuration via the PUT config endpoint.
8. WHEN the configuration is saved successfully, THE EFTPOS_Settings_Page SHALL display a success toast notification.
9. IF the configuration save fails due to validation errors, THEN THE EFTPOS_Settings_Page SHALL display the validation error messages inline below the corresponding fields.

### Requirement 9: Bridge Agent Download Section

**User Story:** As an Org Admin, I want to download the Bridge Agent for my platform with my API key pre-embedded, so that I can install it without manual configuration.

#### Acceptance Criteria

1. THE EFTPOS_Settings_Page SHALL display a "Download Bridge Agent" section with platform selector buttons for: Windows, Mac (Intel), Mac (Apple Silicon), Linux (x64), Linux ARM, and Raspberry Pi.
2. WHEN the Org_Admin clicks a platform download button, THE EFTPOS_Router SHALL serve a pre-built Bridge_Agent binary for the selected platform with the organisation's encrypted EFTPOS_API_Key injected into the binary configuration.
3. THE download endpoint SHALL serve files named: OraInvoiceBridge-windows.exe, OraInvoiceBridge-mac-intel, OraInvoiceBridge-mac-arm, OraInvoiceBridge-linux-x64, OraInvoiceBridge-linux-arm, OraInvoiceBridge-raspberry-pi.
4. IF the organisation does not have an EFTPOS_Config record with a generated API key, THEN THE download endpoint SHALL return HTTP 400 with the message "Please save your EFTPOS configuration first".
5. THE download endpoint SHALL be accessible to Org_Admin role only.

### Requirement 10: Setup Guide Display

**User Story:** As an Org Admin, I want to see step-by-step setup instructions on the EFTPOS settings page, so that I can configure the integration without external documentation.

#### Acceptance Criteria

1. THE EFTPOS_Settings_Page SHALL display an inline setup guide section with the following ordered steps: (1) Download the Bridge Agent for your platform, (2) Run the installer on any PC on the same network as your terminal, (3) Enter your terminal's IP address in the field above, (4) Click Test Connection to verify everything works, (5) You're ready — the EFTPOS button will appear on invoices.
2. THE setup guide SHALL be displayed in a visually distinct card or panel below the configuration fields.
3. EACH step in the setup guide SHALL display a step number, instruction text, and a status indicator showing whether that step has been completed (configuration saved, bridge connected, test passed).


### Requirement 11: Invoice Page EFTPOS Charge Button

**User Story:** As a staff member, I want to see a "Charge via EFTPOS" button on the invoice detail page, so that I can initiate a terminal payment directly from the invoice.

#### Acceptance Criteria

1. WHILE the organisation has an EFTPOS_Config record with is_enabled set to true, THE InvoiceDetail page SHALL display a "Charge via EFTPOS" button in the action buttons area alongside existing buttons (Duplicate, Void, Email, Print, Download PDF).
2. WHILE the organisation does not have EFTPOS enabled, THE InvoiceDetail page SHALL NOT display the "Charge via EFTPOS" button.
3. WHILE the invoice status is "paid" or "voided", THE InvoiceDetail page SHALL NOT display the "Charge via EFTPOS" button.
4. WHEN the staff member clicks the "Charge via EFTPOS" button, THE InvoiceDetail page SHALL display a modal with a waiting spinner and the message "Waiting for card tap..." while the charge is in progress.
5. WHEN the charge is approved, THE InvoiceDetail page SHALL display a green success message with the authorisation code, automatically refresh the invoice data to show the updated "paid" status, and close the modal after 3 seconds.
6. WHEN the charge is declined, THE InvoiceDetail page SHALL display a red declined message with the decline reason, and show "Try Again" and "Cancel" buttons.
7. IF the Bridge_Agent is not connected when the charge button is clicked, THEN THE InvoiceDetail page SHALL display a warning message "EFTPOS terminal not connected. Please check your Bridge Agent is running." without sending a charge request.
8. THE "Charge via EFTPOS" button SHALL send the invoice's balance_due amount as the charge amount.

### Requirement 12: Bridge Agent Application

**User Story:** As a merchant, I want a lightweight desktop application that connects my local EFTPOS terminal to OraInvoice cloud, so that I can process card payments from the cloud system.

#### Acceptance Criteria

1. THE Bridge_Agent SHALL be built as a standalone Python application compiled via PyInstaller into platform-specific binaries for: Windows (x64), macOS Intel, macOS Apple Silicon, Linux x64, Linux ARM, and Raspberry Pi (ARM).
2. THE Bridge_Agent SHALL connect outbound to the OraInvoice cloud Bridge_WebSocket endpoint using the pre-embedded encrypted EFTPOS_API_Key for authentication, requiring no inbound port forwarding on the merchant's network.
3. THE Bridge_Agent SHALL automatically reconnect to the Bridge_WebSocket with exponential backoff (starting at 1 second, maximum 60 seconds) when the connection drops.
4. THE Bridge_Agent SHALL display a simple status window showing: connection status (connected/disconnected), last transaction details (time, amount, status), and the configured terminal IP address.
5. THE Bridge_Agent SHALL run as a background service or daemon that survives system reboots on all supported platforms.
6. WHEN the Bridge_Agent receives a payment command from the Bridge_WebSocket, THE Bridge_Agent SHALL forward the payment request to the local EFTPOS terminal at the configured terminal_ip and terminal_port using the appropriate terminal protocol for the configured Terminal_Brand.
7. WHEN the Bridge_Agent receives a ping command from the Bridge_WebSocket, THE Bridge_Agent SHALL respond with a pong message including the current timestamp.
8. THE Bridge_Agent SHALL log all operations to a local log file for troubleshooting.

### Requirement 13: Binary Download Serving with Key Injection

**User Story:** As a system, I want to inject the organisation's encrypted API key into pre-built Bridge Agent binaries at download time, so that each download is pre-configured for the specific organisation.

#### Acceptance Criteria

1. THE EFTPOS_Router SHALL expose a GET endpoint at `/api/v2/eftpos/download/{platform}` where platform is one of: windows, mac-intel, mac-arm, linux-x64, linux-arm, raspberry-pi.
2. THE download endpoint SHALL read the pre-built binary template for the requested platform from the server's file system.
3. THE download endpoint SHALL locate a placeholder marker in the binary template and replace it with the organisation's encrypted EFTPOS_API_Key and the WebSocket endpoint URL.
4. THE download endpoint SHALL serve the modified binary with appropriate Content-Disposition headers for file download.
5. IF the requested platform is not one of the supported values, THEN THE download endpoint SHALL return HTTP 400 with the message "Unsupported platform".
6. THE download endpoint SHALL be accessible to Org_Admin role only.
