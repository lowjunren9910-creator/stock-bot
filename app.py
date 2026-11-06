"""
app.py - 网页版股票分析（Streamlit）

本地运行：  streamlit run app.py
部署上网：  见 README「网页版」部分（Streamlit Community Cloud，免费）
"""

import asyncio
import hmac
import io
import json
import os
from datetime import date

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
def cached_panel(ticker: str, day: str, snapshot: dict):
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

def page_analysis():
    st.title("📊 AI 股票分析室")
    st.caption("支持 🇲🇾 大马（MAYBANK / 1155）· 🇺🇸 美股（AAPL）· 🇮🇩 印尼（BBCA）")

    with st.form("search"):
        c1, c2 = st.columns([4, 1])
        text = c1.text_input("股票代码或名称", placeholder="例如 MAYBANK、NVDA、BBCA",
                             label_visibility="collapsed")
        go_btn = c2.form_submit_button("分析", width="stretch", type="primary")
    if go_btn and text.strip():
        st.session_state.query = text.strip()
    query = st.session_state.get("query")
    if not query:
        st.info("输入股票代码开始分析。常用名称：MAYBANK、CIMB、TENAGA、IHH、BBCA、TLKM、AAPL、NVDA")
        return

    with st.spinner(f"正在抓取 {query.upper()} 的数据…"):
        try:
            r = cached_analysis(query)
        except Exception as e:
            st.error(f"❌ {e}")
            return
    ticker, tech, fund, news = r["ticker"], r["tech"], r["fund"], r["news"]
    cur = fund["currency"]

    st.subheader(f"{fund['name']}（{ticker} · {A.market_of(ticker)}）")
    st.button("🏢 认识这家公司（业务、成绩、管理层、评级）", on_click=goto_company, args=(ticker,))
    m = st.columns(5)
    m[0].metric("股价", f"{cur} {fmt(tech['price'])}", f"{tech['change_1d']:+.2f}% 今日")
    m[1].metric("1 年涨跌", fmt(tech["change_1y"], 1, "%"))
    m[2].metric("本益比 P/E", fmt(fund["pe"], 1))
    m[3].metric("股息率", fmt(fund["dividend_yield"], 2, "%"))
    m[4].metric("技术面", tech["verdict"], f"分数 {tech['score']:+d}", delta_color="off")

    tab_panel, tab_chart, tab_detail, tab_news = st.tabs(
        ["🎙 基金经理圆桌", "📈 走势图", "📋 技术 & 基本面", "📰 新闻"])

    with tab_chart:
        st.plotly_chart(price_chart(r["df"], ticker), width="stretch")

    with tab_detail:
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

    with tab_news:
        if not news["items"]:
            st.write("没有找到近期新闻（大马/印尼中小型股常见）。")
        else:
            st.write(f"**整体情绪：{news['mood']}**（平均 {news['avg']:+.2f}）")
            for i in news["items"]:
                icon = "🟢" if i["score"] > 0.15 else "🔴" if i["score"] < -0.15 else "⚪"
                st.markdown(f"{icon} [{i['title']}]({i['link']})" if i["link"]
                            else f"{icon} {i['title']}")

    with tab_panel:
        err = M.check_setup()
        if err:
            st.error(err)
            return
        key = f"panel_{ticker}"
        if not st.session_state.get(key):
            st.write("5 位不同风格的 AI 基金经理会根据上面的数据，各自给出评级、看法和前景。")
            if st.button("🎙 开始圆桌讨论", type="primary"):
                st.session_state[key] = True
                st.rerun()
            return
        with st.spinner("5 位基金经理正在独立分析…（约 10-30 秒）"):
            opinions, summary = cached_panel(ticker, str(date.today()), r["snapshot"])

        votes = pd.Series([o["rating"] or "未表态" for o in opinions]).value_counts()
        st.markdown("**🗳 投票：** " + "　".join(f"{k} × {v}" for k, v in votes.items()))

        for start in range(0, len(opinions), 3):  # 每行 3 张卡片
            cols = st.columns(3)
            for col, o in zip(cols, opinions[start:start + 3]):
                with col.container(border=True):
                    color = RATING_COLOR.get(o["rating"], "#94a3b8")
                    body = (o["text"].split("\n", 1)[1] if o["text"].startswith("【评级】")
                            and "\n" in o["text"] else o["text"])
                    st.markdown(
                        f"<div style='font-size:1.25rem;font-weight:700'>{o['emoji']} {o['name']}</div>"
                        f"<div style='opacity:.65;font-size:.85rem;margin-bottom:6px'>{o['title']}</div>"
                        f"<span style='background:{color};color:white;padding:2px 12px;"
                        f"border-radius:999px;font-weight:600'>{o['rating'] or '未表态'}</span>"
                        f"<div style='margin-top:10px;line-height:1.7'>{sections_html(body)}</div>",
                        unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("### 👔 投资委员会主席总结")
            summary_body = summary.split("\n\n", 1)[1] if summary.startswith("🗳") else summary
            st.markdown(f"<div style='line-height:1.8'>{sections_html(summary_body)}</div>",
                        unsafe_allow_html=True)
        st.caption(f"AI 供应商：{M.PROVIDER} · {M.MODEL}。圆桌结果每只股票每天只生成一次以节省额度。"
                   "以上为 AI 模拟观点，仅供学习参考，不构成投资建议。")


# ---------------------------------------------------------------------------
# 页面：投资组合（存在浏览器 session，可下载/上传 CSV 保存）
# ---------------------------------------------------------------------------

def page_portfolio():
    st.title("💼 我的投资组合")
    st.caption("网站不会帮你永久保存资料：用完记得按「下载」存成 CSV，下次再上传。")

    if "pf" not in st.session_state:
        st.session_state.pf = pd.DataFrame(
            {"代码": ["1155.KL"], "数量": [1000.0], "平均成本": [9.80]})

    up = st.file_uploader("上传之前下载的 CSV", type="csv")
    if up is not None and st.session_state.get("pf_loaded") != up.name:
        st.session_state.pf = pd.read_csv(up)
        st.session_state.pf_loaded = up.name

    pf = st.data_editor(st.session_state.pf, num_rows="dynamic", width="stretch",
                        column_config={"数量": st.column_config.NumberColumn(min_value=0),
                                       "平均成本": st.column_config.NumberColumn(format="%.4f")})
    st.session_state.pf = pf

    c1, c2 = st.columns(2)
    c1.download_button("⬇️ 下载 CSV", pf.to_csv(index=False).encode("utf-8-sig"),
                       "my_portfolio.csv", "text/csv", width="stretch")
    if not c2.button("🔄 计算实时盈亏", type="primary", width="stretch"):
        return

    rows = []
    with st.spinner("正在获取最新股价…"):
        for _, row in pf.dropna().iterrows():
            t = A.normalize_ticker(str(row["代码"]))
            try:
                price = float(A.get_history(t, "5d")["Close"].iloc[-1])
            except Exception:
                price = None
            qty, cost = float(row["数量"]), float(row["平均成本"])
            value = qty * price if price else None
            rows.append({"代码": t, "货币": {"KL": "MYR", "JK": "IDR"}.get(t[-2:], "USD"),
                         "数量": qty, "成本": cost, "现价": price,
                         "市值": value, "盈亏": value - qty * cost if price else None,
                         "盈亏%": (price / cost - 1) * 100 if price and cost else None})
    res = pd.DataFrame(rows)
    st.dataframe(res.style.format(precision=2, na_rep="无").map(
        lambda v: f"color: {'#16a34a' if v > 0 else '#dc2626'}" if isinstance(v, float) and v == v else "",
        subset=["盈亏", "盈亏%"]), width="stretch", hide_index=True)
    for cur, g in res.dropna().groupby("货币"):
        inv, val = (g["数量"] * g["成本"]).sum(), g["市值"].sum()
        st.metric(f"{cur} 合计市值", f"{val:,.2f}", f"{val - inv:+,.2f}（{(val / inv - 1) * 100:+.1f}%）")


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


def goto_analysis(ticker: str):
    st.session_state.query = ticker
    st.session_state.nav = "📊 个股分析"


def goto_company(ticker: str):
    st.session_state.company_query = ticker
    st.session_state.nav = "🏢 认识公司"


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
                b1, b2 = st.columns(2)
                b1.button("🏢 认识公司", key=f"{kp}_co_{w['ticker']}", on_click=goto_company,
                          args=(w["ticker"],), width="stretch")
                b2.button("📊 深入分析", key=f"{kp}_go_{w['ticker']}", on_click=goto_analysis,
                          args=(w["ticker"],), width="stretch")

    def table(rows, title):
        df = pd.DataFrame(rows)[["name", "ticker", "price", "change_pct", "vol_ratio", "turnover"]]
        df.columns = ["名称", "代码", "股价", "涨跌%", "成交量倍数", f"成交额 ({cur})"]
        st.markdown(f"**{title}**")
        key = f"{kp}_tbl_{title}"

        def on_pick():  # 点表格某一行 → 跳到「认识公司」
            sel = st.session_state[key].selection.rows
            if sel:
                goto_company(rows[sel[0]]["ticker"])

        st.dataframe(df.style.format({"股价": "{:,.2f}", "涨跌%": "{:+.2f}", "成交量倍数": "{:.1f}",
                                      f"成交额 ({cur})": "{:,.0f}"}).map(
            lambda v: f"color:{'#16a34a' if v > 0 else '#dc2626'}", subset=["涨跌%"]),
            hide_index=True, width="stretch", key=key,
            on_select=on_pick, selection_mode="single-row")

    st.caption("👆 点表格里任何一行，就能认识那家公司")
    c1, c2 = st.columns(2)
    with c1:
        table(r["gainers"], "📈 涨幅最大")
        table(r["volume_surge"], "🔊 成交量异常放大")
    with c2:
        table(r["losers"], "📉 跌幅最大")
        table(r["turnover_top"], "💵 成交额最高")


def page_focus():
    st.title("📅 每日焦点")
    st.caption("每个交易日的开市、午间、收市都会自动生成报告，只看大型蓝筹股，剔除低价和成交冷清的投机股。")
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


async def _company_ai(p: dict):
    M.reset_clients()
    return await C.ai_profile(p)


@st.cache_data(ttl=7 * 86400, show_spinner=False)
def cached_company_ai(ticker: str, _p: dict):
    # 出错会 raise → 不会被缓存，下次可以重试
    return asyncio.run(_company_ai(_p))


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


def page_company():
    st.title("🏢 认识公司")
    st.caption("输入或点击任何股票代码，AI 研究员会整理这家公司的业务、营业模式、近几年成绩和管理层，"
               "并给出 弱 → 强 五级评级。")
    with st.form("company_search"):
        c1, c2 = st.columns([4, 1])
        text = c1.text_input("代码", placeholder="例如 MAYBANK、TENAGA、NVDA、BBCA",
                             label_visibility="collapsed")
        btn = c2.form_submit_button("认识它", type="primary", width="stretch")
    if btn and text.strip():
        st.session_state.company_query = text.strip()
    q = st.session_state.get("company_query")
    if not q:
        st.info("试试看：MAYBANK、PBBANK、TENAGA、IHH、BBCA、TLKM、AAPL、COST")
        return

    with st.spinner(f"正在收集 {q.upper()} 的公司资料和财报…"):
        try:
            p = cached_company(q)
        except Exception as e:
            st.error(f"❌ {e}")
            return

    ai, ai_err = None, None
    if M.check_setup():
        ai_err = "还没设置 AI key，下面只显示财务体检（数字评分）。"
    else:
        with st.spinner("AI 研究员正在阅读资料、写报告…（约 20-40 秒）"):
            try:
                ai = cached_company_ai(p["ticker"], p)
            except Exception as e:
                ai_err = f"AI 研究员暂时无法工作：{e}"
    sec = ai["sections"] if ai else {}
    lv = ai["levels"] if ai else {}
    sc = p["scores"]

    # --- 标题 ---
    st.subheader(f"{p['name']}（{p['ticker']} · {p['market']}）")
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

    # --- 业务 & 模式 ---
    if sec:
        c1, c2 = st.columns(2)
        with c1.container(border=True):
            st.markdown("#### 🏭 主要业务")
            st.markdown(md(sec.get("主要业务", "—")))
        with c2.container(border=True):
            st.markdown("#### 💰 营业模式")
            st.markdown(md(sec.get("营业模式", "—")))

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

    st.button("📊 看这只股票的走势 + 基金经理圆桌 →", on_click=goto_analysis, args=(p["ticker"],))
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
        b1, b2 = st.columns(2)
        b1.button("🏢 认识公司", key=f"{kp}_co_{x['ticker']}", on_click=goto_company,
                  args=(x["ticker"],), width="stretch")
        b2.button("📊 深入分析", key=f"{kp}_an_{x['ticker']}", on_click=goto_analysis,
                  args=(x["ticker"],), width="stretch")


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
        b1, b2 = st.columns(2)
        b1.button("🏢 认识公司", on_click=goto_company, args=(t,), width="stretch", key="klci_co")
        b2.button("📊 深入分析", on_click=goto_analysis, args=(t,), width="stretch", key="klci_an")

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
        text=text, texttemplate="%{text}", colorscale=[[0, "#D9483B"], [0.5, "#F2F2F2"], [1, "#13996A"]],
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
                                     line=dict(color="#22305A", width=2)))
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
                sel = st.session_state[tkey].selection.rows
                if sel:
                    goto_company(rows[sel[0]]["ticker"])

            st.dataframe(show.style.format({"股价": "{:,.2f}", "权重%": "{:.1f}", "1 日%": "{:+.2f}", "1 个月%": "{:+.1f}",
                                            "1 年%": "{:+.1f}", "P/E": "{:.1f}", "股息率%": "{:.1f}", "ROE%": "{:.1f}"},
                                           na_rep="—").map(
                lambda v: f"color:{'#16a34a' if v > 0 else '#dc2626'}" if isinstance(v, (int, float)) and v == v else "",
                subset=["1 日%", "1 个月%", "1 年%"]),
                hide_index=True, width="stretch", key=tkey, on_select=on_pick, selection_mode="single-row")
            st.caption("👆 点任何一行就能认识那家公司。" + sec["note"])

            opts = {f"{m['name']}（{m['ticker']}）": m["ticker"] for m in g["members"]}
            chosen = st.multiselect("⚖️ 勾选 2–3 家来对比", list(opts), max_selections=3, key=f"cmp_{key}_{g['name']}")
            if st.button("对比这几家", key=f"cmpbtn_{key}_{g['name']}", disabled=len(chosen) < 2, type="primary"):
                goto_compare([opts[c] for c in chosen])
                st.rerun()


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
def cached_compare_ai(tickers: tuple):
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
            if st.button("认识公司", key=f"cmpco_{x['ticker']}"):
                goto_company(x["ticker"])
                st.rerun()
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
            ai = cached_compare_ai(tuple(names))
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
        fig.add_trace(go.Bar(x=tr["periods"], y=tr["revenue"], name="营收", marker_color="#93a5cf"))
        fig.add_trace(go.Bar(x=tr["periods"], y=tr["net"], name="净利", marker_color="#22305A"))
        fig.update_layout(height=260, barmode="group", margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=1.15))
        st.plotly_chart(fig, width="stretch", key=f"qtrend_{key}")
    if x.get("ai"):
        st.info("🧠 " + x["ai"])
    b1, b2 = st.columns(2)
    if b1.button("认识这家公司", key=f"qco_{key}"):
        goto_company(x["ticker"])
        st.rerun()
    if b2.button("跟别家对比", key=f"qcmp_{key}"):
        goto_compare([x["ticker"]])
        st.rerun()


