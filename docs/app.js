// AI 股票分析室 · 手机 app
// 数据来源：你的 GitHub repo 里每天自动生成的 reports/*.json（GitHub Actions 写进去的）
// 要用 AI 的功能（认识公司、圆桌）会打开你的 Streamlit 网站

"use strict";

// ---------------------------------------------------------------------------
// 设定：config.js 的默认值 + 手机里保存的设定（「查股 → 设定」）
// ---------------------------------------------------------------------------
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 无痕模式等情况：不保存就算了 */ } },
};

const CFG = Object.assign({ owner: "", repo: "", branch: "main", web: "", bot: "", dataBase: "" },
                          window.STOCK_CONFIG || {}, store.get("settings", {}));
if (!CFG.owner && location.hostname.endsWith(".github.io")) {
  CFG.owner = location.hostname.split(".")[0];               // lowjunren9910-creator.github.io
  CFG.repo = CFG.repo || location.pathname.split("/").filter(Boolean)[0] || "";  // /stock-bot/pwa/
}

const dataBase = () => CFG.dataBase ||
  (CFG.owner && CFG.repo ? `https://raw.githubusercontent.com/${CFG.owner}/${CFG.repo}/${CFG.branch}/reports/` : "");

const MARKETS = { bursa: "🇲🇾 Bursa", idx: "🇮🇩 IDX", us: "🇺🇸 美股" };
const PKEYS = ["1d", "1w", "1m", "3m"];
const PZH = { "1d": "1日", "1w": "1周", "1m": "1月", "3m": "3月", "1y": "1年" };
const SESS = { open: "开市", midday: "午间", close: "收市" };
const CATS = {
  oversold: ["错杀股", "股价大跌，但盈利和质量没变差，估值比自己历史便宜。"],
  growth: ["成长股", "营收和盈利高速增长、回报率高。"],
  double_kill: ["双杀股", "盈利下滑，估值也被调低。宜避开或等企稳。"],
};

const state = {
  tab: store.get("tab", "focus"),
  market: store.get("market", "bursa"),
  stem: null,          // 每日焦点选中的报告，例如 2026-11-04_close
  board: "gainers",    // 排行榜：涨幅 / 跌幅 / 放量 / 成交额
  index: null,
  sector: null,        // 板块详情：选中的板块名字
  sub: null,           // 「更多」里面打开的页面
  cmp: store.get("cmp", []),   // 对比篮子：最多 3 只
  qf: "all",           // 季报筛选
  offline: false,
  loadedAt: 0,
};

