"""
universe.py - 股票池：每个市场要看哪些股票（约 500 只）

来源（合在一起，自动去掉重复）：
  1. Yahoo 股票筛选器：每个市场按市值排前 N 名（每 7 天更新一次，存在 reports/universe/）
  2. 本系统原本的蓝筹名单（scanner.py、klci.py）
  3. 主题板块里的股票（themes.py）
如果 Yahoo 筛选器失败，就用上一次存下来的名单；连这个也没有，就只用 2 + 3。

想改数量：改下面 TARGET，或在 GitHub Variables 加 UNIVERSE_SIZE，例如  bursa:250,idx:100,us:150
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).parent
CACHE_DIR = ROOT / "reports" / "universe"

TARGET = {"bursa": 250, "idx": 100, "us": 150}
# 筛选器的门槛：太便宜的仙股、太小的公司不要
SCREEN = {
    "bursa": {"region": "my", "min_price": 0.30, "min_mcap": 3e8},
    "idx": {"region": "id", "min_price": 150, "min_mcap": 5e12},
    "us": {"region": "us", "min_price": 5, "min_mcap": 2e10,
           "exchanges": ["NMS", "NYQ", "NGM", "ASE"]},
}
REFRESH_DAYS = 7


def targets() -> dict:
    t = dict(TARGET)
    for part in (os.getenv("UNIVERSE_SIZE") or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip() in t and v.strip().isdigit():
                t[k.strip()] = int(v)
    return t


def base(market: str) -> dict:
    """本系统原本就有的名单 + 主题股（不需要上网）。"""
    import scanner as S
    import themes
    out = {}
    if market == "bursa":
        import klci
        out.update(klci.UNIVERSE)
    out.update(S.MARKETS[market].universe)
    for t, n in themes.all_tickers(market).items():
        out.setdefault(t, n)
    return out


def _clean_name(q: dict) -> str:
    n = q.get("shortName") or q.get("longName") or q.get("symbol")
    for tail in (" BHD", " Berhad", " Tbk.", " Tbk", " PT", " Inc.", " Corporation"):
        if n.endswith(tail):
            n = n[: -len(tail)]
    return n.strip().title() if n.isupper() else n.strip()


def fetch_screen(market: str, n: int) -> dict:
    """Yahoo 筛选器：市值最大的 n 只。"""
    import yfinance as yf
    from yfinance import EquityQuery as Q
    c = SCREEN[market]
    parts = [Q("eq", ["region", c["region"]]), Q("gt", ["intradaymarketcap", c["min_mcap"]]),
             Q("gt", ["intradayprice", c["min_price"]])]
    if c.get("exchanges"):
        parts.append(Q("is-in", ["exchange", *c["exchanges"]]))
    out, offset = {}, 0
    while len(out) < n:
        size = min(250, n - len(out))
        res = yf.screen(Q("and", parts), offset=offset, size=size,
                        sortField="intradaymarketcap", sortAsc=False)
        quotes = (res or {}).get("quotes") or []
        for q in quotes:
            sym = q.get("symbol")
            if sym and q.get("quoteType", "EQUITY") == "EQUITY":
                out[sym] = _clean_name(q)
        if len(quotes) < size:
            break
        offset += size
    return out


def _cache_path(market: str) -> Path:
    return CACHE_DIR / f"{market}.json"


def refresh(market: str, force: bool = False) -> dict:
    """需要的话（超过 7 天）重新跑一次 Yahoo 筛选器，结果存起来。"""
    path = _cache_path(market)
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    week_ago = (datetime.now(timezone.utc) - timedelta(days=REFRESH_DAYS)).strftime("%Y-%m-%d")
    if old.get("stocks") and old.get("updated", "") >= week_ago and not force:
        return old["stocks"]
    try:
        stocks = fetch_screen(market, targets()[market])
    except Exception as e:
        print(f"  [{market}] Yahoo 筛选器失败（用上次的名单）：{e}")
        return old.get("stocks") or {}
    if len(stocks) < 20:          # 太少 = 筛选器出问题，不要覆盖旧名单
        print(f"  [{market}] Yahoo 筛选器只回传 {len(stocks)} 只，保留旧名单")
        return old.get("stocks") or stocks
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                                "market": market, "count": len(stocks), "stocks": stocks},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  [{market}] 股票池更新：Yahoo 筛选器 {len(stocks)} 只")
    return stocks


@lru_cache(maxsize=None)
def _get(market: str, online: bool) -> tuple:
    names = base(market)                       # 原本名单的名字比较好看，优先用
    extra = refresh(market) if online else (
        json.loads(_cache_path(market).read_text(encoding="utf-8")).get("stocks", {})
        if _cache_path(market).exists() else {})
    for t, n in extra.items():
        names.setdefault(t, n)
    return tuple(names.items())


def get(market: str, online: bool = True) -> dict:
    """{代码: 名称}。online=False：不上网，只读存好的名单（网站用）。"""
    return dict(_get(market, online))


def market_of(ticker: str) -> str:
    return "bursa" if ticker.endswith(".KL") else "idx" if ticker.endswith(".JK") else "us"


def name_of(ticker: str) -> str | None:
    return get(market_of(ticker), online=False).get(ticker)


if __name__ == "__main__":
    for m in TARGET:
        u = get(m)
        print(m, len(u), list(u.items())[:5])
