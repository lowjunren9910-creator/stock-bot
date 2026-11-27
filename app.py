"""
app.py - 网页版股票分析（Streamlit）

本地运行：  streamlit run app.py
部署上网：  见 README「网页版」部分（Streamlit Community Cloud，免费）
"""

import asyncio
import hmac
import io
import html
import json
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

st.set_page_config(page_title="AI 股票分析室", page_icon="📊", layout="wide")

# 把 Streamlit Secrets 放进环境变量，managers.py 才读得到 key
try:
    for k, v in st.secrets.items():
        if isinstance(v, str):
            os.environ.setdefault(k, v)
except Exception:
    pass  # 本地没有 secrets.toml 就用 .env

import analysis as A  # noqa: E402
import company as C  # noqa: E402
import klci as K  # noqa: E402
import screener as SC  # noqa: E402
import scanner as S  # noqa: E402
import managers as M  # noqa: E402
import ui  # noqa: E402
import i18n  # noqa: E402

i18n.install()                       # 中 / EN 切换：把网站上显示的中文换成英文
if "lang" not in st.session_state:   # 网址带 ?lang=en 就直接用英文（重新整理也记得）
    st.session_state.lang = "EN" if st.query_params.get("lang", "").lower() == "en" else "中文"
M.LANG = st.session_state.get("lang") or "中文"   # AI 现场分析跟着换语言
ui.inject()

RATING_COLOR = {"强烈买入": "#16a34a", "买入": "#4ade80", "持有": "#eab308",
                "减持": "#f97316", "卖出": "#dc2626"}


# ---------------------------------------------------------------------------
# 密码保护：别人打不开，就不会用光你的 AI 额度
# ---------------------------------------------------------------------------

def check_password() -> bool:
    expected = os.getenv("APP_PASSWORD")
    if not expected:
        st.warning("⚠️ 还没设置 APP_PASSWORD，任何人都能使用这个网站。")
        return True
    if st.session_state.get("authed"):
        return True
    st.title("📊 AI 股票分析室")
    pw = st.text_input("请输入密码", type="password")
    if pw:
        if hmac.compare_digest(pw, expected):
            st.session_state.authed = True
            st.rerun()
        st.error("密码错误")
    return False


# ---------------------------------------------------------------------------
# 缓存：同一只股票 15 分钟内不重复抓数据；圆桌同一天只开一次（省 AI 额度）
# ---------------------------------------------------------------------------

@st.cache_data(ttl=900, show_spinner=False)
def cached_analysis(text: str) -> dict:
    return A.analyze_raw(text)


async def _panel(snapshot: dict):
    M.reset_clients()  # 每次新的事件循环都要新的连接
    opinions = await M.ask_all(snapshot)
    summary = await M.chairman_summary(snapshot, list(opinions))
    return list(opinions), summary


@st.cache_data(ttl=86400, show_spinner=False)
def cached_panel(ticker: str, day: str, snapshot: dict, lang: str = "中文"):
    return asyncio.run(_panel(snapshot))


# ---------------------------------------------------------------------------
# 画图
# ---------------------------------------------------------------------------

def price_chart(df: pd.DataFrame, ticker: str):
    d = A.add_indicators(df).tail(180)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25],
                        vertical_spacing=0.04)
    fig.add_trace(go.Candlestick(x=d.index, open=d["Open"], high=d["High"],
                                 low=d["Low"], close=d["Close"], name="股价",
                                 increasing_line_color="#16a34a",
                                 decreasing_line_color="#dc2626"), 1, 1)
    for col, name, color in [("SMA50", "50日均线", "#3b82f6"),
                             ("SMA200", "200日均线", "#f59e0b")]:
        fig.add_trace(go.Scatter(x=d.index, y=d[col], name=name,
                                 line=dict(width=1.4, color=color)), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["BB_UP"], line=dict(width=0),
                             showlegend=False, hoverinfo="skip"), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["BB_LO"], fill="tonexty", name="布林带",
                             line=dict(width=0), fillcolor="rgba(148,163,184,0.18)"), 1, 1)
    fig.add_trace(go.Scatter(x=d.index, y=d["RSI14"], name="RSI",
                             line=dict(color="#8b5cf6", width=1.3)), 2, 1)
    fig.add_hline(y=70, line_dash="dash", line_color="#dc2626", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#16a34a", row=2, col=1)
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_rangeslider_visible=False,
                      legend=dict(orientation="h", y=1.06), title=f"{ticker} 近 6 个月")
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    return fig


def sections_html(text: str) -> str:
    """把 【标题】内容 变成粗体标题 + 换行（HTML 安全）。"""
    import html, re
    t = html.escape(text.strip())
    t = re.sub(r"【(.+?)】", r"<br><b>【\1】</b><br>", t)
    t = re.sub(r"^(<br>)+", "", t).replace("\n<br>", "<br>").replace("\n", "<br>")
    return re.sub(r"(<br>){3,}", "<br><br>", t)


def fmt(x, nd=2, suffix=""):
    return A._num(x, nd, suffix)


# ---------------------------------------------------------------------------
# 页面：个股分析
# ---------------------------------------------------------------------------

STOCK_SECS = ["📈 概览", "🎙 AI 分析", "🏢 认识公司", "📰 新闻公告", "📋 技术面"]
CHART_PERIODS = {"1个月": 22, "3个月": 66, "6个月": 130, "1年": 260, "3年": "3y", "5年": "5y"}


@st.cache_data(ttl=3600, show_spinner=False)
def cached_history(ticker: str, period: str) -> pd.DataFrame:
    return A.get_history(ticker, period)


def line_chart(df: pd.DataFrame, cur: str, height: int = 380):
    c = df["Close"].dropna()
    up = len(c) > 1 and c.iloc[-1] >= c.iloc[0]
    color = "#22c55e" if up else "#ef4444"
    fill = "rgba(34,197,94,.12)" if up else "rgba(239,68,68,.12)"
    lo, hi = float(c.min()), float(c.max())
    pad = (hi - lo) * 0.08 or hi * 0.02
    fig = go.Figure(go.Scatter(x=c.index, y=c, mode="lines", line=dict(color=color, width=2.2),
                               fill="tozeroy", fillcolor=fill, name="收盘价",
                               hovertemplate=f"%{{x|%Y-%m-%d}}<br>{cur} %{{y:,.3f}}<extra></extra>"))
    fig.add_hline(y=float(c.iloc[0]), line_dash="dot", line_color="rgba(148,163,184,.5)")
    fig.update_layout(height=height, margin=dict(l=6, r=6, t=8, b=6), showlegend=False,
                      hovermode="x unified", yaxis=dict(range=[lo - pad, hi + pad], side="right"),
                      xaxis=dict(showgrid=False))
    return fig


def fact_grid(items: list[tuple[str, str]]) -> str:
    cells = "".join(f"<div style='background:rgba(148,163,184,.08);border:1px solid rgba(148,163,184,.18);"
                    f"border-radius:10px;padding:9px 12px'><div style='font-size:.74rem;opacity:.65'>{html.escape(k)}</div>"
                    f"<div style='font-weight:700;font-size:1.02rem;margin-top:2px'>{html.escape(str(v))}</div></div>"
                    for k, v in items)
    return f"<div style='display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px'>{cells}</div>"


def goto_analysis(ticker: str, sec: str = "📈 概览"):
    """任何地方点股票 → 个股页面（走势、资料、AI 分析、认识公司、新闻公告、技术面）。"""
    st.session_state.query = ticker
    st.session_state.stock_sec = sec
    st.session_state.nav = "📊 个股分析"


def goto_company(ticker: str):
    goto_analysis(ticker, "🏢 认识公司")


def picked_row(key: str):
    """表格：点一整行或点任何一格都算选了那一行。"""
    try:
        sel = st.session_state[key].selection
    except Exception:
        return None
    rows = list(sel.get("rows") or [])
    cells = list(sel.get("cells") or [])
    return rows[0] if rows else (cells[0][0] if cells else None)


def stock_button(ticker: str, key: str, label: str = "📈 看这只股票的全部资料", primary: bool = True, target=None):
    (target or st).button(label, key=key, on_click=goto_analysis, args=(ticker,), width="stretch",
                          type="primary" if primary else "secondary")


def set_sec(sec: str):
    st.session_state.stock_sec = sec


def run_panel(ticker: str, snapshot: dict):
    opinions, summary = cached_panel(ticker, str(date.today()), snapshot, M.LANG)
    st.session_state[f"panel_done_{ticker}"] = True
    return opinions, summary


def show_votes(opinions):
    votes = pd.Series([o["rating"] or "未表态" for o in opinions]).value_counts()
    pills = "".join(f"<span style='background:{RATING_COLOR.get(k, '#94a3b8')};color:white;padding:3px 12px;"
                    f"border-radius:999px;font-weight:700;margin:0 6px 4px 0;display:inline-block'>{k} × {v}</span>"
                    for k, v in votes.items())
    st.markdown(f"<div style='margin:4px 0 8px'>🗳 {pills}</div>", unsafe_allow_html=True)


def page_analysis():
    st.title("📊 个股分析")
    with st.form("search"):
        c1, c2 = st.columns([4, 1])
        text = c1.text_input("股票代码或名称", placeholder="输入股票：MAYBANK、1155、NVDA、BBCA…（在任何页面点股票也会来这里）",
                             label_visibility="collapsed")
        go_btn = c2.form_submit_button("查看", width="stretch", type="primary")
    if go_btn and text.strip():
        st.session_state.query = text.strip()
        st.session_state.stock_sec = "📈 概览"
    query = st.session_state.get("query")
    if not query:
        st.info("输入股票代码，或在「每日焦点」「选股雷达」「板块」等页面直接点任何一只股票。"
                "常用：MAYBANK、CIMB、TENAGA、IHH、GAMUDA、BBCA、TLKM、AAPL、NVDA")
        return

    with st.spinner(f"正在抓取 {query.upper()} 的股价、财务、新闻…"):
        try:
            r = cached_analysis(query)
        except Exception as e:
            st.error(f"❌ {e}")
            return
    ticker, tech, fund, news, snap = r["ticker"], r["tech"], r["fund"], r["news"], r["snapshot"]
    cur = fund["currency"]
    recent = snap.get("近期动态") or {}

    # --- 标题列 ---
    chg = tech["change_1d"]
    color = "#22c55e" if chg >= 0 else "#ef4444"
    meta = " · ".join(x for x in (ticker, A.market_of(ticker), fund["sector"], fund["industry"]) if x)
    st.markdown(
        f"<div style='display:flex;justify-content:space-between;align-items:flex-end;flex-wrap:wrap;gap:8px;margin-top:-6px'>"
        f"<div><div style='font-size:1.7rem;font-weight:800;line-height:1.2'>{html.escape(fund['name'])}</div>"
        f"<div style='opacity:.65;font-size:.88rem'>{html.escape(meta)}</div></div>"
        f"<div style='text-align:right'><span style='font-size:1.9rem;font-weight:800'>{cur} {fmt(tech['price'], 3)}</span> "
        f"<span style='color:{color};font-weight:700;font-size:1.1rem'>{chg:+.2f}% 今日</span>"
        f"<div style='opacity:.6;font-size:.78rem'>技术面：{tech['verdict']}（{tech['score']:+d}）</div></div></div>",
        unsafe_allow_html=True)

    if st.session_state.get("stock_sec") not in STOCK_SECS:
        st.session_state.stock_sec = "📈 概览"
    sec = st.segmented_control("看什么", STOCK_SECS, key="stock_sec", label_visibility="collapsed") or "📈 概览"

    if sec == "📈 概览":
        stock_overview(r, ticker, tech, fund, news, recent, cur)
    elif sec == "🎙 AI 分析":
        stock_ai(ticker, snap)
    elif sec == "🏢 认识公司":
        stock_company(ticker)
    elif sec == "📰 新闻公告":
        stock_news(ticker, news, recent)
    else:
        stock_tech(r, ticker, tech, fund, cur)
    st.caption("以上为数据整理和 AI 模拟观点，仅供学习参考，不构成投资建议。")


def stock_overview(r, ticker, tech, fund, news, recent, cur):
    per = st.pills("区间", list(CHART_PERIODS), default="6个月", key=f"per_{ticker}", label_visibility="collapsed") or "6个月"
    n = CHART_PERIODS[per]
    try:
        df = r["df"].tail(n) if isinstance(n, int) else cached_history(ticker, n)
    except Exception:
        df = r["df"]
    c = df["Close"].dropna()
    if len(c) > 1:
        ch = (c.iloc[-1] / c.iloc[0] - 1) * 100
        st.caption(f"{per}涨跌：**{ch:+.1f}%**　（{c.index[0]:%Y-%m-%d} → {c.index[-1]:%Y-%m-%d}，"
                   f"最高 {c.max():,.3f} · 最低 {c.min():,.3f}）")
        st.plotly_chart(line_chart(df, cur), width="stretch", key=f"line_{ticker}_{per}")

    pm = fund.get("profit_margin")
    rec = A.REC_ZH.get(fund["analyst_rec"], fund["analyst_rec"]) if fund.get("analyst_rec") else None
    st.markdown(fact_grid([
        ("1 个月", fmt(tech["change_1m"], 1, "%")), ("1 年", fmt(tech["change_1y"], 1, "%")),
        ("52 周区间", f"{fmt(tech['low_52w'])} – {fmt(tech['high_52w'])}"),
        ("市值", f"{cur} {A._big(fund['market_cap'])}"), ("本益比 P/E", fmt(fund["pe"], 1)),
        ("预期 P/E", fmt(fund["forward_pe"], 1)), ("股价/净值 P/B", fmt(fund["pb"], 2)),
        ("股息率", fmt(fund["dividend_yield"], 2, "%")),
        ("净利率", fmt(pm * 100 if pm is not None and abs(pm) < 1.5 else pm, 1, "%")),
        ("分析师目标价", f"{fmt(fund['target_price'])}（{rec}）" if fund.get("target_price") else "—"),
    ]), unsafe_allow_html=True)
    st.write("")

    left, right = st.columns([1.35, 1])
    with left.container(border=True):
        st.markdown("#### 🎙 AI 分析")
        err = M.check_setup()
        if err:
            st.warning(err)
        else:
            with st.spinner("5 位 AI 基金经理正在分析（第一次约 20-40 秒，之后当天都很快）…"):
                try:
                    opinions, summary = run_panel(ticker, r["snapshot"])
                except Exception as e:
                    opinions, summary = None, None
                    st.warning(f"AI 暂时无法分析：{e}")
            if opinions:
                show_votes(opinions)
                body = summary.split("\n\n", 1)[1] if summary.startswith("🗳") else summary
                st.markdown(f"<div style='line-height:1.75'>{sections_html(body)}</div>", unsafe_allow_html=True)
                st.button("看 5 位经理各自的详细看法 →", on_click=set_sec, args=("🎙 AI 分析",), key="ov_ai")
    with right:
        with st.container(border=True):
            st.markdown("#### 🧭 近期动态")
            q = recent.get("最新一季业绩")
            if q:
                yo = lambda v: "—" if v is None else f"{v:+.1f}%"
                st.markdown(f"**最新季报**（截至 {q['季度结束日']}）：{q.get('结论') or ''}　"
                            f"营收按年 {yo(q.get('营收按年%'))} · 净利按年 {yo(q.get('净利按年%'))}")
            for x in recent.get("公告日历", [])[:3]:
                st.markdown(f"📅 {html.escape(x)}")
            for x in recent.get("新闻追踪的重大事件", [])[:2]:
                st.markdown(f"⭐ {md(x)}")
            for x in recent.get("牵连这家公司的宏观事件", [])[:2]:
                st.markdown(f"🌐 {md(x)}")
            items = news.get("items") or []
            for i in items[:5]:
                d = ""
                if i.get("published"):
                    try:
                        dd = datetime.fromisoformat(str(i["published"]).replace("Z", "+00:00"))
                        d = f"{dd.month}/{dd.day} "
                    except Exception:
                        pass
                t = i["title"].replace("[", "(").replace("]", ")").replace("$", "\\$")
                st.markdown(f"📰 {d}[{t}]({i['link']})" if i.get("link") else f"📰 {d}{t}")
            if not (q or items or recent.get("公告日历")):
                st.write("最近 14 天没有新闻或公告。")
            st.button("全部新闻和公告 →", on_click=set_sec, args=("📰 新闻公告",), key="ov_news")
        with st.container(border=True):
            st.markdown("#### 🏢 这家公司")
            st.write(" · ".join(x for x in (fund["sector"], fund["industry"]) if x) or "—")
            for s in (fund.get("flags") or [])[:3]:
                st.write(s)
            b1, b2 = st.columns(2)
            b1.button("🏢 认识公司", on_click=set_sec, args=("🏢 认识公司",), width="stretch", key="ov_co")
            b2.button("⚖️ 拿去跟别家对比", on_click=goto_compare, args=([ticker],), width="stretch", key="ov_cmp")


