#!/bin/bash
echo "=== Current template for Bangles & Bling ==="
docker exec invoicing-postgres-1 psql -U postgres workshoppro -tAc "SELECT settings->>'invoice_template_id' FROM organisations WHERE name = 'Bangles & Bling'"

echo ""
echo "=== Check app logs for template-related activity ==="
docker logs invoicing-app-1 --tail 200 2>&1 | grep -i "template\|settings.*update\|PUT.*settings\|PUT.*configure" | tail -15

echo ""
echo "=== Check if Jinja2 caches templates ==="
docker exec invoicing-app-1 python -c "
from jinja2 import Environment, FileSystemLoader
import pathlib
template_dir = pathlib.Path('/app/app/templates/pdf')
env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
print(f'auto_reload={env.auto_reload}')
print(f'cache size={len(env._cache) if hasattr(env, \"_cache\") else \"N/A\"}')
# Check if bytecode cache is enabled
print(f'bytecode_cache={env.bytecode_cache}')
"

echo ""
echo "=== Check gunicorn workers (multiple workers = each has own Jinja cache) ==="
docker exec invoicing-app-1 ps aux | grep gunicorn
