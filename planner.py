"""资金规划：输入资金和条件 → 按「我的策略」算出具体怎么分配（规则透明，不靠 AI）。

1. 投资者类型决定基本比例：成长股（你的策略选出的）/ 收息防守股 / 现金（定存、货币基金）
2. 风险管理：估计「坏年头」组合会跌多少（成长股约 35%、收息股约 15%、现金 0%），
   超过你能接受的跌幅 → 把一部分成长股换成现金
3. 期望回报：用长期假设（成长股 9%、收息股 5.5%、现金 3%）估算，跟你的期望比较，不配就直接提醒
4. 挑股票：成长股 = 我的策略的建议组合；收息股 = 股息率高、赚钱、负债不高的公司
   钱少就买少几只（每只至少约 RM2,000，手续费才不会太贵）；按「一手」算能买几股
5. 每只的止损价、全部止损会亏多少、未来几年三种情境的预估
这些都是简化的假设，不是保证，也不是投资建议。
"""
from __future__ import annotations

import math

import pandas as pd

PROFILES = {
    "保守型": {"stock": 40, "income": 30, "cash": 30,
             "desc": "最在意不要亏太多，接受回报比较低；大部分放收息股和现金"},
    "稳健型": {"stock": 60, "income": 25, "cash": 15,
             "desc": "想要成长，但也要睡得着；成长股为主，搭配收息股和一些现金"},
    "积极型": {"stock": 85, "income": 5, "cash": 10,
             "desc": "追求长期最大成长，能接受一年内跌 30% 以上"},
}
# 长期假设（每年 %）：坏年头 / 一般 / 好年头
RETURNS = {"stock": (-25.0, 9.0, 18.0), "income": (-8.0, 5.5, 9.0), "cash": (3.0, 3.0, 3.0)}
BAD_DROP = {"stock": 0.35, "income": 0.15, "cash": 0.0}    # 坏年头最多跌多少（估计）
LOT = {"马股": 100, "印尼股": 100, "美股": 1}
CUR = {"马股": "MYR", "印尼股": "IDR", "美股": "USD"}
MIN_POS = 2000.0                                          # 每只至少约 RM2,000
TYPE_ZH = {"stock": "成长股", "income": "收息股", "cash": "现金"}


def quiz_profile(drop_reaction: str, horizon: str, experience: str) -> str:
    """3 个问题判断投资者类型（网站的「不确定？」）。"""
    score = {"马上卖掉": 0, "先观察": 1, "趁低加码": 2}.get(drop_reaction, 1)
    score += {"1 年内": 0, "1–3 年": 1, "3 年以上": 2}.get(horizon, 1)
    score += {"新手": 0, "有一些经验": 1, "很有经验": 2}.get(experience, 1)
    return "保守型" if score <= 2 else "稳健型" if score <= 4 else "积极型"


# ---------------------------------------------------------------------------
# 个人化问卷：更多问题 → 更贴近你的规划（答案只在这次用，不保存）
# ---------------------------------------------------------------------------
QUESTIONS = {
    # key: (问题, 选项, 默认第几个)
    "age": ("你的年龄", ["25 岁以下", "25–35 岁", "35–50 岁", "50 岁以上"], 0),
    "job": ("收入来源", ["学生 / 还没固定收入", "固定薪水", "自己做生意 / 收入不稳定", "已退休"], 0),
    "emerg": ("有没有应急钱（不算这笔投资）", ["有 6 个月生活费以上", "有 3–6 个月", "不到 3 个月", "没有"], 2),
    "debt": ("有没有信用卡或个人贷款这类高利息的债", ["没有", "有，但每月都还得完", "有，而且越欠越多"], 0),
    "share": ("这笔钱占你全部存款多少", ["不到 25%", "25–50%", "50–75%", "几乎全部"], 1),
    "goal": ("这笔钱主要是为了什么", ["长期增值", "退休", "买房 / 买车头期", "教育 / 进修", "每月有被动收入"], 0),
    "want": ("你比较想要", ["股价成长", "两样平衡", "稳定的股息收入"], 0),
    "drop": ("股票一个月跌了 20%，你会？", ["马上卖掉", "先观察", "趁低加码"], 1),
    "exp": ("投资经验", ["新手", "有一些经验", "很有经验"], 0),
    "watch": ("你多久会看一次投资", ["每天", "每星期", "每个月", "几乎不看"], 1),
}
QUIZ_GROUPS = [("👤 你的情况", ["age", "job", "emerg", "debt", "share"]),
               ("🎯 你的目标", ["goal", "want"]),
               ("🧠 你的性格", ["drop", "exp", "watch"])]
