#!/bin/bash
echo "=== classic.html header block (lines 25-45) ==="
docker exec invoicing-app-1 sed -n '25,45p' app/templates/pdf/classic.html
echo ""
echo "=== _invoice_base.html header block (lines 138-160) ==="
docker exec invoicing-app-1 sed -n '138,160p' app/templates/pdf/_invoice_base.html
