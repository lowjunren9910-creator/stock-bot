"""
company.py - 认识一家公司

点一下股票代码，就生成：
  公司业务 / 营业模式 / 近几年成绩 / 管理层 / 优势与风险
  + 五级评级：弱 / 偏弱 / 中等 / 偏强 / 强

由两部分组成：
  1. 财务体检（规则计算，数字透明）：成长性、获利能力、财务稳健、盈利稳定、股东回报、公司治理
  2. AI 研究员：读公司资料 + 近几年财报数据，写成华文报告并给出评级
"""

from __future__ import annotations

import html
import json
import re
from datetime import date

import pandas as pd
import yfinance as yf

import analysis as A

LEVELS = ["弱", "偏弱", "中等", "偏强", "强"]
LEVEL_COLOR = {"弱": "#dc2626", "偏弱": "#f97316", "中等": "#eab308",
               "偏强": "#22c55e", "强": "#15803d"}


def level_of(score: float | None) -> str | None:
    """1-5 分 → 五个等级。"""
    if score is None:
        return None
    return LEVELS[min(4, max(0, int(score + 0.5) - 1))]


def parse_level(text: str) -> str | None:
    """从 AI 写的 "偏强。理由……" 里抓出等级（只看开头几个字）。"""
    head = (text or "")[:12]
    hits = [(head.find(lv), lv) for lv in ("偏弱", "偏强", "中等") if lv in head]
    if hits:
        return min(hits)[1]
    for lv in ("弱", "强"):
        if lv in head:
            return lv
    return None


def big(x) -> str:
    """大数字缩写，支持负数：-1.2B。"""
    if x is None or pd.isna(x):
        return "无"
    sign = "-" if x < 0 else ""
    x = abs(x)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if x >= div:
            return f"{sign}{x / div:,.2f}{unit}"
    return f"{sign}{x:,.2f}"


# ---------------------------------------------------------------------------
# 1. 抓公司资料和财报
# ---------------------------------------------------------------------------

def _safe(obj, attr):
    try:
        return getattr(obj, attr)
    except Exception:
        return None


def _row(df, *names) -> pd.Series | None:
    """从财报表格里拿一行，返回 {年份: 数值}（旧 → 新）。"""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for n in names:
        if n in df.index:
            r = df.loc[n]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            s = pd.to_numeric(r, errors="coerce").dropna()
            if s.empty:
                continue
            s.index = pd.to_datetime(s.index).year
            s = s[~s.index.duplicated(keep="first")]
            return s.sort_index()
    return None


# 财报项目：中文名 → (哪张表, Yahoo 上可能的英文名)
ROWS = {
    "营收": ("income_stmt", ["Total Revenue", "Operating Revenue"]),
    "营业利润": ("income_stmt", ["Operating Income"]),
    "净利润": ("income_stmt", ["Net Income", "Net Income Common Stockholders"]),
    "每股盈利": ("income_stmt", ["Diluted EPS", "Basic EPS"]),
    "营运现金流": ("cashflow", ["Operating Cash Flow"]),
    "自由现金流": ("cashflow", ["Free Cash Flow"]),
    "总负债": ("balance_sheet", ["Total Debt"]),
    "股东权益": ("balance_sheet", ["Stockholders Equity", "Common Stock Equity"]),
}