@st.cache_data(ttl=3600, show_spinner=False)
def cached_quarter(text: str):
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
                show_quarter(cached_quarter(q), "live")
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
            b1, b2 = c1.columns(2)
            b1.button("🏢 认识公司", key=f"wl_co_{x['ticker']}", on_click=goto_company, args=(x["ticker"],))
            b2.button("📊 深入分析", key=f"wl_an_{x['ticker']}", on_click=goto_analysis, args=(x["ticker"],))


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

PAGES = {"📅 每日焦点": page_focus, "🧩 板块": page_sectors, "🔍 选股雷达": page_radar,
         "⚖️ 股票对比": page_compare, "📑 季度报告": page_quarterly, "⭐ 自选股": page_watchlist, "🏆 KLCI 50 观察": page_klci, "📈 成绩单": page_track,
         "📰 周报": page_weekly, "📊 个股分析": page_analysis, "🏢 认识公司": page_company,
         "💼 投资组合": page_portfolio, "🩺 系统状态": page_health}

if check_password():
    # 手机 app 的按钮会带网址参数打开：?company=4065.KL 或 ?analyze=4065.KL
    qp = st.query_params
    if not st.session_state.get("_qp_done"):
        if qp.get("company"):
            st.session_state.company_query = qp["company"]
            st.session_state.nav = "🏢 认识公司"
        elif qp.get("compare"):
            st.session_state.compare_query = [t for t in qp["compare"].split(",") if t][:3]
            st.session_state.nav = "⚖️ 股票对比"
        elif qp.get("quarter"):
            st.session_state.quarter_query = qp["quarter"]
            st.session_state.nav = "📑 季度报告"
        elif qp.get("analyze"):
            st.session_state.query = qp["analyze"]
            st.session_state.nav = "📊 个股分析"
        elif qp.get("page") in ("focus", "radar", "klci", "sectors", "track", "weekly", "watch", "quarterly", "compare"):
            st.session_state.nav = {"focus": "📅 每日焦点", "radar": "🔍 选股雷达", "klci": "🏆 KLCI 50 观察",
                                    "sectors": "🧩 板块", "track": "📈 成绩单", "weekly": "📰 周报",
                                    "watch": "⭐ 自选股", "quarterly": "📑 季度报告",
                                    "compare": "⚖️ 股票对比"}[qp["page"]]
        st.session_state._qp_done = True
    page = st.sidebar.radio("功能", list(PAGES), key="nav")
    st.sidebar.markdown("---")
    st.sidebar.caption("圆桌嘉宾\n\n" + "\n\n".join(
        f"{m['emoji']} {m['name']}｜{m['title']}" for m in M.MANAGERS))
    st.sidebar.caption("仅供学习参考，不构成投资建议。")
    PAGES[page]()
