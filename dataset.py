"""全部股票的一张大表（约 500 只）：给「我的仪表板」画图、给 AI 助手筛股票用。

资料来自每天收市后的板块报告（reports/sectors/<市场>/最新.json），不用另外抓网络，所以很快。
每一行 = 一只股票；栏位都是中文名称，方便自己写规则（例如「股息率 >= 5」）。
"""
from __future__ import annotations

import json

import pandas as pd

MARKET_ZH = {"bursa": "马股", "idx": "印尼股", "us": "美股"}
CUR = {"bursa": "MYR", "idx": "IDR", "us": "USD"}

# 栏位：内部名 → 中文名（规则、图表都用中文名）
FIELDS = {
    "price": "股价", "mcap_myr": "市值(亿令吉)", "pe": "本益比", "pb": "股价净值比", "div_yield": "股息率%",
    "roe": "ROE%", "margin": "净利率%", "rev_growth": "营收增长%", "eps_growth": "盈利增长%",
    "debt_equity": "负债权益比", "rsi": "RSI", "chg_1d": "1日涨跌%", "chg_1w": "1周涨跌%", "chg_1m": "1个月涨跌%",
    "chg_3m": "3个月涨跌%", "chg_1y": "1年涨跌%", "ma50_gap": "距50日均线%", "ma200_gap": "距200日均线%",
}
NUMERIC = list(FIELDS.values()) + ["PEG"]
CATEGORIES = ["市场", "板块", "行业", "主题", "自选股"]
TEXT = ["代码", "名称"]
ALL_FIELDS = TEXT + CATEGORIES + NUMERIC


def _fx() -> dict:
    try:
        import pfcheck as PC
        r, _ = PC.fx_rates({"USD", "IDR"})
        return r
    except Exception:
        return {"MYR": 1.0, "USD": 4.4, "IDR": 0.00027}


def load(mine: set[str] | None = None) -> pd.DataFrame:
    import sectors as SE
    if mine is None:
        try:
            import announce
            mine = announce.my_tickers()
        except Exception:
            mine = set()
    fx = _fx()
    rows, themes = {}, {}
    for m in ("bursa", "idx", "us"):
        r = SE.latest(m)
        if not r:
            continue
        for g in r.get("themes", []) or []:
            for x in g.get("members", []):
                themes.setdefault(x["ticker"], []).append(g["name"])
        for g in r.get("sectors", []):
            for x in g.get("members", []):
                if x["ticker"] in rows:
                    continue
                row = {"代码": x["ticker"], "名称": x.get("name") or x["ticker"], "市场": MARKET_ZH[m],
                       "板块": g["name"], "行业": x.get("industry") or "—"}
                for k, zh in FIELDS.items():
                    if k == "mcap_myr":
                        v = x.get("mcap")
                        row[zh] = round(v * fx.get(CUR[m], 1) / 1e8, 2) if v else None
                    else:
                        row[zh] = x.get(k)
                rows[x["ticker"]] = row
    df = pd.DataFrame(list(rows.values()))
    if df.empty:
        return pd.DataFrame(columns=ALL_FIELDS)
    df["主题"] = df["代码"].map(lambda t: "、".join(themes.get(t, [])) or "—")
    df["自选股"] = df["代码"].map(lambda t: "是" if t in mine else "否")
    for c in NUMERIC:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # PEG = 本益比 ÷ 盈利增长率（两个都要是正数才算）：越低 = 以成长来说越便宜
    ok = (df["本益比"] > 0) & (df["盈利增长%"] > 0)
    df["PEG"] = (df["本益比"] / df["盈利增长%"]).where(ok).round(2)
    return df[ALL_FIELDS]


# ---------------------------------------------------------------------------
# 规则：[{"栏位": "股息率%", "条件": ">=", "数值": 5}, ...]
# ---------------------------------------------------------------------------

OPS = [">", ">=", "<", "<=", "=", "!=", "包含", "不包含", "介于"]


def apply_rules(df: pd.DataFrame, rules: list[dict]) -> pd.DataFrame:
    out = df
    for r in rules or []:
        f, op, v = r.get("栏位") or r.get("field"), r.get("条件") or r.get("op"), r.get("数值", r.get("value"))
        if f not in out.columns or op not in OPS or v in (None, ""):
            continue
        col = out[f]
        try:
            if op == "介于":
                lo, hi = (v if isinstance(v, (list, tuple)) else [float(x) for x in str(v).replace("~", ",").split(",")])[:2]
                out = out[(col >= float(lo)) & (col <= float(hi))]
            elif op in ("包含", "不包含"):
                words = [w.strip().lower() for w in str(v).replace("，", ",").split(",") if w.strip()]
                hit = col.astype(str).str.lower().apply(lambda s: any(w in s for w in words))
                out = out[hit if op == "包含" else ~hit]
            elif f in NUMERIC:
                x = float(v)
                out = out[{">": col > x, ">=": col >= x, "<": col < x, "<=": col <= x,
                           "=": col == x, "!=": col != x}[op]]
            else:
                hit = col.astype(str).str.lower() == str(v).lower()
                out = out[hit if op == "=" else ~hit] if op in ("=", "!=") else out
        except Exception:
            continue
    return out


def describe_rules(rules: list[dict]) -> str:
    return "；".join(f"{r.get('栏位')} {r.get('条件')} {r.get('数值')}" for r in rules or []) or "全部股票"


def screen(df: pd.DataFrame, rules: list[dict], sort: str | None = None, desc: bool = True,
           limit: int = 20, cols: list[str] | None = None) -> pd.DataFrame:
    out = apply_rules(df, rules)
    if sort in out.columns:
        out = out.sort_values(sort, ascending=not desc, na_position="last")
    cols = [c for c in (cols or ["代码", "名称", "市场", "板块", "股价", "本益比", "股息率%", "ROE%", "1个月涨跌%"])
            if c in out.columns]
    return out[cols].head(limit)


def to_records(df: pd.DataFrame, limit: int = 25) -> list[dict]:
    return json.loads(df.head(limit).to_json(orient="records", force_ascii=False))
