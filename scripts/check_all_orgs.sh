#!/bin/bash
docker exec invoicing-postgres-1 psql -U postgres workshoppro -c "SELECT id, name, substring(settings::text, 1, 200) as settings_preview FROM organisations"
