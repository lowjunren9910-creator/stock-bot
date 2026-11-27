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
    # ---- 更多规则（0 / 空 = 不用）----
    "gate_off": [],                # 关掉的基本关卡，例如 ["时机"]
    "extra_rules": [],             # 自己加的买入规则：[{"名称","栏位","条件","数值","开"}]
    "sell_profit": 50.0,           # 获利了结：涨了这么多 % → 考虑卖一部分锁利润（0 = 不用）
    "sell_ma_gap": 10.0,           # 趋势破坏：跌破 200 日均线超过这么多 % → 检讨（0 = 不用）
    "trim_over": 1.3,              # 单只超过「每只上限 × 这个倍数」→ 减持（0 = 不用）
    "plan": {"emerg_months": 6, "emerg_months_unstable": 9, "age_rule": True, "save_rate": 20.0,
             "rebalance_gap": 5.0, "min_pos": 2000.0},
}

# 可以一键打开的现成规则（「⚙️ 调整我的规则」里的「➕ 更多买入规则」）
PRESET_RULES = [
    {"名称": "有派息", "栏位": "股息率%", "条件": ">=", "数值": 2, "开": False},
    {"名称": "真的赚钱", "栏位": "净利率%", "条件": ">=", "数值": 8, "开": False},
    {"名称": "本益比不要太高", "栏位": "本益比", "条件": "<=", "数值": 30, "开": False},
    {"名称": "公司够大（市值 ≥ RM10 亿）", "栏位": "市值(亿令吉)", "条件": ">=", "数值": 10, "开": False},
    {"名称": "没有过热（RSI ≤ 70）", "栏位": "RSI", "条件": "<=", "数值": 70, "开": False},
    {"名称": "一年没大跌", "栏位": "1年涨跌%", "条件": ">=", "数值": -20, "开": False},
    {"名称": "股价净值比合理", "栏位": "股价净值比", "条件": "<=", "数值": 5, "开": False},
    {"名称": "短期趋势也向上（50 日均线之上）", "栏位": "距50日均线%", "条件": ">", "数值": 0, "开": False},
]

GATES = [("质量", "ROE"), ("成长", "营收或盈利增长"), ("价值", "PEG"), ("安全", "负债"), ("时机", "200 日均线")]


def normalize(d: dict | None) -> dict:
    """补上新版本才有的设定（旧的 my_strategy.json / 网站里的旧设定也能用）。"""
    d = d or {}
    out = {**json.loads(json.dumps(DEFAULT)), **d}
    out["plan"] = {**DEFAULT["plan"], **(d.get("plan") or {})}
    if not out.get("extra_rules"):
        out["extra_rules"] = [dict(r) for r in PRESET_RULES]
    return out


def load() -> dict:
    try:
        return normalize(json.loads(FILE.read_text(encoding="utf-8")))
    except Exception:
        return normalize({})


def rules_on(cfg: dict) -> list[dict]:
    return [r for r in cfg.get("extra_rules") or [] if r.get("开") and r.get("栏位") and r.get("数值") not in (None, "")]


def active_gates(cfg: dict) -> list[str]:
    g = [x for x, _ in GATES if x not in (cfg.get("gate_off") or [])]
    return g + (["自定"] if rules_on(cfg) else [])


def rule_text(r: dict) -> str:
    return f"{r['栏位']} {r['条件']} {r['数值']}"


def dump(cfg: dict) -> str:
    return json.dumps(cfg, ensure_ascii=False, indent=1)


def gate_text(cfg: dict) -> list[tuple[str, str]]:
    return [("质量", f"ROE ≥ {cfg['roe_min']:g}%"),
            ("成长", f"营收或盈利增长 ≥ {cfg['growth_min']:g}%"),
            ("价值", f"PEG ≤ {cfg['peg_max']:g}"),
            ("安全", f"负债权益比 ≤ {cfg['debt_max']:g}%" + ("（银行、产托例外）" if cfg["debt_exempt"] else "")),
            ("时机", "股价在 200 日均线之上" if cfg["trend_ma200"] else "不限")]


