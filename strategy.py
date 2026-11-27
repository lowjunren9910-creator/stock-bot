"""我的策略：用自己的投资规则筛出公司（网站「🎯 我的策略」）。

默认规则 = 你自己定的「合理价格买成长好公司（GARP）」：
  买入 5 关：质量 ROE ≥ 10%｜成长 营收或盈利增长 ≥ 10%｜价值 PEG ≤ 1.5｜安全 负债权益比 ≤ 50%（银行、产托例外）
            ｜时机 股价在 200 日均线之上
  挑选：综合分（质量、成长、便宜各 1/3）排名；组合 8–12 只、每只 ≤ 15%、同板块 ≤ 35%
  卖出：理由消失（ROE / 成长跌破门槛）｜PEG > 2.5｜从买入价跌 20%｜有明显更好的选择
门槛可以在网站上改，存在 my_strategy.json。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

FILE = Path(__file__).parent / "my_strategy.json"

DEFAULT = {
    "name": "合理价格买成长好公司（GARP）",
    "goal": "长期增值，每只持有半年到两年",
    "markets": ["马股", "美股"],
    "roe_min": 10.0,          # 质量
    "growth_min": 10.0,       # 成长（营收或盈利，任一达标）
    "peg_max": 1.5,           # 价值
    "debt_max": 50.0,         # 安全（负债权益比 %）
    "debt_exempt": True,      # 银行、产托不看负债
    "trend_ma200": True,      # 时机：股价在 200 日均线之上
    "n_min": 8, "n_max": 12, "weight_max": 15.0, "sector_max": 35.0,
    "sell_peg": 2.5, "sell_loss": 20.0, "swap_gap": 15.0,
}

GATES = [("质量", "ROE"), ("成长", "营收或盈利增长"), ("价值", "PEG"), ("安全", "负债"), ("时机", "200 日均线")]


def load() -> dict:
    try:
        d = json.loads(FILE.read_text(encoding="utf-8"))
        return {**DEFAULT, **d}
    except Exception:
        return dict(DEFAULT)


def dump(cfg: dict) -> str:
    return json.dumps(cfg, ensure_ascii=False, indent=1)


def gate_text(cfg: dict) -> list[tuple[str, str]]:
    return [("质量", f"ROE ≥ {cfg['roe_min']:g}%"),
            ("成长", f"营收或盈利增长 ≥ {cfg['growth_min']:g}%"),
            ("价值", f"PEG ≤ {cfg['peg_max']:g}"),
            ("安全", f"负债权益比 ≤ {cfg['debt_max']:g}%" + ("（银行、产托例外）" if cfg["debt_exempt"] else "")),
            ("时机", "股价在 200 日均线之上" if cfg["trend_ma200"] else "不限")]


def _exempt(row) -> bool:
    ind = str(row.get("行业") or "").lower()
    return (row.get("板块") == "金融" or "bank" in ind or "reit" in ind or "REIT" in str(row.get("主题") or "")
            or "银行" in str(row.get("主题") or ""))


def evaluate(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """每只股票每一关过不过、为什么没过、综合分。"""
    import dataset as D
    d = D.ensure(df)
    if cfg.get("markets"):
        d = d[d["市场"].isin(cfg["markets"])]
    growth = d[["营收增长%", "盈利增长%"]].max(axis=1)
    d["成长%"] = growth
    d["过_质量"] = d["ROE%"] >= cfg["roe_min"]
    d["过_成长"] = growth >= cfg["growth_min"]
    d["过_价值"] = d["PEG"].notna() & (d["PEG"] <= cfg["peg_max"])
    exempt = d.apply(_exempt, axis=1) if cfg["debt_exempt"] else pd.Series(False, index=d.index)
    d["例外"] = exempt
    d["过_安全"] = exempt | (d["负债权益比"].notna() & (d["负债权益比"] <= cfg["debt_max"]))
    d["过_时机"] = (d["距200日均线%"] > 0) if cfg["trend_ma200"] else True
    keys = [f"过_{g}" for g, _ in GATES]
    d[keys] = d[keys].fillna(False).astype(bool)
    d["过关数"] = d[keys].sum(axis=1)

    def why(r):
        out = []
        if not r["过_质量"]:
            out.append(f"ROE {r['ROE%']:.1f}%" if pd.notna(r["ROE%"]) else "没有 ROE 资料")
        if not r["过_成长"]:
            out.append(f"成长 {r['成长%']:.1f}%" if pd.notna(r["成长%"]) else "没有成长资料")
        if not r["过_价值"]:
            out.append(f"PEG {r['PEG']:.2f}" if pd.notna(r["PEG"]) else "PEG 算不出（盈利没增长或亏损）")
        if not r["过_安全"]:
            out.append(f"负债 {r['负债权益比']:.0f}%" if pd.notna(r["负债权益比"]) else "没有负债资料")
        if not r["过_时机"]:
            out.append(f"在 200 日均线下 {r['距200日均线%']:.1f}%" if pd.notna(r["距200日均线%"]) else "没有均线资料")
        return "；".join(out)
    d["没过的原因"] = d.apply(why, axis=1)

    # 综合分：质量（ROE）、成长、便宜（PEG 越低越好）在全部候选里的百分位，各占 1/3
    q = d["ROE%"].rank(pct=True)
    g = d["成长%"].rank(pct=True)
    v = (-d["PEG"]).rank(pct=True)
    d["综合分"] = ((q.fillna(0) + g.fillna(0) + v.fillna(0)) / 3 * 100).round(0)
    return d


def passed(ev: pd.DataFrame) -> pd.DataFrame:
    return ev[ev["过关数"] == len(GATES)].sort_values("综合分", ascending=False)


def near_miss(ev: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    return ev[ev["过关数"] == len(GATES) - 1].sort_values("综合分", ascending=False).head(n)


def funnel(ev: pd.DataFrame) -> list[tuple[str, int]]:
    out, mask = [("全部", len(ev))], pd.Series(True, index=ev.index)
    for g, _ in GATES:
        mask = mask & ev[f"过_{g}"]
        out.append((g, int(mask.sum())))
    return out


def model_portfolio(p: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """按综合分由高到低挑，遵守每个板块 ≤ sector_max%；平均分配，每只 ≤ weight_max%。"""
    n_max = int(cfg["n_max"])
    per = max(100 / n_max, 100 / max(len(p), 1))
    per = min(per, cfg["weight_max"])
    cap = max(1, int(cfg["sector_max"] // per))
    picks, count = [], {}
    for _, r in p.iterrows():
        if len(picks) >= n_max:
            break
        if count.get(r["板块"], 0) >= cap:
            continue
        picks.append(r)
        count[r["板块"]] = count.get(r["板块"], 0) + 1
    if not picks:
        return pd.DataFrame()
    out = pd.DataFrame(picks)
    w = min(100 / len(out), cfg["weight_max"])
    out["建议比重%"] = round(w, 1)
    out["现金%"] = round(max(0.0, 100 - w * len(out)), 1)
    return out


def sell_check(holdings: list[dict], ev_all: pd.DataFrame, cfg: dict, best_score: float | None) -> list[dict]:
    """你持有的股票碰到哪一条卖出规则。holdings：[{代码, 数量, 平均成本}]"""
    import analysis as A
    out = []
    idx = ev_all.set_index("代码")
    for h in holdings:
        try:
            t = A.normalize_ticker(h["代码"])
        except Exception:
            t = str(h["代码"]).upper()
        if t not in idx.index:
            out.append({"代码": t, "名称": t, "状态": "⚪ 不在资料里（不是马股 / 美股大中型股）", "原因": ""})
            continue
        r = idx.loc[t]
        reasons = []
        if not r["过_质量"] or not r["过_成长"]:
            reasons.append("买入理由变弱：" + "、".join(x for x, ok in (("ROE", r["过_质量"]), ("成长", r["过_成长"])) if not ok)
                           + " 跌破门槛（连续 2 季都这样就卖）")
        if pd.notna(r["PEG"]) and r["PEG"] > cfg["sell_peg"]:
            reasons.append(f"变太贵：PEG {r['PEG']:.2f} > {cfg['sell_peg']:g}")
        cost = float(h.get("平均成本") or 0)
        loss = (r["股价"] / cost - 1) * 100 if cost else None
        if loss is not None and loss <= -cfg["sell_loss"]:
            reasons.append(f"止损：从买入价跌了 {loss:.0f}%，重新检讨")
        if best_score is not None and pd.notna(r["综合分"]) and best_score - r["综合分"] >= cfg["swap_gap"] and r["过关数"] < len(GATES):
            reasons.append(f"有更好的选择：综合分 {r['综合分']:.0f}，符合规则的最好一只是 {best_score:.0f}")
        out.append({"代码": t, "名称": r["名称"], "盈亏%": round(loss, 1) if loss is not None else None,
                    "综合分": r["综合分"], "过关": f"{int(r['过关数'])}/{len(GATES)}",
                    "状态": "🔴 考虑卖出" if reasons else "🟢 继续持有", "原因": "；".join(reasons)})
    return out
