#!/bin/bash
docker exec invoicing-postgres-1 psql -U postgres workshoppro -tAc "SELECT settings->>'invoice_template_id' FROM organisations WHERE name = 'Bangles & Bling'"
