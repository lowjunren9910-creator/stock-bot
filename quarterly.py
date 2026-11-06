"""
quarterly.py - 季度报告追踪 + 快速分析

每个市场收市后跑一次：
  1. 轮流检查股票池里的公司有没有新季报（每只大约 3 天检查一次；自选股每天检查）
  2. 发现新季报 → 规则打分（营收、净利按年 / 按季增长，利润率变化）→ 一句话结论
  3. 新季报里最重要的几只（自选股优先）请 AI 写 3 句快评
  4. 推送 Telegram，存进 reports/quarterly/{市场}.json（网站和手机 app 的「季报」页面用）

也可以随时分析任何一只股票：quick("MAYBANK")（网站、Telegram /quarter 用）。

数据来源：Yahoo Finance 的季度损益表（quarterly_income_stmt）。
注意：Yahoo 通常在公司公布后几天内更新；个别公司可能缺数据。
"""

from __future__ import annotations

import html
import json
import os
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

REPORT_DIR = Path(__file__).parent / "reports" / "quarterly"
STATE_FILE = REPORT_DIR / "state.json"
ROTATION = 3          # 每只股票几天检查一次
KEEP_DAYS = 200       # 超过这么久的季报不放进「最近季报」列表

ROWS = {
    "revenue": ("Total Revenue", "Operating Revenue", "Revenue"),
    "gross": ("Gross Profit",),
    "operating": ("Operating Income", "Total Operating Income As Reported"),
    "net": ("Net Income Common Stockholders", "Net Income", "Net Income Including Noncontrolling Interests"),
    "eps": ("Diluted EPS", "Basic EPS"),
}

VERDICTS = [  # (最低分数, 结论, 图标)
    (4, "亮眼", "🌟"), (2, "稳健", "👍"), (0, "一般", "😐"), (-2, "偏弱", "👎"), (-99, "疲弱", "⚠️"),
]


# ---------------------------------------------------------------------------
# 1. 抓数据 + 分析一只股票
# ---------------------------------------------------------------------------

def statement(ticker: str) -> pd.DataFrame | None:
    """季度损益表，行 = 项目，列 = 季度结束日（新 → 旧）。"""
    import yfinance as yf
    try:
        df = yf.Ticker(ticker).quarterly_income_stmt
    except Exception:
        return None
    return df if isinstance(df, pd.DataFrame) and not df.empty else None


def _row(df: pd.DataFrame, names) -> pd.Series | None:
    for n in names:
        if n in df.index:
            r = df.loc[n]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            s = pd.to_numeric(r, errors="coerce")
            if s.notna().any():
                return s
    return None


def _g(new, old):
    """增长 %。旧数是 0 或负数时，百分比没有意义 → None。"""
    if new is None or old is None or pd.isna(new) or pd.isna(old) or old <= 0:
        return None
    return round((new / old - 1) * 100, 1)


