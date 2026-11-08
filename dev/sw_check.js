// 单次访问版本：用同一个 profile 反复调用，就能验证「发布后老缓存会不会自动失效」。
//   node dev/sw_check.js <url> <profileDir> [marker]
// 第一次运行：装上 Service Worker（页面还是当前版本）
// 第二次运行：外部已经改过文件 → 期望这里拿到新内容（marker=true）
const { spawn } = require('child_process');
const http = require('http');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9411;
const url = process.argv[2];
const profile = process.argv[3];
const marker = process.argv[4] || '__SWTEST';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const getJSON = p => new Promise((res, rej) => {
  http.get({ host: '127.0.0.1', port: PORT, path: p }, r => {
    let b = '';
    r.on('data', d => b += d);
    r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } });
  }).on('error', rej);
});

(async () => {
  const proc = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars', '--mute-audio',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, 'about:blank',
  ], { stdio: 'ignore' });

  let ver = null;
  for (let i = 0; i < 60 && !ver; i++) {
    try { ver = await getJSON('/json/version'); } catch (e) { await sleep(300); }
  }
  if (!ver) { proc.kill(); throw new Error('Edge 没起来'); }

  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pend = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  };
  const send = (method, params = {}, sid) => new Promise(res => {
    const mid = ++id; pend.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params, sessionId: sid }));
  });

  const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
  const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
  await send('Page.enable', {}, sessionId);
  await send('Runtime.enable', {}, sessionId);
  await send('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, sessionId);

  await send('Page.navigate', { url }, sessionId);
  await sleep(4500);
  await send('Page.navigate', { url }, sessionId);   // 第二次导航：给 SW 接管机会
  await sleep(4500);

  const r = await send('Runtime.evaluate', {
    expression: `JSON.stringify({
      marker: !!window['${marker}'],
      ctrl: !!(navigator.serviceWorker && navigator.serviceWorker.controller),
      copies: document.querySelectorAll('[data-copy]').length,
      perf: document.querySelectorAll('.perf').length,
      sw: (navigator.serviceWorker && navigator.serviceWorker.controller)
           ? navigator.serviceWorker.controller.scriptURL.split('/').pop() : null
    })`, returnByValue: true,
  }, sessionId);

  console.log(r.result && r.result.result ? r.result.result.value : JSON.stringify(r));
  ws.close();
  proc.kill();
})().catch(e => { console.error('ERR', e.message); process.exit(2); });