// ---------------------------------------------------------------------------
// 小工具
// ---------------------------------------------------------------------------
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const sign = v => (v > 0 ? "up" : v < 0 ? "down" : "");
const pct = (v, d = 2) => v == null ? "—" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}%`;
const num = (v, cur) => {
  if (v == null) return "—";
  const d = cur === "IDR" ? 0 : Math.abs(v) < 1 ? 3 : 2;
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};
const big = v => v == null ? "—" : v >= 1e12 ? `${(v / 1e12).toFixed(2)}T` : v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : `${(v / 1e6).toFixed(0)}M`;
const day = s => s ? `${Number(s.slice(5, 7))}月${Number(s.slice(8, 10))}日` : "";
const clock = s => (s || "").slice(11, 16);
const curSym = { MYR: "RM", IDR: "Rp", USD: "$" };

function webLink(kind, ticker) {
  if (!CFG.web) return null;
  return `${CFG.web.replace(/\/$/, "")}/?${kind}=${encodeURIComponent(ticker)}`;
}

function cmpButton(ticker) {
  const on = state.cmp.includes(ticker);
  return `<button class="btn ghost cmp-btn${on ? " on" : ""}" data-cmp="${esc(ticker)}">${on ? "✓ 已加入对比" : "＋ 对比"}</button>`;
}

function actionButtons(ticker) {
  const co = webLink("company", ticker), an = webLink("analyze", ticker);
  if (!co) return `<div class="actions">${cmpButton(ticker)}</div>
    <p class="muted">在「更多 → 设定」填上网站网址，就能从这里打开认识公司和基金经理圆桌。</p>`;
  return `<div class="actions wrap">
    <a class="btn" href="${co}" target="_blank" rel="noopener">认识公司</a>
    <a class="btn ghost" href="${an}" target="_blank" rel="noopener">走势和圆桌</a>
    ${cmpButton(ticker)}</div>`;
}

// ---------------------------------------------------------------------------
// 读取数据：先上网拿最新的，失败就用手机里存的上一份
// ---------------------------------------------------------------------------
async function getJSON(path) {
  const base = dataBase();
  if (!base) throw new Error("no-repo");
  const key = base + path;
  const url = `${key}?t=${Math.floor(Date.now() / 60000)}`;  // 每分钟换一次，避开旧缓存
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (res.status === 404) return null;
    if (!res.ok) throw new Error(res.status);
    try { (await caches.open("stock-data")).put(key, res.clone()); } catch { /* 存不了也没关系 */ }
    return await res.json();
  } catch (e) {
    try {
      const hit = await (await caches.open("stock-data")).match(key);
      if (hit) { state.offline = true; return await hit.json(); }
    } catch { /* ignore */ }
    throw e;
  }
}

async function loadIndex(force) {
  if (state.index && !force) return state.index;
  state.offline = false;
  state.index = await getJSON("index.json");
  state.loadedAt = Date.now();
  return state.index;
}

// ---------------------------------------------------------------------------
// 画面：顶部色带
// ---------------------------------------------------------------------------
function setBand(title, extraHTML, showMarkets) {
  $("#title").textContent = title;
  $("#markets").hidden = !showMarkets;
  document.querySelectorAll("#markets button").forEach(b =>
    b.setAttribute("aria-selected", String(b.dataset.m === state.market)));
  $("#band-extra").innerHTML = extraHTML || "";
  $("#offline").hidden = !state.offline;
}

function emptyView(title, text) {
  return `<div class="empty"><b>${esc(title)}</b>${esc(text)}</div>`;
}

function stockRow(x, opts = {}) {
  const cur = x.currency || opts.currency;
  const chg = opts.chg ?? x.change_pct ?? x.ret_1m;
  const tags = (x.tags || x.reasons || []).slice(0, 4);
  const stats = opts.stats ? opts.stats(x) : [];
  const chips = opts.chips ?? tags.map(t => `<span class="tag">${esc(t)}</span>`).join("");
  return `<details>
    <summary><div class="row-main">
      <span class="rank">${opts.rank ?? ""}</span>
      <span class="name">${esc(x.name)}<small>${esc(x.ticker)}</small></span>
      <span class="px">${x.price != null ? `<span class="p">${curSym[cur] || ""} ${num(x.price, cur)}</span><br>` : ""}
        <span class="pill ${sign(chg)}">${pct(chg)}</span></span>
    </div>${chips ? `<div class="tags">${chips}</div>` : ""}</summary>
    <div class="more">
      ${stats.length ? `<div class="stats">${stats.map(([k, v]) => `<div>${esc(k)}<b>${v}</b></div>`).join("")}</div>` : ""}
      ${actionButtons(x.ticker)}
    </div>
  </details>`;
}

// ---------------------------------------------------------------------------
// 焦点：开市 / 午间 / 收市报告
// ---------------------------------------------------------------------------
async function renderFocus() {
  const idx = await loadIndex();
  const stems = (idx && idx[state.market]) || [];
  if (!stems.length) {
    setBand("每日焦点", "", true);
    return emptyView("还没有报告", "交易日开市后会自动生成；也可以在 GitHub 的 Actions 手动跑一次「市场报告」。");
  }
  const latestDay = stems[0].slice(0, 10);
  if (!state.stem || !stems.includes(state.stem) || state.stem.slice(0, 10) !== latestDay) state.stem = stems[0];
  const r = await getJSON(`${state.market}/${state.stem}.json`);
  if (!r) return emptyView("找不到这份报告", "稍后再按右上角重新载入。");

  const today = stems.filter(s => s.startsWith(latestDay));
  const b = r.breadth, tot = Math.max(1, b.up + b.down + b.flat);
  const sessions = Object.entries(SESS).map(([k, v]) => {
    const st = `${latestDay}_${k}`, has = today.includes(st);
    return `<button data-stem="${st}" aria-selected="${st === state.stem}" ${has ? "" : "disabled"}>${r.market === "us" && k === "midday" ? "盘中" : v}</button>`;
  }).join("");
  setBand("每日焦点", `
    <div class="sessions" role="tablist">${sessions}</div>
    <div class="stamp">${day(r.date)} ${clock(r.generated_at)} ${esc(r.session_name)}${r.partial_day < 1 ? "（盘中数据）" : ""}</div>
    <div class="tape" role="img" aria-label="上涨 ${b.up} 只，下跌 ${b.down} 只">
      <span class="t-up" style="width:${b.up / tot * 100}%"></span><span class="t-flat" style="width:${b.flat / tot * 100}%"></span><span class="t-down" style="width:${b.down / tot * 100}%"></span>
    </div>
    <div class="tape-legend"><span><b>${b.up}</b>涨</span><span>平均 <b>${pct(b.avg_change)}</b></span><span><b>${b.down}</b>跌</span></div>`, true);

  const boards = { gainers: "涨幅", losers: "跌幅", volume_surge: "成交量放大", turnover_top: "成交额" };
  const stats = x => [["成交量", `${Number(x.vol_ratio).toFixed(1)} 倍`], ["波幅", pct(x.range_pct, 1).replace("+", "")], ["RSI", Number(x.rsi).toFixed(0)]];
  return `
    ${r.ai_comment ? `<p class="note"><small>AI 点评</small>${esc(r.ai_comment)}</p>` : ""}
    <section>
      <h2>最值得关注</h2>
      <p class="lede">综合涨跌幅、成交量异常、波幅和突破信号排名。只看大型股。</p>
      <div class="list">${r.watchlist.map((x, i) => stockRow(x, { rank: i + 1, currency: r.currency, stats })).join("")}</div>
    </section>
    <section>
      <h2>排行榜</h2>
      <div class="switch" role="tablist">${Object.entries(boards).map(([k, v]) =>
        `<button data-board="${k}" aria-selected="${k === state.board}">${v}</button>`).join("")}</div>
      <div class="list">${(r[state.board] || []).map(x => stockRow(x, { currency: r.currency, stats })).join("")}</div>
    </section>
    <p class="foot">扫描 ${b.scanned} 只大型股，已剔除 ${b.filtered_out.length} 只低价或成交冷清的股票。仅供学习参考。</p>`;
}

// ---------------------------------------------------------------------------
// 雷达：错杀股 / 成长股 / 双杀股
// ---------------------------------------------------------------------------
async function renderRadar() {
  const idx = await loadIndex();
  const dates = (idx && idx.screen && idx.screen[state.market]) || [];
  if (!dates.length) {
    setBand("选股雷达", "", true);
    return emptyView("还没有雷达报告", "每个交易日收市后会自动生成。");
  }
  const r = await getJSON(`screen/${state.market}/${dates[0]}.json`);
  setBand("选股雷达", `<div class="stamp">${day(r.date)} 收市后　扫描 ${r.scanned} 只大型股</div>`, true);
  const stats = x => [["营收增长", pct(x.rev_growth, 0)], ["盈利增长", pct(x.eps_growth, 0)],
                      ["ROE", x.roe == null ? "—" : `${Number(x.roe).toFixed(0)}%`],
                      ["P/E", x.pe == null ? "—" : Number(x.pe).toFixed(1)],
                      ["历史 P/E", x.pe_avg == null ? "—" : Number(x.pe_avg).toFixed(1)],
                      ["3 个月", pct(x.ret_3m, 0)]];
  const sections = Object.entries(CATS).map(([k, [title, desc]]) => `
    <section class="cat-${k}">
      <h2>${title}<span class="count">${r.counts[k]}</span></h2>
      <p class="lede">${desc}</p>
      ${r[k].length ? `<div class="list">${r[k].slice(0, 8).map(x => stockRow(x, { stats, chg: x.ret_1m })).join("")}</div>`
                    : `<p class="muted">今天没有符合条件的股票。</p>`}
    </section>`).join("");
  return `${r.ai_comment ? `<p class="note"><small>AI 基金经理点评</small>${esc(r.ai_comment)}</p>` : ""}
    ${sections}
    <p class="foot">涨跌显示的是 1 个月表现。规则筛选结果，是研究的起点，不是买卖建议。</p>`;
}

// ---------------------------------------------------------------------------
// KLCI 50
// ---------------------------------------------------------------------------
async function renderKlci() {
  const idx = await loadIndex();
  const dates = (idx && idx.klci) || [];
  if (!dates.length) {
    setBand("KLCI 50 观察", "", false);
    return emptyView("还没有 KLCI 报告", "马股收市后会自动生成。");
  }
  const r = await getJSON(`klci/${dates[0]}.json`);
  const rv = r.review || {};
  const left = rv.days_to_cutoff;
  setBand("KLCI 50 观察", rv.review ? `
    <div class="countdown">${left >= 0 ? `<span class="big">${left}</span><span class="unit">天后数据截止</span>`
                                        : `<span class="unit">数据已截止，等待 ${day(rv.announce)} 公布</span>`}</div>
    <div class="dates"><div>截止<b>${day(rv.cutoff)}</b></div><div>公布<b>${day(rv.announce)}</b></div><div>生效<b>${day(rv.effective)}</b></div></div>
    <div class="stamp">${esc(rv.review)}　${day(r.date)} 更新</div>` : "", false);

  let rows = "";
  r.top_candidates.slice(0, 30).forEach((c, i) => {
    if (i === r.slots) rows += `<div class="cutline">${r.slots} 个名额分界线</div>`;
    const gap = c.gap_pct <= 0 ? `<span class="up">高出 ${Math.abs(c.gap_pct).toFixed(0)}%</span>`
                               : `<span class="down">还差 ${c.gap_pct.toFixed(0)}%</span>`;
    rows += `<div class="row k-row">
      <span class="rank">${c.cand_rank ?? "—"}</span>
      <span class="name">${esc(c.name)}${c.eligible ? "" : " ⚠️"}<small>${esc(c.ticker)}　RM ${big(c.mcap)}</small></span>
      <span class="k-right"><span class="prob"><span class="bar"><i style="width:${c.prob}%"></i></span><b>${c.prob}%</b></span>
        <span class="gap">${gap}</span></span>
    </div>`;
  });
  const risk = r.at_risk && r.at_risk.length ? `
    <section><h2>现有成分股有风险</h2>
      <div class="list">${r.at_risk.map(c => `<div class="row k-row"><span></span>
        <span class="name">${esc(c.name)}<small>${esc(c.ticker)}</small></span>
        <span class="prob"><span class="bar"><i style="width:${c.prob}%"></i></span><b>${c.prob}%</b></span></div>`).join("")}</div>
    </section>` : "";
  return `
    ${r.ai_comment ? `<p class="note"><small>AI 分析师点评</small>${esc(r.ai_comment)}</p>` : ""}
    <section>
      <h2>最有机会入选</h2>
      <p class="lede">${esc(r.mode)}。门槛市值约 RM ${big(r.cutoff_mcap)}。</p>
      <div class="list">${rows}</div>
    </section>
    ${risk}
    <p class="foot">⚠️ = 自由流通量或流动性估算未达标。按公开规则模拟估算，不是官方结果。</p>`;
}

// ---------------------------------------------------------------------------
// 查股 + 设定
// ---------------------------------------------------------------------------
function renderSearch() {
  setBand("查股", `<div class="stamp">输入代码或简称，打开网站做深入分析</div>`, false);
  const recent = store.get("recent", []);
  const popular = ["MAYBANK", "PBBANK", "TENAGA", "PPB", "INARI", "NVDA", "AAPL", "BBCA"];
  const chips = list => list.map(t => `<button data-pick="${esc(t)}">${esc(t)}</button>`).join("");
  return `
    <form id="sform" class="search" autocomplete="off">
      <input id="q" name="q" placeholder="例如 PPB、4065、NVDA" aria-label="股票代码" enterkeyhint="search">
      <button class="btn" style="flex:0 0 84px">查</button>
    </form>
    ${recent.length ? `<section><h2>最近查过</h2><div class="chips">${chips(recent)}</div></section>` : ""}
    <section><h2>常用</h2><div class="chips">${chips(popular)}</div></section>
    <div id="sresult"></div>`;
}

function renderSettings() {
  setBand("设定", `<div class="stamp">只存在这部手机里</div>`, false);
  return `
    <section>
      <form id="cfg">
        <label class="field">网站网址（Streamlit）<input name="web" value="${esc(CFG.web)}" placeholder="https://你的名字.streamlit.app" inputmode="url"></label>
        <label class="field">Telegram 机器人用户名<input name="bot" value="${esc(CFG.bot)}" placeholder="例如 junren_stock_bot"></label>
        <label class="field">GitHub 用户名<input name="owner" value="${esc(CFG.owner)}" placeholder="例如 lowjunren9910-creator"></label>
        <label class="field">Repo 名字<input name="repo" value="${esc(CFG.repo)}" placeholder="stock-bot"></label>
        <div class="actions" style="margin-top:14px"><button class="btn">保存设定</button></div>
        <p id="saved" class="muted" hidden>已保存。</p>
      </form>
    </section>`;
}

function showResult(text) {
  const t = text.trim().toUpperCase();
  if (!t) return;
  const recent = [t, ...store.get("recent", []).filter(x => x !== t)].slice(0, 8);
  store.set("recent", recent);
  const tg = CFG.bot ? `<a class="btn ghost" href="https://t.me/${encodeURIComponent(CFG.bot.replace(/^@/, ""))}" target="_blank" rel="noopener">在 Telegram 问机器人</a>` : "";
  $("#sresult").innerHTML = `<div class="result"><h3>${esc(t)}</h3>${actionButtons(t)}${tg ? `<div class="actions" style="margin-top:8px">${tg}</div>` : ""}</div>`;
}


// ---------------------------------------------------------------------------
// 板块：轮动热力图 → 点板块 → 板块指数 + 成分股
// ---------------------------------------------------------------------------
function heatCell(v, lim) {
  if (v == null) return `<span class="hc">—</span>`;
  const a = Math.min(1, Math.abs(v) / lim);
  const bg = v >= 0 ? `rgba(19,153,106,${0.12 + a * 0.78})` : `rgba(217,72,59,${0.12 + a * 0.78})`;
  const fg = a > 0.55 ? "#fff" : "var(--ink)";
  return `<span class="hc num" style="background:${bg};color:${fg}">${v > 0 ? "+" : ""}${v.toFixed(1)}</span>`;
}

function spark(series, bench) {
  const W = 340, H = 120, pad = 6;
  const all = series.levels.concat(bench ? bench.levels : []);
  const lo = Math.min(...all), hi = Math.max(...all);
  const path = (lv) => lv.map((v, i) => `${(pad + i / (lv.length - 1) * (W - 2 * pad)).toFixed(1)},${(H - pad - (v - lo) / (hi - lo || 1) * (H - 2 * pad)).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="板块指数一年走势">
    ${bench ? `<polyline points="${path(bench.levels)}" class="sp-bench"/>` : ""}
    <polyline points="${path(series.levels)}" class="sp-main"/></svg>`;
}

function sectorCard(g, big) {
  const ph = g.photo && g.photo.url ? g.photo.url.replace("w=640", big ? "w=900" : "w=480") : "";
  const r1 = g.returns["1d"], rm = g.returns["1m"];
  return `<button class="scard${big ? " big" : ""}" data-sector="${esc(g.name)}" style="--c:${esc(g.color || "#22305A")}">
    ${ph ? `<img src="${esc(ph)}" alt="" loading="lazy" decoding="async" onerror="this.remove()">` : ""}
    <span class="scard-in">
      <span class="scard-name">${esc(g.emoji || "")} ${esc(g.name)}<small>${g.count} 家</small></span>
      <span class="scard-num"><b class="num ${sign(r1)}">${pct(r1, 1)}</b><small>1 日</small>
        <b class="num ${sign(rm)}">${pct(rm, 1)}</b><small>1 月</small></span>
    </span></button>`;
}

async function renderSectors() {
  const idx = await loadIndex();
  const dates = (idx && idx.sectors && idx.sectors[state.market]) || [];
  if (!dates.length) {
    setBand("板块", "", true);
    return emptyView("还没有板块报告", "每个交易日收市后会自动生成。");
  }
  const r = await getJSON(`sectors/${state.market}/${dates[0]}.json`);
  const mi = r.market_index;
  const themes = r.themes || [];
  const all = themes.concat(r.sectors);
  const sec = state.sector && all.find(s => s.name === state.sector);

  if (sec) {   // ---- 板块详情 ----
    setBand(sec.name, `
      <div class="stamp">${sec.count} 家公司　指数 <b class="num">${sec.level.toLocaleString("en-US")}</b> 点（一年前 = 1000）</div>
      <div class="dates">${["1d", "1m", "1y"].map(k => `<div>${PZH[k]}<b class="${sign(sec.returns[k])}">${pct(sec.returns[k], 1)}</b></div>`).join("")}</div>`, true);
    const stats = x => [["权重", `${x.weight}%`], ["1 个月", pct(x.chg_1m, 1)], ["1 年", pct(x.chg_1y, 1)],
                        ["市值", big(x.mcap)], ["P/E", x.pe == null ? "—" : Number(x.pe).toFixed(1)],
                        ["股息率", x.div_yield == null ? "—" : `${Number(x.div_yield).toFixed(1)}%`],
                        ["ROE", x.roe == null ? "—" : `${Number(x.roe).toFixed(1)}%`], ["行业", esc(x.industry || "—")]];
    return `
      <button class="back" data-sector="">‹ 全部板块</button>
      <div class="hero" style="--c:${esc(sec.color || "#22305A")}">
        ${sec.photo ? `<img src="${esc(sec.photo.url.replace("w=640", "w=900"))}" alt="" onerror="this.remove()">` : ""}
        <span>${esc(sec.emoji || "")} ${esc(sec.name)}</span></div>
      ${sec.desc ? `<p class="lede" style="margin-top:10px">${esc(sec.desc)}</p>` : ""}
      <section>
        <h2>板块指数 vs 全市场</h2>
        ${spark(sec.series, mi.series)}
        <p class="legend"><span class="l-main"></span>${esc(sec.name)}　<span class="l-bench"></span>全市场综合</p>
        ${sec.top_weight >= 40 ? `<p class="lede">最大的公司占 ${sec.top_weight}%，指数主要跟着它走。</p>` : ""}
      </section>
      <section>
        <h2>成分股</h2>
        <p class="lede">按市值排序。点开可以认识公司，或「＋ 对比」放进对比篮子。</p>
        <div class="list">${sec.members.map(x => stockRow({ ...x, currency: r.currency }, { chg: x.chg_1d, stats })).join("")}</div>
      </section>
      ${sec.photo ? `<p class="foot">照片：${esc(sec.photo.credit)}</p>` : ""}`;
  }

  // ---- 板块总览：照片卡片 + 热力图 ----
  setBand("板块", `<div class="stamp">${day(r.date)} 收市　${r.universe_size || ""} 只股票综合 1 日 ${pct(mi.returns["1d"])}　1 月 ${pct(mi.returns["1m"], 1)}</div>`, true);
  const rows = [...all].sort((a, b) => (b.returns["1w"] ?? -99) - (a.returns["1w"] ?? -99));
  const lim = Math.max(1, ...rows.flatMap(s => PKEYS.map(k => Math.abs(s.returns[k] || 0))));
  const credits = [...new Set(all.map(g => g.photo && g.photo.credit).filter(Boolean).map(c => c.replace(" / Unsplash", "")))];
  return `
    ${themes.length ? `<section><h2>主题板块</h2>
      <p class="lede">AI、发电、手套、REIT 这类热门主题。一只股票可以同时在几个主题里。</p>
      <div class="cards">${themes.map(g => sectorCard(g)).join("")}</div></section>` : ""}
    <section><h2>普通板块</h2>
      <div class="cards">${r.sectors.map(g => sectorCard(g)).join("")}</div></section>
    <section>
      <h2>板块轮动</h2>
      <p class="lede">数字是涨跌 %，按 1 周表现排序。</p>
      <div class="heat">
        <div class="hrow hhead"><span></span>${PKEYS.map(k => `<span>${PZH[k]}</span>`).join("")}</div>
        ${rows.map(s => `<button class="hrow" data-sector="${esc(s.name)}">
          <span class="hname">${esc(s.emoji || "")} ${esc(s.name)}<small>${s.count} 家</small></span>
          ${PKEYS.map(k => heatCell(s.returns[k], lim)).join("")}</button>`).join("")}
      </div>
    </section>
    <p class="foot">${esc(r.note)}${credits.length ? `<br>照片：${esc(credits.join("、"))}（Unsplash）` : ""}</p>`;
}

// ---------------------------------------------------------------------------
// 对比：2–3 只股票（用每天收市后的数据，不用等）
// ---------------------------------------------------------------------------
const CMP_ROWS = [  // [键, 中文, 越大越好?, 格式]
  ["price", "股价", null, "price"], ["mcap", "市值", null, "big"],
  ["pe", "本益比 P/E", false, "x"], ["pb", "股价/净值", false, "x"],
  ["div_yield", "股息率", true, "p"], ["roe", "ROE", true, "p"], ["margin", "净利率", true, "p"],
  ["rev_growth", "营收增长", true, "p"], ["eps_growth", "盈利增长", true, "p"],
  ["chg_1m", "1 个月", true, "pc"], ["chg_3m", "3 个月", true, "pc"], ["chg_1y", "1 年", true, "pc"],
  ["rsi", "RSI", null, "n"], ["q", "最新季报", null, "t"],
];

function cmpFmt(v, k, cur) {
  if (v == null || v === "") return "—";
  if (k === "price") return `${curSym[cur] || ""} ${num(v, cur)}`;
  if (k === "big") return big(v);
  if (k === "x") return Number(v).toFixed(1);
  if (k === "p") return `${Number(v).toFixed(1)}%`;
  if (k === "pc") return pct(v, 1);
  if (k === "n") return Number(v).toFixed(0);
  return esc(v);
}

async function findStocks(tickers) {
  const prices = (await getJSON("prices.json").catch(() => null)) || {};
  const idx = await loadIndex();
  const mkts = [...new Set(tickers.map(t => (prices[t] && prices[t].market) ||
    (t.endsWith(".KL") ? "bursa" : t.endsWith(".JK") ? "idx" : "us")))];
  const sect = {}, quart = {};
  await Promise.all(mkts.map(async m => {
    const d = idx && idx.sectors && idx.sectors[m] && idx.sectors[m][0];
    sect[m] = d ? await getJSON(`sectors/${m}/${d}.json`).catch(() => null) : null;
    quart[m] = (idx && (idx.quarterly || []).includes(m)) ? await getJSON(`quarterly/${m}.json`).catch(() => null) : null;
  }));
  return tickers.map(t => {
    const m = (prices[t] && prices[t].market) || (t.endsWith(".KL") ? "bursa" : t.endsWith(".JK") ? "idx" : "us");
    let row = null;
    const r = sect[m];
    if (r) for (const g of r.sectors) { row = g.members.find(x => x.ticker === t); if (row) break; }
    const q = quart[m] && quart[m].items && quart[m].items[t];
    return row ? { ...row, currency: r.currency, market: m, quarter: q,
                   q: q ? `${q.icon} ${q.verdict}` : null }
               : { ticker: t, name: (prices[t] && prices[t].name) || t, missing: true, market: m };
  });
}

async function renderCompare() {
  const prices = (await getJSON("prices.json").catch(() => null)) || {};
  setBand("股票对比", `<div class="stamp">最多 3 只　✓ = 那一项比较好</div>`, false);
  const options = Object.entries(prices).map(([t, v]) => `<option value="${esc(v.name)} (${esc(t)})">`).join("");
  const form = state.cmp.length < 3 ? `<form id="cform" class="search" autocomplete="off" style="margin-top:12px">
      <input name="t" list="c-list" placeholder="加一只股票（名字或代码）" aria-label="股票">
      <datalist id="c-list">${options}</datalist><button class="btn">加入</button></form>` : "";
  if (state.cmp.length < 2) {
    return `<button class="back" data-sub="">‹ 更多</button>${form}
      <p class="lede" style="margin-top:12px">${state.cmp.length ? `已选：${state.cmp.map(esc).join("、")}。再加一只。` :
        "在「板块」页面点开公司按「＋ 对比」，或直接在上面输入。试试 Top Glove、Hartalega、Kossan。"}</p>`;
  }
  const ss = await findStocks(state.cmp);
  const best = {}, wins = Object.fromEntries(ss.map(x => [x.ticker, 0]));
  for (const [k, , better] of CMP_ROWS) {
    if (better == null) continue;
    let vals = ss.filter(x => x[k] != null).map(x => [x.ticker, Number(x[k])]);
    if (k === "pe") vals = vals.filter(v => v[1] > 0);
    if (vals.length < 2) continue;
    const b = vals.reduce((a, c) => (better ? c[1] > a[1] : c[1] < a[1]) ? c : a);
    best[k] = b[0]; wins[b[0]]++;
  }
  const mixed = new Set(ss.map(x => x.currency)).size > 1;
  const head = `<div class="ctable" style="--n:${ss.length}">
    <div class="ch"></div>${ss.map(x => `<div class="ch"><b>${esc(x.name)}</b><small>${esc(x.ticker)}</small>
      <button class="linkbtn" data-cmpdel="${esc(x.ticker)}">移除</button></div>`).join("")}
    ${CMP_ROWS.map(([k, label, , f]) => `<div class="cl">${label}</div>${ss.map(x =>
      `<div class="cv${best[k] === x.ticker ? " best" : ""}">${x.missing ? "—" : cmpFmt(x[k], f, x.currency)}${best[k] === x.ticker ? " ✓" : ""}</div>`).join("")}`).join("")}
    <div class="cl">胜出</div>${ss.map(x => `<div class="cv"><b>${wins[x.ticker]} 项</b></div>`).join("")}
  </div>`;
  const qs = ss.filter(x => x.quarter);
  const web = webLink("compare", state.cmp.join(","));
  return `<button class="back" data-sub="">‹ 更多</button>
    ${form}
    <section>${head}
      ${mixed ? `<p class="lede" style="margin-top:8px">货币不同，股价和市值不能直接比。</p>` : ""}
      ${ss.some(x => x.missing) ? `<p class="lede" style="margin-top:8px">有的股票不在系统追踪的名单里，所以没有数据。用网站版可以比任何股票。</p>` : ""}
    </section>
    ${qs.length ? `<section><h2>最新季报</h2><div class="list">${qs.map(x => `<div class="qline"><b>${esc(x.name)}</b>
      ${esc(x.quarter.icon)} ${esc(x.quarter.verdict)}（${esc(x.quarter.period)}）<br><small>${esc((x.quarter.reasons || []).join("；"))}</small></div>`).join("")}</div></section>` : ""}
    <div class="actions" style="margin-top:14px">
      ${web ? `<a class="btn" href="${web}" target="_blank" rel="noopener">完整对比 + AI 总结</a>` : ""}
      <button class="btn ghost" data-act="cmpclear">清空</button></div>
    <p class="foot">数据是最近一次收市后的数字。仅供参考，不构成投资建议。</p>`;
}

// ---------------------------------------------------------------------------
// 季报：最近公布的季度报告 + 快速结论
// ---------------------------------------------------------------------------
const QF = { all: "全部", new: "新发现", good: "亮眼/稳健", bad: "偏弱/亏损", watch: "自选股" };

function qbars(tr) {
  if (!tr || !tr.periods || tr.periods.length < 2) return "";
  const vals = tr.revenue.concat(tr.net).filter(v => v != null);
  const hi = Math.max(1, ...vals.map(Math.abs));
  const W = 300, H = 90, n = tr.periods.length, bw = W / n;
  const bar = (v, i, off, cls) => v == null ? "" : `<rect class="${cls}" x="${(i * bw + off).toFixed(1)}" width="${(bw * 0.36).toFixed(1)}"
    y="${(v >= 0 ? H / 2 + 30 - v / hi * (H / 2 + 26) : H / 2 + 30).toFixed(1)}" height="${(Math.abs(v) / hi * (H / 2 + 26)).toFixed(1)}"/>`;
  return `<svg class="qbars" viewBox="0 0 ${W} ${H + 18}" role="img" aria-label="近几季营收和净利">
    ${tr.periods.map((p, i) => bar(tr.revenue[i], i, bw * 0.12, "qb-rev") + bar(tr.net[i], i, bw * 0.5, "qb-net") +
      `<text x="${(i * bw + bw / 2).toFixed(1)}" y="${H + 14}" text-anchor="middle">${p.slice(2, 7)}</text>`).join("")}
  </svg><p class="legend"><span class="l-rev"></span>营收　<span class="l-net"></span>净利</p>`;
}

async function renderQuarterly() {
  const idx = await loadIndex();
  const has = idx && (idx.quarterly || []).includes(state.market);
  const r = has ? await getJSON(`quarterly/${state.market}.json`).catch(() => null) : null;
  setBand("季报", r ? `<div class="stamp">追踪 ${r.tracked} / ${r.universe_size} 家　今天新发现 ${r.new_today.length} 份</div>` : "", true);
  const back = `<button class="back" data-sub="">‹ 更多</button>`;
  if (!r) return back + emptyView("还没有季报数据", "收市后会自动检查；第一次要几天才会累积完整。");
  const cut = new Date(Date.now() - 14 * 864e5).toISOString().slice(0, 10);
  const test = {
    all: () => true, new: x => (x.found || "") >= cut, watch: x => x.watch,
    good: x => ["亮眼", "稳健"].includes(x.verdict), bad: x => ["偏弱", "疲弱", "亏损"].includes(x.verdict),
  }[state.qf] || (() => true);
  const items = r.recent.map(t => r.items[t]).filter(Boolean).filter(test);
  const cur = r.currency;
  const row = x => stockRow({ ...x, price: null, currency: cur }, {
    chg: x.net_yoy,
    chips: `<span class="tag q-${esc(x.verdict)}">${esc(x.icon)} ${esc(x.verdict)}</span>
            <span class="tag">${esc(x.period)}</span>${x.found && x.found >= cut ? `<span class="tag gold">新</span>` : ""}
            ${x.watch ? `<span class="tag gold">⭐ 自选</span>` : ""}`,
    stats: q => [["营收按年", pct(q.rev_yoy, 1)], ["净利按年", pct(q.net_yoy, 1)],
                 ["营收按季", pct(q.rev_qoq, 1)], ["净利率", q.net_margin == null ? "—" : `${q.net_margin}%`],
                 ["每股盈利", q.eps == null ? "—" : q.eps], ["发现日期", q.found || "—"]],
  }).replace('<div class="more">', `<div class="more">${qbars(x.trend)}<p>${esc((x.reasons || []).join("；"))}</p>
      ${x.ai ? `<p class="note"><small>AI 快评</small>${esc(x.ai)}</p>` : ""}`);
  return `${back}
    <div class="switch" style="margin-top:12px">${Object.entries(QF).map(([k, v]) =>
      `<button data-qf="${k}" aria-selected="${state.qf === k}">${v}</button>`).join("")}</div>
    <p class="lede">绿色/红色数字 = 净利按年增长。点开看营收、利润率和近几季走势。</p>
    ${items.length ? `<div class="list">${items.slice(0, 80).map(row).join("")}</div>` : `<p class="muted">没有符合的季报。</p>`}
    <p class="foot">${esc(r.note)}</p>`;
}

// ---------------------------------------------------------------------------
// 我的：自选股（GitHub 名单）+ 投资组合（只存在这部手机）
// ---------------------------------------------------------------------------
const ALERT_ZH = { below: "跌破", above: "升破", change_pct: "单日 ±", rsi_below: "RSI <", rsi_above: "RSI >" };

function resolveTicker(text, prices) {
  const t = text.trim().toUpperCase();
  if (!t) return null;
  if (prices[t]) return t;
  if (/^\d{4}$/.test(t) && prices[`${t}.KL`]) return `${t}.KL`;
  if (prices[`${t}.JK`]) return `${t}.JK`;
  const m = t.match(/\(([^)]+)\)\s*$/);           // 从建议清单选的「Maybank (1155.KL)」
  if (m && prices[m[1]]) return m[1];
  const hit = Object.entries(prices).find(([k, v]) => (v.name || "").toUpperCase().replace(/\s/g, "") === t.replace(/\s/g, ""));
  return hit ? hit[0] : t;
}

// ---------------------------------------------------------------------------
// 新闻：只追踪感兴趣的公司 + AI 分析（短期 / 长期影响）
// ---------------------------------------------------------------------------
const VIEW_ICON = { "利好": "📈", "利空": "📉", "中性": "➖" };
const ago = iso => {
  const m = Math.max(1, Math.round((Date.now() - new Date(iso)) / 60000));
  return m < 60 ? `${m} 分钟前` : m < 2880 ? `${Math.round(m / 60)} 小时前` : `${Math.round(m / 1440)} 天前`;
};

function newsCard(e) {
  const imp = (k, label) => `<div class="impact v-${esc(e[k].view)}"><small>${label}</small>
    <b>${VIEW_ICON[e[k].view] || ""} ${esc(e[k].view)}</b><span>${esc(e[k].why)}</span></div>`;
  return `<details class="ncard">
    <summary>
      <span class="nhead"><b>${esc(e.name)}</b><small>${esc(e.ticker)}　${ago(e.published)}</small>
        <span class="stars" aria-label="重要性 ${e.importance}">${"★".repeat(e.importance)}${"☆".repeat(5 - e.importance)}</span></span>
      <span class="ntitle">${esc(e.headline_zh)}</span>
      <span class="nviews"><span class="tag v-${esc(e.short_term.view)}">短期 ${esc(e.short_term.view)}</span>
        <span class="tag v-${esc(e.long_term.view)}">长期 ${esc(e.long_term.view)}</span></span>
    </summary>
    <div class="nbody">
      ${e.analysis ? `<p>${esc(e.analysis)}</p>` : ""}
      <div class="impacts">${imp("short_term", "短期（几天到几周）")}${imp("long_term", "长期（一年以上）")}</div>
      <p class="muted" style="font-size:12.5px">把握度：${esc(e.confidence || "中")}${e.price && e.price.price != null ? `　股价 ${num(e.price.price)}（今天 ${pct(e.price.chg_1d)}）` : ""}</p>
      ${(e.articles || []).slice(0, 3).map(a => `<a class="nlink" href="${esc(a.link)}" target="_blank" rel="noopener">${esc(a.title)}<small>${esc(a.source || "")}　${ago(a.published)}</small></a>`).join("")}
      ${actionButtons(e.ticker)}
    </div></details>`;
}

async function renderNews() {
  const r = await getJSON("news/feed.json").catch(() => null);
  setBand("新闻追踪", r ? `<div class="stamp">追踪 ${r.companies.length} 家公司　更新 ${esc(r.updated)}</div>` : "", false);
  const back = `<button class="back" data-sub="">‹ 更多</button>`;
  if (!r) return back + emptyView("还没有新闻", "新闻追踪每小时自动跑一次，第一次运行后这里就会有内容。");
  const pick = state.newsPick || "";
  const evs = r.events.filter(e => (!pick || e.ticker === pick) && e.importance >= (state.newsAll ? 1 : 3));
  return `${back}
    <div class="switch" style="margin-top:12px"><button data-npick="" aria-selected="${!pick}">全部</button>
      ${r.companies.map(c => `<button data-npick="${esc(c.ticker)}" aria-selected="${pick === c.ticker}">${esc(c.name)}</button>`).join("")}</div>
    <p class="lede">${state.newsAll ? "显示全部新闻。" : "只显示重要性 3 星以上。"}
      <button class="linkbtn" data-act="newsall">${state.newsAll ? "只看重要的" : "显示全部"}</button></p>
    ${evs.length ? `<div class="nlist">${evs.slice(0, 50).map(newsCard).join("")}</div>` : `<p class="muted">没有符合的新闻。</p>`}
    <p class="foot">${esc(r.note)}<br>想追踪别的公司：在 GitHub 编辑 watchlist.yml。</p>`;
}

async function renderMine() {
  setBand("我的", `<div class="stamp">自选股在 GitHub 的 watchlist.yml 设定；投资组合只存在这部手机</div>`, false);
  const [wl, prices, nf] = await Promise.all([getJSON("watchlist.json").catch(() => null), getJSON("prices.json").catch(() => null),
                                              getJSON("news/feed.json").catch(() => null)]);
  const hotNews = ((nf && nf.events) || []).filter(e => e.importance >= 3).slice(0, 4);
  const px = Object.assign({}, prices || {});
  (wl && wl.stocks || []).forEach(s => { if (s.price != null) px[s.ticker] = { ...(px[s.ticker] || {}), name: s.name, price: s.price, chg_1d: s.change_pct, currency: s.market === "bursa" ? "MYR" : s.market === "idx" ? "IDR" : "USD" }; });

  // 自选股
  const watch = (wl && wl.stocks || []).map(x => {
    const al = Object.entries(x.alerts || {}).map(([k, v]) => `<span class="tag${(x.triggered || []).includes(k) ? " hot" : ""}">${(x.triggered || []).includes(k) ? "🔔 " : ""}${ALERT_ZH[k] || k} ${esc(v)}</span>`);
    const cur = x.market === "bursa" ? "MYR" : x.market === "idx" ? "IDR" : "USD";
    if (x.error) return `<div class="row"><div class="row-main"><span></span><span class="name">${esc(x.input)}<small>${esc(x.error)}</small></span><span></span></div></div>`;
    const note = x.note ? `<span class="tag">${esc(x.note)}</span>` : "";
    return stockRow({ ...x, currency: cur },
      { chg: x.change_pct, chips: note + al.join(""),
        stats: () => [["RSI", Number(x.rsi).toFixed(0)], ["1 个月", pct(x.chg_1m, 1)], ["6 月区间", `${num(x.low_6m, cur)}–${num(x.high_6m, cur)}`]] });
  }).join("");
  const editUrl = CFG.owner && CFG.repo ? `https://github.com/${CFG.owner}/${CFG.repo}/edit/${CFG.branch}/watchlist.yml` : null;

  // 投资组合
  const pf = store.get("portfolio", []);
  const totals = {};
  const rows = pf.map((h, i) => {
    const p = px[h.ticker];
    const cur = (p && p.currency) || h.currency || "";
    const val = p ? p.price * h.qty : null, cost = h.cost * h.qty;
    const pl = val != null ? val - cost : null;
    if (val != null) { totals[cur] = totals[cur] || [0, 0]; totals[cur][0] += cost; totals[cur][1] += val; }
    return `<div class="row pf-row">
      <span class="name">${esc((p && p.name) || h.ticker)}<small>${esc(h.ticker)}　${h.qty.toLocaleString("en-US")} 股 @ ${num(h.cost, cur)}</small></span>
      <span class="px">${p ? `<span class="p">${curSym[cur] || ""} ${num(val, cur)}</span><br><span class="pill ${sign(pl)}">${pl >= 0 ? "+" : ""}${num(pl, cur)}（${pct(pl / cost * 100, 1)}）</span>` : `<span class="muted">暂无价格</span>`}</span>
      <button class="x" data-del="${i}" aria-label="删除 ${esc(h.ticker)}">×</button></div>`;
  }).join("");
  const tot = Object.entries(totals).map(([c, [cost, val]]) => `<div><small>${c} 市值</small><b class="num">${num(val, c)}</b><span class="${sign(val - cost)}">${val - cost >= 0 ? "+" : ""}${num(val - cost, c)}（${pct((val / cost - 1) * 100, 1)}）</span></div>`).join("");
  const options = Object.entries(px).map(([k, v]) => `<option value="${esc(v.name)} (${esc(k)})">`).join("");

  return `
    ${hotNews.length ? `<section><h2>最新重要新闻</h2><div class="nlist">${hotNews.map(newsCard).join("")}</div>
      <div class="actions" style="margin-top:10px"><button class="btn ghost" data-gosub="news">看全部新闻 ›</button></div></section>` : ""}
    <section>
      <h2>自选股</h2>
      ${watch ? `<div class="list">${watch}</div>` : `<p class="muted">还没有自选股。</p>`}
      ${editUrl ? `<div class="actions" style="margin-top:10px"><a class="btn ghost" href="${editUrl}" target="_blank" rel="noopener">在 GitHub 编辑名单和提醒</a></div>` : ""}
      ${wl ? `<p class="foot">更新：${esc(wl.updated)}。触发提醒会推送到 Telegram。</p>` : ""}
    </section>
    <section>
      <h2>投资组合</h2>
      ${tot ? `<div class="totals">${tot}</div>` : ""}
      ${rows ? `<div class="list">${rows}</div>` : `<p class="muted">还没有持股。在下面加第一笔。</p>`}
      <form id="pform" class="pform" autocomplete="off">
        <input name="t" list="pf-list" placeholder="股票（例如 Maybank 或 1155）" aria-label="股票" required>
        <datalist id="pf-list">${options}</datalist>
        <input name="q" type="number" inputmode="decimal" step="any" min="0" placeholder="数量" aria-label="数量" required>
        <input name="c" type="number" inputmode="decimal" step="any" min="0" placeholder="平均成本" aria-label="平均成本" required>
        <button class="btn">加入</button>
      </form>
      <p class="foot">价格用每天收市后的最新价，只有系统追踪的约 500 只大中型股有价格。
        <button class="linkbtn" data-act="export">备份</button>　<button class="linkbtn" data-act="import">还原</button></p>
    </section>`;
}

