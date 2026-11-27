"""我的仪表板：用自己的规则做图表。

一张图 = 一份「规格」（spec，存在 my_dashboard.json）：
  {"id", "title", "type", "markets": ["马股"], "rules": [{"栏位","条件","数值"}],
   "x", "y", "color", "size", "group", "agg", "sort", "desc", "limit", "cols", "note"}
图表种类：散点图、排行榜、分组平均、分布图、箱形图、树状图、热力表、表格。
资料来自 dataset.load()（全部约 500 只股票）。可以自己在网站上设定，也可以用一句话叫 AI 生成规格。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

import dataset as D

FILE = Path(__file__).parent / "my_dashboard.json"
TYPES = {"scatter": "🔵 散点图", "rank": "🏆 排行榜", "group": "📊 分组平均", "hist": "📶 分布图",
         "box": "📦 箱形图", "treemap": "🧱 树状图", "heat": "🔥 热力表", "table": "📋 表格"}
AGGS = {"mean": "平均", "median": "中位数", "sum": "总和", "count": "数量", "max": "最高", "min": "最低"}

PRESETS = [
    {"id": "p1", "title": "马股价值地图：本益比 vs 股息率", "type": "scatter", "markets": ["马股"],
     "rules": [{"栏位": "本益比", "条件": "介于", "数值": "0,40"}], "x": "本益比", "y": "股息率%",
     "color": "板块", "size": "市值(亿令吉)", "note": "左上角 = 便宜又高息"},
    {"id": "p2", "title": "各板块 1 个月平均涨跌", "type": "group", "markets": [], "rules": [],
     "group": "板块", "y": "1个月涨跌%", "agg": "mean", "color": "市场"},
    {"id": "p3", "title": "高息又赚钱：股息率 ≥ 5%、ROE ≥ 10%", "type": "rank", "markets": [],
     "rules": [{"栏位": "股息率%", "条件": ">=", "数值": 5}, {"栏位": "ROE%", "条件": ">=", "数值": 10}],
     "y": "股息率%", "limit": 15, "color": "板块"},
    {"id": "p4", "title": "马股市值地图（颜色 = 今日涨跌）", "type": "treemap", "markets": ["马股"], "rules": [],
     "group": "板块", "size": "市值(亿令吉)", "color": "1日涨跌%"},
    {"id": "p5", "title": "成长 vs 估值：营收增长 vs 本益比", "type": "scatter", "markets": [],
     "rules": [{"栏位": "本益比", "条件": "介于", "数值": "0,60"}, {"栏位": "营收增长%", "条件": "介于", "数值": "-50,100"}],
     "x": "营收增长%", "y": "本益比", "color": "市场", "size": "市值(亿令吉)", "note": "右下角 = 增长快又不贵"},
    {"id": "p6", "title": "我的自选股：各期间涨跌", "type": "heat", "markets": [],
     "rules": [{"栏位": "自选股", "条件": "=", "数值": "是"}],
     "cols": ["1日涨跌%", "1周涨跌%", "1个月涨跌%", "3个月涨跌%", "1年涨跌%"], "sort": "1个月涨跌%", "limit": 25},
]


# ---------------------------------------------------------------------------
# 读 / 存
# ---------------------------------------------------------------------------

def load_specs() -> list[dict]:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return d.get("charts", []) if isinstance(d, dict) else d
    except Exception:
        return [dict(p) for p in PRESETS]


def dump_specs(specs: list[dict]) -> str:
    return json.dumps({"charts": specs, "note": "我的仪表板（网站「📐 我的仪表板」或 AI 助手会改这个文件）"},
                      ensure_ascii=False, indent=1)


def new_id() -> str:
    return f"c{int(time.time() * 1000) % 10_000_000_000}"


def clean(spec: dict) -> dict:
    """把 AI 或表单来的规格整理好：不认识的栏位拿掉，种类不对就改成表格。"""
    s = {k: v for k, v in (spec or {}).items() if v not in (None, "", [])}
    s.setdefault("id", new_id())
    s["title"] = str(s.get("title") or "我的图表")[:60]
    if s.get("type") not in TYPES:
        s["type"] = "table"
    s["markets"] = [m for m in s.get("markets", []) if m in D.MARKET_ZH.values()]
    s["rules"] = [r for r in s.get("rules", []) if isinstance(r, dict) and r.get("栏位") in D.ALL_FIELDS
                  and r.get("条件") in D.OPS]
    for k in ("x", "y", "color", "size", "group", "sort"):
        if s.get(k) and s[k] not in D.ALL_FIELDS:
            s.pop(k)
    if s.get("agg") not in AGGS:
        s["agg"] = "mean"
    s["cols"] = [c for c in s.get("cols", []) if c in D.ALL_FIELDS]
    try:
        s["limit"] = max(3, min(100, int(s.get("limit") or 20)))
    except Exception:
        s["limit"] = 20
    s["desc"] = bool(s.get("desc", True))
    return s


# ---------------------------------------------------------------------------
# 画图
# ---------------------------------------------------------------------------

def data_for(spec: dict, df: pd.DataFrame) -> pd.DataFrame:
    out = df
    if spec.get("markets"):
        out = out[out["市场"].isin(spec["markets"])]
    return D.apply_rules(out, spec.get("rules", []))


def figure(spec: dict, df: pd.DataFrame):
    """回传 (plotly 图 或 DataFrame, 说明文字)。"""
    import plotly.express as px
    d = data_for(spec, df)
    t, n = spec["type"], len(d)
    info = f"{n} 只股票 · 规则：{D.describe_rules(spec.get('rules'))}" + (f" · 市场：{'、'.join(spec['markets'])}" if spec.get("markets") else "")
    if d.empty:
        return None, info + " · 没有符合的股票"
    lim = spec.get("limit", 20)
    color, size = spec.get("color"), spec.get("size")
    try:                                   # 分类颜色跟着网站主题
        import ui
        c = ui.COLORS
        seq = [c["accent"], c["soft"], c["accent2"], c["up"], c["down"], "#94A3B8", "#F2C94C", "#6FCF97",
               "#BB86FC", "#56CCF2", "#F2994A", "#EB5757"]
        px.defaults.color_discrete_sequence = seq
    except Exception:
        pass
    hover = ["代码", "板块"]
    if t == "scatter":
        x, y = spec.get("x") or "本益比", spec.get("y") or "股息率%"
        dd = d.dropna(subset=[x, y])
        if size:
            dd = dd[dd[size].fillna(0) > 0]
        fig = px.scatter(dd, x=x, y=y, color=color, size=size if size in D.NUMERIC else None, hover_name="名称",
                         hover_data=hover, size_max=38, opacity=.85)
        if len(dd) <= 25:
            fig.update_traces(text=dd["名称"], textposition="top center", mode="markers+text")
        return fig, info
    if t == "rank":
        y = spec.get("y") or "股息率%"
        dd = d.dropna(subset=[y]).sort_values(y, ascending=not spec.get("desc", True)).head(lim)
        fig = px.bar(dd[::-1], x=y, y="名称", orientation="h", color=color, hover_data=hover, text=y)
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside", cliponaxis=False)
        fig.update_layout(height=max(320, 26 * len(dd) + 80), yaxis_title=None,
                          yaxis=dict(categoryorder="array", categoryarray=list(dd["名称"][::-1])))
        return fig, info
    if t == "group":
        g, y, agg = spec.get("group") or "板块", spec.get("y") or "1个月涨跌%", spec.get("agg", "mean")
        keys = [g] + ([color] if color and color in D.CATEGORIES and color != g else [])
        dd = d.groupby(keys, dropna=False)[y].agg(agg).reset_index().sort_values(y, ascending=False)
        fig = px.bar(dd, x=g, y=y, color=color if len(keys) > 1 else None, barmode="group", text=y)
        fig.update_traces(texttemplate="%{text:.1f}", textposition="outside")
        fig.update_layout(yaxis_title=f"{y}（{AGGS.get(agg, agg)}）")
        return fig, info
    if t == "hist":
        x = spec.get("x") or "RSI"
        fig = px.histogram(d, x=x, color=color if color in D.CATEGORIES else None, nbins=30, opacity=.85)
        return fig, info
    if t == "box":
        x, y = spec.get("group") or spec.get("x") or "板块", spec.get("y") or "本益比"
        fig = px.box(d, x=x, y=y, color=color if color in D.CATEGORIES else None, points="outliers", hover_name="名称")
        return fig, info
    if t == "treemap":
        g, size, c = spec.get("group") or "板块", spec.get("size") or "市值(亿令吉)", spec.get("color") or "1日涨跌%"
        dd = d.dropna(subset=[size])
        dd = dd[dd[size] > 0]
        if c in D.NUMERIC:
            lim_c = max(abs(dd[c].quantile(.05) or 0), abs(dd[c].quantile(.95) or 0), 1)
            fig = px.treemap(dd, path=[g, "名称"], values=size, color=c, color_continuous_scale="RdYlGn",
                             range_color=[-lim_c, lim_c], hover_data=["代码", c])
        else:
            fig = px.treemap(dd, path=[g, "名称"], values=size, color=c)
        fig.update_layout(height=520, margin=dict(l=4, r=4, t=30, b=4))
        return fig, info
    if t == "heat":
        cols = spec.get("cols") or ["1日涨跌%", "1周涨跌%", "1个月涨跌%", "3个月涨跌%"]
        s = spec.get("sort") or cols[0]
        dd = d.sort_values(s, ascending=not spec.get("desc", True)).head(lim) if s in d else d.head(lim)
        z = dd[cols].astype(float)
        import plotly.graph_objects as go
        lim_z = max(float(z.abs().quantile(.9).max() or 1), 1)
        fig = go.Figure(go.Heatmap(z=z.values, x=cols, y=dd["名称"], colorscale="RdYlGn", zmin=-lim_z, zmax=lim_z,
                                   text=z.round(1).values, texttemplate="%{text}", showscale=False))
        fig.update_layout(height=max(300, 28 * len(dd) + 90), yaxis=dict(autorange="reversed"))
        return fig, info
    # table
    cols = spec.get("cols") or ["代码", "名称", "市场", "板块", "股价", "本益比", "股息率%", "ROE%", "1个月涨跌%"]
    s = spec.get("sort")
    dd = d.sort_values(s, ascending=not spec.get("desc", True)) if s in d else d
    return dd[[c for c in cols if c in dd]].head(lim), info


# ---------------------------------------------------------------------------
# 一句话 → 规格（AI）
# ---------------------------------------------------------------------------

SPEC_SYSTEM = """你帮用户把「想看的图表」变成 JSON 规格。只回传 JSON，不要别的文字。
可用栏位（一定要用这些中文名称，一字不差）：
  文字：代码、名称
  分类：市场（马股 / 美股 / 印尼股）、板块、行业、主题、自选股（是 / 否）
  数字：股价、市值(亿令吉)、本益比、股价净值比、股息率%、ROE%、净利率%、营收增长%、盈利增长%、负债权益比、RSI、
        1日涨跌%、1周涨跌%、1个月涨跌%、3个月涨跌%、1年涨跌%