def chips(cfg: dict) -> list[tuple[str, str]]:
    off = cfg.get("gate_off") or []
    return [(g, t) for g, t in gate_text(cfg) if g not in off] + [(r.get("名称") or "自定", rule_text(r)) for r in rules_on(cfg)]


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
    import dataset as D2
    extra = rules_on(cfg)
    fails = pd.Series("", index=d.index)
    ok_all = pd.Series(True, index=d.index)
    for r in extra:
        hit = d.index.isin(D2.apply_rules(d, [r]).index)
        ok_all &= hit
        fails = fails.where(hit, fails + ("、" if True else "") + (r.get("名称") or rule_text(r)))
    d["过_自定"] = ok_all
    d["没过自定"] = fails.str.lstrip("、")
    keys = [f"过_{g}" for g in active_gates(cfg)]
    allk = [f"过_{g}" for g, _ in GATES] + ["过_自定"]
    d[allk] = d[allk].fillna(False).astype(bool)
    d["过关数"] = d[keys].sum(axis=1) if keys else 0
    d["关数"] = len(keys)
    off = set(cfg.get("gate_off") or [])

    def why(r):
        out = []
        if not r["过_质量"] and "质量" not in off:
            out.append(f"ROE {r['ROE%']:.1f}%" if pd.notna(r["ROE%"]) else "没有 ROE 资料")
        if not r["过_成长"] and "成长" not in off:
            out.append(f"成长 {r['成长%']:.1f}%" if pd.notna(r["成长%"]) else "没有成长资料")
        if not r["过_价值"] and "价值" not in off:
            out.append(f"PEG {r['PEG']:.2f}" if pd.notna(r["PEG"]) else "PEG 算不出（盈利没增长或亏损）")
        if not r["过_安全"] and "安全" not in off:
            out.append(f"负债 {r['负债权益比']:.0f}%" if pd.notna(r["负债权益比"]) else "没有负债资料")
        if not r["过_时机"] and "时机" not in off:
            out.append(f"在 200 日均线下 {r['距200日均线%']:.1f}%" if pd.notna(r["距200日均线%"]) else "没有均线资料")
        if r["没过自定"]:
            out.append("没过：" + r["没过自定"])
        return "；".join(out)
    d["没过的原因"] = d.apply(why, axis=1)

    # 综合分：质量（ROE）、成长、便宜（PEG 越低越好）在全部候选里的百分位，各占 1/3
    q = d["ROE%"].rank(pct=True)
    g = d["成长%"].rank(pct=True)
    v = (-d["PEG"]).rank(pct=True)
    d["综合分"] = ((q.fillna(0) + g.fillna(0) + v.fillna(0)) / 3 * 100).round(0)
    return d


def passed(ev: pd.DataFrame) -> pd.DataFrame:
    return ev[ev["过关数"] == ev["关数"]].sort_values("综合分", ascending=False)


