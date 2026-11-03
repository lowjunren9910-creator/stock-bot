"""
bot.py - Telegram 机器人入口。运行：python bot.py

直接发股票代码 → 数据报告 + 图表 + 5 位 AI 基金经理圆桌讨论 + 主席总结
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import analysis as A
import company as C
import klci as K
import screener as SC
import managers as M
import portfolio as P

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")

PANEL_NAMES = "、".join(f"{m['emoji']}{m['name']}（{m['title']}）" for m in M.MANAGERS)

HELP = f"""<b>📊 股票分析机器人</b>
市场：🇲🇾 大马 · 🇺🇸 美股 · 🇮🇩 印尼

<b>直接发股票代码</b>就会得到完整分析 + AI 基金经理圆桌讨论：
  <code>MAYBANK</code>、<code>1155</code>、<code>1155.KL</code>
  <code>AAPL</code>、<code>NVDA</code>
  <code>BBCA</code>、<code>TLKM.JK</code>

本期圆桌嘉宾：{PANEL_NAMES}

其他指令：
/company 代码 - 认识公司：业务、成绩、管理层 + 弱到强评级
/radar [bursa|idx|us] - 今日错杀股 / 成长股 / 双杀股
/klci - KLCI 50 最有机会入选的公司
/quick 代码 - 只看数据报告（不开圆桌，更快）
/panel 代码 - 只开基金经理圆桌
/tech、/fund、/news、/chart + 代码 - 单独看某一部分
/buy 1155.KL 1000 9.80 - 记录买入
/sell 1155.KL [数量] - 卖出（不写数量就全部清空）
/portfolio - 查看持股和实时盈亏
/myid - 查看你的 Chat ID（设置每日自动报告用）"""


async def send(update: Update, text: str):
    # Telegram 每条消息上限 4096 字
    for i in range(0, len(text), 4000):
        await update.message.reply_text(
            text[i:i + 4000], parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)


def need_ticker(ctx) -> str | None:
    return " ".join(ctx.args) if ctx.args else None


async def run_blocking(func, *args):
    """yfinance 是阻塞的，放到线程里跑，机器人才不会卡住。"""
    return await asyncio.to_thread(func, *args)


# --- 基金经理圆桌 -------------------------------------------------------------

async def run_panel(update: Update, snapshot: dict):
    await send(update, f"🎙 <b>基金经理圆桌开始</b>：{A._esc(snapshot['名称'])}\n"
                       f"{len(M.MANAGERS)} 位经理正在独立分析，谁先想好谁先发言…")
    await update.message.chat.send_action(ChatAction.TYPING)
    opinions = []
    async for o in M.run_panel(snapshot):
        opinions.append(o)
        await send(update, f"{o['emoji']} <b>{o['name']}｜{o['title']}</b>\n\n"
                           f"{A._esc(o['text'])}")
    await update.message.chat.send_action(ChatAction.TYPING)
    summary = await M.chairman_summary(snapshot, opinions)
    await send(update, f"👔 <b>投资委员会主席总结</b>\n\n{A._esc(summary)}\n\n"
                       "<i>以上为 AI 模拟观点，仅供学习参考，不构成投资建议。</i>")


# --- 指令处理 ----------------------------------------------------------------

async def company(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/company MAYBANK")
    await update.message.reply_text(f"⏳ 正在研究 {t.upper()}：业务、成绩、管理层…（约 20-40 秒）")
    try:
        p = await run_blocking(C.fetch, t)
    except Exception as e:
        return await send(update, f"❌ {A._esc(str(e))}")
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        ai = await C.ai_profile(p)
    except Exception as e:
        ai = None
        await send(update, f"⚠️ AI 研究员暂时无法工作（{A._esc(str(e))}），先给你财务体检。")
    await send(update, C.to_telegram_html(p, ai))


def _fresh(r: dict | None) -> bool:
    from datetime import date
    return bool(r) and r.get("date") == str(date.today())


async def radar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    market = (ctx.args[0].lower() if ctx.args else "bursa")
    if market not in SC.S.MARKETS:
        return await send(update, "用法：/radar [bursa|idx|us]（默认 bursa）")
    r = SC.latest(market)
    if not _fresh(r):
        await update.message.reply_text("⏳ 正在扫描错杀股 / 成长股 / 双杀股…（约 1-3 分钟）")
        try:
            r = await run_blocking(SC.screen, market)
            SC.save(r)
        except Exception as e:
            return await send(update, f"❌ {A._esc(str(e))}")
    await send(update, SC.to_telegram_html(r))


async def klci_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    r = K.latest()
    if not _fresh(r):
        await update.message.reply_text("⏳ 正在计算 KLCI 50 入选几率…（约 1-2 分钟）")
        try:
            r = await run_blocking(K.track)
            r["ai_comment"] = await run_blocking(K.ai_comment, r)
            K.save(r)
        except Exception as e:
            return await send(update, f"❌ {A._esc(str(e))}")
    await send(update, K.to_telegram_html(r))


async def myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """自动报告要推送到哪里？就是这个 chat id。"""
    await send(update, f"你的 Chat ID：<code>{update.effective_chat.id}</code>\n"
                       "把它填到 GitHub Secrets 的 TELEGRAM_CHAT_ID，就能收到每日市场报告。")


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await send(update, HELP)


async def analyze_text(update: Update, text: str, with_panel=True, with_report=True):
    await update.message.reply_text(f"⏳ 正在分析 {text.upper()}…")
    try:
        ticker, report, df, snapshot = await run_blocking(A.full_report, text)
    except Exception as e:
        logging.exception("analyze failed")
        return await send(update, f"❌ {A._esc(str(e))}")
    if with_report:
        await send(update, report)
        chart = await run_blocking(A.make_chart, ticker, df)
        await update.message.reply_photo(chart)
    if with_panel:
        await run_panel(update, snapshot)


async def analyze(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/analyze 1155.KL")
    await analyze_text(update, t)


async def quick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/quick AAPL")
    await analyze_text(update, t, with_panel=False)


async def panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/panel MAYBANK")
    await analyze_text(update, t, with_report=False)


async def plain_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await analyze_text(update, update.message.text)


async def tech(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/tech AAPL")
    try:
        ticker = A.normalize_ticker(t)
        df = await run_blocking(A.get_history, ticker)
        await send(update, A.format_technical(ticker, A.technical_summary(df)))
    except Exception as e:
        await send(update, f"❌ {A._esc(str(e))}")


async def fund(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/fund BBCA")
    try:
        ticker = A.normalize_ticker(t)
        df = await run_blocking(A.get_history, ticker, "5d")
        info = await run_blocking(A.get_info, ticker)
        f = await run_blocking(A.fundamental_summary, ticker, info,
                               float(df["Close"].iloc[-1]))
        await send(update, A.format_fundamental(f))
    except Exception as e:
        await send(update, f"❌ {A._esc(str(e))}")


async def news(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/news NVDA")
    n = await run_blocking(A.news_sentiment, A.normalize_ticker(t))
    await send(update, A.format_news(n))


async def chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t = need_ticker(ctx)
    if not t:
        return await send(update, "用法：/chart TENAGA")
    try:
        ticker = A.normalize_ticker(t)
        df = await run_blocking(A.get_history, ticker)
        img = await run_blocking(A.make_chart, ticker, df)
        await update.message.reply_photo(img, caption=ticker)
    except Exception as e:
        await send(update, f"❌ {A._esc(str(e))}")


async def buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        t, qty, price = ctx.args
        msg = P.buy(update.effective_user.id, A.normalize_ticker(t),
                    float(qty), float(price))
    except ValueError:
        msg = "用法：/buy 代码 数量 价格，例如 /buy 1155.KL 1000 9.80"
    await send(update, msg)


async def sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        return await send(update, "用法：/sell 1155.KL [数量]")
    try:
        qty = float(ctx.args[1]) if len(ctx.args) > 1 else None
    except ValueError:
        return await send(update, "数量要是数字，例如 /sell 1155.KL 500")
    await send(update, P.sell(update.effective_user.id,
                              A.normalize_ticker(ctx.args[0]), qty))


async def show_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ 正在获取最新股价…")
    await send(update, await run_blocking(P.report, update.effective_user.id))


def main():
    if not TOKEN:
        raise SystemExit("请先在 .env 文件里设置 TELEGRAM_BOT_TOKEN（见 README）。")
    err = M.check_setup()
    if err:
        raise SystemExit(err)
    logging.info(f"AI 供应商：{M.PROVIDER}，模型：{M.MODEL}")
    app = Application.builder().token(TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("company", company))
    app.add_handler(CommandHandler("radar", radar))
    app.add_handler(CommandHandler("klci", klci_cmd))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("quick", quick))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("tech", tech))
    app.add_handler(CommandHandler("fund", fund))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("sell", sell))
    app.add_handler(CommandHandler("portfolio", show_portfolio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, plain_message))
    logging.info("机器人运行中 - 按 Ctrl+C 停止")
    app.run_polling()


if __name__ == "__main__":
    main()
