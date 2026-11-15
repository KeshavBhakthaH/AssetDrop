/**
 * mobile/build.js — Copies AssetDrop static web assets to mobile/www/ for Capacitor Android compilation.
 * Ensures static/mobile.html is mapped to mobile/www/index.html so the Android app serves the
 * dedicated two-stage mobile interface.
 */

const fs = require('fs');
const path = require('path');

const srcDir = path.resolve(__dirname, '..', 'static');
const destDir = path.resolve(__dirname, 'www');

function copyDir(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

console.log('[AssetDrop Mobile] Syncing assets from static/ to mobile/www/...');

// 1. Copy full static asset tree to mobile/www/
copyDir(srcDir, destDir);

// 2. Also ensure mobile/www/static/ mirrors static/ so absolute /static/... paths resolve in Capacitor WebView
const destStaticDir = path.join(destDir, 'static');
copyDir(srcDir, destStaticDir);

// 3. Explicitly overwrite mobile/www/index.html with static/mobile.html for Capacitor Android root
const mobileHtmlSrc = path.join(srcDir, 'mobile.html');
const mobileIndexDest = path.join(destDir, 'index.html');
if (fs.existsSync(mobileHtmlSrc)) {
  fs.copyFileSync(mobileHtmlSrc, mobileIndexDest);
  console.log('[AssetDrop Mobile] Synced static/mobile.html -> mobile/www/index.html (Two-Stage Interface)');
} else {
  console.error('[AssetDrop Mobile] ERROR: static/mobile.html not found!');
  process.exit(1);
}

// 4. Ensure mobile.js and mobile.css are explicitly in mobile/www/
const mobileJsSrc = path.join(srcDir, 'mobile.js');
const mobileJsDest = path.join(destDir, 'mobile.js');
if (fs.existsSync(mobileJsSrc)) {
  fs.copyFileSync(mobileJsSrc, mobileJsDest);
}

const mobileCssSrc = path.join(srcDir, 'mobile.css');
const mobileCssDest = path.join(destDir, 'mobile.css');
if (fs.existsSync(mobileCssSrc)) {
  fs.copyFileSync(mobileCssSrc, mobileCssDest);
}

console.log('[AssetDrop Mobile] Assets synced successfully.');
