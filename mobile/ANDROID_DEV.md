# OraInvoice — Android Development on Ubuntu

## First-time setup on Ubuntu (step by step)

### Step 1: Check your environment

```bash
cd mobile
npm run check:env
```

Fix anything that fails before continuing.

### Step 2: Install Java 21

```bash
sudo apt update
sudo apt install openjdk-21-jdk
java -version   # Should show 21.x
```

### Step 3: Enable KVM (emulator hardware acceleration)

```bash
# Check CPU supports virtualisation
grep -cE '(vmx|svm)' /proc/cpuinfo   # Should be > 0

# Install KVM
sudo apt install qemu-kvm libvirt-daemon-system

# Add your user to the kvm group
sudo usermod -aG kvm $USER

# Log out and back in, then verify
groups   # Should include 'kvm'
ls -la /dev/kvm   # Should exist and be accessible
```

### Step 4: Install Android Studio (recommended)

**Option A — Snap (easiest):**
```bash
sudo snap install android-studio --classic
```

**Option B — Tarball:**
```bash
# Download from https://developer.android.com/studio
tar -xzf android-studio-*.tar.gz -C ~/
~/android-studio/bin/studio.sh   # First launch
```

On first launch:
1. Accept SDK licences
2. Let it download SDK 34 and build tools
3. Go to **Device Manager** → **Create Virtual Device**
4. Select **Pixel 7** → **API 34** → **Google APIs** → **x86_64** image
5. Name it (default is fine, e.g. `Pixel_7_API_34`)
6. Finish — don't start it yet

### Step 4b: Command-line only (lightweight, no Android Studio GUI)

For headless servers or if you prefer CLI tools only:

```bash
# Download command-line tools
mkdir -p ~/Android/Sdk/cmdline-tools
cd ~/Android/Sdk/cmdline-tools
wget https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
unzip commandlinetools-linux-*.zip
mv cmdline-tools latest

# Accept licences
yes | ~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager --licenses

# Install required SDK components
~/Android/Sdk/cmdline-tools/latest/bin/sdkmanager \
  "platform-tools" \
  "platforms;android-34" \
  "build-tools;34.0.0" \
  "system-images;android-34;google_apis;x86_64" \
  "emulator"

# Create a Pixel 7 AVD
~/Android/Sdk/cmdline-tools/latest/bin/avdmanager create avd \
  -n Pixel_7_API_34 \
  -k "system-images;android-34;google_apis;x86_64" \
  -d pixel_7

# Verify
~/Android/Sdk/emulator/emulator -list-avds
# Should show: Pixel_7_API_34
```

> Recommend Android Studio for first-time users — the GUI makes AVD management
> and Gradle debugging much easier. Use CLI tools for CI or headless setups.

### Step 5: Set environment variables

Add to `~/.bashrc` (or `~/.zshrc`):

```bash
export ANDROID_HOME=$HOME/Android/Sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools
export PATH=$PATH:$ANDROID_HOME/emulator
export PATH=$PATH:$ANDROID_HOME/cmdline-tools/latest/bin
```

Then reload:
```bash
source ~/.bashrc
```

Verify:
```bash
adb version
emulator -list-avds
```

### Step 6: Install npm dependencies and sync

```bash
cd mobile
npm install
npm run cap:sync    # Builds web assets + syncs to Android project
```

### Step 7: Start the emulator

```bash
npm run emu:start
```

This launches the emulator with GPU acceleration, 4GB RAM, and 4 cores.
Wait for it to fully boot (home screen visible).

### Step 8: Run the app with live reload

In another terminal:

```bash
cd mobile
npm run android:dev
```

This will:
1. Detect the running emulator
2. Build and deploy the app
3. Start Vite dev server with live reload
4. Changes to source files will hot-reload on the emulator

### Subsequent dev sessions

Just run:
```bash
npm run android:dev
```

It auto-starts the emulator if none is running, waits for boot, then deploys.

---

## Prerequisites

| Tool | Version | Check | Install |
|------|---------|-------|---------|
| Node.js | 20+ | `node -v` | `nvm install 20` |
| JDK | 21 | `java -version` | `sudo apt install openjdk-21-jdk` |
| KVM | — | `ls /dev/kvm` | `sudo apt install qemu-kvm` |
| Android SDK | API 34 | `sdkmanager --list` | Android Studio or CLI tools |
| `ANDROID_HOME` | set | `echo $ANDROID_HOME` | Add to `~/.bashrc` |
| `adb` | on PATH | `adb version` | Add `$ANDROID_HOME/platform-tools` to PATH |
| `emulator` | on PATH | `emulator -list-avds` | Add `$ANDROID_HOME/emulator` to PATH |

