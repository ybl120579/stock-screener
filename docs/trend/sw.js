/* 强趋势页面：离线壳 + 自动更新
 *
 * 关键点：外壳（HTML/JS/CSS）用「网络优先」，只有断网时才回退缓存。
 * 之前的 stale-while-revalidate 会导致：你打开页面看到的还是上一版的界面，
 * 新功能要等第二次访问才出现 —— 这正是「加了功能但手机上没变化」的原因。
 * 版本号由 build_trend.py 在构建时写入，每次发布都会换一份缓存。
 */
const V = 'trend-20261109011757';
const SHELL = ['./', './index.html', './app.js', './style.css', './manifest.webmanifest',
               '../icon-192.png', '../icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(
    ks.filter(k => k !== V && k.startsWith('trend-')).map(k => caches.delete(k))
  )).then(() => self.clients.claim()))
    .then(() => {
      // 新版本接管后，把还开着的旧页面重新加载一次，避免用户一直停在旧外壳上。
      return self.clients.matchAll({ type: 'window' }).then(cs => {
        cs.forEach(c => { try { c.navigate(c.url); } catch (err) { } });
      });
    });
});

self.addEventListener('fetch', e => {
  const req = e.request;
  const u = new URL(req.url);
  if (req.method !== 'GET' || u.origin !== location.origin) return;

  // 导航 / 页面 / 脚本 / 样式：网络优先（保证拿到最新版），断网回退缓存
  const isShell = req.mode === 'navigate' || /\.(html|js|css|webmanifest)$/.test(u.pathname);
  if (isShell) {
    e.respondWith(fetch(req).then(r => {
      const cp = r.clone();
      caches.open(V).then(c => c.put(req, cp));
      return r;
    }).catch(() => caches.match(req).then(hit => hit || caches.match('./index.html'))));
    return;
  }

  // 数据：网络优先，失败回退缓存
  e.respondWith(fetch(req).then(r => {
    const cp = r.clone();
    caches.open(V).then(c => c.put(req, cp));
    return r;
  }).catch(() => caches.match(req)));
});