def stock_ai(ticker, snapshot):
    err = M.check_setup()
    if err:
        st.error(err)
        return
    with st.spinner("5 位不同风格的 AI 基金经理正在独立分析…（约 20-40 秒）"):
        try:
            opinions, summary = run_panel(ticker, snapshot)
        except Exception as e:
            st.error(f"AI 暂时无法分析：{e}")
            return
    show_votes(opinions)
    with st.container(border=True):
        st.markdown("### 👔 投资委员会主席总结")
        summary_body = summary.split("\n\n", 1)[1] if summary.startswith("🗳") else summary
        st.markdown(f"<div style='line-height:1.8'>{sections_html(summary_body)}</div>", unsafe_allow_html=True)
    for start in range(0, len(opinions), 3):  # 每行 3 张卡片
        cols = st.columns(3)
        for col, o in zip(cols, opinions[start:start + 3]):
            with col.container(border=True):
                color = RATING_COLOR.get(o["rating"], "#94a3b8")
                body = (o["text"].split("\n", 1)[1] if o["text"].startswith("【评级】")
                        and "\n" in o["text"] else o["text"])
                st.markdown(
                    f"<div style='font-size:1.2rem;font-weight:700'>{o['emoji']} {o['name']}</div>"
                    f"<div style='opacity:.65;font-size:.85rem;margin-bottom:6px'>{o['title']}</div>"
                    f"<span style='background:{color};color:white;padding:2px 12px;"
                    f"border-radius:999px;font-weight:600'>{o['rating'] or '未表态'}</span>"
                    f"<div style='margin-top:10px;line-height:1.7'>{sections_html(body)}</div>",
                    unsafe_allow_html=True)
    st.caption(f"AI 供应商：{M.PROVIDER} · {M.MODEL}。AI 会参考最近 14 天新闻、最新季报和公告日历。"
               "每只股票每天只分析一次以节省额度。")


def stock_company(ticker):
    with st.spinner("正在收集公司资料和财报…"):
        try:
            p = cached_company(ticker)
        except Exception as e:
            st.error(f"❌ {e}")
            return
    show_company(p)


def stock_news(ticker, news, recent):
    c1, c2 = st.columns([1.4, 1])
    with c1:
        st.markdown("#### 📰 最近 14 天新闻")
        if not news["items"]:
            st.write("没有找到近期新闻（大马/印尼中小型股常见）。")
        else:
            st.caption(f"整体情绪：{news['mood']}（平均 {news['avg']:+.2f}）")
            for i in news["items"]:
                icon = "🟢" if i["score"] > 0.15 else "🔴" if i["score"] < -0.15 else "⚪"
                d = ""
                if i.get("published"):
                    try:
                        dd = datetime.fromisoformat(str(i["published"]).replace("Z", "+00:00"))
                        d = f"{dd.month}/{dd.day} "
                    except Exception:
                        pass
                t = i["title"].replace("[", "(").replace("]", ")").replace("$", "\\$")
                src = f" — {i['source']}" if i.get("source") else ""
                st.markdown(f"{icon} {d}[{t}]({i['link']}){src}" if i.get("link") else f"{icon} {d}{t}{src}")
        b1, b2 = st.columns(2)
        b1.button("🗞️ 让 AI 分析这些新闻的影响", on_click=goto_news, args=(ticker,), width="stretch")
    with c2:
        for title, k in (("⭐ 新闻追踪的重大事件", "新闻追踪的重大事件"), ("🌐 牵连的宏观事件", "牵连这家公司的宏观事件")):
            if recent.get(k):
                st.markdown(f"#### {title}")
                for x in recent[k]:
                    st.markdown("- " + md(x))
        st.markdown("#### 📅 公告日历")
        cal = recent.get("公告日历") or []
        st.markdown("\n".join("- " + html.escape(x) for x in cal) if cal else "最近 / 未来 45 天没有业绩或派息日期。")
        q = recent.get("最新一季业绩")
        if q:
            st.markdown("#### 📑 最新季报")
            st.markdown(f"截至 {q['季度结束日']}：**{q.get('结论') or ''}**")
            for x in q.get("重点", []):
                st.markdown("- " + md(x))
            st.button("看季报详情 →", on_click=goto_quarter, args=(ticker,))


def goto_news(ticker: str):
    st.session_state.news_query = ticker
    st.session_state.nav = "🗞️ 新闻追踪"


def stock_tech(r, ticker, tech, fund, cur):
    st.plotly_chart(price_chart(r["df"], ticker), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 📈 技术面")
        st.write(f"52 周区间：{fmt(tech['low_52w'])} – {fmt(tech['high_52w'])}")
        st.write(f"50 日均线：{fmt(tech['sma50'])}　200 日均线：{fmt(tech['sma200'])}")
        for s in tech["signals"]:
            st.write(s)
    with c2:
        st.markdown("#### 🏢 基本面")
        st.write(" · ".join(x for x in (fund["sector"], fund["industry"]) if x) or "行业：无数据")
        st.write(f"市值：{cur} {A._big(fund['market_cap'])}")
        st.write(f"预期 P/E：{fmt(fund['forward_pe'])}　P/B：{fmt(fund['pb'])}")
        if fund["target_price"]:
            rec = A.REC_ZH.get(fund["analyst_rec"], fund["analyst_rec"] or "无")
            st.write(f"分析师目标价：{fmt(fund['target_price'])}（{rec}）")
        for s in fund["flags"]:
            st.write(s)


# ---------------------------------------------------------------------------
# 页面：投资组合（存在浏览器 session，可下载/上传 CSV 保存）
# ---------------------------------------------------------------------------

async def _pf_ai(pdata, goal, horizon, dd):
    M.reset_clients()
    import pfcheck as PC
    return await PC.ai_report(pdata, goal, horizon, dd)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_pf_ai(key: str, _pdata: dict, goal: str, horizon: str, dd: str, lang: str = "中文") -> str:
    return asyncio.run(_pf_ai(_pdata, goal, horizon, dd))


def page_portfolio():
    import hashlib
    import pfcheck as PC
    st.title("💼 我的投资组合")
    st.caption("网站不会帮你永久保存资料：用完记得按「下载」存成 CSV，下次再上传。手机 App 的投资组合按「🩺 AI 组合体检」会自动带过来。")

    link = st.query_params.get("pf")
    if link and st.session_state.get("pf_link") != link:          # 从手机 App 带来的持股
        rows = PC.parse_link(link)
        if rows:
            st.session_state.pf = pd.DataFrame(rows)
            st.session_state.pf_link = link
            st.session_state.pf_editor_v = st.session_state.get("pf_editor_v", 0) + 1
    if "pf" not in st.session_state:
        st.session_state.pf = pd.DataFrame(
            {"代码": ["1155.KL"], "数量": [1000.0], "平均成本": [9.80]})

    up = st.file_uploader("上传之前下载的 CSV（栏位：代码、数量、平均成本；英文 ticker / qty / cost 也可以）", type="csv")
    if up is not None and st.session_state.get("pf_loaded") != up.name:
        try:
            st.session_state.pf = PC.normalize(pd.read_csv(up, encoding="utf-8-sig"))
            st.session_state.pf_loaded = up.name
            st.session_state.pf_editor_v = st.session_state.get("pf_editor_v", 0) + 1
        except Exception as e:
            st.error(f"❌ 读不懂这个 CSV：{e}")
            st.session_state.pf_loaded = up.name
    try:                                   # 表格万一栏名不对（旧资料、奇怪的 CSV）：修正，修不了就重来
        st.session_state.pf = PC.normalize(st.session_state.pf)
    except Exception:
        st.warning("投资组合表格的栏位不对，已经重设。请重新输入或上传。")
        st.session_state.pf = pd.DataFrame({"代码": ["1155.KL"], "数量": [1000.0], "平均成本": [9.80]})
        st.session_state.pf_editor_v = st.session_state.get("pf_editor_v", 0) + 1

    pf = st.data_editor(st.session_state.pf, num_rows="dynamic", width="stretch",
                        key=f"pf_editor_{st.session_state.get('pf_editor_v', 0)}",
                        column_config={"数量": st.column_config.NumberColumn(min_value=0),
                                       "平均成本": st.column_config.NumberColumn(format="%.4f")})
    st.session_state.pf = pf
    try:
        clean = PC.normalize(pf).dropna()
    except Exception:
        clean = pd.DataFrame(columns=["代码", "数量", "平均成本"])
    holdings = [{"代码": str(r["代码"]), "数量": float(r["数量"]), "平均成本": float(r["平均成本"])}
                for _, r in clean.iterrows() if str(r["代码"]).strip() not in ("", "nan") and float(r["数量"]) > 0]

    st.download_button("⬇️ 下载 CSV", pf.to_csv(index=False).encode("utf-8-sig"),
                       "my_portfolio.csv", "text/csv")

    # ---------------- AI 组合体检 ----------------
    with st.container(border=True):
        st.markdown("### 🩺 AI 组合体检")
        st.caption("程序先算比重、板块 / 市场 / 货币分布、股息率、过去 1 年波动和最大回撤、股票之间的相关性，"
                   "再请 AI 对照你的目标写体检报告。持股不会被保存，但会传给 AI 服务商做这次分析。")
        c1, c2, c3 = st.columns(3)
        goal = c1.selectbox("投资目标", PC.GOALS, key="pf_goal")
        horizon = c2.selectbox("打算持有多久", PC.HORIZONS, index=2, key="pf_hz")
        dd = c3.selectbox("能接受的下跌", PC.DRAWDOWNS, index=1, key="pf_dd")
        go_ = st.button("🩺 开始体检", type="primary", width="stretch", disabled=not holdings)
    if go_:
        st.session_state.pf_run = json.dumps(holdings, sort_keys=True)
    if st.session_state.get("pf_run") and st.session_state.pf_run == json.dumps(holdings, sort_keys=True):
        show_pf_check(holdings, goal, horizon, dd)


def show_pf_check(holdings, goal, horizon, dd):
    import pfcheck as PC
    bar = st.progress(0.0, text="正在收集每只股票的股价、财务、季报和新闻…")
    done = {"n": 0}

    def get_raw(t):
        r = cached_analysis(t)
        done["n"] += 1
        bar.progress(done["n"] / len(holdings), text=f"已收集 {done['n']}/{len(holdings)}：{r['fund']['name']}")
        return r

    p = PC.build(holdings, get_raw)
    bar.empty()
    for e in p["errors"]:
        st.warning(f"找不到：{e}")
    if not p["rows"]:
        return
    rows, risk = p["rows"], p["risk"]

    # --- 数字 ---
    pl_pct = (p["total_myr"] / p["cost_myr"] - 1) * 100 if p["cost_myr"] else 0
    c = st.columns([1.6, 1, 1, 1, 1])
    c[0].metric("总市值（折算令吉）", f"RM {p['total_myr']:,.0f}", f"{p['pl_myr']:+,.0f}（{pl_pct:+.1f}%）")
    c[1].metric("加权股息率", fmt(p["div_yield"], 2, "%"))
    c[2].metric("最大一只占", f"{p['top_weight']:.0f}%", help="一般建议单一股票不超过 15–20%")
    c[3].metric("过去 1 年波动", fmt(risk.get("vol"), 1, "%"), help="年化波动率：数字越大，涨跌越剧烈")
    c[4].metric("过去 1 年最大回撤", fmt(risk.get("max_dd"), 1, "%"), help="按现在的比重回看，从最高点最多跌了多少")
    if p["fx_approx"]:
        st.caption("⚠️ 汇率暂时取不到，用约值折算令吉。")
    else:
        st.caption("汇率：" + "　".join(f"1 {k} = RM {v:.4g}" for k, v in p["fx"].items() if k != "MYR"))

    # --- 分布 ---
    pie = lambda d, title: go.Figure(go.Pie(labels=list(d), values=list(d.values()), hole=.55, sort=False,
                                            textinfo="label+percent")).update_layout(
        title=title, height=290, margin=dict(l=10, r=10, t=40, b=10), showlegend=False)
    a, b, cc = st.columns(3)
    a.plotly_chart(pie({x["name"]: x["weight"] for x in rows}, "个股比重"), width="stretch")
    b.plotly_chart(pie(p["by_sector"], "板块"), width="stretch")
    cc.plotly_chart(pie(p["by_market"], "市场"), width="stretch")

    # --- 规则检查 ---
    if p["flags"]:
        with st.container(border=True):
            st.markdown("#### 🔎 规则检查发现")
            for f in p["flags"]:
                st.markdown(md(f))

    # --- 每只股票 ---
    df = pd.DataFrame([{"股票": x["name"], "代码": x["ticker"], "比重%": x["weight"], "盈亏%": x["pl_pct"],
                        "1年%": x["chg_1y"], "本益比": x["pe"], "股息率%": x["div_yield"], "技术面": x["tech"],
                        "最新季报": x["quarter"] or "—", "板块": x["sector"]} for x in rows])
    st.dataframe(df, hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="%.1f") for k in ("比重%", "盈亏%", "1年%", "本益比")}
                 | {"股息率%": st.column_config.NumberColumn(format="%.2f")})

    if risk.get("curve") is not None:
        l, r_ = st.columns([3, 2])
        cv = risk["curve"] * 100
        l.plotly_chart(go.Figure(go.Scatter(x=cv.index, y=cv, mode="lines", line=dict(color="#C8A23A", width=2)))
                       .update_layout(title="按现在比重回看过去 1 年（起点 = 100）", height=300,
                                      margin=dict(l=10, r=10, t=40, b=10)), width="stretch")
        if risk.get("corr") is not None and len(rows) > 1:
            r_.plotly_chart(go.Figure(go.Heatmap(z=risk["corr"].values, x=list(risk["corr"].columns),
                                                 y=list(risk["corr"].index), zmin=-1, zmax=1, colorscale="RdBu_r",
                                                 text=risk["corr"].round(2).values, texttemplate="%{text}"))
                            .update_layout(title="相关性（越接近 1 越常一起涨跌）", height=300,
                                           margin=dict(l=10, r=10, t=40, b=10)), width="stretch")

    # --- AI 报告 ---
    err = M.check_setup()
    if err:
        st.warning(err)
        return
    import hashlib
    key = hashlib.sha1((json.dumps(holdings, sort_keys=True) + goal + horizon + dd + str(date.today())).encode()).hexdigest()
    with st.spinner("AI 分析员正在写体检报告…（约 20-40 秒）"):
        try:
            text = cached_pf_ai(key, p, goal, horizon, dd, M.LANG)
        except Exception as e:
            st.error(f"AI 暂时无法分析：{e}")
            return
    with st.container(border=True):
        st.markdown("### 🩺 AI 体检报告")
        st.markdown(f"<div style='line-height:1.8'>{sections_html(text)}</div>", unsafe_allow_html=True)
    st.caption("AI 根据上面的数字、最新季报和近期新闻分析；不是持牌投资建议，最后由你自己决定。")


