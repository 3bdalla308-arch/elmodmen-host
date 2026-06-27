/* Service Worker — 𝑬𝑨𝑻𝑴𝑨𝑵 𝑫𝒆𝒗 PWA */
const CACHE = 'batman-dev-v1';
const ASSETS = [
  '/login',
  '/static/favicon.ico',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/manifest.webmanifest'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS).catch(() => {})));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  // الـ API دايمًا من الشبكة (مفيش كاش للبيانات/الجلسة)
  if (url.pathname.startsWith('/api/')) return;
  // الملفات الثابتة: cache-first
  if (url.pathname.startsWith('/static/')) {
    e.respondWith(
      caches.match(req).then((r) => r || fetch(req).then((res) => {
        const cp = res.clone();
        caches.open(CACHE).then((c) => c.put(req, cp));
        return res;
      }))
    );
    return;
  }
  // الصفحات: network-first مع fallback للكاش لو أوفلاين
  e.respondWith(
    fetch(req).catch(() => caches.match(req).then((r) => r || caches.match('/login')))
  );
});
