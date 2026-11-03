"""
fundamentals.py - 批量抓股价和基本面（选股雷达、KLCI 观察共用）

同一次运行里，同一只股票只抓一次（有缓存），避免被 Yahoo 限速。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import pandas as pd
import yfinance as yf


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


@lru_cache(maxsize=1024)
def info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except Exception:
        return {}


@lru_cache(maxsize=1024)
def annual_eps(ticker: str) -> pd.Series:
    """每个财政年度的每股盈利 {财年结束日: EPS}，旧 → 新。"""
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