# ---------------------------------------------------------------------------
# 页面：每日焦点（GitHub Actions 定时生成的开市 / 午间 / 收市报告）
# ---------------------------------------------------------------------------

def list_reports(market: str) -> list[str]:
    folder = S.REPORT_DIR / market
    order = {"open": 0, "midday": 1, "close": 2}
    stems = [f.stem for f in folder.glob("*.json")] if folder.exists() else []
    return sorted(stems, key=lambda s: (s[:10], order.get(s[11:], 0)), reverse=True)


def load_report(market: str, stem: str) -> dict:
    return json.loads((S.REPORT_DIR / market / f"{stem}.json").read_text(encoding="utf-8"))


@st.cache_data(ttl=600, show_spinner=False)
def live_scan(market: str, session: str):
    return S.scan(market, session, with_ai=True)


def show_report(r: dict, prefix: str = "saved"):
    kp = f"{prefix}_{r['market']}_{r['date']}_{r['session']}"
    cur, b = r["currency"], r["breadth"]
    st.markdown(f"#### {r['market_name']}｜{r['session_name']}")
    note = "" if r["partial_day"] >= 1 else f"（盘中数据，交易时间已过约 {r['partial_day']:.0%}）"
    st.caption(f"生成时间：{r['generated_at']}{note}　·　扫描 {b['scanned']} 只大中型股，"
               f"已剔除 {len(b['filtered_out'])} 只低价或成交太少的股票")

    c = st.columns(4)
    c[0].metric("上涨", b["up"])
    c[1].metric("下跌", b["down"])
    c[2].metric("平均涨跌", f"{b['avg_change']:+.2f}%")
    mood = "偏强 🟢" if b["up"] > b["down"] * 1.5 else "偏弱 🔴" if b["down"] > b["up"] * 1.5 else "分歧 ⚪"
    c[3].metric("市场气氛", mood)

    if r.get("ai_comment"):
        with st.container(border=True):
            st.markdown("**🧠 AI 市场点评**")
            st.write(r["ai_comment"])

    st.markdown("##### 🔥 最值得关注的 5 只股票")
    for start in range(0, len(r["watchlist"]), 3):
        cols = st.columns(3)
        for col, w in zip(cols, r["watchlist"][start:start + 3]):
            with col.container(border=True):
                color = "#16a34a" if w["change_pct"] >= 0 else "#dc2626"
                tags = "".join(
                    f"<span style='background:rgba(148,163,184,.18);padding:1px 8px;border-radius:999px;"
                    f"margin:2px 4px 2px 0;display:inline-block;font-size:.8rem'>{t}</span>"
                    for t in (w["tags"] or ["波动较大"]))
                st.markdown(
                    f"<div style='font-weight:700;font-size:1.1rem'>{w['name']}</div>"
                    f"<div style='opacity:.6;font-size:.8rem'>{w['ticker']}</div>"
                    f"<div style='margin:6px 0'><span style='font-size:1.3rem;font-weight:600'>"
                    f"{cur} {w['price']:,.2f}</span> <span style='color:{color};font-weight:600'>"
                    f"{w['change_pct']:+.2f}%</span></div>"
                    f"<div style='font-size:.85rem;opacity:.8'>成交量 {w['vol_ratio']:.1f} 倍 · "
                    f"波幅 {w['range_pct']:.1f}% · RSI {w['rsi']:.0f}</div>"
                    f"<div style='margin-top:6px'>{tags}</div>", unsafe_allow_html=True)
                stock_button(w["ticker"], f"{kp}_go_{w['ticker']}", "📈 走势 · 资料 · AI 分析 →")

    def table(rows, title):
        df = pd.DataFrame(rows)[["name", "ticker", "price", "change_pct", "vol_ratio", "turnover"]]
        df.columns = ["名称", "代码", "股价", "涨跌%", "成交量倍数", f"成交额 ({cur})"]
        st.markdown(f"**{title}**")
        key = f"{kp}_tbl_{title}"

        def on_pick():  # 点表格任何一格 → 跳到那只股票的页面
            i = picked_row(key)
            if i is not None:
                goto_analysis(rows[i]["ticker"])

        st.dataframe(df.style.format({"股价": "{:,.2f}", "涨跌%": "{:+.2f}", "成交量倍数": "{:.1f}",
                                      f"成交额 ({cur})": "{:,.0f}"}).map(
            lambda v: f"color:{'#16a34a' if v > 0 else '#dc2626'}", subset=["涨跌%"]),
            hide_index=True, width="stretch", key=key,
            on_select=on_pick, selection_mode=["single-row", "single-cell"])

    st.caption("👆 点表格里任何一只股票，就会打开它的页面（走势、资料、AI 分析、新闻）")
    c1, c2 = st.columns(2)
    with c1:
        table(r["gainers"], "📈 涨幅最大")
        table(r["volume_surge"], "🔊 成交量异常放大")
    with c2:
        table(r["losers"], "📉 跌幅最大")
        table(r["turnover_top"], "💵 成交额最高")


def page_focus():
    st.title("📅 每日焦点")
    st.caption("每个交易日的开市、午间、收市都会自动生成报告，只看约 500 只大中型股，剔除低价和成交冷清的投机股。")
    tabs = st.tabs([m.name for m in S.MARKETS.values()])
    for tab, (key, m) in zip(tabs, S.MARKETS.items()):
        with tab:
            stems = list_reports(key)
            if stems:
                label = lambda s: f"{s[:10]}　{S.session_label(key, s[11:])}"
                stem = st.selectbox("选择报告", stems, format_func=label, key=f"sel_{key}")
                show_report(load_report(key, stem))
            else:
                st.info("还没有自动生成的报告。设置好 GitHub Actions 后，交易日会自动出现（见 README）。")

            with st.expander("⚡ 现在立即扫描一次（不保存）"):
                sess = st.radio("时段", list(S.SESSION_ZH), horizontal=True, key=f"sess_{key}",
                                format_func=lambda s: S.session_label(key, s))
                if st.button("开始扫描", key=f"scan_{key}", type="primary"):
                    with st.spinner("正在扫描约 500 只股票…（约 1-2 分钟）"):
                        r = live_scan(key, sess)
                    if r is None:
                        st.warning("今天看起来没有开市（周末、假期，或还没开盘）。")
                    else:
                        show_report(r, prefix="live")


# ---------------------------------------------------------------------------
# 页面：认识公司
# ---------------------------------------------------------------------------

@st.cache_data(ttl=7 * 86400, show_spinner=False)
def cached_company(text: str) -> dict:
    return C.fetch(text)


async def _company_ai(p: dict, report: str | None):
    M.reset_clients()
    return await C.ai_profile(p, report)


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def cached_company_ai(ticker: str, report_key: str, _p: dict, _report: str | None = None, lang: str = "中文"):
    # 出错会 raise → 不会被缓存，下次可以重试。report_key：有上传年报时是文件指纹（换年报就重写）
    return asyncio.run(_company_ai(_p, _report))


@st.cache_data(ttl=30 * 86400, show_spinner=False)
def cached_report_excerpt(digest: str, _data: bytes) -> str:
    return C.report_excerpt(_data)


def md(text: str) -> str:
    """AI 文字安全显示：$ 会被 Streamlit 当成数学公式，要转义。"""
    return (text or "").replace("$", "\\$").replace("\n", "  \n")


def md_list(text: str) -> str:
    """把 "1. xx 2. yy" 拆成每点一行。"""
    import re
    t = re.sub(r"\s*(?<![\d.%A-Za-z])([1-9])[.、]\s*(?!\d)", r"\n\1. ", text or "").strip()
    return md(t)


def level_badge(level: str | None, size: str = ".95rem") -> str:
    color = C.LEVEL_COLOR.get(level, "#94a3b8")
    return (f"<span style='background:{color};color:white;padding:3px 14px;border-radius:999px;"
            f"font-weight:700;font-size:{size}'>{level or '无'}</span>")


def level_scale(level: str | None) -> str:
    """弱 → 强 五格刻度，亮起其中一格。"""
    cells = "".join(
        f"<div style='flex:1;text-align:center;padding:8px 0;border-radius:8px;font-size:.95rem;"
        f"background:{C.LEVEL_COLOR[lv] if lv == level else 'rgba(148,163,184,.15)'};"
        f"color:{'white' if lv == level else 'inherit'};font-weight:{800 if lv == level else 400}'>{lv}</div>"
        for lv in C.LEVELS)
    return f"<div style='display:flex;gap:5px'>{cells}</div>"