// ---------------------------------------------------------------------------
// 更多：KLCI 50、成绩单、周报、查股、系统状态、设定
// ---------------------------------------------------------------------------
const SUBS = {
  news: ["新闻追踪", "感兴趣公司的新闻 + AI 分析短期 / 长期影响"],
  compare: ["股票对比", "2–3 只股票放在一起比"],
  quarterly: ["季度报告", "最近公布的季报 + 快速结论"],
  klci: ["KLCI 50 观察", "哪些马股最有机会进入 KLCI 50"],
  track: ["成绩单", "推荐过的股票后来表现 + AI 基金经理排行榜"],
  weekly: ["每周周报", "每个星期六早上自动生成"],
  search: ["查股", "输入代码，打开网站做深入分析"],
  health: ["系统状态", "股票代码健康检查、数据更新时间"],
  settings: ["设定", "网站网址、GitHub 资料"],
};

function renderMore() {
  setBand("更多", "", false);
  return `<div class="list menu">${Object.entries(SUBS).map(([k, [t, d]]) =>
    `<button class="row menu-row" data-sub="${k}"><span class="name">${t}<small>${d}</small></span><span class="chev">›</span></button>`).join("")}</div>`;
}

async function renderTrack() {
  const r = await getJSON(`track/${state.market}.json`).catch(() => null);
  setBand("成绩单", r ? `<div class="stamp">对照 ${esc(r.benchmark)}　超额 = 股票涨跌 − 大盘涨跌</div>` : "", true);
  if (!r) return emptyView("还没有成绩单", "收市后会自动生成；推荐累积几天到几周后才看得出成绩。");
  const H = ["1w", "1m", "3m"];
  const strat = Object.entries(r.summary).map(([k, v]) => `
    <div class="row track-row">
      <span class="name">${v.name}<small>共 ${v.picks} 次推荐</small></span>
      ${H.map(h => { const d = v[h]; return `<span class="tcell"><small>${r.horizons[h]}</small>${d.n ? `<b class="num ${sign(k === "double_kill" ? -d.avg_excess : d.avg_excess)}">${pct(d.avg_excess, 1)}</b><small>${k === "double_kill" ? "避开" : "胜"} ${d.hit_rate}%</small>` : `<b class="muted">—</b><small>累积中</small>`}</span>`; }).join("")}
    </div>`).join("");
  const lb = r.leaderboard;
  const scored = lb.some(x => x.n);
  const board = scored ? lb.map((x, i) => `<div class="row track-row"><span class="rank">${x.hit_rate != null ? i + 1 : ""}</span>
      <span class="name">${x.emoji} ${esc(x.name)}<small>${esc(x.title)}　已评分 ${x.n}</small></span>
      <span class="tcell"><small>准确率</small><b class="num">${x.hit_rate == null ? "—" : x.hit_rate + "%"}</b></span>
      <span class="tcell"><small>看多超额</small><b class="num ${sign(x.bull_avg_excess)}">${pct(x.bull_avg_excess, 1)}</b></span></div>`).join("")
    : `<p class="muted">还在累积：已经记录 ${lb.reduce((a, x) => a + x.pending, 0)} 个评级，过 21 个交易日就会开始评分。</p>`;
  return `
    <button class="back" data-sub="">‹ 更多</button>
    <section><h2>推荐成绩（平均超额回报）</h2>
      <p class="lede">双杀股是要避开的名单，跌得比大盘多才算准。</p>
      <div class="list">${strat}</div></section>
    <section><h2>AI 基金经理排行榜</h2><p class="lede">看 21 个交易日后有没有猜对方向。</p>
      ${scored ? `<div class="list">${board}</div>` : board}</section>`;
}

