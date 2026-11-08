/* 强趋势 · 手机端单页应用（零依赖） */
'use strict';

const BASE = location.pathname.replace(/[^/]*$/, '');
let LOAD_SEQ = 0;

const S = {
  date: null,        // 正在看的日期（null = 最新）
  data: null,
  rows: [],
  hist: [],
  sort: 'score',
  q: '',
};

const SORTS = [
  ['score', '综合分'],
  ['ret20', '20日涨幅'],
  ['rs20', '相对强度'],
  ['to_high', '距新高'],
  ['turnover', '换手'],
  ['pct', '当天涨跌'],
  ['next', '次日涨跌'],
];

const STAGE_TIP = {
  0: '主板股票池：只留 600/601/603/605/000/001/002/003，去掉 ST / 科创 / 创业 / 北交所 / N·C 新股',
  1: '数据充足：至少 150 根日 K，够算 120 日均线',
  2: '价格·流动性：股价 ≥ 3 元，20 日均成交额 0.5–20 亿',
  3: '市值 30–2000 亿：太小容易被操纵，太大拉不动',
  4: '站上 20 日线：收盘价必须在 MA20 之上',
  5: '多头排列：MA5 > MA10 > MA20 > MA60',
  6: '仍在 120 日线上方：长期趋势不能走坏',
  7: '中期仍在涨：20 日涨幅 ≥ 2%',
  8: '贴近 20 日新高：离 20 日最高价 ≤ 6%',
  9: '活跃且有弹性：换手 3–25%、20 日平均振幅 2.2–9%',
  10: '没追太高：离 MA20 ≤ 16%，当日涨幅 < 9%',
  11: '最终入选：按综合分排序取前 N',
};

const $ = (s, el) => (el || document).querySelector(s);
const MY = n => (n === null || n === undefined || (typeof n === 'number' && !isFinite(n)));

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function num(v, nd) {
  if (MY(v)) return '—';
  return Number(v).toFixed(nd === undefined ? 1 : nd);
}
function pct(v, nd) {
  if (MY(v)) return '—';
  const n = Number(v);
  return (n > 0 ? '+' : '') + n.toFixed(nd === undefined ? 1 : nd) + '%';
}
function cls(v) {
  if (MY(v) || Number(v) === 0) return '';
  return Number(v) > 0 ? 'up' : 'dn';
}
function ymd(s) { return (s || '').slice(5); }

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('on');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('on'), 1600);
}

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(url + ' → ' + r.status);
  return r.json();
}

function copyText(txt) {
  // 先走「同步 execCommand」这条老路：
  // 它不挑协议（http 局域网也能用）、不弹权限、在点击手势里最稳。
  const ta = document.createElement('textarea');
  ta.value = txt;
  ta.setAttribute('aria-hidden', 'true');
  ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;' +
                     'padding:0;border:0;opacity:.01;font-size:12px;';
  document.body.appendChild(ta);
  let ok = false;
  try {
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    ok = document.execCommand('copy');
  } catch (e) { ok = false; }
  document.body.removeChild(ta);
  if (ok) return Promise.resolve(true);

  // 再试 Clipboard API（需要 https/localhost 且要有用户手势）
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(txt).then(() => true).catch(() => false);
  }
  return Promise.resolve(false);
}

function copyCode(code, ev) {
  if (ev) { ev.preventDefault(); ev.stopPropagation(); }
  copyText(String(code)).then(ok => {
    toast(ok ? '已复制代码 ' + code : '复制失败：代码 ' + code + '，可长按选中复制');
  });
}

/* ---------------- 数据 ---------------- */
async function load(date) {
  const seq = ++LOAD_SEQ;
  const url = date ? `${BASE}history/${date}.json` : `${BASE}data.json`;
  try {
    const d = await getJSON(url + '?v=' + Date.now());
    if (seq !== LOAD_SEQ) return;
    S.data = d; S.date = date || null; S.rows = d.rows || [];
    renderAll();
  } catch (e) {
    if (seq !== LOAD_SEQ) return;
    toast('加载失败：' + e.message);
  }
}

async function loadHistory() {
  try {
    const h = await getJSON(BASE + 'history.json?v=' + Date.now());
    S.hist = Array.isArray(h) ? h : [];
    renderDates();
  } catch (e) { /* 无历史就算了 */ }
}