def fetch(text: str) -> dict:
    ticker = A.normalize_ticker(text)
    t = yf.Ticker(ticker)
    info = _safe(t, "info") or {}
    stmts = {k: _safe(t, k) for k in ("income_stmt", "balance_sheet", "cashflow")}

    cols = {}
    for label, (src, names) in ROWS.items():
        s = _row(stmts[src], *names)
        if s is not None:
            cols[label] = s
    fin = pd.DataFrame(cols).sort_index().tail(5)

    name = info.get("longName") or info.get("shortName")
    if not name and fin.empty:
        raise ValueError(f"找不到 {ticker} 的公司资料，请检查代码"
                         "（大马 1155.KL、印尼 BBCA.JK、美股 AAPL）。")

    if "营收" in fin and "净利润" in fin:
        fin["净利率%"] = fin["净利润"] / fin["营收"] * 100
    if "净利润" in fin and "股东权益" in fin:
        fin["ROE%"] = fin["净利润"] / fin["股东权益"] * 100

    divs = _safe(t, "dividends")
    this_year = date.today().year
    div_years = {}
    if divs is not None and len(divs):
        g = divs.groupby(divs.index.year).sum()
        div_years = {int(y): round(float(v), 4) for y, v in g.items()
                     if this_year - 5 <= y < this_year}

    officers = [{"姓名": o.get("name"), "职位": o.get("title"), "年龄": o.get("age")}
                for o in (info.get("companyOfficers") or [])[:8]]

    p = {
        "ticker": ticker, "name": name or ticker, "market": A.market_of(ticker),
        "sector": info.get("sector"), "industry": info.get("industry"),
        "country": info.get("country"), "website": info.get("website"),
        "employees": info.get("fullTimeEmployees"),
        "summary": info.get("longBusinessSummary") or "",
        "currency": info.get("financialCurrency") or info.get("currency") or "",
        "market_cap": info.get("marketCap"),
        "insider_pct": info.get("heldPercentInsiders"),
        "institution_pct": info.get("heldPercentInstitutions"),
        "governance_risk": info.get("overallRisk"),
        "officers": officers,
        "fin": fin,
        "dividends": div_years,
    }
    p["scores"] = scorecard(p)
    return p


# ---------------------------------------------------------------------------
# 2. 财务体检（规则计算）
# ---------------------------------------------------------------------------

def _band(x: float, cuts: list[float]) -> int:
    """cuts 由高到低：x ≥ cuts[0] 得 5 分，≥ cuts[1] 得 4 分 ……"""
    for i, c in enumerate(cuts):
        if x >= c:
            return 5 - i
    return 1


