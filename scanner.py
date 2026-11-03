"""
scanner.py - 市场扫描器：找出每个时段最值得关注的股票

每个市场在三个时间点各生成一份报告：
  open   开市报告：开市后约 45 分钟，看跳空和早盘异动
  midday 午间报告：午休时（美股没有午休，用盘中）
  close  收市报告：收市后，全日总结 + 最值得关注 5 只

"不要投机炒股公司" 的做法：
  1. 只扫描大型蓝筹股名单（下面 UNIVERSE，可自己增减）
  2. 股价低于门槛的仙股剔除
  3. 过去 20 天平均成交额太低的（没人玩、容易被炒）剔除

用法：
  python scanner.py --market bursa --session close   立即生成一份
  python scanner.py --due                            自动判断现在该生成哪份（给 GitHub Actions 用）
"""

from __future__ import annotations

import argparse
import html
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

REPORT_DIR = Path(__file__).parent / "reports"

# ---------------------------------------------------------------------------
# 1. 股票名单：大型、成交活跃的蓝筹股（想加减就改这里）
# ---------------------------------------------------------------------------

BURSA = {
    "1155.KL": "Maybank", "1295.KL": "Public Bank", "1023.KL": "CIMB",
    "5347.KL": "Tenaga", "5225.KL": "IHH", "5183.KL": "PChem",
    "6947.KL": "CelcomDigi", "6012.KL": "Maxis", "6888.KL": "Axiata",
    "4863.KL": "TM", "5819.KL": "Hong Leong Bank", "1066.KL": "RHB Bank",
    "1082.KL": "HL Financial", "1015.KL": "AmBank", "1961.KL": "IOI Corp",
    "2445.KL": "KL Kepong", "5285.KL": "SD Guthrie", "4197.KL": "Sime Darby",
    "3182.KL": "Genting", "4715.KL": "Genting Malaysia", "4707.KL": "Nestle",
    "5681.KL": "Petronas Dagangan", "6033.KL": "Petronas Gas", "3816.KL": "MISC",
    "5398.KL": "Gamuda", "4677.KL": "YTL Corp", "6742.KL": "YTL Power",
    "5211.KL": "Sunway", "7084.KL": "QL Resources", "7113.KL": "Top Glove",
    "5168.KL": "Hartalega", "0166.KL": "Inari", "5296.KL": "MR DIY",
    "8869.KL": "Press Metal", "7277.KL": "Dialog", "5246.KL": "Westports",
    "3336.KL": "IJM", "1818.KL": "Bursa Malaysia", "4065.KL": "PPB",
    "3034.KL": "Hap Seng", "5099.KL": "Capital A", "0138.KL": "MyEG",
    "0097.KL": "ViTrox", "5326.KL": "99 Speed Mart", "4588.KL": "UMW",
    "5209.KL": "Gas Malaysia", "3794.KL": "Malayan Cement", "5258.KL": "Bank Islam",
}

IDX = {
    "BBCA.JK": "Bank Central Asia", "BBRI.JK": "Bank Rakyat", "BMRI.JK": "Bank Mandiri",
    "BBNI.JK": "Bank Negara", "BRIS.JK": "Bank Syariah", "TLKM.JK": "Telkom",
    "ASII.JK": "Astra", "UNVR.JK": "Unilever ID", "ICBP.JK": "Indofood CBP",
    "INDF.JK": "Indofood", "ADRO.JK": "Adaro", "ANTM.JK": "Aneka Tambang",
    "PTBA.JK": "Bukit Asam", "ITMG.JK": "Indo Tambangraya", "UNTR.JK": "United Tractors",
    "KLBF.JK": "Kalbe Farma", "CPIN.JK": "Charoen Pokphand", "GOTO.JK": "GoTo",
    "AMRT.JK": "Alfamart", "MDKA.JK": "Merdeka Copper", "INCO.JK": "Vale Indonesia",
    "PGAS.JK": "PGN", "SMGR.JK": "Semen Indonesia", "INKP.JK": "Indah Kiat",
    "TPIA.JK": "Chandra Asri", "BRPT.JK": "Barito Pacific", "MEDC.JK": "Medco",
    "AKRA.JK": "AKR", "EXCL.JK": "XL Axiata", "ISAT.JK": "Indosat",
    "JSMR.JK": "Jasa Marga", "TOWR.JK": "Sarana Menara", "ARTO.JK": "Bank Jago",
    "HRUM.JK": "Harum Energy", "MAPI.JK": "Mitra Adiperkasa", "SIDO.JK": "Sido Muncul",
}

US = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta", "TSLA": "Tesla", "AVGO": "Broadcom",
    "BRK-B": "Berkshire", "JPM": "JPMorgan", "V": "Visa", "MA": "Mastercard",
    "UNH": "UnitedHealth", "XOM": "Exxon", "LLY": "Eli Lilly", "JNJ": "J&J",
    "WMT": "Walmart", "PG": "P&G", "HD": "Home Depot", "COST": "Costco",
    "ORCL": "Oracle", "NFLX": "Netflix", "AMD": "AMD", "CRM": "Salesforce",
    "ADBE": "Adobe", "KO": "Coca-Cola", "PEP": "PepsiCo", "BAC": "Bank of America",
    "CVX": "Chevron", "MRK": "Merck", "ABBV": "AbbVie", "INTC": "Intel",
    "QCOM": "Qualcomm", "CSCO": "Cisco", "DIS": "Disney", "NKE": "Nike",
    "BA": "Boeing", "PLTR": "Palantir", "TSM": "TSMC", "MU": "Micron",
}


@dataclass
class Market:
    key: str
    name: str
    tz: str
    currency: str
    universe: dict
    min_price: float          # 低于这个价格的仙股不看
    min_turnover: float       # 20 天平均每日成交额（本地货币）门槛
    sessions: dict            # 报告时间（当地时间）
    trading: dict = field(default_factory=dict)  # weekday -> [(开, 收), ...] 交易时段

    def zone(self):
        return ZoneInfo(self.tz)


T = time
MARKETS = {
    "bursa": Market(
        "bursa", "🇲🇾 大马股市 Bursa", "Asia/Kuala_Lumpur", "MYR", BURSA,
        min_price=1.0, min_turnover=5e6,
        sessions={"open": T(9, 45), "midday": T(12, 35), "close": T(17, 15)},
        trading={d: [(T(9, 0), T(12, 30)), (T(14, 30), T(17, 0))] for d in range(5)},
    ),
    "idx": Market(
        "idx", "🇮🇩 印尼股市 IDX", "Asia/Jakarta", "IDR", IDX,
        min_price=500, min_turnover=20e9,
        sessions={"open": T(9, 45), "midday": T(12, 5), "close": T(16, 20)},
        trading={**{d: [(T(9, 0), T(12, 0)), (T(13, 30), T(16, 0))] for d in range(4)},
                 4: [(T(9, 0), T(11, 30)), (T(14, 0), T(16, 0))]},  # 星期五午休较长
    ),
    "us": Market(
        "us", "🇺🇸 美股", "America/New_York", "USD", US,
        min_price=10, min_turnover=100e6,
        sessions={"open": T(10, 0), "midday": T(12, 30), "close": T(16, 20)},
        trading={d: [(T(9, 30), T(16, 0))] for d in range(5)},
    ),
}
# 印尼星期五的午间报告提早
IDX_FRIDAY_MIDDAY = T(11, 35)

SESSION_ZH = {"open": "开市报告", "midday": "午间报告", "close": "收市报告"}


def session_label(market: str, session: str) -> str:
    if market == "us" and session == "midday":
        return "盘中报告"
    return SESSION_ZH[session]


# ---------------------------------------------------------------------------
# 2. 抓数据
# ---------------------------------------------------------------------------