/* ---------------- 渲染 ---------------- */
function renderAll() {
  const d = S.data || {};
  $('#sub').textContent = `数据日期 ${d.asof || '—'} · ${(d.generated_at || '').slice(5, 16)} 生成 · ${d.elapsed_sec || '—'}s`;
  renderStats();
  renderDaySummary();
  renderMkt();
  renderRenew();
  renderDates();
  renderSorts();
  renderList();
}

function renderStats() {
  const d = S.data || {};
  const pool = (d.funnel && d.funnel[0]) ? (d.funnel[0].value ?? d.funnel[0]) : 0;
  const ok = d.market ? d.market.ok : true;
  $('#stats').innerHTML = `
    <div class="stat" data-funnel="1"><b>${S.rows.length}</b><span>入选</span></div>
    <div class="stat" data-funnel="1"><b>${pool}</b><span>候选池</span></div>
    <div class="stat" data-funnel="1"><b>${ok ? '可做' : '空仓区'}</b><span>市况</span></div>
    <div class="stat" data-funnel="1"><b>${pct(d.market && d.market.mom20)}</b><span>大盘 20 日</span></div>`;
}

function renderDaySummary() {
  const d = S.data || {};
  const day = d.day, nxt = d.next;
  const row1 = day
    ? `<div class="ds"><i>当天 ${day.n} 只平均</i><b class="${cls(day.avg)}">${pct(day.avg)}</b>
       <span class="dim">涨 ${day.up} · 跌 ${day.down}</span></div>`
    : `<div class="ds"><i>当天</i><b class="wait">—</b><span class="dim">行情源未取到</span></div>`;
  const row2 = nxt
    ? `<div class="ds"><i>次日（${ymd(d.next_date)}）</i><b class="${cls(nxt.avg)}">${pct(nxt.avg)}</b>
       <span class="dim">涨 ${nxt.up} · 跌 ${nxt.down} · 胜率 ${num(nxt.up / nxt.n * 100, 0)}%</span></div>`
    : `<div class="ds"><i>次日表现</i><b class="wait">待次日</b><span class="dim">下一交易日收盘后回填</span></div>`;
  $('#daysum').innerHTML = row1 + row2;
}

function renderMkt() {
  const d = S.data || {};
  const ok = d.market ? d.market.ok : true;
  const mom = d.market ? d.market.mom20 : null;
  const tip = ok
    ? '等权指数站在 20 日线上方，趋势顺势可做。'
    : '等权指数在 20 日线下方，趋势策略在这种环境最容易连续吃面。名单仅作观察。';
  $('#mkt').innerHTML = `
    <div class="mkt ${ok ? 'ok' : 'bad'}">
      <div class="t"><b>${ok ? '可做 · 顺势' : '空仓区 · 建议观望'}</b><span>大盘 20 日 ${pct(mom)}</span></div>
      <div>${esc(tip)}</div>
    </div>`;
}

function renderRenew() {
  const d = S.data || {};
  const bits = [];
  if (S.date) bits.push(`正在看历史 ${ymd(S.date)} 的名单`);
  else bits.push('每个交易日 11:00 自动更新（盘中快照）');
  if (d.generated_at) bits.push('本次 ' + d.generated_at.slice(5, 16));
  $('#renew').innerHTML = `<span class="dot"></span><span>${esc(bits.join(' · '))}</span>`;
}

function renderDates() {
  const el = $('#dates');
  if (!S.hist.length) { el.innerHTML = ''; return; }
  const latest = S.hist[S.hist.length - 1];
  const items = S.hist.slice(-6).reverse().map(h => {
    const on = (S.date || latest.date) === h.date;
    return `<button class="chip ${on ? 'on' : ''}" data-date="${h.date}">${ymd(h.date)} · ${h.count}只</button>`;
  });
  el.innerHTML = items.join('');
}

function renderSorts() {
  $('#sorts').innerHTML = SORTS.map(([k, label]) =>
    `<button class="chip ${S.sort === k ? 'on' : ''}" data-sort="${k}">${label}</button>`).join('');
}

