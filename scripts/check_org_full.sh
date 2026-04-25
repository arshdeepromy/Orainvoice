#!/bin/bash
docker exec invoicing-postgres-1 psql -U postgres workshoppro -c "SELECT name, settings FROM organisations LIMIT 1" -x