def fin_chart(p: dict):
    fin, cur = p["fin"], p["currency"]
    x = [str(y) for y in fin.index]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    if "营收" in fin:
        fig.add_trace(go.Bar(x=x, y=fin["营收"], name="营收", marker_color="#93c5fd"), secondary_y=False)
    if "净利润" in fin:
        fig.add_trace(go.Bar(x=x, y=fin["净利润"], name="净利润", marker_color="#2563eb"), secondary_y=False)
    if "净利率%" in fin:
        fig.add_trace(go.Scatter(x=x, y=fin["净利率%"], name="净利率 %", mode="lines+markers",
                                 line=dict(color="#f59e0b", width=2.5)), secondary_y=True)
    fig.update_layout(height=340, barmode="group", margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", y=1.12))
    fig.update_yaxes(title_text=cur, secondary_y=False)
    if "净利率%" in fin and fin["净利率%"].notna().any():
        hi, lo = fin["净利率%"].max(), fin["净利率%"].min()
        rng = [min(0, lo * 1.3), max(hi * 1.3, 1)]  # 从 0 开始，避免小变化看起来很夸张
        fig.update_yaxes(range=rng, secondary_y=True)
    fig.update_yaxes(title_text="%", secondary_y=True, showgrid=False)
    return fig


def fin_table(p: dict) -> pd.DataFrame:
    fin = p["fin"]
    out = {}
    for k in fin.columns:
        out[k] = [f"{v:.1f}%" if k.endswith("%") else (f"{v:.2f}" if k == "每股盈利" else C.big(v))
                  if pd.notna(v) else "—" for v in fin[k]]
    return pd.DataFrame(out, index=[str(y) for y in fin.index]).T


def show_company(p: dict):
    import hashlib
    rk = f"annual_{p['ticker']}"
    with st.expander("📄 上传年报 / 季报 PDF（可选：AI 会读公司自己写的业务分部、产品、展望，分析更仔细）",
                     expanded=False):
        up = st.file_uploader("年报或季报 PDF（Bursa、公司官网下载的都可以）", type=["pdf"], key=f"up_{p['ticker']}")
        if up is not None:
            data = up.getvalue()
            dg = hashlib.sha1(data).hexdigest()[:16]
            with st.spinner("正在找年报里讲业务、分部、展望的页…"):
                try:
                    st.session_state[rk] = (dg, cached_report_excerpt(dg, data), up.name)
                except Exception as e:
                    st.error(f"读不到这个 PDF：{e}")
        if st.session_state.get(rk):
            dg, ex, nm = st.session_state[rk]
            st.success(f"已读取「{nm}」：挑出 {len(ex):,} 字讲业务的内容。下面的分析已经根据它重写。" if ex
                       else f"「{nm}」里找不到讲业务的文字（可能是扫描图片版的 PDF）。")
            if st.button("不用这份年报", key=f"rm_{p['ticker']}"):
                st.session_state.pop(rk, None)
                st.rerun()
    dg, report = (st.session_state[rk][0], st.session_state[rk][1] or None) if st.session_state.get(rk) else ("", None)

    ai, ai_err = None, None
    if M.check_setup():
        ai_err = "还没设置 AI key，下面只显示财务体检（数字评分）。"
    else:
        with st.spinner("AI 分析员正在仔细阅读资料、分两段写业务报告…（第一次约 40-90 秒，之后 7 天内都很快）"):
            try:
                ai = cached_company_ai(p["ticker"], dg, p, report, M.LANG)
            except Exception as e:
                ai_err = f"AI 研究员暂时无法工作：{e}"
    sec = ai["sections"] if ai else {}
    lv = ai["levels"] if ai else {}
    sc = p["scores"]

    # --- 标题 ---
    facts = [x for x in (p["sector"], p["industry"], p["country"]) if x]
    if p["employees"]:
        facts.append(f"员工 {p['employees']:,} 人")
    if p["market_cap"]:
        facts.append(f"市值 {p['currency']} {C.big(p['market_cap'])}")
    st.caption(" · ".join(facts))
    if ai_err:
        st.warning(ai_err)

    # --- 评级 ---
    with st.container(border=True):
        overall = lv.get("综合评级") or sc["level"]
        c = st.columns([2.2, 1, 1, 1])
        c[0].markdown(f"**⭐ 综合评级**{'' if lv.get('综合评级') else '（财务体检）'}")
        c[0].markdown(level_scale(overall), unsafe_allow_html=True)
        for col, (label, val) in zip(c[1:], [("🏭 业务实力", lv.get("业务实力评级")),
                                             ("👔 管理层", lv.get("管理层评级")),
                                             ("🩺 财务体检", sc["level"])]):
            col.markdown(f"**{label}**")
            col.markdown(level_badge(val), unsafe_allow_html=True)
        if sec.get("综合评级"):
            st.markdown(md(sec["综合评级"]))
        if sec.get("一句话认识"):
            st.info("💡 " + sec["一句话认识"].replace("$", "\\$"))

    # --- 业务详解（像投行报告的业务部分）---
    if sec:
        with st.container(border=True):
            st.markdown("#### 🏭 业务详解" + ("　<span style='font-size:.8rem;opacity:.7'>（已参考你上传的年报）</span>"
                                             if ai.get("with_report") else ""), unsafe_allow_html=True)
            names = [("🏭 主要业务", "主要业务"), ("🧩 业务分部", "业务分部"), ("💰 营业模式", "营业模式"),
                     ("🏁 行业与竞争", "行业与竞争"), ("🚀 增长动力", "增长动力"), ("🎯 关键指标", "关键指标")]
            tabs = st.tabs([n for n, k in names])
            for tab, (n, k) in zip(tabs, names):
                with tab:
                    txt = sec.get(k)
                    st.markdown(md_list(txt) if txt else "—（AI 这次没有写这一部分，可以稍后重新整理页面再试）")
                    if k == "行业与竞争" and p.get("peers"):
                        st.caption("同一板块的同行（板块报告数据）")
                        st.dataframe(pd.DataFrame(p["peers"]), hide_index=True, width="stretch")
                    if k == "营业模式" and not p["fin"].empty:
                        cols = [c for c in ("毛利率%", "营业利润率%", "净利率%", "ROE%") if c in p["fin"]]
                        if cols:
                            m = p["fin"][cols].dropna(how="all")
                            m.index = [str(y) for y in m.index]
                            st.caption("利润率走势（%）")
                            st.line_chart(m, height=220)

    # --- 近几年成绩 ---
    with st.container(border=True):
        st.markdown("#### 📈 近几年成绩")
        if p["fin"].empty:
            st.write("Yahoo 上没有这家公司的年度财报数据。")
        else:
            c1, c2 = st.columns([3, 2])
            c1.plotly_chart(fin_chart(p), width="stretch")
            with c2:
                if sec.get("近几年成绩"):
                    st.markdown(md(sec["近几年成绩"]))
            st.dataframe(fin_table(p), width="stretch")
            if p["dividends"]:
                st.caption("每股股息：" + "　".join(f"{y}：{v:g}" for y, v in sorted(p["dividends"].items())))

    # --- 财务体检 ---
    with st.container(border=True):
        st.markdown(f"#### 🩺 财务体检　{level_badge(sc['level'])}", unsafe_allow_html=True)
        st.caption("根据财报数字用固定规则计算，每项 1-5 分（弱 → 强），透明可查。")
        rows = "".join(
            f"<tr><td style='padding:6px 10px;font-weight:600;white-space:nowrap'>{it['name']}</td>"
            f"<td style='padding:6px 10px'>{level_badge(it['level'], '.8rem')}</td>"
            f"<td style='padding:6px 10px;opacity:.85'>{it['reason']}</td></tr>" for it in sc["items"])
        st.markdown(f"<table style='width:100%;border-collapse:collapse'>{rows}</table>",
                    unsafe_allow_html=True)

    # --- 管理层 ---
    with st.container(border=True):
        st.markdown("#### 👔 管理层")
        if sec.get("管理层"):
            st.markdown(md(sec["管理层"]))
        m = st.columns(3)
        m[0].metric("内部人持股", f"{p['insider_pct'] * 100:.1f}%" if p["insider_pct"] else "无数据")
        m[1].metric("机构持股", f"{p['institution_pct'] * 100:.1f}%" if p["institution_pct"] else "无数据")
        m[2].metric("治理风险分（1好-10差）", p["governance_risk"] or "无数据")
        if p["officers"]:
            st.dataframe(pd.DataFrame(p["officers"]), hide_index=True, width="stretch")

    # --- 优势 / 风险 ---
    if sec.get("优势") or sec.get("风险"):
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            st.markdown("#### ✅ 优势")
            st.markdown(md_list(sec.get("优势", "—")))
        with c2.container(border=True):
            st.markdown("#### ⚠️ 风险")
            st.markdown(md_list(sec.get("风险", "—")))

    if p["summary"]:
        with st.expander("📄 公司官方简介（英文原文）"):
            st.write(p["summary"])
            if p["website"]:
                st.markdown(f"官网：{p['website']}")

    st.caption(f"财报数据来自 Yahoo Finance（年度）；AI 供应商：{M.PROVIDER} · {M.MODEL}。"
               "AI 对公司和管理层的描述来自它的训练知识，可能不是最新，重要决定请查公司年报。"
               "结果保存 7 天。仅供学习参考，不构成投资建议。")


# ---------------------------------------------------------------------------
# 页面：选股雷达（错杀股 / 成长股 / 双杀股）
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def live_screen(market: str):
    return SC.screen(market, with_ai=True)


def dated_files(folder) -> list[str]:
    return sorted((f.stem for f in folder.glob("*.json")), reverse=True) if folder.exists() else []


def chip(text: str) -> str:
    return (f"<span style='background:rgba(148,163,184,.18);padding:1px 8px;border-radius:999px;"
            f"margin:2px 4px 2px 0;display:inline-block;font-size:.8rem'>{text}</span>")


def fnum(v, nd=0, suffix="%", sign=True):
    if v is None:
        return "—"
    return f"{v:+.{nd}f}{suffix}" if sign else f"{v:.{nd}f}{suffix}"


def radar_card(x: dict, kp: str, accent: str):
    with st.container(border=True):
        r1 = x.get("ret_1m")
        color = "#16a34a" if (r1 or 0) >= 0 else "#dc2626"
        st.markdown(
            f"<div style='border-left:4px solid {accent};padding-left:10px'>"
            f"<div style='font-weight:700;font-size:1.05rem'>{x['name']}</div>"
            f"<div style='opacity:.6;font-size:.8rem'>{x['ticker']}{' · ' + x['sector'] if x.get('sector') else ''}</div>"
            f"<div style='margin:4px 0'><b>{x['currency']} {x['price']:,.2f}</b> "
            f"<span style='color:{color}'>1 个月 {fnum(r1, 1)}</span></div></div>"
            f"<div style='font-size:.82rem;opacity:.85;margin:4px 0'>营收 {fnum(x.get('rev_growth'))} · "
            f"盈利 {fnum(x.get('eps_growth'))} · ROE {fnum(x.get('roe'), sign=False)} · "
            f"P/E {fnum(x.get('pe'), 1, '', False)}"
            f"{' (历史 ' + fnum(x.get('pe_avg'), 1, '', False) + ')' if x.get('pe_avg') else ''}</div>"
            f"<div>{''.join(chip(t) for t in x['reasons'])}</div>", unsafe_allow_html=True)
        stock_button(x["ticker"], f"{kp}_an_{x['ticker']}", "📈 走势 · 资料 · AI 分析 →")


def show_screen(r: dict, prefix: str):
    st.caption(f"生成时间：{r['generated_at']}　·　扫描 {r['scanned']} 只大型股（已剔除低价和成交冷清的股票）")
    c = st.columns(3)
    for col, (cat, (title, _)) in zip(c, SC.CATEGORIES.items()):
        col.metric(title, f"{r['counts'][cat]} 只")
    if r.get("ai_comment"):
        with st.container(border=True):
            st.markdown("**🧠 AI 基金经理点评**")
            st.write(r["ai_comment"])
    accents = {"oversold": "#2563eb", "growth": "#16a34a", "double_kill": "#dc2626"}
    for cat, (title, desc) in SC.CATEGORIES.items():
        st.markdown(f"#### {title}")
        st.caption(desc)
        items = r[cat]
        if not items:
            st.write("今天没有符合条件的股票。")
            continue
        for start in range(0, min(len(items), 6), 3):
            cols = st.columns(3)
            for col, x in zip(cols, items[start:start + 3]):
                with col:
                    radar_card(x, f"{prefix}_{r['market']}_{cat}", accents[cat])
        if len(items) > 6:
            with st.expander(f"再看 {len(items) - 6} 只"):
                df = pd.DataFrame(items[6:])[["name", "ticker", "price", "ret_3m", "eps_growth", "roe", "pe"]]
                df.columns = ["名称", "代码", "股价", "3个月%", "盈利增长%", "ROE%", "P/E"]
                st.dataframe(df.round(1), hide_index=True, width="stretch")


def page_radar():
    st.title("🔍 选股雷达")
    st.caption("每个交易日收市后，用固定规则从大型股中找出 错杀股、成长股、双杀股。这是研究的起点，不是买卖建议。")
    with st.expander("📐 三种类型是怎么判断的？"):
        R = SC.RULES
        st.markdown(f"""
**🎯 错杀股**：股价被打得很惨，但公司本身没变差
- 距 52 周高点跌 ≥ {abs(R['oversold']['drawdown'])}%，或 3 个月跌 ≥ {abs(R['oversold']['ret_3m'])}%
- 盈利增长 ≥ {R['oversold']['eps_growth_min']}%（没有恶化）、ROE ≥ {R['oversold']['roe_min']}%
- 本益比比自己过去几年平均便宜 ≥ {abs(R['oversold']['pe_discount'])}%（有历史数据时）

**🚀 成长股**：营收增长 ≥ {R['growth']['rev_growth']}%、盈利增长 ≥ {R['growth']['eps_growth']}%、ROE ≥ {R['growth']['roe_min']}%；
股价在 200 日均线之上更好（之下会标「回调中」）

**⚠️ 双杀股（戴维斯双杀）**：盈利下滑 + 市场给的估值也下降，股价受双重打击
- 盈利增长 ≤ {R['double_kill']['eps_growth_max']}%、6 个月股价跌 ≥ {abs(R['double_kill']['ret_6m'])}%
- 本益比比历史平均低，或股价跌幅大于盈利跌幅（估值被压缩）

规则写在 `screener.py` 的 `RULES`，可以自己调整。""")
    tabs = st.tabs([m.name for m in S.MARKETS.values()])
    for tab, key in zip(tabs, S.MARKETS):
        with tab:
            files = dated_files(SC.REPORT_DIR / key)
            if files:
                d = st.selectbox("日期", files, key=f"radar_sel_{key}")
                show_screen(json.loads((SC.REPORT_DIR / key / f"{d}.json").read_text(encoding="utf-8")), "saved")
            else:
                st.info("还没有自动生成的报告。设置好 GitHub Actions 后，每个交易日收市后会自动出现。")
            with st.expander("⚡ 现在立即扫描（约 1-3 分钟，不保存）"):
                if st.button("开始扫描", key=f"radar_live_{key}", type="primary"):
                    with st.spinner("正在抓取股价和财报数据…"):
                        r = live_screen(key)
                    show_screen(r, "live")


# ---------------------------------------------------------------------------
# 页面：KLCI 50 观察
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def live_klci():
    r = K.track()
    r["ai_comment"] = K.ai_comment(r)
    return r


def prob_bar(p: int) -> str:
    color = "#15803d" if p >= 80 else "#22c55e" if p >= 50 else "#eab308" if p >= 20 else "#94a3b8"
    return (f"<div style='display:flex;align-items:center;gap:8px'>"
            f"<div style='flex:1;background:rgba(148,163,184,.18);border-radius:999px;height:10px'>"
            f"<div style='width:{p}%;background:{color};height:10px;border-radius:999px'></div></div>"
            f"<b style='width:40px;text-align:right'>{p}%</b></div>")


def klci_history(files: list[str], top: list[str]) -> pd.DataFrame:
    rows = []
    for f in sorted(files)[-30:]:
        r = json.loads((K.REPORT_DIR / f"{f}.json").read_text(encoding="utf-8"))
        for c in r["top_candidates"]:
            if c["ticker"] in top:
                rows.append({"日期": r["date"], "公司": c["name"], "几率": c["prob"]})
    return pd.DataFrame(rows)


def show_klci(r: dict, files: list[str]):
    rv = r.get("review") or {}
    st.caption(f"更新时间：{r['generated_at']}　·　扫描 {r['universe_size']} 只大型股，{r['eligible_count']} 只通过资格估算")
    if rv:
        c = st.columns(4)
        left = rv["days_to_cutoff"]
        c[0].metric("下一次检讨", rv["review"].replace(" 检讨", "").replace(" ", ""))
        c[1].metric("数据截止日", rv["cutoff"], f"还有 {left} 天" if left >= 0 else "已截止，等待公布",
                    delta_color="off")
        c[2].metric("公布日", rv["announce"])
        c[3].metric("生效日", rv["effective"])
    st.info("📌 " + r["mode"] + f"。门槛市值约 RM {r['cutoff_mcap'] / 1e9:.1f}B（低于这个市值就排不进名额）。")
    if r.get("ai_comment"):
        with st.container(border=True):
            st.markdown("**🧠 AI 分析师点评**")
            st.write(r["ai_comment"])

    st.markdown(f"#### 🏅 最有机会入选的公司（{r['slots']} 个名额）")
    head = ("<tr style='opacity:.6;font-size:.8rem'><td>候选排名</td><td>公司</td><td>全市值</td>"
            "<td>距门槛</td><td style='width:32%'>入选几率</td><td>状态</td></tr>")
    body = ""
    for c in r["top_candidates"][:25]:
        gap = c["gap_pct"]
        gap_txt = f"<span style='color:#16a34a'>高出 {abs(gap):.0f}%</span>" if gap <= 0 \
            else f"<span style='color:#dc2626'>还差 {gap:.0f}%</span>"
        ref = " 📋" if c.get("in_reference") else ""
        warn = "" if c["eligible"] else " <span title='资格估算未达标' style='color:#f97316'>⚠️</span>"
        line = "border-top:2px dashed #94a3b8" if c.get("cand_rank") == r["slots"] + 1 else ""
        body += (f"<tr style='{line}'><td style='padding:6px'><b>{c.get('cand_rank') or '—'}</b></td>"
                 f"<td style='padding:6px'><b>{c['name']}</b>{ref}{warn}<br><span style='opacity:.6;font-size:.8rem'>{c['ticker']}</span></td>"
                 f"<td style='padding:6px'>RM {c['mcap'] / 1e9:.1f}B</td><td style='padding:6px'>{gap_txt}</td>"
                 f"<td style='padding:6px'>{prob_bar(c['prob'])}</td><td style='padding:6px;font-size:.85rem'>{c['status']}</td></tr>")
    st.markdown(f"<table style='width:100%;border-collapse:collapse'>{head}{body}</table>", unsafe_allow_html=True)
    st.caption("虚线 = 名额分界线。📋 = 出现在官方模拟或分析师名单。⚠️ = 自由流通量或流动性估算未达标。")

    pick = st.selectbox("选一家公司认识一下", [f"{c['name']}（{c['ticker']}）" for c in r["top_candidates"][:25]],
                        index=None, placeholder="选择公司…", key="klci_pick")
    if pick:
        t = pick.split("（")[-1].rstrip("）")
        stock_button(t, "klci_an")

    if len(files) >= 2:
        st.markdown("#### 📈 几率变化（最近 30 天）")
        top = [c["ticker"] for c in r["top_candidates"][max(0, r["slots"] - 5):r["slots"] + 5]]
        h = klci_history(files, top)
        if not h.empty:
            fig = go.Figure()
            for name, g in h.groupby("公司"):
                fig.add_trace(go.Scatter(x=g["日期"], y=g["几率"], name=name, mode="lines+markers"))
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), yaxis=dict(range=[0, 100], title="%"))
            st.plotly_chart(fig, width="stretch")
            st.caption("只显示名额分界线附近的 10 家公司，最有看头。")

    if r["at_risk"]:
        st.markdown("#### ⚠️ 现有成分股：资格或排名有风险")
        st.dataframe(pd.DataFrame(r["at_risk"])[["name", "ticker", "rank", "free_float", "liq_months", "prob"]]
                     .rename(columns={"name": "公司", "ticker": "代码", "rank": "排名", "free_float": "自由流通%",
                                      "liq_months": "流动性达标月数", "prob": "保留几率%"}),
                     hide_index=True, width="stretch")

    with st.expander("📊 完整全市值排名（前 80）"):
        df = pd.DataFrame(r["ranking"])
        df["市值(RM B)"] = (df["mcap"] / 1e9).round(1)
        df = df[["rank_all", "name", "ticker", "市值(RM B)", "status", "free_float", "liq_months", "prob"]]
        df.columns = ["排名", "公司", "代码", "市值(RM B)", "状态", "自由流通%", "流动性达标月数", "几率%"]
        st.dataframe(df, hide_index=True, width="stretch", height=500)

    with st.expander("📖 规则、参考名单和资料来源"):
        st.markdown("""
- **选股标准**：按**全市值**排名（不是自由流通市值）。
- **资格筛选**：自由流通量必须高于 15%；非成分股过去 12 个月中至少 10 个月的每日成交量中位数 ≥ 可投资股数的 0.050%（现有成分股 8 个月、0.040%）。
- **2026 年 12 月扩容**：30 只现有成分股保留，新增 20 只；新成分股 12 月先以 50% 权重加入，2027 年 6 月升到 100%。
- **估算误差**：Yahoo 的自由流通股数和成交量不一定准确，名单也只涵盖约 120 只大型股。几率是根据离门槛多远、离截止日多近算出来的模型估计。""")
        for k, v in r["reference"].items():
            names = [K.UNIVERSE.get(t, t) for t in v]
            st.markdown(f"**{k}**：" + "、".join(names))
        st.markdown("**资料来源**：" + "　".join(f"[{t}]({u})" for t, u in r["sources"]))


