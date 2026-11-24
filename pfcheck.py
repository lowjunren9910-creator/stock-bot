"""pfcheck.py - AI 组合体检：看你整个投资组合（不是单只股票）。

两部分：
  1. 程序计算（数字透明）：每只的比重、盈亏、板块 / 市场 / 货币分布、集中度、加权股息率和本益比、
     过去 1 年的波动、最大回撤、股票之间的相关性（是不是押同一件事）、最新季报、近期重要新闻
  2. AI 分析员：根据上面的数字和你的目标（收息 / 增长…、持有多久、能接受跌多少）写体检报告

持股只在这一次分析时用，不会存进 GitHub。会传给 AI 服务商（Groq / Gemini）做分析。
"""
from __future__ import annotations

import json
import math
from datetime import date

import numpy as np
import pandas as pd

import analysis as A

GOALS = ["长期增长", "收息（股息）", "增长和收息平衡", "短线交易"]
HORIZONS = ["1 年内", "1–3 年", "3 年以上"]
DRAWDOWNS = ["跌 10% 就很不舒服", "可以接受跌 20%", "可以接受跌 30% 以上"]
CUR_OF = lambda t: "MYR" if t.endswith(".KL") else "IDR" if t.endswith(".JK") else "USD"
FX_TICKER = {"USD": "USDMYR=X", "IDR": "IDRMYR=X"}
FX_FALLBACK = {"USD": 4.4, "IDR": 0.00027}
FX_RANGE = {"USD": (3.0, 6.5), "IDR": (0.0001, 0.0006)}


def parse_link(s: str) -> list[dict]:
    """手机 App 传来的「代码:数量:成本,代码:数量:成本」。"""
    out = []
    for part in (s or "").split(","):
        bits = part.split(":")
        if len(bits) >= 3:
            try:
                out.append({"代码": bits[0].strip(), "数量": float(bits[1]), "平均成本": float(bits[2])})
            except ValueError:
                continue
    return out


ALIASES = {
    "代码": ["代码", "股票", "股票代码", "ticker", "symbol", "code", "stock", "股票名称", "名称", "name"],
    "数量": ["数量", "股数", "qty", "quantity", "shares", "units", "持股", "持仓", "holding"],
    "平均成本": ["平均成本", "成本", "成本价", "均价", "cost", "avg cost", "average cost", "avg price", "average price", "price", "买入价"],
}


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """把各种栏名（BOM、英文、券商导出的格式）统一成：代码 / 数量 / 平均成本。找不到就 raise ValueError。"""
    clean = {c: str(c).replace("\ufeff", "").strip() for c in df.columns}
    df = df.rename(columns=clean)
    low = {c.lower(): c for c in df.columns}
    rename, missing = {}, []
    for std, names in ALIASES.items():
        hit = next((low[n] for n in names if n in low), None)
        if hit is None:
            missing.append(std)
        else:
            rename[hit] = std
    if missing:
        raise ValueError(f"找不到这些栏：{'、'.join(missing)}（现在的栏是：{'、'.join(map(str, df.columns))}）")
    out = df.rename(columns=rename)[["代码", "数量", "平均成本"]].copy()
    out["代码"] = out["代码"].astype(str).str.strip()
    for c in ("数量", "平均成本"):
        out[c] = pd.to_numeric(out[c].astype(str).str.replace(",", "").str.replace("RM", "").str.strip(), errors="coerce")
    return out


def fx_rates(curs: set[str]) -> tuple[dict, bool]:
    """各货币 → 令吉的汇率。取不到用约值（会注明）。"""
    rates, approx = {"MYR": 1.0}, False
    for c in curs - {"MYR"}:
        try:
            v = float(A.get_history(FX_TICKER[c], "5d")["Close"].dropna().iloc[-1])
            lo, hi = FX_RANGE[c]
            if not lo <= v <= hi:                    # 数据明显不对：不用
                raise ValueError(v)
            rates[c] = v
        except Exception:
            rates[c], approx = FX_FALLBACK.get(c, 1.0), True
    return rates, approx


def _pct(v, d=1):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), d)


