"""
alerts.py - 自选股 + 价格提醒

读 watchlist.yml → 抓最新股价 → 检查提醒条件 → 推送 Telegram
同时写出 reports/watchlist.json（手机 app 和网站的「自选股」页面用）

每次 GitHub 定时任务都会跑（约每 15 分钟），同一个条件每个交易日只提醒一次。
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

import analysis as A
import fundamentals as F
import scanner as S

ROOT = Path(__file__).parent
WATCH_FILE = ROOT / "watchlist.yml"
OUT_FILE = ROOT / "reports" / "watchlist.json"
STATE_FILE = ROOT / "reports" / "alerts_state.json"

LABELS = {"below": "跌破", "above": "升破", "change_pct": "单日波动超过",
          "rsi_below": "RSI 低于", "rsi_above": "RSI 高于"}


def load_watchlist() -> list[dict]:
    if not WATCH_FILE.exists():
        return []
    import yaml
    data = yaml.safe_load(WATCH_FILE.read_text(encoding="utf-8")) or {}
    out = []
    for s in data.get("stocks") or []:
        if isinstance(s, str):
            s = {"ticker": s}
        if s and s.get("ticker"):
            out.append({"input": str(s["ticker"]), "note": s.get("note") or "",
                        "alerts": s.get("alerts") or {}})
    return out


def market_of(t: str) -> str:
    return "bursa" if t.endswith(".KL") else "idx" if t.endswith(".JK") else "us"


def name_of(t: str) -> str:
    try:
        import klci
        for uni in (klci.UNIVERSE, S.IDX, S.US):
            if t in uni:
                return uni[t]
    except Exception:
        pass
    i = F.info(t)
    return i.get("shortName") or i.get("longName") or t


def check(alerts: dict, x: dict) -> list[str]:
    """返回触发了的条件，例如 ['below', 'rsi_below']。"""
    hit = []
    p, chg, r = x["price"], x["change_pct"], x["rsi"]
    try:
        if "below" in alerts and p <= float(alerts["below"]):
            hit.append("below")
        if "above" in alerts and p >= float(alerts["above"]):
            hit.append("above")
        if "change_pct" in alerts and abs(chg) >= float(alerts["change_pct"]):
            hit.append("change_pct")
        if "rsi_below" in alerts and r <= float(alerts["rsi_below"]):
            hit.append("rsi_below")
        if "rsi_above" in alerts and r >= float(alerts["rsi_above"]):
            hit.append("rsi_above")
    except (TypeError, ValueError):
        pass  # 条件写错（例如不是数字）：跳过，不让整个程序停
    return hit


def run(push: bool = True) -> dict:
    items = load_watchlist()
    if not items:
        return {"stocks": []}
    for it in items:
        it["ticker"] = A.normalize_ticker(it["input"])
    tickers = sorted({it["ticker"] for it in items})
    px = F.prices(tickers, "6mo")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}

    rows, fired = [], []
    for it in items:
        t = it["ticker"]
        df = px.get(t)
        row = {"ticker": t, "input": it["input"], "name": name_of(t), "note": it["note"],
               "market": market_of(t), "alerts": it["alerts"], "triggered": []}
        if df is None or len(df) < 2:
            row["error"] = "找不到股价数据，请检查代码"
            rows.append(row)
            continue
        c = df["Close"]
        x = {"price": float(c.iloc[-1]), "change_pct": (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100,
             "rsi": S.rsi(c)}
        bar_day = str(df.index[-1].date())
        row.update(price=round(x["price"], 3), change_pct=round(x["change_pct"], 2),
                   rsi=round(x["rsi"], 1), date=bar_day,
                   chg_1m=round((x["price"] / float(c.iloc[-22]) - 1) * 100, 2) if len(c) > 22 else None,
                   high_6m=round(float(df["High"].max()), 3), low_6m=round(float(df["Low"].min()), 3))
        for cond in check(it["alerts"], x):
            row["triggered"].append(cond)
            key = f"{t}:{cond}"
            if state.get(key) != bar_day:      # 这根 K 线还没提醒过
                state[key] = bar_day
                fired.append((row, cond))
        rows.append(row)

    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "stocks": rows}
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    old = json.loads(OUT_FILE.read_text(encoding="utf-8")) if OUT_FILE.exists() else {}
    if old.get("stocks") != json.loads(json.dumps(rows, ensure_ascii=False)):  # 有变化才写，避免每 15 分钟一个空提交
        OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if fired:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")

    if fired and push:
        S.push_text(alert_html(fired))
    print(f"自选股 {len(rows)} 只，触发提醒 {len(fired)} 个")
    return out


def describe(cond: str, alerts: dict) -> str:
    v = alerts.get(cond)
    return f"{LABELS[cond]} {v}{'%' if cond == 'change_pct' else ''}"


def alert_html(fired: list) -> str:
    lines = ["<b>🔔 自选股提醒</b>"]
    for row, cond in fired:
        lines.append(f"• <b>{html.escape(row['name'])}</b> {row['ticker']}：{row['price']:,.2f}"
                     f"（{row['change_pct']:+.2f}%，RSI {row['rsi']:.0f}）\n    {describe(cond, row['alerts'])}")
    lines.append("\n<i>改提醒条件：在 GitHub 编辑 watchlist.yml</i>")
    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print(json.dumps(run(), ensure_ascii=False, indent=1)[:2000])
