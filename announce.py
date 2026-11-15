"""公告日历：股票池（约 500 只）的业绩公布日 + 派息（除权日、金额）。

资料来源（都是 Yahoo，不用额外的钥匙）：
  - 过去 6 个月的派息：yf.download(actions=True)，一次抓很多只
  - 下一次除权日、业绩日：每只股票的 Ticker.info（轮流更新：每只大约 2 天更新一次，自选股每天更新）
  - 大马股票 Yahoo 常常没有业绩日期：按 Bursa 规定「季度结束后 2 个月内要公布」推算最迟日期，标「预计」

存在 reports/calendar/：
  events.json  全部事件（网站、手机 App、Telegram 用）
  cache.json   每只股票的日期资料
  state.json   提醒发过哪些（不重复发）

自选股（watchlist.yml + news_only + Telegram /follow）明天除权、今天 / 明天公布业绩：推送 Telegram。
"""
from __future__ import annotations

import calendar as _cal
import html
import json
import os
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DIR = ROOT / "reports" / "calendar"
EVENTS = DIR / "events.json"
CACHE = DIR / "cache.json"
STATE = DIR / "state.json"
MYT = timezone(timedelta(hours=8))
CUR = {"bursa": "RM", "idx": "Rp", "us": "US$"}
MKT_ZH = {"bursa": "马股", "idx": "印尼股", "us": "美股"}
INFO_KEYS = ("exDividendDate", "lastDividendValue", "lastDividendDate", "dividendRate", "dividendYield",
             "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd", "isEarningsDateEstimate",
             "mostRecentQuarter", "currency", "shortName")
WEEK = "一二三四五六日"


def today_myt() -> date:
    return datetime.now(MYT).date()


def _load(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def _d(ts) -> date | None:
    """Yahoo 的时间戳 / 字串 → 日期（大马时间）。"""
    if ts in (None, "", 0):
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, MYT).date()
        return date.fromisoformat(str(ts)[:10])
    except Exception:
        return None


def _month_end(d: date, add_months: int) -> date:
    m = d.month - 1 + add_months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, _cal.monthrange(y, m)[1])


# ---------------------------------------------------------------------------
# 1. 我关注的公司
# ---------------------------------------------------------------------------

def my_tickers() -> set[str]:
    out = set()
    try:
        import yaml
        import analysis as A
        data = yaml.safe_load((ROOT / "watchlist.yml").read_text(encoding="utf-8")) or {}
        raw = list(data.get("stocks") or []) + list(data.get("news_only") or [])
        for s in raw:
            t = s.get("ticker") if isinstance(s, dict) else s
            if t:
                out.add(A.normalize_ticker(str(t)))
    except Exception:
        pass
    try:
        out |= set(json.loads((ROOT / "reports" / "news" / "follow.json").read_text(encoding="utf-8")))
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 2. 抓资料
# ---------------------------------------------------------------------------

def _due(ticker: str, stamp: str | None, days: float, today: date) -> bool:
    if not stamp:
        return True
    jitter = (zlib.crc32(ticker.encode()) % 100) / 100       # 让每天大约一半的股票更新，不会全部挤同一天
    try:
        return (today - date.fromisoformat(stamp[:10])).days >= days - jitter
    except Exception:
        return True


def fetch_info(ticker: str) -> dict | None:
    import yfinance as yf
    try:
        i = yf.Ticker(ticker).info or {}
    except Exception:
        return None
    if not i:
        return None
    return {k: i.get(k) for k in INFO_KEYS if i.get(k) is not None}


def refresh_info(tickers: list[str], mine: set[str], cache: dict, today: date, days: float = 2,
                 workers: int = 6, limit: int | None = None) -> int:
    todo = [t for t in tickers if t in mine or _due(t, (cache.get(t) or {}).get("stamp"), days, today)]
    if limit:
        todo = todo[:limit]
    if not todo:
        return 0
    with ThreadPoolExecutor(workers) as ex:
        for t, r in zip(todo, ex.map(fetch_info, todo)):
            if r is not None:
                cache[t] = {"stamp": str(today), **r}
    return len(todo)


