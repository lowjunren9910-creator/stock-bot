"""新闻追踪的「报纸版面」：把 feed.json 的新闻事件排成像新闻网站首页的样子（网站用）。

头条区：左边一则大新闻（大图 + 大标题），中间一则（图 + 标题），右边两则（小图）。
下面每个栏目（马股 / 美股 / 印尼股 / 宏观…）一排四则。
点标题打开原文；「AI 分析」可以展开看短期 / 长期影响。
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

import themes

MYT = timezone(timedelta(hours=8))
WEEK = "一二三四五六日"

# 栏目：名称 → 条件
SECTIONS = {
    "头条": None,
    "最新": None,
    "马股": lambda e: e.get("market") == "bursa" or (e.get("type") == "macro" and _any_mkt(e, "bursa")),
    "美股": lambda e: e.get("market") == "us" or (e.get("type") == "macro" and _any_mkt(e, "us")),
    "印尼股": lambda e: e.get("market") == "idx" or (e.get("type") == "macro" and _any_mkt(e, "idx")),
    "宏观": lambda e: e.get("type") == "macro",
    "业绩": lambda e: e.get("topic") == "业绩",
    "企业动态": lambda e: e.get("topic") in ("合约订单", "并购重组", "派息融资", "管理层", "业务扩张", "监管法律"),
    "利好": lambda e: _views(e) & {"利好"} and not _views(e) & {"利空"},
    "利空": lambda e: "利空" in _views(e),
}
FRONT_ROWS = ["马股", "美股", "印尼股", "宏观"]          # 头条页下面依序排的栏目


def _any_mkt(e, m):
    sfx = {"bursa": ".KL", "idx": ".JK"}
    for t in e.get("tickers") or []:
        if (m in sfx and t.endswith(sfx[m])) or (m == "us" and not t.endswith((".KL", ".JK"))):
            return True
    return False


def _views(e) -> set:
    if e.get("type") == "macro":
        return {a[k]["view"] for a in e.get("affected", []) for k in ("short_term", "long_term")}
    return {e["short_term"]["view"], e["long_term"]["view"]}


def _dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(MYT)
    except Exception:
        return None


def when(s: str) -> str:
    d = _dt(s)
    if not d:
        return ""
    h = d.hour % 12 or 12
    return f"{d.month}月{d.day}日, {h}:{d.minute:02d} {'PM' if d.hour >= 12 else 'AM'}"


def today_line() -> str:
    d = datetime.now(MYT)
    return f"{d.year}年{d.month}月{d.day}日星期{WEEK[d.weekday()]}"


def score(e: dict) -> float:
    """头条排序：重要性为主，越新越前（3 天内）。"""
    d = _dt(e.get("published", ""))
    hours = (datetime.now(MYT) - d).total_seconds() / 3600 if d else 999
    return e.get("importance", 1) * 10 - min(hours, 96) / 4


def pick(events: list[dict], section: str, sort: str = "最新") -> list[dict]:
    f = SECTIONS.get(section)
    out = [e for e in events if f is None or f(e)]
    if section == "头条" or sort == "最重要":
        return sorted(out, key=score, reverse=True)
    return sorted(out, key=lambda e: e.get("published", ""), reverse=True)


def _title(e: dict, lang: str) -> str:
    if lang == "EN" and e.get("articles"):
        t = e["articles"][0].get("title") or ""
        src = e["articles"][0].get("source") or ""
        if src and t.endswith(" - " + src):
            t = t[: -len(src) - 3]
        return t
    return e.get("headline_zh") or ""


def _kicker(e: dict) -> str:
    if e.get("type") == "macro":
        names = "、".join(a["name"] for a in e.get("affected", [])[:3])
        return f"宏观 · {names}" if names else "宏观"
    topic = e.get("topic")
    return f"{e.get('name', '')}" + (f" · {topic}" if topic and topic != "其他" else "")


def _link(e: dict) -> str:
    return (e.get("articles") or [{}])[0].get("link") or "#"


def _source(e: dict) -> str:
    return ((e.get("articles") or [{}])[0].get("source") or "").upper()


CHIP = {"利好": ("▲", "#0a7d4f", "#e3f4ec"), "利空": ("▼", "#b42318", "#fde8e6"), "中性": ("■", "#6b6b6b", "#eeeeee")}


def _chips(e: dict) -> str:
    x = html.escape
    out = []
    if e.get("type") == "macro":
        for a in e.get("affected", [])[:3]:
            v = a["short_term"]["view"]
            i, c, bg = CHIP.get(v, CHIP["中性"])
            out.append(f"<span class='np-chip' style='color:{c};background:{bg}'>{x(a['name'])} {i}{v}</span>")
    else:
        for lab, k in (("短期", "short_term"), ("长期", "long_term")):
            v = e[k]["view"]
            i, c, bg = CHIP.get(v, CHIP["中性"])
            out.append(f"<span class='np-chip' style='color:{c};background:{bg}'>{lab} {i}{v}</span>")
        px = e.get("price") or {}
        if px.get("chg_1d") is not None:
            ch = px["chg_1d"]
            c = "#0a7d4f" if ch > 0 else "#b42318" if ch < 0 else "#6b6b6b"
            out.append(f"<span class='np-chip np-px' style='color:{c}'>{x(e.get('ticker') or '')} {ch:+.2f}%</span>")
    return "<div class='np-chips'>" + "".join(out) + "</div>"


def _details(e: dict) -> str:
    x = html.escape
    rows = []
    if e.get("type") == "macro":
        for a in e.get("affected", []):
            rows.append(f"<li><b>{x(a['name'])}</b>：短期{a['short_term']['view']}（{x(a['short_term']['why'])}）；"
                        f"长期{a['long_term']['view']}（{x(a['long_term']['why'])}）</li>")
    else:
        rows.append(f"<li><b>短期（几天到几周）{e['short_term']['view']}</b>：{x(e['short_term']['why'])}</li>")
        rows.append(f"<li><b>长期（一年以上）{e['long_term']['view']}</b>：{x(e['long_term']['why'])}</li>")
    arts = "".join(f"<li><a href='{x(a.get('link') or '#')}' target='_blank'>{x((a.get('title') or '')[:110])}</a>"
                   f" — {x(a.get('source') or '')}</li>" for a in (e.get("articles") or [])[:4])
    return (f"<details class='np-more'><summary>AI 分析 · 把握度{x(e.get('confidence', '中'))}</summary>"
            f"<ul>{''.join(rows)}</ul><div class='np-src'>原文：</div><ul>{arts}</ul></details>")


def story(e: dict, size: str, lang: str = "中文") -> str:
    """size：lead（大图大标题）/ mid（图在上）/ side（右边小图）/ card（栏目一排四则）/ row（列表）"""
    x = html.escape
    title, link = x(_title(e, lang)), x(_link(e))
    img = x(themes.news_image(e, 1000 if size == "lead" else 600))
    meta = f"<div class='np-meta'>{when(e.get('published', ''))} · {x(_source(e))}</div>"
    kick = f"<div class='np-kick'>{x(_kicker(e))}</div>"
    dek = f"<p class='np-dek'>{x(e.get('analysis') or '')}</p>" if e.get("analysis") else ""
    stars = "★" * e.get("importance", 1)
    pic = lambda cls: f"<a href='{link}' target='_blank'><div class='{cls}' style=\"background-image:url('{img}')\"></div></a>"
    h = lambda cls: f"<a class='np-h {cls}' href='{link}' target='_blank'>{title}</a>"
    if size == "lead":
        return (f"<article class='np-lead'>{pic('np-img np-img-lead')}"
                f"<div class='np-imgcap'><span>{x(_kicker(e))}</span><span class='np-stars'>{stars}</span></div>"
                f"{h('np-h1')}{dek}{_chips(e)}{meta}{_details(e)}</article>")
    if size == "mid":
        return (f"<article class='np-mid'>{pic('np-img np-img-mid')}{kick}{h('np-h2')}{dek}{_chips(e)}{meta}"
                f"{_details(e)}</article>")
    if size == "side":
        short = x((e.get("analysis") or "")[:60] + ("…" if len(e.get("analysis") or "") > 60 else ""))
        return (f"<article class='np-side'>{h('np-h3')}<div class='np-sidebody'><p class='np-dek'>{short}</p>"
                f"{pic('np-img np-img-side')}</div>{_chips(e)}{meta}</article>")
    if size == "card":
        return (f"<article class='np-card'>{pic('np-img np-img-card')}{kick}{h('np-h4')}{_chips(e)}{meta}"
                f"{_details(e)}</article>")
    return (f"<article class='np-row'>{pic('np-img np-img-row')}<div>{kick}{h('np-h3')}{dek}{_chips(e)}{meta}"
            f"{_details(e)}</div></article>")


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@600;700;900&display=swap');
.np{background:#fff;color:#121212;border-radius:14px;padding:26px 30px 30px;font-family:"Noto Sans SC",system-ui,sans-serif}
.np a{color:inherit;text-decoration:none}
.np-mast{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid #d9d9d9;padding-bottom:10px}
.np-mast h1{font-family:"Noto Serif SC",serif;font-weight:900;font-size:2.7rem;margin:0;color:#121212;padding:0;line-height:1.1}
.np-date{color:#555;font-size:.85rem}
.np-sec{display:flex;justify-content:space-between;align-items:center;border-top:2px solid #121212;margin:34px 0 14px;padding-top:8px}
.np-sec h2{font-family:"Noto Serif SC",serif;font-weight:900;font-size:1.35rem;margin:0;padding:0;color:#121212}
.np-sec span{font-size:.78rem;color:#666}
.np-front{display:grid;grid-template-columns:1.75fr 1fr 1fr;gap:0;margin-top:22px}
.np-c2{grid-template-columns:1.6fr 1fr}.np-c1{grid-template-columns:1fr}
.np-solo{margin-top:22px}
.np-solo .np-lead{display:grid;grid-template-columns:1.25fr 1fr;column-gap:28px}
.np-solo .np-lead>a:first-child{grid-row:1 / span 6}
.np-solo .np-imgcap{margin-top:0}
.np-front>div{padding:0 22px;border-left:1px solid #e2e2e2}
.np-front>div:first-child{padding-left:0;border-left:none}
.np-front>div:last-child{padding-right:0}
.np-img{background:#eee center/cover no-repeat;width:100%}
.np-img-lead{aspect-ratio:16/9}.np-img-mid{aspect-ratio:3/2}.np-img-card{aspect-ratio:3/2}
.np-img-side{width:96px;min-width:96px;height:96px}.np-img-row{width:180px;min-width:180px;aspect-ratio:3/2}
.np-imgcap{display:flex;justify-content:space-between;font-size:.74rem;color:#666;margin:6px 0 4px}
.np-stars{color:#b8860b;letter-spacing:1px}
.np-h{display:block;font-family:"Noto Serif SC",serif;color:#121212;line-height:1.25}
.np-h:hover{text-decoration:underline}
.np-h1{font-size:2.05rem;font-weight:900;margin:8px 0 10px}
.np-h2{font-size:1.45rem;font-weight:900;margin:4px 0 8px}
.np-h3{font-size:1.18rem;font-weight:700;margin:0 0 8px}
.np-h4{font-size:1.05rem;font-weight:700;margin:2px 0 6px}
.np-kick{font-size:.74rem;color:#b42318;font-weight:700;margin-top:8px;letter-spacing:.5px}
.np-dek{font-family:"Noto Serif SC",serif;color:#333;font-size:.98rem;line-height:1.65;margin:0 0 8px}
.np-lead .np-dek{font-size:1.08rem}
.np-meta{font-size:.72rem;color:#666;letter-spacing:.4px;margin-top:6px}
.np-side{padding-bottom:16px;margin-bottom:16px;border-bottom:1px solid #e2e2e2}
.np-side:last-child{border-bottom:none}
.np-sidebody{display:flex;gap:12px}
.np-sidebody .np-dek{font-size:.88rem;flex:1}
.np-cards{display:grid;grid-template-columns:repeat(4,1fr);gap:22px}
.np-card .np-chips{margin-top:4px}
.np-row{display:flex;gap:18px;padding:16px 0;border-bottom:1px solid #e2e2e2}
.np-chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}
.np-chip{font-size:.72rem;font-weight:700;padding:2px 8px;border-radius:99px}
.np-px{background:#f4f4f4}
.np-more{margin-top:6px;font-size:.85rem;color:#333}
.np-more summary{cursor:pointer;color:#555;font-size:.76rem;list-style:none}
.np-more summary::before{content:"▸ "}
.np-more[open] summary::before{content:"▾ "}
.np-more ul{margin:6px 0 4px 18px;padding:0}
.np-more li{margin:3px 0;line-height:1.5;font-size:.85rem}
.np-more a{color:#1a56a8}
.np-src{font-size:.72rem;color:#888;margin-top:4px}
.np-empty{color:#666;padding:30px 0;text-align:center}
@media (max-width:900px){
 .np{padding:18px}
 .np-front,.np-c2,.np-c1{grid-template-columns:1fr}
 .np-solo .np-lead{display:block}
 .np-front>div{padding:0;border-left:none;border-top:1px solid #e2e2e2;margin-top:18px;padding-top:14px}
 .np-front>div:first-child{border-top:none;margin-top:0;padding-top:0}
 .np-cards{grid-template-columns:1fr 1fr}
 .np-h1{font-size:1.6rem}.np-img-row{width:110px;min-width:110px}
}
</style>
"""