def page_klci():
    st.title("🏆 KLCI 50 观察")
    st.caption("FBM KLCI 将从 30 只扩大到 50 只成分股。每天估算哪些公司最有机会入选。按公开规则模拟，非官方结果。")
    files = dated_files(K.REPORT_DIR)
    r = None
    if files:
        d = st.selectbox("日期", files, key="klci_sel")
        r = json.loads((K.REPORT_DIR / f"{d}.json").read_text(encoding="utf-8"))
    else:
        st.info("还没有自动生成的报告。设置好 GitHub Actions 后，每个交易日马股收市后会自动更新。")
    with st.expander("⚡ 现在立即计算（约 1-2 分钟）", expanded=not files):
        if st.button("开始计算", key="klci_live", type="primary"):
            with st.spinner("正在抓取约 120 只马股的市值、自由流通量和成交量…"):
                r = live_klci()
    if r:
        show_klci(r, files)


# ---------------------------------------------------------------------------
# 页面：板块（分类 + 板块指数 + 轮动热力图）
# ---------------------------------------------------------------------------

PERIOD_KEYS = ["1d", "1w", "1m", "3m", "1y"]
PERIOD_ZH = {"1d": "1 日", "1w": "1 周", "1m": "1 个月", "3m": "3 个月", "1y": "1 年"}


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def heatmap(sec: dict):
    rows = sorted(sec["sectors"], key=lambda s: s["returns"]["1w"] or 0, reverse=True)
    z = [[s["returns"][k] for k in PERIOD_KEYS] for s in rows]
    text = [[("—" if v is None else f"{v:+.1f}%") for v in r] for r in z]
    lim = max([abs(v) for r in z for v in r if v is not None] + [1])
    fig = go.Figure(go.Heatmap(
        z=z, x=[PERIOD_ZH[k] for k in PERIOD_KEYS], y=[f"{s['name']}（{s['count']}）" for s in rows],
        text=text, texttemplate="%{text}", colorscale=[[0, "#D9483B"], [0.5, "#26314F"], [1, "#13996A"]], textfont=dict(color="#F4F6FB"),
        zmin=-lim, zmax=lim, showscale=False, hovertemplate="%{y} · %{x}：%{text}<extra></extra>"))
    fig.update_layout(height=60 + 34 * len(rows), margin=dict(l=10, r=10, t=10, b=10),
                      yaxis=dict(autorange="reversed"), xaxis=dict(side="top"))
    return fig


def sector_card(g: dict, height: int = 118) -> str:
    """有照片的板块卡片（照片载入不了就只显示底色）。"""
    ph = (g.get("photo") or {}).get("url", "")
    r1, r1m = g["returns"].get("1d"), g["returns"].get("1m")
    col = lambda v: "#6ee7b7" if (v or 0) > 0 else "#fca5a5" if (v or 0) < 0 else "#e5e7eb"
    return f"""<div style="position:relative;height:{height}px;border-radius:14px;overflow:hidden;
      background:{g.get('color', '#22305A')} url('{ph}') center/cover no-repeat;margin-bottom:6px">
      <div style="position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.05),rgba(0,0,0,.78))"></div>
      <div style="position:absolute;left:12px;right:12px;bottom:9px;color:#fff;font-family:inherit">
        <div style="font-weight:700;font-size:1.02rem">{g.get('emoji', '')} {g['name']}
          <span style="font-weight:400;opacity:.8;font-size:.8rem">· {g['count']} 家</span></div>
        <div style="font-size:.86rem;margin-top:2px">1 日 <b style="color:{col(r1)}">{fnum(r1, 2)}</b>
          　1 个月 <b style="color:{col(r1m)}">{fnum(r1m, 1)}</b></div>
      </div></div>"""


def photo_credit(groups) -> str:
    names = sorted({(g.get("photo") or {}).get("credit", "").replace(" / Unsplash", "") for g in groups} - {""})
    return "照片：" + "、".join(names) + "（Unsplash）" if names else ""


def card_grid(groups, key: str, ncol: int = 3):
    for i in range(0, len(groups), ncol):
        cols = st.columns(ncol)
        for col, g in zip(cols, groups[i:i + ncol]):
            with col:
                st.markdown(sector_card(g), unsafe_allow_html=True)
                if st.button("查看", key=f"open_{key}_{g['name']}", width="stretch"):
                    st.session_state[f"sec_{key}"] = g["name"]
                    st.rerun()


def page_sectors():
    st.title("🧩 板块")
    st.caption("约 500 只大中型股按板块分类，另外有 AI 股、发电股、手套股、REIT 等主题板块。"
               "每个板块有自己的市值加权指数（一年前 = 1000 点）。点公司就能认识它，也可以勾选几家去对比。")
    tabs = st.tabs([m.name for m in S.MARKETS.values()])
    for tab, key in zip(tabs, S.MARKETS):
        with tab:
            files = dated_files(S.REPORT_DIR / "sectors" / key)
            if not files:
                st.info("还没有板块报告，每个交易日收市后会自动生成。")
                continue
            sec = read_json(S.REPORT_DIR / "sectors" / key / f"{files[0]}.json")
            mi = sec["market_index"]
            themes = sec.get("themes") or []
            st.caption(f"{sec['date']} 收市　{sec.get('universe_size', '')} 只股票综合：1 日 {fnum(mi['returns']['1d'], 2)}"
                       f"　1 个月 {fnum(mi['returns']['1m'], 2)}　1 年 {fnum(mi['returns']['1y'], 1)}")

            all_groups = themes + sec["sectors"]
            pick = st.session_state.get(f"sec_{key}")
            g = next((x for x in all_groups if x["name"] == pick), None)
            if g is None:
                if themes:
                    st.markdown("##### 🔥 主题板块")
                    card_grid(themes, key)
                st.markdown("##### 🗂️ 普通板块")
                card_grid(sec["sectors"], key)
                with st.expander("板块轮动热力图（按 1 周表现排序）"):
                    st.plotly_chart(heatmap({"sectors": all_groups}), width="stretch", key=f"hm_{key}")
                st.caption(photo_credit(all_groups))
                continue

            # ---- 板块详情 ----
            if st.button("‹ 全部板块", key=f"back_{key}"):
                st.session_state[f"sec_{key}"] = None
                st.rerun()
            st.markdown(sector_card(g, 150), unsafe_allow_html=True)
            if g.get("desc"):
                st.write(g["desc"])
            c = st.columns(5)
            for col, k in zip(c, PERIOD_KEYS):
                col.metric(PERIOD_ZH[k], fnum(g["returns"][k], 2))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=g["series"]["dates"], y=g["series"]["levels"], name=f"{g['name']}指数",
                                     line=dict(color="#8EA2F0", width=2.2)))
            fig.add_trace(go.Scatter(x=mi["series"]["dates"], y=mi["series"]["levels"], name="全市场综合",
                                     line=dict(color="#C8A23A", width=1.5, dash="dot")))
            fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1),
                              yaxis_title="点（起点 1000）")
            st.plotly_chart(fig, width="stretch", key=f"line_{key}")
            st.caption(f"指数 {g['level']:,.1f} 点　今天 {g['up']} 涨 {g['down']} 跌"
                       + (f"　⚠️ 最大的公司占 {g['top_weight']}%，指数主要跟着它走" if (g["top_weight"] or 0) >= 40 else ""))

            df = pd.DataFrame(g["members"])
            df["市值"] = df["mcap"].map(C.big)
            for col_ in ("div_yield", "roe"):
                if col_ not in df:
                    df[col_] = None
            show = df[["name", "ticker", "price", "weight", "chg_1d", "chg_1m", "chg_1y", "市值", "pe", "div_yield", "roe"]]
            show.columns = ["公司", "代码", "股价", "权重%", "1 日%", "1 个月%", "1 年%", "市值", "P/E", "股息率%", "ROE%"]
            tkey = f"members_{key}_{g['name']}"

            def on_pick(rows=g["members"], tkey=tkey):
                i = picked_row(tkey)
                if i is not None:
                    goto_analysis(rows[i]["ticker"])

            st.dataframe(show.style.format({"股价": "{:,.2f}", "权重%": "{:.1f}", "1 日%": "{:+.2f}", "1 个月%": "{:+.1f}",
                                            "1 年%": "{:+.1f}", "P/E": "{:.1f}", "股息率%": "{:.1f}", "ROE%": "{:.1f}"},
                                           na_rep="—").map(
                lambda v: f"color:{'#16a34a' if v > 0 else '#dc2626'}" if isinstance(v, (int, float)) and v == v else "",
                subset=["1 日%", "1 个月%", "1 年%"]),
                hide_index=True, width="stretch", key=tkey, on_select=on_pick, selection_mode=["single-row", "single-cell"])
            st.caption("👆 点任何一行就能认识那家公司。" + sec["note"])

            opts = {f"{m['name']}（{m['ticker']}）": m["ticker"] for m in g["members"]}
            chosen = st.multiselect("⚖️ 勾选 2–3 家来对比", list(opts), max_selections=3, key=f"cmp_{key}_{g['name']}")
            st.button("对比这几家", key=f"cmpbtn_{key}_{g['name']}", disabled=len(chosen) < 2, type="primary",
                      on_click=goto_compare, args=([opts[c] for c in chosen],))


# ---------------------------------------------------------------------------
# 页面：股票对比
# ---------------------------------------------------------------------------

def goto_compare(tickers: list[str]):
    st.session_state.compare_query = list(tickers)[:3]
    st.session_state.nav = "⚖️ 股票对比"


@st.cache_data(ttl=1800, show_spinner=False)
def cached_compare(tickers: tuple):
    import compare
    return compare.build(list(tickers))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_compare_ai(tickers: tuple, lang: str = "中文"):
    import compare
    return asyncio.run(compare.ai_verdict(cached_compare(tickers)))


def page_compare():
    import compare
    st.title("⚖️ 股票对比")
    st.caption("放 2 到 3 家公司在同一张表：估值、获利、成长、财务、股价表现、最新季报和公司体检评级，"
               "✓ 表示那一项比较好。最后 AI 会说谁比较适合哪种投资者。")
    q = st.session_state.get("compare_query") or ["", "", ""]
    q = (list(q) + ["", "", ""])[:3]
    with st.form("compare_form"):
        cols = st.columns(3)
        vals = [c.text_input(f"股票 {i + 1}", value=q[i], placeholder=["MAYBANK", "PBBANK", "（可留空）"][i])
                for i, c in enumerate(cols)]
        go_ = st.form_submit_button("开始对比", type="primary")
    if go_:
        st.session_state.compare_query = [v.strip() for v in vals if v.strip()]
    names = [v for v in (st.session_state.get("compare_query") or []) if v]
    if len(names) < 2:
        st.info("试试看：MAYBANK / PBBANK / CIMB，或 TOPGLOV / HARTA / KOSSAN，或 NVDA / AMD / AVGO。"
                "也可以在「板块」页面勾选同板块的公司来对比。")
        return
    with st.spinner("正在收集资料和财报（约 20-40 秒）…"):
        try:
            d = cached_compare(tuple(names))
        except Exception as e:
            st.error(f"❌ {e}")
            return

    ss = d["stocks"]
    cols = st.columns(len(ss))
    for col, x in zip(cols, ss):
        with col:
            lvl = x.get("level")
            st.markdown(f"**{x['name']}**  \n`{x['ticker']}`　{x.get('industry') or ''}")
            st.metric("股价", f"{x.get('price') or 0:,.2f} {x['currency']}",
                      None if x.get("chg_1m") is None else fnum(x["chg_1m"], 1) + "（1 个月）")
            if lvl:
                st.markdown(f"公司体检：<b style='color:{C.LEVEL_COLOR.get(lvl, '#555')}'>{lvl}</b>", unsafe_allow_html=True)
            st.caption(f"胜出 {d['wins'][x['ticker']]} 项")
            st.button("📈 看这只股票", key=f"cmpco_{x['ticker']}", on_click=goto_analysis, args=(x["ticker"],))
    if d["mixed_currency"]:
        st.warning("这几只股票的货币不同，股价和市值不能直接比，看比例类的数字（P/E、ROE、增长率）就好。")

    st.dataframe(compare.table(d), width="stretch", height=36 * (len(compare.METRICS) + 1))

    fig = go.Figure()
    for x in ss:
        if x.get("series"):
            fig.add_trace(go.Scatter(x=x["series"]["dates"], y=x["series"]["rebased"], name=x["name"]))
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h", y=1.12),
                      title="一年股价走势（起点 = 100）", yaxis_title="")
    st.plotly_chart(fig, width="stretch", key="cmp_chart")

    qs = [x for x in ss if x.get("quarter")]
    if qs:
        st.markdown("##### 📑 最新季报")
        cols = st.columns(len(qs))
        for col, x in zip(cols, qs):
            qq = x["quarter"]
            col.markdown(f"**{x['name']}**：{qq['icon']} {qq['verdict']}（{qq['period']}）")
            col.caption("；".join(qq["reasons"]))

    st.markdown("##### 🧠 AI 总结")
    with st.spinner("AI 正在比较…"):
        try:
            ai = cached_compare_ai(tuple(names), M.LANG)
        except Exception as e:
            ai = None
            st.caption(f"AI 暂时不可用：{e}")
    if ai:
        st.info(ai)
    st.caption("仅供学习参考，不构成投资建议。")


# ---------------------------------------------------------------------------
# 页面：季度报告
# ---------------------------------------------------------------------------

def big_money(v):
    import quarterly
    return quarterly.big(v)


