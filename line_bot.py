"""Line AI Assistant Bot
與 Discord bot 共用 shared/ 模組（使用者偏好、使用統計皆寫入同一份 SQLite）
"""
import os
import asyncio
import datetime
import re

import anthropic
from dotenv import load_dotenv
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from shared import storage, users as user_store, stats

load_dotenv()
storage.init_db()

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
PORT = int(os.getenv("LINE_PORT", "8080"))

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    raise ValueError("❌ 缺少 LINE_CHANNEL_SECRET 或 LINE_CHANNEL_ACCESS_TOKEN")
if not ANTHROPIC_API_KEY:
    raise ValueError("❌ 缺少 ANTHROPIC_API_KEY")

TAIWAN_TZ = datetime.timezone(datetime.timedelta(hours=8))

app = Flask(__name__)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
line_config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 對話記憶（記憶體；重啟會清空，與 Discord bot 行為一致）
conversation_history: dict[str, list] = {}

SYSTEM_PROMPT = """你是一個友善、聰明的 Line 私人助理。
你的名字叫做「小助理」。
請用繁體中文回答，保持簡潔但有幫助。
你可以提供翻譯、天氣、股票、新聞、回答各種問題。"""


# ── 共用：依使用者偏好建立 system prompt ──────────────
def build_user_system_prompt(display_name: str) -> str:
    prefs = user_store.get_user_prefs(display_name)
    lang = prefs.get("語言", "繁體中文")
    auto_translate = prefs.get("自動翻譯", True)
    prompt = SYSTEM_PROMPT
    if lang:
        prompt += f"\n請一律使用「{lang}」回覆此用戶（{display_name}）。"
    if auto_translate:
        prompt += "\n若用戶以其他語言提問，仍以其偏好語言回覆，不需特別說明。"
    return prompt


def ai_reply(user_key: str, display_name: str, text: str) -> str:
    history = conversation_history.setdefault(user_key, [])
    history.append({"role": "user", "content": text})
    recent = history[-10:]
    resp = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=build_user_system_prompt(display_name),
        messages=recent,
    )
    reply = resp.content[0].text
    history.append({"role": "assistant", "content": reply})
    return reply


# ── 指令解析（Line 沒有 slash command，靠關鍵字前綴）────
COMMAND_HELP = (
    "📋 **可用指令：**\n"
    "/天氣 - 高雄天氣\n"
    "/股票 - 0056、00878、009816\n"
    "/新聞 [綜合|財經|科技]\n"
    "/晨報 - 今日晨報\n"
    "/翻譯 <文字> | <語言>\n"
    "/設定語言 <語言>\n"
    "/自動翻譯 - 切換開關\n"
    "/個人 - 查看偏好\n"
    "/統計 - 跨平台使用統計\n"
    "/清除 - 清除對話記憶\n"
    "其他訊息會直接交給 AI 回答。"
)


def handle_command(user_key: str, display_name: str, text: str) -> str | None:
    """回傳要回覆的內容；若不是指令則回傳 None 讓 AI 接手"""
    t = text.strip()
    if t in ("/help", "/幫助", "幫助"):
        return COMMAND_HELP

    if t == "/個人":
        prefs = user_store.get_user_prefs(display_name)
        auto = "✅ 開啟" if prefs.get("自動翻譯", True) else "❌ 關閉"
        return (
            f"👤 {display_name} 的偏好\n"
            f"🌐 語言：{prefs.get('語言', '繁體中文')}\n"
            f"🔄 自動翻譯：{auto}"
        )

    if t == "/統計":
        summary = stats.user_summary(display_name=display_name)
        return stats.format_summary(summary, display_name)

    if t == "/自動翻譯":
        prefs = user_store.get_user_prefs(display_name)
        new_val = not prefs.get("自動翻譯", True)
        user_store.set_user_pref(display_name, "自動翻譯", new_val)
        return f"🔄 自動翻譯：{'✅ 已開啟' if new_val else '❌ 已關閉'}"

    if t.startswith("/設定語言"):
        lang = t.replace("/設定語言", "", 1).strip()
        if not lang:
            return "用法：/設定語言 繁體中文"
        user_store.set_user_pref(display_name, "語言", lang)
        return f"✅ 已將回覆語言設為：{lang}"

    if t == "/清除":
        conversation_history.pop(user_key, None)
        return "🗑️ 已清除對話記憶！"

    if t == "/天氣":
        return asyncio.run(get_weather())

    if t == "/股票":
        return asyncio.run(get_stock_prices())

    if t.startswith("/新聞"):
        cat = t.replace("/新聞", "", 1).strip() or "綜合"
        if cat not in ("綜合", "財經", "科技"):
            cat = "綜合"
        return asyncio.run(get_news(cat, translate_intl=True))

    if t == "/晨報":
        return asyncio.run(build_morning_summary())

    if t.startswith("/翻譯"):
        body = t.replace("/翻譯", "", 1).strip()
        if "|" in body:
            text_part, lang = [s.strip() for s in body.split("|", 1)]
        else:
            text_part, lang = body, "英文"
        if not text_part:
            return "用法：/翻譯 你好 | English"
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="你是專業翻譯員，只輸出翻譯結果，不加任何解釋。",
            messages=[{"role": "user", "content": f"翻譯成{lang}：{text_part}"}],
        )
        return f"🌐 → {lang}\n{resp.content[0].text}"

    return None


