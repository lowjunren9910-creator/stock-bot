"""
managers.py - AI 基金经理圆桌会议

每位"基金经理"都是一个独立的 AI agent，有自己的投资风格。
它们拿到同一份股票数据（技术面 + 基本面 + 新闻），各自独立给出：
  评级 / 当前看法 / 未来前景 / 关键风险 / 操作建议
最后由"投资委员会主席"汇总各方意见。

想加新风格？在 MANAGERS 列表里加一个 dict 就行。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date

from dotenv import load_dotenv

load_dotenv()  # 先读 .env，下面才拿得到 AI_PROVIDER

# ---------------------------------------------------------------------------
# 0. AI 供应商设置 —— 在 .env 里改 AI_PROVIDER 就能切换，不用改代码
# ---------------------------------------------------------------------------
#   groq   : 免费，速度快（默认）       需要 GROQ_API_KEY
#   gemini : 免费额度，华文不错         需要 GEMINI_API_KEY
#   ollama : 本地运行，100% 免费        需要先装 Ollama
#   claude : 付费，分析质量最好         需要 ANTHROPIC_API_KEY

PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "key_env": "GEMINI_API_KEY", "model": "gemini-3.8-flash"},
    "ollama": {"base_url": "http://localhost:11434/v1",
               "key_env": None, "model": "qwen3:8b"},
    "claude": {"base_url": None,
               "key_env": "ANTHROPIC_API_KEY", "model": "claude-haiku-5-5"},
}

PROVIDER = os.getenv("AI_PROVIDER", "groq").lower()
if PROVIDER not in PROVIDERS:
    raise SystemExit(f"AI_PROVIDER 只能是：{', '.join(PROVIDERS)}")
CFG = PROVIDERS[PROVIDER]
MODEL = os.getenv("AI_MODEL") or CFG["model"]

_client = None


def check_setup() -> str | None:
    """返回错误信息；没问题就返回 None。"""
    if CFG["key_env"] and not os.getenv(CFG["key_env"]):
        return f"你选了 AI_PROVIDER={PROVIDER}，请在 .env 里设置 {CFG['key_env']}。"
    return None


def client():
    global _client
    if _client is None:
        if PROVIDER == "claude":
            from anthropic import AsyncAnthropic
            _client = AsyncAnthropic()
        else:  # Groq / Gemini / Ollama 都兼容 OpenAI 的接口格式
            from openai import AsyncOpenAI
            key = os.getenv(CFG["key_env"]) if CFG["key_env"] else "ollama"
            _client = AsyncOpenAI(api_key=key, base_url=CFG["base_url"])
    return _client


async def chat(system: str, user: str, max_tokens: int = 700) -> str:
    """统一的 AI 调用：不管用哪家，都是丢 system + user，拿回文字。"""
    if PROVIDER == "claude":
        resp = await client().messages.create(
            model=MODEL, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in resp.content if b.type == "text")
    else:
        resp = await client().chat.completions.create(
            model=MODEL,
            # 有些免费模型会先"思考"，思考也算 token，所以给多一点空间
            max_tokens=max_tokens * 3,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}])
        text = resp.choices[0].message.content or ""
    # 有些模型会输出 <think>...</think> 思考过程，去掉
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    return text.replace("**", "").strip()


# ---------------------------------------------------------------------------
# 1. 基金经理人设
# ---------------------------------------------------------------------------

MANAGERS = [
    {
        "id": "value",
        "name": "老陈",
        "title": "价值投资派",
        "emoji": "🧓",
        "style": (
            "你是一位有 30 年经验的价值投资基金经理，信奉'用合理价格买入好公司并长期持有'。"
            "你最看重：护城河、ROE、负债水平、估值（P/E、P/B）、股息和管理层。"
            "你对短期股价波动和技术指标不太在意，讨厌炒作和过高估值。说话沉稳、保守、爱讲道理。"
        ),
    },
    {
        "id": "growth",
        "name": "Kelly",
        "title": "成长股猎手",
        "emoji": "🚀",
        "style": (
            "你是一位进取型成长股基金经理，专找未来 3-5 年营收和利润能高速增长的公司。"
            "你最看重：营收增长率、行业趋势（AI、能源转型、数字化等）、市场份额扩张。"
            "你可以接受高估值，只要增长够快；但讨厌增长停滞的公司。说话乐观、有冲劲。"
        ),
    },
    {
        "id": "technical",
        "name": "阿杰",
        "title": "技术派交易员",
        "emoji": "📊",
        "style": (
            "你是一位短中线技术派交易员，只相信价格和趋势。"
            "你最看重：均线（SMA50/200）、RSI、MACD、52 周高低位、动能和支撑阻力。"
            "你会给出具体的进场区、止损位和目标位（以数据中的价格为基础）。说话直接、简短、讲纪律。"
        ),
    },
    {
        "id": "dividend",
        "name": "Auntie Lim",
        "title": "收息派老手",
        "emoji": "💰",
        "style": (
            "你是一位专注东南亚市场（大马、印尼）的收息型基金经理，客户多是退休人士。"
            "你最看重：股息率是否稳定、派息能力、现金流、公司是否抗跌，以及本地政策和宏观环境。"
            "对美股你会从'能不能长期稳定拿钱'的角度看。说话亲切、务实，常提醒风险。"
        ),
    },
    {
        "id": "bear",
        "name": "冷面周",
        "title": "风控官·唱反调",
        "emoji": "🐻",
        "style": (
            "你是基金公司的风险控制官，职责就是唱反调，找出别人忽略的风险。"
            "你最看重：估值泡沫、负债、盈利下滑、行业逆风、宏观风险（利率、汇率、地缘政治）、负面新闻。"
            "你不是一味看空——如果真的没大问题你也会承认，但一定要指出最大的下行风险。说话冷静、犀利。"
        ),
    },
]

OUTPUT_FORMAT = """请用简体中文回答，严格按照下面格式，不要用 Markdown（不要 **、#），总字数 250 字以内：

