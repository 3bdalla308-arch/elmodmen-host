/* Service Worker — BATMAN Dev PWA v2 (Pro) */
const CACHE = 'batman-dev-v2';
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
  // الـ API دايماً من الشبكة (مفيش كاش للبيانات/الجلسة)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/p/') || url.pathname.startsWith('/v/')) return;
  // Stale-while-revalidate للصفحات والستاتك
  e.respondWith(
    caches.match(req).then((cached) => {
      const net = fetch(req).then((res) => {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy).catch(() => {}));
        }
        return res;
      }).catch(() => cached);
      return cached || net;
    })
  );
});

// Push notifications (جاهز لما تضيف VAPID keys على الخادم)
self.addEventListener('push', (e) => {
  let payload = { title: 'BATMAN Dev', body: 'لوغ جديد', url: '/dashboard' };
  try { if (e.data) payload = Object.assign(payload, e.data.json()); } catch (_) {}
  e.waitUntil(self.registration.showNotification(payload.title, {
    body: payload.body,
    icon: '/static/icons/icon-192.png',
    badge: '/static/icons/icon-192.png',
    dir: 'rtl',
    lang: 'ar',
    vibrate: [100, 50, 100],
    data: { url: payload.url }
  }));
});

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/dashboard';
  e.waitUntil(clients.matchAll({ type: 'window' }).then((wins) => {
    for (const w of wins) { if (w.url.includes(url) && 'focus' in w) return w.focus(); }
    if (clients.openWindow) return clients.openWindow(url);
  }));
});

// رسائل من الصفحة (لإعادة تحميل الأصول إلخ)
self.addEventListener('message', (e) => {
  if (e.data === 'skipWaiting') self.skipWaiting();
});
