"""
analysis.py - 股票机器人的"大脑"：取数据、算指标、整理报告。

Data source: Yahoo Finance via the free `yfinance` library.
Ticker formats:
  - Bursa Malaysia : 1155.KL  (Maybank)   - or just type 1155 / MAYBANK
  - US             : AAPL, NVDA, TSLA
  - Indonesia      : BBCA.JK (Bank Central Asia) - or just type BBCA
"""

from __future__ import annotations

import io
from functools import lru_cache
from datetime import datetime, timedelta, timezone

import matplotlib

matplotlib.use("Agg")  # no screen needed - we render charts to PNG in memory
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# ---------------------------------------------------------------------------
# 1. Ticker handling
# ---------------------------------------------------------------------------

# Friendly names -> Yahoo tickers. Add your own favourites here.
ALIASES = {
    # Bursa Malaysia：Bursa 官方简称 → 代码（想加就在这里加）
    "MAYBANK": "1155.KL", "PBBANK": "1295.KL", "PUBLICBANK": "1295.KL", "CIMB": "1023.KL",
    "TENAGA": "5347.KL", "TNB": "5347.KL", "IHH": "5225.KL", "PCHEM": "5183.KL",
    "PETDAG": "5681.KL", "PETGAS": "6033.KL", "MISC": "3816.KL", "MAXIS": "6012.KL",
    "CDB": "6947.KL", "CELCOMDIGI": "6947.KL", "AXIATA": "6888.KL", "TM": "4863.KL",
    "HLBANK": "5819.KL", "HLFG": "1082.KL", "RHBBANK": "1066.KL", "RHB": "1066.KL",
    "AMBANK": "1015.KL", "AMMB": "1015.KL", "IOICORP": "1961.KL", "KLK": "2445.KL",
    "SDG": "5285.KL", "SIME": "4197.KL", "PPB": "4065.KL", "NESTLE": "4707.KL",
    "PMETAL": "8869.KL", "PRESSMETAL": "8869.KL", "GENTING": "3182.KL", "GENM": "4715.KL",
    "YTL": "4677.KL", "YTLPOWR": "6742.KL", "SUNWAY": "5211.KL", "SUNMED": "5555.KL",
    "IOIPROP": "5249.KL", "GAMUDA": "5398.KL", "IJM": "3336.KL", "99SMART": "5326.KL",
    "MRDIY": "5296.KL", "QL": "7084.KL", "INARI": "0166.KL", "VITROX": "0097.KL",
    "TIMECOM": "5031.KL", "UTDPLT": "2089.KL", "WPRTS": "5246.KL", "WESTPORTS": "5246.KL",
    "KPJ": "5878.KL", "ABMB": "2488.KL", "SIMEPROP": "5288.KL", "SUNREIT": "5176.KL",
    "IGBREIT": "5227.KL", "PAVREIT": "5212.KL", "MCEMENT": "3794.KL", "SUNCON": "5263.KL",
    "ECOSHOP": "5337.KL", "HAPSENG": "3034.KL", "DIALOG": "7277.KL", "BIMB": "5258.KL",
    "MBSB": "1171.KL", "AFFIN": "5185.KL", "BURSA": "1818.KL", "AEONCR": "5139.KL",
    "KLCC": "5235SS.KL", "AXREIT": "5106.KL", "CAPITALA": "5099.KL", "AAX": "5238.KL",
    "MYEG": "0138.KL", "ZETRIX": "0138.KL", "UMW": "4588.KL", "BAUTO": "5248.KL",
    "GASMSIA": "5209.KL", "MALAKOF": "5264.KL", "MFCB": "3069.KL", "RANHILL": "5272.KL",
    "SLVEST": "0215.KL", "YINSON": "7293.KL", "VELESTO": "5243.KL", "HIBISCS": "5199.KL",
    "PETRONM": "3042.KL", "BIPORT": "5032.KL", "GENP": "2291.KL", "FGV": "5222.KL",
    "SOP": "5126.KL", "TOPGLOV": "7113.KL", "HARTA": "5168.KL", "KOSSAN": "7153.KL",
    "FRONTKN": "0128.KL", "GREATEC": "0208.KL", "UNISEM": "5005.KL", "PENTA": "7160.KL",
    "KGB": "0151.KL", "UWC": "5292.KL", "ITMAX": "5309.KL", "SPSETIA": "8664.KL",
    "UEMS": "5148.KL", "MAHSING": "8583.KL", "MATRIX": "5236.KL", "SCIENTX": "4731.KL",
    "LCTITAN": "5284.KL", "HLIND": "3301.KL", "HEIM": "3255.KL", "CARLSBG": "2836.KL",
    "AEON": "6599.KL", "ASTRO": "6399.KL", "CTOS": "5301.KL", "TANCO": "2429.KL",
    "VS": "6963.KL", "UCHITEC": "7100.KL", "DPHARMA": "7148.KL",
    # Indonesia (IDX)
    "BBCA": "BBCA.JK", "BBRI": "BBRI.JK", "BMRI": "BMRI.JK",
    "BBNI": "BBNI.JK", "TLKM": "TLKM.JK", "ASII": "ASII.JK",
    "UNVR": "UNVR.JK", "GOTO": "GOTO.JK", "ICBP": "ICBP.JK",
    "ADRO": "ADRO.JK", "ANTM": "ANTM.JK", "BREN": "BREN.JK",
}