def scorecard(p: dict) -> dict:
    fin = p["fin"]

    def col(k):
        return fin[k].dropna() if k in fin else pd.Series(dtype=float)

    rev, ni, fcf, roe = col("营收"), col("净利润"), col("自由现金流"), col("ROE%")
    items = []  # (名称, 分数 1-5 或 None, 理由, 权重)

    # 成长性：营收年复合增长率
    if len(rev) >= 2 and rev.iloc[0] > 0:
        yrs = int(rev.index[-1] - rev.index[0])
        cagr = ((rev.iloc[-1] / rev.iloc[0]) ** (1 / yrs) - 1) * 100
        items.append(("成长性", _band(cagr, [15, 8, 3, 0]),
                      f"营收 {yrs} 年复合增长 {cagr:+.1f}%", 1.0))
    else:
        items.append(("成长性", None, "营收数据不足", 1.0))

    # 获利能力：近 3 年平均 ROE
    if len(roe):
        r = float(roe.tail(3).mean())
        items.append(("获利能力", _band(r, [20, 15, 10, 5]), f"近年平均 ROE {r:.1f}%", 1.5))
    else:
        items.append(("获利能力", None, "ROE 数据不足", 1.5))

    # 财务稳健：负债/股本 + 自由现金流
    pair = fin[["总负债", "股东权益"]].dropna() if {"总负债", "股东权益"} <= set(fin) else pd.DataFrame()
    if p["sector"] == "Financial Services":
        items.append(("财务稳健", None, "银行/金融业负债结构特殊，不用负债比评分", 1.0))
    elif len(pair):
        debt, eq = pair.iloc[-1]
        de = debt / eq * 100 if eq > 0 else 999
        s = _band(-de, [-30, -70, -120, -200])
        reason = f"负债/股本 {de:.0f}%"
        if len(fcf):
            pos = int((fcf > 0).sum())
            reason += f"，自由现金流 {pos}/{len(fcf)} 年为正"
            if pos < len(fcf) / 2:
                s = max(1, s - 1)
        items.append(("财务稳健", s, reason, 1.0))
    else:
        items.append(("财务稳健", None, "负债数据不足", 1.0))

    # 盈利稳定：有没有亏损、营收是不是年年增长
    if len(ni) >= 2:
        losses = int((ni <= 0).sum())
        n = max(1, len(rev) - 1)
        grew = int((rev.diff().dropna() > 0).sum()) if len(rev) >= 2 else 0
        if losses == 0 and grew >= n - 1 and n >= 2:
            s = 5
        elif losses == 0 and grew >= n / 2:
            s = 4
        elif losses == 0:
            s = 3
        elif losses == 1:
            s = 2
        else:
            s = 1
        items.append(("盈利稳定", s, f"{len(ni)} 年中亏损 {losses} 年，营收增长 {grew}/{n} 年", 1.0))
    else:
        items.append(("盈利稳定", None, "利润数据不足", 1.0))

    # 股东回报：过去 5 年派息
    d = p["dividends"]
    paid = sum(1 for v in d.values() if v > 0)
    vals = [d[y] for y in sorted(d)]
    if paid == 5 and vals[-1] > vals[0]:
        s, why = 5, "连续 5 年派息且股息上升"
    elif paid == 5:
        s, why = 4, "连续 5 年派息"
    elif paid >= 3:
        s, why = 3, f"过去 5 年有 {paid} 年派息"
    elif paid >= 1:
        s, why = 2, f"过去 5 年只有 {paid} 年派息"
    else:
        s, why = 1, "不派息（成长股常见，把钱留着扩张）"
    items.append(("股东回报", s, why, 0.5))

    # 公司治理：ISS 治理风险分（1 最好，10 最差；美股较常有）
    g = p["governance_risk"]
    if g:
        items.append(("公司治理", _band(-g, [-2, -4, -6, -8]),
                      f"ISS 治理风险分 {g}/10（越低越好）", 0.5))
    else:
        items.append(("公司治理", None, "没有治理评分数据", 0.5))

    scored = [(s, w) for _, s, _, w in items if s is not None]
    overall = sum(s * w for s, w in scored) / sum(w for _, w in scored) if scored else None
    return {
        "items": [{"name": n, "score": s, "level": level_of(s), "reason": r}
                  for n, s, r, _ in items],
        "overall": round(overall, 2) if overall is not None else None,
        "level": level_of(overall),
    }


# ---------------------------------------------------------------------------
# 3. AI 研究员
# ---------------------------------------------------------------------------

SECTIONS = ["一句话认识", "主要业务", "营业模式", "近几年成绩", "管理层",
            "优势", "风险", "业务实力评级", "管理层评级", "综合评级"]


def _system() -> str:
    return f"""你是一位资深股票研究员，要帮一位投资新手"认识一家公司"。今天是 {date.today():%Y年%m月%d日}。
你会收到：公司资料、近几年财务数据、高管名单，以及一份规则计算的财务体检分数。

写作要求：
- 用简体中文，口语化、易懂；专业名词第一次出现时用括号简单解释
- 「近几年成绩」必须引用提供的数字（例如营收从多少增长到多少）
- 「管理层」只根据提供的高管名单、持股比例、治理分数，加上你确定知道的公开信息来写；不确定就说"资料不足"，绝对不要编造人名、经历或事件
- 你的知识有截止日期，提到近期动态要说"据我所知"
- 不要用 Markdown 符号（不要 **、#）

严格按下面格式输出，每个标题都要有，总字数 600-900 字：
【一句话认识】一句话说清楚这家公司是做什么的
【主要业务】3-4 句：卖什么产品/服务、客户是谁、主要市场在哪
【营业模式】3-4 句：靠什么赚钱、主要收入来源、成本结构、有没有护城河（难以被抄袭的竞争优势）
【近几年成绩】3-5 句：营收、利润、利润率、现金流的趋势，亮点和问题
【管理层】2-4 句：主要领导人、内部人持股、公司治理
【优势】2-3 点，用 1. 2. 3. 编号
【风险】2-3 点，用 1. 2. 3. 编号
【业务实力评级】从 弱 / 偏弱 / 中等 / 偏强 / 强 选一个，接着一句话理由
【管理层评级】同上
【综合评级】同上（综合业务、财务和管理层；可参考财务体检，但可以有自己的判断）"""


