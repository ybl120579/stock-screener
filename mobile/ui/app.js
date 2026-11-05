/* 选股 App 前端（原生 JS，无依赖） */
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const S = {
  snap: null,
  rows: [],
  sort: 'score',
  q: '',
  date: null,
  offline: false,
  busy: false,
};

const SORTS = [
  ['score', '冷度分'],
  ['retrace', '回踩幅度'],
  ['turnover', '换手率'],
  ['days', '首板最近'],
];

/* ---------------- 工具 ---------------- */
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = (v, d = 1) => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(d);
const sgn = v => (v > 0 ? '+' : '') + num(v, 1) + '%';
const cls = v => v > 0 ? 'up' : (v < 0 ? 'dn' : 'mut');
const fmtTime = t => (t && String(t).length >= 4) ? String(t).slice(0, 2) + ':' + String(t).slice(2, 4) : '—';
const money = v => {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 100) return num(v, 0) + '亿';
  if (a >= 1) return num(v, 2) + '亿';
  return num(v * 10000, 0) + '万';
};

function toast(msg, ms = 2000) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('on');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('on'), ms);
}

/* 站点可能部署在子路径（GitHub Pages /repo/），所有相对路径都以 BASE 为准 */
const BASE = location.pathname.replace(/[^/]*$/, '');

/* live：本机 app.py 服务；static：纯静态托管（GitHub Pages 等），读 data/*.json */
let MODE = null;
async function getMode() {
  if (MODE) return MODE;
  try {
    const r = await fetch(BASE + 'api/status', { cache: 'no-store' });
    MODE = r.ok ? 'live' : 'static';
  } catch (e) { MODE = 'static'; }
  if (MODE === 'static') { const b = $('#btnRefresh'); if (b) b.style.display = 'none'; }
  return MODE;
}