EMERG_HAVE = {"有 6 个月生活费以上": 6, "有 3–6 个月": 4.5, "不到 3 个月": 1.5, "没有": 0}


def default_answers() -> dict:
    return {k: v[1][v[2]] for k, v in QUESTIONS.items()}


def risk_score(a: dict) -> tuple[int, list[str]]:
    """0–100 分：分数越高越能承受风险。同时说明每题怎样影响。"""
    pts = {"age": {"25 岁以下": 3, "25–35 岁": 3, "35–50 岁": 2, "50 岁以上": 0},
           "job": {"学生 / 还没固定收入": 1, "固定薪水": 3, "自己做生意 / 收入不稳定": 1, "已退休": 0},
           "emerg": {"有 6 个月生活费以上": 3, "有 3–6 个月": 2, "不到 3 个月": 1, "没有": 0},
           "debt": {"没有": 3, "有，但每月都还得完": 2, "有，而且越欠越多": 0},
           "share": {"不到 25%": 3, "25–50%": 2, "50–75%": 1, "几乎全部": 0},
           "drop": {"马上卖掉": 0, "先观察": 2, "趁低加码": 3},
           "exp": {"新手": 1, "有一些经验": 2, "很有经验": 3}}
    weight = {"age": 1, "job": 1, "emerg": 1, "debt": 1, "share": 1.5, "drop": 2, "exp": 1}
    got = sum(pts[k].get(a.get(k), 1) * weight[k] for k in pts)
    full = sum(3 * weight[k] for k in pts)
    score = round(got / full * 100)
    why = []
    if a.get("drop") == "马上卖掉":
        why.append("跌 20% 会想马上卖 → 股票不宜放太多，不然很容易在最低点卖掉")
    if a.get("share") in ("50–75%", "几乎全部"):
        why.append("这笔钱占你大部分存款 → 要保守一点")
    if a.get("age") in ("25 岁以下", "25–35 岁") and a.get("job") == "固定薪水":
        why.append("年轻又有固定收入 → 时间站在你这边，可以承受多一点波动")
    if a.get("job") in ("学生 / 还没固定收入", "自己做生意 / 收入不稳定"):
        why.append("收入还不稳定 → 应急钱要多留一些")
    return score, why


def profile_from_score(score: int) -> str:
    return "保守型" if score < 45 else "稳健型" if score < 70 else "积极型"


def years_cap(years: int) -> float:
    """离要用钱的时间越近，股票（会大跌的部分）越少。"""
    return 0.1 if years <= 1 else 0.3 if years <= 2 else 0.5 if years <= 3 else 1.0


def stock_count(watch: str, n_max: int) -> int:
    return {"每天": n_max, "每星期": n_max, "每个月": min(n_max, 8), "几乎不看": min(n_max, 5)}.get(watch, n_max)


def income_candidates(ev: pd.DataFrame, markets: list[str]) -> pd.DataFrame:
    """收息防守股：股息率 ≥ 4%、ROE ≥ 8%、负债不高（金融例外）、一年没大跌。"""
    d = ev if not markets else ev[ev["市场"].isin(markets)]
    ok = (d["股息率%"].between(4, 15)) & (d["ROE%"] >= 8) & d["过_安全"] & (d["1年涨跌%"].fillna(0) > -20)
    out = d[ok].copy()
    out["收息分"] = out["股息率%"].rank(pct=True) + out["ROE%"].rank(pct=True)
    return out.sort_values("收息分", ascending=False)