def _f(v, nd=4):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def analyze(df: pd.DataFrame) -> dict | None:
    """规则分析最新一季。"""
    cols = sorted(pd.to_datetime(df.columns), reverse=False)
    df = df.copy()
    df.columns = pd.to_datetime(df.columns)
    df = df[cols]
    s = {k: _row(df, v) for k, v in ROWS.items()}
    if s["revenue"] is None and s["net"] is None:
        return None
    # 最新一季：营收或净利有数字的最后一列
    have = [c for c in cols if any(s[k] is not None and pd.notna(s[k].get(c)) for k in ("revenue", "net"))]
    if not have:
        return None
    last = have[-1]
    prev = have[-2] if len(have) >= 2 else None
    # 去年同季：日期相差 330~400 天
    yago = next((c for c in reversed(have[:-1]) if 330 <= (last - c).days <= 400), None)

    val = lambda k, c: None if (c is None or s[k] is None) else s[k].get(c)
    rev, net = val("revenue", last), val("net", last)
    margin = lambda c: (val("net", c) / val("revenue", c) * 100
                        if c is not None and val("net", c) is not None and val("revenue", c) not in (None, 0)
                        and pd.notna(val("net", c)) and pd.notna(val("revenue", c)) else None)
    nm, nm_y = margin(last), margin(yago)
    gm = (val("gross", last) / rev * 100) if rev and val("gross", last) is not None and pd.notna(val("gross", last)) else None

    x = {
        "period": str(last.date()), "prev_period": str(prev.date()) if prev is not None else None,
        "yoy_period": str(yago.date()) if yago is not None else None,
        "revenue": _f(rev, 0), "net": _f(net, 0), "eps": _f(val("eps", last)),
        "rev_yoy": _g(rev, val("revenue", yago)), "net_yoy": _g(net, val("net", yago)),
        "rev_qoq": _g(rev, val("revenue", prev)), "net_qoq": _g(net, val("net", prev)),
        "net_margin": _f(nm, 1), "net_margin_yoy": _f(nm_y, 1), "gross_margin": _f(gm, 1),
        "trend": {"periods": [str(c.date()) for c in have[-5:]],
                  "revenue": [_f(val("revenue", c), 0) for c in have[-5:]],
                  "net": [_f(val("net", c), 0) for c in have[-5:]]},
    }
    x.update(verdict(x, net_prev_year=val("net", yago)))
    return x


def verdict(x: dict, net_prev_year=None) -> dict:
    """打分 → 亮眼 / 稳健 / 一般 / 偏弱 / 疲弱（亏损另外标示）。"""
    score, why = 0, []
    ry, ny, rq, nq = x["rev_yoy"], x["net_yoy"], x["rev_qoq"], x["net_qoq"]
    net = x["net"]

    if ry is not None:
        score += 2 if ry >= 10 else 1 if ry >= 0 else -2 if ry <= -10 else -1
        why.append(f"营收按年 {ry:+.1f}%")
    elif rq is not None:
        score += 1 if rq >= 5 else -1 if rq <= -5 else 0
        why.append(f"营收按季 {rq:+.1f}%")

    if net is not None and net < 0:
        score -= 2
        if net_prev_year is not None and pd.notna(net_prev_year) and net_prev_year < 0 and net > net_prev_year:
            why.append("仍然亏损，但亏损比去年同期收窄")
            score += 1
        else:
            why.append("这一季亏损")
    elif ny is not None:
        score += 2 if ny >= 20 else 1 if ny >= 0 else -2 if ny <= -20 else -1
        why.append(f"净利按年 {ny:+.1f}%")
    elif net is not None and net_prev_year is not None and pd.notna(net_prev_year) and net_prev_year < 0:
        score += 2
        why.append("去年同期亏损，这一季转亏为盈")
    elif nq is not None:
        score += 1 if nq >= 10 else -1 if nq <= -10 else 0
        why.append(f"净利按季 {nq:+.1f}%")

    if x["net_margin"] is not None and x["net_margin_yoy"] is not None:
        d = x["net_margin"] - x["net_margin_yoy"]
        if d >= 1:
            score += 1
            why.append(f"净利率升到 {x['net_margin']:.1f}%（去年 {x['net_margin_yoy']:.1f}%）")
        elif d <= -1:
            score -= 1
            why.append(f"净利率降到 {x['net_margin']:.1f}%（去年 {x['net_margin_yoy']:.1f}%）")

    for cut, label, icon in VERDICTS:
        if score >= cut:
            break
    if net is not None and net < 0:
        label, icon = ("亏损收窄", "🩹") if "收窄" in " ".join(why) else ("亏损", "🔻")
    return {"score": score, "verdict": label, "icon": icon, "reasons": why}


def quick(text: str, with_ai: bool = False) -> dict:
    """随时分析一只股票的最新季报（网站、Telegram 用）。"""
    import analysis as A
    import fundamentals as F
    t = A.normalize_ticker(text)
    df = statement(t)
    if df is None:
        raise ValueError(f"找不到 {t} 的季度报告数据（Yahoo 没有这家公司的季报，或代码有误）。")
    x = analyze(df)
    if x is None:
        raise ValueError(f"{t} 的季报数据不完整，无法分析。")
    i = F.info(t)
    import universe
    x.update(ticker=t, name=universe.name_of(t) or i.get("shortName") or i.get("longName") or t,
             currency=i.get("financialCurrency") or i.get("currency") or "",
             next_earnings=_next_earnings(i))
    if with_ai:
        x["ai"] = ai_note(x)
    return x


