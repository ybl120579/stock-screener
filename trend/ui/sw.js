/* 强趋势页面离线壳 */
const V = 'trend-v1';
const SHELL = ['./', './index.html', './app.js', './style.css', './manifest.webmanifest',
               '../icon-192.png', '../icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(
    ks.filter(k => k !== V && k.startsWith('trend-')).map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.origin !== location.origin) return;
  const isData = /\/data\.json$|\/history\.json$|\/history\/\d{4}-\d2-\d2\.json$/.test(u.pathname);
  if (isData) {
    e.respondWith(fetch(e.request).then(r => {
      const cp = r.clone();
      caches.open(V).then(c => c.put(e.request, cp));
      return r;
    }).catch(() => caches.match(e.request)));
    return;
  }
  e.respondWith(caches.match(e.request).then(hit => {
    const net = fetch(e.request).then(r => {
      const cp = r.clone();
      caches.open(V).then(c => c.put(e.request, cp));
      return r;
    }).catch(() => hit);
    return hit || net;
  }));
});
