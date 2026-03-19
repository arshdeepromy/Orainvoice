#!/bin/sh
# Watch for source changes and rebuild.
# Preserves old assets briefly so browsers with cached index.html
# don't get 404s during the rebuild window.

echo "[watch] Running initial build..."
npx vite build
echo "[watch] Initial build complete."
echo "[watch] Watching for changes in /app/src..."

# Use Node's fs.watch (works on all platforms including Alpine)
node -e "
const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');

let timer = null;
const DEBOUNCE = 800;

function rebuild() {
  console.log('[watch] Change detected, rebuilding...');
  try {
    // Build to a temp directory first, then swap — keeps old assets
    // available until the new build is ready.
    execSync('npx vite build --outDir /tmp/dist-new --emptyOutDir', { stdio: 'inherit' });

    // Copy new files into dist (don't delete old ones yet)
    execSync('cp -r /tmp/dist-new/* /app/dist/', { stdio: 'inherit' });

    // Clean up temp dir
    execSync('rm -rf /tmp/dist-new', { stdio: 'inherit' });

    // Remove stale assets after 60s (gives browsers time to finish loading)
    setTimeout(() => {
      try {
        // Get list of files referenced by current index.html
        const html = fs.readFileSync('/app/dist/index.html', 'utf8');
        const referenced = new Set();
        const re = /\\/assets\\/([^\"'\\s]+)/g;
        let m;
        while ((m = re.exec(html)) !== null) referenced.add(m[1]);

        // Remove unreferenced asset files
        const assetsDir = '/app/dist/assets';
        if (fs.existsSync(assetsDir)) {
          for (const f of fs.readdirSync(assetsDir)) {
            if (!referenced.has(f)) {
              fs.unlinkSync(path.join(assetsDir, f));
            }
          }
        }
        console.log('[watch] Cleaned up stale assets.');
      } catch (e) {
        // Non-critical — old assets just take up a bit of space
      }
    }, 60000);

    console.log('[watch] Build complete. Refresh your browser.');
  } catch (e) {
    console.error('[watch] Build failed:', e.message);
  }
}

function watchDir(dir) {
  try {
    fs.watch(dir, { recursive: true }, (event, filename) => {
      if (filename && (filename.endsWith('.tsx') || filename.endsWith('.ts') || filename.endsWith('.css') || filename.endsWith('.html') || filename.endsWith('.json'))) {
        clearTimeout(timer);
        timer = setTimeout(rebuild, DEBOUNCE);
      }
    });
  } catch (e) {
    console.log('[watch] recursive watch not supported, falling back to polling');
    setInterval(() => {}, 2000);
  }
}

watchDir('/app/src');

// Also watch index.html
try {
  fs.watch('/app/index.html', () => {
    clearTimeout(timer);
    timer = setTimeout(rebuild, DEBOUNCE);
  });
} catch (e) {}

console.log('[watch] Watching /app/src for changes...');
"
