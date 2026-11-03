"""
screener.py - 选股雷达：每日找出 错杀股 / 成长股 / 双杀股

三种类型（规则透明，可以在 RULES 里自己调）：

  🎯 错杀股：股价大跌，但公司本身没变差 → 可能被市场错杀，值得研究
       股价：距 52 周高点跌 ≥ 20%，或 3 个月跌 ≥ 15%
       盈利：最近盈利增长 ≥ -5%（没有明显恶化）
       质量：ROE ≥ 8%
       估值：本益比比自己过去几年平均便宜（有历史数据时）

  🚀 成长股：营收和盈利都在高速增长，股价趋势也向上
       营收增长 ≥ 10%、盈利增长 ≥ 15%、ROE ≥ 12%
       股价在 200 日均线之上（基本面没走坏的话，跌破均线的标为「成长股·回调中」）

  ⚠️ 双杀股（戴维斯双杀）：盈利下滑 + 估值也被市场调低 → 股价受双重打击，要小心
       盈利增长 ≤ -10%
       6 个月股价跌 ≥ 15%
       本益比比历史平均低，或股价跌幅大于盈利跌幅（代表估值被压缩）

只扫描大型、成交活跃的股票（与每日焦点相同的门槛），避开投机股。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

import fundamentals as F
import scanner as S

REPORT_DIR = Path(__file__).parent / "reports" / "screen"

RULES = {
    "oversold": {"drawdown": -20, "ret_3m": -15, "eps_growth_min": -5, "roe_min": 8, "pe_discount": -10},
    "growth": {"rev_growth": 10, "eps_growth": 15, "roe_min": 12},
    "double_kill": {"eps_growth_max": -10, "ret_6m": -15, "pe_discount": -10},
}

CATEGORIES = {
    "oversold": ("🎯 错杀股", "股价大跌，但盈利和质量没变差，估值比自己历史便宜，可能被市场错杀。"),
    "growth": ("🚀 成长股", "营收和盈利高速增长、回报率高，股价趋势向上。"),
    "double_kill": ("⚠️ 双杀股", "盈利下滑 + 市场给的估值也被调低，股价受双重打击，宜避开或等企稳。"),
}


def universe(market: str) -> dict:
    if market == "bursa":
        import klci
        return klci.UNIVERSE
    return S.MARKETS[market].universe


def pct(x):
    return None if x is None or pd.isna(x) else float(x) * 100


def features(t: str, name: str, df: pd.DataFrame, m: S.Market) -> dict | None:
    c = df["Close"]
    price = float(c.iloc[-1])
    hist = df.iloc[:-1]
    avg_turnover = float((hist["Close"] * hist["Volume"]).tail(20).mean())
    if price < m.min_price or avg_turnover < m.min_turnover:
        return None  # 低价或成交冷清：不看

    i = F.info(t)
    ret = lambda n: (price / float(c.iloc[-n - 1]) - 1) * 100 if len(c) > n else None
    year = c.tail(252)
    sma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None

    # 盈利增长：先用最近一季按年增长，没有就用最近两个财年 EPS
    eps_g = pct(i.get("earningsGrowth"))
    rev_g = pct(i.get("revenueGrowth"))
    eps = F.annual_eps(t)
    if eps_g is None and len(eps) >= 2 and eps.iloc[-2] > 0:
        eps_g = (eps.iloc[-1] / eps.iloc[-2] - 1) * 100

    pe = i.get("trailingPE")
    if pe is None and i.get("trailingEps") and i["trailingEps"] > 0:
        pe = price / i["trailingEps"]
    pe_avg = F.historical_pe(t, df)
    pe_disc = (pe / pe_avg - 1) * 100 if (pe and pe_avg and pe > 0) else None
    growth_for_peg = eps_g if eps_g and eps_g > 0 else None

    return {
        "ticker": t, "name": name, "price": round(price, 3), "currency": m.currency,
        "sector": i.get("sector"),
        "ret_1m": ret(21), "ret_3m": ret(63), "ret_6m": ret(126),
        "drawdown": (price / float(year.max()) - 1) * 100,
        "rsi": S.rsi(c),
        "above_200": bool(sma200 and price > sma200),
        "rev_growth": rev_g, "eps_growth": eps_g,
        "roe": pct(i.get("returnOnEquity")),
        "debt_equity": i.get("debtToEquity"),
        "pe": pe, "pe_avg": pe_avg, "pe_discount": pe_disc,
        "peg": pe / growth_for_peg if (pe and growth_for_peg) else None,
        "div_yield": pct(i.get("dividendYield") / 100 if (i.get("dividendYield") or 0) > 1
                         else i.get("dividendYield")),
    }


def classify(x: dict) -> list[tuple[str, float, list[str]]]:
    """返回 [(类别, 分数, 理由列表)]，一只股票可能不属于任何类别。"""
    out = []
    g = lambda k: x.get(k)
    eg, rg, roe, dd, r3, r6, pd_ = (g("eps_growth"), g("rev_growth"), g("roe"),
                                    g("drawdown"), g("ret_3m"), g("ret_6m"), g("pe_discount"))

    # 🎯 错杀股
    R = RULES["oversold"]
    hit = (dd is not None and dd <= R["drawdown"]) or (r3 is not None and r3 <= R["ret_3m"])
    if hit and eg is not None and eg >= R["eps_growth_min"] and roe is not None and roe >= R["roe_min"] \
            and (pd_ is None or pd_ <= R["pe_discount"]):
        why = [f"距 52 周高点 {dd:.0f}%", f"盈利增长 {eg:+.0f}%", f"ROE {roe:.0f}%"]
        if pd_ is not None:
            why.append(f"本益比比历史平均低 {abs(pd_):.0f}%")
        if g("rsi") and g("rsi") < 35:
            why.append(f"RSI {g('rsi'):.0f} 超卖")
        score = abs(dd) + max(0, eg) * 0.5 + (abs(pd_) * 0.5 if pd_ else 0) + (5 if (g("rsi") or 50) < 35 else 0)
        out.append(("oversold", round(score, 1), why))

    # 🚀 成长股
    R = RULES["growth"]
    if rg is not None and eg is not None and roe is not None \
            and rg >= R["rev_growth"] and eg >= R["eps_growth"] and roe >= R["roe_min"]:
        why = [f"营收增长 {rg:+.0f}%", f"盈利增长 {eg:+.0f}%", f"ROE {roe:.0f}%"]
        if g("peg"):
            why.append(f"PEG {g('peg'):.2f}" + ("（相对便宜）" if g("peg") < 1 else ""))
        why.append("股价在 200 日均线之上" if g("above_200") else "回调中：股价跌破 200 日均线")
        score = min(rg, 60) + min(eg, 100) * 0.6 + min(roe, 40) * 0.5 + (10 if g("above_200") else 0)
        out.append(("growth", round(score, 1), why))

    # ⚠️ 双杀股
    R = RULES["double_kill"]
    if eg is not None and r6 is not None and eg <= R["eps_growth_max"] and r6 <= R["ret_6m"]:
        squeezed = (pd_ is not None and pd_ <= R["pe_discount"]) or (abs(r6) > abs(eg))
        if squeezed:
            why = [f"盈利增长 {eg:+.0f}%", f"6 个月股价 {r6:+.0f}%"]
            why.append(f"本益比比历史平均低 {abs(pd_):.0f}%" if pd_ is not None and pd_ < 0
                       else "股价跌幅大于盈利跌幅（估值被压缩）")
            score = abs(r6) + min(abs(eg), 100) * 0.6
            out.append(("double_kill", round(score, 1), why))
    return out


def screen(market: str, now: datetime | None = None, with_ai: bool = True) -> dict:
    m = S.MARKETS[market]
    now = now or datetime.now(m.zone())
    uni = universe(market)
    px = F.prices(list(uni), "5y")
    F.prefetch(list(px))

    rows, buckets = [], {k: [] for k in CATEGORIES}
    for t, df in px.items():
        try:
            x = features(t, uni[t], df, m)
        except Exception as e:
            print(f"  {t} 计算失败：{e}")
            continue
        if x is None:
            continue
        rows.append(x)
        for cat, score, why in classify(x):
            buckets[cat].append({**x, "score": score, "reasons": why})

    clean = lambda d: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}
    report = {
        "market": market, "market_name": m.name, "date": str(now.date()),
        "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"), "scanned": len(rows),
        "counts": {k: len(v) for k, v in buckets.items()},
        "rules": RULES, "ai_comment": None,
    }
    for cat, items in buckets.items():
        report[cat] = [clean(x) for x in sorted(items, key=lambda r: r["score"], reverse=True)[:10]]
    if with_ai:
        report["ai_comment"] = ai_comment(report)
    return report


def ai_comment(r: dict) -> str | None:
    try:
        import asyncio
        import managers as M
        if M.check_setup():
            return None
        brief = {CATEGORIES[k][0]: [{"股票": f"{x['name']} ({x['ticker']})", "理由": x["reasons"]}
                                    for x in r[k][:5]] for k in CATEGORIES}
        system = ("你是资深基金经理。根据选股雷达结果，用简体中文写 200 字以内的点评："
                  "分别挑出错杀股、成长股中最值得研究的 1-2 只并说明原因，提醒双杀股要注意什么，"
                  "最后一句说明这只是筛选起点、要再看公司基本面。不要用 Markdown，不要编造数据里没有的事。")
        return asyncio.run(M.chat(system, json.dumps(brief, ensure_ascii=False), 600))
    except Exception as e:
        print("选股雷达 AI 点评失败：", e)
        return None


def save(r: dict) -> Path:
    folder = REPORT_DIR / r["market"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{r['date']}.json"
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return path


def latest(market: str) -> dict | None:
    folder = REPORT_DIR / market
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def to_telegram_html(r: dict) -> str:
    import html
    lines = [f"<b>🔍 选股雷达｜{html.escape(r['market_name'])}｜{r['date']}</b>",
             f"扫描 {r['scanned']} 只大型股"]
    for cat, (title, _) in CATEGORIES.items():
        items = r[cat][:5]
        lines += ["", f"<b>{title}（{r['counts'][cat]} 只）</b>"]
        if not items:
            lines.append("今天没有符合条件的股票")
        for x in items:
            lines.append(f"• <b>{html.escape(x['name'])}</b> {x['ticker']}：{html.escape('、'.join(x['reasons'][:3]))}")
    if r.get("ai_comment"):
        lines += ["", "<b>🧠 AI 点评</b>", html.escape(r["ai_comment"])]
    lines += ["", "<i>规则筛选结果，仅供学习研究，不构成投资建议。</i>"]
    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser(description="选股雷达")
    p.add_argument("--market", choices=S.MARKETS, default="bursa")
    p.add_argument("--no-ai", action="store_true")
    a = p.parse_args()
    r = screen(a.market, with_ai=not a.no_ai)
    print("已保存：", save(r), r["counts"])
    S.push_text(to_telegram_html(r))
