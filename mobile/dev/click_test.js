// 真·点击测试：用 CDP 发送受信任的鼠标事件，验证「一键复制代码」是否真的写进剪贴板。
//   node dev/click_test.js "http://127.0.0.1:8099/" "[data-copy]"
// 输出：toast 文案 / 剪贴板内容 / 是否误开了详情 sheet
const { spawn, execSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const EDGE = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
].find(p => fs.existsSync(p));
const URL_ = process.argv[2] || 'http://127.0.0.1:8099/';
const SEL = process.argv[3] || '[data-copy]';
const PORT = 9500 + Math.floor(Math.random() * 300);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function getJSON(url) {
  return new Promise((res, rej) => {
    http.get(url, r => { let b = ''; r.on('data', d => b += d); r.on('end', () => { try { res(JSON.parse(b)); } catch (e) { rej(e); } }); }).on('error', rej);
  });
}

(async () => {
  try { execSync('taskkill /F /IM msedge.exe', { stdio: 'ignore' }); } catch (e) { }
  const prof = path.join(process.env.TEMP || '.', 'edge-click-' + Date.now());
  spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-sandbox',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + prof, 'about:blank'], { stdio: 'ignore' });

  let ver = null;
  for (let i = 0; i < 60 && !ver; i++) {
    try { ver = await getJSON(`http://127.0.0.1:${PORT}/json/version`); } catch (e) { await sleep(300); }
  }
  if (!ver) throw new Error('Edge 没起来');

  const ws = new WebSocket(ver.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pend = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  };
  const send = (method, params = {}, sessionId) => {
    const mid = ++id;
    return new Promise(res => { pend.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params, sessionId })); });
  };
  let SID = null; // 页面 session，避免每次调用都传
  const evalJS = async (expr, sid) => {
    const r = await send('Runtime.evaluate',
      { expression: expr, returnByValue: true, awaitPromise: true }, sid || SID);
    return r.result && r.result.result ? r.result.result.value : null;
  };

  const { result: { targetId } } = await send('Target.createTarget', { url: 'about:blank' });
  const { result: { sessionId } } = await send('Target.attachToTarget', { targetId, flatten: true });
  SID = sessionId;

  await send('Page.enable', {}, sessionId);
  await send('Runtime.enable', {}, sessionId);
  // 关键：放开剪贴板权限，否则 headless 下必然拒绝
  await send('Browser.grantPermissions',
    { permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'], origin: new URL(URL_).origin });
  await send('Emulation.setDeviceMetricsOverride',
    { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, sessionId);
  await send('Page.navigate', { url: URL_ }, sessionId);

  let ready = false;
  for (let i = 0; i < 90; i++) {
    await sleep(500);
    if (await evalJS(`document.querySelectorAll(${JSON.stringify(SEL)}).length`)) { ready = true; break; }
  }
  if (!ready) console.log('(选择器没等到，仍然尝试点击)');

  const box = await evalJS(`(() => {
    const el = document.querySelector(${JSON.stringify(SEL)});
    if (!el) return null;
    el.scrollIntoView({ block: 'center' });
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2, code: el.dataset.copy, txt: el.textContent.trim() };
  })()`);
  if (!box) throw new Error('找不到按钮');
  await sleep(400);
  const b2 = await evalJS(`(() => { const el = document.querySelector(${JSON.stringify(SEL)});
    const r = el.getBoundingClientRect(); return { x: r.x + r.width/2, y: r.y + r.height/2 }; })()`);

  // 受信任的鼠标按下/抬起（等价于真人点击）
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x: b2.x, y: b2.y, button: 'left', clickCount: 1 }, sessionId);
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x: b2.x, y: b2.y, button: 'left', clickCount: 1 }, sessionId);
  await sleep(800);

  const toast = await evalJS(`(document.querySelector('#toast')||{}).textContent || ''`);
  const sheetOpen = await evalJS(`!!document.querySelector('#sheet.on')`);
  const clip = await evalJS(`navigator.clipboard.readText().then(t => t).catch(e => 'READ-ERR:' + e.message)`);

  console.log('button :', box.txt, '(data-copy=' + box.code + ')');
  console.log('toast  :', toast);
  console.log('sheet  :', sheetOpen ? '打开（错误！）' : '未打开（正确）');
  console.log('clipbrd:', JSON.stringify(clip));
  ws.close();
  try { execSync('taskkill /F /IM msedge.exe', { stdio: 'ignore' }); } catch (e) { }
  process.exit(0);
})().catch(e => {
  console.error('ERR', e.message);
  try { execSync('taskkill /F /IM msedge.exe', { stdio: 'ignore' }); } catch (x) { }
  process.exit(1);
});
