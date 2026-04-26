#!/bin/bash
# Run on PRIMARY Pi - check standby postgres logs
ssh nerdy@192.168.10.87 << 'EOF'
sudo docker logs invoicing-postgres-1 --tail=50 2>&1
EOF