function sortVal(r, k) {
  if (k === 'next') return MY(r.next_close_pct) ? -999 : r.next_close_pct;
  if (k === 'pct') return MY(r.pct) ? -999 : r.pct;
  return MY(r[k]) ? -999 : r[k];
}

function filtered() {
  const q = S.q.trim().toUpperCase();
  let rows = S.rows.slice();
  if (q) rows = rows.filter(r => (r.code || '').includes(q) || (r.name || '').toUpperCase().includes(q));
  rows.sort((a, b) => sortVal(b, S.sort) - sortVal(a, S.sort));
  return rows;
}

function ring(score) {
  const v = Math.max(0, Math.min(100, Number(score) || 0));
  const c = 2 * Math.PI * 19;
  return `<div class="ring"><svg viewBox="0 0 44 44">
      <circle cx="22" cy="22" r="19" fill="none" stroke="rgba(255,255,255,.09)" stroke-width="4"/>
      <circle cx="22" cy="22" r="19" fill="none" stroke="url(#g1)" stroke-width="4"
        stroke-linecap="round" stroke-dasharray="${(c * v / 100).toFixed(1)} ${c.toFixed(1)}"/>
      <defs><linearGradient id="g1" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#5b8cff"/><stop offset="1" stop-color="#c084fc"/></linearGradient></defs>
    </svg><span class="v">${num(score, 1)}</span></div>`;
}

function card(r, idx) {
  const nxt = MY(r.next_close_pct)
    ? '<div><i>次日</i><b class="wait">待次日</b></div>'
    : `<div><i>次日 ${ymd(r.next_date)}</i><b class="${cls(r.next_close_pct)}">${pct(r.next_close_pct)}</b></div>`;
  return `<div class="card" data-code="${esc(r.code)}">
    <div class="crow">
      <div class="rank">${idx}</div>
      <div class="nm">
        <h3>${esc(r.name)}<button class="code" type="button" data-copy="${esc(r.code)}" title="复制代码">${esc(r.code)}
          <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="5.6" y="5.6" width="8" height="8" rx="1.6"/><path d="M10.4 5.6V3.9a1.5 1.5 0 0 0-1.5-1.5H3.9a1.5 1.5 0 0 0-1.5 1.5v5a1.5 1.5 0 0 0 1.5 1.5h1.7"/></svg></button></h3>
        <div class="sub">
          <span>${esc(r.industry || '—')}</span>
          <span class="tag">离新高 ${num(r.to_high, 1)}%</span>
          <span>换手 ${num(r.turnover, 1)}%</span>
        </div>
      </div>
      ${ring(r.score)}
    </div>
    <div class="perf">
      <div><i>当天涨跌</i><b class="${cls(r.pct)}">${pct(r.pct)}</b></div>
      ${nxt}
    </div>
    <div class="kv">
      <div><i>20 日涨幅</i><b class="${cls(r.ret20)}">${pct(r.ret20)}</b></div>
      <div><i>相对强度</i><b>${num((r.rs20 || 0) * 100, 0)}%</b></div>
      <div><i>离 MA20</i><b class="${cls(r.dist_ma20)}">${pct(r.dist_ma20)}</b></div>
      <div><i>日均振幅</i><b>${num(r.atr_pct, 1)}%</b></div>
      <div><i>量能</i><b>${num(r.vol_surge, 2)}</b></div>
      <div><i>20日均额</i><b>${num(r.amt20_yi, 2)}亿</b></div>
      <div><i>止损</i><b class="dn">${num(r.stop, 2)}</b></div>
      <div><i>目标</i><b class="up">${num(r.target, 2)}</b></div>
    </div>
    <div class="spark"><canvas data-spark="${esc(r.code)}"></canvas><span class="hint">近40日</span></div>
  </div>`;
}

function renderList() {
  const rows = filtered();
  const el = $('#list');
  if (!rows.length) {
    el.innerHTML = `<div class="empty">没有符合条件的股票${S.q ? '（换个关键词试试）' : ''}</div>`;
    return;
  }
  el.innerHTML = rows.map((r, i) => card(r, i + 1)).join('');
  rows.forEach(r => drawSpark(r));
}