def page(events: list[dict], section: str = "头条", lang: str = "中文", sort: str = "最新", title: str | None = None) -> str:
    """整页 HTML（一个字符串，交给 st.html）。"""
    parts = [CSS, "<div class='np'>",
             f"<div class='np-mast'><h1>{html.escape(title or section)}</h1><div class='np-date'>{today_line()}</div></div>"]
    evs = pick(events, section, sort)
    if not evs:
        parts.append("<div class='np-empty'>这个栏目暂时没有新闻。</div></div>")
        return _flat(parts)
    if section == "头条":
        lead, rest = evs[0], evs[1:]
        mid = rest[0] if rest else None
        sides = rest[1:3]
        cols = [story(lead, "lead", lang)]
        if mid:
            cols.append(story(mid, "mid", lang))
        if sides:
            cols.append("".join(story(e, "side", lang) for e in sides))
        parts.append(f"<div class='np-front np-c{len(cols)}'>"
                     + "".join(f"<div>{c}</div>" for c in cols) + "</div>")
        used = {id(e) for e in [lead, mid, *sides] if e}
        for name in FRONT_ROWS:
            row = [e for e in pick(events, name, "最新") if id(e) not in used][:4]
            if not row:
                continue
            used |= {id(e) for e in row}
            parts.append(f"<div class='np-sec'><h2>{name}</h2><span>上面「{name}」看更多 →</span></div>")
            parts.append("<div class='np-cards'>" + "".join(story(e, "card", lang) for e in row) + "</div>")
    else:
        top = evs[:1]
        parts.append("<div class='np-solo'>" + story(top[0], "lead", lang) + "</div>")
        if len(evs) > 1:
            parts.append(f"<div class='np-sec'><h2>更多{html.escape(section)}</h2><span>共 {len(evs)} 则</span></div>")
            parts.append("".join(story(e, "row", lang) for e in evs[1:40]))
    parts.append("</div>")
    return _flat(parts)


def _flat(parts: list[str]) -> str:
    return re.sub(r"\s*\n\s*", " ", "".join(parts))