async function getJSON(url, timeout = 20000) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  try {
    const res = await fetch(url, { signal: ctl.signal, cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } finally { clearTimeout(timer); }
}

async function apiLive(path, opt = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), opt.timeout || 20000);
  try {
    const res = await fetch(path, { ...opt, signal: ctl.signal, cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } finally { clearTimeout(timer); }
}

/* 静态模式：把 /api/* 映射到 data/*.json */
async function apiStatic(path, opt = {}) {
  const u = new URL(path.replace(/^\//, ''), location.href);
  const q = u.searchParams;
  if (u.pathname.endsWith('api/refresh'))
    throw new Error('静态版每天自动更新，不需要手动刷新');
  if (u.pathname.endsWith('api/list')) {
    const d = q.get('date');
    return getJSON(d ? `${BASE}data/archive/${d}.json` : `${BASE}data/list.json`);
  }
  if (u.pathname.includes('api/stock/')) {
    const code = u.pathname.split('/').pop();
    let r = (S.rows || []).find(x => x.code === code);
    if ((!r || !r.chart) && S.date) {
      const d = await getJSON(`${BASE}data/archive/${S.date}.json`);
      r = (d.rows || []).find(x => x.code === code);
    }
    if (r && r.chart) return { stock: { code, chart: r.chart } };
    throw new Error('无 K 线数据');
  }
  if (u.pathname.endsWith('api/history')) return getJSON(BASE + 'data/history.json');
  if (u.pathname.endsWith('api/status')) return getJSON(BASE + 'data/status.json', 6000);
  throw new Error('接口不可用');
}

async function api(path, opt = {}) {
  return (await getMode()) === 'live' ? apiLive(path, opt) : apiStatic(path, opt);
}

/* ---------------- 加载 ---------------- */
async function load(showSkeleton = true) {
  if (showSkeleton && !S.snap) $('#list').innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  const url = '/api/list' + (S.date ? '?date=' + S.date : '');
  try {
    const d = await api(url);
    if (d.empty) {
      renderEmpty(d.message || '还没有生成名单');
      renderStatus(d.status);
      return;
    }
    S.snap = d; S.rows = d.rows || []; S.offline = false;
    localStorage.setItem('snap:' + d.trade_date, JSON.stringify(d));
    if (!S.date) localStorage.setItem('snap:last', d.trade_date);
    renderAll();
    loadHistory();
    loadStatus();
    loadErrorInfo();
    openFromHash();
  } catch (e) {
    const cached = localStorage.getItem('snap:' + (S.date || localStorage.getItem('snap:last')));
    if (cached) {
      S.snap = JSON.parse(cached); S.rows = S.snap.rows || []; S.offline = true;
      renderAll();
      toast('离线模式 · 数据截至 ' + S.snap.generated_at);
    } else {
      renderEmpty(...(MODE === 'static'
        ? ['还没有名单数据', '云端每天收盘后自动生成，稍后再打开看看。']
        : ['连接不到服务', '确认电脑上的 App 服务已启动，且手机与电脑在同一 WiFi。']));
    }
  }
}

function renderEmpty(title, sub = '') {
  $('#stats').innerHTML = '';
  $('#list').innerHTML = `<div class="empty"><b>${esc(title)}</b>${esc(sub)}
    <div style="margin-top:18px"><button class="iconbtn" style="width:auto;padding:0 16px;height:36px"
      onclick="doRefresh()">立即生成</button></div></div>`;
  $('#foot').innerHTML = '';
}

function renderAll() {
  renderStats();
  renderRenew();
  renderSorts();
  renderList();
  renderFoot();
}

function renderStatus(st) {
  S.status = st || S.status;
  renderRenew();
}

function ymdLocal(d = new Date()) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/* 工作日 16 点后，如果最新数据还不是今天的，就认为今天没更新成功 */
function isStale() {
  const snap = S.snap; if (!snap || !snap.trade_date) return false;
  const now = new Date();
  const wd = now.getDay();
  if (wd === 0 || wd === 6) return false;
  if (now.getHours() < 16) return false;
  return snap.trade_date < ymdLocal(now);
}

function renderRenew() {
  const el = $('#renew'); if (!el) return;
  const st = S.status;
  const bits = [];
  let dot = 'dot';
  if (S.offline) {
    dot = 'dot off';
    bits.push('离线 · 数据截至 ' + (S.snap ? S.snap.trade_date : '—'));
  } else if (st && st.running) {
    dot = 'dot warn';
    bits.push('正在重新筛选…' + (st.last_stage ? '（' + st.last_stage + '）' : ''));
  } else if (isStale()) {
    dot = 'dot bad';
    bits.push('今天还没更新成功 · 数据仍是 ' + S.snap.trade_date.slice(5));
    if (st && st.last_run) bits.push('上次成功 ' + st.last_run.slice(5, 16));
  } else {
    bits.push('每交易日 ' + (st && st.schedule ? st.schedule : '15:40') + ' 起自动更新');
    if (st && st.next_run) bits.push('下次 ' + st.next_run.slice(5));
    else if (S.snap) bits.push('下次开盘日');
    if (st && st.last_error) { dot = 'dot warn'; bits.push('上次更新失败'); }
  }
  if (S.err && S.err.time && !isStale()) {
    dot = 'dot bad';
    bits.push('任务失败：' + String(S.err.reason || '').slice(0, 40));
  }
  el.innerHTML = `<span class="${dot}"></span><span>${esc(bits.join(' · '))}</span>`;
}

/* ---------------- 概览 ---------------- */
function renderStats() {
  const d = S.snap; if (!d) return;
  const f = d.funnel || {};
  const vals = Object.values(f);
  const n0 = vals.length ? vals[0] : 0;
  const board = f['首板(1连板)'] ?? vals[2] ?? '—';
  const left = f['已回落到首板左侧'] ?? '—';
  $('#stats').innerHTML = `
    <div class="stat" data-funnel="1"><b>${d.count}</b><span>入选</span></div>
    <div class="stat" data-funnel="1"><b>${board}</b><span>真首板</span></div>
    <div class="stat" data-funnel="1"><b>${left}</b><span>回踩到位</span></div>
    <div class="stat" data-funnel="1"><b>${n0}</b><span>涨停池</span></div>`;
  const sub = `数据日期 ${d.trade_date} · ${d.generated_at.slice(11, 16)} 生成`
    + (S.offline ? ' · 离线' : '') + (d.elapsed_sec ? ` · ${d.elapsed_sec}s` : '');
  $('#sub').textContent = sub;
}

/* ---------------- 排序 ---------------- */
function renderSorts() {
  $('#sorts').innerHTML = SORTS.map(([k, label]) =>
    `<div class="chip ${S.sort === k ? 'on' : ''}" data-sort="${k}">${label}</div>`).join('');
}

/* ---------------- 列表 ---------------- */
function filtered() {
  const q = S.q.trim().toLowerCase();
  let rows = S.rows.filter(r => !q ||
    r.code.includes(q) || (r.name || '').toLowerCase().includes(q) ||
    (r.industry || '').toLowerCase().includes(q));
  const by = {
    score: (a, b) => b.score - a.score,
    retrace: (a, b) => a.retrace_pct - b.retrace_pct,
    turnover: (a, b) => a.today_turnover - b.today_turnover,
    days: (a, b) => a.days_since - b.days_since,
  }[S.sort];
  return rows.slice().sort(by);
}

function ring(score) {
  const r = 19, c = 2 * Math.PI * r, off = c * (1 - Math.min(100, Math.max(0, score)) / 100);
  const id = 'g' + Math.random().toString(36).slice(2, 7);
  return `<div class="ring">
    <svg width="44" height="44" viewBox="0 0 44 44">
      <defs><linearGradient id="${id}" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#5b8cff"/><stop offset="1" stop-color="#c084fc"/></linearGradient></defs>
      <circle cx="22" cy="22" r="${r}" fill="none" stroke="#1b222c" stroke-width="3.5"/>
      <circle cx="22" cy="22" r="${r}" fill="none" stroke="url(#${id})" stroke-width="3.5"
        stroke-linecap="round" stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${off.toFixed(1)}"/>
    </svg><span class="v">${num(score, 1)}</span></div>`;
}

function card(r, i) {
  const wtag = r.window === '5日内' ? 'w5' : 'w10';
  const hit = r.hit_type === '平台' ? '<span class="tag hit">平台命中</span>'
    : `<span class="tag open">${esc(r.hit_type)}命中</span>`;
  return `<div class="card" data-code="${esc(r.code)}">
    <div class="crow">
      <div class="rank">${i + 1}</div>
      <div class="nm">
        <h3>${esc(r.name)}<span class="code">${esc(r.code)}</span>${hit}</h3>
        <div class="sub">
          <span>${esc(r.industry || '—')}</span>
          <span class="tag ${wtag}">${esc(r.window)}</span>
          <span>首板 ${esc(r.board_date.slice(5))} · 距 ${r.days_since} 天</span>
        </div>
      </div>
      ${ring(r.score)}
    </div>
    <div class="kv">
      <div><i>回踩</i><b class="${cls(r.retrace_pct)}">${num(r.retrace_pct, 1)}%</b></div>
      <div><i>左偏</i><b class="${cls(r.left_dev_pct)}">${sgn(r.left_dev_pct)}</b></div>
      <div><i>今换手</i><b>${num(r.today_turnover, 2)}%</b></div>
      <div><i>户均</i><b>${num(r.holder_avg_wan, 1)}万</b></div>
      <div><i>成交</i><b>${money(r.amount_yi)}</b></div>
      <div><i>流通</i><b>${num(r.float_mcap_yi, 0)}亿</b></div>
      <div><i>60日涨</i><b class="${cls(r.gain60_pct)}">${sgn(r.gain60_pct)}</b></div>
      <div><i>户变</i><b class="${cls(-r.holder_chg_pct)}">${sgn(r.holder_chg_pct)}</b></div>
    </div>
    <div class="spark"><canvas data-spark="${i}"></canvas><span class="hint">近20日</span></div>
  </div>`;
}

function renderList() {
  const rows = filtered();
  if (!rows.length) {
    $('#list').innerHTML = `<div class="empty"><b>没有匹配的股票</b>换个关键字或排序试试</div>`;
    return;
  }
  $('#list').innerHTML = rows.map(card).join('');
  requestAnimationFrame(() => {
    document.querySelectorAll('canvas[data-spark]').forEach(cv => {
      const r = rows[+cv.dataset.spark];
      drawSpark(cv, r.spark || [], r.board_close);
    });
  });
}

function drawSpark(cv, vals, anchor) {
  const w = cv.clientWidth || 200, h = 26, dpr = window.devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr;
  const g = cv.getContext('2d'); g.scale(dpr, dpr);
  if (!vals.length) return;
  const mn = Math.min(...vals), mx = Math.max(...vals), rg = (mx - mn) || 1;
  const x = i => 1 + i * (w - 2) / Math.max(1, vals.length - 1);
  const y = v => h - 3 - (v - mn) / rg * (h - 6);
  const up = vals[vals.length - 1] >= vals[0];
  g.beginPath();
  vals.forEach((v, i) => i ? g.lineTo(x(i), y(v)) : g.moveTo(x(i), y(v)));
  g.strokeStyle = up ? '#ff5a5f' : '#22c58b';
  g.lineWidth = 1.4; g.lineJoin = 'round'; g.stroke();
  const grad = g.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, up ? 'rgba(255,90,95,.28)' : 'rgba(34,197,139,.28)');
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.lineTo(x(vals.length - 1), h); g.lineTo(x(0), h); g.closePath();
  g.fillStyle = grad; g.fill();
  if (anchor != null && anchor >= mn && anchor <= mx) {
    g.beginPath(); g.moveTo(0, y(anchor)); g.lineTo(w, y(anchor));
    g.setLineDash([3, 3]); g.strokeStyle = 'rgba(143,178,255,.55)'; g.lineWidth = 1; g.stroke();
  }
}

/* ---------------- 底部信息 ---------------- */
function renderFoot() {
  const d = S.snap; if (!d) return;
  $('#foot').innerHTML = `
    <div>冷度分只衡量「热度低 / 散户少 / 缩量」，不代表上涨概率</div>
    <div>数据 东方财富 · 生成于 ${esc(d.generated_at)}</div>
    <div>非投资建议，风险自担</div>`;
}

async function loadStatus() {
  try { renderStatus(await api('/api/status', { timeout: 6000 })); } catch (e) { renderRenew(); }
}

/* 云端任务失败时构建脚本会写 data/last_error.json（成功则删除） */
async function loadErrorInfo() {
  try {
    S.err = await getJSON(BASE + 'data/last_error.json', 5000);
  } catch (e) {
    S.err = null;
  }
  renderRenew();
}

/* ---------------- 历史日期 ---------------- */
async function loadHistory() {
  try {
    const d = await api('/api/history');
    const items = (d.items || []).slice(0, 12);
    if (items.length < 2) { $('#dates').innerHTML = ''; return; }
    $('#dates').innerHTML = items.map(it =>
      `<div class="chip ${(!S.date && it === items[0]) || S.date === it.date ? 'on' : ''}"
        data-date="${it.date}">${it.date.slice(5)} · ${it.count}只</div>`).join('');
  } catch (e) { /* ignore */ }
}

/* ---------------- 详情 ---------------- */
function metric(label, val, klass = '') {
  return `<div><i>${label}</i><b class="${klass}">${val}</b></div>`;
}

const WEIGHT_LABEL = {
  turnover_today: '今日换手率', turnover_5d: '5日均换手', amount_today: '成交额',
  vol_vs_board: '较首板缩量', avg_holding_value: '户均持股市值', holder_change: '股东户数下降',
  gain60: '60日涨幅', retail_flow: '小单净流入',
};

async function openSheet(code) {
  const row = S.rows.find(r => r.code === code);
  if (!row) return;
  const sh = $('#sheet');
  sh.classList.add('on');
  document.body.style.overflow = 'hidden';
  $('#pbody').innerHTML = '<div class="skel" style="height:200px"></div>';
  $('#phead').innerHTML = `<div class="bar"></div>
    <h2>${esc(row.name)}<span>${esc(row.code)} · ${esc(row.industry || '')}</span></h2>
    <div class="px"><b class="${cls(row.today_pct)}">${num(row.today_close, 2)}</b>
      <span class="${cls(row.today_pct)}">${sgn(row.today_pct)}</span>
      <span>今换手 ${num(row.today_turnover, 2)}%</span>
      <span>冷度 <b style="font-size:13px">${num(row.score, 1)}</b></span></div>`;
  let chart = { bars: [] };
  try {
    const d = await api('/api/stock/' + code + (S.date ? '?date=' + S.date : ''));
    chart = d.stock.chart || { bars: [] };
  } catch (e) { /* 兜底：空图 */ }
  $('#pbody').innerHTML = `
    <div class="chartbox"><canvas id="kc"></canvas></div>
    <div class="legend">
      <span><i style="background:#ff5a5f"></i>阳线</span>
      <span><i style="background:#22c58b"></i>阴线</span>
      <span><i style="background:#8fb2ff;border-radius:50%"></i>首板前收盘（左侧锚点）</span>
      <span><i style="background:rgba(91,140,255,.35)"></i>首板日</span>
    </div>
    <div class="mgrid">
      ${metric('首板日', esc(row.board_date))}
      ${metric('距今天数', row.days_since + ' 天')}
      ${metric('首板涨幅', sgn(row.board_pct), cls(row.board_pct))}
      ${metric('首板换手', num(row.board_turnover, 2) + '%')}
      ${metric('首板成交', money(row.board_amount_yi))}
      ${metric('封单占流通', num(row.seal_ratio_pct, 2) + '%')}
      ${metric('封板时间', fmtTime(row.board_first_time))}
      ${metric('首板前收盘', num(row.pre_close, 2))}
      ${metric('首板收盘', num(row.board_close, 2))}
      ${metric('首板开盘', num(row.board_open, 2))}
      ${metric('回踩幅度', num(row.retrace_pct, 1) + '%', cls(row.retrace_pct))}
      ${metric('左侧偏离', sgn(row.left_dev_pct), cls(row.left_dev_pct))}
      ${metric('命中类型', esc(row.hit_type))}
      ${metric('今日成交', money(row.amount_yi))}
      ${metric('较首板量比', num(row.vol_ratio_board, 2))}
      ${metric('5日均换手', num(row.turnover5, 2) + '%')}
      ${metric('户均持股市值', num(row.holder_avg_wan, 1) + ' 万')}
      ${metric('股东户数变化', sgn(row.holder_chg_pct), cls(-row.holder_chg_pct))}
      ${metric('小单净占比', sgn(row.retail_pct), cls(-row.retail_pct))}
      ${metric('流通市值', num(row.float_mcap_yi, 0) + ' 亿')}
      ${metric('60日涨幅', sgn(row.gain60_pct), cls(row.gain60_pct))}
      ${metric('股东数据', esc((row.holder_stat_date || '').slice(5) || '—'))}
    </div>
    <div class="sect"><span>冷度评分构成</span><b>${num(row.score, 1)} / 100</b></div>
    <div class="scorebar">
      ${Object.entries(row.score_parts || {}).map(([k, v]) => {
        const w = (S.snap.weights || {})[k] || 0;
        return `<div class="row"><span class="n">${WEIGHT_LABEL[k] || k}</span>
          <span class="track"><span class="fill" style="width:${Math.max(0, Math.min(100, v))}%"></span></span>
          <span class="s">${num(v, 0)} ·${num(v * w, 1)}</span></div>`;
      }).join('')}
      ${row.lhb_after_cnt ? `<div class="row"><span class="n">首板后龙虎榜</span>
        <span class="track"><span class="fill" style="width:0%"></span></span>
        <span class="s" style="color:#f5a524">-${row.lhb_after_cnt * (S.snap.params.lhb_after_penalty || 20)}</span></div>` : ''}
    </div>
    <div class="foot">左偏 = 现价 / 首板前收盘 − 1，越接近 0 说明越贴近首板起涨平台。</div>`;

  requestAnimationFrame(() => drawK($('#kc'), chart, row));
}

const FUNNEL_HINT = {
  '涨停池记录': '近 11 个交易日全部涨停记录（含连板、含各类板块）',
  '主板·非ST·非次新': '去掉创业板 / 科创板 / 北交所、ST 与 N/C 次新',
  '首板(1连板)': '当天是第一次涨停（连板数 = 1）',
  'K线数据充足': '至少有 45 根历史 K 线，够算回踩与均量',
  '首板前无涨停': '再往前 30 个交易日也没有涨停 —— 确认是「真首板」',
  '首板后无再涨停': '首板之后没有继续涨停，形态还在回落区间',
  '首板在时间窗口内': '首板距今 1–10 个交易日',
  '已回落到首板左侧': '从首板高点回落 ≥3%，且回到左侧（首板前收盘价）±3.5% 内',
  '热度/市值硬过滤': '换手、成交额、60 日涨幅、流通市值、人气榜前 100',
  '最终入选': '通过全部条件，按冷度分排序',
};

function auxNote(d) {
  const miss = d.aux_missing || [];
  const bits = [];
  if (d.spot_source) bits.push(`行情源：${d.spot_source}`);
  if (miss.length) bits.push(`${miss.join('、')} 本次未取到（相关评分按中性计）`);
  if (!bits.length) return '';
  return `<p class="dim aux">${bits.join(' · ')}</p>`;
}

function openFunnel() {
  const d = S.snap; if (!d) return;
  const f = d.funnel || {};
  const keys = Object.keys(f);
  const top = keys.length ? f[keys[0]] : 0;
  const rows = keys.map((k, i) => {
    const v = f[k];
    const prev = i === 0 ? v : f[keys[i - 1]];
    const cut = i === 0 ? '' : (prev - v > 0
      ? `<i class="cut">−${prev - v}</i>` : '<i class="cut zero">—</i>');
    const pct = top ? (100 * v / top) : 0;
    return `<div class="wide frow">
      <div class="ftop"><span class="fname">${k}</span>${cut}<b class="fval">${v}</b></div>
      <div class="fbar"><i style="width:${Math.max(1.5, pct)}%"></i></div>
      <div class="fhint">${FUNNEL_HINT[k] || ''}</div>
    </div>`;
  }).join('');
  const sh = $('#sheet');
  sh.classList.add('on');
  document.body.style.overflow = 'hidden';
  $('#phead').innerHTML = `<div class="bar"></div><h2>筛选漏斗<span>${d.trade_date} · 逐步收敛</span></h2>`;
  $('#pbody').innerHTML = `<div class="info">
    <p>从 ${top} 条涨停记录里，一层层筛到 <b>${d.count}</b> 只。左边数字是「这一层还剩多少」，
       右边 <i class="cut">−N</i> 是被这一层去掉的数量。</p>
    ${rows}
    ${auxNote(d)}
    <p class="dim">只做形态与热度过滤，不含任何未来信息；数据来自公开行情接口。</p>
  </div>`;
}

function openInfo() {
  const sh = $('#sheet');
  sh.classList.add('on');
  document.body.style.overflow = 'hidden';
  $('#phead').innerHTML = `<div class="bar"></div><h2>筛选条件与说明<span>每交易日 15:35 自动更新</span></h2>`;
  $('#pbody').innerHTML = `<div class="info">
    <h4>条件一：5 日内或 10 日内首板</h4>
    <p>取涨停池里「当日涨停、此前 30 个交易日没有涨停」的股票，也就是<b>真首板</b>。
       首板距今天数 1–5 天算「<b>5日内</b>」，6–10 天算「<b>10日内</b>」；首板之后<b>不能再有涨停</b>（否则就不是回落形态了）。</p>
    <h4>条件二：回落到首板左侧附近</h4>
    <p>首板是右侧的启动，<b>首板前一天的收盘价</b>就是左侧平台的位置。今天收盘价要
       <b>从首板最高点回落 3% 以上</b>，且回到首板前收盘价 <b>±3.5%</b> 以内（平台命中）；
       首板当天大幅高开的，回到首板开盘价 ±1.5% 也算（开盘价命中）。</p>
    <h4>条件三：只留主板、去掉 ST</h4>
    <p>保留 600 / 601 / 603 / 605 / 000 / 001 / 002 / 003 开头，剔除 ST、*ST、退市整理、
       名称带 <b>N/C</b> 的新股（K 线不足 45 根的也自动剔除），以及股价 &lt; 2 元的仙股。</p>
    <h4>条件四：热度低、散户少</h4>
    <p>先硬过滤：今日换手 ≤10%、5 日均换手 ≤12%、成交额 ≤20 亿、60 日涨幅 ≤60%、
       流通市值 10–1500 亿，并剔除东财人气榜前 100。<br>
       再算「<b>冷度分</b>」（0–100，越高越冷）：今日换手 20%、5 日均换手 15%、
       户均持股市值 20%、股东户数变化 10%、较首板缩量 12%、成交额 8%、60 日涨幅 8%、小单净流入 7%。</p>
    <h4>数据与更新</h4>
    <p>数据来自公开行情接口：行情快照、涨停池、K 线以<b>东方财富</b>为主，
       被限流时自动切<b>新浪行情</b>（快照）与<b>腾讯行情</b>（K 线），涨停池还会回退到仓库里的历史快照，
       所以某一路数据挂了也能出名单。<br>
       云端每交易日 15:35 起跑、最多重试 4 次；本机版服务每天收盘后重跑，当时没开机会在下次启动时补跑。
       本轮的取数情况可以在「筛选漏斗」页底部看到。</p>
    <h4>回测过没有</h4>
    <p>有。<b>python backtest.py --days 20</b> 会把每个交易日重放一遍，统计入选股票之后 1/3/5/10 天的表现。
       最近 20 个交易日（10-09 ~ 11-05）的结果：入选 516 次，T+5 均值 <b>-2.8%</b>、T+10 <b>-6.0%</b>，
       同期「所有首板股不加条件」是 T+5 -3.9%、T+10 -7.3%。<br>
       也就是说：这套过滤比“随便买首板”略好，但在这段时间里<b>绝对收益是负的</b>；
       冷度分越高的一组，T+10 表现确实更好（Q1 -3.9% vs Q5 -7.8%），但优势不大。
       样本只有 20 天、市场环境单一，别把回测当成未来收益的保证。</p>
    <h4>请注意</h4>
    <p>冷度分只衡量「热度低 / 散户少 / 缩量」，<b>不代表上涨概率</b>，也不是买入信号；
       首板回踩属于右侧转左侧的博弈形态，跌破首板前收盘价（左侧锚点）形态就破了，需要重新评估。
       非投资建议，风险自担。</p>
  </div>`;
}

function closeSheet() {
  $('#sheet').classList.remove('on');
  document.body.style.overflow = '';
}

function drawK(cv, payload, row) {
  if (!cv) return;
  const bars = (payload && payload.bars) || [];
  if (!bars.length) {
    const g0 = cv.getContext('2d');
    cv.width = 10; cv.height = 10;
    cv.parentNode.insertAdjacentHTML('beforeend',
      '<div style="color:#5d6775;font-size:11px;text-align:center;padding:8px">暂无K线数据</div>');
    return;
  }
  const W = cv.clientWidth, H = 200, dpr = window.devicePixelRatio || 1;
  cv.width = W * dpr; cv.height = H * dpr;
  const g = cv.getContext('2d'); g.scale(dpr, dpr);
  const padL = 34, padR = 8, padT = 8;
  const volH = 34, gap = 10;
  const plotW = W - padL - padR;
  const priceH = H - padT - volH - gap - 14;

  const hi = Math.max(...bars.map(b => b[4])), lo = Math.min(...bars.map(b => b[3]));
  const pad = (hi - lo) * 0.08 || 1;
  const top = hi + pad, bot = lo - pad;
  const y = v => padT + (top - v) / (top - bot) * priceH;
  const n = bars.length, step = plotW / n, bw = Math.max(1.6, step * 0.62);
  const x = i => padL + step * i + step / 2;
  const volTop = padT + priceH + gap;
  const vmax = Math.max(...bars.map(b => b[5])) || 1;

  // 网格与价格刻度
  g.font = '9px system-ui'; g.textBaseline = 'middle';
  for (let k = 0; k <= 2; k++) {
    const v = bot + (top - bot) * k / 2, yy = y(v);
    g.strokeStyle = 'rgba(255,255,255,.05)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(padL, yy); g.lineTo(W - padR, yy); g.stroke();
    g.fillStyle = '#5d6775'; g.textAlign = 'right';
    g.fillText(v.toFixed(2), padL - 4, yy);
  }

  // 首板日高亮带
  let bi = (payload.board_idx != null && payload.board_idx >= 0) ? payload.board_idx : -1;
  if (bi < 0 || bi >= bars.length) {
    bi = bars.findIndex(b => (b[0] || '').slice(0, 10) === row.board_date);
  }
  if (bi >= 0) {
    g.fillStyle = 'rgba(91,140,255,.12)';
    g.fillRect(padL + step * bi, padT, step, priceH + gap + volH);
  }

  // 蜡烛 + 量
  bars.forEach((b, i) => {
    const [, o, c, h, l, v] = b;
    const up = c >= o, col = up ? '#ff5a5f' : '#22c58b';
    g.strokeStyle = col; g.fillStyle = col; g.lineWidth = 1;
    g.beginPath(); g.moveTo(x(i), y(h)); g.lineTo(x(i), y(l)); g.stroke();
    const yo = y(o), yc = y(c), hh = Math.max(1, Math.abs(yc - yo));
    if (up) g.fillRect(x(i) - bw / 2, Math.min(yo, yc), bw, hh);
    else g.fillRect(x(i) - bw / 2, Math.min(yo, yc), bw, hh);
    const vh = v / vmax * volH;
    g.fillStyle = up ? 'rgba(255,90,95,.55)' : 'rgba(34,197,139,.55)';
    g.fillRect(x(i) - bw / 2, volTop + volH - vh, bw, vh);
  });

  // 左侧锚点线
  const anchor = row.pre_close;
  if (anchor && anchor >= bot && anchor <= top) {
    const yy = y(anchor);
    g.setLineDash([4, 3]); g.strokeStyle = 'rgba(143,178,255,.75)'; g.lineWidth = 1;
    g.beginPath(); g.moveTo(padL, yy); g.lineTo(W - padR, yy); g.stroke();
    g.setLineDash([]);
    const txt = '首板前收盘 ' + anchor.toFixed(2);
    g.font = '9px system-ui';
    const tw = g.measureText(txt).width + 8;
    g.fillStyle = 'rgba(15,20,28,.9)';
    g.fillRect(W - padR - tw, yy - 12, tw, 12);
    g.fillStyle = '#8fb2ff'; g.textAlign = 'right';
    g.fillText(txt, W - padR - 4, yy - 6);
  }

  // 首板标签
  if (bi >= 0) {
    const txt = '首板';
    g.font = '9px system-ui';
    const tw = g.measureText(txt).width + 8, cx = x(bi);
    const bx = Math.min(Math.max(padL, cx - tw / 2), W - padR - tw);
    g.fillStyle = 'rgba(91,140,255,.9)';
    g.fillRect(bx, padT - 1, tw, 12);
    g.fillStyle = '#fff'; g.textAlign = 'center';
    g.fillText(txt, bx + tw / 2, padT + 6);
  }

  // 日期轴
  g.font = '9px system-ui'; g.fillStyle = '#5d6775';
  [0, Math.floor(n / 2), n - 1].forEach((i, k) => {
    g.textAlign = k === 0 ? 'left' : (k === 2 ? 'right' : 'center');
    g.fillText((bars[i][0] || '').slice(5), x(i), H - 4);
  });
}

/* ---------------- 刷新 ---------------- */
async function doRefresh() {
  if (S.busy) return;
  S.busy = true;
  $('#btnRefresh').classList.add('spin');
  try {
    await api('/api/refresh', { method: 'POST', timeout: 8000 });
    toast('正在重新筛选…', 4000);
    const t0 = Date.now();
    while (Date.now() - t0 < 180000) {
      await new Promise(r => setTimeout(r, 1500));
      const st = await api('/api/status');
      if (st.last_stage) toast(st.last_stage, 1500);
      if (!st.running) {
        if (st.last_error) throw new Error(st.last_error);
        break;
      }
    }
    S.date = null;
    await load(false);
    loadStatus();
    toast('已更新到 ' + (S.snap ? S.snap.trade_date : '最新'));
  } catch (e) {
    toast('刷新失败：' + (e.message || e));
  } finally {
    S.busy = false;
    $('#btnRefresh').classList.remove('spin');
    $('#ptr').classList.remove('on');
  }
}

/* ---------------- 事件 ---------------- */
function bind() {
  $('#btnRefresh').addEventListener('click', doRefresh);
  $('#btnInfo').addEventListener('click', openInfo);

  $('#sheet .mask').addEventListener('click', closeSheet);

  document.addEventListener('click', e => {
    if (e.target.closest('#stats [data-funnel]')) { openFunnel(); return; }

    const card = e.target.closest('.card');
    if (card) openSheet(card.dataset.code);

    const s = e.target.closest('[data-sort]');
    if (s) { S.sort = s.dataset.sort; renderSorts(); renderList(); window.scrollTo({ top: 0, behavior: 'smooth' }); }

    const d = e.target.closest('[data-date]');
    if (d) {
      S.date = d.dataset.date;
      document.querySelectorAll('#dates .chip').forEach(c => c.classList.remove('on'));
      d.classList.add('on');
      load();
    }
  });

  let timer;
  $('#q').addEventListener('input', e => {
    clearTimeout(timer);
    const v = e.target.value;
    timer = setTimeout(() => { S.q = v; renderList(); }, 120);
  });

  // 下拉刷新
  let sy = null, pulling = false;
  window.addEventListener('touchstart', e => {
    if (window.scrollY <= 0) sy = e.touches[0].clientY;
  }, { passive: true });
  window.addEventListener('touchmove', e => {
    if (sy == null || pulling) return;
    const dy = e.touches[0].clientY - sy;
    if (dy > 70) { pulling = true; sy = null; $('#ptr').classList.add('on'); doRefresh(); }
  }, { passive: true });
  window.addEventListener('touchend', () => { sy = null; pulling = false; });

  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); });
}