def _key(s: str) -> str:
    return "".join(ch for ch in s.upper() if ch.isalnum())


@lru_cache(maxsize=1)
def _name_index() -> dict:
    """公司全名 → 代码，例如 PPBGROUP → 4065.KL、PUBLICBANK → 1295.KL。"""
    idx = {}
    try:
        import klci
        import scanner
        for uni in (klci.UNIVERSE, scanner.IDX, scanner.US):
            for code, name in uni.items():
                idx.setdefault(_key(name), code)
    except Exception:
        pass
    return idx


def _quick(t: str) -> str | None:
    """不用上网就能认出来的：简称、4 位数代码、带后缀的代码、公司名称。"""
    if t in ALIASES:
        return ALIASES[t]
    if t.isdigit() and len(t) == 4:  # Bursa 股票代码是 4 位数
        return f"{t}.KL"
    if "." in t:
        return t
    k = _key(t)
    for name, code in _name_index().items():
        if k and (k == name or (len(k) >= 4 and name.startswith(k))):
            return code
    return None


@lru_cache(maxsize=512)
def normalize_ticker(text: str) -> str:
    """把用户输入的东西变成 Yahoo 代码：MAYBANK / 1155 / PPB / public bank / AAPL / BBCA …"""
    t = text.strip().upper().replace(" ", "")
    hit = _quick(t)
    if hit:
        return hit
    # 认不出来：先当美股代码试试
    try:
        if not yf.Ticker(t).history(period="5d").empty:
            return t
    except Exception:
        pass
    # 再用 Yahoo 搜索（公司名称、其他简称），马股和印尼股优先
    try:
        quotes = yf.Search(text.strip(), max_results=10).quotes
        quotes = [q for q in quotes if q.get("quoteType") in ("EQUITY", "ETF") and q.get("symbol")]
        local = [q for q in quotes if q["symbol"].endswith((".KL", ".JK"))]
        if local or quotes:
            return (local or quotes)[0]["symbol"]
    except Exception:
        pass
    return t


def market_of(ticker: str) -> str:
    if ticker.endswith(".KL"):
        return "大马股市 Bursa"
    if ticker.endswith(".JK"):
        return "印尼股市 IDX"
    return "美股"


# ---------------------------------------------------------------------------
# 2. Data fetching
# ---------------------------------------------------------------------------

def get_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if df.empty:
        raise ValueError(
            f"找不到 {ticker} 的股价数据，请检查代码"
            "（大马：1155.KL，印尼：BBCA.JK，美股：AAPL）。"
        )
    return df


def get_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 3. Technical indicators (computed by hand so you can see the maths)
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. >70 = overbought, <30 = oversold."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    line = ema_fast - ema_slow
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c = df["Close"]
    df["SMA20"] = c.rolling(20).mean()
    df["SMA50"] = c.rolling(50).mean()
    df["SMA200"] = c.rolling(200).mean()
    df["RSI14"] = rsi(c)
    df["MACD"], df["MACD_SIG"], df["MACD_HIST"] = macd(c)
    std20 = c.rolling(20).std()
    df["BB_UP"] = df["SMA20"] + 2 * std20
    df["BB_LO"] = df["SMA20"] - 2 * std20
    return df