def download(tickers: list[str]) -> dict[str, pd.DataFrame]:
    raw = yf.download(tickers, period="1y", interval="1d", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if len(df) >= 25:
                out[t] = df
        except KeyError:
            continue
    return out


# ---------------------------------------------------------------------------
# 3. 计算每只股票的指标
# ---------------------------------------------------------------------------

def session_fraction(m: Market, now: datetime) -> float:
    """今天的交易时间已经过了几成（用来公平比较盘中成交量）。"""
    blocks = m.trading.get(now.weekday(), [])
    total = done = 0.0
    for a, b in blocks:
        start = now.replace(hour=a.hour, minute=a.minute, second=0, microsecond=0)
        end = now.replace(hour=b.hour, minute=b.minute, second=0, microsecond=0)
        mins = (end - start).total_seconds() / 60
        total += mins
        done += max(0.0, min(mins, (now - start).total_seconds() / 60))
    return min(1.0, max(0.1, done / total)) if total else 1.0


def rsi(close: pd.Series, period: int = 14) -> float:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    return float(100 - 100 / (1 + up.iloc[-1] / dn.iloc[-1])) if dn.iloc[-1] else 100.0


def stock_metrics(df: pd.DataFrame, frac: float) -> dict:
    today, prev = df.iloc[-1], df.iloc[-2]
    hist = df.iloc[:-1]
    price, pc = float(today["Close"]), float(prev["Close"])
    avg_vol = float(hist["Volume"].tail(20).mean())
    avg_turnover = float((hist["Close"] * hist["Volume"]).tail(20).mean())
    sma50 = df["Close"].rolling(50).mean()
    year = hist.tail(250)
    return {
        "price": price,
        "change_pct": (price / pc - 1) * 100,
        "gap_pct": (float(today["Open"]) / pc - 1) * 100,
        "range_pct": (float(today["High"]) - float(today["Low"])) / pc * 100,
        "volume": float(today["Volume"]),
        "vol_ratio": float(today["Volume"]) / (avg_vol * frac) if avg_vol else 0.0,
        "turnover": price * float(today["Volume"]),
        "avg_turnover": avg_turnover,
        "new_high": float(today["High"]) > float(year["High"].max()),
        "new_low": float(today["Low"]) < float(year["Low"].min()),
        "cross_up_50": pc <= sma50.iloc[-2] and price > sma50.iloc[-1] if len(df) > 51 else False,
        "cross_dn_50": pc >= sma50.iloc[-2] and price < sma50.iloc[-1] if len(df) > 51 else False,
        "rsi": rsi(df["Close"]),
    }


def tags_for(x: dict) -> list[str]:
    t = []
    c, vr = x["change_pct"], x["vol_ratio"]
    if c >= 2 and vr >= 1.5:
        t.append("放量大涨")
    elif c <= -2 and vr >= 1.5:
        t.append("放量大跌")
    elif vr >= 2:
        t.append(f"成交量 {vr:.1f} 倍")
    if x["new_high"]:
        t.append("创 52 周新高")
    if x["new_low"]:
        t.append("创 52 周新低")
    if x["gap_pct"] >= 1.5:
        t.append("跳空高开")
    elif x["gap_pct"] <= -1.5:
        t.append("跳空低开")
    if x["cross_up_50"]:
        t.append("突破 50 日均线")
    if x["cross_dn_50"]:
        t.append("跌破 50 日均线")
    if x["rsi"] >= 75:
        t.append("RSI 超买")
    elif x["rsi"] <= 25:
        t.append("RSI 超卖")
    return t


def watch_score(x: dict) -> float:
    """关注度分数：涨跌幅 + 异常成交量 + 波幅 + 特殊事件加分。"""
    s = abs(x["change_pct"]) + 1.5 * max(0.0, x["vol_ratio"] - 1) + 0.3 * x["range_pct"]
    s += 2 * (x["new_high"] or x["new_low"]) + 1 * (x["cross_up_50"] or x["cross_dn_50"])
    return round(s, 2)


# ---------------------------------------------------------------------------
# 4. 生成报告
# ---------------------------------------------------------------------------

def scan(market: str, session: str, now: datetime | None = None,
         with_ai: bool = True) -> dict | None:
    m = MARKETS[market]
    now = now or datetime.now(m.zone())
    data = download(list(m.universe))
    today = now.date()

    # 今天有没有开市？（大部分股票最新一根K线不是今天 = 假期或还没开）
    fresh = {t: d for t, d in data.items() if d.index[-1].date() == today}
    if len(fresh) < max(5, len(data) // 2):
        print(f"[{market}] {today} 看起来没有开市（假期或数据未更新），跳过。")
        return None

    frac = 1.0 if session == "close" else session_fraction(m, now)
    rows, skipped = [], []
    for t, df in fresh.items():
        x = stock_metrics(df, frac)
        if x["price"] < m.min_price or x["avg_turnover"] < m.min_turnover:
            skipped.append(t)
            continue
        x.update(ticker=t, name=m.universe[t], tags=tags_for(x), score=watch_score(x))
        rows.append(x)

    tbl = pd.DataFrame(rows)
    pick = lambda df: df.round(2).to_dict("records")
    up, down = int((tbl.change_pct > 0).sum()), int((tbl.change_pct < 0).sum())
    report = {
        "market": market, "market_name": m.name, "currency": m.currency,
        "session": session, "session_name": session_label(market, session),
        "date": str(today), "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "partial_day": round(frac, 2),
        "breadth": {"scanned": len(tbl), "up": up, "down": down,
                    "flat": len(tbl) - up - down,
                    "avg_change": round(float(tbl.change_pct.mean()), 2) + 0.0,
                    "filtered_out": skipped},
        "watchlist": pick(tbl.nlargest(5, "score")),
        "gainers": pick(tbl.nlargest(5, "change_pct")),
        "losers": pick(tbl.nsmallest(5, "change_pct")),
        "volume_surge": pick(tbl.nlargest(5, "vol_ratio")),
        "turnover_top": pick(tbl.nlargest(5, "turnover")),
        "ai_comment": None,
    }
    if with_ai:
        report["ai_comment"] = ai_comment(report)
    return report


def ai_comment(report: dict) -> str | None:
    """用 AI 写一段市场点评（没设置 AI key 就跳过）。"""
    try:
        import asyncio
        import managers as M
        if M.check_setup():
            return None
        brief = {k: report[k] for k in ("market_name", "session_name", "date", "breadth")}
        brief["最值得关注"] = [
            {"股票": f"{w['name']} ({w['ticker']})", "涨跌%": w["change_pct"],
             "成交量倍数": w["vol_ratio"], "信号": w["tags"]} for w in report["watchlist"]]
        system = ("你是一位资深市场评论员。根据扫描数据，用简体中文写 150 字以内的点评："
                  "先一句话总结今天这个时段的市场气氛，再点出最值得关注的 2-3 只股票和原因，"
                  "最后一句提醒风险。不要用 Markdown，不要编造数据里没有的新闻。")
        return asyncio.run(M.chat(system, json.dumps(brief, ensure_ascii=False), 500))
    except Exception as e:
        print("AI 点评失败：", e)
        return None


def save(report: dict) -> Path:
    folder = REPORT_DIR / report["market"]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report['date']}_{report['session']}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=float),
                    encoding="utf-8")
    update_index()
    return path


