"""
ui.py - 网站的外观（颜色、字体、左边功能列表、卡片）

跟手机 app 用同一套颜色：深靛蓝底 + 金色重点 + 绿涨红跌。
想改颜色：改下面 COLORS，以及 .streamlit/config.toml 的 [theme]。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

COLORS = {
    "bg": "#121A2E", "panel": "#1B2540", "panel2": "#222D4D", "line": "#2C3756",
    "ink": "#E6EAF2", "ink2": "#A3ADC2", "gold": "#C8A23A", "indigo": "#22305A",
    "up": "#2BC48A", "down": "#F06A5D", "accent": "#8EA2F0",
}

# 左边功能列表的分组：(第几项开始, 组名)。PAGES 的顺序改了，这里也要跟着改。
NAV_GROUPS = [(1, "市场"), (5, "研究个股"), (9, "我的"), (14, "系统")]


def _css() -> str:
    c = COLORS
    groups = "\n".join(
        f"""section[data-testid="stSidebar"] [role="radiogroup"] > div:nth-child({i})::before {{
              content: "{name}"; }}""" for i, name in NAV_GROUPS)
    group_gaps = ", ".join(
        f'section[data-testid="stSidebar"] [role="radiogroup"] > div:nth-child({i})' for i, _ in NAV_GROUPS)
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Noto+Sans+SC:wght@400;500;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select {{
  font-family: "Noto Sans SC", system-ui, -apple-system, "PingFang SC", sans-serif;
}}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1240px; }}
header[data-testid="stHeader"] {{ background: transparent; }}

/* ---------- 标题 ---------- */
h1 {{ font-weight: 800 !important; letter-spacing: .5px; font-size: 2.15rem !important; padding-bottom: .2rem !important; }}
h1::after {{ content: ""; display: block; width: 56px; height: 4px; border-radius: 2px;
             background: {c['gold']}; margin-top: .55rem; }}
h2, h3, h4, h5 {{ font-weight: 700 !important; }}
[data-testid="stCaptionContainer"] {{ color: {c['ink2']}; font-size: .92rem; }}

/* ---------- 左边：品牌 + 大按钮功能列表 ---------- */
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, #1A2547 0%, #141C35 100%);
  border-right: 1px solid {c['line']};
}}
section[data-testid="stSidebar"] > div {{ padding-top: .6rem; }}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{ display: none; }}
section[data-testid="stSidebar"] .stElementContainer:has(.stRadio),
section[data-testid="stSidebar"] .stRadio, section[data-testid="stSidebar"] [data-testid="stRadio"] {{ width: 100% !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; display: flex; flex-direction: column;
  align-items: stretch !important; width: 100% !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div {{ position: relative; width: 100%; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label {{
  display: flex !important; width: 100% !important; max-width: none !important; box-sizing: border-box;
  margin: 0; padding: 9px 14px 9px 16px; border-radius: 12px; transition: background .15s; cursor: pointer;
}}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label:hover {{ background: rgba(142, 162, 240, .12); }}
section[data-testid="stSidebar"] [role="radiogroup"] > div[data-selected="true"] > label {{
  background: linear-gradient(90deg, rgba(200,162,58,.30), rgba(200,162,58,.06));
  box-shadow: inset 4px 0 0 {c['gold']};
}}
section[data-testid="stSidebar"] [role="radiogroup"] > div[data-selected="true"] > label p {{ color: #fff !important; }}
/* 藏起小圆圈 */
section[data-testid="stSidebar"] [role="radiogroup"] > div > label > div > div:first-child:not([data-testid]) {{ display: none; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label > div {{ flex: 1; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label p {{
  font-size: 1.16rem !important; font-weight: 600; color: {c['ink']}; letter-spacing: .5px; line-height: 1.4;
}}
/* 分组标题 */
{group_gaps} {{ margin-top: 26px; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div:nth-child(1) {{ margin-top: 34px; }}
{groups}
section[data-testid="stSidebar"] [role="radiogroup"] > div::before {{
  position: absolute; left: 8px; top: -21px; font-size: .76rem; font-weight: 700;
  letter-spacing: 2px; color: {c['gold']}; pointer-events: none;
}}
.brand {{ display: flex; align-items: center; gap: 12px; padding: 6px 4px 14px;
          border-bottom: 1px solid {c['line']}; margin-bottom: 4px; }}
.brand-logo {{ width: 46px; height: 46px; border-radius: 13px; display: grid; place-items: center;
               background: linear-gradient(135deg, {c['gold']}, #E9CF7A); font-size: 24px;
               box-shadow: 0 4px 14px rgba(200,162,58,.35); }}
.brand-name {{ font-weight: 800; font-size: 1.22rem; color: #fff; line-height: 1.2; }}
.brand-sub {{ font-size: .8rem; color: {c['ink2']}; margin-top: 2px; }}
.mkt {{ display: grid; grid-template-columns: 1fr auto; gap: 4px 8px; font-size: .86rem;
        color: {c['ink2']}; padding: 10px 6px 2px; }}
.mkt b {{ font-weight: 600; }}
.dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }}
.dot.open {{ background: {c['up']}; box-shadow: 0 0 0 3px rgba(43,196,138,.2); }}
.dot.closed {{ background: #5B6478; }}
.guests {{ font-size: .82rem; color: {c['ink2']}; line-height: 1.9; padding: 0 6px; }}

/* ---------- 卡片：数字、表格、框框 ---------- */
[data-testid="stMetric"] {{
  background: {c['panel']}; border: 1px solid {c['line']}; border-radius: 14px; padding: 14px 16px;
}}
[data-testid="stMetricValue"] {{ font-family: "Barlow Semi Condensed", sans-serif; font-weight: 700; }}
[data-testid="stMetricLabel"] p {{ color: {c['ink2']}; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 16px !important; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) {{
  background: rgba(27, 37, 64, .55);
}}
[data-testid="stDataFrame"], [data-testid="stTable"] {{
  border-radius: 14px; overflow: hidden; border: 1px solid {c['line']};
}}
[data-testid="stExpander"] details {{ border-radius: 14px; border-color: {c['line']}; background: {c['panel']}; }}
[data-testid="stAlert"] {{ border-radius: 14px; }}
.js-plotly-plot, [data-testid="stPlotlyChart"] {{ border-radius: 14px; overflow: hidden; }}

/* ---------- 按钮、输入框、分页 ---------- */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button, .stLinkButton > a {{
  border-radius: 10px; font-weight: 600; padding: .45rem 1rem; transition: transform .1s, box-shadow .15s;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover {{ transform: translateY(-1px); }}
button[kind="primary"], button[kind="primaryFormSubmit"] {{
  background: linear-gradient(135deg, {c['gold']}, #DDB955) !important; border: 0 !important;
  color: #1D2433 !important; box-shadow: 0 3px 12px rgba(200,162,58,.3);
}}
button[kind="primary"] p, button[kind="primaryFormSubmit"] p {{ color: #1D2433 !important; font-weight: 700; }}
.stTextInput input, .stNumberInput input, div[data-baseweb="select"] > div {{ border-radius: 10px !important; }}
[data-testid="stTabs"] [role="tablist"] {{ gap: 8px; border-bottom: 0 !important; flex-wrap: wrap; }}
[data-testid="stTab"] {{
  background: {c['panel']}; border-radius: 999px; padding: 7px 18px !important; height: auto;
  border: 1px solid {c['line']}; max-width: none !important;
}}
[data-testid="stTab"] p {{ font-size: 1rem; font-weight: 600; white-space: nowrap; }}
[data-testid="stTab"][aria-selected="true"] {{ background: {c['gold']} !important; border-color: {c['gold']}; }}
[data-testid="stTab"][aria-selected="true"] p {{ color: #1D2433 !important; }}
[data-testid="stTabs"] .react-aria-SelectionIndicator {{ display: none !important; }}
@media (max-width: 640px) {{
  h1 {{ font-size: 1.7rem !important; }}
  [data-testid="stTab"] {{ padding: 5px 12px !important; }}
  [data-testid="stTab"] p {{ font-size: .92rem; }}
}}
hr {{ border-color: {c['line']} !important; }}
</style>"""