def show_quarter(x: dict, key: str):
    st.markdown(f"#### {x['icon']} {x['name']}（{x['ticker']}）季报结论：{x['verdict']}")
    st.caption(f"季度结束 {x['period']}" + (f"　·　发现日期 {x['found']}" if x.get("found") else "")
               + (f"　·　下次业绩预计 {x['next_earnings']}" if x.get("next_earnings") else ""))
    c = st.columns(4)
    c[0].metric("营收", big_money(x["revenue"]), fnum(x["rev_yoy"], 1) + " 按年" if x["rev_yoy"] is not None else None)
    c[1].metric("净利", big_money(x["net"]), fnum(x["net_yoy"], 1) + " 按年" if x["net_yoy"] is not None else None)
    c[2].metric("净利率", fnum(x["net_margin"], 1, sign=False),
                f"去年 {x['net_margin_yoy']:.1f}%" if x.get("net_margin_yoy") is not None else None, delta_color="off")
    c[3].metric("每股盈利", "—" if x.get("eps") is None else f"{x['eps']}")
    for r in x["reasons"]:
        st.markdown(f"- {r}")
    tr = x.get("trend") or {}
    if tr.get("periods"):
        fig = go.Figure()
        fig.add_trace(go.Bar(x=tr["periods"], y=tr["revenue"], name="营收", marker_color="#8EA2F0"))
        fig.add_trace(go.Bar(x=tr["periods"], y=tr["net"], name="净利", marker_color="#C8A23A"))
        fig.update_layout(height=260, barmode="group", margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=1.15))
        st.plotly_chart(fig, width="stretch", key=f"qtrend_{key}")
    if x.get("ai"):
        st.info("🧠 " + x["ai"])
    b1, b2 = st.columns(2)
    b1.button("📈 看这只股票的全部资料", key=f"qco_{key}", on_click=goto_analysis, args=(x["ticker"],))
    b2.button("跟别家对比", key=f"qcmp_{key}", on_click=goto_compare, args=([x["ticker"]],))


@st.cache_data(ttl=3600, show_spinner=False)
def cached_quarter(text: str, lang: str = "中文"):
    import quarterly
    return quarterly.quick(text, with_ai=True)


def page_quarterly():
    st.title("📑 季度报告")
    st.caption("系统每个交易日轮流检查股票池里约 500 家公司的季报（自选股每天检查），"
               "发现新季报就打分：营收、净利按年和按季增长，再看利润率有没有变好。")
    with st.form("q_search"):
        c1, c2 = st.columns([4, 1])
        text = c1.text_input("分析任何一只股票的最新季报", placeholder="例如 TOPGLOV、TENAGA、NVDA",
                             value=st.session_state.get("quarter_query", ""))
        btn = c2.form_submit_button("分析", type="primary", width="stretch")
    if btn and text.strip():
        st.session_state.quarter_query = text.strip()
    q = st.session_state.get("quarter_query")
    if q:
        with st.spinner(f"正在读取 {q.upper()} 的季报…"):
            try:
                show_quarter(cached_quarter(q, M.LANG), "live")
            except Exception as e:
                st.error(f"❌ {e}")
        st.markdown("---")

    tabs = st.tabs([m.name for m in S.MARKETS.values()])
    for tab, key in zip(tabs, S.MARKETS):
        with tab:
            r = read_json(S.REPORT_DIR / "quarterly" / f"{key}.json")
            if not r or not r.get("items"):
                st.info("还没有季报追踪数据，每个交易日收市后会自动更新（第一次要几天才会累积完整）。")
                continue
            items = [r["items"][t] for t in r["recent"] if t in r["items"]]
            st.caption(f"更新：{r['generated_at']}　·　追踪 {r['tracked']} / {r['universe_size']} 家　·　"
                       f"今天新发现 {len(r['new_today'])} 份")
            only_new = st.toggle("只看最近 14 天新发现的", key=f"qnew_{key}")
            if only_new:
                cut = str(date.fromordinal(date.today().toordinal() - 14))
                items = [x for x in items if (x.get("found") or "") >= cut]
            if not items:
                st.info("没有符合的季报。")
                continue
            df = pd.DataFrame([{"结论": f"{x['icon']} {x['verdict']}", "公司": x["name"], "代码": x["ticker"],
                                "季度": x["period"], "营收按年%": x["rev_yoy"], "净利按年%": x["net_yoy"],
                                "净利率%": x["net_margin"], "发现": x.get("found") or "",
                                "⭐": "⭐" if x.get("watch") else ""} for x in items])
            tkey = f"qtable_{key}"
            st.dataframe(df.style.format({"营收按年%": "{:+.1f}", "净利按年%": "{:+.1f}", "净利率%": "{:.1f}"}, na_rep="—").map(
                lambda v: f"color:{'#16a34a' if v > 0 else '#dc2626'}" if isinstance(v, (int, float)) and v == v else "",
                subset=["营收按年%", "净利按年%"]), hide_index=True, width="stretch", key=tkey,
                on_select="rerun", selection_mode="single-row")
            sel = st.session_state[tkey].selection.rows if tkey in st.session_state else []
            if sel:
                show_quarter(items[sel[0]], f"{key}_{sel[0]}")
            else:
                st.caption("👆 点一行看详细分析。" + r["note"])


# ---------------------------------------------------------------------------
# 页面：IPO 追踪
# ---------------------------------------------------------------------------

STAGE_COLOR = {"计划中": "#A3ADC2", "草拟招股书": "#8EA2F0", "招股中": "#C8A23A", "认购结果": "#2BC48A",
               "已上市": "#6ee7b7", "已撤回": "#F06A5D"}


def show_ipo_analysis(a: dict, key: str):
    import ipo
    sc = a.get("score") or {}
    with st.container(border=True):
        st.markdown(f"#### 📑 IPO 分析：{a.get('name') or ''}")
        if a.get("basis") == "news":
            st.warning("没有自动找到招股书，这份分析只根据新闻，很多数字可能缺。想更准：在上面「分析招股书」上传 PDF，或在 Telegram 把 PDF 传给机器人。")
        else:
            st.caption(f"资料来源：{a.get('basis_zh') or '招股书'}　" + (f"[原文]({a['source']})" if str(a.get('source', '')).startswith('http') else ""))
        lvl = sc.get("level")
        c = st.columns(5)
        c[0].metric("规则评分", lvl or "—", f"{sc.get('avg') or '—'} / 5", delta_color="off")
        c[1].metric("本益比", f"{sc['pe']:.1f} 倍" if sc.get("pe") else "—")
        c[2].metric("盈利年复合增长", f"{sc['pat_cagr']:+.1f}%" if sc.get("pat_cagr") is not None else "—")
        c[3].metric("净利率", f"{sc['margin']:.1f}%" if sc.get("margin") is not None else "—")
        c[4].metric("募资用在扩张", f"{sc['growth_pct']:.0f}%" if sc.get("growth_pct") is not None else "—")
        st.dataframe(pd.DataFrame([{"项目": i["name"], "数值": i["value"], "分数（1–5）": str(i["score"]) if i["score"] else "—"}
                                   for i in sc.get("items", [])]), hide_index=True, width="stretch")
        if a.get("summary_zh"):
            st.info("🧠 " + a["summary_zh"])
        if a.get("business_zh"):
            st.markdown(f"**业务**：{a['business_zh']}")
        if a.get("model_zh"):
            st.markdown(f"**营业模式**：{a['model_zh']}")
        fy = [f for f in a.get("fy") or [] if f.get("year")]
        if fy:
            fig = go.Figure()
            fig.add_trace(go.Bar(x=[f["year"] for f in fy], y=[ipo._num(f.get("revenue_rm_m")) for f in fy],
                                 name="营收（RM 百万）", marker_color="#8EA2F0"))
            fig.add_trace(go.Bar(x=[f["year"] for f in fy], y=[ipo._num(f.get("pat_rm_m")) for f in fy],
                                 name="净利（RM 百万）", marker_color="#C8A23A"))
            fig.update_layout(height=260, barmode="group", margin=dict(l=10, r=10, t=10, b=10),
                              legend=dict(orientation="h", y=1.15))
            st.plotly_chart(fig, width="stretch", key=f"ipofy_{key}")
        if a.get("proceeds"):
            st.markdown("**募资用途**")
            st.dataframe(pd.DataFrame([{"用途": p.get("use"), "RM 百万": ipo._num(p.get("rm_m")), "%": ipo._num(p.get("pct")),
                                        "用在扩张": "✓" if p.get("growth") else ""} for p in a["proceeds"]]),
                         hide_index=True, width="stretch")
        for label, k in (("股息政策", "dividend_policy"), ("大股东", "major_shareholders"), ("禁售期", "moratorium")):
            if a.get(k):
                st.markdown(f"**{label}**：{a[k]}")
        cols = st.columns(3)
        for col, (label, k) in zip(cols, (("✅ 优势", "strengths_zh"), ("⚠️ 风险", "risks_zh"), ("🚩 要警惕", "red_flags_zh"))):
            col.markdown(f"**{label}**")
            for x in a.get(k) or ["—"]:
                col.markdown(f"- {x}")
        st.caption("AI 只读了招股书的重点段落（摘要、IPO 详情、财务、募资用途、风险），数字请对照原文。不构成投资建议。")


def ipo_card(r: dict, key: str):
    import ipo
    with st.container(border=True):
        top = st.columns([5, 2])
        color = STAGE_COLOR.get(r["stage"], "#A3ADC2")
        top[0].markdown(f"**{r['name']}**　<span style='background:{color}22;color:{color};padding:2px 10px;"
                        f"border-radius:999px;font-size:.85rem'>{ipo.STAGE_ICON.get(r['stage'], '')} {r['stage']}</span>"
                        + (f"　`{r['market']} Market`" if r.get("market") else ""), unsafe_allow_html=True)
        if r.get("analysis"):
            top[1].markdown(f"<div style='text-align:right'>分析评分 <b style='color:#C8A23A'>{r['analysis']['level']}</b></div>",
                            unsafe_allow_html=True)
        if r.get("business"):
            st.caption(r["business"])
        p = r.get("perf")
        facts = [("IPO 价", f"RM{r['ipo_price']:g}" if r.get("ipo_price") else "—", None),
                 ("集资", ipo.f_rm(r.get("proceeds_rm_m")) if r.get("proceeds_rm_m") else "—", None),
                 ("上市市值", ipo.f_rm(r.get("market_cap_rm_m")) if r.get("market_cap_rm_m") else "—", None),
                 ("超额认购", f"{r['oversub_times']:.1f} 倍" if r.get("oversub_times") else "—",
                  f"{r['applications']:,.0f} 份申请" if r.get("applications") else None)]
        if p:
            facts.append(("首日", f"{p['first_day_pct']:+.1f}%", f"至今 {p['since_ipo_pct']:+.1f}%"))
        else:
            facts.append(("本益比", f"{r['pe']:.1f} 倍" if r.get("pe") else "—", None))
        st.markdown("<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:6px 0'>" + "".join(
            f"<div style='background:#1B2540;border:1px solid #2C3756;border-radius:12px;padding:10px 12px'>"
            f"<div style='font-size:.8rem;color:#A3ADC2'>{k}</div>"
            f"<div style='font-family:\"Barlow Semi Condensed\",sans-serif;font-weight:700;font-size:1.35rem'>{v}</div>"
            + (f"<div style='font-size:.78rem;color:#A3ADC2'>{sub}</div>" if sub else "") + "</div>"
            for k, v, sub in facts) + "</div>", unsafe_allow_html=True)
        dates = [("申请", f"{r.get('application_open') or '?'} → {r['application_close']}" if r.get("application_close") else None),
                 ("抽签", r.get("balloting_date")), ("上市", r.get("listing_date")),
                 ("代码", r.get("ticker")), ("土著部分", f"{r['bumi_oversub_times']:.2f} 倍" if r.get("bumi_oversub_times") else None),
                 ("顾问", r.get("principal_adviser")), ("发行处", r.get("issuing_house"))]
        st.caption("　·　".join(f"{k} {v}" for k, v in dates if v))
        with st.expander("新闻来源"):
            for a in r.get("articles", [])[:6]:
                st.markdown(f"🔗 [{a.get('title')}]({a.get('link')}) — {a.get('source') or ''}，{(a.get('published') or '')[:10]}")
        # ---- 一键分析：已经分析过就直接显示；没有就按按钮（自动找招股书，找不到用新闻）----
        saved = read_json(S.REPORT_DIR / "ipo" / r["analysis"]["file"]) if r.get("analysis") else None
        live = st.session_state.get(f"ipo_live_{r['slug']}")
        b = st.columns([2, 2, 3])
        label = "🔍 重新分析" if (saved or live) else "🔍 分析这家公司"
        auto = st.session_state.get("ipo_auto") == r["slug"]
        if b[0].button(label, key=f"ipoan_{key}", type="primary" if not (saved or live) else "secondary") or (auto and not live):
            st.session_state.ipo_auto = None
            with st.spinner(f"正在找 {r['name']} 的招股书并分析（约 1–2 分钟）…"):
                try:
                    st.session_state[f"ipo_live_{r['slug']}"] = cached_ipo_analysis(r["slug"], json.dumps(r, ensure_ascii=False), M.LANG)
                    live = st.session_state[f"ipo_live_{r['slug']}"]
                except Exception as e:
                    st.error(f"❌ {e}")
        if r.get("ticker"):
            b[1].button("📈 看这只股票", key=f"ipoco_{key}", on_click=goto_analysis, args=(r["ticker"],))
        if live or saved:
            show_ipo_analysis(live or saved, key)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_ipo_analysis(slug: str, rec_json: str, lang: str = "中文"):
    import ipo
    return ipo.analyze_ipo(json.loads(rec_json))


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def live_ipo_list():
    """自动任务还没存到资料时：网站自己去抓一次（发行处网站 + 新闻 + AI 整理），不推送 Telegram。"""
    import ipo
    return ipo.run(push=False, force=True)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_ipo_pdf(data: bytes, source: str, lang: str = "中文"):
    import ipo
    return ipo.analyze_pdf(data, source)


