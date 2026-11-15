"""
ipo.py - 马股 IPO 追踪：有什么新股、招股资料、认购情况、招股书分析、上市后表现

运作方式（GitHub Actions「新闻追踪」里，每 3 小时一次）：
  1. 从 Google 新闻找马股 IPO 的消息（草拟招股书、推出招股书、超额认购、上市）
  2. AI 把新闻整理成每家公司一张资料卡：市场、IPO 价、发售股数、集资额、市值、本益比、
     申请日期、上市日期、超额认购倍数、申请人数……（只用新闻里出现的数字）
  3. 已上市的：用 Yahoo 抓股价，算「首日表现」和「到现在的表现」
  4. 重要变化推送 Telegram：新 IPO 开放申请、申请快截止、认购结果、上市首日表现
  5. 存进 reports/ipo/ipos.json（网站和手机 app 的「IPO 追踪」页面用）

招股书分析：
  招股书 PDF 有几百页，网站上没有固定格式可以自动下载，所以要你给：
    · Telegram 把招股书 PDF 直接传给机器人（20MB 以内），或发 /ipopdf 链接
    · 网站「IPO 追踪」页面上传 PDF 或贴链接
  系统读前面的「招股书摘要」和重点段落 → AI 抽出财务数字和重点 → 规则打分（弱到强）。

资料来源都是公开新闻和招股书；AI 只整理，不保证完整，申购前请看招股书原文。
"""

from __future__ import annotations

import html
import io
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DIR = ROOT / "reports" / "ipo"
STORE = DIR / "ipos.json"
STATE = DIR / "state.json"
ANALYSIS_DIR = DIR / "analysis"
MYT = timezone(timedelta(hours=8))

QUERIES = [  # (查询, 语言地区)
    ('"ACE Market" IPO', ("en-MY", "MY", "MY:en")),
    ('"Main Market" IPO Bursa', ("en-MY", "MY", "MY:en")),
    ('IPO oversubscribed Bursa', ("en-MY", "MY", "MY:en")),
    ('IPO prospectus launch Bursa', ("en-MY", "MY", "MY:en")),
    ('IPO debut Bursa', ("en-MY", "MY", "MY:en")),
    ('"prospectus exposure" OR "draft prospectus" IPO Malaysia', ("en-MY", "MY", "MY:en")),
    ('"LEAP Market" IPO', ("en-MY", "MY", "MY:en")),
    ('IPO 超额认购 创业板 OR 主板', ("zh-CN", "MY", "MY:zh-Hans")),
]

STAGES = ["计划中", "草拟招股书", "招股中", "认购结果", "已上市", "已撤回"]
STAGE_ICON = {"计划中": "🗂", "草拟招股书": "📄", "招股中": "📝", "认购结果": "🎯", "已上市": "🔔", "已撤回": "⛔"}
FIELDS = ["market", "ipo_price", "shares_offered_m", "public_portion_m", "proceeds_rm_m", "market_cap_rm_m", "pe",
          "application_open", "application_close", "balloting_date", "listing_date", "oversub_times",
          "applications", "applied_shares_m", "bumi_oversub_times", "business", "sector", "principal_adviser",
          "issuing_house"]