def past_dividends(tickers: list[str], period: str = "6mo") -> dict[str, list[tuple[date, float]]]:
    """{代码: [(除权日, 每股金额)]}，一次抓一批。"""
    import yfinance as yf
    out: dict[str, list] = {}
    for i in range(0, len(tickers), 80):
        part = tickers[i:i + 80]
        try:
            df = yf.download(part, period=period, actions=True, group_by="ticker", progress=False,
                             auto_adjust=False, threads=True)
        except Exception as e:
            print("  派息资料失败：", e)
            continue
        if df is None or df.empty:
            continue
        for t in part:
            try:
                try:
                    sub = df[t]
                except KeyError:
                    sub = df
                s = sub["Dividends"].dropna()
            except Exception:
                continue
            s = s[s > 0]
            out[t] = [(ix.date() if hasattr(ix, "date") else _d(ix), float(v)) for ix, v in s.items()]
    return out


# ---------------------------------------------------------------------------
# 3. 整理成事件
# ---------------------------------------------------------------------------

def _amt(v: float | None, market: str) -> str:
    if v is None:
        return "金额待公布"
    c = CUR.get(market, "")
    if market == "bursa" and v < 1:
        return f"每股 {v * 100:.2f} 仙".replace(".00 仙", " 仙")
    if market == "idx":
        return f"每股 Rp{v:,.0f}" if v >= 10 else f"每股 Rp{v:,.2f}"
    return f"每股 {c}{v:,.4g}"


def _quarter_label(q_end: date | None) -> str:
    return f"截至 {q_end.year}年{q_end.month}月{q_end.day}日 的季度" if q_end else "季度业绩"


def build_for(ticker: str, name: str, market: str, info: dict, divs: list[tuple[date, float]],
              today: date, mine: set[str]) -> list[dict]:
    ev = []
    base = {"ticker": ticker, "name": name, "market": market, "mine": ticker in mine}
    # 股息：已除权（过去 6 个月）
    seen = set()
    for d, v in divs:
        if not d:
            continue
        seen.add(d)
        ev.append({**base, "type": "股息", "date": str(d), "amount": v,
                   "title": f"派息 {_amt(v, market)}", "sub": f"除权日 {d.month}月{d.day}日",
                   "status": "已除权" if d <= today else "即将除权", "estimate": False})
    # 股息：下一次除权日（还没出现在历史里）
    xd = _d(info.get("exDividendDate"))
    if xd and xd not in seen and xd >= today - timedelta(days=7):
        last = _d(info.get("lastDividendDate"))
        v = info.get("lastDividendValue") if last == xd else None
        ev.append({**base, "type": "股息", "date": str(xd), "amount": v,
                   "title": f"派息 {_amt(v, market)}", "sub": f"除权日 {xd.month}月{xd.day}日",
                   "status": "已除权" if xd <= today else "即将除权", "estimate": False})
    # 业绩
    mrq = _d(info.get("mostRecentQuarter"))
    ed = _d(info.get("earningsTimestampStart") or info.get("earningsTimestamp"))
    if ed:
        q_end = None
        if mrq:                                    # 公布的是哪一季：业绩日前至少 10 天结束的最近一季
            q = mrq
            while _month_end(q, 3) <= ed - timedelta(days=10):
                q = _month_end(q, 3)
            q_end = q if q <= ed else None
        past = ed < today
        est = bool(info.get("isEarningsDateEstimate")) and not past
        ev.append({**base, "type": "业绩", "date": str(ed), "amount": None,
                   "title": f"{_quarter_label(q_end)}业绩", "sub": ("预计 " if est else "") + f"{ed.month}月{ed.day}日公布",
                   "status": "已公布" if past else ("预计" if est else "即将公布"), "estimate": est})
    if market == "bursa" and mrq and (not ed or ed < today):
        # Bursa 规定：季度结束后 2 个月内公布 → 推算下一季最迟日期
        q_next = _month_end(mrq, 3)
        deadline = _month_end(q_next, 2)
        if deadline >= today and (not ed or deadline > ed + timedelta(days=30)):
            ev.append({**base, "type": "业绩", "date": str(deadline), "amount": None,
                       "title": f"{_quarter_label(q_next)}业绩", "sub": f"最迟 {deadline.month}月{deadline.day}日（Bursa 规定）",
                       "status": "预计", "estimate": True})
    return ev


# ---------------------------------------------------------------------------
# 4. 每天跑（scanner.run_daily_extras 收市后调用）
# ---------------------------------------------------------------------------