def _brief(p: dict) -> str:
    table = {}
    for y, row in p["fin"].iterrows():
        table[str(y)] = {k: (f"{v:.1f}%" if k.endswith("%") else big(v))
                         for k, v in row.dropna().items()}
    data = {
        "公司": p["name"], "代码": p["ticker"], "市场": p["market"],
        "行业": f"{p['sector'] or ''} / {p['industry'] or ''}", "国家": p["country"],
        "员工人数": p["employees"], "市值": big(p["market_cap"]), "财报货币": p["currency"],
        "英文业务简介": p["summary"][:2000],
        "近几年财务（年度）": table,
        "每年股息（每股）": p["dividends"],
        "高管名单": p["officers"],
        "内部人持股%": round(p["insider_pct"] * 100, 1) if p["insider_pct"] else None,
        "机构持股%": round(p["institution_pct"] * 100, 1) if p["institution_pct"] else None,
        "ISS治理风险分(1好-10差)": p["governance_risk"],
        "财务体检": [{k: it[k] for k in ("name", "level", "reason")} for it in p["scores"]["items"]],
        "财务体检总评": p["scores"]["level"],
    }
    return json.dumps(data, ensure_ascii=False, default=str, indent=1)


def parse_sections(text: str) -> dict:
    parts = re.split(r"【(.+?)】", text)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


async def ai_profile(p: dict) -> dict | None:
    """返回 AI 报告；没设置 AI key 返回 None；API 出错会 raise（让调用方处理）。"""
    import managers as M
    if M.check_setup():
        return None
    text = await M.chat(_system(), f"请帮我认识这家公司：\n{_brief(p)}", max_tokens=1800)
    sec = parse_sections(text)
    if not sec:  # 模型没按格式写，至少把全文显示出来
        sec = {"一句话认识": text}
    return {"sections": sec, "raw": text,
            "levels": {k: parse_level(sec.get(k, ""))
                       for k in ("业务实力评级", "管理层评级", "综合评级")}}


# ---------------------------------------------------------------------------
# 4. Telegram 版本
# ---------------------------------------------------------------------------

def to_telegram_html(p: dict, ai: dict | None) -> str:
    e = html.escape
    sc = p["scores"]
    lines = [f"🏢 <b>{e(p['name'])}</b>（{p['ticker']} · {p['market']}）",
             e(" · ".join(x for x in (p["sector"], p["industry"], p["country"]) if x))]
    if ai:
        lv = ai["levels"]
        lines += ["", f"<b>⭐ 综合评级：{lv.get('综合评级') or '无'}</b>",
                  f"业务实力 {lv.get('业务实力评级') or '无'}｜管理层 {lv.get('管理层评级') or '无'}"
                  f"｜财务体检 {sc['level'] or '无'}"]
        for k, icon in [("一句话认识", "💡"), ("主要业务", "🏭"), ("营业模式", "💰"),
                        ("近几年成绩", "📈"), ("管理层", "👔"), ("优势", "✅"),
                        ("风险", "⚠️"), ("综合评级", "⭐")]:
            if ai["sections"].get(k):
                lines += ["", f"<b>{icon} {k}</b>", e(ai["sections"][k])]
    else:
        lines += ["", f"<b>财务体检总评：{sc['level'] or '无'}</b>（未设置 AI，只有数字评分）"]
    lines += ["", "<b>🩺 财务体检</b>"]
    lines += [f"{it['level'] or '—'}｜{it['name']}：{e(it['reason'])}" for it in sc["items"]]
    lines += ["", "<i>仅供学习参考，不构成投资建议。</i>"]
    return "\n".join(lines)