板块名称：金融、工业、必需消费、非必需消费、公用事业、房地产、医疗保健、原材料、电讯媒体、能源、科技、种植
主题（用「主题 包含 …」，写关键字就好）：数据中心、AI、半导体、发电、太阳能、手套、REIT、银行、油气、建筑、煤炭、电动车、数字经济、网络安全、医药
图表种类 type：
  scatter（散点：x、y 数字，color 分类或数字，size 数字）
  rank（排行榜：y 数字，limit 前几名，desc true=由大到小）
  group（分组：group 分类，y 数字，agg mean/median/sum/count/max/min）
  hist（分布：x 数字）　box（箱形：group 分类，y 数字）
  treemap（树状：group 分类，size 数字，color 数字）
  heat（热力表：cols 几个数字栏位，sort，limit）　table（表格：cols，sort，limit）
规则 rules：[{"栏位":"股息率%","条件":">=","数值":5}]；条件只能是 > >= < <= = != 包含 不包含 介于（介于的数值写 "0,40"）
markets：["马股"] / ["美股"] / ["印尼股"]，空的 = 全部
格式：{"title":"中文标题","type":"...","markets":[],"rules":[],"x":"","y":"","color":"","size":"","group":"",
"agg":"mean","sort":"","desc":true,"limit":20,"cols":[],"note":"一句话说明怎么看这张图"}
本益比要排除负数和太大的（例如 介于 0,60），不然图会很难看。
栏位名称、分类名称、条件一律用上面的中文（就算用户用英文问也一样）；只有 title 和 note 可以用用户的语言。"""


async def spec_from_text(text: str) -> dict:
    import managers as M
    from news import _json_from
    raw = await M.chat(SPEC_SYSTEM, f"用户想看：{text}", max_tokens=900)
    data = _json_from(raw)
    if not data:
        raise ValueError("AI 没有回传正确的图表规格，换个说法再试一次")
    return clean(data)
