"""
sectors.py - 板块分类 + 板块指数 + 板块轮动

做的事（每个市场收市后跑一次）：
  1. 把约 200 只大型股（大马 ~120、印尼 36、美股 40）按板块分类
  2. 每个板块算一个「市值加权指数」，一年前 = 1000 点
  3. 算 1 日 / 1 周 / 1 个月 / 3 个月 / 1 年涨跌 → 板块轮动热力图
  4. 顺便存一份所有股票的最新股价（reports/prices.json），给手机 app 的投资组合用

板块指数怎么算（链式市值加权）：
  每天的指数涨跌 = 各成分股涨跌 × 它前一天的市值占比
  指数(今天) = 指数(昨天) × (1 + 当天涨跌)
  这样新上市或缺数据的股票，有数据那天才开始算进去，不会扭曲指数。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import fundamentals as F
import scanner as S
import themes as TH

REPORT_DIR = Path(__file__).parent / "reports"
META_FILE = REPORT_DIR / "sectors" / "meta.json"   # 板块和股数，每周更新一次就够
PRICES_FILE = REPORT_DIR / "prices.json"

SECTOR_ZH = {
    "Financial Services": "金融", "Technology": "科技", "Consumer Defensive": "必需消费",
    "Consumer Cyclical": "非必需消费", "Utilities": "公用事业", "Industrials": "工业",
    "Basic Materials": "原材料", "Energy": "能源", "Real Estate": "房地产",
    "Healthcare": "医疗保健", "Communication Services": "电讯媒体",
}
PLANTATION = ("Farm Products", "Agricultural")   # 马股、印尼股的种植股自成一个板块
PERIODS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "1y": 250}
PERIOD_ZH = {"1d": "1 日", "1w": "1 周", "1m": "1 个月", "3m": "3 个月", "1y": "1 年"}


def universe(market: str) -> dict:
    import screener
    return screener.universe(market)


def sector_of(info: dict, market: str) -> str:
    industry = info.get("industry") or ""
    if market in ("bursa", "idx") and any(k in industry for k in PLANTATION):
        return "种植"
    return SECTOR_ZH.get(info.get("sector"), info.get("sector") or "其他")


def load_meta(tickers: list[str], market: str) -> dict:
    """板块 + 股数。缓存 7 天，避免每天抓 200 次公司资料。"""
    meta = json.loads(META_FILE.read_text(encoding="utf-8")) if META_FILE.exists() else {}
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    stale = [t for t in tickers if t not in meta or meta[t].get("updated", "") < week_ago
             or "roe" not in meta[t]]          # 旧版本没有这些栏位：补抓
    if stale:
        F.prefetch(stale, with_eps=False)
        for t in stale:
            i = F.info(t)
            if not i:
                continue
            meta[t] = {"sector": sector_of(i, market), "industry": i.get("industry"),
                       "shares": i.get("sharesOutstanding") or i.get("impliedSharesOutstanding"),
                       "pe": i.get("trailingPE"), "currency": i.get("currency"),
                       "pb": i.get("priceToBook"), "div_yield": div_pct(i.get("dividendYield")),
                       "roe": pct100(i.get("returnOnEquity")), "margin": pct100(i.get("profitMargins")),
                       "rev_growth": pct100(i.get("revenueGrowth")), "eps_growth": pct100(i.get("earningsGrowth")),
                       "debt_equity": i.get("debtToEquity"),
                       "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        META_FILE.parent.mkdir(parents=True, exist_ok=True)
        META_FILE.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def pct100(v):
    return None if v is None else round(float(v) * 100, 2)


def div_pct(v):
    """Yahoo 的股息率有时是 0.045，有时是 4.5，统一变成 %。"""
    if v is None:
        return None
    v = float(v)
    return round(v if v > 1 else v * 100, 2)


def chain_index(closes: pd.DataFrame, shares: pd.Series) -> pd.Series:
    """链式市值加权指数，起点 = 1000。"""
    mcap = closes.mul(shares, axis=1)
    rets = closes.pct_change()
    w = mcap.shift(1)
    valid = rets.notna() & w.notna()
    daily = (rets.where(valid, 0) * w.where(valid, 0)).sum(axis=1) / w.where(valid, 0).sum(axis=1)
    daily = daily.fillna(0)
    daily.iloc[0] = 0
    return 1000 * (1 + daily).cumprod()


def period_returns(series: pd.Series) -> dict:
    s = series.dropna()
    out = {}
    for k, n in PERIODS.items():
        out[k] = round((s.iloc[-1] / s.iloc[-1 - n] - 1) * 100, 2) if len(s) > n else None
    return out


def build(market: str, now: datetime | None = None) -> dict:
    m = S.MARKETS[market]
    now = now or datetime.now(m.zone())
    uni = universe(market)
    px = F.prices(list(uni), "1y")
    meta = load_meta(list(px), market)

    closes = pd.DataFrame({t: df["Close"] for t, df in px.items()}).sort_index().ffill(limit=3)
    shares = pd.Series({t: (meta.get(t) or {}).get("shares") for t in closes.columns}, dtype=float)
    # 没有股数的股票：用 1 股代替会让它几乎没权重，所以改用中位数，至少让它算进去
    shares = shares.fillna(shares.median() if shares.notna().any() else 1.0)

    groups: dict[str, list[str]] = {}
    for t in closes.columns:
        groups.setdefault((meta.get(t) or {}).get("sector") or "其他", []).append(t)

    def member_row(t):
        c = closes[t].dropna()
        price = float(c.iloc[-1])
        rets = period_returns(c)
        mt = meta.get(t) or {}
        return {"ticker": t, "name": uni.get(t, t), "price": round(price, 3),
                "mcap": float(price * shares[t]), "pe": mt.get("pe"),
                "industry": mt.get("industry"), "sector": mt.get("sector"),
                **{k: mt.get(k) for k in ("pb", "div_yield", "roe", "margin", "rev_growth", "eps_growth", "debt_equity")},
                "rsi": round(S.rsi(c), 1) if len(c) > 15 else None,
                **{f"chg_{k}": v for k, v in rets.items()}}

    def group(name, members, **extra):
        idx = chain_index(closes[members], shares[members])
        rows = sorted((member_row(t) for t in members), key=lambda r: r["mcap"], reverse=True)
        total = sum(r["mcap"] for r in rows) or 1
        for r in rows:
            r["weight"] = round(r["mcap"] / total * 100, 1)
        return {
            "name": name, "count": len(rows), "mcap": total,
            "level": round(float(idx.iloc[-1]), 1), "returns": period_returns(idx),
            "up": sum(1 for r in rows if (r["chg_1d"] or 0) > 0),
            "down": sum(1 for r in rows if (r["chg_1d"] or 0) < 0),
            "top_weight": rows[0]["weight"] if rows else None,
            "series": {"dates": [d.strftime("%Y-%m-%d") for d in idx.index[-250:]],
                       "levels": [round(float(v), 1) for v in idx.iloc[-250:]]},
            "members": rows, **extra,
        }

    market_idx = chain_index(closes, shares)
    sectors = [group(name, members, kind="sector", **TH.sector_look(name))
               for name, members in groups.items()]
    sectors.sort(key=lambda s: s["mcap"], reverse=True)

    # 主题板块（AI 股、发电股、手套股、REIT …）：一只股票可以同时在几个主题里
    theme_rows = []
    for th in TH.for_market(market):
        members = [t for t in th["members"] if t in closes.columns]
        if len(members) >= 2:
            theme_rows.append(group(th["name"], members, kind="theme", key=th["key"],
                                    desc=th["desc"], **TH.look(th)))
    theme_rows.sort(key=lambda s: s["returns"].get("1m") or 0, reverse=True)

    report = {
        "market": market, "market_name": m.name, "currency": m.currency,
        "date": str(now.date()), "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "periods": PERIOD_ZH,
        "market_index": {"level": round(float(market_idx.iloc[-1]), 1),
                         "returns": period_returns(market_idx),
                         "series": {"dates": [d.strftime("%Y-%m-%d") for d in market_idx.index[-250:]],
                                    "levels": [round(float(v), 1) for v in market_idx.iloc[-250:]]}},
        "sectors": sectors,
        "themes": theme_rows,
        "universe_size": len(closes.columns),
        "note": f"链式市值加权指数，一年前 = 1000 点；包括本系统追踪的 {len(closes.columns)} 只大中型股，跟官方板块指数不同。"
                "板块照片来自 Unsplash。",
    }
    update_prices(market, report)
    return report


def update_prices(market: str, report: dict):
    """所有股票最新股价 → reports/prices.json（手机 app 投资组合用）。"""
    prices = json.loads(PRICES_FILE.read_text(encoding="utf-8")) if PRICES_FILE.exists() else {}
    for s in report["sectors"]:
        for r in s["members"]:
            prices[r["ticker"]] = {"name": r["name"], "price": r["price"], "chg_1d": r["chg_1d"],
                                   "currency": report["currency"], "market": market,
                                   "sector": s["name"], "date": report["date"]}
    PRICES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PRICES_FILE.write_text(json.dumps(prices, ensure_ascii=False, indent=1), encoding="utf-8")


def save(r: dict) -> Path:
    folder = REPORT_DIR / "sectors" / r["market"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{r['date']}.json"
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    S.update_index()
    return path


def latest(market: str) -> dict | None:
    folder = REPORT_DIR / "sectors" / market
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def to_telegram_html(r: dict) -> str:
    import html
    lines = [f"<b>🧩 板块轮动｜{html.escape(r['market_name'])}｜{r['date']}</b>",
             f"大型股综合：1 日 {_pct(r['market_index']['returns']['1d'])}　1 个月 {_pct(r['market_index']['returns']['1m'])}", ""]
    ranked = sorted(r["sectors"], key=lambda s: s["returns"]["1d"] or 0, reverse=True)
    for s in ranked:
        lines.append(f"{_pct(s['returns']['1d']):>7}  {html.escape(s['name'])}（{s['count']} 只）")
    if r.get("themes"):
        lines += ["", "<b>主题板块</b>（1 日 / 1 个月）"]
        for s in sorted(r["themes"], key=lambda s: s["returns"]["1d"] or 0, reverse=True):
            lines.append(f"{s['emoji']} {html.escape(s['name'])}：{_pct(s['returns']['1d'])} / {_pct(s['returns']['1m'])}")
    return "\n".join(lines)


def find_group(r: dict, text: str) -> dict | None:
    """用名字找板块或主题，例如「手套」「REIT」「ai」。"""
    t = text.strip().lower()
    pool = (r.get("themes") or []) + r["sectors"]
    for s in pool:
        if t in (s["name"].lower(), (s.get("key") or "").lower()):
            return s
    for s in pool:
        if t and (t in s["name"].lower() or t in (s.get("key") or "")):
            return s
    return None


def group_html(r: dict, s: dict) -> str:
    import html
    lines = [f"<b>{s.get('emoji', '')} {html.escape(s['name'])}｜{html.escape(r['market_name'])}</b>"]
    if s.get("desc"):
        lines.append(f"<i>{html.escape(s['desc'])}</i>")
    rt = s["returns"]
    lines.append(f"指数 {s['level']:,.0f} 点　1 日 {_pct(rt['1d'])}　1 个月 {_pct(rt['1m'])}　1 年 {_pct(rt['1y'])}\n")
    for m in s["members"][:12]:
        lines.append(f"{_pct(m['chg_1d']):>7}  {html.escape(m['name'])} <code>{m['ticker']}</code>（权重 {m['weight']}%）")
    return "\n".join(lines)


def reply(arg: str) -> str:
    """Telegram /sector：
       /sector            → 大马板块轮动
       /sector us         → 美股板块轮动
       /sector 手套 / REIT / AI → 那个板块或主题的指数和成分股"""
    import html
    words = arg.split()
    mk = next((w.lower() for w in words if w.lower() in S.MARKETS), None)
    name = " ".join(w for w in words if w.lower() not in S.MARKETS)
    if not name:
        r = latest(mk or "bursa")
        return to_telegram_html(r) if r else "还没有板块报告（收市后会生成）。用法：/sector [bursa|idx|us] [板块名]"
    order = [mk] if mk else ["bursa", "idx", "us"]
    for m in order:
        r = latest(m)
        g = find_group(r, name) if r else None
        if g:
            return group_html(r, g)
    names = sorted({th["name"] for th in TH.THEMES})
    return (f"找不到「{html.escape(name)}」。可以试试这些主题：\n" + "、".join(names) +
            "\n\n例如 <code>/sector 手套</code>、<code>/sector us AI</code>")


def _pct(v):
    return "—" if v is None else f"{v:+.2f}%"


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--market", choices=S.MARKETS, default="bursa")
    a = p.parse_args()
    r = build(a.market)
    print("已保存：", save(r))
