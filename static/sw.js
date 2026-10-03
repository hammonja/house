const CACHE = 'house-public-shell-v041';
const PUBLIC = ['/static/offline.html','/static/photos.css','/static/photos.js','/static/icon-192.png','/static/icon-512.png','/manifest.webmanifest'];
self.addEventListener('install', event => { event.waitUntil(caches.open(CACHE).then(c => c.addAll(PUBLIC))); self.skipWaiting(); });
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k.startsWith('house-public-shell-') && k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== 'GET') return;
  // Explicit public allowlist. Never cache login, API, photos, models, or authenticated HTML.
  if (PUBLIC.includes(url.pathname) && !url.search) {
    event.respondWith(caches.open(CACHE).then(async cache => {
      try { const response = await fetch(event.request); if (response.ok && !response.redirected) await cache.put(event.request, response.clone()); return response; }
      catch { return await cache.match(event.request) || Response.error(); }
    }));
  } else if (event.request.mode === 'navigate' && url.pathname === '/photos') {
    event.respondWith(fetch(event.request).catch(() => caches.match('/static/offline.html')));
  }
});
