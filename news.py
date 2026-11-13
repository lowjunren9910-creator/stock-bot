"""
news.py - 新闻追踪：只追你感兴趣的公司，每条新闻附 AI 分析 + 对股价的短期 / 长期影响

流程（GitHub Actions 每小时跑一次，见 .github/workflows/news.yml）：
  1. 读 watchlist.yml：自选股 + news_only 名单（只想看新闻、不要价格提醒的公司）
  2. 每家公司抓新闻：Google 新闻（英文 / 马来文 / 印尼文，可加中文）+ Yahoo Finance
  3. 过滤：标题一定要提到这家公司（名字、简称或你写的关键字），看过的不再看
  4. 同一家公司的新新闻一起交给 AI：判断是不是真的跟公司有关、重不重要，
     同一件事的几篇报道合并成一个「事件」，写分析 + 短期 / 长期影响
  5. 重要性够高的才推送到 Telegram；全部存进 reports/news/feed.json（网站、手机 app 看）

注意：AI 只看到标题和摘要，看不到整篇文章，重要新闻请点链接看原文。
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).parent
DIR = ROOT / "reports" / "news"
FEED = DIR / "feed.json"
SEEN = DIR / "seen.json"

MAX_AGE_HOURS = 48          # 只看最近 48 小时的新闻
FEED_KEEP_DAYS = 30
UA = {"User-Agent": "Mozilla/5.0 (compatible; stock-news-bot/1.0)"}

# Google 新闻的地区 / 语言
REGION = {
    "bursa": [("en-MY", "MY", "MY:en"), ("ms-MY", "MY", "MY:ms")],
    "idx": [("en-ID", "ID", "ID:en"), ("id-ID", "ID", "ID:id")],
    "us": [("en-US", "US", "US:en")],
}
ZH_REGION = {"bursa": ("zh-CN", "MY", "MY:zh-Hans"), "idx": ("zh-CN", "ID", "ID:zh-Hans"),
             "us": ("zh-CN", "US", "US:zh-Hans")}

# 名字里这些字太普通，不能单独拿来当关键字
STOP = {"berhad", "bhd", "holdings", "group", "corp", "corporation", "inc", "the", "tbk", "pt", "persero",
        "co", "company", "ltd", "limited", "malaysia", "indonesia", "bank", "international", "industries",
        "resources", "energy", "power", "technologies", "technology", "properties", "property", "reit"}

IMPACT = {"利好": "📈", "利空": "📉", "中性": "➖"}


# ---------------------------------------------------------------------------
# 1. 要追踪哪些公司
# ---------------------------------------------------------------------------

FOLLOW = DIR / "follow.json"      # 你用 Telegram /follow 加的公司（自动存这里）


def load_follow() -> list[str]:
    try:
        return list(json.loads(FOLLOW.read_text(encoding="utf-8")))
    except Exception:
        return []


def set_follow(texts: list[str], add: bool = True) -> list[str]:
    """/follow、/unfollow：回传改了哪些代码。"""
    import analysis as A
    cur = load_follow()
    changed = []
    for x in texts:
        t = A.normalize_ticker(x)
        if add and t not in cur:
            cur.append(t)
            changed.append(t)
        elif not add and t in cur:
            cur.remove(t)
            changed.append(t)
    DIR.mkdir(parents=True, exist_ok=True)
    FOLLOW.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return changed


def companies() -> list[dict]:
    """watchlist.yml 的 stocks（除非写 news: false）+ news_only。"""
    import analysis as A
    path = ROOT / "watchlist.yml"
    if not path.exists():
        return []
    import yaml
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = [s if isinstance(s, dict) else {"ticker": s} for s in (data.get("stocks") or [])]
    raw = [s for s in raw if s.get("news", True) is not False]
    raw += [s if isinstance(s, dict) else {"ticker": s} for s in (data.get("news_only") or [])]
    raw += [{"ticker": t} for t in load_follow()]          # Telegram /follow 加的公司
    out, seen = [], set()
    for s in raw:
        if not s.get("ticker"):
            continue
        t = A.normalize_ticker(str(s["ticker"]))
        if t in seen:
            continue
        seen.add(t)
        out.append(make_company(t, str(s["ticker"]), s.get("keywords"), s.get("exclude")))
    return out


LEGAL = r"\b(berhad|bhd\.?|tbk\.?|pt|inc\.?|corp\.?|corporation|ltd\.?|limited|plc|co\.?|n\.v\.|s\.a\.)$"
# 市场里的「上下文字眼」：简称太短（PPB、IOI、MISC）时，新闻还要出现这些字才算
BUSINESS = ["profit", "profits", "revenue", "earnings", "quarter", "quarterly", "dividend", "contract", "shares",
            "share price", "stock", "ceo", "chairman", "billion", "million", "acquisition", "acquire", "merger",
            "analyst", "analysts", "investor", "investors", "listed", "subsidiary", "target price",
            "盈利", "营收", "净利", "股价", "股息", "合约", "收购", "股东", "季报", "业绩"]
CONTEXT = {
    "bursa": BUSINESS + ["bhd", "berhad", "bursa", "klse", "malaysia", "malaysian", "ringgit", "rm", "sen",
                         "kuala lumpur", "马来西亚", "大马", "马股", "令吉", "laba", "untung", "syarikat"],
    "idx": BUSINESS + ["tbk", "bei", "idx", "saham", "indonesia", "rupiah", "jakarta", "laba", "pendapatan",
                       "dividen", "印尼"],
    "us": BUSINESS + ["stocks", "nasdaq", "nyse", "wall street", "s&p", "美股"],
}
RULES = DIR / "rules.json"      # 你用 Telegram /notnews、/newskw 加的规则（自动存这里）


def _strip_legal(n: str) -> str:
    n = re.sub(r"\(.*?\)", "", n).strip(" ,.")
    for _ in range(3):
        n2 = re.sub(LEGAL, "", n, flags=re.I).strip(" ,.")
        if n2 == n:
            break
        n = n2
    return n


def make_company(t: str, user_input: str, extra=None, exclude=None) -> dict:
    import universe
    import fundamentals as F
    try:
        i = F.info(t)
    except Exception:
        i = {}
    short = universe.name_of(t) or i.get("shortName") or t
    long_ = _strip_legal(i.get("longName") or i.get("shortName") or short)
    rule = load_rules().get(t, {})
    extra = [str(k) for k in (extra or [])] + rule.get("keywords", [])
    exclude = list(exclude or []) + rule.get("exclude", [])
    strong, weak = keywords(t, short, long_, user_input)
    return {"ticker": t, "name": short, "long_name": long_, "market": universe.market_of(t), "input": user_input,
            "strong": sorted(set(strong + extra)), "weak": sorted(set(weak) - set(extra)),
            "keywords": sorted(set(strong + weak + extra)),
            "exclude": [str(k).lower() for k in (exclude or [])],
            "about": {"行业": i.get("industry"), "板块": i.get("sector"),
                      "业务简介": (i.get("longBusinessSummary") or "")[:400]}}


def load_rules() -> dict:
    try:
        return json.loads(RULES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def add_rule(text: str, kind: str, words: list[str]) -> str:
    """kind = exclude（这些字出现就不要）或 keywords（这些字一出现就算）。"""
    import analysis as A
    t = A.normalize_ticker(text)
    rules = load_rules()
    r = rules.setdefault(t, {"exclude": [], "keywords": []})
    for w in words:
        if w and w not in r[kind]:
            r[kind].append(w)
    DIR.mkdir(parents=True, exist_ok=True)
    RULES.write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding="utf-8")
    return t


def rules_html() -> str:
    rules = load_rules()
    if not rules:
        return "还没有自订的新闻规则。"
    lines = ["<b>🗞️ 新闻规则</b>"]
    for t, r in rules.items():
        if r.get("keywords"):
            lines.append(f"<code>{t}</code> 一定算：{html.escape('、'.join(r['keywords']))}")
        if r.get("exclude"):
            lines.append(f"<code>{t}</code> 不要：{html.escape('、'.join(r['exclude']))}")
    return "\n".join(lines)


def keywords(ticker: str, short: str, long_: str, user_input: str) -> tuple[list[str], list[str]]:
    """强关键字（完整名字：一出现就算）和弱关键字（简称：要配合上下文字眼才算）。"""
    strong, weak = set(), set()

    def add(k):
        k = k.strip()
        if len(k) < 3 or re.search(r"\d{4}", k):     # 太短，或是 1155.KL 这种代码
            return
        # 只有一个字的名字（PPB、Maybank、Tenaga、Dialog、Sunway…）可能是普通的字、别的机构或地名，
        # 所以当弱关键字：新闻里还要有 Bhd / RM / profit / shares 之类的上下文才算
        (weak if " " not in k else strong).add(k)

    for n in (long_, _strip_legal(short)):
        add(n)
        core = [w for w in re.split(r"[\s,.&]+", n) if w and w.lower() not in STOP]
        if core and " ".join(core) != n:
            add(" ".join(core))
    code = ticker.split(".")[0]
    if not code.isdigit():
        add(code)                                   # NVDA、BBCA（数字代码的 Bursa 不用）
    if not user_input.isdigit():
        add(user_input)                             # MAYBANK、TENAGA、PPB
    low = {k.lower() for k in strong}
    weak = {k for k in weak if k.lower() not in low}
    uniq = {}
    for k in sorted(weak):                          # MAYBANK 和 Maybank 只留一个
        uniq.setdefault(k.lower(), k)
    return sorted(strong), sorted(uniq.values())


def _info_name(t):
    try:
        import fundamentals as F
        i = F.info(t)
        return i.get("shortName") or i.get("longName")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2. 抓新闻
# ---------------------------------------------------------------------------

def _hash(title: str) -> str:
    t = re.sub(r"\W+", "", title.lower())
    return hashlib.sha1(t.encode()).hexdigest()[:16]


def _strip_source(title: str, source: str) -> str:
    if source and title.endswith(f" - {source}"):
        return title[: -len(source) - 3]
    return title


def google_news(query: str, hl: str, gl: str, ceid: str) -> list[dict]:
    url = (f"https://news.google.com/rss/search?q={quote(query)}+when:2d"
           f"&hl={hl}&gl={gl}&ceid={quote(ceid)}")
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  Google 新闻失败（{query}）：{e}")
        return []
    out = []
    for it in root.iter("item"):
        src_el = it.find("source")
        source = src_el.text if src_el is not None else ""
        title = _strip_source(html.unescape(it.findtext("title") or ""), source)
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            when = datetime.now(timezone.utc)
        desc = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or ""))
        out.append({"title": title, "source": source, "link": it.findtext("link"),
                    "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "summary": re.sub(r"\s+", " ", desc).strip()[:300], "via": "google"})
    return out


def yahoo_news(ticker: str) -> list[dict]:
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).news or []
    except Exception:
        return []
    out = []
    for n in raw[:15]:
        c = n.get("content", n)
        title = c.get("title")
        if not title:
            continue
        link = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
        when = c.get("pubDate") or c.get("providerPublishTime")
        try:
            when = (datetime.fromtimestamp(when, timezone.utc) if isinstance(when, (int, float))
                    else datetime.fromisoformat(str(when).replace("Z", "+00:00")))
        except Exception:
            when = datetime.now(timezone.utc)
        prov = c.get("provider") or {}
        out.append({"title": title, "source": prov.get("displayName") if isinstance(prov, dict) else c.get("publisher", ""),
                    "link": link, "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "summary": (c.get("summary") or "")[:300], "via": "yahoo"})
    return out


def _has(text: str, k: str) -> bool:
    k = k.lower()
    if re.search(r"[\u4e00-\u9fff]", k):            # 中文：直接找
        return k in text
    return re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", text) is not None


def mentions(item: dict, c: dict) -> bool:
    """新闻是不是在讲这家公司。"""
    text = f"{item['title']} {item.get('summary', '')}".lower()
    if any(x in text for x in c.get("exclude", [])):
        return False
    if item.get("via") == "yahoo":                 # Yahoo 的新闻本来就是按股票代码分好的
        return True
    if any(_has(text, k) for k in c.get("strong", [])):
        return True
    if any(_has(text, k) for k in c.get("weak", [])):
        return any(_has(text, w) for w in CONTEXT[c["market"]])   # 简称 + 上下文才算
    return False


def gather(c: dict, seen: dict) -> list[dict]:
    """一家公司的新新闻（还没看过、48 小时内、标题提到这家公司）。"""
    is_zh = lambda k: re.search(r"[\u4e00-\u9fff]", k) is not None
    strong = [k for k in c.get("strong", []) if not is_zh(k)]
    weak = [k for k in c.get("weak", []) if not is_zh(k)]
    ctx = {"bursa": "(Bhd OR Berhad OR Bursa)", "idx": "(Tbk OR saham OR IDX)",
           "us": "(stock OR shares OR earnings)"}[c["market"]]
    queries = []
    if strong:
        queries.append(f'"{max(strong, key=len)}"')
    for w in weak[:2]:
        queries.append(f'"{w}" {ctx}')              # 简称：一定要配合 Bhd / Tbk / stock 之类一起找
    items = []
    for q in queries:
        for hl, gl, ceid in REGION[c["market"]]:
            items += google_news(q, hl, gl, ceid)
    zh = [k for k in c["keywords"] if re.search(r"[一-鿿]", k)]
    if zh:                                          # 有写中文关键字：也看中文新闻（星洲、南洋…）
        items += google_news(" OR ".join(f'"{k}"' for k in zh), *ZH_REGION[c["market"]])
    items += yahoo_news(c["ticker"])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, here = [], set()
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        h = _hash(it["title"])
        key = f"{c['ticker']}:{h}"                  # 每家公司分开记：一篇讲两家公司的新闻，两家都会分析
        if h in here or key in seen or it["published"] < cutoff:
            continue
        here.add(h)
        it["id"] = h
        it["key"] = key
        if mentions(it, c):
            out.append(it)
        else:
            seen[key] = it["published"][:10]        # 没提到这家公司：记下来，下次不用再看
    return out[:12]


# ---------------------------------------------------------------------------
# 3. AI 分析
# ---------------------------------------------------------------------------

SYSTEM = """你是资深股票分析师，帮投资者读新闻。下面是关于某一家上市公司的几条新闻（只有标题和摘要）。
请用简体中文分析，只回传 JSON，格式：
{"events":[{"ids":["新闻id",...],"relevant":true,"importance":1-5,"headline_zh":"一句话中文标题",
"analysis":"2-3 句：发生了什么、为什么重要","short_term":{"view":"利好|利空|中性","why":"1 句：几天到几周的股价影响"},
"long_term":{"view":"利好|利空|中性","why":"1 句：一年以上对业务和盈利的影响"},"confidence":"高|中|低"}]}
规则：
- 报道同一件事的几条新闻合并成一个事件（ids 放在一起）。
- relevant=false：新闻其实不是在讲这家公司。特别注意「同名不同机构」：先看「公司资料」的行业和业务，
  例如简称一样但其实是别国的政府部门、协会、别的公司，一律 relevant=false。只是顺带一提、大盘新闻也是 false。