【评级】从这五个选一个：强烈买入 / 买入 / 持有 / 减持 / 卖出
【当前看法】2-3 句，结合数据说明你怎么看现在这只股票
【未来前景】2-3 句，未来 6-12 个月你预期会怎样，为什么
【关键风险】1-2 点
【我会怎么做】1-2 句具体操作建议"""

RATINGS = ["强烈买入", "买入", "持有", "减持", "卖出"]


def _system_prompt(m: dict) -> str:
    return (
        f"{m['style']}\n\n"
        f"今天是 {date.today():%Y年%m月%d日}。你会收到一份股票数据快照。"
        "请主要依据这份数据，结合你对该公司和行业的一般认识来分析；"
        "如果数据不足或你不确定，就直接说明，不要编造具体数字或新闻。"
        "你是在一个学习用的模拟投资委员会里发言，不构成真实投资建议。\n\n"
        + OUTPUT_FORMAT
    )


# ---------------------------------------------------------------------------
# 2. 调用 AI
# ---------------------------------------------------------------------------

async def ask_manager(m: dict, snapshot: dict) -> dict:
    data = json.dumps(snapshot, ensure_ascii=False, default=str, indent=1)
    try:
        text = await chat(_system_prompt(m), f"请分析这只股票：\n{data}")
    except Exception as e:
        text = f"（{m['name']} 暂时无法发言：{e}）"
    return {**m, "text": text, "rating": parse_rating(text)}


def parse_rating(text: str) -> str | None:
    match = re.search(r"【评级】\s*([^\n]+)", text)
    if not match:
        return None
    line = match.group(1)
    for r in RATINGS:  # "强烈买入" 要排在 "买入" 前面匹配
        if r in line:
            return r
    return None


async def run_panel(snapshot: dict):
    """并行询问所有基金经理，谁先答完谁先输出（async generator）。"""
    tasks = [asyncio.create_task(ask_manager(m, snapshot)) for m in MANAGERS]
    for fut in asyncio.as_completed(tasks):
        yield await fut


async def chairman_summary(snapshot: dict, opinions: list[dict]) -> str:
    votes = {r: 0 for r in RATINGS}
    for o in opinions:
        if o["rating"]:
            votes[o["rating"]] += 1
    tally = "  ".join(f"{r} {n}" for r, n in votes.items() if n)

    transcript = "\n\n".join(
        f"{o['name']}（{o['title']}）：\n{o['text']}" for o in opinions)
    try:
        text = await chat(
            "你是投资委员会主席，负责总结各基金经理的意见。用简体中文，不要用 Markdown，200 字以内。"
            "格式：\n【共识】大家意见一致的地方\n【分歧】主要争论点\n"
            "【综合结论】给出委员会整体倾向（看多/中性/看空）和一句话理由\n"
            "【适合什么人】这只股票比较适合哪种投资者",
            f"股票：{snapshot.get('名称')}（{snapshot.get('代码')}）\n"
            f"投票：{tally}\n\n各经理意见：\n{transcript}",
            max_tokens=600)
    except Exception as e:
        text = f"（主席总结失败：{e}）"
    return f"🗳 投票：{tally or '无'}\n\n{text}"