def _next_earnings(i: dict) -> str | None:
    ts = i.get("earningsTimestamp")
    try:
        d = datetime.fromtimestamp(int(ts)).date()
        return str(d) if d >= date.today() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2. AI 快评
# ---------------------------------------------------------------------------

def ai_note(x: dict) -> str | None:
    try:
        import asyncio
        import managers as M
        if M.check_setup():
            return None
        brief = {k: x.get(k) for k in ("name", "ticker", "currency", "period", "revenue", "net", "eps",
                                        "rev_yoy", "net_yoy", "rev_qoq", "net_qoq", "net_margin",
                                        "net_margin_yoy", "gross_margin", "verdict", "reasons", "trend")}
        system = ("你是资深股票分析师。根据这家公司最新一季的财报数字，用简体中文写 3 句快评："
                  "第 1 句说这一季整体表现；第 2 句点出最值得注意的变化（好的或坏的）；"
                  "第 3 句说下一季要留意什么。只用提供的数字，不要编造原因或事件，不要用 Markdown，"
                  "不要给买卖建议。")
        return asyncio.run(M.chat(system, json.dumps(brief, ensure_ascii=False, default=str), 350))
    except Exception as e:
        print("季报 AI 快评失败：", e)
        return None


# ---------------------------------------------------------------------------
# 3. 每日轮流检查
# ---------------------------------------------------------------------------

def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def watch_tickers(market: str) -> list[str]:
    try:
        import alerts
        import analysis as A
        return [t for t in (A.normalize_ticker(s["input"]) for s in alerts.load_watchlist())
                if alerts.market_of(t) == market]
    except Exception:
        return []


def todays_slice(tickers: list[str], today: date) -> list[str]:
    k = today.toordinal() % ROTATION
    return [t for t in tickers if zlib.crc32(t.encode()) % ROTATION == k]


