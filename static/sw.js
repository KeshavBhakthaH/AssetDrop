/**
 * sw.js — AssetDrop Offline Application Shell Service Worker (v2.0)
 *
 * Implements:
 * - Robust precaching of core mobile shell assets.
 * - Cache invalidation and migration across versions.
 * - Strict network-first / network-only bypass for ingestion API & dynamic telemetry.
 * - Graceful offline synthetic fallback responses for API calls when host is unreachable.
 * - Stale-while-revalidate caching for static CSS/JS/icons for instant < 10ms repeat load.
 */

const CACHE_NAME = 'assetdrop-shell-v2.0.0';

const PRECACHE_ASSETS = [
  '/',
  '/index.html',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/manifest.json',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/favicon.ico',
];

// --- 1. Installation: Precache core shell defensively ---
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      // Individual cache.add to prevent a single missing asset from aborting installation
      await Promise.all(
        PRECACHE_ASSETS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn(`[AssetDrop SW] Precache missed for ${url}:`, err);
          })
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// --- 2. Activation: Purge outdated cache versions & claim clients ---
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => {
            console.log(`[AssetDrop SW] Purging old cache: ${key}`);
            return caches.delete(key);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// --- 3. Fetch Routing Strategy ---
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // A. Only intercept GET requests. Non-GET (e.g. POST /api/queue, /download) pass straight to network.
  if (req.method !== 'GET') {
    return;
  }

  // B. Dynamic REST API & Telemetry Endpoints: NETWORK-ONLY
  // Must NEVER return stale cached data for live downloads, directory browsing, or PIN verification.
  const isApiRoute = (
    url.pathname.startsWith('/api/') ||
    url.pathname === '/download' ||
    url.pathname === '/status' ||
    url.pathname === '/folders' ||
    url.pathname === '/health'
  );

  if (isApiRoute) {
    event.respondWith(
      fetch(req).catch(() => {
        // Return synthetic offline JSON response when server is unreachable
        return new Response(
          JSON.stringify({
            status: 'offline',
            error: 'Host server is unreachable. Check local Wi-Fi or Tailscale connection.',
            active: [],
            recent: [],
            errors: [],
            presets: {},
            folders: [],
            drives: [],
            offline: true,
          }),
          {
            status: 503,
            statusText: 'Service Unavailable (Offline)',
            headers: { 'Content-Type': 'application/json' },
          }
        );
      })
    );
    return;
  }

  // C. Navigation Requests (HTML Document): NETWORK-FIRST with CACHE FALLBACK
  // Guarantees users always see the latest UI build when connected, but provides
  // instantaneous offline shell loading when offline or on unstable local Wi-Fi.
  if (
    req.mode === 'navigate' ||
    req.destination === 'document' ||
    url.pathname === '/' ||
    url.pathname === '/index.html'
  ) {
    event.respondWith(
      fetch(req)
        .then((networkResp) => {
          if (networkResp && networkResp.status === 200) {
            const copy = networkResp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return networkResp;
        })
        .catch(async () => {
          const cachedResp = await caches.match(req);
          if (cachedResp) return cachedResp;
          const shellRoot = await caches.match('/');
          if (shellRoot) return shellRoot;
          return await caches.match('/index.html');
        })
    );
    return;
  }

  // D. Static Shell Assets (CSS, JS, Fonts, Images, Icons): STALE-WHILE-REVALIDATE
  // Serves instant cached copy (< 10ms latency) while fetching latest in background.
  event.respondWith(
    caches.match(req).then((cachedResp) => {
      const fetchPromise = fetch(req)
        .then((networkResp) => {
          if (networkResp && networkResp.status === 200) {
            const copy = networkResp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return networkResp;
        })
        .catch(() => {
          // Network failure is tolerated because cachedResp was already matched
        });

      return cachedResp || fetchPromise;
    })
  );
});