function drawSpark(r) {
  const cv = document.querySelector(`canvas[data-spark="${r.code}"]`);
  if (!cv || !r.spark || r.spark.length < 2) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 240, h = 26;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext('2d');
  g.scale(dpr, dpr);
  const a = r.spark, mn = Math.min(...a), mx = Math.max(...a), rg = (mx - mn) || 1;
  const x = i => (i / (a.length - 1)) * (w - 2) + 1;
  const y = v => h - 3 - ((v - mn) / rg) * (h - 6);
  g.clearRect(0, 0, w, h);
  const up = a[a.length - 1] >= a[0];
  g.strokeStyle = up ? '#2bd48f' : '#ff5a5f';
  g.lineWidth = 1.4; g.lineJoin = 'round';
  g.beginPath();
  a.forEach((v, i) => (i ? g.lineTo : g.moveTo).call(g, x(i), y(v)));
  g.stroke();
  const grd = g.createLinearGradient(0, 0, 0, h);
  grd.addColorStop(0, up ? 'rgba(43,212,143,.28)' : 'rgba(255,90,95,.28)');
  grd.addColorStop(1, 'rgba(0,0,0,0)');
  g.lineTo(x(a.length - 1), h); g.lineTo(x(0), h); g.closePath();
  g.fillStyle = grd; g.fill();
}

/* ---------------- 详情 sheet ---------------- */
function openSheet(code) {
  const r = S.rows.find(x => x.code === code);
  if (!r) return toast('找不到 ' + code);
  $('#phead').innerHTML = `
    <div class="bar"></div>
    <h2>${esc(r.name)}
      <button class="code lg" data-copy="${esc(r.code)}" title="复制代码">${esc(r.code)}
        <svg viewBox="0 0 24 24" width="12" height="12"><path d="M9 3h9a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-1v-2h1a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v1H6V6a3 3 0 0 1 3-3Zm-3 6h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2Z" fill="currentColor"/></svg>
      </button>
      <span>${esc(r.industry || '—')}</span>
    </h2>
    <div class="px"><b>${num(r.price, 2)}</b>
      <span class="${cls(r.pct)}">${pct(r.pct)}</span>
      <span>综合分 ${num(r.score, 1)}</span></div>`;

  const parts = [
    ['动量', r.s_parts && r.s_parts.s_mom, 25],
    ['中期', r.s_parts && r.s_parts.s_mid, 15],
    ['强度', r.s_parts && r.s_parts.s_rs, 20],
    ['量能', r.s_parts && r.s_parts.s_vol, 15],
    ['弹性', r.s_parts && r.s_parts.s_atr, 10],
    ['近高', r.s_parts && r.s_parts.s_high, 15],
  ];
  const partHtml = parts.map(([n, v, w]) => `
    <div class="part"><i>${n} <span class="stag">${w}%</span></i>
      <div class="b"><span style="width:${Math.max(0, Math.min(100, Number(v) || 0))}%"></span></div>
      <b>${num(v, 0)}</b></div>`).join('');

  const kv = [
    ['20 日涨幅', pct(r.ret20), cls(r.ret20)],
    ['60 日涨幅', pct(r.ret60), cls(r.ret60)],
    ['相对强度 RS20', num((r.rs20 || 0) * 100, 0) + '%', ''],
    ['距 20 日新高', num(r.to_high, 1) + '%', ''],
    ['离 MA20', pct(r.dist_ma20), cls(r.dist_ma20)],
    ['日均振幅', num(r.atr_pct, 1) + '%', ''],
    ['今日换手', num(r.turnover, 1) + '%', ''],
    ['量能（额/20日均额）', num(r.vol_surge, 2), ''],
    ['20 日均额', num(r.amt20_yi, 2) + ' 亿', ''],
    ['流通市值', num(r.float_mcap_yi, 0) + ' 亿', ''],
    ['止损（ATR自适应）', num(r.stop, 2), 'dn'],
    ['目标（+40%）', num(r.target, 2), 'up'],
  ].map(([k, v, c]) => `<div><i>${k}</i><b class="${c}">${v}</b></div>`).join('');

  $('#pbody').innerHTML = `
    <div class="chartbox"><canvas id="kline"></canvas></div>
    <div class="legend">
      <span><i class="dot up"></i>阳线</span><span><i class="dot dn"></i>阴线</span>
      <span><i class="dot ma5"></i>MA20</span><span><i class="dot ma60"></i>MA60</span>
      <span><i class="dot stop"></i>止损</span><span><i class="dot tgt"></i>目标</span>
    </div>
    <div class="sec"><h4>评分构成</h4>${partHtml}</div>
    <div class="sec"><h4>关键指标</h4><div class="kv2">${kv}</div></div>
    <div class="sec"><h4>交易规则</h4>
      <p class="tip">次日开盘买入；跌破止损无条件走；涨到目标（+40%）或收盘跌破 MA10 走；最长持有 15 个交易日。
      止损按 ATR×2 自适应，夹在 4–9%。</p></div>`;

  $('#sheet').classList.add('on');
  drawKline(r);
  if (location.hash !== '#/stock/' + code) history.replaceState(null, '', '#/stock/' + code);
}

