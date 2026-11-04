"""
klci.py - KLCI 50 观察：每天估算哪些马股最有机会进入 FBM KLCI 成分股

背景（2026 年 8 月公布）：
  FBM KLCI 由 30 只扩大到 50 只成分股，2026 年 12 月 21 日起分两阶段实施。
  选股依据：全市值（full market capitalisation）排名，且必须通过 FTSE 的资格筛选：
    - 自由流通量（free float）必须高于 15%
    - 流动性：非成分股过去 12 个月中，至少 10 个月的每日成交量中位数 ≥ 可投资股数的 0.050%
              现有成分股 8/12 个月 ≥ 0.040%
  2026 年 12 月检讨：数据截止 11 月 23 日（星期一），12 月 3 日公布，12 月 21 日生效。

本程序做的事：
  1. 抓约 100 只马股大型股的市值、自由流通量、成交量
  2. 套用上面的资格筛选（估算）
  3. 按全市值排名，找出第 50 名的"门槛市值"
  4. 按离门槛多远 + 离数据截止日多近，估算每家公司的入选几率

⚠️ 这是根据公开规则的模拟估算，不是官方结果。50 只成分股的新缓冲规则（例如排第几名才会被剔除）
   官方还没公布细节，所以以下用"排名 ≤ 50"作为入选标准。
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import fundamentals as F

REPORT_DIR = Path(__file__).parent / "reports" / "klci"
KL = ZoneInfo("Asia/Kuala_Lumpur")
TARGET_SIZE = 50

# ---------------------------------------------------------------------------
# 现有 30 只成分股（2026 年 6 月 22 日检讨后）
#   2026-03：Sunway Healthcare (SUNMED) 快速纳入，QL Resources 移出
#   2026-06：IOI Properties 纳入，Sime Darby 移出
# 每次官方检讨后记得更新这里！
# ---------------------------------------------------------------------------
CONSTITUENTS = {
    "5326.KL": "99 Speed Mart", "6888.KL": "Axiata", "6947.KL": "CelcomDigi",
    "1023.KL": "CIMB", "5398.KL": "Gamuda", "5819.KL": "Hong Leong Bank",
    "1082.KL": "HL Financial", "5225.KL": "IHH Healthcare", "1961.KL": "IOI Corp",
    "2445.KL": "KL Kepong", "1155.KL": "Maybank", "6012.KL": "Maxis",
    "3816.KL": "MISC", "5296.KL": "MR DIY", "4707.KL": "Nestle Malaysia",
    "5183.KL": "Petronas Chemicals", "5681.KL": "Petronas Dagangan", "6033.KL": "Petronas Gas",
    "4065.KL": "PPB Group", "8869.KL": "Press Metal", "1295.KL": "Public Bank",
    "1066.KL": "RHB Bank", "5285.KL": "SD Guthrie", "5211.KL": "Sunway",
    "4863.KL": "Telekom Malaysia", "5347.KL": "Tenaga Nasional", "4677.KL": "YTL Corp",
    "6742.KL": "YTL Power", "5555.KL": "Sunway Healthcare", "5249.KL": "IOI Properties",
}

# 其他大型股（候选名单）。想加公司就在这里加：代码.KL: 名称
CANDIDATES = {
    # 官方咨询文件 / 分析师提到的潜在新成分股
    "5031.KL": "TIME dotCom", "2089.KL": "United Plantations", "3336.KL": "IJM Corp",
    "7277.KL": "Dialog Group", "5878.KL": "KPJ Healthcare", "3182.KL": "Genting",
    "5246.KL": "Westports", "0166.KL": "Inari Amertron", "5227.KL": "IGB REIT",
    "2488.KL": "Alliance Bank", "5288.KL": "Sime Darby Property", "5176.KL": "Sunway REIT",
    "4715.KL": "Genting Malaysia", "3794.KL": "Malayan Cement", "5212.KL": "Pavilion REIT",
    "5263.KL": "Sunway Construction", "0097.KL": "ViTrox", "5337.KL": "Eco-Shop",
    "3034.KL": "Hap Seng", "4197.KL": "Sime Darby", "7084.KL": "QL Resources",
    # 其他大型股
    "1015.KL": "AMMB", "5258.KL": "Bank Islam", "1171.KL": "MBSB", "5185.KL": "Affin Bank",
    "1818.KL": "Bursa Malaysia", "1163.KL": "Allianz Malaysia", "5139.KL": "AEON Credit",
    "5235SS.KL": "KLCC Property", "5180.KL": "CapitaLand Malaysia Trust", "5106.KL": "Axis REIT",
    "5099.KL": "Capital A", "5238.KL": "AirAsia X", "0138.KL": "Zetrix AI (MyEG)",
    "4588.KL": "UMW Holdings", "5248.KL": "Bermaz Auto", "5209.KL": "Gas Malaysia",
    "5264.KL": "Malakoff", "3069.KL": "Mega First", "5272.KL": "Ranhill Utilities",
    "0215.KL": "Solarvest", "7293.KL": "Yinson", "5243.KL": "Velesto",
    "5199.KL": "Hibiscus Petroleum", "3042.KL": "Petron Malaysia", "5032.KL": "Bintulu Port",
    "2291.KL": "Genting Plantations", "5222.KL": "FGV", "5126.KL": "Sarawak Oil Palms",
    "7113.KL": "Top Glove", "5168.KL": "Hartalega", "7153.KL": "Kossan",
    "0128.KL": "Frontken", "0208.KL": "Greatech", "5005.KL": "Unisem",
    "7204.KL": "D&O Green Tech", "7160.KL": "Pentamaster", "5286.KL": "Mi Technovation",
    "0151.KL": "Kelington", "5292.KL": "UWC", "9822.KL": "SAM Engineering",
    "5309.KL": "ITMAX", "8664.KL": "SP Setia", "5148.KL": "UEM Sunrise",
    "8583.KL": "Mah Sing", "5236.KL": "Matrix Concepts", "3417.KL": "Eastern & Oriental",
    "5038.KL": "KSL Holdings", "4731.KL": "Scientex", "5401.KL": "Tropicana",
    "5284.KL": "Lotte Chemical Titan", "3301.KL": "Hong Leong Industries", "3255.KL": "Heineken Malaysia",
    "2836.KL": "Carlsberg Malaysia", "6599.KL": "AEON Co", "3689.KL": "Fraser & Neave",
    "7148.KL": "Duopharma", "6399.KL": "Astro", "5301.KL": "CTOS Digital",
    "2429.KL": "Tanco", "5273.KL": "Chin Hin", "9296.KL": "RCE Capital",
    "6963.KL": "VS Industry", "7100.KL": "Uchi Technologies", "0270.KL": "NationGate",
}

UNIVERSE = {**CONSTITUENTS, **CANDIDATES}

# 参考：官方/分析师公布过的模拟名单（不是最终结果）
REFERENCE = {
    "官方咨询文件模拟（2025 年 12 月数据）": [
        "5031.KL", "2089.KL", "3336.KL", "7277.KL", "5878.KL", "3182.KL", "5246.KL",
        "0166.KL", "5227.KL", "2488.KL", "5288.KL", "5176.KL", "5249.KL", "4715.KL",
        "3794.KL", "5212.KL", "5263.KL", "0097.KL", "5337.KL", "3034.KL"],
    "HLIB / CIMB 分析师模型（2026 年 8 月）": [
        "5246.KL", "2089.KL", "0097.KL", "4197.KL", "7084.KL", "5878.KL",
        "7277.KL", "5031.KL", "5263.KL", "3336.KL", "4715.KL", "2488.KL"],
}

SOURCES = [
    ("FTSE Russell：FBM KLCI 扩大至 50 只 FAQ",
     "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/policy-documents/ftse-bursa-malaysia-index-series-enhancement-faq.pdf"),
    ("FTSE Bursa Malaysia 指数编制规则 Ground Rules",
     "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/ftse-bursa-malaysia-index-series-ground-rules.pdf"),
    ("The Star：FBM KLCI to expand to 50 stocks（2026-08-20）",
     "https://www.thestar.com.my/business/business-news/2026/08/20/fbm-klci-to-expand-to-50-stocks-in-first-major-revamp-since-2009"),
    ("The Edge：Analysts see tech, construction benefitting from KLCI expansion（2026-08-21）",
     "https://theedgemalaysia.com/node/815365"),
]


# ---------------------------------------------------------------------------
# 检讨日期：每年 6 月和 12 月
#   生效：第三个星期五收市后（下个星期一开始）
#   数据截止：生效日前 4 个星期的星期一
#   公布：该月第一个星期五前的星期四
# ---------------------------------------------------------------------------

def _nth_weekday(y: int, m: int, weekday: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def review_dates(today: date | None = None) -> dict:
    today = today or datetime.now(KL).date()
    for y in (today.year, today.year + 1):
        for m in (6, 12):
            effective = _nth_weekday(y, m, 4, 3) + timedelta(days=3)  # 第三个星期五 → 下个星期一
            if effective <= today:
                continue
            cutoff = effective - timedelta(days=28)
            announce = _nth_weekday(y, m, 4, 1) - timedelta(days=1)
            return {"review": f"{y} 年 {m} 月检讨", "cutoff": str(cutoff), "announce": str(announce),
                    "effective": str(effective), "days_to_cutoff": (cutoff - today).days,
                    "days_to_announce": (announce - today).days}


# ---------------------------------------------------------------------------
# 资格筛选（估算）
# ---------------------------------------------------------------------------

def liquidity_months(px: pd.DataFrame, investable_shares: float, threshold: float) -> tuple[int, int]:
    """过去 12 个月中，有几个月的每日成交量中位数 ≥ 门槛（占可投资股数 %）。"""
    vol = px["Volume"].tail(260)
    monthly = vol.groupby([vol.index.year, vol.index.month])
    passed = total = 0
    for _, v in monthly:
        if len(v) < 5:
            continue
        total += 1
        passed += int(v.median() / investable_shares >= threshold)
    return passed, total


def probability(ratio: float, days_to_cutoff: int | None) -> float:
    """市值 ÷ 门槛市值 → 入选几率。越接近截止日，曲线越陡（变数越少）。"""
    days = 180 if days_to_cutoff is None else max(0, min(days_to_cutoff, 180))
    k = 6 + 14 * (1 - days / 180)
    return 1 / (1 + math.exp(-k * math.log(max(ratio, 1e-6))))


def track(now: datetime | None = None) -> dict:
    now = now or datetime.now(KL)
    tickers = list(UNIVERSE)
    px = F.prices(tickers, "1y")
    F.prefetch(list(px), with_eps=False)
    dates = review_dates(now.date())

    rows = []
    for t, df in px.items():
        i = F.info(t)
        price = float(df["Close"].iloc[-1])
        shares = i.get("sharesOutstanding") or i.get("impliedSharesOutstanding")
        mcap = price * shares if shares else i.get("marketCap")
        if not mcap:
            continue
        flt = i.get("floatShares")
        ff = min(1.0, flt / shares) if (flt and shares) else None
        is_con = t in CONSTITUENTS
        thr, need = (0.0004, 8) if is_con else (0.0005, 10)
        liq_pass = liq_total = None
        if shares:
            liq_pass, liq_total = liquidity_months(df, shares * (ff or 1.0), thr)
        ff_ok = ff is None or ff > 0.15
        liq_ok = liq_pass is None or liq_pass >= min(need, max(1, liq_total - (12 - need)))
        rows.append({
            "ticker": t, "name": UNIVERSE[t], "price": round(price, 3),
            "mcap": float(mcap), "free_float": round(ff * 100, 1) if ff else None,
            "liq_months": f"{liq_pass}/{liq_total}" if liq_pass is not None else None,
            "ff_ok": ff_ok, "liq_ok": liq_ok, "eligible": ff_ok and liq_ok,
            "constituent": is_con,
            "ret_1m": round((price / float(df["Close"].iloc[-22]) - 1) * 100, 2) if len(df) > 22 else None,
        })

    tbl = pd.DataFrame(rows).sort_values("mcap", ascending=False).reset_index(drop=True)
    tbl["rank_all"] = tbl.index + 1
    elig = tbl[tbl.eligible].reset_index(drop=True)
    rank_map = {t: n + 1 for n, t in enumerate(elig.ticker)}
    tbl["rank"] = tbl.ticker.map(lambda t: rank_map.get(t))           # 合格公司中的全市值排名
    cand = elig[~elig.constituent].reset_index(drop=True)
    cand_map = {t: n + 1 for n, t in enumerate(cand.ticker)}
    tbl["cand_rank"] = tbl.ticker.map(lambda t: cand_map.get(t))      # 非成分股中的排名

    # 2026 年 12 月是扩容：现有成分股（合格的）保留，空出来的名额给排名最高的非成分股
    transition = bool(dates and dates["effective"] == "2026-12-21")
    kept = int((tbl.constituent & tbl.eligible).sum())
    if transition:
        slots = 20  # 官方：新增 20 只；若有现有成分股不合格被剔除，名额会相应增加
        mode = (f"扩容模式：现有 30 只成分股保留，新增 {slots} 个名额给全市值最高的合格非成分股"
                + (f"（另有 {30 - kept} 只现有成分股的资格估算未达标，若真被剔除，名额会增加）"
                   if kept < 30 else ""))
        pool = cand
    else:
        slots = TARGET_SIZE
        mode = "常规模式：合格公司按全市值排名，前 50 名（新缓冲规则官方未公布，按排名估算）"
        pool = elig
    idx = min(slots, len(pool)) - 1
    cutoff_mcap = float(pool.mcap.iloc[idx]) if idx >= 0 else float(tbl.mcap.min())

    def prob(r):
        if r.constituent:
            if transition:
                p = 0.95 if r.eligible else 0.3
            else:  # 现有成分股有缓冲，用较宽的门槛（第 60 名）
                wide = float(elig.mcap.iloc[min(59, len(elig) - 1)])
                p = probability(r.mcap / wide, dates and dates["days_to_cutoff"])
        else:
            p = probability(r.mcap / cutoff_mcap, dates and dates["days_to_cutoff"])
        if not r.ff_ok:
            p *= 0.05   # 自由流通量不足基本上不能入选
        elif not r.liq_ok:
            p *= 0.3    # 流动性估算不达标（估算有误差，所以不是 0）
        return int(round(min(0.99, max(0.01, p)) * 100))

    tbl["prob"] = tbl.apply(prob, axis=1)
    tbl["gap_pct"] = ((cutoff_mcap / tbl.mcap - 1) * 100).round(1)  # 正数 = 还要涨多少 %

    def label(r):
        if r.constituent:
            return "现有成分股" if r.prob >= 50 else "现有成分股（有风险）"
        return "很可能入选" if r.prob >= 80 else "有机会" if r.prob >= 50 else \
            "边缘观察" if r.prob >= 20 else "机会较低"
    tbl["status"] = tbl.apply(label, axis=1)
    tbl["in_reference"] = tbl.ticker.map(lambda t: sum(t in v for v in REFERENCE.values()))
    tbl = tbl.astype(object).where(tbl.notna(), None)
    for col in ("rank", "cand_rank", "rank_all", "prob"):
        tbl[col] = pd.Series([int(v) if v is not None else None for v in tbl[col]],
                             index=tbl.index, dtype=object)

    newcomers = tbl[~tbl.constituent.astype(bool)].sort_values(["prob", "mcap"], ascending=False)
    report = {
        "date": str(now.date()), "generated_at": now.strftime("%Y-%m-%d %H:%M %Z"),
        "review": dates, "target_size": TARGET_SIZE, "mode": mode, "slots": slots,
        "transition": transition, "kept": kept,
        "cutoff_mcap": cutoff_mcap, "universe_size": len(tbl),
        "eligible_count": int(tbl.eligible.sum()),
        "expected_new": int((newcomers.prob >= 50).sum()),
        "top_candidates": newcomers.head(30).to_dict("records"),
        "at_risk": tbl[tbl.constituent.astype(bool) & (tbl.prob.astype(int) < 50)].to_dict("records"),
        "ranking": tbl.head(80).to_dict("records"),
        "reference": REFERENCE, "sources": SOURCES,
        "ai_comment": None,
    }
    return report


def ai_comment(r: dict) -> str | None:
    try:
        import asyncio
        import managers as M
        if M.check_setup():
            return None
        brief = {
            "检讨": r["review"], "规则": r["mode"], "门槛市值": f"RM {r['cutoff_mcap'] / 1e9:.1f}B",
            "最有机会的新成分股": [
                {"公司": c["name"], "非成分股排名": c["cand_rank"], "入选几率%": c["prob"], "距门槛%": c["gap_pct"]}
                for c in r["top_candidates"][:25]],
        }
        system = ("你是马来西亚股市分析师。根据数据，用简体中文写 150 字以内的点评："
                  "离数据截止还有多久、哪些公司几乎确定入选、哪些在边缘要看最后几天股价、"
                  "以及指数纳入通常会带来的被动基金买盘（但提醒消息可能已反映在股价里）。"
                  "不要用 Markdown，不要编造数据里没有的事。")
        return asyncio.run(M.chat(system, json.dumps(brief, ensure_ascii=False, default=str), 500))
    except Exception as e:
        print("KLCI AI 点评失败：", e)
        return None


def save(r: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{r['date']}.json"
    path.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    import scanner
    scanner.update_index()  # 更新报告目录（手机 app 用）
    return path


def latest() -> dict | None:
    files = sorted(REPORT_DIR.glob("*.json")) if REPORT_DIR.exists() else []
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def to_telegram_html(r: dict) -> str:
    import html
    rv = r["review"] or {}
    lines = [f"<b>🏆 KLCI 50 观察｜{r['date']}</b>"]
    if rv:
        lines.append(f"{rv['review']}：数据截止 {rv['cutoff']}（还有 {rv['days_to_cutoff']} 天），"
                     f"{rv['announce']} 公布")
    lines += [html.escape(r["mode"]), f"门槛市值：RM {r['cutoff_mcap'] / 1e9:.1f}B",
              "", f"<b>最有机会入选（{r['slots']} 个名额）</b>"]
    for c in r["top_candidates"][:15]:
        lines.append(f"{c['prob']:>2}%  <b>{html.escape(c['name'])}</b> {c['ticker']}"
                     f"（候选第 {c['cand_rank'] or '—'} 名）")
    if r["at_risk"]:
        lines += ["", "<b>⚠️ 现有成分股有风险</b>"] + [f"{c['name']}（{c['prob']}%）" for c in r["at_risk"]]
    if r.get("ai_comment"):
        lines += ["", "<b>🧠 AI 点评</b>", html.escape(r["ai_comment"])]
    lines += ["", "<i>按公开规则模拟估算，非官方结果。</i>"]
    return "\n".join(lines)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    r = track()
    r["ai_comment"] = ai_comment(r)
    print("已保存：", save(r))
    import scanner
    scanner.push_text(to_telegram_html(r))