def run(market: str, push: bool = True, limit: int | None = None) -> dict:
    import universe
    today = today_myt()
    mine = my_tickers()
    names = universe.get(market)
    for t in mine:
        if universe.market_of(t) == market and t not in names:
            names[t] = universe.name_of(t) or t
    tickers = list(names)
    cache = _load(CACHE, {})
    n = refresh_info(tickers, mine, cache, today, float(os.getenv("CALENDAR_DAYS") or 2), limit=limit)
    print(f"  公告日历 {market}：{len(tickers)} 只，更新了 {n} 只的日期资料")
    divs = past_dividends(tickers)
    evs = []
    for t in tickers:
        try:
            evs += build_for(t, names[t], market, cache.get(t) or {}, divs.get(t, []), today, mine)
        except Exception as e:
            print(f"  {t} 失败：{e}")
    lo, hi = str(today - timedelta(days=95)), str(today + timedelta(days=100))
    data = _load(EVENTS, {"events": []})
    keep = [e for e in data.get("events", []) if e.get("market") != market]
    for e in keep:                                   # 别的市场的也更新「是不是自选股」
        e["mine"] = e["ticker"] in mine
    data["events"] = sorted([e for e in keep + evs if lo <= e["date"] <= hi], key=lambda e: (e["date"], e["ticker"]))
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data.setdefault("markets", {})[market] = {"stocks": len(tickers), "updated": data["updated"]}
    DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    EVENTS.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  公告日历：{market} {len(evs)} 个事件，全部 {len(data['events'])} 个")
    if push:
        remind(data["events"], market, today)
    return data


def remind(events: list[dict], market: str, today: date):
    """自选股：明天除权、今天 / 明天公布业绩 → Telegram。同一件事只发一次。"""
    import scanner as S
    state = _load(STATE, {"pushed": {}})
    pushed = state.setdefault("pushed", {})
    tmr = str(today + timedelta(days=1))
    hits = [e for e in events if e.get("mine") and e["market"] == market and not e.get("estimate")
            and ((e["type"] == "股息" and e["date"] == tmr) or (e["type"] == "业绩" and e["date"] in (str(today), tmr)))]
    hits = [e for e in hits if f"{e['ticker']}:{e['type']}:{e['date']}" not in pushed]
    if hits:
        x = html.escape
        lines = [f"📅 <b>{MKT_ZH[market]}公告提醒</b>（你关注的公司）", ""]
        for e in hits:
            when = "明天" if e["date"] == tmr else "今天"
            if e["type"] == "股息":
                lines.append(f"💰 <b>{x(e['name'])}</b> {when}除权：{x(e['title'])}\n　<i>想拿这次股息，今天收市前要持有。</i>")
            else:
                lines.append(f"📊 <b>{x(e['name'])}</b> {when}公布{x(e['title'])}")
        S.push_text("\n".join(lines))
        for e in hits:
            pushed[f"{e['ticker']}:{e['type']}:{e['date']}"] = str(today)
    cut = str(today - timedelta(days=30))
    state["pushed"] = {k: v for k, v in pushed.items() if v >= cut}
    DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. 查询（网站 / Telegram 共用）
# ---------------------------------------------------------------------------

PERIODS = ["上月", "本周", "本月", "下月", "未来 3 个月"]


def period_range(name: str, today: date | None = None) -> tuple[date, date]:
    t = today or today_myt()
    if name == "本周":
        s = t - timedelta(days=t.weekday())
        return s, s + timedelta(days=6)
    if name == "下周":
        s = t - timedelta(days=t.weekday()) + timedelta(days=7)
        return s, s + timedelta(days=6)
    if name == "上月":
        e = t.replace(day=1) - timedelta(days=1)
        return e.replace(day=1), e
    if name == "下月":
        s = _month_end(t, 0) + timedelta(days=1)
        return s, _month_end(s, 0)
    if name == "未来 3 个月":
        return t, t + timedelta(days=92)
    return t.replace(day=1), _month_end(t, 0)          # 本月