def technical_summary(df: pd.DataFrame) -> dict:
    """Score the latest bar. Each bullish signal +1, bearish -1."""
    df = add_indicators(df)
    last, prev = df.iloc[-1], df.iloc[-2]
    price = last["Close"]
    signals, score = [], 0

    def check(cond_bull, cond_bear, bull_msg, bear_msg):
        nonlocal score
        if cond_bull:
            score += 1
            signals.append("🟢 " + bull_msg)
        elif cond_bear:
            score -= 1
            signals.append("🔴 " + bear_msg)

    if pd.notna(last["SMA50"]):
        check(price > last["SMA50"], price < last["SMA50"],
              "股价在 50 日均线之上（短期上升趋势）",
              "股价在 50 日均线之下（短期下降趋势）")
    if pd.notna(last["SMA200"]):
        check(price > last["SMA200"], price < last["SMA200"],
              "股价在 200 日均线之上（长期上升趋势）",
              "股价在 200 日均线之下（长期下降趋势）")
    if pd.notna(last["SMA50"]) and pd.notna(last["SMA200"]):
        check(last["SMA50"] > last["SMA200"], last["SMA50"] < last["SMA200"],
              "黄金交叉格局（50日 > 200日）", "死亡交叉格局（50日 < 200日）")
    if pd.notna(last["RSI14"]):
        r = last["RSI14"]
        check(r < 30, r > 70,
              f"RSI {r:.0f}：超卖，可能反弹",
              f"RSI {r:.0f}：超买，可能回调")
        if 30 <= r <= 70:
            signals.append(f"⚪ RSI {r:.0f}：中性")
    check(last["MACD"] > last["MACD_SIG"], last["MACD"] < last["MACD_SIG"],
          "MACD 在信号线之上（动能向上）",
          "MACD 在信号线之下（动能向下）")
    if prev["MACD"] <= prev["MACD_SIG"] < last["MACD_SIG"] <= last["MACD"]:
        signals.append("✨ 今天 MACD 刚出现金叉")
    if prev["MACD"] >= prev["MACD_SIG"] > last["MACD_SIG"] >= last["MACD"]:
        signals.append("⚠️ 今天 MACD 刚出现死叉")

    if score >= 3:
        verdict = "看涨"
    elif score >= 1:
        verdict = "偏多"
    elif score <= -3:
        verdict = "看跌"
    elif score <= -1:
        verdict = "偏空"
    else:
        verdict = "中性"

    year = df.tail(252)
    return {
        "price": price,
        "change_1d": (price / prev["Close"] - 1) * 100,
        "change_1m": (price / df["Close"].iloc[-22] - 1) * 100 if len(df) > 22 else None,
        "change_1y": (price / year["Close"].iloc[0] - 1) * 100,
        "high_52w": year["High"].max(),
        "low_52w": year["Low"].min(),
        "rsi": last["RSI14"],
        "sma50": last["SMA50"],
        "sma200": last["SMA200"],
        "score": score,
        "verdict": verdict,
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# 4. Fundamentals
# ---------------------------------------------------------------------------

def dividend_yield(ticker: str, price: float) -> float | None:
    """Trailing 12-month dividends / price - computed ourselves for consistency."""
    try:
        divs = yf.Ticker(ticker).dividends
        if divs.empty:
            return 0.0
        cutoff = pd.Timestamp.now(tz=divs.index.tz) - pd.Timedelta(days=365)
        return divs[divs.index >= cutoff].sum() / price * 100
    except Exception:
        return None


def fundamental_summary(ticker: str, info: dict, price: float) -> dict:
    g = info.get
    flags = []
    pe = g("trailingPE")
    if pe:
        if pe < 0:
            flags.append("🔴 本益比为负（公司亏损）")
        elif pe < 12:
            flags.append(f"🟢 本益比偏低 {pe:.1f}：可能便宜（也可能市场看到风险）")
        elif pe > 35:
            flags.append(f"🔴 本益比偏高 {pe:.1f}：股价已反映高增长预期")
    rg = g("revenueGrowth")
    if rg is not None:
        flags.append(("🟢" if rg > 0 else "🔴") + f" 营收按年增长 {rg*100:+.1f}%")
    roe = g("returnOnEquity")
    if roe is not None:
        flags.append(("🟢" if roe >= 0.15 else "⚪" if roe > 0 else "🔴")
                     + f" 股本回报率 ROE {roe*100:.1f}%")
    de = g("debtToEquity")
    if de is not None:
        # Banks naturally carry high leverage - don't flag them
        if g("sector") != "Financial Services":
            flags.append(("🔴" if de > 150 else "🟢" if de < 50 else "⚪")
                         + f" 负债/股本 {de:.0f}%")
    dy = dividend_yield(ticker, price)
    if dy:
        flags.append(("🟢" if dy >= 4 else "⚪") + f" 股息率 {dy:.2f}%")

    return {
        "name": g("longName") or g("shortName") or ticker,
        "sector": g("sector"),
        "industry": g("industry"),
        "currency": g("currency", ""),
        "market_cap": g("marketCap"),
        "pe": pe,
        "forward_pe": g("forwardPE"),
        "pb": g("priceToBook"),
        "profit_margin": g("profitMargins"),
        "dividend_yield": dy,
        "target_price": g("targetMeanPrice"),
        "analyst_rec": g("recommendationKey"),
        "flags": flags,
    }


# ---------------------------------------------------------------------------
# 5. News sentiment (VADER - a rule-based model tuned for short text)
# ---------------------------------------------------------------------------

_vader = SentimentIntensityAnalyzer()


def news_sentiment(ticker: str, limit: int = 8) -> dict:
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []
    items = []
    for n in raw[:limit]:
        c = n.get("content", n)  # newer yfinance nests data under "content"
        title = c.get("title")
        if not title:
            continue
        link = (c.get("canonicalUrl") or {}).get("url") if isinstance(
            c.get("canonicalUrl"), dict) else c.get("link")
        score = _vader.polarity_scores(title)["compound"]  # -1 .. +1
        items.append({"title": title, "link": link, "score": score})

    if not items:
        return {"items": [], "avg": None, "mood": "没有近期新闻"}
    avg = sum(i["score"] for i in items) / len(items)
    mood = "正面" if avg > 0.15 else "负面" if avg < -0.15 else "中性 / 好坏参半"
    return {"items": items, "avg": avg, "mood": mood}


# ---------------------------------------------------------------------------
# 6. Chart
# ---------------------------------------------------------------------------

def make_chart(ticker: str, df: pd.DataFrame) -> io.BytesIO:
    df = add_indicators(df).tail(180)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(9, 6), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )
    ax1.plot(df.index, df["Close"], label="Close", linewidth=1.6)
    ax1.plot(df.index, df["SMA50"], label="SMA 50", linewidth=1)
    ax1.plot(df.index, df["SMA200"], label="SMA 200", linewidth=1)
    ax1.fill_between(df.index, df["BB_LO"], df["BB_UP"], alpha=0.12, label="Bollinger")
    ax1.set_title(f"{ticker} - last 6 months")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.plot(df.index, df["RSI14"], color="purple", linewidth=1)
    ax2.axhline(70, color="red", linestyle="--", linewidth=0.8)
    ax2.axhline(30, color="green", linestyle="--", linewidth=0.8)
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("RSI")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# 7. Formatting helpers (Telegram HTML)
# ---------------------------------------------------------------------------

