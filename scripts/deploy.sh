#!/bin/bash
# ---------------------------------------------------------------------------
# OraInvoice Deploy Script
#
# Detects the host's LAN IP on the host machine (before Docker starts),
# writes it to HA_LOCAL_LAN_IP in the .env file, then starts the stack.
#
# Usage:
#   ./scripts/deploy.sh                          # Primary (dev)
#   ./scripts/deploy.sh --standby                # HA Standby (dev)
#   ./scripts/deploy.sh --pi                     # Primary (Pi prod)
#   ./scripts/deploy.sh --standby --pi           # HA Standby on Pi
#   ./scripts/deploy.sh --standby-prod           # Standby Prod (local)
# ---------------------------------------------------------------------------
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# ---------------------------------------------------------------------------
# Detect host LAN IP (runs on the host, not inside Docker)
# ---------------------------------------------------------------------------
detect_lan_ip() {
    # Method 1: ip route get to a known external IP — picks the right interface
    local ip
    ip=$(ip route get 8.8.8.8 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1); exit}')
    if [ -n "$ip" ] && [ "$ip" != "127.0.0.1" ]; then
        echo "$ip"
        return
    fi

    # Method 2: hostname -I (first non-loopback IP)
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    if [ -n "$ip" ] && [ "$ip" != "127.0.0.1" ]; then
        echo "$ip"
        return
    fi

    # Method 3: ifconfig fallback
    ip=$(ifconfig 2>/dev/null | grep -oP 'inet \K[0-9.]+' | grep -v '127.0.0.1' | grep -v '172\.' | head -1)
    if [ -n "$ip" ]; then
        echo "$ip"
        return
    fi

    echo "127.0.0.1"
}

# ---------------------------------------------------------------------------
# Update HA_LOCAL_LAN_IP in an env file
# ---------------------------------------------------------------------------
set_lan_ip_in_env() {
    local env_file="$1"
    local lan_ip="$2"

    if [ ! -f "$env_file" ]; then
        echo "HA_LOCAL_LAN_IP=$lan_ip" > "$env_file"
        return
    fi

    # Remove existing HA_LOCAL_LAN_IP line(s) and re-add with correct value
    if grep -q "^HA_LOCAL_LAN_IP=" "$env_file" 2>/dev/null; then
        sed -i "s|^HA_LOCAL_LAN_IP=.*|HA_LOCAL_LAN_IP=$lan_ip|" "$env_file"
    else
        echo "" >> "$env_file"
        echo "# HA: Host LAN IP (auto-detected by deploy.sh)" >> "$env_file"
        echo "HA_LOCAL_LAN_IP=$lan_ip" >> "$env_file"
    fi
}

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
MODE="primary"
PLATFORM="dev"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --standby)      MODE="standby"; shift ;;
        --standby-prod) MODE="standby-prod"; shift ;;
        --pi)           PLATFORM="pi"; shift ;;
        --help|-h)
            echo "Usage: $0 [--standby|--standby-prod] [--pi]"
            echo ""
            echo "  (no flags)       Primary dev stack (docker-compose.yml + dev.yml)"
            echo "  --standby        HA Standby dev stack (docker-compose.ha-standby.yml)"
            echo "  --standby-prod   Standby Prod stack (docker-compose.standby-prod.yml)"
            echo "  --pi             Use Pi production compose overlay"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Detect and store LAN IP
# ---------------------------------------------------------------------------
LAN_IP=$(detect_lan_ip)
echo "==> Detected host LAN IP: $LAN_IP"

# ---------------------------------------------------------------------------
# Deploy based on mode
# ---------------------------------------------------------------------------
case "$MODE" in
    primary)
        if [ "$PLATFORM" = "pi" ]; then
            ENV_FILE=".env.pi"
            set_lan_ip_in_env "$ENV_FILE" "$LAN_IP"
            echo "==> Starting primary (Pi prod)..."
            docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d --build --force-recreate
        else
            ENV_FILE=".env"
            set_lan_ip_in_env "$ENV_FILE" "$LAN_IP"
            echo "==> Starting primary (dev)..."
            docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build --force-recreate
        fi
        ;;
    standby)
        ENV_FILE=".env.ha-standby"
        set_lan_ip_in_env "$ENV_FILE" "$LAN_IP"
        echo "==> Starting HA standby (dev)..."
        docker compose -p invoicing-standby -f docker-compose.ha-standby.yml up -d --build --force-recreate
        ;;
    standby-prod)
        ENV_FILE=".env.standby-prod"
        set_lan_ip_in_env "$ENV_FILE" "$LAN_IP"
        echo "==> Starting standby prod..."
        docker compose -p invoicing-standby-prod -f docker-compose.standby-prod.yml up -d --build --force-recreate
        ;;
esac

echo "==> Deploy complete. LAN IP: $LAN_IP (stored in $ENV_FILE)"
