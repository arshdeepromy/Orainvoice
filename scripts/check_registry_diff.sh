#!/bin/bash
echo "=== TemplateMetadata fields ==="
docker exec invoicing-app-1 python -c "
from app.modules.invoices.template_registry import get_template_metadata
meta = get_template_metadata('classic')
print(vars(meta))
"

echo ""
echo "=== list_templates first entry ==="
docker exec invoicing-app-1 python -c "
from app.modules.invoices.template_registry import list_templates
templates = list_templates()
if templates:
    print(templates[0])
"

echo ""
echo "=== MD5 of template_registry.py ==="
docker exec invoicing-app-1 md5sum app/modules/invoices/template_registry.py

echo ""
echo "=== MD5 of service.py ==="
docker exec invoicing-app-1 md5sum app/modules/invoices/service.py