def weeks(s: date, e: date) -> list[tuple[date, date]]:
    out, d = [], s
    while d <= e:
        w_end = min(d + timedelta(days=6 - d.weekday()), e)
        out.append((d, w_end))
        d = w_end + timedelta(days=1)
    # 头尾不到 3 天的零碎几天：并进旁边那一周（例如 11月1日 星期天 → 11月1日–11月8日）
    if len(out) > 1 and (out[0][1] - out[0][0]).days < 2:
        out[:2] = [(out[0][0], out[1][1])]
    if len(out) > 1 and (out[-1][1] - out[-1][0]).days < 2:
        out[-2:] = [(out[-2][0], out[-1][1])]
    return out


def buckets(per: str, s: date, e: date) -> list[tuple[date, date]]:
    """日历分组：「未来 3 个月」按月，其他按周。"""
    if per != "未来 3 个月":
        return weeks(s, e)
    out, d = [], s
    while d <= e:
        m_end = min(_month_end(d, 0), e)
        out.append((d, m_end))
        d = m_end + timedelta(days=1)
    if len(out) > 1 and (out[-1][1] - out[-1][0]).days < 7:
        out[-2:] = [(out[-2][0], out[-1][1])]
    return out


def select(events: list[dict], s: date, e: date, market: str | None = None, kind: str | None = None,
           only_mine: bool = False, query: str = "") -> list[dict]:
    q = query.strip().lower()
    return [x for x in events if str(s) <= x["date"] <= str(e)
            and (not market or x["market"] == market) and (not kind or x["type"] == kind)
            and (not only_mine or x.get("mine"))
            and (not q or q in x["ticker"].lower() or q in (x["name"] or "").lower())]


def countdown(d: str, today: date | None = None) -> str:
    t = today or today_myt()
    n = (date.fromisoformat(d) - t).days
    return "今天" if n == 0 else "明天" if n == 1 else "昨天" if n == -1 else f"还有 {n} 天" if n > 0 else f"{-n} 天前"


def day_label(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.year}年{x.month}月{x.day}日周{WEEK[x.weekday()]}"


def to_telegram_html(arg: str = "") -> str:
    """/calendar [本周|下周|本月|代码]：默认 = 你关注的公司，未来 30 天。"""
    import analysis as A
    data = _load(EVENTS, None)
    if not data:
        return "还没有公告日历资料。收市后的自动任务跑过一次就会有。"
    arg = (arg or "").strip()
    today = today_myt()
    x = html.escape
    if arg in ("本周", "下周", "本月", "下月", "上月"):
        s, e = period_range(arg, today)
        evs = select(data["events"], s, e)
        mine = [v for v in evs if v.get("mine")]
        head = f"📅 <b>公告日历 · {arg}</b>（{s.month}/{s.day}–{e.month}/{e.day}）\n共 {len(evs)} 项：业绩 {sum(v['type'] == '业绩' for v in evs)}、派息 {sum(v['type'] == '股息' for v in evs)}"
        show = mine + [v for v in evs if not v.get("mine")][:max(0, 25 - len(mine))]
    elif arg:
        t = A.normalize_ticker(arg)
        show = [v for v in data["events"] if v["ticker"] == t]
        head = f"📅 <b>{x(show[0]['name'] if show else t)} 的公告日历</b>"
        if not show:
            return head + "\n\n最近 3 个月没有找到业绩或派息日期（可能不在股票池里）。"
    else:
        evs = select(data["events"], today - timedelta(days=3), today + timedelta(days=30), only_mine=True)
        head = "📅 <b>你关注的公司 · 未来 30 天</b>"
        show = evs
        if not show:
            return head + "\n\n没有找到日期。试试 /calendar 本周 看全部，或 /calendar 代码 查一家。"
    lines = [head, ""]
    cur = None
    for v in sorted(show, key=lambda v: v["date"])[:40]:
        if v["date"] != cur:
            cur = v["date"]
            lines.append(f"<b>{day_label(cur)}</b>　<i>{countdown(cur, today)}</i>")
        icon = "💰" if v["type"] == "股息" else "📊"
        star = "⭐" if v.get("mine") else ""
        lines.append(f"{icon}{star} {x(v['name'])} <code>{x(v['ticker'])}</code>　{x(v['title'])}"
                     + (f"（{x(v['status'])}）" if v["status"] in ("预计", "已公布", "已除权") else ""))
    lines.append("\n<i>日期来自 Yahoo；「预计」= 还没正式宣布。/calendar 本周 · 下周 · 本月 · 代码</i>")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    for m in (sys.argv[1:] or ["bursa", "idx", "us"]):
        run(m, push=False)