def _load(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


def slug(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\b(berhad|bhd|holdings?|group|capital|corporation|corp|international|ltd)\b\.?", " ", n)
    return re.sub(r"[^a-z0-9]+", "-", n).strip("-") or re.sub(r"\s+", "-", name.strip().lower())


def today_myt() -> date:
    return datetime.now(MYT).date()


# ---------------------------------------------------------------------------
# 1. 从新闻整理 IPO 资料
# ---------------------------------------------------------------------------

EXTRACT_SYSTEM = """你是马来西亚股市的 IPO 资料整理员。下面是最近的新闻标题和摘要，以及系统已经知道的 IPO 名单。
把新闻里提到的「马来西亚 Bursa（Main / ACE / LEAP）IPO」整理成资料卡，只回传 JSON：
{"ipos":[{"ids":["新闻id",...],"name":"公司英文全名（例如 Big Caring Group Bhd）","stage":"计划中|草拟招股书|招股中|认购结果|已上市|已撤回",
"market":"Main|ACE|LEAP","ipo_price":RM数字,"shares_offered_m":发售股数(百万),"public_portion_m":马来西亚公众部分(百万股),
"proceeds_rm_m":集资额(RM百万),"market_cap_rm_m":上市市值(RM百万),"pe":本益比,
"application_open":"YYYY-MM-DD","application_close":"YYYY-MM-DD","balloting_date":"YYYY-MM-DD","listing_date":"YYYY-MM-DD",
"oversub_times":公众部分超额认购倍数,"applications":申请份数,"applied_shares_m":申请股数(百万),"bumi_oversub_times":土著部分倍数,
"business":"一句中文：做什么生意","sector":"中文行业","principal_adviser":"","issuing_house":""}]}
规则：
- 只放新闻里明确出现的数字和日期；没有提到就写 null，绝对不要猜。
- 「仙」要换成 RM（例如 25 sen = 0.25）。billion 要换成百万（1.2 billion = 1200）。
- 同一家公司的几条新闻合并成一张卡；名字跟已知名单是同一家时，用已知名单的名字。
- 不是马来西亚 Bursa 的 IPO（例如香港、新加坡、美国）不要放。
- stage：只是获批 / 委任顾问 = 计划中；证监会草拟招股书曝光 = 草拟招股书；推出招股书、开放申请 = 招股中；
  公布超额认购 = 认购结果；已经挂牌交易 = 已上市。"""


def gather_news(seen: dict, first: bool) -> list[dict]:
    import news as N
    items, here = [], set()
    for q, (hl, gl, ceid) in QUERIES:
        items += N.google_news(q, hl, gl, ceid, when="21d" if first else "3d")
    out = []
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        h = N._hash(it["title"])
        if h in here or h in seen:
            continue
        here.add(h)
        it["id"] = h
        out.append(it)
    return out


def extract(items: list[dict], known: list[str]) -> list[dict]:
    import asyncio
    import managers as M
    import news as N
    if M.check_setup() or not items:
        return []
    brief = {"已知 IPO": known[:80],
             "新闻": [{"id": it["id"], "标题": it["title"], "摘要": it.get("summary", "")[:240],
                     "来源": it["source"], "时间": it["published"][:10]} for it in items]}
    text = asyncio.run(M.chat(EXTRACT_SYSTEM, json.dumps(brief, ensure_ascii=False), 2500))
    data = N._json_from(text)
    if not data or "ipos" not in data:
        raise ValueError("AI 回传的格式不对")
    by_id = {it["id"]: it for it in items}
    out = []
    for x in data["ipos"]:
        if not x.get("name"):
            continue
        x["articles"] = [{k: by_id[i].get(k) for k in ("title", "source", "link", "published")}
                         for i in x.get("ids") or [] if i in by_id]
        out.append(x)
    return out


def _num(v):
    try:
        if v in (None, "", "null"):
            return None
        t = str(v).replace(",", "").replace("RM", "").strip().lower()
        if t.endswith("sen"):                       # 30 sen = RM0.30
            return float(t[:-3].strip()) / 100
        return float(t.rstrip("x倍 "))
    except (TypeError, ValueError):
        return None


def _date(v):
    try:
        return str(date.fromisoformat(str(v)[:10])) if v else None
    except ValueError:
        return None


def merge(store: dict, x: dict) -> tuple[dict, list[str]]:
    """把一张新资料卡并进数据库，回传 (记录, 变化了什么)。"""
    ipos = store.setdefault("ipos", {})
    key = slug(x["name"])
    rec = ipos.get(key) or {"name": x["name"], "slug": key, "first_seen": str(today_myt()),
                            "stage": "计划中", "articles": [], "history": []}
    changes = []
    for f in FIELDS:
        v = x.get(f)
        if f in ("application_open", "application_close", "balloting_date", "listing_date"):
            v = _date(v)
        elif f in ("ipo_price", "shares_offered_m", "public_portion_m", "proceeds_rm_m", "market_cap_rm_m", "pe",
                   "oversub_times", "applications", "applied_shares_m", "bumi_oversub_times"):
            v = _num(v)
        if v in (None, ""):
            continue
        if rec.get(f) != v:
            if f == "oversub_times" and rec.get(f) is None:
                changes.append("subscription")
            rec[f] = v
    st_new = x.get("stage") if x.get("stage") in STAGES else None
    if st_new and (STAGES.index(st_new) > STAGES.index(rec.get("stage", "计划中")) or st_new == "已撤回"):
        changes.append(f"stage:{st_new}")
        rec["stage"] = st_new
        rec["history"].append({"date": str(today_myt()), "stage": st_new})
    links = {a.get("link") for a in rec["articles"]}
    rec["articles"] = ([a for a in x.get("articles", []) if a.get("link") not in links] + rec["articles"])[:12]
    rec["updated"] = str(today_myt())
    ipos[key] = rec
    return rec, changes


def fix_stage(rec: dict, today: date) -> list[str]:
    """用日期推算阶段（新闻没说的时候）。"""
    ch = []
    lst, op, cl = rec.get("listing_date"), rec.get("application_open"), rec.get("application_close")
    if rec.get("stage") == "已撤回":
        return ch
    if lst and lst <= str(today) and rec["stage"] != "已上市":
        rec["stage"] = "已上市"
        ch.append("stage:已上市")
    elif op and cl and op <= str(today) <= cl and STAGES.index(rec["stage"]) < STAGES.index("招股中"):
        rec["stage"] = "招股中"
        ch.append("stage:招股中")
    if rec.get("oversub_times") and STAGES.index(rec["stage"]) < STAGES.index("认购结果"):
        rec["stage"] = "认购结果"
    return ch


# ---------------------------------------------------------------------------
# 2. 上市后表现（Yahoo）
# ---------------------------------------------------------------------------

MIH_CURRENT = "https://mih.com.my/ipo/current-ipo"


def mih_current() -> list[dict]:
    """Malaysian Issuing House「Current IPO」：正在招股 / 等上市的 IPO（有准确的日期和价格）。"""
    import pandas as pd
    try:
        tables = pd.read_html(io.StringIO(_get(MIH_CURRENT).text))
    except Exception as e:
        print(f"  MIH 读取失败：{e}")
        return []
    out = []
    for t in tables:
        cols = {str(c).strip().lower(): c for c in t.columns}
        name_c = next((cols[c] for c in cols if "company" in c), None)
        if name_c is None:
            continue
        pick = lambda key: next((cols[c] for c in cols if key in c), None)
        def d(v):
            try:
                return str(datetime.strptime(str(v).strip(), "%d-%b-%Y").date())
            except Exception:
                return None
        for _, row in t.iterrows():
            name = str(row[name_c]).strip()
            if not name or name.lower() == "nan":
                continue
            mk = str(row[pick("market")]) if pick("market") is not None else ""
            out.append({"name": name.title().replace("Bhd", "Bhd").replace("Berhad", "Berhad"),
                        "market": "ACE" if "ace" in mk.lower() else "Main" if "main" in mk.lower() else None,
                        "application_open": d(row[pick("open")]) if pick("open") is not None else None,
                        "application_close": d(row[pick("clos")]) if pick("clos") is not None else None,
                        "balloting_date": d(row[pick("ballot")]) if pick("ballot") is not None else None,
                        "listing_date": d(row[pick("listing")]) if pick("listing") is not None else None,
                        "ipo_price": _num(row[pick("price")]) if pick("price") is not None else None,
                        "issuing_house": "Malaysian Issuing House", "stage": "招股中", "articles": []})
    return out


def find_ticker(name: str) -> str | None:
    try:
        import yfinance as yf
        base = re.sub(r"\b(Bhd|Berhad)\b\.?", "", name).strip()
        for q in (f"{base} Berhad", base):
            for r in (yf.Search(q, max_results=8).quotes or []):
                sym = r.get("symbol", "")
                if sym.endswith(".KL"):
                    return sym
    except Exception:
        pass
    return None


def performance(rec: dict) -> dict | None:
    if not rec.get("ticker") or not rec.get("ipo_price") or not rec.get("listing_date"):
        return None
    try:
        import yfinance as yf
        df = yf.download(rec["ticker"], start=rec["listing_date"], progress=False, auto_adjust=False)
        if df is None or df.empty:
            return None
        if hasattr(df.columns, "levels"):          # 多层栏位：找出有 Close 的那一层
            for lv in range(df.columns.nlevels):
                if "Close" in set(df.columns.get_level_values(lv)):
                    df.columns = df.columns.get_level_values(lv)
                    break
        p0 = rec["ipo_price"]
        first = df.iloc[0]
        last = float(df["Close"].iloc[-1])
        return {"first_open": round(float(first["Open"]), 3), "first_close": round(float(first["Close"]), 3),
                "first_day_pct": round((float(first["Close"]) / p0 - 1) * 100, 1),
                "first_open_pct": round((float(first["Open"]) / p0 - 1) * 100, 1),
                "last": round(last, 3), "since_ipo_pct": round((last / p0 - 1) * 100, 1),
                "high": round(float(df["High"].max()), 3), "days": len(df), "as_of": str(df.index[-1].date())}
    except Exception as e:
        print(f"  {rec['name']} 股价失败：{e}")
        return None


# ---------------------------------------------------------------------------
# 3. 招股书分析
# ---------------------------------------------------------------------------

PDF_SYSTEM = """你是资深 IPO 分析师。下面是一份马来西亚 IPO 招股书的重点段落（摘要、IPO 详情、财务、募资用途、股息政策、风险）。
用简体中文分析，只回传 JSON：
{"name":"公司英文名","market":"Main|ACE|LEAP","ipo_price":RM,"enlarged_shares_m":上市后总股数(百万),"market_cap_rm_m":RM百万,
"public_issue_m":新股(百万股),"offer_for_sale_m":旧股出售(百万股),"proceeds_rm_m":公司拿到的集资额(RM百万),"pe":本益比,"pe_basis":"根据哪一年",
"fy":[{"year":"FYE2025","revenue_rm_m":数字,"pat_rm_m":数字,"gp_margin_pct":数字}],
"proceeds":[{"use":"中文用途","rm_m":数字,"pct":数字,"growth":true/false}],
"dividend_policy":"中文一句","major_shareholders":"中文一句（谁持有多少 %）","moratorium":"中文一句（禁售期）",
"application_open":"YYYY-MM-DD","application_close":"YYYY-MM-DD","listing_date":"YYYY-MM-DD",
"business_zh":"2-3 句：做什么生意、客户是谁、怎么赚钱","model_zh":"1-2 句营业模式",
"strengths_zh":["3-4 个优势"],"risks_zh":["3-5 个主要风险"],"red_flags_zh":["值得警惕的地方，没有就空列表"],
"summary_zh":"3-4 句总结：这个 IPO 的卖点、估值是否合理、最大的疑问"}
规则：只用提供的内容，数字照抄（RM 百万）；找不到就 null；growth=true 代表用在扩张、资本开支、研发、新市场，
还债、上市费用、营运资金=false。不要给买卖建议。"""

KEYWORDS = ["prospectus summary", "details of our ipo", "utilisation of proceeds", "use of proceeds",
            "dividend policy", "price-to-earnings", "pe multiple", "market capitalisation",
            "financial highlights", "historical financial information", "revenue", "profit after tax",
            "risk factors", "moratorium", "promoters and substantial shareholders", "indicative timetable",
            "opening of the application", "listing on"]


def pdf_text(data: bytes, max_pages: int = 140) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = []
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return re.sub(r"[ \t]+", " ", "\n".join(parts))


def digest(text: str, limit: int = 18000) -> str:
    """几百页太长：只拿摘要 + 关键字附近的段落，大约 4–5 千 tokens。"""
    low = text.lower()
    chunks = []
    # 招股书摘要：跳过目录（第一次出现通常在目录），取第二次出现之后
    hits = [m.start() for m in re.finditer(r"prospectus summary", low)]
    start = hits[1] if len(hits) > 1 else (hits[0] if hits else 0)
    chunks.append(text[start:start + 9000])
    used = [(start, start + 9000)]
    for kw in KEYWORDS:
        for m in list(re.finditer(re.escape(kw), low))[1:3]:
            a, b = max(0, m.start() - 300), m.start() + 1500
            if any(a < u2 and b > u1 for u1, u2 in used):
                continue
            used.append((a, b))
            chunks.append(text[a:b])
            if sum(len(c) for c in chunks) > limit:
                break
        if sum(len(c) for c in chunks) > limit:
            break
    return "\n...\n".join(chunks)[:limit]


def fetch_pdf(url: str) -> bytes:
    import requests
    r = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0 (compatible; stock-bot/1.0)"})
    r.raise_for_status()
    if b"%PDF" not in r.content[:1024]:
        raise ValueError("这个链接不是 PDF 文件（可能要登录，或是网页不是文件本身）")
    return r.content


def band(v, cuts, higher_better=True):
    if v is None:
        return None
    for score, c in zip((5, 4, 3, 2), cuts):
        if (v >= c) if higher_better else (v <= c):
            return score
    return 1


def scorecard(a: dict) -> dict:
    """规则打分：估值、成长、获利、募资用途、旧股出售比例 → 弱 / 偏弱 / 中等 / 偏强 / 强。"""
    fy = [f for f in a.get("fy") or [] if _num(f.get("pat_rm_m")) is not None]
    items = []
    pe = _num(a.get("pe"))
    if pe is None and _num(a.get("market_cap_rm_m")) and fy and _num(fy[-1].get("pat_rm_m")):
        pat = _num(fy[-1]["pat_rm_m"])
        pe = round(_num(a["market_cap_rm_m"]) / pat, 1) if pat > 0 else None
    items.append(("估值（本益比）", band(pe, (12, 16, 20, 25), False), f"{pe:.1f} 倍" if pe else "—"))
    cagr = None
    if len(fy) >= 2:
        p0, p1 = _num(fy[0]["pat_rm_m"]), _num(fy[-1]["pat_rm_m"])
        n = len(fy) - 1
        if p0 and p0 > 0 and p1 and p1 > 0:
            cagr = round(((p1 / p0) ** (1 / n) - 1) * 100, 1)
    items.append(("盈利成长（年复合）", band(cagr, (20, 10, 5, 0)), f"{cagr:+.1f}%" if cagr is not None else "—"))
    margin = None
    if fy and _num(fy[-1].get("revenue_rm_m")):
        margin = round(_num(fy[-1]["pat_rm_m"]) / _num(fy[-1]["revenue_rm_m"]) * 100, 1)
    items.append(("净利率（最新一年）", band(margin, (15, 10, 6, 3)), f"{margin:.1f}%" if margin is not None else "—"))
    pr = [p for p in a.get("proceeds") or [] if _num(p.get("pct")) is not None]
    growth = round(sum(_num(p["pct"]) for p in pr if p.get("growth")), 1) if pr else None
    items.append(("募资用在扩张的比例", band(growth, (60, 45, 30, 15)), f"{growth:.0f}%" if growth is not None else "—"))
    pi, ofs = _num(a.get("public_issue_m")), _num(a.get("offer_for_sale_m"))
    ofs_pct = round(ofs / (pi + ofs) * 100, 1) if pi is not None and ofs is not None and pi + ofs > 0 else None
    items.append(("旧股东套现比例（越低越好）", band(ofs_pct, (0, 20, 35, 50), False), f"{ofs_pct:.0f}%" if ofs_pct is not None else "—"))
    scored = [s for _, s, _ in items if s]
    avg = sum(scored) / len(scored) if scored else None
    level = None if avg is None else ["弱", "偏弱", "中等", "偏强", "强"][max(0, min(4, round(avg) - 1))]
    return {"items": [{"name": n, "score": s, "value": v} for n, s, v in items], "avg": round(avg, 2) if avg else None,
            "level": level, "pe": pe, "pat_cagr": cagr, "margin": margin, "growth_pct": growth, "ofs_pct": ofs_pct}


def analyze_pdf(data: bytes, source: str = "", name_hint: str = "") -> dict:
    import asyncio
    import managers as M
    import news as N
    if M.check_setup():
        raise ValueError(M.check_setup())
    text = pdf_text(data)
    if len(text) < 2000:
        raise ValueError("这份 PDF 读不到文字（可能是扫描图片），没办法分析。")
    dg = digest(text)
    raw = asyncio.run(M.chat(PDF_SYSTEM, (f"公司：{name_hint}\n" if name_hint else "") + dg, 2500))
    a = N._json_from(raw)
    if not a:
        raise ValueError("AI 回传的格式不对，请再试一次。")
    a["score"] = scorecard(a)
    a["source"] = source
    a["analyzed"] = str(today_myt())
    return a


# ---------------------------------------------------------------------------
# 3b. 一键分析：自动找招股书；找不到就用新闻
# ---------------------------------------------------------------------------

SC_INDEX = "https://www.sc.com.my/resources/prospectus-exposure"
SC_SECTIONS = [("prospectus summary", 1), ("details of our ipo", 2), ("financial information", 3),
               ("risk factors", 4), ("business overview", 5)]          # 要下载的章节（数字 = 优先次序）
UA = {"User-Agent": "Mozilla/5.0 (compatible; stock-bot/1.0)"}

NEWS_SYSTEM = PDF_SYSTEM.replace("下面是一份马来西亚 IPO 招股书的重点段落（摘要、IPO 详情、财务、募资用途、股息政策、风险）。",
                                 "找不到这家公司的招股书，下面是关于它 IPO 的新闻标题和摘要，以及已知资料。") + \
    "\n额外规则：新闻没提到的一律 null，不要用常识补数字；summary_zh 开头要写「根据新闻（未读招股书）」。"


def _get(url: str, timeout: int = 40):
    import requests
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r


def _plain(htm: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", htm))).strip()


def sc_page(name: str) -> str | None:
    """证监会「招股书曝光」（主板 IPO 才有）：找这家公司的页面网址。"""
    want = slug(name)
    try:
        idx = _get(SC_INDEX).text
        for href, text in re.findall(r'href="([^"]*prospectus-exposure-[^"]+)"[^>]*>(.*?)</a>', idx, re.S | re.I):
            if slug(_plain(text)) == want or want in slug(href.rsplit("prospectus-exposure-", 1)[-1]):
                return href if href.startswith("http") else "https://www.sc.com.my" + href
    except Exception as e:
        print(f"  证监会名单读取失败：{e}")
    full = re.sub(r"\bbhd\b\.?", "berhad", name.lower())
    guess = SC_INDEX + "/prospectus-exposure-" + re.sub(r"[^a-z0-9]+", "-", full).strip("-")
    try:
        _get(guess)
        return guess
    except Exception:
        return None


def sc_sections(page_url: str) -> list[tuple[str, str]]:
    """页面里各章节的 PDF：[(章节名, 网址)]，按重要性排好。"""
    htm = _get(page_url).text
    out = []
    parts = re.split(r'(href="[^"]*download\.ashx\?id=[^"]+")', htm)
    for i in range(1, len(parts), 2):
        url = html.unescape(parts[i][6:-1])
        url = url if url.startswith("http") else "https://www.sc.com.my" + url
        label = _plain(parts[i - 1][-400:]).lower()
        for key, rank in SC_SECTIONS:
            if key in label[-120:]:
                out.append((rank, key, url))
                break
    seen, res = set(), []
    for rank, key, url in sorted(out):
        if key not in seen:
            seen.add(key)
            res.append((key, url))
    return res


def find_prospectus(rec: dict) -> dict | None:
    """自动找招股书。现在支持：证监会招股书曝光（主板）。找到就回传各章节文字。"""
    page = sc_page(rec["name"])
    if not page:
        return None
    secs = sc_sections(page)
    if not secs:
        return None
    texts = []
    for key, url in secs:
        try:
            data = _get(url, 90).content
            if b"%PDF" in data[:1024]:
                texts.append(f"===== {key.upper()} =====\n" + pdf_text(data, max_pages=60))
        except Exception as e:
            print(f"  下载 {key} 失败：{e}")
    if not texts:
        return None
    return {"text": "\n".join(texts), "source": page, "kind": "证监会招股书曝光（草拟版）"}


def _ai_json(system: str, user: str, tokens: int = 2500) -> dict:
    import asyncio
    import managers as M
    import news as N
    if M.check_setup():
        raise ValueError(M.check_setup())
    a = N._json_from(asyncio.run(M.chat(system, user, tokens)))
    if not a:
        raise ValueError("AI 回传的格式不对，请再试一次。")
    return a


def analyze_ipo(rec: dict) -> dict:
    """一键分析：先找招股书，找不到就用新闻。"""
    facts = {k: rec.get(k) for k in FIELDS if rec.get(k) is not None}
    pro = None
    try:
        pro = find_prospectus(rec)
    except Exception as e:
        print(f"  找招股书失败：{e}")
    if pro:
        dg = digest(pro["text"])
        a = _ai_json(PDF_SYSTEM, f"公司：{rec['name']}\n已知资料：{json.dumps(facts, ensure_ascii=False)}\n\n{dg}")
        a.update(basis="prospectus", basis_zh=pro["kind"], source=pro["source"])
    else:
        import news as N
        short = re.sub(r"(?i)\b(berhad|bhd)\b\.?", "", rec["name"]).strip()
        items = N.google_news(f'"{short}" IPO', "en-MY", "MY", "MY:en", when="120d")
        arts = [{"标题": it["title"], "摘要": it.get("summary", "")[:300], "来源": it["source"], "时间": it["published"][:10]}
                for it in items[:25]]
        arts += [{"标题": x.get("title"), "来源": x.get("source"), "时间": (x.get("published") or "")[:10]}
                 for x in rec.get("articles", [])[:10]]
        if not arts and not facts:
            raise ValueError("找不到招股书，也找不到相关新闻。可以上传招股书 PDF 来分析。")
        a = _ai_json(NEWS_SYSTEM, json.dumps({"公司": rec["name"], "已知资料": facts, "新闻": arts}, ensure_ascii=False))
        a.update(basis="news", basis_zh="新闻（没有找到招股书）", source="Google 新闻")
    a["name"] = a.get("name") or rec["name"]
    for k in ("ipo_price", "market_cap_rm_m", "pe", "market"):          # AI 没抓到的，用资料卡的数字
        if a.get(k) in (None, "") and rec.get(k) is not None:
            a[k] = rec[k]
    a["score"] = scorecard(a)
    a["analyzed"] = str(today_myt())
    return a


def save_analysis(a: dict, rec_slug: str | None = None) -> dict | None:
    """存起来，并挂到对应的 IPO 资料卡上（找不到就新建一张）。"""
    if not a.get("name"):
        return None
    store = _load(STORE, {"ipos": {}})
    x = {"name": a["name"], "market": a.get("market"), "ipo_price": a.get("ipo_price"),
         "market_cap_rm_m": a.get("market_cap_rm_m"), "proceeds_rm_m": a.get("proceeds_rm_m"),
         "pe": (a.get("score") or {}).get("pe") or a.get("pe"), "business": a.get("business_zh"),
         "application_open": a.get("application_open"), "application_close": a.get("application_close"),
         "listing_date": a.get("listing_date"), "stage": "招股中" if a.get("application_open") else None}
    # 名字可能跟新闻的写法不同：先找相近的
    key = rec_slug or slug(a["name"])
    for k in store.get("ipos", {}):
        if k == key or (len(key) > 4 and (k.startswith(key) or key.startswith(k))):
            x["name"] = store["ipos"][k]["name"]
            break
    rec, _ = merge(store, x)
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    (ANALYSIS_DIR / f"{rec['slug']}.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["analysis"] = {"level": a["score"]["level"], "avg": a["score"]["avg"], "summary": a.get("summary_zh"),
                       "date": a["analyzed"], "file": f"analysis/{rec['slug']}.json", "basis": a.get("basis", "prospectus")}
    _save(store)
    return rec


def save_analysis_into(store: dict, rec: dict, a: dict):
    """把分析存成文件，并挂在这张资料卡上（run() 里用，不重读数据库）。"""
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    (ANALYSIS_DIR / f"{rec['slug']}.json").write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["analysis"] = {"level": a["score"]["level"], "avg": a["score"]["avg"], "summary": a.get("summary_zh"),
                       "date": a["analyzed"], "file": f"analysis/{rec['slug']}.json", "basis": a.get("basis")}
    for k in ("market_cap_rm_m", "proceeds_rm_m", "pe"):
        if rec.get(k) is None and _num(a.get(k)) is not None:
            rec[k] = _num(a.get(k))
    if not rec.get("business") and a.get("business_zh"):
        rec["business"] = a["business_zh"][:80]


def attach_analyses(store: dict):
    """招股书分析存在独立文件里：每次都重新挂上去（避免两个自动任务同时改资料时弄丢）。"""
    if not ANALYSIS_DIR.exists():
        return
    for f in ANALYSIS_DIR.glob("*.json"):
        rec = store.get("ipos", {}).get(f.stem)
        a = _load(f, None)
        if rec is not None and a:
            rec["analysis"] = {"level": (a.get("score") or {}).get("level"), "avg": (a.get("score") or {}).get("avg"),
                               "summary": a.get("summary_zh"), "date": a.get("analyzed"), "file": f"analysis/{f.stem}.json",
                               "basis": a.get("basis", "prospectus")}


def _save(store: dict):
    store["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 4. 定时跑
# ---------------------------------------------------------------------------

def due(every_h: float) -> bool:
    last = _load(STATE, {}).get("last")
    if not last:
        return True
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() >= every_h * 3600 - 600
    except Exception:
        return True


def run(push: bool = True, force: bool = False) -> dict:
    import scanner as S
    every = float(os.getenv("IPO_EVERY") or 3)
    if every <= 0 or not (force or due(every)):
        return _load(STORE, {"ipos": {}})
    state = _load(STATE, {"seen": {}, "pushed": {}})
    seen, pushed = state.setdefault("seen", {}), state.setdefault("pushed", {})
    first = not STORE.exists()
    store = _load(STORE, {"ipos": {}})
    today = today_myt()
    msgs = []

    for x in mih_current():                          # 发行处网站：准确的日期和价格（不用 AI）
        rec, ch = merge(store, x)
        if not first:
            msgs += [(rec, c) for c in ch]

    items = gather_news(seen, first)
    print(f"IPO 追踪：{len(items)} 条新新闻" + ("（第一次：看最近 3 个星期）" if first else ""))
    for i in range(0, len(items), 25):                 # 一次最多 25 条给 AI
        part = items[i:i + 25]
        try:
            cards = extract(part, [r["name"] for r in store["ipos"].values()])
        except Exception as e:
            print(f"  AI 整理失败（下次再试）：{e}")
            continue
        for it in part:
            seen[it["id"]] = it["published"][:10]
        for x in cards:
            rec, ch = merge(store, x)
            if not first:
                msgs += [(rec, c) for c in ch]

    for rec in store["ipos"].values():
        for c in fix_stage(rec, today):
            if not first:
                msgs.append((rec, c))
        if rec["stage"] == "已上市" or (rec.get("listing_date") and rec["listing_date"] <= str(today + timedelta(days=3))):
            if not rec.get("ticker"):
                rec["ticker"] = find_ticker(rec["name"])
            if rec["stage"] == "已上市" and rec.get("ticker"):
                perf = performance(rec)
                if perf:
                    rec["perf"] = perf
                    if 1 <= perf["days"] <= 2 and f"{rec['slug']}:listed" not in pushed and not first \
                            and (perf["days"] == 2 or datetime.now(MYT).hour >= 17):   # 刚上市的才发
                        msgs.append((rec, "listed"))
        # 申请快截止提醒（截止前一天）
        cl = rec.get("application_close")
        if cl and rec["stage"] in ("招股中",) and str(today) <= cl <= str(today + timedelta(days=1)) and not first:
            msgs.append((rec, "closing"))

    attach_analyses(store)

    # 自动分析：招股中 / 等上市 / 草拟招股书的 IPO，还没分析过（或只用新闻分析过、超过 7 天）
    auto_max = int(os.getenv("IPO_AUTO_MAX") or 2)
    todo = [r for r in store["ipos"].values() if r["stage"] in ("草拟招股书", "招股中", "认购结果")
            and (not r.get("analysis") or (r["analysis"].get("basis") == "news"
                                            and r["analysis"].get("date", "") <= str(today - timedelta(days=7))))]
    todo.sort(key=lambda r: STAGES.index(r["stage"]), reverse=True)
    for r in todo[:auto_max]:
        try:
            a = analyze_ipo(r)
            save_analysis_into(store, r, a)
            print(f"  自动分析 {r['name']}：{a['score']['level']}（{a['basis_zh']}）")
            if r["stage"] == "招股中" and not first:
                msgs.append((r, "analysis"))
        except Exception as e:
            print(f"  自动分析 {r['name']} 失败：{e}")

    week = str(today - timedelta(days=30))
    state["seen"] = {k: v for k, v in seen.items() if v >= week}
    state["last"] = datetime.now(timezone.utc).isoformat()
    _save(store)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    sent = 0
    for rec, kind in msgs:
        key = f"{rec['slug']}:{kind}"
        if key in pushed:
            continue
        if kind == "analysis":
            pushed[key] = str(today)
            if push:
                a = _load(DIR / rec["analysis"]["file"], None)
                if a:
                    S.push_text(analysis_html(a))
                    sent += 1
            continue
        if kind.startswith("stage:") and kind[6:] not in ("招股中", "已撤回"):
            continue                                  # 「已上市」等首日表现才发；草拟阶段不打扰
        pushed[key] = str(today)
        if push:
            S.push_text(card_html(rec, kind))
            sent += 1
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"  追踪 {len(store['ipos'])} 个 IPO，推送 {sent} 条")
    return store


# ---------------------------------------------------------------------------
# 5. 显示
# ---------------------------------------------------------------------------

def f_rm(v, unit=""):
    if v is None:
        return "—"
    return f"RM{v:,.3f}".rstrip("0").rstrip(".") if unit == "price" else f"RM{v:,.1f} 百万" if v < 1000 else f"RM{v / 1000:,.2f} 十亿"


def card_html(rec: dict, kind: str = "") -> str:
    e = html.escape
    head = {"stage:招股中": "📝 新 IPO 开放申请", "subscription": "🎯 IPO 认购结果", "closing": "⏰ IPO 申请明天截止",
            "listed": "🔔 IPO 上市首日", "stage:已撤回": "⛔ IPO 撤回"}.get(kind, f"{STAGE_ICON.get(rec['stage'], '')} IPO")
    lines = [f"<b>{head}｜{e(rec['name'])}</b>"]
    if rec.get("business"):
        lines.append(e(rec["business"]))
    lines.append("")
    facts = [("市场", f"{rec['market']} Market" if rec.get("market") else None),
             ("IPO 价", f_rm(rec.get("ipo_price"), "price") if rec.get("ipo_price") else None),
             ("集资", f_rm(rec.get("proceeds_rm_m")) if rec.get("proceeds_rm_m") else None),
             ("上市市值", f_rm(rec.get("market_cap_rm_m")) if rec.get("market_cap_rm_m") else None),
             ("本益比", f"{rec['pe']:.1f} 倍" if rec.get("pe") else None),
             ("申请", f"{rec.get('application_open') or '?'} 到 {rec['application_close']}" if rec.get("application_close") else None),
             ("上市日", rec.get("listing_date")),
             ("公众部分超额认购", f"{rec['oversub_times']:.2f} 倍" if rec.get("oversub_times") else None),
             ("申请份数", f"{rec['applications']:,.0f}" if rec.get("applications") else None)]
    lines += [f"{k}：<b>{e(str(v))}</b>" for k, v in facts if v]
    p = rec.get("perf")
    if kind == "listed" and p:
        lines.append(f"\n首日：开 {p['first_open']}（{p['first_open_pct']:+.1f}%），收 {p['first_close']}（<b>{p['first_day_pct']:+.1f}%</b>）")
    a = rec.get("analysis")
    if a:
        lines.append(f"\n📑 招股书评分：<b>{a['level']}</b>　{e(a.get('summary') or '')}")
    elif kind in ("stage:招股中", "closing"):
        lines.append("\n想分析招股书：把 PDF 传给我，或发 /ipopdf 链接")
    if rec.get("articles"):
        a0 = rec["articles"][0]
        lines.append(f"\n🔗 <a href=\"{e(a0.get('link') or '')}\">{e((a0.get('title') or '')[:80])}</a>")
    lines.append("<i>资料整理自新闻，申购前请看招股书原文。不构成投资建议。</i>")
    return "\n".join(lines)


def analysis_html(a: dict) -> str:
    e = html.escape
    sc = a.get("score") or {}
    lines = [f"<b>📑 招股书分析｜{e(a.get('name') or '')}</b>（{e(a.get('market') or '?')} Market）",
             f"规则评分：<b>{sc.get('level') or '—'}</b>（{sc.get('avg') or '—'} / 5）",
             f"资料来源：{e(a.get('basis_zh') or '招股书')}"]
    for it in sc.get("items", []):
        lines.append(f"  · {it['name']}：{it['value']}" + (f"（{it['score']} 分）" if it["score"] else ""))
    if a.get("business_zh"):
        lines += ["", f"<b>业务</b>：{e(a['business_zh'])}"]
    fy = a.get("fy") or []
    if fy:
        lines.append("<b>财务（RM 百万）</b>：" + "；".join(
            f"{e(str(f.get('year')))} 营收 {f.get('revenue_rm_m')}、净利 {f.get('pat_rm_m')}" for f in fy))
    if a.get("proceeds"):
        lines.append("<b>募资用途</b>：" + "；".join(f"{e(str(p.get('use')))} {p.get('pct')}%" for p in a["proceeds"]))
    for label, k in (("股息政策", "dividend_policy"), ("大股东", "major_shareholders"), ("禁售期", "moratorium")):
        if a.get(k):
            lines.append(f"<b>{label}</b>：{e(a[k])}")
    for label, k in (("✅ 优势", "strengths_zh"), ("⚠️ 风险", "risks_zh"), ("🚩 要警惕", "red_flags_zh")):
        if a.get(k):
            lines.append(f"\n<b>{label}</b>\n" + "\n".join(f"• {e(str(x))}" for x in a[k]))
    if a.get("summary_zh"):
        lines += ["", f"🧠 {e(a['summary_zh'])}"]
    if a.get("basis") == "news":
        lines.append("\n<i>⚠️ 没找到招股书，只根据新闻分析，很多数字可能缺。把招股书 PDF 传给我可以分析得更准。</i>")
    lines.append("\n<i>AI 只读了重点段落，数字请对照原文。不构成投资建议。</i>")
    return "\n".join(lines)


def list_html(store: dict) -> str:
    recs = sorted(store.get("ipos", {}).values(), key=lambda r: (STAGES.index(r["stage"]) if r["stage"] in STAGES else 0,
                                                                  r.get("listing_date") or ""), reverse=False)
    open_ = [r for r in recs if r["stage"] in ("招股中", "认购结果")]
    soon = [r for r in recs if r["stage"] in ("草拟招股书", "计划中")]
    listed = sorted([r for r in recs if r["stage"] == "已上市"], key=lambda r: r.get("listing_date") or "", reverse=True)[:8]
    e = html.escape
    lines = ["<b>🆕 马股 IPO 追踪</b>"]

    def line(r):
        bits = [f"{r['market']}" if r.get("market") else "", f"RM{r['ipo_price']}" if r.get("ipo_price") else "",
                f"超额 {r['oversub_times']:.1f}x" if r.get("oversub_times") else "",
                f"上市 {r['listing_date']}" if r.get("listing_date") else ""]
        return f"{STAGE_ICON.get(r['stage'], '')} {e(r['name'])}　" + " · ".join(b for b in bits if b)

    if open_:
        lines += ["", "<b>招股中 / 等上市</b>"] + [line(r) for r in open_]
    if soon:
        lines += ["", "<b>筹备中</b>"] + [line(r) for r in soon[:10]]
    if listed:
        lines += ["", "<b>最近上市</b>"]
        for r in listed:
            p = r.get("perf") or {}
            lines.append(f"🔔 {e(r['name'])}　首日 {p.get('first_day_pct', 0):+.1f}%，至今 {p.get('since_ipo_pct', 0):+.1f}%"
                         if p else line(r))
    lines.append("\n<i>/ipo 公司名 看详细；把招股书 PDF 传给我就会分析。</i>")
    return "\n".join(lines)


def find(store: dict, text: str) -> dict | None:
    t = slug(text)
    for k, r in store.get("ipos", {}).items():
        if t and (t in k or k in t):
            return r
    return None


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
        src = sys.argv[1]
        data = fetch_pdf(src) if src.startswith("http") else open(src, "rb").read()
        a = analyze_pdf(data, src)
        print(analysis_html(a))
        save_analysis(a)
    else:
        print(list_html(run(push=False, force=True)))
