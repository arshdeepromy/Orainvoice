#!/bin/bash
echo "=== Template registry ==="
docker exec invoicing-app-1 python -c "
from app.modules.invoices.template_registry import get_all_templates
for t in get_all_templates():
    print(f'{t.id}: file={t.template_file}')
"

echo ""
echo "=== Template files in container ==="
docker exec invoicing-app-1 ls -la app/templates/pdf/*.html

echo ""
echo "=== Bangles org template setting ==="
docker exec invoicing-postgres-1 psql -U postgres workshoppro -tAc "SELECT settings->>'invoice_template_id' FROM organisations WHERE name = 'Bangles & Bling'"