def near_miss(ev: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    return ev[(ev["关数"] > 0) & (ev["过关数"] == ev["关数"] - 1)].sort_values("综合分", ascending=False).head(n)


def funnel(ev: pd.DataFrame, cfg: dict | None = None) -> list[tuple[str, int]]:
    out, mask = [("全部", len(ev))], pd.Series(True, index=ev.index)
    for g in (active_gates(cfg) if cfg else [x for x, _ in GATES]):
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


def sell_check(holdings: list[dict], ev_all: pd.DataFrame, cfg: dict, best_score: float | None,
               fx: dict | None = None) -> list[dict]:
    """你持有的股票碰到哪一条卖出 / 风险规则。holdings：[{代码, 数量, 平均成本}]
    🔴 考虑卖出：理由消失、太贵、止损、有更好的选择、趋势破坏
    🟡 考虑减持：获利很多、单只太重、板块太重"""
    import analysis as A
    fx = fx or {"MYR": 1.0, "USD": 4.4, "IDR": 0.00027}
    cur = {"马股": "MYR", "美股": "USD", "印尼股": "IDR"}
    idx = ev_all.set_index("代码")
    rows = []
    for h in holdings:
        try:
            t = A.normalize_ticker(h["代码"])
        except Exception:
            t = str(h["代码"]).upper()
        r = idx.loc[t] if t in idx.index else None
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        val = None
        if r is not None and pd.notna(r["股价"]):
            val = float(h.get("数量") or 0) * float(r["股价"]) * fx.get(cur.get(r["市场"], "MYR"), 1.0)
        rows.append((t, h, r, val))
    total = sum(v for *_, v in rows if v) or 0.0
    sec_w = {}
    for t, h, r, v in rows:
        if r is not None and v and total:
            sec_w[r["板块"]] = sec_w.get(r["板块"], 0) + v / total * 100

    out = []
    for t, h, r, val in rows:
        if r is None:
            out.append({"代码": t, "名称": t, "状态": "⚪ 不在资料里（不是马股 / 美股大中型股）", "原因": ""})
            continue
        sell, trim = [], []
        if not r["过_质量"] or not r["过_成长"]:
            sell.append("买入理由变弱：" + "、".join(x for x, ok in (("ROE", r["过_质量"]), ("成长", r["过_成长"])) if not ok)
                        + " 跌破门槛（连续 2 季都这样就卖）")
        if pd.notna(r["PEG"]) and r["PEG"] > cfg["sell_peg"]:
            sell.append(f"变太贵：PEG {r['PEG']:.2f} > {cfg['sell_peg']:g}")
        cost = float(h.get("平均成本") or 0)
        chg = (r["股价"] / cost - 1) * 100 if cost else None
        if chg is not None and chg <= -cfg["sell_loss"]:
            sell.append(f"止损：从买入价跌了 {-chg:.0f}%，重新检讨")
        gap = cfg.get("sell_ma_gap") or 0
        if gap and pd.notna(r["距200日均线%"]) and r["距200日均线%"] <= -gap:
            sell.append(f"趋势破坏：跌破 200 日均线 {-r['距200日均线%']:.0f}%")
        if best_score is not None and pd.notna(r["综合分"]) and best_score - r["综合分"] >= cfg["swap_gap"] and r["过关数"] < r["关数"]:
            sell.append(f"有更好的选择：综合分 {r['综合分']:.0f}，符合规则的最好一只是 {best_score:.0f}")
        prof = cfg.get("sell_profit") or 0
        if prof and chg is not None and chg >= prof:
            trim.append(f"获利了结：已经涨了 {chg:.0f}%，可以考虑卖一部分（例如 1/3）锁住利润")
        w = val / total * 100 if val and total else None
        lim = (cfg.get("trim_over") or 0) * cfg["weight_max"]
        if lim and w is not None and w > lim and len(rows) > 1:
            trim.append(f"单只太重：占组合 {w:.0f}%（上限 {cfg['weight_max']:g}%）")
        sw = sec_w.get(r["板块"])
        if sw is not None and sw > cfg["sector_max"] and len(rows) > 1:
            trim.append(f"板块太重：{r['板块']} 占组合 {sw:.0f}%（上限 {cfg['sector_max']:g}%）")
        state = "🔴 考虑卖出" if sell else "🟡 考虑减持" if trim else "🟢 继续持有"
        out.append({"代码": t, "名称": r["名称"], "盈亏%": round(chg, 1) if chg is not None else None,
                    "占组合%": round(w, 1) if w is not None else None,
                    "综合分": r["综合分"], "过关": f"{int(r['过关数'])}/{int(r['关数'])}",
                    "状态": state, "原因": "；".join(sell + trim)})
    return out