async function renderWeekly() {
  const idx = await loadIndex();
  const dates = (idx && idx.weekly) || [];
  setBand("每周周报", dates.length ? `<div class="stamp">${day(dates[0])}</div>` : "", false);
  if (!dates.length) return `<button class="back" data-sub="">‹ 更多</button>` + emptyView("还没有周报", "第一个星期五美股收市后（星期六早上）会出现。");
  const r = await getJSON(`weekly/${dates[0]}.json`);
  const mk = Object.values(r.markets).map(v => `
    <section><h2>${esc(v.name)}<span class="count ${sign(v.week)}">${pct(v.week)}</span></h2>
      <div class="heat">${v.sectors.map(s => `<div class="hrow wk"><span class="hname">${esc(s.name)}</span>${heatCell(s.week, 4)}</div>`).join("")}</div>
      <p class="lede" style="margin-top:8px">涨最多：${v.gainers.slice(0, 3).map(g => `${esc(g.name)} <span class="up">${pct(g.chg_1w, 1)}</span>`).join("、")}</p>
      <p class="lede">跌最多：${v.losers.slice(0, 3).map(g => `${esc(g.name)} <span class="down">${pct(g.chg_1w, 1)}</span>`).join("、")}</p>
    </section>`).join("");
  return `<button class="back" data-sub="">‹ 更多</button>
    ${r.ai_comment ? `<p class="note"><small>本周总结</small>${esc(r.ai_comment)}</p>` : ""}${mk}`;
}