REC_ZH = {"strong_buy": "强烈买入", "buy": "买入", "hold": "持有",
          "underperform": "跑输大市", "sell": "卖出", "none": "无"}


def _num(x, nd=2, suffix=""):
    return "无" if x is None or pd.isna(x) else f"{x:,.{nd}f}{suffix}"


def _big(x):
    if not x:
        return "无"
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if x >= div:
            return f"{x/div:,.2f}{unit}"
    return f"{x:,.0f}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_technical(ticker, t, cur=""):
    lines = [
        f"<b>📈 技术面 - {ticker}</b>",
        f"股价：<b>{cur} {_num(t['price'])}</b>（今日 {t['change_1d']:+.2f}%）",
        f"1个月：{_num(t['change_1m'], suffix='%')} | 1年：{_num(t['change_1y'], suffix='%')}",
        f"52周区间：{_num(t['low_52w'])} - {_num(t['high_52w'])}",
        f"50日均线：{_num(t['sma50'])} | 200日均线：{_num(t['sma200'])}",
        "",
        *t["signals"],
        "",
        f"<b>技术面结论：{t['verdict']}</b>（分数 {t['score']:+d}）",
    ]
    return "\n".join(lines)


def format_fundamental(f):
    lines = [
        f"<b>🏢 基本面 - {_esc(f['name'])}</b>",
        " · ".join(_esc(x) for x in (f["sector"], f["industry"]) if x) or "行业：无数据",
        f"市值：{f['currency']} {_big(f['market_cap'])}",
        f"本益比 P/E：{_num(f['pe'])} | 预期 P/E：{_num(f['forward_pe'])} | 市净率 P/B：{_num(f['pb'])}",
        f"净利率：{_num(f['profit_margin'] * 100 if f['profit_margin'] is not None else None, 1, '%')}",
    ]
    if f["target_price"]:
        lines.append(f"分析师目标价：{_num(f['target_price'])} "
                     f"（{REC_ZH.get(f['analyst_rec'], f['analyst_rec'] or '无')}）")
    lines += ["", *f["flags"]]
    return "\n".join(lines)


