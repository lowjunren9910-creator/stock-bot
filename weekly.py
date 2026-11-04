"""
weekly.py - 每周周报（美股星期五收市后自动生成，大马时间星期六早上）

内容：三个市场本周表现、最强 / 最弱板块、本周涨跌最多的大型股、
自选股本周表现、KLCI 50 入选几率变化、推荐成绩单，最后一段 AI 总结。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import scanner as S
import sectors as SE

REPORT_DIR = Path(__file__).parent / "reports" / "weekly"


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def build(now: datetime | None = None) -> dict:
    now = now or datetime.now(ZoneInfo("Asia/Kuala_Lumpur"))
    markets = {}
    for mk, m in S.MARKETS.items():
        sec = SE.latest(mk)
        if not sec:
            continue
        members = [r for s in sec["sectors"] for r in s["members"] if r.get("chg_1w") is not None]
        ranked = sorted(sec["sectors"], key=lambda s: s["returns"]["1w"] or 0, reverse=True)
        track = _load(S.REPORT_DIR / "track" / f"{mk}.json")
        markets[mk] = {
            "name": m.name, "currency": m.currency, "as_of": sec["date"],
            "week": sec["market_index"]["returns"]["1w"], "month": sec["market_index"]["returns"]["1m"],
            "sectors": [{"name": s["name"], "week": s["returns"]["1w"]} for s in ranked],
            "gainers": [{k: r[k] for k in ("ticker", "name", "price", "chg_1w")}
                        for r in sorted(members, key=lambda r: r["chg_1w"], reverse=True)[:5]],
            "losers": [{k: r[k] for k in ("ticker", "name", "price", "chg_1w")}
                       for r in sorted(members, key=lambda r: r["chg_1w"])[:5]],
            "track": {k: v.get("1w") for k, v in (track or {}).get("summary", {}).items()},
        }

    wl = _load(S.REPORT_DIR / "watchlist.json") or {}
    watch = [{k: s.get(k) for k in ("ticker", "name", "price", "change_pct", "chg_1m")}
             for s in wl.get("stocks", []) if s.get("price")]

    klci = None
    kfiles = sorted((S.REPORT_DIR / "klci").glob("*.json")) if (S.REPORT_DIR / "klci").exists() else []
    if kfiles:
        now_k = _load(kfiles[-1])
        old_k = _load(kfiles[-6]) if len(kfiles) >= 6 else _load(kfiles[0])
        old = {c["ticker"]: c["prob"] for c in (old_k or {}).get("top_candidates", [])}
        klci = {"review": now_k.get("review"), "slots": now_k.get("slots"),
                "top": [{"name": c["name"], "ticker": c["ticker"], "prob": c["prob"],
                         "change": c["prob"] - old[c["ticker"]] if c["ticker"] in old else None}
                        for c in now_k["top_candidates"][:25]]}

    report = {"date": str(now.date()), "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
              "markets": markets, "watchlist": watch, "klci": klci, "ai_comment": None}
    report["ai_comment"] = ai_comment(report)
    return report


def ai_comment(r: dict) -> str | None:
    try:
        import asyncio
        import managers as M
        if M.check_setup():
            return None
        brief = {mk: {"本周%": v["week"], "最强板块": v["sectors"][:2], "最弱板块": v["sectors"][-2:],
                      "涨最多": v["gainers"][:3], "跌最多": v["losers"][:3]} for mk, v in r["markets"].items()}
        brief["自选股"] = r["watchlist"]
        system = ("你是投资周报编辑。用简体中文写 250 字以内的本周总结：三个市场各一句话表现，"
                  "点出最强和最弱的板块，自选股里值得注意的一两只，最后一句提醒下周要留意什么。"
                  "不要用 Markdown，不要编造数据里没有的新闻或数字。")
        return asyncio.run(M.chat(system, json.dumps(brief, ensure_ascii=False, default=str), 800))
    except Exception as e:
        print("周报 AI 总结失败：", e)
        return None


def save(r: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{r['date']}.json"
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    S.update_index()
    return path


def latest() -> dict | None:
    files = sorted(REPORT_DIR.glob("*.json")) if REPORT_DIR.exists() else []
    return _load(files[-1]) if files else None


def _p(v):
    return "—" if v is None else f"{v:+.2f}%"


def to_telegram_html(r: dict) -> str:
    import html
    e = html.escape
    lines = [f"<b>📰 每周周报｜{r['date']}</b>"]
    for v in r["markets"].values():
        best, worst = v["sectors"][0], v["sectors"][-1]
        lines += ["", f"<b>{e(v['name'])}</b>　本周 {_p(v['week'])}",
                  f"最强板块：{e(best['name'])} {_p(best['week'])}　最弱：{e(worst['name'])} {_p(worst['week'])}",
                  "涨最多：" + "、".join(f"{e(g['name'])} {_p(g['chg_1w'])}" for g in v["gainers"][:3])]
    if r["watchlist"]:
        lines += ["", "<b>⭐ 自选股</b>"] + [f"{e(w['name'])}：{w['price']:,.2f}（1 个月 {_p(w.get('chg_1m'))}）"
                                            for w in r["watchlist"]]
    if r.get("ai_comment"):
        lines += ["", "<b>🧠 本周总结</b>", e(r["ai_comment"])]
    lines += ["", "<i>仅供学习参考，不构成投资建议。</i>"]
    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    r = build()
    print("已保存：", save(r))
    S.push_text(to_telegram_html(r))