def page_ipo():
    import ipo
    st.title("🆕 IPO 追踪")
    st.caption("自动从新闻和发行处网站整理马股新股（Main / ACE / LEAP）：招股资料、认购情况、上市后表现，每 3 小时更新。"
               "点任何一家的「🔍 分析这家公司」：系统自动找招股书（证监会网站），找不到就用新闻分析。招股中的 IPO 会自动先分析好。")
    r = read_json(S.REPORT_DIR / "ipo" / "ipos.json")
    recs = list((r or {}).get("ipos", {}).values())

    with st.expander("📑 自己上传招股书（自动找不到时用）", expanded=False):
        up = st.file_uploader("招股书 PDF", type=["pdf"], key="ipo_pdf")
        url = st.text_input("或 PDF 链接", placeholder="https://…/prospectus.pdf", key="ipo_url")
        if st.button("开始分析", type="primary", disabled=not (up or url.strip())):
            with st.spinner("正在读招股书的重点段落并分析（约 1–2 分钟）…"):
                try:
                    data = up.getvalue() if up else ipo.fetch_pdf(url.strip())
                    st.session_state.ipo_result = cached_ipo_pdf(data, up.name if up else url.strip(), M.LANG)
                except Exception as e:
                    st.error(f"❌ {e}")
        if st.session_state.get("ipo_result"):
            show_ipo_analysis(st.session_state.ipo_result, "upload")
            st.caption("网站上的分析不会存起来；想长期保存，请在 Telegram 把 PDF 传给机器人。")

    if not recs:
        with st.spinner("自动任务还没存到 IPO 资料，网站现在自己去找（发行处网站 + 最近 3 个星期的新闻，约 1 分钟）…"):
            try:
                r = live_ipo_list()
            except Exception as e:
                st.error(f"❌ 抓取失败：{e}")
                r = None
        recs = list((r or {}).get("ipos", {}).values())
        if not recs:
            live_ipo_list.clear()
            st.warning("现在找不到 IPO 资料（可能是新闻网站或 AI 暂时连不上）。等一下重新整理这一页再试。")
            if st.button("🔄 再找一次"):
                st.rerun()
            return
        st.caption("（这是网站刚刚自己抓的；「新闻追踪」自动任务存好资料后，手机 App 和 Telegram 也会看到。）")
    st.caption(f"更新：{r.get('updated')}　·　共 {len(recs)} 个 IPO")
    active = sorted([x for x in recs if x["stage"] in ("招股中", "认购结果")], key=lambda x: x.get("listing_date") or "9")
    pipeline = sorted([x for x in recs if x["stage"] in ("计划中", "草拟招股书")], key=lambda x: x.get("updated") or "", reverse=True)
    listed = sorted([x for x in recs if x["stage"] == "已上市"], key=lambda x: x.get("listing_date") or "", reverse=True)
    tabs = st.tabs([f"招股中 / 等上市（{len(active)}）", f"已上市（{len(listed)}）", f"筹备中（{len(pipeline)}）"])
    with tabs[0]:
        if not active:
            st.info("现在没有开放申请或等待上市的 IPO。")
        for i, x in enumerate(active):
            ipo_card(x, f"a{i}")
    with tabs[1]:
        perf = [x for x in listed if x.get("perf")]
        if perf:
            c = st.columns(3)
            avg1 = sum(x["perf"]["first_day_pct"] for x in perf) / len(perf)
            up_ = sum(1 for x in perf if x["perf"]["first_day_pct"] > 0)
            c[0].metric("平均首日表现", f"{avg1:+.1f}%")
            c[1].metric("首日上涨比例", f"{up_}/{len(perf)}")
            c[2].metric("至今仍高于 IPO 价", f"{sum(1 for x in perf if x['perf']['since_ipo_pct'] > 0)}/{len(perf)}")
            pts = [x for x in perf if x.get("oversub_times")]
            if len(pts) >= 3:
                fig = go.Figure(go.Scatter(x=[x["oversub_times"] for x in pts], y=[x["perf"]["first_day_pct"] for x in pts],
                                           mode="markers+text", text=[x["name"].split()[0] for x in pts], textposition="top center",
                                           marker=dict(size=10, color="#C8A23A")))
                fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10), title="超额认购倍数 vs 首日表现",
                                  xaxis_title="公众部分超额认购（倍，对数）", yaxis_title="首日涨跌 %", xaxis_type="log")
                st.plotly_chart(fig, width="stretch", key="ipo_scatter")
            st.dataframe(pd.DataFrame([{"公司": x["name"], "代码": x.get("ticker"), "市场": x.get("market"),
                                        "上市日": x.get("listing_date"), "IPO 价": x.get("ipo_price"),
                                        "超额认购": x.get("oversub_times"), "首日%": x["perf"]["first_day_pct"],
                                        "现价": x["perf"]["last"], "至今%": x["perf"]["since_ipo_pct"]} for x in perf]
                                      ).style.format({"IPO 价": "{:g}", "超额认购": "{:.1f}", "首日%": "{:+.1f}", "至今%": "{:+.1f}",
                                                      "现价": "{:g}"}, na_rep="—").map(
                lambda v: f"color:{'#16a34a' if v > 0 else '#dc2626'}" if isinstance(v, (int, float)) and v == v else "",
                subset=["首日%", "至今%"]), hide_index=True, width="stretch")
        for i, x in enumerate(listed[:20]):
            ipo_card(x, f"l{i}")
    with tabs[2]:
        if not pipeline:
            st.info("没有筹备中的 IPO 资料。")
        for i, x in enumerate(pipeline[:30]):
            ipo_card(x, f"p{i}")
    st.caption("资料由 AI 整理自公开新闻，可能不完整或有出入；申购前请看招股书原文。不构成投资建议。")


# ---------------------------------------------------------------------------
# 页面：新闻追踪
# ---------------------------------------------------------------------------

VIEW_STYLE = {"利好": ("📈", "#2BC48A"), "利空": ("📉", "#F06A5D"), "中性": ("➖", "#A3ADC2")}


def macro_card(e: dict, key: str):
    import news as N
    with st.container(border=True):
        top = st.columns([5, 2])
        top[0].markdown("**🌏 宏观新闻**　" + "、".join(f"`{a['name']}`" for a in e["affected"]))
        top[1].markdown(f"<div style='text-align:right;color:#C8A23A;letter-spacing:2px'>{N.stars(e['importance'])}</div>",
                        unsafe_allow_html=True)
        st.markdown(f"#### {e['headline_zh']}")
        if e.get("analysis"):
            st.write(e["analysis"])
        for a in e["affected"]:
            c1, c2 = st.columns(2)
            for col, label, k in ((c1, f"{a['name']} · 短期", "short_term"), (c2, f"{a['name']} · 长期", "long_term")):
                v = a[k]["view"]
                icon, color = VIEW_STYLE.get(v, VIEW_STYLE["中性"])
                col.markdown(f"<div style='border-left:4px solid {color};padding:6px 12px;border-radius:8px;margin-bottom:6px;"
                             f"background:rgba(127,127,127,.08)'><div style='font-size:.82rem;opacity:.7'>{label}</div>"
                             f"<div style='font-weight:700;color:{color}'>{icon} {v}</div>"
                             f"<div style='font-size:.9rem'>{a[k]['why']}</div></div>", unsafe_allow_html=True)
        st.caption(f"把握度：{e.get('confidence', '中')}")
        for a in e["articles"][:3]:
            st.markdown(f"🔗 [{a['title']}]({a['link']}) — {a.get('source') or ''}，{N._ago(a['published'])}")


def news_card(e: dict, key: str):
    if e.get("type") == "macro":
        return macro_card(e, key)
    import news as N
    with st.container(border=True):
        top = st.columns([5, 2])
        top[0].markdown(f"**{e['name']}**　`{e['ticker']}`")
        top[1].markdown(f"<div style='text-align:right;color:#C8A23A;letter-spacing:2px'>{N.stars(e['importance'])}</div>",
                        unsafe_allow_html=True)
        st.markdown(f"#### {e['headline_zh']}")
        if e.get("analysis"):
            st.write(e["analysis"])
        c1, c2 = st.columns(2)
        for col, label, k in ((c1, "短期（几天到几周）", "short_term"), (c2, "长期（一年以上）", "long_term")):
            v = e[k]["view"]
            icon, color = VIEW_STYLE.get(v, VIEW_STYLE["中性"])
            col.markdown(f"<div style='border-left:4px solid {color};padding:6px 12px;border-radius:8px;"
                         f"background:rgba(127,127,127,.08)'><div style='font-size:.82rem;opacity:.7'>{label}</div>"
                         f"<div style='font-weight:700;color:{color}'>{icon} {v}</div>"
                         f"<div style='font-size:.9rem'>{e[k]['why']}</div></div>", unsafe_allow_html=True)
        px = e.get("price") or {}
        meta = [f"把握度：{e.get('confidence', '中')}"]
        if px.get("price") is not None:
            meta.insert(0, f"股价 {px['price']:,.2f}（今天 {px.get('chg_1d') or 0:+.2f}%，1 个月 {px.get('chg_1m') or 0:+.1f}%）")
        st.caption("　·　".join(meta))
        for a in e["articles"][:3]:
            st.markdown(f"🔗 [{a['title']}]({a['link']}) — {a.get('source') or ''}，{N._ago(a['published'])}")
        st.button("📈 看这只股票的全部资料", key=f"nan_{key}", on_click=goto_analysis, args=(e["ticker"],))


@st.cache_data(ttl=1800, show_spinner=False)
def cached_news(text: str, lang: str = "中文"):
    import news as N
    return N.quick(text)


def page_news():
    import newspaper as NP
    st.title("🗞️ 新闻追踪")
    st.caption("只追踪你关注的公司（自选股、news_only、Telegram /follow），加上牵连到它们的宏观大新闻。"
               "AI 先确认新闻真的跟公司有关，再分析短期和长期影响；点标题看原文，点「AI 分析」看理由。")
    r = read_json(S.REPORT_DIR / "news" / "feed.json")
    events = (r or {}).get("events") or []
    names = {c["ticker"]: c["name"] for c in (r or {}).get("companies", [])}

    c1, c2, c3, c4 = st.columns([6, 1.3, 1.4, 1.1], vertical_alignment="bottom")
    with c1:
        sec = st.pills("栏目", list(NP.SECTIONS), default="头条", key="np_sec", label_visibility="collapsed") or "头条"
    with c2:
        lang = st.segmented_control("语言", ["中文", "EN"], default="中文", key="np_lang",
                                    label_visibility="collapsed") or "中文"
    with c3:
        sort = st.selectbox("排序", ["最新", "最重要"], key="np_sort", label_visibility="collapsed",
                            format_func=lambda v: f"排序：{v}")
    with c4:
        with st.popover("筛选", icon=":material/tune:", width="stretch"):
            pick = st.multiselect("公司", list(names), format_func=lambda t: names.get(t, t), key="news_pick",
                                  placeholder="全部公司")
            min_imp = st.select_slider("重要性至少", options=[1, 2, 3, 4, 5], value=1, key="news_imp")
            days = st.select_slider("时间", options=[1, 3, 7, 14, 30], value=30, key="news_days",
                                    format_func=lambda d: f"最近 {d} 天")
    tick = lambda e: e.get("tickers") or [e.get("ticker")]
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    evs = [e for e in events if e.get("importance", 1) >= min_imp and e.get("published", "") >= cut
           and (not pick or set(tick(e)) & set(pick))]

    if r and r.get("ai_error"):
        st.error("⚠️ " + r["ai_error"])
    if not r:
        st.info("还没有新闻记录。新闻追踪每小时自动跑一次（GitHub Actions 的「新闻追踪」），第一次运行后这里就会有内容。")
    else:
        st.html(NP.page(evs, sec, lang, sort))
        st.caption(f"更新：{r['updated']}　·　追踪 {len(names)} 家：" + "、".join(names.values())
                   + "　·　加减公司：Telegram 发 /follow 代码 或 /unfollow 代码")
        if r.get("note"):
            st.caption(r["note"])

    with st.expander("🔍 现在就查某只股票的新闻（不在追踪名单也可以）", expanded=bool(st.session_state.get("news_query"))):
        with st.form("news_search"):
            f1, f2 = st.columns([4, 1])
            text = f1.text_input("股票", placeholder="例如 GAMUDA、TOPGLOV、NVDA", label_visibility="collapsed",
                                 value=st.session_state.get("news_query", ""))
            btn = f2.form_submit_button("分析", type="primary", width="stretch")
        if btn and text.strip():
            st.session_state.news_query = text.strip()
        q = st.session_state.get("news_query")
        if q:
            with st.spinner(f"正在找 {q.upper()} 的新闻并请 AI 分析（约 20-40 秒）…"):
                try:
                    found = cached_news(q, M.LANG)
                except Exception as e:
                    found = None
                    st.error(f"❌ {e}")
            found = [e for e in found or [] if e["relevant"]]
            if not found and found is not None:
                st.info("最近 48 小时没有找到这家公司的新闻。")
            else:
                st.html(NP.page(found, "最新", lang, "最重要", title=q.upper()))
                st.button("📈 看这只股票的全部资料", key="nq_an", on_click=goto_analysis, args=(found[0]["ticker"],))


# ---------------------------------------------------------------------------
# 页面：公告日历（业绩日、除权日）
# ---------------------------------------------------------------------------

CAL_CSS = """
<style>
.cal{background:#fff;color:#141414;border-radius:14px;padding:6px 0 10px;font-family:"Noto Sans SC",system-ui,sans-serif}
.cal-weeks{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:2px 0 4px}
.cal-wk{background:#f3f4f7;border:1px solid #e3e5ea;border-radius:12px;padding:12px 14px;color:#141414}
.cal-wk.now{background:#fff;border-color:#3b5bdb;box-shadow:0 0 0 1px #3b5bdb inset}
.cal-wk small{display:block;font-size:.72rem;color:#777;font-weight:600}.cal-wk.now small{color:#3b5bdb}
.cal-wk b{display:block;font-size:1.08rem;margin:2px 0}.cal-wk span{font-size:.78rem;color:#555}
.cal-grp{display:flex;justify-content:space-between;align-items:center;background:#f6f7f9;border-top:1px solid #e6e6e6;
 border-bottom:1px solid #e6e6e6;padding:12px 18px;margin-top:6px}
.cal-grp b{font-size:1rem}.cal-grp small{display:block;color:#777;font-size:.75rem}
.cal-grp .cnt{border:1px solid #ddd;border-radius:99px;padding:3px 12px;font-size:.78rem;font-weight:700;background:#fff}
.cal-row{display:grid;grid-template-columns:2.2fr 2.6fr 1.7fr .8fr 1fr;align-items:center;gap:12px;padding:11px 18px;border-bottom:1px solid #eee}
.cal-row:hover{background:#fafafa}
.cal-co{display:flex;gap:10px;align-items:center;min-width:0}
.cal-av{width:34px;min-width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:.8rem}
.cal-co b{display:block;font-size:.92rem}.cal-co small,.cal-ev small,.cal-dt small{display:block;color:#777;font-size:.75rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cal-ev b,.cal-dt b{font-size:.88rem;font-weight:700}
.cal-tag{justify-self:start;font-size:.74rem;font-weight:700;padding:3px 10px;border-radius:99px}
.cal-tag.div{background:#efe7fb;color:#6b3fb8}.cal-tag.ern{background:#e6effc;color:#1f5bb5}
.cal-st{font-size:.82rem;color:#555}.cal-st.soon{color:#0a7d4f;font-weight:700}.cal-st.est{color:#b26a00}
.cal-star{color:#d4a017;margin-left:4px}
.cal-empty{padding:26px;text-align:center;color:#777}
@media(max-width:900px){.cal-row{grid-template-columns:1fr 1fr;row-gap:4px}.cal-tag,.cal-st{display:none}}
</style>
"""
AV_COLORS = ["#2b4c7e", "#a0522d", "#2f6b3b", "#6b3fb8", "#b42318", "#1f7a74", "#8a6d1d", "#4a5a8a", "#c2410c", "#334155"]


def cal_row(e: dict) -> str:
    import announce as AN
    import zlib
    x = html.escape
    code = e["ticker"].split(".")[0]
    bursa = code[:1].isdigit()                       # 大马股票代码是数字：名字放大，代码放小
    short, longname = ((e["name"] or code), e["ticker"]) if bursa else (code, e["name"] or "")
    av = AV_COLORS[zlib.crc32(e["ticker"].encode()) % len(AV_COLORS)]
    init = short[:2].upper()
    stt = e["status"]
    cls = "soon" if stt in ("即将公布", "即将除权") else "est" if stt == "预计" else ""
    star = "<span class='cal-star'>★</span>" if e.get("mine") else ""
    tag = "<span class='cal-tag div'>股息</span>" if e["type"] == "股息" else "<span class='cal-tag ern'>业绩</span>"
    return (f"<div class='cal-row'><div class='cal-co'><div class='cal-av' style='background:{av}'>{x(init)}</div>"
            f"<div style='min-width:0'><b>{x(short)}{star}</b><small>{x(longname)}</small></div></div>"
            f"<div class='cal-ev'><b>{x(e['title'])}</b><small>{x(e['sub'])}</small></div>"
            f"<div class='cal-dt'><b>{AN.day_label(e['date'])}</b><small>{AN.countdown(e['date'])}</small></div>"
            f"{tag}<div class='cal-st {cls}'>{x(stt)}</div></div>")


