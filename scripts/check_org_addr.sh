#!/bin/bash
docker exec invoicing-postgres-1 psql -U postgres workshoppro -c "SELECT settings->>'address' as legacy_addr, settings->>'address_street' as street, settings->>'address_city' as city, settings->>'address_country' as country FROM organisations LIMIT 1"
