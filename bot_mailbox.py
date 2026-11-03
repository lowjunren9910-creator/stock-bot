"""
bot_mailbox.py - Telegram「信箱模式」：不用开电脑的问答机器人

GitHub Actions 每 15 分钟运行一次：
  1. 读取你发给机器人的新消息
  2. 先告诉 Telegram「这些消息已读」（避免重复处理）
  3. 逐条回复：个股分析、基金经理圆桌、认识公司、选股雷达、KLCI 50 …
  4. 做完就结束，等下一个 15 分钟

安全：只回复 TELEGRAM_CHAT_ID 里的人（就是你），陌生人用不了你的 AI 额度。
注意：不要同时在电脑上运行 bot.py，两边会抢消息。
"""

from __future__ import annotations

import asyncio
import html
import os
from datetime import date

import requests

import analysis as A
import company as C
import klci as K
import managers as M
import screener as SC

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
ALLOWED = {s.strip() for s in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if s.strip()}
esc = html.escape

PANEL_NAMES = "、".join(f"{m['emoji']}{m['name']}" for m in M.MANAGERS)
HELP = f"""<b>📊 股票分析机器人（信箱模式）</b>
每 15 分钟处理一次消息，发完稍等一下就会收到回复。
市场：🇲🇾 大马 · 🇺🇸 美股 · 🇮🇩 印尼

<b>直接发股票代码</b> → 完整分析 + 基金经理圆桌（{PANEL_NAMES}）
  例如 <code>MAYBANK</code>、<code>1155</code>、<code>NVDA</code>、<code>BBCA</code>

/company 代码 - 认识公司：业务、成绩、管理层 + 弱到强评级
/radar [bursa|idx|us] - 今日错杀股 / 成长股 / 双杀股
/klci - KLCI 50 最有机会入选的公司
/quick 代码 - 只看数据报告（不开圆桌）
/panel 代码 - 只开基金经理圆桌
/tech、/fund、/news、/chart + 代码 - 单独看某一部分
/myid - 查看你的 Chat ID

投资组合请用网站版（信箱模式不会保存资料）。"""


# ---------------------------------------------------------------------------
# Telegram API（直接用 requests，不需要一直开着连接）
# ---------------------------------------------------------------------------

def tg(method: str, files=None, **data) -> dict:
    r = requests.post(f"{API}/{method}", data=data, files=files, timeout=60)
    return r.json()


def send(chat, text: str):
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=chat, text=text[i:i + 4000], parse_mode="HTML",
           disable_web_page_preview=True)


def send_photo(chat, buf, caption: str = ""):
    tg("sendPhoto", chat_id=chat, caption=caption, files={"photo": ("chart.png", buf, "image/png")})


def typing(chat):
    tg("sendChatAction", chat_id=chat, action="typing")


# ---------------------------------------------------------------------------
# 各种指令
# ---------------------------------------------------------------------------

def do_panel(chat, snapshot: dict):
    async def run():
        M._client = None
        ops = await M.ask_all(snapshot)
        return list(ops), await M.chairman_summary(snapshot, list(ops))

    if M.check_setup():
        return send(chat, f"⚠️ {esc(M.check_setup())}")
    typing(chat)
    opinions, summary = asyncio.run(run())
    send(chat, f"🎙 <b>基金经理圆桌</b>：{esc(snapshot['名称'])}")
    for o in opinions:
        send(chat, f"{o['emoji']} <b>{o['name']}｜{o['title']}</b>\n\n{esc(o['text'])}")
    send(chat, f"👔 <b>投资委员会主席总结</b>\n\n{esc(summary)}\n\n"
               "<i>以上为 AI 模拟观点，仅供学习参考，不构成投资建议。</i>")


def do_analyze(chat, text: str, report=True, panel=True):
    typing(chat)
    ticker, html_report, df, snapshot = A.full_report(text)
    if report:
        send(chat, html_report)
        send_photo(chat, A.make_chart(ticker, df), ticker)
    if panel:
        do_panel(chat, snapshot)


def do_company(chat, text: str):
    typing(chat)
    p = C.fetch(text)
    try:
        ai = asyncio.run(C.ai_profile(p))
    except Exception as e:
        ai = None
        send(chat, f"⚠️ AI 研究员暂时无法工作（{esc(str(e))}），先给你财务体检。")
    send(chat, C.to_telegram_html(p, ai))