function drawKline(r) {
  const cv = $('#kline');
  if (!cv || !r.bars || r.bars.length < 5) return;
  const dpr = window.devicePixelRatio || 1;
  const w = cv.clientWidth || 340, h = 190;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext('2d');
  g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);

  const bars = r.bars, closes = bars.map(b => b[2]);
  const ma = (n) => closes.map((_, i) => {
    if (i < n - 1) return null;
    let s = 0; for (let k = i - n + 1; k <= i; k++) s += closes[k];
    return s / n;
  });
  const ma20 = ma(20), ma60 = ma(60);
  const L = 34, R = 6, T = 8, B = 16;
  const px = w - L - R, py = h - T - B;
  const lo = Math.min(...bars.map(b => b[3]), r.stop || Infinity);
  const hi = Math.max(...bars.map(b => b[4]), r.target || -Infinity);
  const rg = (hi - lo) || 1;
  const X = i => L + (i / Math.max(1, bars.length - 1)) * px;
  const Y = v => T + (1 - (v - lo) / rg) * py;

  g.strokeStyle = 'rgba(255,255,255,.06)'; g.lineWidth = 1;
  for (let k = 0; k <= 3; k++) {
    const y = T + py * k / 3;
    g.beginPath(); g.moveTo(L, y); g.lineTo(L + px, y); g.stroke();
    g.fillStyle = '#5d6775'; g.font = '9px system-ui'; g.textAlign = 'left';
    g.fillText((hi - rg * k / 3).toFixed(2), 2, y + 3);
  }

  const bw = Math.max(1.2, px / bars.length * 0.62);
  bars.forEach((b, i) => {
    const [, o, c, l, hh] = b;
    const up = c >= o;
    g.strokeStyle = g.fillStyle = up ? '#ff5a5f' : '#2bd48f';
    const x = X(i);
    g.beginPath(); g.moveTo(x, Y(hh)); g.lineTo(x, Y(l)); g.stroke();
    const y1 = Y(Math.max(o, c)), y2 = Y(Math.min(o, c));
    g.fillRect(x - bw / 2, y1, bw, Math.max(1, y2 - y1));
  });

  const line = (arr, color) => {
    g.strokeStyle = color; g.lineWidth = 1.2; g.beginPath();
    let started = false;
    arr.forEach((v, i) => {
      if (v === null) return;
      if (!started) { g.moveTo(X(i), Y(v)); started = true; } else g.lineTo(X(i), Y(v));
    });
    g.stroke();
  };
  line(ma20, 'rgba(91,140,255,.95)');
  line(ma60, 'rgba(192,132,252,.85)');

  const hline = (v, color, label) => {
    if (MY(v)) return;
    const y = Y(v);
    g.save(); g.setLineDash([4, 3]); g.strokeStyle = color; g.lineWidth = 1;
    g.beginPath(); g.moveTo(L, y); g.lineTo(L + px, y); g.stroke(); g.restore();
    const txt = label + ' ' + Number(v).toFixed(2);
    g.font = '9px system-ui'; g.textAlign = 'left';
    const tw = g.measureText(txt).width;
    g.fillStyle = 'rgba(10,13,18,.86)';
    g.fillRect(L + 1, y - 12, tw + 5, 11);
    g.fillStyle = color;
    g.fillText(txt, L + 3, y - 3);
  };
  hline(r.stop, 'rgba(43,212,143,.95)', '止损');
  hline(r.target, 'rgba(255,90,95,.95)', '目标');

  g.fillStyle = '#5d6775'; g.font = '9px system-ui'; g.textAlign = 'left';
  g.fillText(bars[0][0].slice(5), L, h - 4);
  g.textAlign = 'right';
  g.fillText(bars[bars.length - 1][0].slice(5), L + px, h - 4);
}

