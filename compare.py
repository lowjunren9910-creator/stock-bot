"""
compare.py - 股票对比（2 到 3 家）

把几家公司放在同一张表：估值、获利能力、成长、财务、股价表现、最新季报、公司体检评级，
每一行标出谁比较好，最后请 AI 用中文总结「谁适合什么样的投资者」。

用法：
  build(["MAYBANK", "PBBANK", "CIMB"])          → 对比数据
  ai_verdict(data)                                → AI 总结（异步）
  to_telegram_html(data, ai)                      → Telegram 消息

不同市场也可以比（例如 Inari vs NVIDIA），但货币不同，金额类数字只看比例就好。
"""

from __future__ import annotations

import html
import json

import pandas as pd

import analysis as A
import fundamentals as F

# (键, 中文, 越大越好? True/False/None=不比较, 格式)
METRICS = [
    ("price", "股价", None, "price"),
    ("mcap", "市值", None, "big"),
    ("pe", "本益比 P/E", False, "x"),
    ("pb", "股价/净值 P/B", False, "x"),
    ("div_yield", "股息率", True, "pct"),
    ("roe", "股东权益回报 ROE", True, "pct"),
    ("margin", "净利率", True, "pct"),
    ("rev_growth", "营收增长（按年）", True, "pct"),
    ("eps_growth", "盈利增长（按年）", True, "pct"),
    ("debt_equity", "负债/股东权益", False, "pct0"),
    ("chg_1m", "股价 1 个月", True, "pctc"),
    ("chg_3m", "股价 3 个月", True, "pctc"),
    ("chg_1y", "股价 1 年", True, "pctc"),
    ("from_high", "距 52 周高点", None, "pctc"),
    ("rsi", "RSI（14 日）", None, "n0"),
    ("q_verdict", "最新季报", None, "text"),
    ("level", "公司体检评级", None, "text"),
]
SCORED = [k for k, _, better, _ in METRICS if better is not None]


def _pct(v):
    if v is None:
        return None
    v = float(v)
    return round(v * 100, 2)


def _div(v):
    if v is None:
        return None
    v = float(v)
    return round(v if v > 1 else v * 100, 2)


def one(text: str, px: pd.DataFrame | None = None, deep: bool = True) -> dict:
    t = A.normalize_ticker(text)
    i = F.info(t)
    if px is None:
        px = F.prices([t], "1y").get(t)
    import universe
    x = {"ticker": t, "input": text, "name": universe.name_of(t) or i.get("shortName") or i.get("longName") or t,
         "currency": i.get("currency") or "", "market": A.market_of(t),
         "sector": i.get("sector"), "industry": i.get("industry"),
         "mcap": i.get("marketCap"), "pe": i.get("trailingPE"), "pb": i.get("priceToBook"),
         "div_yield": _div(i.get("dividendYield")), "roe": _pct(i.get("returnOnEquity")),
         "margin": _pct(i.get("profitMargins")), "rev_growth": _pct(i.get("revenueGrowth")),
         "eps_growth": _pct(i.get("earningsGrowth")), "debt_equity": i.get("debtToEquity")}
    if x["sector"] == "Financial Services":
        x["debt_equity"] = None          # 银行的负债结构不能这样比
    if px is not None and len(px):
        import scanner as S
        c = px["Close"].dropna()
        p = float(c.iloc[-1])
        ret = lambda n: round((p / float(c.iloc[-n - 1]) - 1) * 100, 2) if len(c) > n else None
        x.update(price=round(p, 3), chg_1m=ret(21), chg_3m=ret(63), chg_1y=ret(len(c) - 1 if len(c) < 250 else 249),
                 from_high=round((p / float(c.tail(252).max()) - 1) * 100, 2), rsi=round(S.rsi(c), 0),
                 series={"dates": [d.strftime("%Y-%m-%d") for d in c.index],
                         "rebased": [round(float(v) / float(c.iloc[0]) * 100, 2) for v in c]})
    if deep:
        try:
            import quarterly
            q = quarterly.analyze(quarterly.statement(t))
            if q:
                x["quarter"] = q
                x["q_verdict"] = f"{q['icon']} {q['verdict']}（{q['period']}）"
        except Exception:
            pass
        try:
            import company
            sc = company.scorecard(company.fetch(t))
            x["scores"] = sc
            x["level"] = sc["level"]
        except Exception:
            pass
    return x