---

## npm scripts reference

| Script | Description |
|--------|-------------|
| `npm run check:env` | Check Ubuntu prerequisites |
| `npm run android:dev` | Auto-start emulator + deploy with live reload |
| `npm run android:open` | Open project in Android Studio |
| `npm run android:build` | Build debug APK |
| `npm run android:release` | Build release APK |
| `npm run cap:sync` | Build web + sync to Android |
| `npm run emu:list` | List available AVDs |
| `npm run emu:start` | Start emulator with GPU accel, 4GB RAM, 4 cores |
| `npm run emu:wipe` | Start emulator with factory reset |
| `npm run emu:cold` | Start emulator without snapshot (cold boot) |

---

## Emulator performance flags

The `emu:start` and `android:dev` scripts use these flags for best performance:

| Flag | Purpose |
|------|---------|
| `-gpu host` | Use host GPU for rendering (much faster) |
| `-accel on` | Enable KVM hardware acceleration |
| `-memory 4096` | 4GB RAM for the emulator |
| `-cores 4` | Use 4 CPU cores |
| `-no-snapshot-load` | Fresh boot (avoids stale snapshot issues) |

If the emulator is slow, check:
1. KVM is enabled: `ls /dev/kvm`
2. You're using an x86_64 system image (not ARM)
3. GPU acceleration is working: `emulator -accel-check`

---

## Live reload: how it works

### On the emulator

The Android emulator uses `10.0.2.2` as an alias for the host machine's
`127.0.0.1`. When you run `npm run android:dev`, the script:

1. Starts Vite dev server on `0.0.0.0:5173`
2. Tells Capacitor to load from `http://10.0.2.2:5173/mobile/`
3. File changes trigger HMR through the Vite WebSocket

### On a real device (LAN)

```bash
CAPACITOR_SERVER_URL=http://192.168.1.50:5173/mobile/ npx cap run android --livereload --external
```

Replace `192.168.1.50` with your machine's LAN IP (`ip addr show`).

### Production build (no live reload)

```bash
npm run cap:sync    # Builds and bundles into the APK
npm run android:build
```

---

## Firebase (push notifications)

1. Create a Firebase project at https://console.firebase.google.com
2. Add an Android app with package name `nz.oraflows.orainvoice`
3. Download `google-services.json` into `android/app/`
4. Uncomment the google-services classpath in `android/build.gradle`
5. Uncomment the apply plugin line in `android/app/build.gradle`

See `android/app/google-services.json.example` for the expected structure.

> **Backend TODO:** The endpoint `POST /api/v1/notifications/devices/register`
> needs to be created to accept `{ token, platform }` for FCM device registration.

---

## Real device setup

1. Enable **Developer Options**: Settings → About Phone → tap **Build Number** 7 times
2. Enable **USB Debugging** in Developer Options
3. Connect via USB, accept the debugging prompt
4. Verify: `adb devices`

### Wireless debugging (Android 11+)

```bash
# On the device: Developer Options → Wireless Debugging → Pair device
adb pair <DEVICE_IP>:<PAIRING_PORT>    # Enter pairing code
adb connect <DEVICE_IP>:<DEBUG_PORT>
adb devices   # Should show the device
```

---

## Useful commands

| Command | Description |
|---------|-------------|
| `npx cap sync` | Sync web assets + plugins to Android |
| `npx cap copy android` | Copy web assets only (no plugin update) |
| `npx cap doctor` | Check Capacitor project health |
| `adb logcat \| grep -i capacitor` | View Capacitor logs |
| `adb logcat \| grep -i chromium` | View WebView console logs |
| `adb shell getprop sys.boot_completed` | Check if emulator has booted |

---

## Troubleshooting

**Emulator won't start:** Check KVM: `ls /dev/kvm`. If missing, install `qemu-kvm`
and add your user to the `kvm` group.

**Emulator is very slow:** Make sure you're using an x86_64 system image and
`-gpu host` flag. ARM images are 10x slower on x86 hosts.

**Gradle sync fails:** Ensure `ANDROID_HOME` is set and API 34 is installed.
Run `sdkmanager --list | grep 34` to check.

**White screen on emulator:** Run `npx cap sync` — web assets may be stale.

**Live reload not connecting:** The emulator reaches the host at `10.0.2.2`.
Make sure Vite is running on `0.0.0.0:5173` (not just `localhost`).

**"INSTALL_FAILED_OLDER_SDK":** Your emulator image is below API 23. Create a
new AVD with API 34.
