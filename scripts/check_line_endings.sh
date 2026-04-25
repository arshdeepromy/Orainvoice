#!/bin/bash
echo "=== Line count comparison ==="
echo "--- Pi service.py ---"
wc -l /home/nerdy/invoicing/app/modules/invoices/service.py
echo "--- Pi template_registry.py ---"
wc -l /home/nerdy/invoicing/app/modules/invoices/template_registry.py

echo ""
echo "=== Check for CRLF in Pi files ==="
echo "--- service.py CRLF count ---"
grep -cP '\r' /home/nerdy/invoicing/app/modules/invoices/service.py || echo "0 (no CRLF)"
echo "--- template_registry.py CRLF count ---"
grep -cP '\r' /home/nerdy/invoicing/app/modules/invoices/template_registry.py || echo "0 (no CRLF)"

echo ""
echo "=== Check specific content - template switching code ==="
grep -n "invoice_template_id\|template_file\|get_template_metadata" /home/nerdy/invoicing/app/modules/invoices/service.py | tail -10

echo ""
echo "=== Check if org settings save endpoint exists ==="
grep -n "invoice_template_id" /home/nerdy/invoicing/app/modules/organisations/service.py 2>/dev/null | head -5
grep -n "invoice_template_id" /home/nerdy/invoicing/app/modules/organisations/router.py 2>/dev/null | head -5