def build(texts: list[str], deep: bool = True) -> dict:
    texts = [s.strip() for s in texts if s and s.strip()][:3]
    if len(texts) < 2:
        raise ValueError("请给 2 到 3 只股票，例如：MAYBANK PBBANK CIMB")
    tickers = [A.normalize_ticker(s) for s in texts]
    if len(set(tickers)) < len(tickers):
        raise ValueError("有重复的股票，请换一只。")
    px = F.prices(tickers, "1y")
    stocks = [one(s, px.get(t), deep) for s, t in zip(texts, tickers)]

    wins = {s["ticker"]: 0 for s in stocks}
    best = {}
    for k, _, better, _ in METRICS:
        if better is None:
            continue
        vals = [(s["ticker"], s.get(k)) for s in stocks if s.get(k) is not None]
        if k == "pe":
            vals = [(t, v) for t, v in vals if v > 0]        # 亏损公司没有本益比
        if len(vals) < 2:
            continue
        t_best = (max if better else min)(vals, key=lambda tv: tv[1])[0]
        best[k] = t_best
        wins[t_best] += 1
    currencies = {s["currency"] for s in stocks}
    return {"stocks": stocks, "best": best, "wins": wins, "metrics": METRICS,
            "mixed_currency": len(currencies) > 1}


def fmt(v, kind: str, cur: str = "") -> str:
    if v is None:
        return "—"
    if kind == "price":
        return f"{v:,.3f}" if v < 1 else f"{v:,.2f}"
    if kind == "big":
        a = abs(v)
        return (f"{v / 1e12:.2f}T" if a >= 1e12 else f"{v / 1e9:.1f}B" if a >= 1e9 else f"{v / 1e6:.0f}M")
    if kind == "x":
        return f"{v:.1f}"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "pct0":
        return f"{v:.0f}%"
    if kind == "pctc":
        return f"{v:+.1f}%"
    if kind == "n0":
        return f"{v:.0f}"
    return str(v)


def table(data: dict) -> pd.DataFrame:
    """给网站用的表格：行 = 指标，列 = 股票。最好的加 ✓。"""
    cols = {}
    for s in data["stocks"]:
        col = []
        for k, label, better, kind in METRICS:
            v = fmt(s.get(k), kind, s["currency"])
            if data["best"].get(k) == s["ticker"]:
                v += " ✓"
            col.append(v)
        cols[f"{s['name']}\n{s['ticker']}"] = col
    return pd.DataFrame(cols, index=[m[1] for m in METRICS])


async def ai_verdict(data: dict) -> str | None:
    import managers as M
    if M.check_setup():
        return None
    brief = []
    for s in data["stocks"]:
        b = {"公司": f"{s['name']} ({s['ticker']})", "行业": s.get("industry"), "货币": s["currency"]}
        for k, label, _, kind in METRICS:
            if k not in ("price", "series"):
                b[label] = fmt(s.get(k), kind)
        if s.get("quarter"):
            b["季报重点"] = s["quarter"]["reasons"]
        brief.append(b)
    system = ("你是资深基金经理。用户在比较几只股票。根据提供的数据，用简体中文写 250 字以内的对比总结："
              "1) 每只股票一句话说出最大优势和最大风险；2) 分别说明哪只比较适合「价值型」「成长型」「收息型」投资者"
              "（没有明显适合的就说没有）；3) 最后一句提醒这只是数据对比、要再看公司基本面，不构成买卖建议。"
              "只用提供的数字，不要编造新闻或事件。不要用 Markdown。")
    return await M.chat(system, json.dumps(brief, ensure_ascii=False, default=str), 700)


def to_telegram_html(data: dict, ai: str | None = None) -> str:
    e = html.escape
    ss = data["stocks"]
    lines = ["<b>⚖️ 股票对比</b>", "　vs　".join(f"<b>{e(s['name'])}</b> <code>{s['ticker']}</code>" for s in ss), ""]
    for k, label, better, kind in METRICS:
        vals = []
        for s in ss:
            v = fmt(s.get(k), kind)
            if data["best"].get(k) == s["ticker"]:
                v = f"<b>{v}✓</b>"
            vals.append(v)
        if any(s.get(k) is not None for s in ss):
            lines.append(f"{e(label)}：" + " ｜ ".join(vals))
    lines.append("")
    lines.append("胜出项目：" + "，".join(f"{e(s['name'])} {data['wins'][s['ticker']]} 项" for s in ss))
    if data["mixed_currency"]:
        lines.append("<i>注意：货币不同，股价和市值不能直接比。</i>")
    if ai:
        lines += ["", "<b>🧠 AI 总结</b>", e(ai)]
    lines += ["", "<i>✓ = 这一项比较好。仅供参考，不构成投资建议。</i>"]
    return "\n".join(lines)


if __name__ == "__main__":
    import asyncio
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    d = build(sys.argv[1:] or ["MAYBANK", "PBBANK"])
    print(to_telegram_html(d, asyncio.run(ai_verdict(d))))