def build(holdings: list[dict], get_raw) -> dict:
    """holdings：[{代码, 数量, 平均成本}]；get_raw(代码) → analysis.analyze_raw 的结果（网站会缓存）。"""
    rows, closes, errors = [], {}, []
    for h in holdings:
        try:
            r = get_raw(str(h["代码"]))
        except Exception as e:
            errors.append(f"{h['代码']}：{e}")
            continue
        t, tech, fund = r["ticker"], r["tech"], r["fund"]
        snap = r["snapshot"].get("近期动态") or {}
        q = snap.get("最新一季业绩") or {}
        qty, cost, px = float(h["数量"]), float(h["平均成本"]), float(tech["price"])
        rows.append({
            "ticker": t, "name": fund["name"], "cur": CUR_OF(t), "market": A.market_of(t),
            "sector": fund["sector"] or "其他", "qty": qty, "cost": cost, "price": px,
            "value": qty * px, "pl_pct": (px / cost - 1) * 100 if cost else None,
            "chg_1m": tech.get("change_1m"), "chg_1y": tech.get("change_1y"), "tech": tech["verdict"],
            "pe": fund.get("pe"), "div_yield": fund.get("dividend_yield"), "beta": fund.get("beta"),
            "quarter": q.get("结论"), "quarter_note": "；".join(q.get("重点", [])[:2]),
            "events": (snap.get("新闻追踪的重大事件") or [])[:2] + (snap.get("牵连这家公司的宏观事件") or [])[:1],
            "news": [x for x in (snap.get("最近新闻") or [])[:3] if "没有找到" not in x],
            "calendar": (snap.get("公告日历") or [])[:2],
        })
        closes[t] = r["df"]["Close"]
    if not rows:
        return {"rows": [], "errors": errors}

    rates, approx = fx_rates({x["cur"] for x in rows})
    total = 0.0
    for x in rows:
        x["value_myr"] = x["value"] * rates[x["cur"]]
        x["cost_myr"] = x["qty"] * x["cost"] * rates[x["cur"]]
        total += x["value_myr"]
    for x in rows:
        x["weight"] = x["value_myr"] / total * 100 if total else 0
    rows.sort(key=lambda x: -x["weight"])
    cost_total = sum(x["cost_myr"] for x in rows)

    def alloc(key):
        s = pd.Series({}, dtype=float)
        for x in rows:
            s.loc[x[key]] = s.get(x[key], 0) + x["weight"]
        return s.sort_values(ascending=False).round(1).to_dict()

    w = np.array([x["weight"] / 100 for x in rows])
    hhi = float((w ** 2).sum())
    wavg = lambda k: (sum(x[k] * x["weight"] for x in rows if x[k] is not None) /
                      sum(x["weight"] for x in rows if x[k] is not None)) if any(x[k] is not None for x in rows) else None

    # 过去 1 年：用现在的比重回看（波动、最大回撤、相关性）
    risk = {}
    px = pd.DataFrame(closes)
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize() if getattr(px.index, "tz", None) else pd.to_datetime(px.index).normalize()
    px = px.groupby(level=0).last().ffill().dropna(how="all")
    rets = px.pct_change().dropna(how="all").fillna(0)
    if len(rets) > 40:
        wt = pd.Series({x["ticker"]: x["weight"] / 100 for x in rows})
        port = (rets[wt.index] * wt).sum(axis=1)
        curve = (1 + port).cumprod()
        risk = {"vol": float(port.std() * math.sqrt(252) * 100),
                "ret_1y": float((curve.iloc[-1] - 1) * 100),
                "max_dd": float(((curve / curve.cummax()) - 1).min() * 100),
                "curve": curve}
        if len(rows) > 1:
            corr = rets[wt.index].corr()
            names = {x["ticker"]: x["name"] for x in rows}
            pairs = [(corr.iloc[i, j], corr.index[i], corr.columns[j])
                     for i in range(len(corr)) for j in range(i + 1, len(corr)) if not math.isnan(corr.iloc[i, j])]
            if pairs:
                risk["avg_corr"] = float(np.mean([p[0] for p in pairs]))
                top = sorted(pairs, reverse=True)[:3]
                risk["top_pairs"] = [(names[a], names[b], round(float(c), 2)) for c, a, b in top]
                risk["corr"] = corr.rename(index=names, columns=names)

    out = {
        "rows": rows, "errors": errors, "fx": rates, "fx_approx": approx,
        "total_myr": total, "cost_myr": cost_total, "pl_myr": total - cost_total,
        "by_sector": alloc("sector"), "by_market": alloc("market"), "by_cur": alloc("cur"),
        "top_weight": rows[0]["weight"], "eff_n": 1 / hhi if hhi else None,
        "div_yield": wavg("div_yield"), "pe": wavg("pe"), "beta": wavg("beta"), "risk": risk,
    }
    out["flags"] = flags(out)
    return out


