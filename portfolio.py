"""
portfolio.py - 用本地 SQLite 文件记录每位用户的持股。
重复买入同一只股票会自动计算平均成本。
"""

import sqlite3
from contextlib import closing

import yfinance as yf

DB_FILE = "portfolio.db"


def _conn():
    con = sqlite3.connect(DB_FILE)
    con.execute(
        """CREATE TABLE IF NOT EXISTS holdings (
               user_id   INTEGER,
               ticker    TEXT,
               qty       REAL,
               avg_cost  REAL,
               PRIMARY KEY (user_id, ticker))"""
    )
    return con


def buy(user_id: int, ticker: str, qty: float, price: float) -> str:
    with closing(_conn()) as con, con:
        row = con.execute(
            "SELECT qty, avg_cost FROM holdings WHERE user_id=? AND ticker=?",
            (user_id, ticker),
        ).fetchone()
        if row:
            old_qty, old_cost = row
            new_qty = old_qty + qty
            new_cost = (old_qty * old_cost + qty * price) / new_qty
            con.execute(
                "UPDATE holdings SET qty=?, avg_cost=? WHERE user_id=? AND ticker=?",
                (new_qty, new_cost, user_id, ticker),
            )
        else:
            new_qty, new_cost = qty, price
            con.execute("INSERT INTO holdings VALUES (?,?,?,?)",
                        (user_id, ticker, qty, price))
    return f"✅ {ticker}：现在持有 {new_qty:,.0f} 股，平均成本 {new_cost:,.4f}"


def sell(user_id: int, ticker: str, qty: float | None = None) -> str:
    with closing(_conn()) as con, con:
        row = con.execute(
            "SELECT qty FROM holdings WHERE user_id=? AND ticker=?",
            (user_id, ticker),
        ).fetchone()
        if not row:
            return f"你没有持有 {ticker}。"
        if qty is None or qty >= row[0]:
            con.execute("DELETE FROM holdings WHERE user_id=? AND ticker=?",
                        (user_id, ticker))
            return f"🗑 已清空 {ticker}。"
        con.execute("UPDATE holdings SET qty=? WHERE user_id=? AND ticker=?",
                    (row[0] - qty, user_id, ticker))
        return f"✅ 卖出 {qty:,.0f} 股 {ticker}，剩下 {row[0]-qty:,.0f} 股。"


def _last_price(ticker: str) -> float | None:
    try:
        h = yf.Ticker(ticker).history(period="5d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception:
        return None


def _currency(ticker: str) -> str:
    if ticker.endswith(".KL"):
        return "MYR"
    if ticker.endswith(".JK"):
        return "IDR"
    return "USD"


def report(user_id: int) -> str:
    with closing(_conn()) as con:
        rows = con.execute(
            "SELECT ticker, qty, avg_cost FROM holdings WHERE user_id=? ORDER BY ticker",
            (user_id,),
        ).fetchall()
    if not rows:
        return ("你的投资组合是空的。\n"
                "添加持股：<code>/buy 1155.KL 1000 9.80</code>")

    lines = ["<b>💼 我的投资组合</b>"]
    totals = {}  # currency -> [cost, value] (kept separate: no FX conversion)
    for ticker, qty, cost in rows:
        price = _last_price(ticker)
        cur = _currency(ticker)
        if price is None:
            lines.append(f"⚪ {ticker}：{qty:,.0f} 股 @ {cost:,.2f}（暂时拿不到股价）")
            continue
        value, invested = qty * price, qty * cost
        pl = value - invested
        pct = pl / invested * 100 if invested else 0
        icon = "🟢" if pl >= 0 else "🔴"
        lines.append(
            f"{icon} <b>{ticker}</b> {qty:,.0f} × {price:,.2f} "
            f"（成本 {cost:,.2f}）→ 盈亏 {pl:+,.2f} {cur}（{pct:+.1f}%）"
        )
        t = totals.setdefault(cur, [0.0, 0.0])
        t[0] += invested
        t[1] += value

    lines.append("")
    for cur, (inv, val) in totals.items():
        pct = (val - inv) / inv * 100 if inv else 0
        lines.append(f"<b>{cur} 合计：</b>{val:,.2f}（盈亏 {val-inv:+,.2f}，{pct:+.1f}%）")
    return "\n".join(lines)