/* ---------------- 漏斗 + 为什么没入选 ---------------- */
function openFunnel() {
  const d = S.data || {};
  const rows = (d.funnel || []).map(x => (typeof x === 'object' ? x : { name: String(x), value: x }));
  const max = rows.length ? Number(rows[0].value) || 1 : 1;
  let prev = null;
  const html = rows.map((x, i) => {
    const v = Number(x.value) || 0;
    const cut = prev === null ? '' : (prev - v > 0 ? '−' + (prev - v) : '');
    prev = v;
    const name = x.name || (d.stages && d.stages[i] && d.stages[i].name) || ('阶段' + i);
    const hint = (d.stages && d.stages[i] && d.stages[i].hint) || '';
    return `<div class="frow"><div class="ftop"><span class="fname">${esc(name)}</span>
        ${cut ? `<span class="cut">${cut}</span>` : ''}
        <span class="fval">${v}</span></div>
      <div class="fbar"><i style="width:${Math.max(1.5, v / max * 100)}%"></i></div>
      ${hint ? `<div class="fhint">${esc(hint)}</div>` : ''}</div>`;
  }).join('');

  $('#phead').innerHTML = `<div class="bar"></div><h2>筛选漏斗 <span>${esc(d.asof || '')} · 逐级收敛</span></h2>`;
  $('#pbody').innerHTML = `
    <p class="tip">从 ${rows.length ? Number(rows[0].value) : 0} 只主板里一层层筛到 ${S.rows.length} 只。
      左边是「这一层还剩多少」，右边 −N 是被这一层去掉的。</p>
    ${html}
    <div class="sec"><h4>查一只股票为什么没入选</h4>
      <p class="dim">输入代码或名称，看看它卡在第几层。</p>
      <input class="q" id="whyq" type="search" placeholder="例如 300839 或 博汇" autocomplete="off">
      <div id="whyout"></div>
    </div>`;
  $('#sheet').classList.add('on');
}

function whyLookup(code) {
  const q = code.trim().toUpperCase();
  const out = $('#whyout');
  if (!q) { out.innerHTML = ''; return; }
  const hit = S.rows.find(r => (r.code || '').includes(q) || (r.name || '').toUpperCase().includes(q));
  if (hit) {
    out.innerHTML = `<div class="whyrow"><div class="whytop"><b>${esc(hit.name)}</b>
      <span>${esc(hit.code)}</span><i class="st ok">已入选 · 第 ${S.rows.indexOf(hit) + 1} 名</i></div>
      <div class="whybd">综合分 ${num(hit.score, 1)} · 离 20 日新高 ${num(hit.to_high, 1)}% · 换手 ${num(hit.turnover, 1)}%</div></div>`;
    return;
  }
  const list = (S.data && S.data.rejects_list) || [];
  const hits = list.filter(x => x.code.includes(q) || (x.name || '').toUpperCase().includes(q));
  if (hits.length) {
    out.innerHTML = hits.slice(0, 6).map(x => `<div class="whyrow">
        <div class="whytop"><b>${esc(x.name)}</b><span>${esc(x.code)}</span>
        <i class="st bad">没进名单</i></div>
        <div class="whybd">${esc(x.why)}</div></div>`).join('');
    return;
  }
  out.innerHTML = '<p class="dim">没有找到这条记录（可能不在最近一次的主板池里）。</p>';
}

