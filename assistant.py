"""网站里的 AI 助手：问什么都可以（用系统里的真实资料回答），也可以帮你改设定。

做法（免费模型也做得到）：AI 每一步回传一个 JSON：
  要查资料 → {"tool": "工具名", "args": {...}}        程序执行工具，把结果给 AI 再想一次（最多 4 次）
  回答     → {"answer": "...", "chart": {...}, "actions": [...]}
chart = 一张图表规格（同「我的仪表板」），网站会画出来，可以一键加进仪表板。
actions = 想改的设定（自选股、提醒、新闻追踪、仪表板、外观），网站会先问你「确认」才真的改。
不会改程序。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import dataset as D

ROOT = Path(__file__).parent
MAX_STEPS = 4

TOOLS_DOC = """工具（args 用 JSON）：
1. screen {"rules":[{"栏位":"股息率%","条件":">=","数值":5}], "markets":["马股"], "sort":"ROE%", "desc":true, "limit":15, "cols":[...]}
   → 从约 500 只股票（马股 / 美股 / 印尼股）按规则筛选、排序。栏位：代码、名称、市场、板块、行业、主题、自选股、股价、
     市值(亿令吉)、本益比、股价净值比、股息率%、ROE%、净利率%、营收增长%、盈利增长%、负债权益比、RSI、
     1日涨跌%、1周涨跌%、1个月涨跌%、3个月涨跌%、1年涨跌%。条件：> >= < <= = != 包含 不包含 介于（"0,40"）
2. stock {"ticker":"MAYBANK"} → 一只股票的现价、涨跌、技术面、估值、最近新闻（附日期）、最新季报、公告日历
3. market {"market":"bursa|idx|us"} → 今天的每日焦点报告：涨跌家数、最值得关注的股票和理由、AI 市场点评
4. sectors {"market":"bursa|idx|us"} → 各板块 / 主题的 1 日、1 个月涨跌
5. news {"ticker":"GAMUDA"}（不写 ticker = 最近最重要的）→ 新闻追踪的事件和 AI 判断的短期 / 长期影响
6. calendar {"ticker":"MAYBANK"} 或 {"days":14} → 业绩公布日、除权日
7. ipo {} → 马股 IPO：阶段、日期、价格、超额认购、上市表现
8. compare {"tickers":["TENAGA","YTLPOWR"]} → 2–3 只股票的估值、获利、成长、股息对比
9. portfolio {} → 用户投资组合的体检数字（比重、板块分布、股息率、波动、回撤；没有持股就会说没有）
10. settings {} → 现在的自选股、提醒、新闻追踪名单、仪表板图表名称、外观主题"""

ACTIONS_DOC = """可以帮用户改的设定（放在 actions，网站会先请用户确认）：
- {"type":"watch_add","ticker":"GAMUDA","note":"可不写","alerts":{"below":4.2}}　加进自选股（可同时设提醒）
- {"type":"watch_remove","ticker":"PPB"}
- {"type":"watch_alert","ticker":"MAYBANK","alerts":{"below":9.5,"above":11,"change_pct":4,"rsi_below":30,"rsi_above":70}}
- {"type":"watch_clear_alerts","ticker":"MAYBANK"}
- {"type":"follow","ticker":"PPB"} / {"type":"unfollow","ticker":"PPB"}　新闻追踪名单
- {"type":"dashboard_add","chart":{图表规格}} / {"type":"dashboard_remove","title":"图表标题"}
- {"type":"theme","th":"vice|navy|midnight|emerald|graphite|ocean|sakura","fs":"小|标准|大|特大","dn":"舒适|紧凑","rd":"圆润|方正","bd":"光晕|纯色|渐层","ac":"#FF4FA0"}
不能改程序或网站功能：用户要求新功能时，诚实说这里只能改设定，新功能要请开发者（Claude）帮忙。"""

CHART_DOC = """图表（放在 chart，用户问「画 / 看分布 / 比较一堆股票」时用）：
{"title":"…","type":"scatter|rank|group|hist|box|treemap|heat|table","markets":[],"rules":[],"x":"","y":"","color":"",
 "size":"","group":"","agg":"mean","sort":"","desc":true,"limit":20,"cols":[],"note":"怎么看这张图"}
scatter：x、y 数字；rank：y 数字 + limit；group：group 分类 + y 数字 + agg；hist：x；box：group + y；
treemap：group + size + color；heat：cols（几个涨跌栏位）+ sort + limit；table：cols + sort + limit。栏位名称同 screen。"""


def system_prompt() -> str:
    return f"""你是「AI 股票分析室」网站里的助手，帮一位投资新手。今天是 {date.today():%Y年%m月%d日}。