async function renderHealth() {
  const [h, idx] = await Promise.all([getJSON("health.json").catch(() => null), loadIndex()]);
  setBand("系统状态", `<div class="stamp">报告目录更新：${esc((idx && idx.updated) || "—")}</div>`, false);
  const body = !h ? emptyView("还没有检查结果", "每个星期六早上自动检查一次。")
    : `<section><h2>股票代码 ${h.ok} / ${h.total} 正常</h2><p class="lede">检查时间 ${esc(h.checked)}</p>
       ${h.problems.length ? `<div class="list">${h.problems.map(p => `<div class="row"><div class="row-main"><span></span><span class="name">${esc(p.name)}<small>${esc(p.ticker)}　${esc(p.status)}</small></span><span></span></div></div>`).join("")}</div>`
                           : `<p class="muted">全部正常。</p>`}</section>`;
  return `<button class="back" data-sub="">‹ 更多</button>${body}`;
}

async function renderMoreRouter() {
  const back = `<button class="back" data-sub="">‹ 更多</button>`;
  switch (state.sub) {
    case "news": return await renderNews();
    case "compare": return await renderCompare();
    case "quarterly": return await renderQuarterly();
    case "klci": return back + await renderKlci();
    case "track": return await renderTrack();
    case "weekly": return await renderWeekly();
    case "search": return back + renderSearch();
    case "health": return await renderHealth();
    case "settings": return back + renderSettings();
    default: return renderMore();
  }
}

