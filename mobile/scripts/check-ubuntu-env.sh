#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# OraInvoice — Ubuntu Android Dev Environment Check
#
# Run: ./scripts/check-ubuntu-env.sh
# Checks all prerequisites for Capacitor Android development on Ubuntu.
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

PASS="\033[0;32m✔ PASS\033[0m"
FAIL="\033[0;31m✘ FAIL\033[0m"
WARN="\033[0;33m⚠ WARN\033[0m"

passed=0
failed=0

check() {
  local label="$1"
  local result="$2"  # 0 = pass, 1 = fail
  local fix="${3:-}"

  if [ "$result" -eq 0 ]; then
    echo -e "  $PASS  $label"
    ((passed++))
  else
    echo -e "  $FAIL  $label"
    [ -n "$fix" ] && echo -e "         Fix: $fix"
    ((failed++))
  fi
}

echo ""
echo "🔍 OraInvoice — Ubuntu Android Dev Environment Check"
echo "───────────────────────────────────────────────────────"
echo ""

# ── 1. Java 21 ────────────────────────────────────────────────────────
echo "Java:"
if command -v java &>/dev/null; then
  java_ver=$(java -version 2>&1 | head -1 | grep -oP '"\K[^"]+' || echo "unknown")
  java_major=$(echo "$java_ver" | cut -d. -f1)
  if [ "$java_major" -ge 17 ] 2>/dev/null; then
    check "Java $java_ver installed (need 17+)" 0
  else
    check "Java $java_ver installed — need 17+" 1 \
      "sudo apt install openjdk-21-jdk"
  fi
else
  check "Java not found" 1 \
    "sudo apt install openjdk-21-jdk"
fi
echo ""

# ── 2. KVM virtualisation ─────────────────────────────────────────────
echo "KVM (hardware acceleration for emulator):"
if [ -e /dev/kvm ]; then
  check "/dev/kvm exists" 0
else
  cpu_flags=$(grep -cE '(vmx|svm)' /proc/cpuinfo 2>/dev/null || echo "0")
  if [ "$cpu_flags" -gt 0 ]; then
    check "CPU supports virtualisation but /dev/kvm missing" 1 \
      "sudo apt install qemu-kvm && sudo modprobe kvm"
  else
    check "CPU does not support hardware virtualisation" 1 \
      "Enable VT-x/AMD-V in BIOS, then: sudo apt install qemu-kvm"
  fi
fi

# Check kvm group membership
if groups "$USER" 2>/dev/null | grep -qw kvm; then
  check "User '$USER' is in kvm group" 0
else
  check "User '$USER' NOT in kvm group" 1 \
    "sudo usermod -aG kvm $USER && newgrp kvm  (then log out and back in)"
fi
echo ""

# ── 3. ANDROID_HOME ───────────────────────────────────────────────────
echo "Android SDK:"
if [ -n "${ANDROID_HOME:-}" ] && [ -d "$ANDROID_HOME" ]; then
  check "ANDROID_HOME=$ANDROID_HOME" 0
else
  check "ANDROID_HOME not set or directory missing" 1 \
    "Add to ~/.bashrc: export ANDROID_HOME=\$HOME/Android/Sdk"
fi
echo ""

# ── 4. adb on PATH ───────────────────────────────────────────────────
echo "CLI tools:"
if command -v adb &>/dev/null; then
  adb_ver=$(adb version 2>&1 | head -1 || echo "unknown")
  check "adb found: $adb_ver" 0
else
  check "adb not on PATH" 1 \
    "Add to ~/.bashrc: export PATH=\$PATH:\$ANDROID_HOME/platform-tools"
fi

# ── 5. emulator on PATH ──────────────────────────────────────────────
if command -v emulator &>/dev/null; then
  emu_ver=$(emulator -version 2>&1 | head -1 || echo "unknown")
  check "emulator found: $emu_ver" 0
else
  check "emulator not on PATH" 1 \
    "Add to ~/.bashrc: export PATH=\$PATH:\$ANDROID_HOME/emulator"
fi

# ── 6. Node.js ────────────────────────────────────────────────────────
if command -v node &>/dev/null; then
  node_ver=$(node -v)
  check "Node.js $node_ver" 0
else
  check "Node.js not found" 1 \
    "Install Node 20+ via nvm or apt"
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────
echo "───────────────────────────────────────────────────────"
echo -e "  Results: \033[0;32m$passed passed\033[0m, \033[0;31m$failed failed\033[0m"
echo ""

if [ "$failed" -gt 0 ]; then
  echo "  Fix the failures above, then re-run this script."
  exit 1
else
  echo "  All checks passed — ready for Android development! 🚀"
  exit 0
fi
