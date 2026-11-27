"""
ui.py - 网站的外观（颜色、字体、左边功能列表、卡片）

有 6 套主题（「🎨 外观设定」页面可以换），也可以自选重点颜色、字体大小、留白、圆角、背景。
设定存在网址里（?th=ocean&fs=大…），加书签就会记得。想加新主题：在 THEMES 加一套。
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

# ---------------------------------------------------------------------------
# 主题：每套颜色（全部是深色底，图表和表格看起来才一致）
# ---------------------------------------------------------------------------
THEMES = {
    "navy": {"name": "🌙 深蓝金", "bg": "#121A2E", "side1": "#1A2547", "side2": "#141C35", "panel": "#1B2540",
             "line": "#2C3756", "ink": "#E6EAF2", "ink2": "#A3ADC2", "accent": "#C8A23A", "accent2": "#E9CF7A",
             "soft": "#8EA2F0", "up": "#2BC48A", "down": "#F06A5D"},
    "midnight": {"name": "🌌 午夜紫", "bg": "#120F24", "side1": "#1E1838", "side2": "#14112A", "panel": "#1D1838",
                 "line": "#332B57", "ink": "#ECE9FB", "ink2": "#ABA3CC", "accent": "#8B7CFF", "accent2": "#5FD4F5",
                 "soft": "#C4B8FF", "up": "#34D399", "down": "#FB7185"},
    "emerald": {"name": "🌲 森林绿", "bg": "#0D1A17", "side1": "#13271F", "side2": "#0E1C18", "panel": "#15281F",
                "line": "#24402F", "ink": "#E4F2EA", "ink2": "#9EBDAA", "accent": "#3DDC97", "accent2": "#B6F09C",
                "soft": "#7FE0B6", "up": "#3DDC97", "down": "#FF7A6B"},
    "graphite": {"name": "🖤 石墨橙", "bg": "#121212", "side1": "#1C1C1E", "side2": "#141414", "panel": "#1E1E21",
                 "line": "#303034", "ink": "#EDEDED", "ink2": "#A8A8AD", "accent": "#FF8A3D", "accent2": "#FFC36B",
                 "soft": "#FFB07A", "up": "#30C48D", "down": "#FF5A5F"},
    "ocean": {"name": "🌊 海洋蓝", "bg": "#0B1824", "side1": "#0F2536", "side2": "#0B1A27", "panel": "#12283A",
              "line": "#1F3D54", "ink": "#E3F1FA", "ink2": "#98B6C9", "accent": "#2EC4D6", "accent2": "#FF8C69",
              "soft": "#7ADCEA", "up": "#2ED39C", "down": "#FF6B6B"},
    "sakura": {"name": "🌸 樱花夜", "bg": "#1A1220", "side1": "#2A1A30", "side2": "#1C1323", "panel": "#291B30",
               "line": "#432C4B", "ink": "#F6EAF2", "ink2": "#C3A7BC", "accent": "#FF7EB6", "accent2": "#FFC2DC",
               "soft": "#F5A9CF", "up": "#3DD6A0", "down": "#FF6F7F"},
}
FONT_SCALE = {"小": 0.92, "标准": 1.0, "大": 1.1, "特大": 1.2}
DENSITY = {"舒适": 1.0, "紧凑": 0.72}
RADIUS = {"圆润": 1.0, "方正": 0.35}
BACKDROPS = ["光晕", "纯色", "渐层"]
DEFAULTS = {"th": "navy", "ac": "", "fs": "标准", "dn": "舒适", "rd": "圆润", "bd": "光晕", "home": ""}

COLORS = dict(THEMES["navy"])     # 其他地方（图表）也会用到：跟着主题变


def _rgb(hexc: str) -> tuple[int, int, int]:
    h = hexc.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgba(hexc: str, a: float) -> str:
    r, g, b = _rgb(hexc)
    return f"rgba({r},{g},{b},{a})"


def on_color(hexc: str) -> str:
    """按钮上的字：浅色按钮用深字，深色按钮用白字。"""
    r, g, b = _rgb(hexc)
    return "#141821" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


def prefs() -> dict:
    """外观设定：先看这次的设定，没有就看网址（?th=ocean&fs=大…，加书签就会记得）。"""
    if "ui_prefs" not in st.session_state:
        qp = st.query_params
        p = {k: qp.get(k, v) for k, v in DEFAULTS.items()}
        if p["th"] not in THEMES:
            p["th"] = "navy"
        if p["ac"] and not p["ac"].startswith("#"):
            p["ac"] = "#" + p["ac"]
        st.session_state.ui_prefs = p
    return st.session_state.ui_prefs


def save_prefs(p: dict):
    st.session_state.ui_prefs = p
    for k, v in p.items():                       # 只把跟默认不一样的写进网址
        val = v.lstrip("#") if k == "ac" else v
        if v and v != DEFAULTS[k]:
            st.query_params[k] = val
        elif k in st.query_params:
            del st.query_params[k]


def palette(p: dict | None = None) -> dict:
    p = p or prefs()
    c = dict(THEMES.get(p["th"], THEMES["navy"]))
    if p.get("ac"):
        c["accent"] = p["ac"]
    COLORS.clear()
    COLORS.update(c)
    return c


# 左边功能列表的分组：(第几项开始, 组名)。PAGES 的顺序改了，这里也要跟着改。
NAV_GROUPS = [(1, "市场"), (7, "研究个股"), (10, "我的"), (15, "系统")]


def _css() -> str:
    p = prefs()
    c = palette(p)
    fs, dn, rd = FONT_SCALE.get(p["fs"], 1.0), DENSITY.get(p["dn"], 1.0), RADIUS.get(p["rd"], 1.0)
    R = lambda px: f"{max(2, round(px * rd))}px"          # 圆角
    P = lambda rem: f"{rem * dn:.2f}rem"                  # 留白
    acc, acc2, on = c["accent"], c["accent2"], on_color(c["accent"])
    if p["bd"] == "光晕":
        backdrop = (f"radial-gradient(900px 500px at 85% -10%, {rgba(acc, .16)}, transparent 60%),"
                    f"radial-gradient(700px 500px at -10% 110%, {rgba(c['soft'], .10)}, transparent 60%), {c['bg']}")
    elif p["bd"] == "渐层":
        backdrop = f"linear-gradient(160deg, {c['side1']} 0%, {c['bg']} 45%, {c['bg']} 100%)"
    else:
        backdrop = c["bg"]
    groups = "\n".join(
        f"""section[data-testid="stSidebar"] [role="radiogroup"] > div:nth-child({i})::before {{
              content: "{name}"; }}""" for i, name in NAV_GROUPS)
    group_gaps = ", ".join(
        f'section[data-testid="stSidebar"] [role="radiogroup"] > div:nth-child({i})' for i, _ in NAV_GROUPS)
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700&family=Noto+Sans+SC:wght@400;500;700;800&display=swap');

html {{ font-size: {16 * fs:.1f}px; }}
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea, select {{
  font-family: "Noto Sans SC", system-ui, -apple-system, "PingFang SC", sans-serif;
}}
[data-testid="stApp"] {{ background: {backdrop} !important; background-attachment: fixed !important; color: {c['ink']}; }}
[data-testid="stMain"] p, [data-testid="stMain"] li {{ color: {c['ink']}; }}
.block-container {{ padding-top: {P(2.2)}; padding-bottom: 4rem; max-width: 1240px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
a {{ color: {c['soft']}; }}

/* ---------- 标题 ---------- */
h1 {{ font-weight: 800 !important; letter-spacing: .5px; font-size: 2.15rem !important; padding-bottom: .2rem !important; }}
h1::after {{ content: ""; display: block; width: 64px; height: 4px; border-radius: 2px;
             background: linear-gradient(90deg, {acc}, {acc2}); margin-top: .55rem; }}
h2, h3, h4, h5 {{ font-weight: 700 !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {c['ink2']} !important; font-size: .92rem; }}

/* ---------- 左边：品牌 + 大按钮功能列表 ---------- */
section[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {c['side1']} 0%, {c['side2']} 100%) !important;
  border-right: 1px solid {c['line']};
}}
section[data-testid="stSidebar"] > div {{ padding-top: .6rem; }}
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] {{ display: none; }}
section[data-testid="stSidebar"] .stElementContainer:has(.stRadio),
section[data-testid="stSidebar"] .stRadio, section[data-testid="stSidebar"] [data-testid="stRadio"] {{ width: 100% !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; display: flex; flex-direction: column;
  align-items: stretch !important; width: 100% !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div {{ position: relative; width: 100%; }}
/* 中 / EN 切换（segmented control 也是 radiogroup，不要套用功能列表的直排样式） */
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] [role="radiogroup"] {{ flex-direction: row !important;
  gap: 0 !important; }}
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] [role="radiogroup"] > button {{ flex: 1; min-height: 32px; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label {{
  display: flex !important; width: 100% !important; max-width: none !important; box-sizing: border-box;
  margin: 0; padding: {9 * dn:.0f}px 14px {9 * dn:.0f}px 16px; border-radius: {R(12)}; transition: background .15s, transform .15s; cursor: pointer;
}}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label:hover {{ background: {rgba(c['soft'], .12)}; transform: translateX(2px); }}
section[data-testid="stSidebar"] [role="radiogroup"] > div[data-selected="true"] > label {{
  background: linear-gradient(90deg, {rgba(acc, .32)}, {rgba(acc, .05)});
  box-shadow: inset 4px 0 0 {acc};
}}
section[data-testid="stSidebar"] [role="radiogroup"] > div[data-selected="true"] > label p {{ color: #fff !important; }}
/* 藏起小圆圈 */
section[data-testid="stSidebar"] [role="radiogroup"] > div > label > div > div:first-child:not([data-testid]) {{ display: none; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label > div {{ flex: 1; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div > label p {{
  font-size: 1.16rem !important; font-weight: 600; color: {c['ink']}; letter-spacing: .5px; line-height: 1.4;
}}
/* 分组标题 */
{group_gaps} {{ margin-top: {26 * dn:.0f}px; }}
section[data-testid="stSidebar"] [role="radiogroup"] > div:nth-child(1) {{ margin-top: 34px; }}
{groups}
section[data-testid="stSidebar"] [role="radiogroup"] > div::before {{
  position: absolute; left: 8px; top: -21px; font-size: .76rem; font-weight: 700;
  letter-spacing: 2px; color: {acc}; pointer-events: none;
}}
.brand {{ display: flex; align-items: center; gap: 12px; padding: 6px 4px 14px;
          border-bottom: 1px solid {c['line']}; margin-bottom: 4px; }}
.brand-logo {{ width: 46px; height: 46px; border-radius: {R(13)}; display: grid; place-items: center;
               background: linear-gradient(135deg, {acc}, {acc2}); font-size: 24px;
               box-shadow: 0 4px 16px {rgba(acc, .4)}; }}
.brand-name {{ font-weight: 800; font-size: 1.22rem; color: #fff; line-height: 1.2; }}
.brand-sub {{ font-size: .8rem; color: {c['ink2']}; margin-top: 2px; }}
.mkt {{ display: grid; grid-template-columns: 1fr auto; gap: 4px 8px; font-size: .86rem;
        color: {c['ink2']}; padding: 10px 6px 2px; }}
.mkt b {{ font-weight: 600; }}
.dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }}
.dot.open {{ background: {c['up']}; box-shadow: 0 0 0 3px {rgba(c['up'], .22)}; }}
.dot.closed {{ background: #5B6478; }}
.guests {{ font-size: .82rem; color: {c['ink2']}; line-height: 1.9; padding: 0 6px; }}

/* ---------- 卡片：数字、表格、框框 ---------- */
[data-testid="stMetric"] {{
  background: linear-gradient(160deg, {rgba(c['panel'], .95)}, {rgba(c['panel'], .7)});
  border: 1px solid {c['line']}; border-radius: {R(16)}; padding: {P(.9)} {P(1)};
  box-shadow: 0 6px 18px rgba(0,0,0,.18); transition: transform .15s, border-color .15s;
}}
[data-testid="stMetric"]:hover {{ transform: translateY(-2px); border-color: {rgba(acc, .55)}; }}
[data-testid="stMetricValue"] {{ font-family: "Barlow Semi Condensed", sans-serif; font-weight: 700; }}
[data-testid="stMetricLabel"] p {{ color: {c['ink2']} !important; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: {R(18)} !important; border-color: {c['line']} !important; }}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]) {{
  background: {rgba(c['panel'], .55)}; backdrop-filter: blur(6px);
  box-shadow: 0 8px 24px rgba(0,0,0,.16); transition: border-color .2s;
}}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div[data-testid="stVerticalBlock"]):hover {{
  border-color: {rgba(acc, .45)} !important;
}}
[data-testid="stVerticalBlock"] {{ gap: {P(1)}; }}
[data-testid="stDataFrame"], [data-testid="stTable"] {{
  border-radius: {R(14)}; overflow: hidden; border: 1px solid {c['line']};
}}
[data-testid="stExpander"] details {{ border-radius: {R(14)}; border-color: {c['line']}; background: {rgba(c['panel'], .8)}; }}
[data-testid="stAlert"] {{ border-radius: {R(14)}; }}
.js-plotly-plot, [data-testid="stPlotlyChart"] {{ border-radius: {R(14)}; overflow: hidden; }}

/* ---------- 按钮、输入框、分页 ---------- */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button, .stLinkButton > a {{
  border-radius: {R(10)}; font-weight: 600; padding: {P(.45)} 1rem; transition: transform .1s, box-shadow .15s, border-color .15s;
  border-color: {c['line']};
}}
.stButton > button:hover, .stFormSubmitButton > button:hover {{ transform: translateY(-1px); border-color: {acc}; color: {acc}; }}
button[kind="primary"], button[kind="primaryFormSubmit"] {{
  background: linear-gradient(135deg, {acc}, {acc2}) !important; border: 0 !important;
  color: {on} !important; box-shadow: 0 4px 14px {rgba(acc, .35)};
}}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {{ box-shadow: 0 6px 20px {rgba(acc, .5)}; color: {on} !important; }}
button[kind="primary"] p, button[kind="primaryFormSubmit"] p {{ color: {on} !important; font-weight: 700; }}
.stTextInput input, .stNumberInput input, .stTextArea textarea, div[data-baseweb="select"] > div {{
  border-radius: {R(10)} !important; background: {c['panel']} !important; border-color: {c['line']} !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus {{ border-color: {acc} !important; }}
/* 输入框、下拉选单、普通按钮的底色跟着主题（不然会是固定的深蓝） */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"], [data-baseweb="select"] > div,
[data-baseweb="input"] input, [data-baseweb="base-input"] input, .stNumberInput button {{
  background-color: {c['panel']} !important; }}
[data-testid="stSelectbox"] [role="group"], [data-testid="stMultiSelect"] [role="group"],
[data-testid="stTextInput"] input, [data-testid="stTextInput"] [role="group"], [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea, [data-testid="stDateInput"] input {{
  background-color: {c['panel']} !important; border-color: {c['line']} !important; border-radius: {R(10)} !important; }}
.react-aria-Popover, .react-aria-ListBox, [role="listbox"] {{ background-color: {c['panel']} !important; }}
[role="option"][data-focused="true"], [role="option"][aria-selected="true"] {{ background-color: {rgba(acc, .18)} !important; }}
[data-baseweb="popover"] ul, [data-baseweb="popover"] [role="listbox"], [data-baseweb="menu"] {{
  background-color: {c['panel']} !important; }}
[data-baseweb="popover"] li[aria-selected="true"], [data-baseweb="popover"] li:hover {{ background-color: {rgba(acc, .18)} !important; }}
.stButton > button[kind="secondary"], .stDownloadButton > button, .stFormSubmitButton > button[kind="secondaryFormSubmit"],
[data-testid="stButtonGroup"] button, [data-testid="stPopover"] button, [data-testid="stFileUploaderDropzone"] {{
  background-color: {rgba(c['panel'], .85)} !important; }}
[data-testid="stExpander"] summary:hover {{ color: {acc}; }}
[data-testid="stTabs"] [role="tablist"] {{ gap: 8px; border-bottom: 0 !important; flex-wrap: wrap; }}
[data-testid="stTab"] {{
  background: {c['panel']}; border-radius: 999px; padding: {7 * dn:.0f}px 18px !important; height: auto;
  border: 1px solid {c['line']}; max-width: none !important;
}}
[data-testid="stTab"] p {{ font-size: 1rem; font-weight: 600; white-space: nowrap; }}
[data-testid="stTab"][aria-selected="true"] {{ background: {acc} !important; border-color: {acc}; }}
[data-testid="stTab"][aria-selected="true"] p {{ color: {on} !important; }}
[data-testid="stTabs"] .react-aria-SelectionIndicator {{ display: none !important; }}
/* 选项按钮（pills / segmented）选中的颜色 */
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[aria-pressed="true"],
[data-testid="stButtonGroup"] button[data-selected="true"] {{
  background: {rgba(acc, .18)} !important; border-color: {acc} !important; color: {acc} !important;
}}
[data-testid="stButtonGroup"] button[aria-checked="true"] p {{ color: {acc} !important; }}
[data-baseweb="slider"] [role="slider"] {{ background: {acc} !important; }}
[data-testid="stToggle"] [aria-checked="true"] > div:first-child, label[data-baseweb="checkbox"] input:checked + div {{ background: {acc} !important; }}
@media (max-width: 640px) {{
  h1 {{ font-size: 1.7rem !important; }}
  [data-testid="stTab"] {{ padding: 5px 12px !important; }}
  [data-testid="stTab"] p {{ font-size: .92rem; }}
}}
hr {{ border-color: {c['line']} !important; }}
[data-testid="stButtonGroup"] button[aria-checked="true"], [data-testid="stButtonGroup"] button[aria-pressed="true"] {{
  background-color: {rgba(acc, .18)} !important; }}
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