def update_index():
    """reports/index.json：所有报告清单，网站用来找最新报告。"""
    idx = {}
    for mk in MARKETS:
        order = {"open": 0, "midday": 1, "close": 2}
        stems = [f.stem for f in (REPORT_DIR / mk).glob("*.json")] if (REPORT_DIR / mk).exists() else []
        idx[mk] = sorted(stems, key=lambda s: (s[:10], order.get(s[11:], 0)), reverse=True)[:90]
    (REPORT_DIR / "index.json").write_text(json.dumps(idx, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 5. Telegram 推送（可选：设置 TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID）
# ---------------------------------------------------------------------------

def to_telegram_html(r: dict) -> str:
    e = html.escape
    b = r["breadth"]
    lines = [f"<b>{e(r['market_name'])}｜{r['session_name']}</b>",
             f"{r['generated_at']}",
             f"上涨 {b['up']} · 下跌 {b['down']} · 平均 {b['avg_change']:+.2f}%（{b['scanned']} 只蓝筹）",
             "", "<b>🔥 最值得关注</b>"]
    for i, w in enumerate(r["watchlist"], 1):
        tags = "、".join(w["tags"]) or "波动较大"
        lines.append(f"{i}. <b>{e(w['name'])}</b> {w['ticker']}  "
                     f"{w['price']:,.2f} ({w['change_pct']:+.2f}%)\n    {e(tags)}")
    if r.get("ai_comment"):
        lines += ["", "<b>🧠 AI 点评</b>", e(r["ai_comment"])]
    lines += ["", "<i>仅供学习参考，不构成投资建议。</i>"]
    return "\n".join(lines)


def push_text(text: str):
    """推送一条 HTML 消息到你的 Telegram（没设置 token/chat id 就跳过）。"""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    try:
        for i in range(0, len(text), 4000):
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=20,
                          data={"chat_id": chat, "text": text[i:i + 4000],
                                "parse_mode": "HTML", "disable_web_page_preview": True})
    except Exception as e:
        print("Telegram 推送失败：", e)


def push_telegram(r: dict):
    push_text(to_telegram_html(r))


# ---------------------------------------------------------------------------
# 6. 自动排程：现在该生成哪些报告？
# ---------------------------------------------------------------------------

def due_reports(now_utc: datetime | None = None, window_hours: float = 1.5) -> list[tuple[str, str]]:
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    enabled = os.getenv("SCAN_MARKETS", "bursa,idx,us").split(",")
    due = []
    for mk in enabled:
        mk = mk.strip()
        if mk not in MARKETS:
            continue
        m = MARKETS[mk]
        now = now_utc.astimezone(m.zone())
        if now.weekday() >= 5:
            continue
        for sess, at in m.sessions.items():
            if mk == "idx" and sess == "midday" and now.weekday() == 4:
                at = IDX_FRIDAY_MIDDAY
            target = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
            done = (REPORT_DIR / mk / f"{now.date()}_{sess}.json").exists()
            if target <= now < target + timedelta(hours=window_hours) and not done:
                due = [d for d in due if d[0] != mk]  # 同一市场只做最新的那个时段
                due.append((mk, sess))
    return due


def main():
    p = argparse.ArgumentParser(description="市场扫描器")
    p.add_argument("--market", choices=MARKETS)
    p.add_argument("--session", choices=SESSION_ZH, default="close")
    p.add_argument("--due", action="store_true", help="自动判断现在该生成的报告")
    p.add_argument("--no-ai", action="store_true")
    p.add_argument("--no-push", action="store_true")
    p.add_argument("--skip-extra", action="store_true", help="收市后不跑选股雷达 / KLCI 观察")
    a = p.parse_args()

    jobs = due_reports() if a.due else [(a.market or "bursa", a.session)]
    if not jobs:
        print("现在没有需要生成的报告。")
    for mk, sess in jobs:
        print(f"→ 生成 {mk} {sess} …")
        r = scan(mk, sess, with_ai=not a.no_ai)
        if r is None:
            continue
        print("  已保存：", save(r))
        if not a.no_push:
            push_telegram(r)
        if sess == "close" and not a.skip_extra:
            run_daily_extras(mk, with_ai=not a.no_ai, push=not a.no_push)


def run_daily_extras(market: str, with_ai: bool = True, push: bool = True):
    """收市后：跑选股雷达；大马另外跑 KLCI 50 观察。出错不影响其他报告。"""
    try:
        import screener
        print(f"→ 选股雷达 {market} …")
        r = screener.screen(market, with_ai=with_ai)
        print("  已保存：", screener.save(r), r["counts"])
        if push:
            push_text(screener.to_telegram_html(r))
    except Exception as e:
        print("选股雷达失败：", e)
    if market != "bursa":
        return
    try:
        import klci
        print("→ KLCI 50 观察 …")
        r = klci.track()
        if with_ai:
            r["ai_comment"] = klci.ai_comment(r)
        print("  已保存：", klci.save(r))
        if push:
            push_text(klci.to_telegram_html(r))
    except Exception as e:
        print("KLCI 观察失败：", e)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    main()