# ── 對應 discord_bot 的網路函式（簡化版）────────────────
import aiohttp
import feedparser

WEATHER_CITY = os.getenv("WEATHER_CITY", "Kaohsiung")
STOCKS = {"0056": "元大高股息", "00878": "國泰永續高股息", "009816": "中信成長高股息"}


async def get_weather() -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://wttr.in/{WEATHER_CITY}?format=j1",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
                cur = data["current_condition"][0]
                area = data["nearest_area"][0]["areaName"][0]["value"]
                return (
                    f"🌤️ {area}\n"
                    f"🌡️ {cur['temp_C']}°C（體感 {cur['FeelsLikeC']}°C）\n"
                    f"💧 濕度 {cur['humidity']}%\n"
                    f"📋 {cur['weatherDesc'][0]['value']}"
                )
    except Exception as e:
        return f"❌ 天氣失敗：{e}"


async def get_stock_prices() -> str:
    out = []
    async with aiohttp.ClientSession() as session:
        for ticker, name in STOCKS.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}.TW"
                async with session.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    meta = data["chart"]["result"][0]["meta"]
                    price = meta.get("regularMarketPrice", 0)
                    prev = meta.get("previousClose", 0)
                    change = round(price - prev, 2)
                    pct = round(change / prev * 100, 2) if prev else 0
                    arrow = "📈" if change >= 0 else "📉"
                    out.append(f"{arrow} {ticker} {name} {price:.2f} ({change:+}/{pct:+}%)")
            except Exception:
                out.append(f"⚠️ {ticker} 取得失敗")
    return "💹 台股\n" + "\n".join(out)


def _clean_title(title: str) -> str:
    return re.sub(r"\s*[-–]\s*[^-–]+$", "", title).strip()


def translate_titles(titles: list[str]) -> list[str]:
    if not titles:
        return titles
    try:
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="將以下編號新聞標題翻譯成繁體中文，保持相同編號，只輸出翻譯。",
            messages=[{"role": "user", "content": numbered}],
        )
        lines = [re.sub(r"^\d+\.\s*", "", l.strip()) for l in resp.content[0].text.strip().split("\n") if l.strip()]
        return lines if len(lines) == len(titles) else titles
    except Exception:
        return titles


async def get_news(category: str = "綜合", translate_intl: bool = False) -> str:
    tw_urls = {
        "綜合": "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "財經": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtcFVHZ0pVVWlnQVAB?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "科技": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtcFVHZ0pVVWlnQVAB?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    }
    intl_urls = {
        "綜合": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "財經": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
        "科技": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    }
    try:
        tw_feed = feedparser.parse(tw_urls.get(category, tw_urls["綜合"]))
        intl_feed = feedparser.parse(intl_urls.get(category, intl_urls["綜合"]))
        tw_lines = [f"• {_clean_title(e.title)}" for e in tw_feed.entries[:3]]
        raw_intl = [_clean_title(e.title) for e in intl_feed.entries[:3]]
        if translate_intl:
            raw_intl = translate_titles(raw_intl)
        intl_lines = [f"• {t}" for t in raw_intl]
        return (
            f"📰 {category}\n"
            f"🇹🇼 國內：\n" + "\n".join(tw_lines) + "\n"
            f"🌍 國際：\n" + "\n".join(intl_lines)
        )
    except Exception as e:
        return f"❌ 新聞失敗：{e}"


async def build_morning_summary() -> str:
    now = datetime.datetime.now(TAIWAN_TZ)
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    date_str = f"{now.strftime('%Y/%m/%d')} {weekdays[now.weekday()]}"
    weather, stocks_text, news_gen = await asyncio.gather(
        get_weather(), get_stock_prices(), get_news("綜合", translate_intl=True)
    )
    return f"🌅 早安！{date_str}\n\n{weather}\n\n{stocks_text}\n\n{news_gen}"


# ── Line webhook ─────────────────────────────────────────
def _get_display_name(api: MessagingApi, user_id: str) -> str:
    """嘗試取得 Line 使用者名稱；失敗就用 userId 後 6 碼"""
    try:
        profile = api.get_profile(user_id)
        return profile.display_name
    except Exception:
        return f"line-{user_id[-6:]}"


@handler.add(MessageEvent, message=TextMessageContent)
def on_message(event: MessageEvent):
    user_id = event.source.user_id
    text = event.message.text

    with ApiClient(line_config) as api_client:
        api = MessagingApi(api_client)
        display_name = _get_display_name(api, user_id)

        cmd_reply = handle_command(user_id, display_name, text)
        if cmd_reply is not None:
            command_name = text.strip().split()[0].lstrip("/") or "command"
            stats.log_usage("line", user_id, command_name, display_name)
            reply_text = cmd_reply
        else:
            stats.log_usage("line", user_id, "mention", display_name)
            try:
                reply_text = ai_reply(user_id, display_name, text)
            except Exception as e:
                reply_text = f"❌ 錯誤：{e}"

        # Line 單則訊息上限 5000 字
        api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text[:5000])],
            )
        )


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