/* ---------------- 深链：/  #/stock/603303 ---------------- */
function openFromHash() {
  const m = location.hash.match(/^#\/stock\/(\d{6})/);
  if (m && S.rows.some(r => r.code === m[1])) openSheet(m[1]);
  else {
    const sp = new URLSearchParams(location.search);
    if (sp.has('info')) { openInfo(); return; }
    if (sp.has('funnel')) { openFunnel(); return; }
    const q = sp.get('open');
    if (q && S.rows.some(r => r.code === q)) openSheet(q);
  }
}
window.addEventListener('hashchange', () => {
  if (!location.hash) closeSheet(); else openFromHash();
});

/* ---------------- 调试：?debug=1 显示尺寸 ---------------- */
function debugSizes() {
  if (!location.search.includes('debug')) return;
  const info = [];
  const q = (sel) => document.querySelector(sel);
  const w = (sel) => { const e = q(sel); return e ? Math.round(e.getBoundingClientRect().width) : -1; };
  info.push('doc ' + document.documentElement.scrollWidth + '/' + document.documentElement.clientWidth + ' inner ' + window.innerWidth);
  info.push('body ' + w('body') + ' wrap ' + w('.wrap') + ' stats ' + w('.stats')
    + ' list ' + w('#list') + ' card ' + w('.card') + ' kv ' + w('.kv')
    + ' spark ' + w('.spark') + ' canvas ' + w('.spark canvas') + ' nm ' + w('.nm'));
  const st = q('.stat');
  if (st) info.push('stat ' + w('.stat') + ' statSpan ' + getComputedStyle(q('.stat span')).fontSize
    + ' bodyFont ' + getComputedStyle(document.body).fontSize);
  const d = document.createElement('pre');
  d.id = 'dbg';
  d.style.cssText = 'position:fixed;left:0;bottom:0;z-index:999;background:#000;color:#0f0;font:10px monospace;padding:4px;margin:0;white-space:pre-wrap;max-width:100%';
  d.textContent = info.join('\n');
  document.body.appendChild(d);
  console.log(info.join('\n'));
}

/* ---------------- 启动 ---------------- */
bind();
load().then(() => setTimeout(debugSizes, 300));
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register(BASE + 'sw.js').catch(() => { });
}