// ---------------------------------------------------------------------------
// 切换和事件
// ---------------------------------------------------------------------------
const VIEWS = { focus: renderFocus, sectors: renderSectors, radar: renderRadar, mine: renderMine, more: renderMoreRouter };
if (!VIEWS[state.tab]) { state.sub = state.tab === "klci" || state.tab === "search" ? state.tab : null; state.tab = "more"; }

function cmpBar() {
  if (!state.cmp.length || (state.tab === "more" && state.sub === "compare")) return "";
  return `<div style="height:58px"></div><button class="cmpbar" data-gocmp="1">⚖️ 对比篮子：${state.cmp.length} 只　去对比 ›</button>`;
}

function setCmp(list) { state.cmp = list.slice(0, 3); store.set("cmp", state.cmp); }

async function render(force) {
  document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  const btn = $("#refresh");
  btn.classList.add("spin");
  try {
    if (force) await loadIndex(true);
    $("#view").innerHTML = await VIEWS[state.tab]() + cmpBar();
  } catch (e) {
    const noRepo = String(e.message) === "no-repo";
    setBand($("#title").textContent, "", false);
    $("#view").innerHTML = noRepo
      ? emptyView("还没设定数据来源", "到「查股 → 设定」填上 GitHub 用户名和 repo 名字。")
      : emptyView("载入失败", `检查网络后按右上角重新载入。（${e.message}）`);
  } finally {
    btn.classList.remove("spin");
    $("#offline").hidden = !state.offline;
  }
}

