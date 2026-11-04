// 生成手机视图截图（Edge headless 的 --window-size 受本机 DPI 影响，用固定宽度 iframe 规避）
//   用法：node dev/shot.js "" shots/list.png
//         node dev/shot.js "?open=603303" shots/detail.png
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const HASH = process.argv[2] || '';
const OUT = process.argv[3] || 'shots/shot.png';
const PORT = process.env.PORT || '8765';
const BASE = process.env.BASE || ('http://127.0.0.1:' + PORT + '/');   // 页面根（可带子路径）
const ROOT = process.env.SHOT_DIR || path.join(__dirname, '..', 'ui');  // 该根对应的本地目录
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const W = 390, H = 844;

const tmpHtml = path.join(ROOT, '_shot.html');
fs.writeFileSync(tmpHtml, [
  '<!DOCTYPE html><html><head><meta charset="utf-8">',
  `<style>html,body{margin:0;background:#0a0d12}iframe{border:0;display:block;width:${W}px;height:${H}px}</style>`,
  `</head><body><iframe id="fr" src="${BASE}${HASH}"></iframe></body></html>`,
].join('\n'));

const outAbs = path.resolve(OUT);
const prof = path.join(process.env.TEMP || '.', 'edge-shot-' + Date.now());
const tmpShot = outAbs + '.raw.png';
if (fs.existsSync(tmpShot)) fs.unlinkSync(tmpShot);

function sleepSync(ms) {
  const sab = new SharedArrayBuffer(4);
  Atomics.wait(new Int32Array(sab), 0, 0, ms);
}

function runOnce() {
  execFileSync(EDGE, [
    '--headless=new', '--disable-gpu', '--no-sandbox',
    '--user-data-dir=' + prof, '--hide-scrollbars',
    '--window-size=' + W + ',' + H,
    '--virtual-time-budget=9000',
    '--screenshot=' + tmpShot,
    BASE + '_shot.html',
  ], { stdio: 'ignore' });
}

for (let i = 0; i < 3 && !fs.existsSync(tmpShot); i++) {
  try { runOnce(); } catch (e) { /* Edge 首次调用偶发失败 */ }
  for (let t = 0; t < 10 && !fs.existsSync(tmpShot); t++) sleepSync(1000);
}

if (!fs.existsSync(tmpShot)) { console.error('screenshot failed'); process.exit(1); }
fs.renameSync(tmpShot, outAbs);
try { fs.unlinkSync(tmpHtml); } catch (e) { /* ignore */ }
console.log('saved', outAbs, fs.statSync(outAbs).size);