def flags(p: dict) -> list[str]:
    """规则检查：明显的问题（不靠 AI）。"""
    f = []
    for x in p["rows"]:
        if x["weight"] >= 25:
            f.append(f"⚠️ {x['name']} 占了 {x['weight']:.0f}%：一只股票出事，整个组合会受很大影响（一般建议单一股票不超过 15–20%）")
        if x["pl_pct"] is not None and x["pl_pct"] <= -25:
            f.append(f"🔻 {x['name']} 亏了 {x['pl_pct']:.0f}%：值得重新检查当初买入的理由还在不在")
        if x["quarter"] in ("偏弱", "疲弱"):
            f.append(f"📉 {x['name']} 最新季报「{x['quarter']}」")
    for k, v in p["by_sector"].items():
        if v >= 40 and len(p["rows"]) > 2:
            f.append(f"🧩 {k} 板块占 {v:.0f}%：组合很依赖这个行业的景气")
    if p["eff_n"] and len(p["rows"]) >= 3 and p["eff_n"] < 4:
        f.append(f"🎯 按比重算，组合实际上只等于分散在约 {p['eff_n']:.1f} 只股票")
    r = p["risk"]
    if r.get("avg_corr") is not None and r["avg_corr"] >= 0.5:
        f.append(f"🔗 股票之间平均相关性 {r['avg_corr']:.2f}：经常一起涨一起跌，分散效果有限")
    if len(p["by_cur"]) == 1 and len(p["rows"]) >= 3:
        f.append(f"💱 全部是 {next(iter(p['by_cur']))} 资产：没有其他货币分散")
    return f


SYSTEM = """你是一位谨慎、诚实的投资组合分析员，帮一位投资新手做「组合体检」。今天是 {today}。
你会收到：每只持股的数字（比重、盈亏、估值、技术面、最新季报、近期新闻）、整个组合的分布和风险数字、规则检查发现的问题，以及投资者自己的目标。

规则：
- 数字只能用提供的；近况只能根据提供的新闻和季报（你的知识可能过时）；不要编造
- 你不是持牌投资顾问：给「可以考虑」的方向和理由，不要下「马上买 / 卖」的指令，不要给目标价
- 要对照投资者的目标、持有时间、能接受的下跌来评价（例如目标是收息，就看股息率够不够、稳不稳）
- 用简体中文，口语化，专业名词第一次出现时用括号解释；不要用 Markdown 符号（不要 **、#）

严格按下面格式输出（总共约 900-1300 字）：
【总评】3-4 句：这个组合整体是什么风格、跟目标配不配、最大的问题是什么；最后给一个体检等级：健康 / 尚可 / 需要调整 / 风险偏高
【做得好的地方】2-3 点，用 1. 2. 3.
【主要风险】3-4 点，用 1. 2. 3.，每点说清楚可能怎样亏钱（引用比重、相关性、回撤等数字）
【每只股票】每只一行：名称 — 现在的情况（盈亏、季报、新闻）+ 在组合里的角色 + 需要注意什么
【可以考虑的调整】3-5 点，用 1. 2. 3.：例如降低哪一只 / 哪个板块的比重、可以补充什么类型的资产（说类型，例如防守型、收息型、其他市场，不要点名推荐具体股票）、哪只要重新检查买入理由
【接下来要追踪的事】2-4 点：即将到来的业绩日 / 除权日、要留意的新闻或数字"""


def brief(p: dict, goal: str, horizon: str, dd: str) -> str:
    r = p["risk"]
    data = {
        "投资者": {"目标": goal, "打算持有": horizon, "能接受的下跌": dd},
        "组合": {"总市值(令吉)": round(p["total_myr"]), "总盈亏%": _pct((p["total_myr"] / p["cost_myr"] - 1) * 100 if p["cost_myr"] else None),
                 "股票数": len(p["rows"]), "最大一只比重%": _pct(p["top_weight"]), "实际分散相当于几只": _pct(p["eff_n"]),
                 "板块分布%": p["by_sector"], "市场分布%": p["by_market"], "货币分布%": p["by_cur"],
                 "加权股息率%": _pct(p["div_yield"], 2), "加权本益比": _pct(p["pe"]), "加权beta": _pct(p["beta"], 2),
                 "过去1年(按现在比重)回报%": _pct(r.get("ret_1y")), "年化波动%": _pct(r.get("vol")),
                 "最大回撤%": _pct(r.get("max_dd")), "平均相关性": _pct(r.get("avg_corr"), 2),
                 "最相关的几对": r.get("top_pairs")},
        "规则检查发现": p["flags"],
        "持股": [{"名称": x["name"], "代码": x["ticker"], "板块": x["sector"], "比重%": _pct(x["weight"]),
                  "盈亏%": _pct(x["pl_pct"]), "1个月%": _pct(x["chg_1m"]), "1年%": _pct(x["chg_1y"]),
                  "本益比": _pct(x["pe"]), "股息率%": _pct(x["div_yield"], 2), "技术面": x["tech"],
                  "最新季报": x["quarter"], "季报重点": x["quarter_note"] or None,
                  "重大事件": x["events"] or None, "最近新闻": x["news"] or None, "公告日历": x["calendar"] or None}
                 for x in p["rows"]],
    }
    return json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":"))


async def ai_report(p: dict, goal: str, horizon: str, dd: str) -> str:
    import managers as M
    return await M.chat(SYSTEM.format(today=f"{date.today():%Y年%m月%d日}"),
                        f"请帮这个投资组合做体检：\n{brief(p, goal, horizon, dd)}", max_tokens=3000)
