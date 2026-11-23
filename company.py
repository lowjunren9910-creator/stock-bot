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
    "毛利": ("income_stmt", ["Gross Profit"]),
    "营业利润": ("income_stmt", ["Operating Income"]),
    "净利润": ("income_stmt", ["Net Income", "Net Income Common Stockholders"]),
    "每股盈利": ("income_stmt", ["Diluted EPS", "Basic EPS"]),
    "营运现金流": ("cashflow", ["Operating Cash Flow"]),
    "自由现金流": ("cashflow", ["Free Cash Flow"]),
    "资本开支": ("cashflow", ["Capital Expenditure"]),
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
    if "营收" in fin:
        for k, lab in (("毛利", "毛利率%"), ("营业利润", "营业利润率%")):
            if k in fin:
                fin[lab] = fin[k] / fin["营收"] * 100

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
        "quarters": _quarters(t),
        "ratios": {k: info.get(v) for k, v in (("毛利率", "grossMargins"), ("营业利润率", "operatingMargins"),
                                              ("净利率", "profitMargins"), ("营收按年增长", "revenueGrowth"),
                                              ("盈利按年增长", "earningsGrowth"), ("ROE", "returnOnEquity"),
                                              ("负债/股东权益%", "debtToEquity"), ("流动比率", "currentRatio"))
                   if info.get(v) is not None},
        "peers": peers_of(ticker),
    }
    p["scores"] = scorecard(p)
    return p


def _quarters(t) -> dict:
    """最近 5 季营收、净利（看最新趋势）。"""
    q = _safe(t, "quarterly_income_stmt")
    out = {}
    if q is None or getattr(q, "empty", True):
        return out
    for lab, names in (("营收", ["Total Revenue", "Operating Revenue"]), ("净利润", ["Net Income", "Net Income Common Stockholders"])):
        for n in names:
            if n in q.index:
                r = pd.to_numeric(q.loc[n], errors="coerce").dropna().sort_index().tail(5)
                for d, v in r.items():
                    out.setdefault(str(pd.Timestamp(d).date()), {})[lab] = big(v)
                break
    return out


def peers_of(ticker: str, limit: int = 6) -> list[dict]:
    """同一个板块的其他公司（来自板块报告），给 AI 当竞争对手 / 同行参考。"""
    try:
        import sectors as SE
        import universe
        r = SE.latest(universe.market_of(ticker))
    except Exception:
        return []
    if not r:
        return []
    for g in r.get("sectors", []):
        if any(m["ticker"] == ticker for m in g["members"]):
            rows = [m for m in g["members"] if m["ticker"] != ticker][:limit]
            pc = lambda v: None if v is None else round(v, 1)
            return [{"公司": m["name"], "代码": m["ticker"], "板块": g["name"], "市值": big(m.get("mcap")),
                     "P/E": pc(m.get("pe")), "ROE%": pc(m.get("roe")), "净利率%": pc(m.get("margin")),
                     "营收增长%": pc(m.get("rev_growth"))} for m in rows]
    return []


# ---------------------------------------------------------------------------
# 1b. 年报 / 季报 PDF（可选，自己上传）：挑出讲业务的段落
# ---------------------------------------------------------------------------

BIZ_WORDS = ["segment", "business review", "management discussion", "md&a", "operations review",
             "revenue by", "our business", "principal activities", "outlook", "prospects", "market share",
             "customers", "products", "brands", "stores", "capacity", "order book", "业务", "分部", "展望"]


def report_excerpt(data: bytes, limit: int = 6000) -> str:
    """从年报 PDF 挑出讲业务、分部、展望的页（英文 6000 字大约 1500 个 token，免费额度放得下）。"""
    import io
    from pypdf import PdfReader
    rd = PdfReader(io.BytesIO(data))
    pages = []
    for i, pg in enumerate(rd.pages[:260]):
        try:
            t = re.sub(r"[ \t]+", " ", pg.extract_text() or "")
        except Exception:
            continue
        low = t.lower()
        hit = sum(low.count(w) for w in BIZ_WORDS)
        if hit and len(t) > 300:
            pages.append((hit, i, t))
    pages.sort(key=lambda x: -x[0])
    out, n = [], 0
    for hit, i, t in sorted(pages[:8], key=lambda x: x[1]):
        chunk = re.sub(r"\n{2,}", "\n", t).strip()[:2200]
        out.append(f"[第 {i + 1} 页] {chunk}")
        n += len(chunk)
        if n >= limit:
            break
    return "\n".join(out)[:limit]


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