def run(market: str, now: datetime | None = None, push: bool = True, with_ai: bool = True) -> dict:
    import scanner as S
    import universe
    m = S.MARKETS[market]
    now = now or datetime.now(m.zone())
    today = now.date()
    uni = universe.get(market)
    watch = watch_tickers(market)
    check = sorted(set(todays_slice(list(uni), today)) | set(watch))
    print(f"  [{market}] 今天检查 {len(check)} 只的季报（股票池 {len(uni)} 只，每只约 {ROTATION} 天一次）")

    state = _load(STATE_FILE, {})
    path = REPORT_DIR / f"{market}.json"
    book = _load(path, {"items": {}})
    items = book.get("items", {})

    def one(t):
        df = statement(t)
        return t, (analyze(df) if df is not None else None)

    with ThreadPoolExecutor(6) as ex:
        results = list(ex.map(one, check))

    new = []
    for t, x in results:
        if not x:
            continue
        seen = state.get(t)
        if seen == x["period"] and t in items:
            items[t].update({k: v for k, v in x.items()})       # 数字有时会被修正：更新，但不算新
            continue
        is_new = seen is not None and x["period"] > seen     # 第一次看到这只股票：只记录，不算「新」
        state[t] = max(seen or "", x["period"])
        x.update(ticker=t, name=uni.get(t, t), currency=m.currency, watch=t in watch,
                 found=str(today) if is_new else (items.get(t) or {}).get("found"))
        if is_new:
            new.append(x)
        items[t] = x

    # 新季报：AI 快评（自选股优先，再来是分数最极端的）
    limit = int(os.getenv("QUARTERLY_AI") or 3)
    if with_ai and new:
        new.sort(key=lambda x: (not x["watch"], -abs(x["score"])))
        for x in new[:limit]:
            x["ai"] = ai_note(x)
            items[x["ticker"]]["ai"] = x["ai"]

    cutoff = str(today - timedelta(days=KEEP_DAYS))
    items = {t: x for t, x in items.items() if x.get("period", "") >= cutoff and t in uni}
    # 最近季报：季度结束日越新越前面；同一天的，新发现的排前面
    recent = sorted(items.values(), key=lambda x: (x.get("period", ""), x.get("found") or ""), reverse=True)
    report = {
        "market": market, "market_name": m.name, "currency": m.currency, "date": str(today),
        "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "tracked": len(items), "universe_size": len(uni),
        "new_today": [x["ticker"] for x in new],
        "recent": [x["ticker"] for x in recent[:60]],
        "items": items,
        "note": "数据来自 Yahoo Finance 季度损益表。「发现日期」是本系统第一次看到这份季报的日子，"
                "通常比公司公布晚 1–5 天。",
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    S.update_index()
    print(f"  [{market}] 季报：追踪 {len(items)} 家，今天发现新季报 {len(new)} 份")
    if push and new:
        S.push_text(to_telegram_html(report, new))
    return report


# ---------------------------------------------------------------------------
# 4. 显示
# ---------------------------------------------------------------------------

def big(v, cur=""):
    if v is None:
        return "—"
    a = abs(v)
    s = f"{v / 1e12:.2f} 万亿" if a >= 1e12 else f"{v / 1e9:.2f} 十亿" if a >= 1e9 else \
        f"{v / 1e6:.1f} 百万" if a >= 1e6 else f"{v:,.0f}"
    return f"{cur} {s}".strip()


def _p(v):
    return "—" if v is None else f"{v:+.1f}%"


def one_html(x: dict) -> str:
    e = html.escape
    cur = x.get("currency", "")
    lines = [f"<b>{x['icon']} {e(x['name'])}</b> <code>{x['ticker']}</code>　季报结论：<b>{x['verdict']}</b>",
             f"季度结束：{x['period']}",
             f"营收 {big(x['revenue'], cur)}（按年 {_p(x['rev_yoy'])}，按季 {_p(x['rev_qoq'])}）",
             f"净利 {big(x['net'], cur)}（按年 {_p(x['net_yoy'])}，按季 {_p(x['net_qoq'])}）"]
    if x.get("net_margin") is not None:
        lines.append(f"净利率 {x['net_margin']:.1f}%" + (f"（去年同期 {x['net_margin_yoy']:.1f}%）"
                                                         if x.get("net_margin_yoy") is not None else ""))
    if x.get("eps") is not None:
        lines.append(f"每股盈利 {x['eps']}")
    if x.get("reasons"):
        lines.append("· " + "；".join(e(r) for r in x["reasons"]))
    if x.get("ai"):
        lines += ["", f"🧠 {e(x['ai'])}"]
    if x.get("next_earnings"):
        lines.append(f"\n下一次业绩预计：{x['next_earnings']}")
    return "\n".join(lines)


def to_telegram_html(r: dict, new: list[dict]) -> str:
    lines = [f"<b>📑 新季报｜{html.escape(r['market_name'])}｜{r['date']}</b>", ""]
    for x in new[:8]:
        star = "⭐ " if x.get("watch") else ""
        lines.append(f"{star}{x['icon']} <b>{html.escape(x['name'])}</b> {x['ticker']}：<b>{x['verdict']}</b>"
                     f"\n    营收按年 {_p(x['rev_yoy'])}，净利按年 {_p(x['net_yoy'])}")
        if x.get("ai"):
            lines.append(f"    🧠 {html.escape(x['ai'])}")
    if len(new) > 8:
        lines.append(f"\n…还有 {len(new) - 8} 份，在网站或手机 app 的「季报」页面看全部。")
    lines.append("\n<i>⭐ = 你的自选股。仅供参考，不构成投资建议。</i>")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("ticker", nargs="?", help="分析一只股票，例如 MAYBANK")
    p.add_argument("--market", default="bursa")
    a = p.parse_args()
    if a.ticker:
        print(one_html(quick(a.ticker, with_ai=True)))
    else:
        run(a.market)