def format_news(n):
    if not n["items"]:
        return "<b>📰 新闻</b>\n没有找到近期新闻（大马/印尼中小型股常见）。"
    lines = [f"<b>📰 新闻情绪：{n['mood']}</b>（平均 {n['avg']:+.2f}）"]
    for i in n["items"]:
        icon = "🟢" if i["score"] > 0.15 else "🔴" if i["score"] < -0.15 else "⚪"
        title = _esc(i["title"])
        lines.append(f"{icon} <a href=\"{i['link']}\">{title}</a>" if i["link"]
                     else f"{icon} {title}")
    return "\n".join(lines)


def build_snapshot(ticker, tech, fund, news) -> dict:
    """给 AI 基金经理看的数据摘要（纯数字/文字，不含 HTML）。"""
    r = lambda x, n=2: None if x is None or pd.isna(x) else round(float(x), n)
    strip = lambda s: s[2:] if s[:1] in "🟢🔴⚪✨⚠" else s
    return {
        "代码": ticker, "名称": fund["name"], "市场": market_of(ticker),
        "行业": f"{fund['sector'] or ''} / {fund['industry'] or ''}",
        "货币": fund["currency"],
        "技术面": {
            "股价": r(tech["price"]), "今日涨跌%": r(tech["change_1d"]),
            "1个月涨跌%": r(tech["change_1m"]), "1年涨跌%": r(tech["change_1y"]),
            "52周高": r(tech["high_52w"]), "52周低": r(tech["low_52w"]),
            "50日均线": r(tech["sma50"]), "200日均线": r(tech["sma200"]),
            "RSI14": r(tech["rsi"], 1), "信号": [strip(x).strip() for x in tech["signals"]],
            "技术分数": tech["score"], "技术结论": tech["verdict"],
        },
        "基本面": {
            "市值": fund["market_cap"], "本益比": r(fund["pe"]),
            "预期本益比": r(fund["forward_pe"]), "市净率": r(fund["pb"]),
            "净利率%": r(fund["profit_margin"] * 100) if fund["profit_margin"] is not None else None,
            "股息率%": r(fund["dividend_yield"]),
            "分析师目标价": r(fund["target_price"]), "分析师建议": fund["analyst_rec"],
            "要点": [strip(x).strip() for x in fund["flags"]],
        },
        "新闻": {
            "整体情绪": news["mood"],
            "标题(情绪分 -1~+1)": [f"{i['title']} ({i['score']:+.2f})" for i in news["items"]],
        },
    }


def analyze_raw(text: str) -> dict:
    """取数据 + 算好所有结果（网站和机器人共用）。"""
    ticker = normalize_ticker(text)
    df = get_history(ticker)
    info = get_info(ticker)
    tech = technical_summary(df)
    fund = fundamental_summary(ticker, info, tech["price"])
    news = news_sentiment(ticker)
    return {"ticker": ticker, "df": df, "tech": tech, "fund": fund, "news": news,
            "snapshot": build_snapshot(ticker, tech, fund, news)}


def full_report(text: str) -> tuple[str, str, pd.DataFrame, dict]:
    """Telegram 用：返回 (代码, HTML报告, 股价历史, 给AI的数据快照)。"""
    r = analyze_raw(text)
    ticker, tech, fund, news = r["ticker"], r["tech"], r["fund"], r["news"]
    report = "\n\n".join([
        f"🔎 <b>{_esc(fund['name'])}</b>（{ticker} · {market_of(ticker)}）",
        format_technical(ticker, tech, fund["currency"]),
        format_fundamental(fund),
        format_news(news),
    ])
    return ticker, report, r["df"], r["snapshot"]
