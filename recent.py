"""「近期动态」：给 AI 基金经理的最新资料，让分析跟得上最近发生的事。

AI 模型本身的知识停在训练那天（可能是一年多前），它「记得」的公司情况可能已经过时。
所以每次分析都附上：
  1. 最近 14 天的新闻（Google 新闻 + Yahoo，附日期和来源）
  2. 新闻追踪已经分析过的重大事件、牵连到这家公司的宏观事件（利率、油价、关税…）
  3. 最新一季业绩（营收、净利按年变化）
  4. 公告日历：最近 / 即将到来的业绩日、除权日
  5. 股价最近 5 天、1 个月的走势
任何一项抓不到就跳过，不影响分析。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
MYT = timezone(timedelta(hours=8))
DAYS = 14


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _day(iso: str) -> str:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(MYT)
        return f"{d.month}月{d.day}日"
    except Exception:
        return str(iso)[:10]


def news_items(ticker: str, limit: int = 10) -> list[dict]:
    """[{title, source, link, published, summary}]，新的在前。失败回传 []。"""
    try:
        import news as N
        return N.recent(ticker, DAYS, limit)
    except Exception as e:
        print(f"  近期新闻失败（{ticker}）：{e}")
        return []


def tracked_events(ticker: str) -> tuple[list[str], list[str]]:
    """新闻追踪（feed.json）里这家公司的事件 + 牵连它的宏观事件。"""
    feed = _load(ROOT / "reports" / "news" / "feed.json") or {}
    cut = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    own, macro = [], []
    for e in feed.get("events", []):
        if e.get("published", "") < cut:
            continue
        if e.get("type") == "macro":
            a = next((a for a in e.get("affected", []) if a.get("ticker") == ticker), None)
            if a:
                macro.append(f"{_day(e['published'])}：{e['headline_zh']}（对这家公司：短期{a['short_term']['view']}，"
                             f"{a['short_term']['why']}；长期{a['long_term']['view']}）")
        elif e.get("ticker") == ticker:
            own.append(f"{_day(e['published'])}：{e['headline_zh']}（重要性 {e.get('importance')}/5；"
                       f"短期{e['short_term']['view']}，长期{e['long_term']['view']}）")
    return own[:6], macro[:4]


def latest_quarter(ticker: str) -> dict | None:
    try:
        import quarterly as Q
        df = Q.statement(ticker)
        x = Q.analyze(df) if df is not None else None
    except Exception:
        return None
    if not x:
        return None
    r = lambda v: None if v is None else round(float(v), 1)
    return {"季度结束日": x["period"], "结论": x.get("verdict"), "营收按年%": r(x.get("rev_yoy")),
            "净利按年%": r(x.get("net_yoy")), "营收按季%": r(x.get("rev_qoq")), "净利按季%": r(x.get("net_qoq")),
            "净利率%": x.get("net_margin"), "重点": x.get("reasons", [])[:4]}


def calendar_items(ticker: str) -> list[str]:
    data = _load(ROOT / "reports" / "calendar" / "events.json") or {}
    today = datetime.now(MYT).date()
    lo, hi = str(today - timedelta(days=DAYS)), str(today + timedelta(days=45))
    out = []
    for e in data.get("events", []):
        if e.get("ticker") == ticker and lo <= e["date"] <= hi:
            out.append(f"{e['date']}：{e['title']}（{e['status']}）")
    return out[:5]


def price_moves(df) -> dict:
    try:
        c = df["Close"].dropna()
        last = float(c.iloc[-1])
        ch = lambda n: round((last / float(c.iloc[-1 - n]) - 1) * 100, 1) if len(c) > n else None
        return {"最后交易日": str(c.index[-1].date()), "5日涨跌%": ch(5), "1个月涨跌%": ch(21), "3个月涨跌%": ch(63)}
    except Exception:
        return {}


def context(ticker: str, df=None, items: list[dict] | None = None) -> dict:
    """给 AI 的「近期动态」区块（纯文字 / 数字）。items：已经抓好的新闻（避免重复抓）。"""
    items = news_items(ticker) if items is None else items
    own, macro = tracked_events(ticker)
    out = {
        "说明": f"以下是截至今天的最新资料（最近 {DAYS} 天）。如果跟你记忆中的公司情况不同，以这里为准。",
        "股价走势": price_moves(df) if df is not None else {},
        "最近新闻": [f"{_day(i['published'])} {i.get('source') or ''}：{i['title'][:140]}"
                     + (f" —— {i['summary'][:160]}" if k < 3 and i.get("summary") and i["summary"][:40] not in i["title"] else "")
                     for k, i in enumerate(items[:8])] or ["最近 14 天没有找到这家公司的新闻"],
    }
    if own:
        out["新闻追踪的重大事件"] = own
    if macro:
        out["牵连这家公司的宏观事件"] = macro
    q = latest_quarter(ticker)
    if q:
        out["最新一季业绩"] = q
    cal = calendar_items(ticker)
    if cal:
        out["公告日历"] = cal
    return out
