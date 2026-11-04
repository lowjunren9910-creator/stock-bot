"""
panels.py - 每天自动开几场基金经理圆桌，结果存起来给「基金经理排行榜」评分

每个市场收市后，挑几只股票（自选股优先，再来是当天最值得关注的）开圆桌，
把 5 位经理的评级存进 reports/panels/日期.json。
过一段时间再用 tracker.py 对照实际涨跌，就知道哪位经理最准。

要开几场：GitHub Variables 的 PANEL_DAILY，默认 "bursa:3,idx:1,us:1"
（每场用 6 次 AI，太多会用光免费额度）
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import analysis as A
import managers as M
import scanner as S

REPORT_DIR = Path(__file__).parent / "reports" / "panels"


def quota(market: str) -> int:
    raw = os.getenv("PANEL_DAILY") or "bursa:3,idx:1,us:1"
    for part in raw.split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            if k.strip() == market:
                try:
                    return max(0, int(v))
                except ValueError:
                    return 0
    return 0


def pick_tickers(market: str, n: int) -> list[str]:
    picks = []
    try:
        wl = json.loads((S.REPORT_DIR / "watchlist.json").read_text(encoding="utf-8"))
        picks += [s["ticker"] for s in wl.get("stocks", []) if s.get("market") == market and s.get("price")]
    except Exception:
        pass
    folder = S.REPORT_DIR / market
    closes = sorted(folder.glob("*_close.json")) if folder.exists() else []
    if closes:
        r = json.loads(closes[-1].read_text(encoding="utf-8"))
        picks += [w["ticker"] for w in r.get("watchlist", [])]
    seen, out = set(), []
    for t in picks:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:n]


async def _one(snapshot):
    M.reset_clients()
    ops = await M.ask_all(snapshot)
    return ops


def run(market: str) -> Path | None:
    n = quota(market)
    if n == 0 or M.check_setup():
        print(f"每日圆桌 {market}：跳过（数量 {n} 或没有 AI key）")
        return None
    m = S.MARKETS[market]
    now = datetime.now(m.zone())
    panels = []
    for t in pick_tickers(market, n):
        try:
            r = A.analyze_raw(t)
            ops = asyncio.run(_one(r["snapshot"]))
            panels.append({"ticker": r["ticker"], "name": r["fund"]["name"], "price": r["tech"]["price"],
                           "opinions": [{"id": o["id"], "name": o["name"], "rating": o["rating"]} for o in ops]})
            print(f"  圆桌 {t}：{[o['rating'] for o in ops]}")
        except Exception as e:
            print(f"  圆桌 {t} 失败：{e}")
    if not panels:
        return None
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{now.date()}_{market}.json"
    path.write_text(json.dumps({"date": str(now.date()), "market": market, "panels": panels},
                               ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return path