def plan(capital: float, monthly: float, profile: str, max_drop: float, target: float, years: int,
         growth_picks: pd.DataFrame, income_picks: pd.DataFrame, fx: dict, cfg: dict,
         answers: dict | None = None, expense: float = 0.0) -> dict:
    a = answers or {}
    p = PROFILES[profile]
    w = {k: p[k] / 100 for k in ("stock", "income", "cash")}
    notes = []
    total = capital

    # 0. 先顾好基本：高利息债、应急钱
    if a.get("debt") == "有，而且越欠越多":
        notes.append("🚨 你的高利息债在越欠越多：信用卡利息一年约 15–18%，比股票长期回报还高。"
                     "最划算的「投资」是先还清它，再开始买股票。下面的规划只给你参考。")
    reserve = 0.0
    if expense > 0 and a.get("emerg") in EMERG_HAVE:
        need_m = 9 if a.get("job") in ("学生 / 还没固定收入", "自己做生意 / 收入不稳定") else 6
        short = max(0.0, (need_m - EMERG_HAVE[a["emerg"]]) * expense)
        reserve = min(short, capital * 0.5)
        if reserve > 0:
            notes.append(f"🧯 应急钱不够：建议备 {need_m} 个月生活费（RM {need_m * expense:,.0f}）。"
                         f"先从这笔钱留 RM {reserve:,.0f} 当应急钱（放定存 / 货币基金，不投资），"
                         + ("其余才拿去投资。" if reserve < short else "应急钱补够了，其余才拿去投资。")
                         + (f"还差 RM {short - reserve:,.0f}，之后每月的钱可以先补应急钱。" if reserve < short else ""))
            capital = capital - reserve

    # 1. 目标和偏好：调整成长 / 收息比例
    want = a.get("want")
    if want == "稳定的股息收入" or a.get("goal") == "每月有被动收入":
        mv = w["stock"] * 0.4
        w["stock"] -= mv
        w["income"] += mv
        notes.append(f"💵 你想要稳定收入：把 {mv * 100:.0f}% 从成长股移到收息股。")
    elif want == "股价成长" and a.get("goal") != "每月有被动收入":
        mv = w["income"] * 0.5
        w["income"] -= mv
        w["stock"] += mv
    cap = years_cap(years)
    eq = w["stock"] + w["income"]
    if eq > cap + 1e-9:
        f = cap / eq
        w["stock"] *= f
        w["income"] *= f
        w["cash"] = 1 - w["stock"] - w["income"]
        goal = a.get("goal", "")
        notes.append(f"⏳ {years} 年内就要用这笔钱{('（' + goal + '）') if goal and goal != '长期增值' else ''}：股票随时可能跌 20–30%，"
                     f"可能来不及等回来。所以股票从 {eq * 100:.0f}% 降到 {cap * 100:.0f}%，其余放定存 / 货币基金。")

    # 2. 风险管理：坏年头估计跌幅不能超过你能接受的
    def drop(w):
        return sum(w[k] * BAD_DROP[k] for k in w) * 100
    if drop(w) > max_drop:
        need = (max_drop / 100 - w["income"] * BAD_DROP["income"]) / BAD_DROP["stock"]
        new_stock = max(0.0, min(w["stock"], need))
        if w["stock"] - new_stock >= 0.02:
                notes.append(f"🛡️ 你能接受最多跌 {max_drop:g}%：成长股从 {w['stock'] * 100:.0f}% 降到 {new_stock * 100:.0f}%，多出来的放现金。")
        w["cash"] += w["stock"] - new_stock
        w["stock"] = new_stock

    exp = sum(w[k] * RETURNS[k][1] for k in w)
    if target > exp + 0.5:
        best = 0.9 * RETURNS["stock"][1] + 0.1 * RETURNS["cash"][1]
        notes.append(f"⚠️ 你期望每年 {target:g}%，但按你的风险条件，目标配置的长期估计只有约 {exp:.1f}%。"
                     + (f"就算几乎全部放成长股也只有约 {best:.1f}%，期望可能太高；" if target > best + 0.5 else
                        "想达到就要放更多在成长股，也就是要能接受更大的跌幅；")
                     + "建议调整期望或风险，不要为了追回报去冒自己受不了的风险。")
    elif exp > target + 3:
        notes.append(f"✅ 目标配置的长期估计约 {exp:.1f}%，比你的期望 {target:g}% 高，可以考虑再保守一点。")

    # 4. 挑股票、算股数
    rows, cash_left = [], capital * w["cash"]

    def fill(kind: str, picks: pd.DataFrame, budget: float, n_cap: int):
        """先平均分，买不够一手就至少买一手（预算够的话），剩下的钱再一手一手补给分数高的。"""
        nonlocal cash_left
        if budget <= 0 or picks.empty:
            cash_left += budget
            if budget > 0:
                notes.append(f"ℹ️ 今天没有符合条件的{TYPE_ZH[kind]}，这部分（RM {budget:,.0f}）先放现金。")
            return
        cap_amt = capital * cfg.get("weight_max", 15) / 100
        if cap_amt < MIN_POS * 1.5:            # 资金少：每只上限太小会什么都买不了 → 放宽，并提醒
            cap_amt = MIN_POS * 1.5
            msg = (f"ℹ️ 资金比较少：每只最多 {cfg.get('weight_max', 15):g}% 只有 RM {capital * cfg.get('weight_max', 15) / 100:,.0f}，"
                   f"买不到一手，所以放宽到每只最多约 RM {cap_amt:,.0f}（股票会比较集中，风险较高）。")
            if msg not in notes:
                notes.append(msg)
        cand = []
        for _, r in picks.iterrows():
            rate = fx.get(CUR.get(r["市场"], "MYR"), 1.0)
            lot = LOT.get(r["市场"], 100)
            lot_cost = float(r["股价"]) * rate * lot
            if lot_cost <= 0 or lot_cost > min(budget, cap_amt):
                continue                       # 一手都买不起 / 一手就超过上限：跳过，换下一只
            cand.append((r, lot, lot_cost))
        avg_lot = sum(c[2] for c in cand[:n_cap]) / max(1, len(cand[:n_cap]))
        n = max(1, min(n_cap, len(cand), int(budget // max(MIN_POS, avg_lot))))
        cand = cand[:n]
        if not cand:
            cash_left += budget
            notes.append(f"ℹ️ {TYPE_ZH[kind]}的预算 RM {budget:,.0f} 不够买一手符合条件的股票，先放现金（或考虑提高资金 / 美股碎股）。")
            return
        lots = [max(1, min(int((budget / len(cand)) // c[2]), int(cap_amt // c[2]))) for c in cand]
        cost = lambda: sum(l * c[2] for l, c in zip(lots, cand))
        while cost() > budget and max(lots) > 1:            # 超出预算：从买最多的那只减一手
            i = max(range(len(lots)), key=lambda k: lots[k] * cand[k][2])
            lots[i] -= 1
        changed = True
        while changed:                                       # 剩下的钱：一手一手补（分数高的先、不超过上限）
            changed = False
            for i, (r, lot, lc) in enumerate(cand):
                if cost() + lc <= budget and (lots[i] + 1) * lc <= cap_amt:
                    lots[i] += 1
                    changed = True
        for (r, lot, lc), l in zip(cand, lots):
            amt = l * lc
            rows.append({"类型": TYPE_ZH[kind], "名称": r["名称"], "代码": r["代码"], "市场": r["市场"], "板块": r["板块"],
                         "现价": float(r["股价"]), "货币": CUR.get(r["市场"], "MYR"), "每手股数": lot, "买几股": l * lot,
                         "金额(RM)": round(amt, 2), "止损价": round(float(r["股价"]) * (1 - cfg.get("sell_loss", 20) / 100), 3),
                         "股息率%": r.get("股息率%"), "综合分": r.get("综合分"), "备注": ""})
        cash_left += budget - cost()

    n_growth = stock_count(a.get("watch", "每星期"), int(cfg.get("n_max", 12)))
    if a.get("watch") == "几乎不看":
        notes.append("👀 你很少看投资：只买最多 5 只，省得照顾不来；也可以考虑指数基金 / ETF，最省心。")
    elif a.get("watch") == "每个月":
        notes.append("👀 你每个月看一次：最多买 8 只，比较容易跟进。")
    fill("stock", growth_picks, capital * w["stock"], n_growth)
    fill("income", income_picks, capital * w["income"], 5)
    pos = pd.DataFrame(rows)
    invested = float(pos["金额(RM)"].sum()) if len(pos) else 0.0
    if len(pos):
        pos["占比%"] = (pos["金额(RM)"] / capital * 100).round(1)

    actual = {"stock": float(pos[pos["类型"] == "成长股"]["金额(RM)"].sum()) if len(pos) else 0.0,
              "income": float(pos[pos["类型"] == "收息股"]["金额(RM)"].sum()) if len(pos) else 0.0}
    actual["cash"] = capital - actual["stock"] - actual["income"]
    aw = {k: v / capital for k, v in actual.items()} if capital else w

    # 5. 风险数字 + 未来预估
    stop_loss_total = float((pos["金额(RM)"] * cfg.get("sell_loss", 20) / 100).sum()) if len(pos) else 0.0
    scen = {}
    for i, name in enumerate(("坏情况", "一般", "好情况")):
        r = sum(aw[k] * RETURNS[k][i] for k in aw) / 100
        vals, v = [], capital
        for mth in range(years * 12 + 1):
            if mth:
                v = v * (1 + r) ** (1 / 12) + monthly
            vals.append(v + reserve * (1 + RETURNS["cash"][1] / 100) ** (mth / 12))
        scen[name] = vals
    put_in = total + monthly * years * 12
    div_year = float((pos["金额(RM)"] * pos["股息率%"].fillna(0) / 100).sum()) if len(pos) else 0.0
    return {"reserve": reserve, "total": total, "dividend_year": div_year, "answers": a, "capital_invest": capital, "weights_target": w, "weights_actual": aw, "positions": pos, "cash": actual["cash"], "invested": invested,
            "exp_return": sum(aw[k] * RETURNS[k][1] for k in aw), "bad_drop": drop(aw), "stop_loss_total": stop_loss_total,
            "scenarios": scen, "put_in": put_in, "notes": notes, "profile": profile, "years": years}


def brief(pl: dict, capital: float, monthly: float, target: float, max_drop: float) -> dict:
    pos = pl["positions"]
    return {"问卷回答": {QUESTIONS[k][0]: v for k, v in pl.get("answers", {}).items() if k in QUESTIONS},
            "先留的应急钱(RM)": round(pl.get("reserve", 0)), "估计每年股息(RM)": round(pl.get("dividend_year", 0)),
            "投资者类型": pl["profile"], "资金": capital, "每月追加": monthly, "期望每年回报%": target,
            "能接受最大跌幅%": max_drop, "持有年数": pl["years"],
            "实际配置%": {TYPE_ZH[k]: round(v * 100, 1) for k, v in pl["weights_actual"].items()},
            "长期估计回报%": round(pl["exp_return"], 1), "坏年头估计跌幅%": round(pl["bad_drop"], 1),
            "全部止损最多亏(RM)": round(pl["stop_loss_total"]),
            f"{pl['years']}年后估计(RM)": {k: round(v[-1]) for k, v in pl["scenarios"].items()},
            "持股": pos[["类型", "名称", "板块", "金额(RM)", "占比%"]].to_dict("records") if len(pos) else [],
            "系统提醒": pl["notes"]}


EXPLAIN_SYSTEM = """你是一位诚实、谨慎的理财规划师，帮一位投资新手解释系统算出来的投资组合规划。
规则：数字只能用提供的；不要推荐提供以外的股票；不要承诺回报；说清楚风险。用简体中文，口语化，不要用 Markdown 的 ** 或 #。
按格式输出（约 500–700 字）：
【这个规划适合你吗】2–3 句：对照他的问卷回答（年龄、收入、应急钱、目标、用钱时间）、类型、能接受的跌幅、期望回报
【钱是怎么分的】为什么这样分成长股 / 收息股 / 现金
【风险管理】最坏情况大概会怎样、止损怎么用、要留多少应急钱
【执行建议】分几次买入（例如分 3 个月）、多久检讨一次、什么情况要调整
【要注意】2–3 点（例如假设可能不准、集中在某板块、汇率）"""