def fresh(r: dict | None) -> bool:
    return bool(r) and r.get("date") == str(date.today())


def do_radar(chat, arg: str):
    market = (arg or "bursa").lower()
    if market not in SC.S.MARKETS:
        return send(chat, "用法：/radar [bursa|idx|us]")
    r = SC.latest(market)
    if not fresh(r):
        typing(chat)
        r = SC.screen(market)
    send(chat, SC.to_telegram_html(r))


def do_klci(chat):
    r = K.latest()
    if not fresh(r):
        typing(chat)
        r = K.track()
        r["ai_comment"] = K.ai_comment(r)
    send(chat, K.to_telegram_html(r))


def do_fund(chat, text: str):
    t = A.normalize_ticker(text)
    df = A.get_history(t, "5d")
    send(chat, A.format_fundamental(A.fundamental_summary(t, A.get_info(t), float(df["Close"].iloc[-1]))))


def handle(chat, text: str):
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # 群组里会是 /radar@你的bot
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/start", "/help"):
        return send(chat, HELP)
    if cmd == "/myid":
        return send(chat, f"你的 Chat ID：<code>{chat}</code>")
    if cmd in ("/buy", "/sell", "/portfolio"):
        return send(chat, "💼 信箱模式不会保存资料，投资组合请用网站版的「投资组合」页面。")

    need = {"/analyze", "/quick", "/panel", "/company", "/tech", "/fund", "/news", "/chart"}
    if cmd in need and not arg:
        return send(chat, f"用法：{cmd} 股票代码，例如 {cmd} MAYBANK")

    if cmd == "/company":
        return do_company(chat, arg)
    if cmd == "/radar":
        return do_radar(chat, arg)
    if cmd == "/klci":
        return do_klci(chat)
    if cmd == "/quick":
        return do_analyze(chat, arg, panel=False)
    if cmd == "/panel":
        return do_analyze(chat, arg, report=False)
    if cmd == "/analyze":
        return do_analyze(chat, arg)
    if cmd == "/tech":
        t = A.normalize_ticker(arg)
        return send(chat, A.format_technical(t, A.technical_summary(A.get_history(t))))
    if cmd == "/fund":
        return do_fund(chat, arg)
    if cmd == "/news":
        return send(chat, A.format_news(A.news_sentiment(A.normalize_ticker(arg))))
    if cmd == "/chart":
        t = A.normalize_ticker(arg)
        return send_photo(chat, A.make_chart(t, A.get_history(t)), t)
    if cmd.startswith("/"):
        return send(chat, "看不懂这个指令，发 /help 看看有什么功能。")
    return do_analyze(chat, text)  # 直接发股票代码


# ---------------------------------------------------------------------------

def main():
    if not TOKEN:
        raise SystemExit("缺少 TELEGRAM_BOT_TOKEN")
    ups = tg("getUpdates", timeout=0, allowed_updates='["message"]').get("result", [])
    if not ups:
        print("没有新消息")
        return
    # 先确认已读：就算下面某条处理出错，也不会下次重复处理
    tg("getUpdates", offset=max(u["update_id"] for u in ups) + 1, limit=1, timeout=0)
    print(f"收到 {len(ups)} 条消息")

    for u in ups:
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        text = (msg.get("text") or "").strip()
        if not chat or not text:
            continue
        if not ALLOWED:
            send(chat, f"⚙️ 机器人还没设置主人。你的 Chat ID 是 <code>{chat}</code>，"
                       "请把它填到 GitHub Secrets 的 TELEGRAM_CHAT_ID。")
            continue
        if str(chat) not in ALLOWED:
            send(chat, "🔒 这是私人机器人。")
            continue
        try:
            handle(chat, text)
        except Exception as e:
            print("处理失败：", e)
            send(chat, f"❌ 处理「{esc(text[:30])}」时出错：{esc(str(e))}")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", TOKEN)
    API = f"https://api.telegram.org/bot{TOKEN}"
    ALLOWED = {s.strip() for s in os.getenv("TELEGRAM_CHAT_ID", "").split(",") if s.strip()} or ALLOWED
    main()