- importance：5=重大（业绩大幅偏离、并购、大合约、监管处罚、管理层巨变），3=值得知道，1=无关紧要的例行新闻。
- 只根据提供的内容判断，不要编造数字或细节；资料不够就说「要看原文确认」，confidence 用「低」。
- 考虑股价最近的走势：如果已经大涨或大跌，提醒可能已经反映在股价里。"""


def _json_from(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def price_context(ticker: str) -> dict:
    try:
        import fundamentals as F
        df = F.prices([ticker], "6mo").get(ticker)
        c = df["Close"].dropna()
        p = float(c.iloc[-1])
        r = lambda n: round((p / float(c.iloc[-n - 1]) - 1) * 100, 2) if len(c) > n else None
        return {"price": round(p, 3), "chg_1d": r(1), "chg_1w": r(5), "chg_1m": r(21)}
    except Exception:
        return {}


def analyze(c: dict, items: list[dict], px: dict | None = None) -> list[dict]:
    import asyncio
    import managers as M
    if M.check_setup():
        return []
    px = px if px is not None else price_context(c["ticker"])
    brief = {"公司": f"{c.get('long_name') or c['name']} ({c['ticker']})", "公司资料": c.get("about") or {},
             "股价近况": px,
             "新闻": [{"id": it["id"], "标题": it["title"], "来源": it["source"], "时间": it["published"],
                     "摘要": it.get("summary", "")} for it in items]}
    text = asyncio.run(M.chat(SYSTEM, json.dumps(brief, ensure_ascii=False), 1400))
    data = _json_from(text)
    if not data or "events" not in data:
        # 小模型有时不按格式回答：当作失败，这些新闻不标记为看过，下一小时再试
        raise ValueError("AI 回传的格式不对")
    by_id = {it["id"]: it for it in items}
    events = []
    for ev in data.get("events") or []:
        ids = [i for i in ev.get("ids") or [] if i in by_id]
        if not ids:
            continue
        arts = [by_id[i] for i in ids]
        st_, lt = ev.get("short_term") or {}, ev.get("long_term") or {}
        events.append({
            "id": ids[0], "ticker": c["ticker"], "name": c["name"], "market": c["market"],
            "relevant": bool(ev.get("relevant", True)),
            "importance": max(1, min(5, int(ev.get("importance") or 1))),
            "headline_zh": str(ev.get("headline_zh") or arts[0]["title"]),
            "analysis": str(ev.get("analysis") or ""),
            "short_term": {"view": _view(st_.get("view")), "why": str(st_.get("why") or "")},
            "long_term": {"view": _view(lt.get("view")), "why": str(lt.get("why") or "")},
            "confidence": str(ev.get("confidence") or "中"),
            "articles": [{k: a.get(k) for k in ("title", "source", "link", "published")} for a in arts],
            "published": max(a["published"] for a in arts),
            "price": px,
        })
    return events


def _view(v) -> str:
    v = str(v or "")
    return "利好" if "好" in v else "利空" if "空" in v else "中性"


# ---------------------------------------------------------------------------
# 4. 每小时跑一次
# ---------------------------------------------------------------------------

def _load(p: Path, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return d


# ---------------------------------------------------------------------------
# 4b. 宏观大新闻：利率、油价、关税、汇率、政府预算…… 有牵连到你的公司才发
# ---------------------------------------------------------------------------

MACRO_STATE = DIR / "macro_state.json"
MACRO_QUERIES = {
    "bursa": [("en-MY", "MY", "MY:en"), ['"Bank Negara" OPR', "ringgit", "Malaysia budget", "Malaysia GDP OR inflation",
                                          "Malaysia subsidy OR SST OR tariff", "crude palm oil prices",
                                          "Malaysia data centre electricity tariff"]],
    "idx": [("en-ID", "ID", "ID:en"), ['"Bank Indonesia" rate', "rupiah", "Indonesia coal OR nickel export",
                                        "Indonesia budget OR GDP"]],
    "global": [("en-US", "US", "US:en"), ['"Federal Reserve" rates', "oil prices OPEC", "tariffs trade war",
                                           "China economy stimulus", "US inflation CPI", "chip export controls",
                                           "AI data center spending"]],
}
TOPIC_FEEDS = {   # Google 新闻的「商业」头条
    "bursa": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-MY&gl=MY&ceid=MY:en",
    "global": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
}

MACRO_SYSTEM = """你是宏观策略分析师。下面是最近的宏观 / 行业新闻标题，以及投资者关注的公司名单（附行业和业务）。
找出「会明显影响名单里某些公司」的宏观或行业事件，用简体中文分析，只回传 JSON：
{"events":[{"ids":["新闻id",...],"importance":1-5,"headline_zh":"一句话中文标题",
"analysis":"2-3 句：发生了什么、通过什么途径影响这些公司（利率、成本、需求、汇率、政策…）",
"affected":[{"ticker":"名单里的代码","short_term":{"view":"利好|利空|中性","why":"1 句"},
"long_term":{"view":"利好|利空|中性","why":"1 句"}}],"confidence":"高|中|低"}]}
规则：
- 只要宏观、政策、商品价格、行业层面的事件；只讲某一家公司的新闻不要（另外有系统处理）。
- affected 只放真的有明显牵连的公司，说得出影响途径才放；没有任何公司受影响的事件不要回传。
- 报道同一件事的几条合并成一个事件。importance：5=央行利率决定、大型政策 / 关税、商品价格剧变；3=值得知道；1=小事。
- 只根据提供的内容，不要编造数字；不确定就 confidence「低」。"""


def macro_due(every_h: float, now: datetime) -> bool:
    st_ = _load(MACRO_STATE, {})
    last = st_.get("last")
    if not last:
        return True
    try:
        return (now - datetime.fromisoformat(last)).total_seconds() >= every_h * 3600 - 600
    except Exception:
        return True


def _feed(url: str) -> list[dict]:
    """直接读一个 Google 新闻 RSS 网址（商业头条）。"""
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  商业头条失败：{e}")
        return []
    out = []
    for it in root.iter("item"):
        src_el = it.find("source")
        source = src_el.text if src_el is not None else ""
        try:
            when = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            when = datetime.now(timezone.utc)
        out.append({"title": _strip_source(html.unescape(it.findtext("title") or ""), source), "source": source,
                    "link": it.findtext("link"), "published": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "summary": "", "via": "google"})
    return out


def macro_headlines(markets: set[str], seen: dict, max_items: int = 30) -> list[dict]:
    items = []
    for key in ["global", *sorted(markets)]:
        if key not in MACRO_QUERIES:
            continue
        (hl, gl, ceid), queries = MACRO_QUERIES[key]
        for q in queries:
            items += google_news(q, hl, gl, ceid)
        if key in TOPIC_FEEDS:
            items += _feed(TOPIC_FEEDS[key])
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, here = [], set()
    for it in sorted(items, key=lambda x: x["published"], reverse=True):
        h = _hash(it["title"])
        key = f"macro:{h}"
        if h in here or key in seen or it["published"] < cutoff:
            continue
        here.add(h)
        it.update(id=h, key=key)
        out.append(it)
    return out[:max_items]


def analyze_macro(comps: list[dict], items: list[dict]) -> list[dict]:
    import asyncio
    import managers as M
    if M.check_setup() or not comps or not items:
        return []
    by_t = {c["ticker"]: c for c in comps}
    brief = {"关注的公司": [{"代码": c["ticker"], "名字": c.get("long_name") or c["name"],
                         "行业": (c.get("about") or {}).get("行业"), "板块": (c.get("about") or {}).get("板块"),
                         "业务": ((c.get("about") or {}).get("业务简介") or "")[:160]} for c in comps],
             "新闻": [{"id": it["id"], "标题": it["title"], "来源": it["source"], "时间": it["published"]} for it in items]}
    text = asyncio.run(M.chat(MACRO_SYSTEM, json.dumps(brief, ensure_ascii=False), 1800))
    data = _json_from(text)
    if not data or "events" not in data:
        raise ValueError("AI 回传的格式不对")
    by_id = {it["id"]: it for it in items}
    events = []
    for ev in data["events"]:
        ids = [i for i in ev.get("ids") or [] if i in by_id]
        aff = []
        for a in ev.get("affected") or []:
            c = by_t.get(str(a.get("ticker", "")).strip())
            if not c:
                continue
            st_, lt = a.get("short_term") or {}, a.get("long_term") or {}
            aff.append({"ticker": c["ticker"], "name": c["name"],
                        "short_term": {"view": _view(st_.get("view")), "why": str(st_.get("why") or "")},
                        "long_term": {"view": _view(lt.get("view")), "why": str(lt.get("why") or "")}})
        if not ids or not aff:
            continue
        arts = [by_id[i] for i in ids]
        events.append({
            "type": "macro", "id": ids[0], "ticker": None, "name": "宏观", "market": None, "relevant": True,
            "tickers": [a["ticker"] for a in aff], "affected": aff,
            "importance": max(1, min(5, int(ev.get("importance") or 1))),
            "headline_zh": str(ev.get("headline_zh") or arts[0]["title"]),
            "analysis": str(ev.get("analysis") or ""), "confidence": str(ev.get("confidence") or "中"),
            "articles": [{k: a.get(k) for k in ("title", "source", "link", "published")} for a in arts],
            "published": max(a["published"] for a in arts)})
    return events


def macro_html(e: dict) -> str:
    x = html.escape
    lines = [f"🌏 <b>宏观新闻</b>　重要性 {stars(e['importance'])}", f"<b>{x(e['headline_zh'])}</b>", ""]
    if e["analysis"]:
        lines += [f"🧠 {x(e['analysis'])}", ""]
    lines.append("<b>对你关注的公司：</b>")
    for a in e["affected"]:
        st_, lt = a["short_term"], a["long_term"]
        lines.append(f"• <b>{x(a['name'])}</b> <code>{a['ticker']}</code>\n"
                     f"   {IMPACT[st_['view']]} 短期{st_['view']}：{x(st_['why'])}\n"
                     f"   {IMPACT[lt['view']]} 长期{lt['view']}：{x(lt['why'])}")
    lines.append(f"\n把握度：{x(e['confidence'])}")
    for a in e["articles"][:3]:
        lines.append(f"🔗 <a href=\"{x(a['link'] or '')}\">{x(a['title'][:90])}</a> — {x(a['source'] or '')}，{_ago(a['published'])}")
    lines.append("\n<i>AI 只看了标题，仅供参考，不构成投资建议。</i>")
    return "\n".join(lines)


def run(push: bool = True) -> dict:
    import scanner as S
    comps = companies()
    seen = _load(SEEN, {})
    feed = _load(FEED, {"events": []})
    first_run = not SEEN.exists()
    min_imp = int(os.getenv("NEWS_MIN_IMPORTANCE") or 3)
    max_ai = int(os.getenv("NEWS_AI_MAX") or 8)        # 每次最多几次 AI（控制额度）
    print(f"新闻追踪：{len(comps)} 家公司" + ("（第一次运行：先分析存起来，不推送）" if first_run else ""))

    new_events, ai_used = [], 0
    for c in comps:
        items = gather(c, seen)
        if not items:
            continue
        print(f"  {c['name']}：{len(items)} 条新新闻")
        if ai_used >= max_ai:
            print("    这次 AI 次数用完了，下次再分析")
            continue                                  # 不标记为看过，下次再处理
        try:
            evs = analyze(c, items)
            ai_used += 1
        except Exception as e:
            print(f"    AI 分析失败（下次再试）：{e}")
            continue
        for it in items:
            seen[it["key"]] = it["published"][:10]
        new_events += [e for e in evs if e["relevant"]]

    # 宏观新闻：默认每 2 小时一次（一次 AI 看完全部标题），有牵连到你的公司才留下
    every = float(os.getenv("NEWS_MACRO_EVERY") or 2)
    now = datetime.now(timezone.utc)
    if every > 0 and comps and macro_due(every, now):
        heads = macro_headlines({c["market"] for c in comps}, seen)
        print(f"  宏观新闻：{len(heads)} 条新标题")
        if heads:
            try:
                mev = analyze_macro(comps, heads)
                ai_used += 1
                for it in heads:
                    seen[it["key"]] = it["published"][:10]
                new_events += mev
                print(f"    跟你的公司有关的宏观事件：{len(mev)} 个")
            except Exception as e:
                print(f"    宏观 AI 分析失败（下次再试）：{e}")
        MACRO_STATE.parent.mkdir(parents=True, exist_ok=True)
        MACRO_STATE.write_text(json.dumps({"last": now.isoformat()}), encoding="utf-8")

    # 保存：feed 只留 30 天；seen 只留 7 天
    cut = (datetime.now(timezone.utc) - timedelta(days=FEED_KEEP_DAYS)).strftime("%Y-%m-%d")
    fresh_ids = {(e["ticker"], e["id"]) for e in new_events}
    by_t = {c["ticker"]: c for c in comps}

    def still_ok(e):     # 旧新闻用新的规则再检查一次（例如 PPB 被认成别国的 PPB）
        c = by_t.get(e["ticker"])
        return c is None or any(mentions({"title": a["title"]}, c) for a in e.get("articles", []))

    feed["events"] = [e for e in feed.get("events", []) if still_ok(e)]
    events = new_events + [e for e in feed.get("events", [])
                           if e.get("published", "") >= cut and (e["ticker"], e["id"]) not in fresh_ids]
    events.sort(key=lambda e: e["published"], reverse=True)
    week = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    seen = {k: v for k, v in seen.items() if v >= week}
    out = {"updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "companies": [{k: c[k] for k in ("ticker", "name", "market", "keywords")} for c in comps],
           "followed": load_follow(),
           "events": events[:300],
           "note": "AI 只看了新闻标题和摘要，重要新闻请点链接看原文。影响判断仅供参考，不构成投资建议。"}
    DIR.mkdir(parents=True, exist_ok=True)
    FEED.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    SEEN.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    # 不更新 index.json：新闻是另一个 workflow 在跑，避免两边同时改同一个文件

    hot = [e for e in new_events if e["importance"] >= min_imp]
    print(f"  新事件 {len(new_events)} 个，推送 {len(hot)} 个（重要性 ≥ {min_imp}），用了 AI {ai_used} 次")
    if push and not first_run:                       # 第一次运行只建立新闻库，不一次推一大堆
        for e in sorted(hot, key=lambda e: -e["importance"]):
            S.push_text(macro_html(e) if e.get("type") == "macro" else event_html(e))
    return out


# ---------------------------------------------------------------------------
# 5. 随时分析一家公司最新新闻（Telegram /news、网站）
# ---------------------------------------------------------------------------

def quick(text: str) -> list[dict]:
    import analysis as A
    c = make_company(A.normalize_ticker(text), text)
    items = gather(c, {})
    if not items:
        return []
    return sorted(analyze(c, items), key=lambda e: (-e["relevant"], -e["importance"]))


# ---------------------------------------------------------------------------
# 6. 显示
# ---------------------------------------------------------------------------

def stars(n: int) -> str:
    return "★" * n + "☆" * (5 - n)


def _ago(iso: str) -> str:
    try:
        d = datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))
        h = int(d.total_seconds() // 3600)
        return f"{max(1, int(d.total_seconds() // 60))} 分钟前" if h < 1 else f"{h} 小时前" if h < 48 else f"{h // 24} 天前"
    except Exception:
        return ""


def event_html(e: dict) -> str:
    x = html.escape
    st_, lt = e["short_term"], e["long_term"]
    px = e.get("price") or {}
    lines = [f"📰 <b>{x(e['name'])}</b> <code>{e['ticker']}</code>　重要性 {stars(e['importance'])}",
             f"<b>{x(e['headline_zh'])}</b>", ""]
    if e["analysis"]:
        lines += [f"🧠 {x(e['analysis'])}", ""]
    lines.append(f"{IMPACT[st_['view']]} <b>短期（几天到几周）：{st_['view']}</b>　{x(st_['why'])}")
    lines.append(f"{IMPACT[lt['view']]} <b>长期（一年以上）：{lt['view']}</b>　{x(lt['why'])}")
    if px.get("price") is not None:
        lines.append(f"\n股价 {px['price']:,.2f}（今天 {px.get('chg_1d') or 0:+.2f}%，1 个月 {px.get('chg_1m') or 0:+.1f}%）　把握度：{x(e['confidence'])}")
    lines.append("")
    for a in e["articles"][:3]:
        lines.append(f"🔗 <a href=\"{x(a['link'] or '')}\">{x(a['title'][:90])}</a> — {x(a['source'] or '')}，{_ago(a['published'])}")
    lines.append("\n<i>AI 只看了标题和摘要，仅供参考，不构成投资建议。</i>")
    return "\n".join(lines)


def list_html(events: list[dict], title: str) -> str:
    if not events:
        return f"{title}\n\n最近 48 小时没有找到相关新闻。"
    return "\n\n———\n\n".join([title] + [event_html(e) for e in events[:5]])


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    if len(sys.argv) > 1:
        print(list_html(quick(sys.argv[1]), f"新闻：{sys.argv[1]}"))
    else:
        run()
