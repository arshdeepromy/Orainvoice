#!/bin/bash
echo "=== Docker image creation date ==="
docker inspect invoicing-app:latest --format='{{.Created}}'

echo ""
echo "=== Docker image layers ==="
docker history invoicing-app:latest --no-trunc --format='{{.CreatedAt}} {{.Size}} {{.Comment}}' | head -15

echo ""
echo "=== Files on disk vs in container ==="
echo "--- Disk service.py MD5 ---"
md5sum /home/nerdy/invoicing/app/modules/invoices/service.py
echo "--- Container service.py MD5 ---"
docker exec invoicing-app-1 md5sum app/modules/invoices/service.py

echo ""
echo "--- Disk template_registry.py MD5 ---"
md5sum /home/nerdy/invoicing/app/modules/invoices/template_registry.py
echo "--- Container template_registry.py MD5 ---"
docker exec invoicing-app-1 md5sum app/modules/invoices/template_registry.py
