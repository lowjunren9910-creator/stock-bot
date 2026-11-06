"""
fundamentals.py - 批量抓股价和基本面（选股雷达、KLCI 观察共用）

同一次运行里，同一只股票只抓一次（有缓存），避免被 Yahoo 限速。
"""

from __future__ import annotations

import atexit
import json
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# 硬盘缓存：公司资料（info）和每年 EPS 变化很慢，不用每天重抓。
# 股票池扩大到约 500 只后，这样每天只需要重抓大约 1/3，不容易被 Yahoo 限速。
# 存在 reports/cache/fundamentals.json，程序结束时自动保存。
# ---------------------------------------------------------------------------
CACHE_FILE = Path(__file__).parent / "reports" / "cache" / "fundamentals.json"
KEEP = (  # 只存用得到的栏位，文件才不会太大
    "shortName", "longName", "sector", "industry", "currency", "financialCurrency",
    "marketCap", "sharesOutstanding", "impliedSharesOutstanding", "floatShares",
    "trailingPE", "forwardPE", "trailingEps", "priceToBook", "dividendYield", "payoutRatio",
    "returnOnEquity", "returnOnAssets", "profitMargins", "grossMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth", "debtToEquity", "currentRatio", "totalRevenue",
    "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "enterpriseToEbitda",
    "mostRecentQuarter", "earningsTimestamp", "heldPercentInsiders", "recommendationKey",
    "longBusinessSummary",
)
_lock = threading.Lock()
_disk: dict | None = None
_dirty = False


def _load() -> dict:
    global _disk
    if _disk is None:
        try:
            _disk = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            _disk = {}
    return _disk


def _fresh(ticker: str, stamp: str | None, days: int) -> bool:
    """每只股票的有效期错开（days ~ days+2 天），每天只会有一部分过期。"""
    if not stamp:
        return False
    jitter = zlib.crc32(ticker.encode()) % 3
    return stamp >= str(date.today() - timedelta(days=days + jitter))


def _put(ticker: str, **kv):
    global _dirty
    with _lock:
        _load().setdefault(ticker, {}).update(kv)
        _dirty = True


@atexit.register
def save_cache():
    global _dirty
    if not _dirty or _disk is None:
        return
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(_disk, ensure_ascii=False, separators=(",", ":"), default=str),
                              encoding="utf-8")
        _dirty = False
    except Exception as e:
        print("保存基本面缓存失败：", e)


def prices(tickers: list[str], period: str = "2y") -> dict[str, pd.DataFrame]:
    """批量下载日线。返回 {代码: DataFrame}，数据太少的不返回。"""
    raw = yf.download(tickers, period=period, interval="1d", group_by="ticker",
                      auto_adjust=False, progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if len(df) >= 60:
                out[t] = df
        except KeyError:
            continue
    return out


@lru_cache(maxsize=4096)
def info(ticker: str) -> dict:
    hit = _load().get(ticker) or {}
    if hit.get("info") and _fresh(ticker, hit.get("info_d"), 2):
        return hit["info"]
    try:
        full = yf.Ticker(ticker).info or {}
    except Exception:
        full = {}
    slim = {k: full[k] for k in KEEP if full.get(k) is not None}
    if "longBusinessSummary" in slim:
        slim["longBusinessSummary"] = slim["longBusinessSummary"][:400]   # 只留开头，文件才不会太大
    if slim:
        _put(ticker, info=slim, info_d=str(date.today()))
        return slim
    return hit.get("info") or {}      # 抓不到：先用旧的


def _eps_from_web(ticker: str) -> pd.Series:
    try:
        inc = yf.Ticker(ticker).income_stmt
    except Exception:
        return pd.Series(dtype=float)
    if not isinstance(inc, pd.DataFrame) or inc.empty:
        return pd.Series(dtype=float)
    for name in ("Diluted EPS", "Basic EPS"):
        if name in inc.index:
            r = inc.loc[name]
            if isinstance(r, pd.DataFrame):
                r = r.iloc[0]
            s = pd.to_numeric(r, errors="coerce").dropna()
            s.index = pd.to_datetime(s.index)
            return s.sort_index()
    return pd.Series(dtype=float)


@lru_cache(maxsize=4096)
def annual_eps(ticker: str) -> pd.Series:
    """每个财政年度的每股盈利 {财年结束日: EPS}，旧 → 新。缓存 10 天左右。"""
    hit = _load().get(ticker) or {}
    if "eps" in hit and _fresh(ticker, hit.get("eps_d"), 10):
        s = pd.Series(hit["eps"], dtype=float)
        s.index = pd.to_datetime(s.index)
        return s.sort_index()
    s = _eps_from_web(ticker)
    if len(s) or "eps" not in hit:
        _put(ticker, eps={str(k.date()): float(v) for k, v in s.items()}, eps_d=str(date.today()))
        return s
    old = pd.Series(hit["eps"], dtype=float)
    old.index = pd.to_datetime(old.index)
    return old.sort_index()


def prefetch(tickers: list[str], with_eps: bool = True, workers: int = 6):
    """多线程预先抓好 info（和 EPS），后面直接读缓存。"""
    jobs = [info] + ([annual_eps] if with_eps else [])
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda t: [f(t) for f in jobs], tickers))


def historical_pe(ticker: str, px: pd.DataFrame) -> float | None:
    """过去几个财年年底的平均本益比（股价 ÷ 当年 EPS），只算盈利为正的年份。"""
    eps = annual_eps(ticker)
    i = info(ticker)
    if eps.empty or (i.get("financialCurrency") and i.get("currency")
                     and i["financialCurrency"] != i["currency"]):
        return None
    close = px["Close"]
    idx = close.index.tz_localize(None) if close.index.tz is not None else close.index
    close = pd.Series(close.values, index=idx)
    pes = []
    for d, e in eps.items():
        if e <= 0:
            continue
        before = close[close.index <= d]
        if len(before) and (d - before.index[-1]).days < 10:
            pes.append(before.iloc[-1] / e)
    pes = [p for p in pes if 0 < p < 150]  # 去掉极端值
    return sum(pes) / len(pes) if len(pes) >= 2 else None