def inject():
    st.markdown(_css(), unsafe_allow_html=True)


def _market_status() -> list[tuple[str, bool, str]]:
    import scanner as S
    out = []
    for key, m in S.MARKETS.items():
        now = datetime.now(ZoneInfo(m.tz))
        sessions = m.trading.get(now.weekday(), [])
        is_open = any(a <= now.time() <= b for a, b in sessions)
        out.append((m.name.split(" ", 1)[1] if " " in m.name else m.name, is_open, now.strftime("%H:%M")))
    return out


def sidebar_brand():
    rows = "".join(
        f"<span><i class='dot {'open' if o else 'closed'}'></i>{name}</span><b>{'交易中' if o else '已收市'} · {t}</b>"
        for name, o, t in _market_status())
    st.sidebar.markdown(f"""
      <div class="brand"><div class="brand-logo">📊</div>
        <div><div class="brand-name">AI 股票分析室</div>
             <div class="brand-sub">大马 · 印尼 · 美股</div></div></div>
      <div class="mkt">{rows}</div>""", unsafe_allow_html=True)


def sidebar_footer(managers):
    st.sidebar.markdown("---")
    st.sidebar.markdown("<div class='guests'><b style='color:#C8A23A'>圆桌嘉宾</b><br>" + "<br>".join(
        f"{m['emoji']} {m['name']}｜{m['title']}" for m in managers) +
        "<br><br>仅供学习参考，不构成投资建议。</div>", unsafe_allow_html=True)
