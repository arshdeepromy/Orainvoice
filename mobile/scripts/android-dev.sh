#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# OraInvoice — Android Dev with Emulator Auto-Start
#
# 1. Checks if any device/emulator is running
# 2. If not, starts the first available AVD and waits for boot
# 3. Runs npx cap run android --livereload --external
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# ── Helper: get first running device/emulator ─────────────────────────
get_device() {
  adb devices 2>/dev/null | grep -E 'device$' | head -1 | awk '{print $1}'
}

# ── Helper: get first available AVD ───────────────────────────────────
get_avd() {
  emulator -list-avds 2>/dev/null | head -1
}

# ── Step 1: Check for running device ─────────────────────────────────
DEVICE=$(get_device)

if [ -n "$DEVICE" ]; then
  echo "✔ Device/emulator already running: $DEVICE"
else
  echo "No device/emulator running. Starting emulator..."

  AVD=$(get_avd)
  if [ -z "$AVD" ]; then
    echo "✘ No AVDs found. Create one first:"
    echo "  Android Studio → Device Manager → Create Virtual Device"
    echo "  Or: avdmanager create avd -n Pixel_7_API_34 -k 'system-images;android-34;google_apis;x86_64' -d pixel_7"
    exit 1
  fi

  echo "  Starting AVD: $AVD"
  echo "  (with GPU acceleration, 4GB RAM, 4 cores)"

  # Launch emulator in background with performance flags
  emulator -avd "$AVD" \
    -gpu host \
    -accel on \
    -memory 4096 \
    -cores 4 \
    -no-snapshot-load \
    &>/dev/null &

  EMU_PID=$!

  # Wait for the emulator to boot (up to 120 seconds)
  echo "  Waiting for emulator to boot..."
  TIMEOUT=120
  ELAPSED=0

  while [ $ELAPSED -lt $TIMEOUT ]; do
    BOOT_COMPLETE=$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || echo "")
    if [ "$BOOT_COMPLETE" = "1" ]; then
      echo "  ✔ Emulator booted in ${ELAPSED}s"
      break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
    # Print progress every 10 seconds
    if [ $((ELAPSED % 10)) -eq 0 ]; then
      echo "  ... still booting (${ELAPSED}s)"
    fi
  done

  if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "  ✘ Emulator boot timed out after ${TIMEOUT}s"
    echo "  Try starting it manually: emulator -avd $AVD"
    exit 1
  fi

  # Give it a moment to settle
  sleep 2
  DEVICE=$(get_device)
fi

if [ -z "$DEVICE" ]; then
  echo "✘ No device found after boot. Check adb devices."
  exit 1
fi

echo ""
echo "🚀 Running Capacitor on $DEVICE with live reload..."
echo "   Vite dev server will start automatically."
echo ""

# ── Step 3: Run with live reload ──────────────────────────────────────
npx cap run android --livereload --external --target="$DEVICE"