你可以用工具查系统里的真实资料（马股、美股、印尼股约 500 只），再用简体中文回答。

{TOOLS_DOC}

{CHART_DOC}

{ACTIONS_DOC}

规则：
- 每次只回传「一个」JSON，不要别的文字：要查资料就 {{"tool":"…","args":{{…}}}}；可以回答了就
  {{"answer":"…","chart":{{…}}或null,"actions":[…]或[]}}
- 跟股票、市场、新闻、设定有关的问题，一定先用工具查，不要凭记忆（你的知识可能过时）；最多查 {MAX_STEPS} 次
- 数字只能用工具给的；工具没有的资料就说没有，不要编造
- answer 要具体、口语化，重点数字写出来；可以用「1. 2. 3.」列点；不要用 Markdown 的 ** 或 #
- 不给「马上买 / 卖」的指令，只说可以考虑的方向和理由；最后不用每次都写免责声明
- 用户要改设定：在 actions 放要改的东西，answer 里说清楚会改什么（网站会请用户确认）"""


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _short(x, n=2600) -> str:
    s = json.dumps(x, ensure_ascii=False, default=str, separators=(",", ":"))
    return s if len(s) <= n else s[:n] + "…（太长，已截断）"


class Agent:
    def __init__(self, df, get_raw, holdings=None, prefs=None):
        self.df, self.get_raw, self.holdings, self.prefs = df, get_raw, holdings or [], prefs or {}
        self.steps: list[str] = []

    # ---- 每个工具 ----
    def t_screen(self, a):
        df = self.df
        if a.get("markets"):
            df = df[df["市场"].isin(a["markets"])]
        out = D.screen(df, a.get("rules"), a.get("sort"), a.get("desc", True), int(a.get("limit") or 15), a.get("cols"))
        return {"符合": len(D.apply_rules(df, a.get("rules"))), "结果": D.to_records(out, 25)}

    def t_stock(self, a):
        r = self.get_raw(str(a.get("ticker", "")))
        t, f = r["tech"], r["fund"]
        snap = r["snapshot"]
        return {"代码": r["ticker"], "名称": f["name"], "货币": f["currency"], "现价": t["price"],
                "今日%": t["change_1d"], "1个月%": t["change_1m"], "1年%": t["change_1y"], "技术面": t["verdict"],
                "技术信号": t["signals"][:5], "52周": [t["low_52w"], t["high_52w"]], "本益比": f["pe"],
                "预期本益比": f["forward_pe"], "股价净值比": f["pb"], "股息率%": f["dividend_yield"],
                "市值": f["market_cap"], "行业": f"{f['sector']} / {f['industry']}", "分析师目标价": f["target_price"],
                "基本面提示": f["flags"][:4], "近期动态": snap.get("近期动态")}

    def t_market(self, a):
        import scanner as S
        import universe
        m = a.get("market") or "bursa"
        folder = S.REPORT_DIR / m
        files = sorted(folder.glob("*_*.json")) if folder.exists() else []
        if not files:
            return "还没有这个市场的报告"
        r = _load(files[-1]) or {}

        def rows(xs, n=6):
            out = []
            for x in (xs or [])[:n]:
                tags = [k for k in ("new_high", "new_low", "cross_up_50", "cross_dn_50") if x.get(k)]
                out.append({"名称": universe.name_of(x["ticker"]) or x["ticker"], "代码": x["ticker"], "价格": x.get("price"),
                            "涨跌%": x.get("change_pct"), "成交量倍数": x.get("vol_ratio"), "RSI": x.get("rsi"),
                            "信号": tags or None})
            return out
        return {"报告": f"{r.get('date')} {r.get('session_name')}", "AI 点评": r.get("ai_comment"),
                "涨跌家数": r.get("breadth"), "自选股": rows(r.get("watchlist"), 10), "涨幅最大": rows(r.get("gainers")),
                "跌幅最大": rows(r.get("losers")), "成交量异常": rows(r.get("volume_surge")),
                "成交额最高": rows(r.get("turnover_top"), 5)}

    def t_sectors(self, a):
        import sectors as SE
        r = SE.latest(a.get("market") or "bursa")
        if not r:
            return "还没有板块报告"
        row = lambda s: {"名称": s["name"], "1日%": s["returns"].get("1d"), "1个月%": s["returns"].get("1m"), "只数": s["count"]}
        return {"日期": r["date"], "板块": [row(s) for s in r["sectors"]], "主题": [row(s) for s in r.get("themes", [])]}

    def t_news(self, a):
        import analysis as A
        feed = _load(ROOT / "reports" / "news" / "feed.json") or {}
        evs = feed.get("events", [])
        if a.get("ticker"):
            t = A.normalize_ticker(a["ticker"])
            evs = [e for e in evs if e.get("ticker") == t or t in (e.get("tickers") or [])]
            if not evs:
                try:
                    import recent
                    return {"说明": "新闻追踪没有这家公司的事件，以下是最近 14 天的新闻标题",
                            "新闻": recent.context(t).get("最近新闻")}
                except Exception:
                    return "没有找到这家公司的新闻"
        else:
            evs = sorted(evs, key=lambda e: (e.get("importance", 0), e.get("published", "")), reverse=True)
        return [{"日期": e.get("published", "")[:10], "公司": e.get("name"), "标题": e.get("headline_zh"),
                 "重要性": e.get("importance"), "分析": e.get("analysis"),
                 "短期": (e.get("short_term") or {}).get("view"), "长期": (e.get("long_term") or {}).get("view")}
                for e in evs[:8]] or "最近没有新闻事件"

    def t_calendar(self, a):
        import analysis as A
        data = _load(ROOT / "reports" / "calendar" / "events.json") or {}
        evs = data.get("events", [])
        today = datetime.now(timezone(timedelta(hours=8))).date()
        if a.get("ticker"):
            t = A.normalize_ticker(a["ticker"])
            evs = [e for e in evs if e["ticker"] == t]
        else:
            hi = str(today + timedelta(days=int(a.get("days") or 14)))
            evs = [e for e in evs if str(today) <= e["date"] <= hi]
            evs.sort(key=lambda e: (not e.get("mine"), e["date"]))
        return [{"日期": e["date"], "公司": e["name"], "代码": e["ticker"], "事件": e["title"], "状态": e["status"],
                 "自选": e.get("mine")} for e in evs[:20]] or "没有找到日期"

    def t_ipo(self, a):
        d = _load(ROOT / "reports" / "ipo" / "ipos.json") or {}
        out = []
        for r in list(d.get("ipos", {}).values())[:15]:
            out.append({k: r.get(k) for k in ("name", "stage", "market", "ipo_price", "listing_date", "close_date",
                                              "oversub_times", "business", "sector") if r.get(k) is not None}
                       | ({"分析": (r.get("analysis") or {}).get("level")} if r.get("analysis") else {}))
        return out or "没有 IPO 资料"

    def t_compare(self, a):
        import compare as CP
        d = CP.build([str(x) for x in (a.get("tickers") or [])][:3])
        flat = lambda s: {k: v for k, v in s.items() if not isinstance(v, (dict, list)) and v is not None}
        return {"股票": [flat(s) for s in d.get("stocks", [])], "胜出项目数": d.get("wins")}

    def t_portfolio(self, a):
        if not self.holdings:
            return "用户还没有输入投资组合（可以到「💼 投资组合」页面输入，或从手机 App 带过来）"
        import pfcheck as PC
        p = PC.build(self.holdings, self.get_raw)
        return json.loads(PC.brief(p, "（未指定）", "（未指定）", "（未指定）"))

    def t_settings(self, a):
        import yaml
        import dashboard as B
        import news as N
        try:
            wl = yaml.safe_load((ROOT / "watchlist.yml").read_text(encoding="utf-8")) or {}
        except Exception:
            wl = {}
        return {"自选股": wl.get("stocks"), "新闻追踪（/follow）": N.load_follow(),
                "仪表板图表": [c.get("title") for c in B.load_specs()], "外观": self.prefs}

    def run_tool(self, name: str, args: dict):
        fn = getattr(self, f"t_{name}", None)
        if not fn:
            return f"没有这个工具：{name}"
        try:
            return fn(args or {})
        except Exception as e:
            return f"工具出错：{e}"

    # ---- 主循环 ----
    async def ask(self, question: str, history: list[dict]) -> dict:
        import managers as M
        from news import _json_from
        convo = "\n".join(f"{'用户' if h['role'] == 'user' else '助手'}：{str(h.get('content', ''))[:600]}"
                          for h in history[-6:])
        log = []
        for step in range(MAX_STEPS + 1):
            prompt = (f"之前的对话：\n{convo or '（没有）'}\n\n用户现在问：{question}\n\n"
                      + ("已经查到的资料：\n" + "\n".join(log) + "\n\n" if log else "")
                      + ("（已经查了很多次，现在一定要用 answer 回答）" if step >= MAX_STEPS else "")
                      + "请回传一个 JSON。")
            raw = await M.chat(system_prompt(), prompt, max_tokens=1800)
            data = _json_from(raw)
            if not data:
                return {"answer": raw.strip() or "抱歉，我这次没有想好，请换个说法再问一次。", "steps": self.steps}
            if data.get("tool") and step < MAX_STEPS:
                name, args = str(data["tool"]), data.get("args") or {}
                self.steps.append(f"{name} {json.dumps(args, ensure_ascii=False)[:120]}")
                res = self.run_tool(name, args)
                log.append(f"[{name} {json.dumps(args, ensure_ascii=False)[:200]}] → {_short(res)}")
                continue
            ans = {"answer": str(data.get("answer") or "").strip(), "steps": self.steps}
            if isinstance(data.get("chart"), dict):
                import dashboard as B
                ans["chart"] = B.clean(data["chart"])
            acts = data.get("actions") or []
            ans["actions"] = [x for x in acts if isinstance(x, dict) and x.get("type")][:5]
            if not ans["answer"]:
                ans["answer"] = "（已经准备好，请看下面）" if ans.get("chart") or ans["actions"] else "抱歉，我没有找到答案。"
            return ans
        return {"answer": "查了太多次还没有结论，请把问题问得更具体一点。", "steps": self.steps}


# ---------------------------------------------------------------------------
# 设定动作：说明 + 执行
# ---------------------------------------------------------------------------

def describe(act: dict) -> str:
    t = act.get("type")
    tk = act.get("ticker", "")
    import github_store as G
    if t == "watch_add":
        al = act.get("alerts") or {}
        return f"⭐ 把 {tk} 加进自选股" + (f"（提醒：{'、'.join(f'{G.ALERT_ZH.get(k, k)} {v}' for k, v in al.items())}）" if al else "")
    if t == "watch_remove":
        return f"🗑️ 从自选股拿掉 {tk}"
    if t == "watch_alert":
        return f"🔔 {tk} 提醒：" + "、".join(f"{G.ALERT_ZH.get(k, k)} {v}" for k, v in (act.get("alerts") or {}).items())
    if t == "watch_clear_alerts":
        return f"🔕 取消 {tk} 的全部提醒"
    if t == "follow":
        return f"🗞️ 新闻追踪加入 {tk}"
    if t == "unfollow":
        return f"🗞️ 新闻追踪拿掉 {tk}"
    if t == "dashboard_add":
        return f"📐 仪表板加入图表「{(act.get('chart') or {}).get('title', '')}」"
    if t == "dashboard_remove":
        return f"📐 仪表板拿掉图表「{act.get('title', '')}」"
    if t == "theme":
        return "🎨 外观改成：" + "、".join(f"{k}={v}" for k, v in act.items() if k != "type")
    return f"（不认识的设定：{t}）"


def execute(act: dict) -> str:
    """真的去改（用户按了确认）。回传结果说明。外观在网站那边处理。"""
    import github_store as G
    t = act.get("type")
    if t in ("watch_add", "watch_remove", "watch_alert", "watch_clear_alerts"):
        kind = {"watch_add": "add", "watch_remove": "remove", "watch_alert": "alert", "watch_clear_alerts": "clear_alerts"}[t]
        holder = {}

        def fn(old):
            new, msg = G.edit_watchlist(old or "stocks: []\n", kind, act.get("ticker", ""), act.get("note"), act.get("alerts"))
            holder["msg"] = msg
            return new
        _, url = G.update("watchlist.yml", fn, f"AI 助手：{describe(act)}", local=str(ROOT / "watchlist.yml"))
        return f"✅ {holder.get('msg')}（约 15 分钟内提醒生效）"
    if t in ("follow", "unfollow"):
        import analysis as A
        tk = A.normalize_ticker(act.get("ticker", ""))

        def fn(old):
            cur = json.loads(old) if old else []
            if t == "follow" and tk not in cur:
                cur.append(tk)
            if t == "unfollow" and tk in cur:
                cur.remove(tk)
            return json.dumps(cur, ensure_ascii=False)
        G.update("reports/news/follow.json", fn, f"AI 助手：{describe(act)}", local=str(ROOT / "reports" / "news" / "follow.json"))
        return f"✅ 新闻追踪已{'加入' if t == 'follow' else '拿掉'} {tk}（下一次新闻追踪开始生效）"
    if t in ("dashboard_add", "dashboard_remove"):
        import dashboard as B

        def fn(old):
            try:
                specs = json.loads(old).get("charts", []) if old else B.load_specs()
            except Exception:
                specs = B.load_specs()
            if t == "dashboard_add":
                specs.append(B.clean(act.get("chart") or {}))
            else:
                specs = [c for c in specs if c.get("title") != act.get("title")]
            return B.dump_specs(specs)
        G.update("my_dashboard.json", fn, f"AI 助手：{describe(act)}", local=str(B.FILE))
        return "✅ 仪表板已更新"
    return "（这个设定由网站直接处理）"
