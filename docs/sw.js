/* 离线缓存：外壳「网络优先」（保证每次打开都是最新版），断网才回退缓存。
 *
 * 之前用的是 stale-while-revalidate —— 会先给你旧界面、后台再更新，
 * 结果就是「代码里加了新功能，手机上却看不到，要再进一次才出现」。
 * 版本号由 build_static.py 在构建时写入，每次发布换一份缓存。
 */
const V = 'sbcd-20261109011747';
const SHELL = [
  './', './index.html', './style.css', './app.js',
  './manifest.webmanifest', './icon-192.png', './icon-180.png', './icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== V).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
      .then(() => {
        // 新版本接管后，把还开着的旧页面重新加载一次，避免用户一直停在旧外壳上。
        return self.clients.matchAll({ type: 'window' }).then(cs => {
          cs.forEach(c => { try { c.navigate(c.url); } catch (err) { } });
        });
      })
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin) return;

  const isShell = req.mode === 'navigate' || /\.(html|js|css|webmanifest)$/.test(url.pathname);
  if (isShell) {
    e.respondWith(fetch(req).then(r => {
      const cp = r.clone();
      caches.open(V).then(c => c.put(req, cp));
      return r;
    }).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html'))));
    return;
  }

  // 数据（data/、api/）与图标：网络优先，失败回退缓存
  e.respondWith(fetch(req).then(r => {
    const cp = r.clone();
    caches.open(V).then(c => c.put(req, cp));
    return r;
  }).catch(() => caches.match(req)));
});
