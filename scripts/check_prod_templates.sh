#!/bin/bash
echo "=== Working directory ==="
docker exec invoicing-app-1 pwd

echo ""
echo "=== Find template files ==="
docker exec invoicing-app-1 find / -name "classic.html" -path "*/pdf/*" 2>/dev/null

echo ""
echo "=== Template registry functions ==="
docker exec invoicing-app-1 grep "^def \|^class " app/modules/invoices/template_registry.py

echo ""
echo "=== Template resolution in service.py ==="
docker exec invoicing-app-1 grep -n "template_id\|template_file\|invoice_template" app/modules/invoices/service.py | tail -20

echo ""
echo "=== Jinja2 template loader path ==="
docker exec invoicing-app-1 grep -n "template_dir\|FileSystemLoader" app/modules/invoices/service.py