/* ---------------- 说明 ---------------- */
function openInfo() {
  $('#phead').innerHTML = `<div class="bar"></div><h2>策略说明 <span>每个交易日 11:00 自动更新</span></h2>`;
  $('#pbody').innerHTML = `
    <div class="info">
      <h4>这套在找什么</h4>
      <p>找<b>正在走强、而且还有弹性</b>的票：均线多头排列、贴着 20 日新高、有量能、换手活跃，
         但已经涨上天的不追。<br>
         一句话：<b>只做强中强，不抄底、不碰弱票</b>。</p>
      <h4>五个硬条件</h4>
      <p>① 均线多头排列：MA5 &gt; MA10 &gt; MA20 &gt; MA60，并且站在 120 日线上；<br>
         ② 贴着 20 日新高：离 20 日最高价不超过 <b>6%</b>；<br>
         ③ 有弹性：20 日平均振幅 <b>2.2–9%</b>，换手 <b>3–25%</b>；<br>
         ④ 量能配合：成交额 ≥ 20 日均额的 <b>1.0 倍</b>；<br>
         ⑤ 没追太高：离 MA20 不超过 <b>16%</b>，当日涨幅 &lt; 9%。</p>
      <h4>怎么打分</h4>
      <p>动量 25% + 中期 15% + 相对强度 20% + 量能 15% + 弹性 10% + 贴近新高 15%，
         全部按当天全市场横截面排位算，所以 90 分代表「今天这 3000 只里最强的那一档」。</p>
      <h4>今天该不该做</h4>
      <p>看等权指数在不在 20 日线上方。在下方就是<b>空仓区</b>：趋势策略在这种环境最容易连续吃面，
         名单只能观察。今天要不要做，比选哪只更重要。</p>
      <h4>回测过没有</h4>
      <p>有。200 个交易日、每天只取前 5 名、次日开盘买、止损按 ATR、收盘破 MA10 走、扣 0.2% 成本：<br>
         <b>464 笔，均值 +1.22%，中位 −3.85%，胜率 29.7%</b>；同期「所有主板股等权」是 <b>−0.91%</b>。<br>
         注意：胜率不到三成，靠少数几只大赢家（最好 +39.8%，最差 −14.5%，超过 +20% 的占 10.8%、亏超 5% 的占 42.9%）。
         这是典型的低胜率高赔率策略，<b>连亏几笔是正常的，不是系统坏了</b>。</p>
      <h4>当天的涨跌怎么看</h4>
      <p>11:00 是盘中快照，所以「当天涨跌」是当时的价，收盘会变；「次日」那一栏要等下一个交易日收盘后才会回填。</p>
      <h4>风险</h4>
      <p>回测只有 200 天、单一市场环境，不含涨跌停买不进、停牌、流动性冲击等真实摩擦。
         这不是投资建议，钱是你自己的。</p>
    </div>`;
  $('#sheet').classList.add('on');
}

/* ---------------- 事件 ---------------- */
document.addEventListener('click', e => {
  const cp = e.target.closest('[data-copy]');
  if (cp) return copyCode(cp.dataset.copy, e);

  if (e.target.closest('[data-close]')) { closeSheet(); return; }
  if (e.target.closest('#btnInfo')) { openInfo(); return; }

  const st = e.target.closest('#stats [data-funnel]');
  if (st) { openFunnel(); return; }

  const chipD = e.target.closest('#dates .chip');
  if (chipD) { load(chipD.dataset.date); return; }

  const chipS = e.target.closest('#sorts .chip');
  if (chipS) { S.sort = chipS.dataset.sort; renderSorts(); renderList(); return; }

  const c = e.target.closest('.card');
  if (c) { openSheet(c.dataset.code); return; }
});

document.addEventListener('input', e => {
  if (e.target.id === 'q') { S.q = e.target.value; renderList(); }
  if (e.target.id === 'whyq') whyLookup(e.target.value);
});

function closeSheet() {
  $('#sheet').classList.remove('on');
  if (location.hash.startsWith('#/stock/')) history.replaceState(null, '', location.pathname + location.search);
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });

window.addEventListener('hashchange', openFromHash);
function openFromHash() {
  const m = location.hash.match(/^#\/stock\/(\d{6})/);
  if (m) return openSheet(m[1]);
  const sp = new URLSearchParams(location.search);
  if (sp.has('info')) return openInfo();
  if (sp.has('funnel')) return openFunnel();
  const q = sp.get('open');
  if (q) openSheet(q);
}

/* ---------------- 启动 ---------------- */
(async function init() {
  await Promise.all([load(null), loadHistory()]);
  openFromHash();
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    const hadController = !!navigator.serviceWorker.controller;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (hadController) location.reload();
    });
    navigator.serviceWorker.register(BASE + 'sw.js', { updateViaCache: 'none' }).catch(() => {});
  }
})();
