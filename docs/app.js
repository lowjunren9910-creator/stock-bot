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

function actionButtons(ticker) {
  const co = webLink("company", ticker), an = webLink("analyze", ticker);
  if (!co) return `<p class="muted">在「查股 → 设定」填上网站网址，就能从这里打开认识公司和基金经理圆桌。</p>`;
  return `<div class="actions">
    <a class="btn" href="${co}" target="_blank" rel="noopener">认识公司</a>
    <a class="btn ghost" href="${an}" target="_blank" rel="noopener">走势和圆桌</a></div>`;
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
  return `<details>
    <summary class="row-main">
      <span class="rank">${opts.rank ?? ""}</span>
      <span class="name">${esc(x.name)}<small>${esc(x.ticker)}</small></span>
      <span class="px"><span class="p">${curSym[cur] || ""} ${num(x.price, cur)}</span><br>
        <span class="pill ${sign(chg)}">${pct(chg)}</span></span>
    </summary>
    ${tags.length ? `<div class="tags">${tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
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
    <div id="sresult"></div>
    <section>
      <h2>设定</h2>
      <p class="lede">只存在这部手机里。</p>
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
// 切换和事件
// ---------------------------------------------------------------------------
const VIEWS = { focus: renderFocus, radar: renderRadar, klci: renderKlci, search: renderSearch };

async function render(force) {
  document.querySelectorAll(".tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
  const btn = $("#refresh");
  btn.classList.add("spin");
  try {
    if (force) await loadIndex(true);
    $("#view").innerHTML = await VIEWS[state.tab]();
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
  if (t.dataset.tab) { state.tab = t.dataset.tab; store.set("tab", state.tab); window.scrollTo(0, 0); render(); }
  else if (t.dataset.m) { state.market = t.dataset.m; store.set("market", state.market); state.stem = null; render(); }
  else if (t.dataset.stem) { state.stem = t.dataset.stem; render(); }
  else if (t.dataset.board) { state.board = t.dataset.board; render(); }
  else if (t.dataset.pick) { $("#q").value = t.dataset.pick; showResult(t.dataset.pick); }
  else if (t.id === "refresh") render(true);
});

document.addEventListener("submit", e => {
  e.preventDefault();
  if (e.target.id === "sform") showResult(e.target.q.value);
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