SECTIONS = ["一句话认识", "主要业务", "业务分部", "营业模式", "行业与竞争", "增长动力", "关键指标",
            "近几年成绩", "管理层", "优势", "风险", "业务实力评级", "管理层评级", "综合评级"]
BIZ_SECTIONS = SECTIONS[:7]


def _rules() -> str:
    return f"""今天是 {date.today():%Y年%m月%d日}。
资料规则（很重要）：
- 数字只能用提供的资料（年度 / 季度财报、比率、同行表、年报摘录、近期动态），不要自己编数字；资料没有就写「资料未提供」
- 「年报摘录」是公司自己写的，最可靠：有提供的话，业务分部、产品、市场、展望要优先根据它，并写出里面的数字（例如分部营收占比、店数、产能、订单）
- 你的知识有截止日期：讲「最近」「现在」只能根据近期动态；用自己的知识补充（例如行业常识、知名竞争对手）时要写「据我所知」
- 绝对不要编造人名、合约、事件；不确定就说不确定
- 用简体中文，像投资银行研究报告一样仔细、具体，但要让投资新手看得懂：专业名词第一次出现时用括号简单解释
- 不要用 Markdown 符号（不要 **、#），列点用「1. 2. 3.」或「- 」"""


def _system_business() -> str:
    return f"""你是投资银行的资深股票分析员，专门写「公司业务」研究，要把一家公司的生意讲得非常清楚、仔细。
{_rules()}

严格按下面格式输出，每个标题都要有（总共约 1500-2000 字）：
【一句话认识】一句话：这家公司靠什么赚钱、在行业里是什么角色
【主要业务】5-7 句：卖什么产品 / 服务（举出具体产品、品牌或服务名称）、客户是谁（个人 / 企业 / 政府）、主要市场和地区、规模（员工、门店、产能、客户数等，有资料才写）
【业务分部】列出每个业务分部，每个一段：做什么、主要产品、营收或利润占比和趋势（有资料才写数字）、这个分部的前景。资料没有分部数字就根据业务简介分类，并注明「占比资料未提供」
【营业模式】分 4 点写：1. 收入怎么来（卖一次 / 经常性收入？靠量还是靠价？有没有季节性）2. 成本结构（毛利率、营业利润率的数字和这几年的变化，主要成本是什么）3. 要花多少钱维持和扩张（资本开支占营收多少、营运现金流跟净利比较，赚的是不是真金白银）4. 定价能力和护城河（难以被抄袭的竞争优势是什么，有多强）
【行业与竞争】4-6 句：行业现在的情况和周期（景气 / 低迷 / 受什么影响）、主要竞争对手（优先用提供的同行表，跟这家公司比 P/E、ROE、利润率、增长）、这家公司的市场地位
【增长动力】3-4 点，每点说明：是什么、有多大影响、什么时候会看到（尽量引用年报摘录或近期动态的具体事件和日期）
【关键指标】3-4 个这个行业最值得追踪的数字（例如零售看同店销售和开店数、银行看贷款增长和净利息收益率、建筑看订单），每个一句话说明为什么重要、现在的情况（有资料才写）"""


def _system_rest() -> str:
    return f"""你是投资银行的资深股票分析员。你已经写好了这家公司的业务分析（会附上），现在要写成绩、管理层、优势、风险和评级。
{_rules()}

严格按下面格式输出，每个标题都要有（总共约 800-1100 字）：
【近几年成绩】5-7 句：营收、毛利率、营业利润、净利、现金流的趋势（必须引用年度财报的数字，例如营收从多少增长到多少），最近几季的变化，亮点和问题；最后一句提最新一季业绩（如果有提供）
【管理层】3-4 句：主要领导人、内部人持股、机构持股、公司治理；只根据提供的资料和你确定知道的公开信息，不确定就说「资料不足」
【优势】3 点，用 1. 2. 3. 编号，每点要有根据（数字或事实）
【风险】3-4 点，用 1. 2. 3. 编号，每点说明会怎样影响盈利；要反映近期动态里的重要事情（如果有）
【业务实力评级】从 弱 / 偏弱 / 中等 / 偏强 / 强 选一个，接着一句话理由
【管理层评级】同上
【综合评级】同上（综合业务、财务和管理层；可参考财务体检，但可以有自己的判断）"""


