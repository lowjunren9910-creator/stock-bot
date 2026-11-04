"""
tracker.py - 成绩单：系统推荐的股票后来表现怎样？哪位基金经理最准？

1. 推荐成绩单
   从 reports/ 里所有历史报告，找出每天推荐的股票：
     每日焦点（收市报告最值得关注 5 只）、错杀股、成长股、双杀股（各取前 5）
   用推荐当天的收市价当「买入价」，算 1 周（5 个交易日）、1 个月（21）、3 个月（63）后的涨跌，
   再减掉同期大盘（FBM KLCI / 雅加达综合指数 / 标普 500）的涨跌 = 超额回报。

   怎么看：
     错杀股、成长股、每日焦点 → 超额回报为正、跑赢大盘的比例越高越好
     双杀股是「要避开」的名单 → 跑输大盘的比例越高，代表这个警告越准

2. 基金经理排行榜
   reports/panels/ 里每天自动圆桌的评级，过 21 个交易日后对照超额回报：
     看多（买入 / 强烈买入）且跑赢大盘 = 猜对
     看空（减持 / 卖出）且跑输大盘 = 猜对
     持有 且超额回报在 ±3% 以内 = 猜对
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import fundamentals as F
import scanner as S

REPORT_DIR = Path(__file__).parent / "reports"
OUT_DIR = REPORT_DIR / "track"
BENCH = {"bursa": "^KLSE", "idx": "^JKSE", "us": "^GSPC"}
BENCH_ZH = {"bursa": "FBM KLCI", "idx": "雅加达综合指数", "us": "标普 500"}
HORIZONS = {"1w": 5, "1m": 21, "3m": 63}
STRATEGIES = {"focus": "每日焦点", "oversold": "错杀股", "growth": "成长股", "double_kill": "双杀股"}
SCORE = {"强烈买入": 2, "买入": 1, "持有": 0, "减持": -1, "卖出": -2}


def collect_picks(market: str) -> list[dict]:
    picks = []
    for f in sorted((REPORT_DIR / market).glob("*_close.json")) if (REPORT_DIR / market).exists() else []:
        r = json.loads(f.read_text(encoding="utf-8"))
        for w in r.get("watchlist", [])[:5]:
            picks.append({"date": r["date"], "strategy": "focus", "ticker": w["ticker"], "name": w["name"]})
    folder = REPORT_DIR / "screen" / market
    for f in sorted(folder.glob("*.json")) if folder.exists() else []:
        r = json.loads(f.read_text(encoding="utf-8"))
        for cat in ("oversold", "growth", "double_kill"):
            for x in r.get(cat, [])[:5]:
                picks.append({"date": r["date"], "strategy": cat, "ticker": x["ticker"], "name": x["name"]})
    return picks


def forward(close: pd.Series, date: str, n: int | None) -> tuple[float | None, int]:
    """从 date 那天收市到 n 个交易日后的涨跌 %；n=None = 到最新。返回 (涨跌, 已过天数)。"""
    idx = close.index.tz_localize(None) if close.index.tz is not None else close.index
    s = pd.Series(close.values, index=idx).dropna()
    pos = s.index.searchsorted(pd.Timestamp(date), side="right") - 1
    if pos < 0:
        return None, 0
    passed = len(s) - 1 - pos
    if n is None:
        n = passed
    if n == 0 or passed < n:
        return None, passed
    return (s.iloc[pos + n] / s.iloc[pos] - 1) * 100, passed


def build(market: str) -> dict:
    picks = collect_picks(market)
    panels = []
    for f in sorted((REPORT_DIR / "panels").glob(f"*_{market}.json")) if (REPORT_DIR / "panels").exists() else []:
        panels.append(json.loads(f.read_text(encoding="utf-8")))
    tickers = sorted({p["ticker"] for p in picks} | {p["ticker"] for d in panels for p in d["panels"]})
    bench = BENCH[market]
    px = F.prices(tickers + [bench], "2y") if tickers else {}
    closes = {t: df["Close"] for t, df in px.items()}
    b = closes.get(bench)

    def excess(t, date, n):
        if t not in closes or b is None:
            return None, None, 0
        r, passed = forward(closes[t], date, n)
        br, _ = forward(b, date, n)
        return r, (r - br if r is not None and br is not None else None), passed

    # ---- 推荐成绩单 ----
    rows = []
    for p in picks:
        rec = dict(p)
        for k, n in HORIZONS.items():
            r, ex, passed = excess(p["ticker"], p["date"], n)
            rec[f"ret_{k}"] = None if r is None else round(r, 2)
            rec[f"ex_{k}"] = None if ex is None else round(ex, 2)
        r, ex, passed = excess(p["ticker"], p["date"], None)
        rec.update(ret_now=None if r is None else round(r, 2), ex_now=None if ex is None else round(ex, 2),
                   days=passed)
        rows.append(rec)

    summary = {}
    for cat, zh in STRATEGIES.items():
        sub = [r for r in rows if r["strategy"] == cat]
        stat = {"name": zh, "picks": len(sub)}
        for k in list(HORIZONS) + ["now"]:
            vals = [r[f"ex_{k}"] for r in sub if r[f"ex_{k}"] is not None]
            rets = [r[f"ret_{k}"] for r in sub if r[f"ret_{k}"] is not None]
            good = (lambda v: v < 0) if cat == "double_kill" else (lambda v: v > 0)
            stat[k] = {"n": len(vals),
                       "avg_ret": round(sum(rets) / len(rets), 2) if rets else None,
                       "avg_excess": round(sum(vals) / len(vals), 2) if vals else None,
                       "hit_rate": round(sum(1 for v in vals if good(v)) / len(vals) * 100) if vals else None}
        summary[cat] = stat

    # ---- 基金经理排行榜 ----
    import managers as M
    board = {m["id"]: {"id": m["id"], "name": m["name"], "title": m["title"], "emoji": m["emoji"],
                       "n": 0, "hits": 0, "bull_ex": [], "pending": 0} for m in M.MANAGERS}
    recent_panels = []
    for d in panels:
        for p in d["panels"]:
            r, ex, passed = excess(p["ticker"], d["date"], 21)
            _, ex_now, _ = excess(p["ticker"], d["date"], None)
            recent_panels.append({"date": d["date"], "ticker": p["ticker"], "name": p["name"],
                                  "ratings": {o["id"]: o["rating"] for o in p["opinions"]},
                                  "ex_now": None if ex_now is None else round(ex_now, 2), "days": passed})
            for o in p["opinions"]:
                me = board.get(o["id"])
                if not me or o["rating"] not in SCORE:
                    continue
                if ex is None:
                    me["pending"] += 1
                    continue
                s = SCORE[o["rating"]]
                hit = (s > 0 and ex > 0) or (s < 0 and ex < 0) or (s == 0 and abs(ex) <= 3)
                me["n"] += 1
                me["hits"] += int(hit)
                if s > 0:
                    me["bull_ex"].append(ex)
    leaderboard = []
    for me in board.values():
        leaderboard.append({**{k: me[k] for k in ("id", "name", "title", "emoji", "n", "pending")},
                            "hit_rate": round(me["hits"] / me["n"] * 100) if me["n"] else None,
                            "bull_avg_excess": round(sum(me["bull_ex"]) / len(me["bull_ex"]), 2) if me["bull_ex"] else None})
    leaderboard.sort(key=lambda x: (x["hit_rate"] is not None, x["hit_rate"] or 0, x["n"]), reverse=True)

    return {"market": market, "market_name": S.MARKETS[market].name, "benchmark": BENCH_ZH[market],
            "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "horizons": {"1w": "1 周", "1m": "1 个月", "3m": "3 个月", "now": "至今"},
            "summary": summary, "picks": sorted(rows, key=lambda r: r["date"], reverse=True)[:120],
            "leaderboard": leaderboard, "panels": sorted(recent_panels, key=lambda r: r["date"], reverse=True)[:60]}


def save(r: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{r['market']}.json"
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    S.update_index()
    return path


def latest(market: str) -> dict | None:
    p = OUT_DIR / f"{market}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    a = argparse.ArgumentParser()
    a.add_argument("--market", choices=S.MARKETS, default="bursa")
    print("已保存：", save(build(a.parse_args().market)))