document.addEventListener("click", e => {
  const t = e.target.closest("button, a");
  if (!t) return;
  if (t.dataset.tab) {
    if (t.dataset.tab === state.tab) { state.sector = null; state.sub = null; }   // 再按一次 = 回到这一页的首页
    state.tab = t.dataset.tab; store.set("tab", state.tab); window.scrollTo(0, 0); render();
  }
  else if (t.dataset.cmp) {
    const k = t.dataset.cmp;
    if (state.cmp.includes(k)) setCmp(state.cmp.filter(x => x !== k));
    else if (state.cmp.length >= 3) { alert("对比最多 3 只，先移除一只。"); return; }
    else setCmp([...state.cmp, k]);
    const open = [...document.querySelectorAll("details[open] summary .name small")].map(e => e.textContent);
    render().then(() => document.querySelectorAll("details summary .name small").forEach(e => {
      if (open.includes(e.textContent)) e.closest("details").open = true; }));
  }
  else if (t.dataset.cmpdel) { setCmp(state.cmp.filter(x => x !== t.dataset.cmpdel)); render(); }
  else if (t.dataset.act === "cmpclear") { setCmp([]); render(); }
  else if (t.dataset.gocmp) { state.tab = "more"; state.sub = "compare"; store.set("tab", "more"); window.scrollTo(0, 0); render(); }
  else if (t.dataset.npick !== undefined) { state.newsPick = t.dataset.npick; render(); }
  else if (t.dataset.act === "newsall") { state.newsAll = !state.newsAll; render(); }
  else if (t.dataset.gosub) { state.tab = "more"; state.sub = t.dataset.gosub; store.set("tab", "more"); window.scrollTo(0, 0); render(); }
  else if (t.dataset.qf) { state.qf = t.dataset.qf; render(); }
  else if (t.dataset.sector !== undefined) { state.sector = t.dataset.sector || null; window.scrollTo(0, 0); render(); }
  else if (t.dataset.sub !== undefined) { state.sub = t.dataset.sub || null; window.scrollTo(0, 0); render(); }
  else if (t.dataset.del !== undefined) {
    const pf = store.get("portfolio", []); pf.splice(Number(t.dataset.del), 1); store.set("portfolio", pf); render();
  }
  else if (t.dataset.act === "export") {
    const blob = new Blob([JSON.stringify(store.get("portfolio", []), null, 1)], { type: "application/json" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "my-portfolio.json"; a.click();
  }
  else if (t.dataset.act === "import") {
    const inp = document.createElement("input"); inp.type = "file"; inp.accept = "application/json,.json";
    inp.onchange = async () => {
      try { const data = JSON.parse(await inp.files[0].text()); if (Array.isArray(data)) { store.set("portfolio", data); render(); } }
      catch { alert("文件格式不对，请选之前「备份」下载的文件。"); }
    };
    inp.click();
  }
  else if (t.dataset.m) { state.market = t.dataset.m; store.set("market", state.market); state.stem = null; state.sector = null; render(); }
  else if (t.dataset.stem) { state.stem = t.dataset.stem; render(); }
  else if (t.dataset.board) { state.board = t.dataset.board; render(); }
  else if (t.dataset.pick) { $("#q").value = t.dataset.pick; showResult(t.dataset.pick); }
  else if (t.id === "refresh") render(true);
});

document.addEventListener("submit", e => {
  e.preventDefault();
  if (e.target.id === "sform") showResult(e.target.q.value);
  if (e.target.id === "cform") {
    const text = String(new FormData(e.target).get("t") || "");
    getJSON("prices.json").catch(() => ({})).then(prices => {
      const t = resolveTicker(text, prices || {});
      if (t && !state.cmp.includes(t)) setCmp([...state.cmp, t]);
      render();
    });
  }
  if (e.target.id === "pform") {
    const f = new FormData(e.target);
    getJSON("prices.json").catch(() => ({})).then(prices => {
      const pf = store.get("portfolio", []);
      const t = resolveTicker(String(f.get("t")), prices || {});
      const qty = Number(f.get("q")), cost = Number(f.get("c"));
      if (!t || !(qty > 0) || !(cost >= 0)) return;
      const old = pf.find(h => h.ticker === t);
      if (old) { old.cost = (old.cost * old.qty + cost * qty) / (old.qty + qty); old.qty += qty; }   // 平均成本
      else pf.push({ ticker: t, qty, cost, currency: (prices && prices[t] && prices[t].currency) || "" });
      store.set("portfolio", pf); render();
    });
  }
  if (e.target.id === "cfg") {
    const f = new FormData(e.target);
    const s = { web: f.get("web").trim(), bot: f.get("bot").trim(), owner: f.get("owner").trim(), repo: f.get("repo").trim() };
    store.set("settings", s);
    Object.assign(CFG, s);
    state.index = null;
    $("#saved").hidden = false;
  }
});

// 回到 app 时，超过 10 分钟没更新就自动重新载入
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - state.loadedAt > 10 * 60 * 1000 && state.tab !== "search") render(true);
});

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
render();
