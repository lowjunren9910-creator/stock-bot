"""
health.py - 股票代码健康检查（每周跟周报一起跑，也可以手动跑）

检查所有名单里的股票代码：
  - 抓不到任何数据（代码可能错了，或已经除牌）
  - 数据太旧（超过 7 天没有新 K 线：可能停牌）
  - 简称对应的代码有问题（analysis.py 的 ALIASES）
结果存在 reports/health.json，网站和手机 app 的「系统状态」会显示。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import analysis as A
import scanner as S

OUT = Path(__file__).parent / "reports" / "health.json"


def all_lists() -> dict[str, dict]:
    import klci
    return {
        "scanner.py BURSA（每日焦点）": S.BURSA, "scanner.py IDX": S.IDX, "scanner.py US": S.US,
        "klci.py（KLCI 和选股雷达）": klci.UNIVERSE,
        "themes.py（主题板块）": {t: n for m in ("bursa", "idx", "us") for t, n in __import__("themes").all_tickers(m).items()},
        "analysis.py ALIASES（简称）": {v: k for k, v in A.ALIASES.items()},
    }


def run() -> dict:
    lists = all_lists()
    tickers = sorted({t for d in lists.values() for t in d})
    raw = yf.download(tickers, period="1mo", interval="1d", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    today = pd.Timestamp.now().normalize()
    status = {}
    for t in tickers:
        try:
            df = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(subset=["Close"])
        except KeyError:
            df = pd.DataFrame()
        if df.empty:
            status[t] = "missing"
        elif (today - pd.Timestamp(df.index[-1]).tz_localize(None).normalize()).days > 7:
            status[t] = "stale"
        else:
            status[t] = "ok"

    problems = []
    for where, d in lists.items():
        for t, name in d.items():
            if status.get(t) != "ok":
                problems.append({"ticker": t, "name": name, "where": where,
                                 "status": "抓不到数据（代码可能错了或已除牌）" if status.get(t) == "missing"
                                 else "超过 7 天没有新数据（可能停牌）"})
    out = {"checked": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "total": len(tickers), "ok": sum(1 for v in status.values() if v == "ok"),
           "problems": problems}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"健康检查：{out['ok']}/{out['total']} 正常，{len(problems)} 个问题")
    return out


def to_telegram_html(h: dict) -> str | None:
    if not h["problems"]:
        return None
    import html
    lines = [f"<b>🩺 股票代码健康检查</b>：{h['ok']}/{h['total']} 正常"]
    for p in h["problems"][:20]:
        lines.append(f"• {html.escape(p['name'])} <code>{p['ticker']}</code>：{p['status']}\n   在 {html.escape(p['where'])}")
    lines.append("\n把有问题的代码告诉 Claude，或自己在对应文件里改正。")
    return "\n".join(lines)


if __name__ == "__main__":
    h = run()
    print(json.dumps(h, ensure_ascii=False, indent=1)[:3000])