def _data(p: dict, report_text: str | None = None) -> dict:
    table = {}
    for y, row in p["fin"].iterrows():
        table[str(y)] = {k: (f"{v:.1f}%" if k.endswith("%") else big(v))
                         for k, v in row.dropna().items()}
    r = p.get("ratios") or {}
    ratios = {k: (f"{v * 100:.1f}%" if k not in ("负债/股东权益%", "流动比率") else round(v, 2)) for k, v in r.items()}
    data = {
        "公司": p["name"], "代码": p["ticker"], "市场": p["market"],
        "行业": f"{p['sector'] or ''} / {p['industry'] or ''}", "国家": p["country"], "网站": p.get("website"),
        "员工人数": p["employees"], "市值": big(p["market_cap"]), "财报货币": p["currency"],
        "英文业务简介": p["summary"][:3000],
        "近几年财务（年度）": table,
        "最近几季（季度）": p.get("quarters") or {},
        "最新比率": ratios,
        "同行（同一板块）": p.get("peers") or [],
        "每年股息（每股）": p["dividends"],
    }
    if report_text:
        data["年报摘录（公司自己写的，英文原文）"] = report_text
    try:                                   # 最新资料：最近 14 天新闻、重大事件、最新季报、公告日历
        import recent
        ctx = recent.context(p["ticker"])
        ctx.pop("股价走势", None)
        data["近期动态"] = ctx
    except Exception as e:
        print("近期动态失败：", e)
    return data


def _brief(p: dict, report_text: str | None = None) -> str:
    return json.dumps(_data(p, report_text), ensure_ascii=False, default=str, separators=(",", ":"))


def _brief_rest(p: dict, business: str) -> str:
    d = _data(p)
    for k in ("英文业务简介", "同行（同一板块）"):
        d.pop(k, None)
    d.update({
        "高管名单": p["officers"],
        "内部人持股%": round(p["insider_pct"] * 100, 1) if p["insider_pct"] else None,
        "机构持股%": round(p["institution_pct"] * 100, 1) if p["institution_pct"] else None,
        "ISS治理风险分(1好-10差)": p["governance_risk"],
        "财务体检": [{k: it[k] for k in ("name", "level", "reason")} for it in p["scores"]["items"]],
        "财务体检总评": p["scores"]["level"],
        "你写好的业务分析（摘要）": business[:2500],
    })
    return json.dumps(d, ensure_ascii=False, default=str, separators=(",", ":"))


def parse_sections(text: str) -> dict:
    parts = re.split(r"【(.+?)】", text)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


async def ai_profile(p: dict, report_text: str | None = None) -> dict | None:
    """返回 AI 报告（分两次写：先写业务，再写成绩 / 风险 / 评级，每次不超过免费额度的上限）。
    没设置 AI key 返回 None；API 出错会 raise（让调用方处理）。report_text：年报摘录（可选）。"""
    import managers as M
    if M.check_setup():
        return None
    biz = await M.chat(_system_business(), f"请仔细分析这家公司的业务：\n{_brief(p, report_text)}", max_tokens=3200 if report_text else 3600)
    rest = await M.chat(_system_rest(), f"请写成绩、管理层、优势、风险和评级：\n{_brief_rest(p, biz)}", max_tokens=2200)
    text = biz.strip() + "\n" + rest.strip()
    sec = parse_sections(text)
    if not sec:  # 模型没按格式写，至少把全文显示出来
        sec = {"一句话认识": text}
    return {"sections": sec, "raw": text, "with_report": bool(report_text),
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
        for k, icon in [("一句话认识", "💡"), ("主要业务", "🏭"), ("业务分部", "🧩"), ("营业模式", "💰"),
                        ("行业与竞争", "🏁"), ("增长动力", "🚀"), ("关键指标", "🎯"),
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
