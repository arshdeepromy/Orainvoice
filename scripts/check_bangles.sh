#!/bin/bash
docker exec invoicing-postgres-1 psql -U postgres workshoppro -c "SELECT settings FROM organisations WHERE name = 'Bangles & Bling'" -t
