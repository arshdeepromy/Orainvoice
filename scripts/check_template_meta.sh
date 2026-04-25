#!/bin/bash
echo "=== get_template_metadata('classic') ==="
docker exec invoicing-app-1 python -c "
from app.modules.invoices.template_registry import get_template_metadata
meta = get_template_metadata('classic')
if meta:
    print(f'id={meta.id}, file={meta.template_file}, name={meta.name}')
else:
    print('NOT FOUND')
"

echo ""
echo "=== list_templates() ==="
docker exec invoicing-app-1 python -c "
from app.modules.invoices.template_registry import list_templates
for t in list_templates():
    print(f\"  {t['id']}: {t['template_file']} - {t['name']}\")
"

echo ""
echo "=== Actual template_dir resolution ==="
docker exec invoicing-app-1 python -c "
import pathlib
service_file = pathlib.Path('/app/app/modules/invoices/service.py')
template_dir = service_file.resolve().parent.parent.parent / 'templates' / 'pdf'
print(f'template_dir = {template_dir}')
print(f'exists = {template_dir.exists()}')
import os
files = [f for f in os.listdir(template_dir) if f.endswith('.html')]
print(f'html files: {sorted(files)}')
"
