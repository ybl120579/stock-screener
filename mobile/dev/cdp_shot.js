// 用 Chrome DevTools Protocol 截手机尺寸的图（Edge headless 直接 --window-size 会受本机 DPI 影响）
//   node dev/cdp_shot.js <url> <out.png> [--wait=卡片选择器] [--width=390] [--height=844] [--dpr=2]
// 例：node dev/cdp_shot.js https://ybl120579.github.io/stock-screener/ shots/cloud-list.png
//     node dev/cdp_shot.js "https://.../#/stock/603303" shots/cloud-detail.png
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const args = process.argv.slice(2);
const URL_ = args[0];
const OUT = args[1] || 'shots/shot.png';
const opt = k => (args.find(a => a.startsWith('--' + k + '=')) || '').split('=')[1];
const W = +(opt('width') || 390), H = +(opt('height') || 844), DPR = +(opt('dpr') || 2);
const SEL = opt('wait') || '.card';
const PORT = 9222 + Math.floor(Math.random() * 300);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((res, rej) => {
    http.get(url, r => { let b = ''; r.on('data', d => b += d); r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on('error', rej);
  });
}

(async () => {
  const prof = path.join(process.env.TEMP || '.', 'edge-cdp-' + Date.now());
  const proc = spawn(EDGE, [
    '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars', '--mute-audio',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + prof, 'about:blank',
  ], { stdio: 'ignore' });

  let ver = null;
  for (let i = 0; i < 60 && !ver; i++) {
    try { ver = await getJSON(`http://127.0.0.1:${PORT}/json/version`); } catch (e) { await sleep(300); }
  }
  if (!ver) { proc.kill(); throw new Error('Edge 没起来'); }

  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pend = new Map();
  const events = [];
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
    else if (m.method) events.push(m);
  };
  function send(method, params = {}, sessionId) {
    const mid = ++id;
    return new Promise(res => { pend.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params, sessionId })); });
  }

  const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
  const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
  const S = p => JSON.stringify(Object.assign({}, p));

  await send('Page.enable', {}, sessionId);
  await send('Runtime.enable', {}, sessionId);
  await send('Emulation.setDeviceMetricsOverride',
    { width: W, height: H, deviceScaleFactor: DPR, mobile: true }, sessionId);
  await send('Emulation.setTouchEmulationEnabled', { enabled: true }, sessionId);
  await send('Page.navigate', { url: URL_ }, sessionId);

  // 等数据渲染出来（最多 45 秒）
  let ok = false;
  for (let i = 0; i < 90; i++) {
    await sleep(500);
    const r = await send('Runtime.evaluate',
      { expression: `document.querySelectorAll(${JSON.stringify(SEL)}).length`, returnByValue: true }, sessionId);
    if (r.result && r.result.result && r.result.result.value > 0) { ok = true; break; }
  }
  // 可选：先执行一段页面脚本（例如填入查询框、点开某个 sheet）
  const EVAL = opt('eval');
  if (EVAL) {
    const dec = decodeURIComponent(EVAL);
    await send('Runtime.evaluate', { expression: dec, returnByValue: true }, sessionId);
    await sleep(600);
  }
  await sleep(700);
  const info = await send('Runtime.evaluate', {
    expression: `JSON.stringify({w:innerWidth,h:innerHeight,cards:document.querySelectorAll('.card').length,
      title:document.title,sub:(document.querySelector('#sub')||{}).textContent||''})`, returnByValue: true,
  }, sessionId);
  console.log('page:', info.result.result.value, ok ? '' : '(选择器没等到，仍然截图)');

  const shot = await send('Page.captureScreenshot', { format: 'png' }, sessionId);
  const buf = Buffer.from(shot.result.data, 'base64');
  fs.mkdirSync(path.dirname(path.resolve(OUT)), { recursive: true });
  fs.writeFileSync(path.resolve(OUT), buf);
  console.log('saved', path.resolve(OUT), buf.length);

  ws.close();
  try { proc.kill(); } catch (e) { }
  setTimeout(() => { try { execSync('taskkill /F /IM msedge.exe', { stdio: 'ignore' }); } catch (e) { } }, 200);
  process.exit(0);
})().catch(e => { console.error('ERR', e.message); try { execSync('taskkill /F /IM msedge.exe', { stdio: 'ignore' }); } catch (x) { } process.exit(1); });