def cal_group(title: str, sub: str, evs: list[dict], limit: int | None = None) -> str:
    rows = "".join(cal_row(e) for e in (evs[:limit] if limit else evs))
    more = f"<div class='cal-empty'>还有 {len(evs) - limit} 项，打开上面的「显示全部」</div>" if limit and len(evs) > limit else ""
    return (f"<div class='cal-grp'><div><b>{html.escape(title)}</b><small>{html.escape(sub)}</small></div>"
            f"<span class='cnt'>{len(evs)} 项</span></div>{rows}{more}")


def goto_quarter(t: str):
    st.session_state.quarter_query = t
    st.session_state.nav = "📑 季度报告"


def page_calendar():
    import announce as AN
    st.title("📅 公告日历")
    st.caption("股票池约 500 只股票（加上你关注的公司）的业绩公布日和派息除权日。每个交易日收市后更新；"
               "⭐ = 你关注的公司，明天除权、今天 / 明天公布业绩会发 Telegram 提醒。Telegram 也可以发 /calendar 查。")
    data = read_json(S.REPORT_DIR / "calendar" / "events.json")
    if not data or not data.get("events"):
        st.info("还没有公告日历资料。下一次收市后的「市场报告」自动任务跑完就会有（也可以去 Actions 手动跑一次）。")
        return
    today = AN.today_myt()
    c1, c2 = st.columns([3, 2], vertical_alignment="bottom")
    with c1:
        per = st.segmented_control("时间", AN.PERIODS, default="本月", key="cal_per", label_visibility="collapsed") or "本月"
    with c2:
        q = st.text_input("搜索", placeholder="🔍 搜索股票代码、简称、名称", key="cal_q", label_visibility="collapsed")
    s, e = AN.period_range(per, today)
    f1, f2, f3, f4 = st.columns([1.2, 1.2, 1.6, 2], vertical_alignment="center")
    mk = f1.selectbox("市场", ["全部市场", "马股", "美股", "印尼股"], key="cal_mk", label_visibility="collapsed")
    kind = f2.selectbox("类型", ["业绩 + 股息", "业绩", "股息"], key="cal_kind", label_visibility="collapsed")
    mine = f3.toggle("只看我关注的公司", key="cal_mine")
    market = {"马股": "bursa", "美股": "us", "印尼股": "idx"}.get(mk)
    evs = AN.select(data["events"], s, e, market, None if kind == "业绩 + 股息" else kind, mine, q or "")
    upcoming = [x for x in evs if x["date"] >= str(today)]
    f4.markdown(f"<div style='text-align:right;font-weight:700'>{len(upcoming)} 项即将公布 / 除权</div>", unsafe_allow_html=True)

    # 每周小卡
    cards = []
    for ws, we in AN.buckets(per, s, e):
        n = [x for x in evs if str(ws) <= x["date"] <= str(we)]
        done = sum(x["status"] in ("已公布", "已除权") for x in n)
        now = ws <= today <= we
        lab = "本周" if now else f"{ws.month}月{ws.day}日 当周"
        info = f"{done} 项已公布 · {len(n) - done} 项待公布" if done and len(n) - done else (f"{done} 项已公布" if done else f"{len(n)} 项")
        cards.append(f"<div class='cal-wk{' now' if now else ''}'><small>{lab}</small>"
                     f"<b>{ws.month}月{ws.day}日 – {we.month}月{we.day}日</b><span>{info}</span></div>")
    st.html(CAL_CSS + "<div class='cal-weeks'>" + "".join(cards) + "</div>")

    show_all = st.toggle("显示全部（不然每组只显示前 15 项）", key="cal_all")
    lim = None if show_all else 15
    parts = []
    recent = [x for x in AN.select(data["events"], today - timedelta(days=7), today - timedelta(days=1), market,
                                   None if kind == "业绩 + 股息" else kind, mine, q or "")]
    if per in ("本周", "本月", "上月") and recent:
        parts.append(cal_group("最近公布 / 除权", "过去 7 天", sorted(recent, key=lambda x: (bool(x.get("mine")), x["date"]), reverse=True), 5 if lim else None))
    for ws, we in AN.buckets(per, s, e):
        n = [x for x in evs if str(ws) <= x["date"] <= str(we)]
        if not n:
            continue
        n.sort(key=lambda x: (x["date"], not x.get("mine"), x["type"]))
        parts.append(cal_group(f"{ws.month}月{ws.day}日 – {we.month}月{we.day}日", "本周" if ws <= today <= we else
                               ("已过" if we < today else "即将到来"), n, lim))
    st.html(CAL_CSS + "<div class='cal'>" + ("".join(parts) or "<div class='cal-empty'>这段时间没有符合条件的业绩或派息。</div>") + "</div>")
    st.caption(f"更新：{data.get('updated')}　·　日期来自 Yahoo Finance；「预计」= 公司还没正式宣布"
               "（大马股票按 Bursa 规定：季度结束后 2 个月内一定要公布，所以显示最迟日期）。派息金额以公司公告为准。")

    opts = sorted({x["ticker"]: x["name"] for x in evs}.items(), key=lambda kv: kv[1] or "")
    if opts:
        g1, g2, g3 = st.columns([3, 1, 1], vertical_alignment="bottom")
        t = g1.selectbox("想深入看哪一家？", [k for k, _ in opts], format_func=lambda k: f"{dict(opts)[k]}（{k}）", key="cal_pick")
        g2.button("📑 季度报告", width="stretch", on_click=goto_quarter, args=(t,))
        g3.button("📈 个股页面", width="stretch", on_click=goto_analysis, args=(t,))


# ---------------------------------------------------------------------------
# 页面：自选股
# ---------------------------------------------------------------------------

def page_watchlist():
    st.title("⭐ 自选股")
    owner_repo = os.getenv("GITHUB_REPO", "lowjunren9910-creator/stock-bot")
    st.caption(f"名单和提醒条件在 GitHub 的 watchlist.yml 里改：[打开编辑](https://github.com/{owner_repo}/edit/main/watchlist.yml)。"
               "交易日每 15 分钟检查一次，触发时推送 Telegram。")
    wl = read_json(S.REPORT_DIR / "watchlist.json")
    if not wl or not wl.get("stocks"):
        st.info("还没有自选股资料。编辑 watchlist.yml 后，下一次自动任务就会出现。")
        return
    st.caption(f"更新：{wl['updated']}")
    for x in wl["stocks"]:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 2, 2])
            c1.markdown(f"**{x['name']}**　`{x['ticker']}`" + (f"　{x['note']}" if x.get("note") else ""))
            if x.get("error"):
                c1.error(x["error"])
                continue
            c2.metric("股价", f"{x['price']:,.2f}", f"{x['change_pct']:+.2f}%")
            c3.metric("RSI / 1 个月", f"{x['rsi']:.0f}", fnum(x.get("chg_1m"), 1), delta_color="off")
            al = x.get("alerts") or {}
            if al:
                labels = {"below": "跌破", "above": "升破", "change_pct": "单日 ±", "rsi_below": "RSI <", "rsi_above": "RSI >"}
                chips = "　".join(("🔔 " if k in x["triggered"] else "") + f"{labels.get(k, k)} {v}" for k, v in al.items())
                c1.caption("提醒：" + chips)
            c1.button("📈 走势 · 资料 · AI 分析 →", key=f"wl_an_{x['ticker']}", on_click=goto_analysis, args=(x["ticker"],))


# ---------------------------------------------------------------------------
# 页面：成绩单 + 基金经理排行榜
# ---------------------------------------------------------------------------

def page_track():
    st.title("📈 成绩单")
    st.caption("系统推荐过的股票后来表现怎样？跟大盘比是赢还是输？AI 基金经理谁最准？")
    tabs = st.tabs([m.name for m in S.MARKETS.values()])
    for tab, key in zip(tabs, S.MARKETS):
        with tab:
            tr = read_json(S.REPORT_DIR / "track" / f"{key}.json")
            if not tr:
                st.info("还没有成绩单，收市后会自动生成。推荐累积几天到几周后才看得出成绩。")
                continue
            st.caption(f"更新：{tr['updated']}　对照大盘：{tr['benchmark']}")
            rows = []
            for cat, v in tr["summary"].items():
                for h in ("1w", "1m", "3m", "now"):
                    d = v[h]
                    rows.append({"策略": v["name"], "持有": tr["horizons"][h], "已评估": d["n"],
                                 "平均涨跌%": d["avg_ret"], "平均超额%": d["avg_excess"],
                                 ("避开成功率%" if cat == "double_kill" else "跑赢大盘%"): d["hit_rate"]})
            df = pd.DataFrame(rows)
            st.markdown("##### 推荐成绩")
            st.dataframe(df, hide_index=True, width="stretch")
            st.caption("超额 = 股票涨跌 − 同期大盘涨跌。双杀股是要避开的名单，所以看「跑输大盘」的比例。持有期还没到的不计算。")

            st.markdown("##### 🏆 AI 基金经理排行榜（看 21 个交易日后）")
            lb = pd.DataFrame(tr["leaderboard"])
            if lb.empty or not lb["n"].sum():
                pend = int(lb["pending"].sum()) if not lb.empty else 0
                st.info(f"还在累积中：已经记录 {pend} 个评级，过 21 个交易日后就会开始评分。")
            else:
                lb["经理"] = lb["emoji"] + " " + lb["name"] + "｜" + lb["title"]
                st.dataframe(lb[["经理", "n", "hit_rate", "bull_avg_excess", "pending"]].rename(columns={
                    "n": "已评分", "hit_rate": "准确率%", "bull_avg_excess": "看多时平均超额%", "pending": "等待中"}),
                    hide_index=True, width="stretch")
            with st.expander("最近的推荐（至今表现）"):
                p = pd.DataFrame(tr["picks"])
                if not p.empty:
                    p["策略"] = p["strategy"].map({k: v["name"] for k, v in tr["summary"].items()})
                    st.dataframe(p[["date", "策略", "name", "ticker", "ret_now", "ex_now", "days"]].rename(columns={
                        "date": "推荐日", "name": "公司", "ticker": "代码", "ret_now": "至今%", "ex_now": "超额%",
                        "days": "交易日"}), hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# 页面：周报 + 系统状态
# ---------------------------------------------------------------------------

def page_weekly():
    st.title("📰 每周周报")
    st.caption("每个星期六早上（美股星期五收市后）自动生成。")
    files = dated_files(S.REPORT_DIR / "weekly")
    if not files:
        st.info("还没有周报，第一个星期五美股收市后会出现。")
        return
    d = st.selectbox("选择周报", files)
    r = read_json(S.REPORT_DIR / "weekly" / f"{d}.json")
    if r.get("ai_comment"):
        with st.container(border=True):
            st.markdown("**🧠 本周总结**")
            st.write(r["ai_comment"])
    for mk, v in r["markets"].items():
        st.markdown(f"#### {v['name']}　本周 {fnum(v['week'], 2)}")
        c1, c2, c3 = st.columns(3)
        c1.markdown("**板块（本周）**\n\n" + "\n\n".join(f"{x['name']} {fnum(x['week'], 2)}" for x in v["sectors"]))
        c2.markdown("**涨最多**\n\n" + "\n\n".join(f"{x['name']} {fnum(x['chg_1w'], 1)}" for x in v["gainers"]))
        c3.markdown("**跌最多**\n\n" + "\n\n".join(f"{x['name']} {fnum(x['chg_1w'], 1)}" for x in v["losers"]))
    if r.get("klci"):
        st.markdown("#### 🏆 KLCI 50 几率（本周变化）")
        st.dataframe(pd.DataFrame(r["klci"]["top"]).rename(columns={"name": "公司", "ticker": "代码", "prob": "几率%",
                                                                   "change": "本周变化"}), hide_index=True, width="stretch")


def page_health():
    st.title("🩺 系统状态")
    h = read_json(S.REPORT_DIR / "health.json")
    idx = read_json(S.REPORT_DIR / "index.json") or {}
    st.caption(f"报告目录更新：{idx.get('updated', '—')}")
    if not h:
        st.info("还没有健康检查结果，每个星期六早上会自动检查一次。")
        return
    st.metric("股票代码正常", f"{h['ok']} / {h['total']}", f"检查时间 {h['checked']}", delta_color="off")
    if h["problems"]:
        st.dataframe(pd.DataFrame(h["problems"]).rename(columns={"ticker": "代码", "name": "名称", "where": "在哪个名单",
                                                                "status": "问题"}), hide_index=True, width="stretch")
    else:
        st.success("全部代码都正常 👍")


# ---------------------------------------------------------------------------

PAGES = {  # 顺序要跟 ui.NAV_GROUPS 的分组对应
    "📅 每日焦点": page_focus, "🧩 板块": page_sectors, "🔍 选股雷达": page_radar, "🏆 KLCI 50 观察": page_klci, "🆕 IPO 追踪": page_ipo, "📅 公告日历": page_calendar,
    "📊 个股分析": page_analysis, "⚖️ 股票对比": page_compare, "📑 季度报告": page_quarterly,
    "⭐ 自选股": page_watchlist, "🗞️ 新闻追踪": page_news, "💼 投资组合": page_portfolio, "📈 成绩单": page_track, "📰 周报": page_weekly,
    "🩺 系统状态": page_health}

if check_password():
    # 手机 app 的按钮会带网址参数打开：?company=4065.KL 或 ?analyze=4065.KL
    qp = st.query_params
    if not st.session_state.get("_qp_done"):
        if qp.get("company"):
            goto_analysis(qp["company"], "🏢 认识公司")
        elif qp.get("compare"):
            st.session_state.compare_query = [t for t in qp["compare"].split(",") if t][:3]
            st.session_state.nav = "⚖️ 股票对比"
        elif qp.get("quarter"):
            st.session_state.quarter_query = qp["quarter"]
            st.session_state.nav = "📑 季度报告"
        elif qp.get("ipo"):
            st.session_state.ipo_auto = qp["ipo"]
            st.session_state.nav = "🆕 IPO 追踪"
        elif qp.get("news"):
            st.session_state.news_query = qp["news"]
            st.session_state.nav = "🗞️ 新闻追踪"
        elif qp.get("analyze") or qp.get("stock"):
            goto_analysis(qp.get("stock") or qp["analyze"])
        elif qp.get("page") in ("focus", "radar", "klci", "sectors", "track", "weekly", "watch", "quarterly", "compare", "news", "ipo", "calendar", "portfolio"):
            st.session_state.nav = {"focus": "📅 每日焦点", "radar": "🔍 选股雷达", "klci": "🏆 KLCI 50 观察",
                                    "sectors": "🧩 板块", "track": "📈 成绩单", "weekly": "📰 周报",
                                    "watch": "⭐ 自选股", "quarterly": "📑 季度报告",
                                    "compare": "⚖️ 股票对比", "news": "🗞️ 新闻追踪", "ipo": "🆕 IPO 追踪",
                                    "calendar": "📅 公告日历", "portfolio": "💼 投资组合"}[qp["page"]]
        st.session_state._qp_done = True
    ui.sidebar_brand()

    def _lang_changed():
        st.query_params["lang"] = "en" if st.session_state.lang == "EN" else "zh"
    st.sidebar.segmented_control("🌐 语言", ["中文", "EN"], key="lang", on_change=_lang_changed,
                                 label_visibility="collapsed", width="stretch")
    page = st.sidebar.radio("功能", list(PAGES), key="nav")
    ui.sidebar_footer(M.MANAGERS)
    PAGES[page]()
