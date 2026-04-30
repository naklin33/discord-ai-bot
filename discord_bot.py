"""
Discord AI Assistant Bot - 進階版 v2.0
功能：AI 對話、天氣、股票、新聞、每日晨報、翻譯、圖片分析、文件分析、提醒
"""

import os
import asyncio
import discord
from discord.ext import commands, tasks
from discord import app_commands
import anthropic
from dotenv import load_dotenv
import aiohttp
import feedparser
import datetime
import base64
import re
import json
import pytz
from icalendar import Calendar

load_dotenv()

# ── 設定 ──────────────────────────────────────────────
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SUMMARY_CHANNEL_ID = int(os.getenv("SUMMARY_CHANNEL_ID", "1498980534704017428"))
WEATHER_CITY = os.getenv("WEATHER_CITY", "Kaohsiung")

# Notion 整合
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID  = os.getenv("NOTION_DB_ID", "32b3dd73-128c-4ca1-880f-00c896953656")

# Google Calendar（私人 iCal 網址）
GCAL_ICAL_URL = os.getenv("GCAL_ICAL_URL", "")

# 台灣時區 UTC+8
TAIWAN_TZ = datetime.timezone(datetime.timedelta(hours=8))

# 用戶偏好檔案
USERS_FILE = "users.json"


# ── 用戶偏好管理 ──────────────────────────────────────
def load_users() -> dict:
    """載入用戶偏好設定"""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(data: dict):
    """儲存用戶偏好設定"""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_prefs(display_name: str) -> dict:
    """取得用戶偏好，若無則回傳預設值"""
    users = load_users()
    return users.get(display_name, {"語言": "繁體中文", "自動翻譯": True})


def set_user_pref(display_name: str, key: str, value):
    """更新單一用戶偏好"""
    users = load_users()
    if display_name not in users:
        users[display_name] = {"語言": "繁體中文", "自動翻譯": True}
    users[display_name][key] = value
    save_users(users)


def build_user_system_prompt(display_name: str) -> str:
    """根據用戶偏好建立個人化系統提示詞"""
    prefs = get_user_prefs(display_name)
    lang = prefs.get("語言", "繁體中文")
    auto_translate = prefs.get("自動翻譯", True)

    prompt = SYSTEM_PROMPT
    if lang:
        prompt += f"\n請一律使用「{lang}」回覆此用戶（{display_name}）。"
    if auto_translate:
        prompt += "\n若用戶以其他語言提問，仍以其偏好語言回覆，不需特別說明。"
    return prompt

# 股票清單
STOCKS = {
    "0056":  "元大高股息",
    "00878": "國泰永續高股息",
    "009816": "中信成長高股息",
}

# 關鍵字自動回覆
KEYWORD_REPLIES = {
    "你好": "你好！有什麼我可以幫你的嗎？😊",
    "hello": "Hello! How can I help you? 😊",
    "幫助": (
        "📋 **可用指令：**\n"
        "`/ask` 向 AI 提問\n"
        "`/weather` 高雄天氣預報\n"
        "`/stocks` 股票行情\n"
        "`/news` 最新新聞\n"
        "`/morning` 今日晨報\n"
        "`/translate` 翻譯\n"
        "`/remind` 設定提醒\n"
        "`/summary` 頻道摘要\n"
        "`/clear` 清除對話記憶\n\n"
        "也可以直接 **@私人AI助理** 並附上圖片或文件！"
    ),
}

# 系統提示詞
SYSTEM_PROMPT = """你是一個友善、聰明的 Discord 私人助理。
你的名字叫做「小助理」。
請用繁體中文回答，保持簡潔但有幫助。
在 Discord 中回覆時，適當使用 emoji 讓對話更生動。
你可以分析圖片和文件，提供翻譯，回答各種問題。"""

# ── Bot 初始化 ──────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
conversation_history: dict[int, list] = {}
pending_reminders: list = []


# ── 工具函式 ──────────────────────────────────────────
def get_ai_response(user_id: int, user_message: str, image_data: dict = None, display_name: str = "") -> str:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    if image_data:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image_data["media_type"],
                    "data": image_data["data"],
                },
            },
            {"type": "text", "text": user_message or "請描述這張圖片的內容"},
        ]
    else:
        content = user_message

    conversation_history[user_id].append({"role": "user", "content": content})
    recent = conversation_history[user_id][-10:]

    # 根據用戶偏好選擇系統提示詞
    system = build_user_system_prompt(display_name) if display_name else SYSTEM_PROMPT

    response = claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=system,
        messages=recent,
    )
    reply = response.content[0].text
    conversation_history[user_id].append({"role": "assistant", "content": reply})
    return reply


def split_message(text: str, limit: int = 2000) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def translate_titles_to_chinese(titles: list[str]) -> list[str]:
    """使用 Claude 將標題批次翻譯成繁體中文"""
    if not titles:
        return titles
    try:
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="你是專業翻譯員。將以下編號新聞標題翻譯成繁體中文，保持相同編號格式，只輸出翻譯結果，不加任何解釋或原文。",
            messages=[{"role": "user", "content": numbered}],
        )
        lines = [re.sub(r"^\d+\.\s*", "", l.strip()) for l in resp.content[0].text.strip().split("\n") if l.strip()]
        return lines if len(lines) == len(titles) else titles
    except Exception:
        return titles


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
                temp = cur["temp_C"]
                feels = cur["FeelsLikeC"]
                humidity = cur["humidity"]
                desc = cur["weatherDesc"][0]["value"]
                uv = cur.get("uvIndex", "N/A")

                forecast = data.get("weather", [])
                labels = ["今天", "明天", "後天"]
                fc_lines = []
                for i, day in enumerate(forecast[:3]):
                    mx = day["maxtempC"]
                    mn = day["mintempC"]
                    d = day["hourly"][4]["weatherDesc"][0]["value"]
                    fc_lines.append(f"  {labels[i]}：{mn}°~{mx}° {d}")

                return (
                    f"🌤️ **{area} 即時天氣**\n"
                    f"🌡️ 氣溫：{temp}°C（體感 {feels}°C）\n"
                    f"💧 濕度：{humidity}%　☀️ UV：{uv}\n"
                    f"📋 狀況：{desc}\n\n"
                    f"📅 **三日預報**\n" + "\n".join(fc_lines)
                )
    except Exception as e:
        return f"❌ 天氣資料取得失敗：{e}"


async def get_stock_prices() -> str:
    results = []
    try:
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
                        change = round(price - prev, 2) if price and prev else 0
                        pct = round(change / prev * 100, 2) if prev else 0
                        arrow = "📈" if change >= 0 else "📉"
                        sign = "+" if change >= 0 else ""
                        results.append(
                            f"{arrow} **{ticker} {name}**\n"
                            f"   現價：**{price:.2f}** 元　{sign}{change} ({sign}{pct}%)"
                        )
                except Exception:
                    results.append(f"⚠️ **{ticker} {name}**：資料取得失敗")
    except Exception as e:
        return f"❌ 股票查詢失敗：{e}"

    return "💹 **台股行情**\n" + "\n".join(results)


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

        def clean(title):
            return re.sub(r"\s*[-–]\s*[^-–]+$", "", title).strip()

        tw_lines = [f"• {clean(e.title)}" for e in tw_feed.entries[:3]]
        raw_intl = [clean(e.title) for e in intl_feed.entries[:3]]

        # 若開啟自動翻譯，將國際新聞英文標題翻譯成繁體中文
        if translate_intl:
            raw_intl = translate_titles_to_chinese(raw_intl)

        intl_lines = [f"• {t}" for t in raw_intl]
        emoji = {"綜合": "📰", "財經": "💰", "科技": "💻"}.get(category, "📰")

        return (
            f"{emoji} **{category}新聞**\n"
            f"🇹🇼 國內：\n" + "\n".join(tw_lines) + "\n"
            f"🌍 國際（已翻譯）：\n" + "\n".join(intl_lines)
            if translate_intl else
            f"{emoji} **{category}新聞**\n"
            f"🇹🇼 國內：\n" + "\n".join(tw_lines) + "\n"
            f"🌍 國際：\n" + "\n".join(intl_lines)
        )
    except Exception as e:
        return f"❌ 新聞取得失敗：{e}"


async def get_notion_todos() -> str:
    """從 Notion 取得待處理 / 處理中的待辦事項"""
    if not NOTION_TOKEN:
        return ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                headers={
                    "Authorization": f"Bearer {NOTION_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={
                    "filter": {
                        "or": [
                            {"property": "狀態", "select": {"equals": "📌 待處理"}},
                            {"property": "狀態", "select": {"equals": "🔄 處理中"}},
                        ]
                    },
                    "sorts": [{"property": "截止日期", "direction": "ascending"}],
                    "page_size": 10,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                results = data.get("results", [])
                if not results:
                    return "📝 **今日待辦 (Notion)**\n• 沒有待辦事項，今天辛苦了！🎉"
                lines = []
                for page in results:
                    props = page.get("properties", {})
                    title_rich = props.get("待辦事項", {}).get("title", [])
                    title = title_rich[0]["plain_text"] if title_rich else "（無標題）"
                    status_obj = props.get("狀態", {}).get("select") or {}
                    status = status_obj.get("name", "")
                    due_obj = props.get("截止日期", {}).get("date") or {}
                    due_str = f"  ⏰ {due_obj['start']}" if due_obj.get("start") else ""
                    lines.append(f"• {status} {title}{due_str}")
                return "📝 **今日待辦 (Notion)**\n" + "\n".join(lines)
    except Exception as e:
        return f"📝 **今日待辦 (Notion)**\n• 取得失敗：{e}"


async def get_calendar_events() -> str:
    """從 Google Calendar 私人 iCal 網址取得今日行程"""
    if not GCAL_ICAL_URL:
        return ""
    try:
        tz_taipei = pytz.timezone("Asia/Taipei")
        today = datetime.datetime.now(tz_taipei).date()
        async with aiohttp.ClientSession() as session:
            async with session.get(
                GCAL_ICAL_URL,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                ical_data = await resp.read()
        cal = Calendar.from_ical(ical_data)
        events = []
        for component in cal.walk():
            if component.name != "VEVENT":
                continue
            summary = str(component.get("SUMMARY", "（無標題）"))
            dtstart = component.get("DTSTART")
            if dtstart is None:
                continue
            dt_val = dtstart.dt
            # 全天事件是 date 型別；有時間的事件是 datetime
            if isinstance(dt_val, datetime.datetime):
                if dt_val.tzinfo is None:
                    dt_val = pytz.utc.localize(dt_val)
                dt_local = dt_val.astimezone(tz_taipei)
                if dt_local.date() == today:
                    events.append((dt_local, summary, False))
            elif isinstance(dt_val, datetime.date):
                if dt_val == today:
                    events.append((dt_val, summary, True))
        if not events:
            return "📅 **今日行程 (Google Calendar)**\n• 今天沒有行程，放鬆一下！😊"
        events.sort(key=lambda x: (x[2], x[0] if not x[2] else datetime.datetime.min))
        lines = []
        for dt_val, title, all_day in events:
            if all_day:
                lines.append(f"• 📆 {title}（全天）")
            else:
                lines.append(f"• {dt_val.strftime('%H:%M')} {title}")
        return "📅 **今日行程 (Google Calendar)**\n" + "\n".join(lines)
    except Exception as e:
        return f"📅 **今日行程 (Google Calendar)**\n• 取得失敗：{e}"


async def build_morning_summary() -> str:
    now = datetime.datetime.now(TAIWAN_TZ)
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    date_str = f"{now.strftime('%Y/%m/%d')} {weekdays[now.weekday()]}"

    # 並行取得所有資料，加速晨報生成
    (
        weather,
        stocks,
        news_gen,
        news_fin,
        news_tech,
        notion_todos,
        calendar_events,
    ) = await asyncio.gather(
        get_weather(),
        get_stock_prices(),
        get_news("綜合", translate_intl=True),
        get_news("財經", translate_intl=True),
        get_news("科技", translate_intl=True),
        get_notion_todos(),
        get_calendar_events(),
    )

    divider = f"\n{'─'*32}\n\n"
    sections = [
        f"🌅 **早安！今日晨報 {date_str}**\n{'─'*32}\n",
        weather,
        stocks,
    ]

    # 加入行程與待辦（如有設定就顯示）
    if calendar_events:
        sections.append(calendar_events)
    if notion_todos:
        sections.append(notion_todos)

    sections += [news_gen, news_fin, news_tech]

    return divider.join(sections) + f"\n{'─'*32}\nHave a productive day! 💪✨"


# ── 排程任務 ──────────────────────────────────────────
@tasks.loop(time=datetime.time(hour=8, minute=0, tzinfo=TAIWAN_TZ))
async def morning_task():
    channel = bot.get_channel(SUMMARY_CHANNEL_ID)
    if channel:
        summary = await build_morning_summary()
        for chunk in split_message(summary):
            await channel.send(chunk)


@tasks.loop(minutes=1)
async def reminder_task():
    now = datetime.datetime.now(TAIWAN_TZ)
    done = []
    for r in pending_reminders:
        if now >= r["time"]:
            ch = bot.get_channel(r["channel_id"])
            if ch:
                await ch.send(f"⏰ <@{r['user_id']}> 提醒：**{r['message']}**")
            done.append(r)
    for r in done:
        pending_reminders.remove(r)


# ── 事件處理 ──────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Bot 已上線：{bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ 同步了 {len(synced)} 個斜線指令")
    except Exception as e:
        print(f"❌ 同步失敗：{e}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="/ask 來提問")
    )
    morning_task.start()
    reminder_task.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    content = message.content.strip()

    if not content.startswith("/") and not content.startswith("!"):
        for kw, reply in KEYWORD_REPLIES.items():
            if kw.lower() in content.lower():
                await message.reply(reply)
                return

    if bot.user in message.mentions:
        clean = content.replace(f"<@{bot.user.id}>", "").strip()
        async with message.channel.typing():
            try:
                image_data = None
                for att in message.attachments:
                    ct = att.content_type or ""
                    if ct.startswith("image/"):
                        img_bytes = await att.read()
                        image_data = {
                            "media_type": ct.split(";")[0],
                            "data": base64.b64encode(img_bytes).decode(),
                        }
                        break
                    elif att.filename.endswith((".txt", ".md", ".csv", ".json", ".py", ".js", ".html")):
                        doc = (await att.read()).decode("utf-8", errors="ignore")
                        clean = f"請分析以下文件：\n\n{doc[:3000]}\n\n{clean}"
                        break

                if clean or image_data:
                    reply = get_ai_response(message.author.id, clean, image_data, message.author.display_name)
                    for chunk in split_message(reply):
                        await message.reply(chunk)
            except Exception as e:
                await message.reply(f"❌ 錯誤：{e}")
        return

    await bot.process_commands(message)


# ── 斜線指令 ──────────────────────────────────────────
@bot.tree.command(name="ask", description="向 AI 助理提問")
@app_commands.describe(問題="你想問什麼？")
async def ask(interaction: discord.Interaction, 問題: str):
    await interaction.response.defer(thinking=True)
    try:
        reply = get_ai_response(interaction.user.id, 問題, display_name=interaction.user.display_name)
        chunks = split_message(reply)
        await interaction.followup.send(chunks[0])
        for c in chunks[1:]:
            await interaction.channel.send(c)
    except Exception as e:
        await interaction.followup.send(f"❌ 錯誤：{e}")


@bot.tree.command(name="weather", description="查詢高雄即時天氣與三日預報")
async def weather_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await get_weather())


@bot.tree.command(name="stocks", description="查詢 0056、00878、009816 股票行情")
async def stocks_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await get_stock_prices())


@bot.tree.command(name="news", description="查看最新新聞（國內外各 3 則）")
@app_commands.describe(類別="新聞類別")
@app_commands.choices(
    類別=[
        app_commands.Choice(name="綜合頭條", value="綜合"),
        app_commands.Choice(name="財經", value="財經"),
        app_commands.Choice(name="科技", value="科技"),
    ]
)
async def news_cmd(interaction: discord.Interaction, 類別: str = "綜合"):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await get_news(類別))


@bot.tree.command(name="morning", description="立即取得今日晨報（天氣＋股票＋新聞）")
async def morning_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    summary = await build_morning_summary()
    chunks = split_message(summary)
    await interaction.followup.send(chunks[0])
    for c in chunks[1:]:
        await interaction.channel.send(c)


@bot.tree.command(name="translate", description="翻譯文字")
@app_commands.describe(文字="要翻譯的文字", 語言="目標語言（預設英文）")
async def translate_cmd(interaction: discord.Interaction, 文字: str, 語言: str = "英文"):
    await interaction.response.defer(thinking=True)
    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="你是專業翻譯員，只輸出翻譯結果，不加任何解釋。",
            messages=[{"role": "user", "content": f"翻譯成{語言}：{文字}"}],
        )
        await interaction.followup.send(f"🌐 **→ {語言}**\n{resp.content[0].text}")
    except Exception as e:
        await interaction.followup.send(f"❌ 翻譯失敗：{e}")


@bot.tree.command(name="remind", description="設定倒數提醒")
@app_commands.describe(分鐘="幾分鐘後提醒", 內容="提醒內容")
async def remind_cmd(interaction: discord.Interaction, 分鐘: int, 內容: str):
    t = datetime.datetime.now(TAIWAN_TZ) + datetime.timedelta(minutes=分鐘)
    pending_reminders.append({
        "time": t,
        "message": 內容,
        "channel_id": interaction.channel_id,
        "user_id": interaction.user.id,
    })
    await interaction.response.send_message(
        f"⏰ **{分鐘} 分鐘後**提醒你：{內容}", ephemeral=True
    )


@bot.tree.command(name="clear", description="清除與 AI 的對話記憶")
async def clear_cmd(interaction: discord.Interaction):
    if interaction.user.id in conversation_history:
        conversation_history.pop(interaction.user.id)
        await interaction.response.send_message("🗑️ 已清除對話記憶！", ephemeral=True)
    else:
        await interaction.response.send_message("目前沒有對話記憶。", ephemeral=True)


@bot.tree.command(name="summary", description="摘要此頻道最近的訊息")
@app_commands.describe(數量="訊息數量（預設 20，最多 50）")
async def summary_cmd(interaction: discord.Interaction, 數量: int = 20):
    await interaction.response.defer(thinking=True)
    數量 = min(數量, 50)
    try:
        msgs = []
        async for m in interaction.channel.history(limit=數量 + 1):
            if not m.author.bot:
                msgs.append(f"{m.author.display_name}: {m.content}")
        msgs.reverse()
        if not msgs:
            await interaction.followup.send("❌ 找不到可摘要的訊息。")
            return
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"請用繁體中文條列摘要：\n\n{chr(10).join(msgs)}"}],
        )
        reply = f"📋 **最近 {數量} 則訊息摘要：**\n\n{resp.content[0].text}"
        chunks = split_message(reply)
        await interaction.followup.send(chunks[0])
        for c in chunks[1:]:
            await interaction.channel.send(c)
    except Exception as e:
        await interaction.followup.send(f"❌ 摘要失敗：{e}")


@bot.tree.command(name="profile", description="查看你的個人偏好設定")
async def profile_cmd(interaction: discord.Interaction):
    name = interaction.user.display_name
    prefs = get_user_prefs(name)
    lang = prefs.get("語言", "繁體中文")
    auto_tr = "✅ 開啟" if prefs.get("自動翻譯", True) else "❌ 關閉"
    await interaction.response.send_message(
        f"👤 **{name} 的偏好設定**\n"
        f"🌐 回覆語言：**{lang}**\n"
        f"🔄 自動翻譯：**{auto_tr}**\n\n"
        f"使用 `/setlang` 更改語言，`/autotranslate` 切換自動翻譯",
        ephemeral=True,
    )


@bot.tree.command(name="setlang", description="設定 AI 回覆語言")
@app_commands.describe(語言="偏好的回覆語言（例如：繁體中文、English、日本語）")
async def setlang_cmd(interaction: discord.Interaction, 語言: str):
    name = interaction.user.display_name
    set_user_pref(name, "語言", 語言)
    await interaction.response.send_message(
        f"✅ 已將你的回覆語言設為：**{語言}**", ephemeral=True
    )


@bot.tree.command(name="autotranslate", description="切換自動翻譯（開/關）")
async def autotranslate_cmd(interaction: discord.Interaction):
    name = interaction.user.display_name
    prefs = get_user_prefs(name)
    current = prefs.get("自動翻譯", True)
    new_val = not current
    set_user_pref(name, "自動翻譯", new_val)
    status = "✅ 已開啟" if new_val else "❌ 已關閉"
    await interaction.response.send_message(
        f"🔄 自動翻譯：**{status}**", ephemeral=True
    )


@bot.tree.command(name="keyword", description="查看關鍵字自動回覆清單")
async def keyword_cmd(interaction: discord.Interaction):
    lines = ["🔑 **關鍵字自動回覆清單：**\n"]
    for kw, r in KEYWORD_REPLIES.items():
        lines.append(f"• `{kw}` → {str(r)[:50]}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# ── 啟動 ──────────────────────────────────────────────
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("❌ 缺少 DISCORD_TOKEN，請設定環境變數")
    if not ANTHROPIC_API_KEY:
        raise ValueError("❌ 缺少 ANTHROPIC_API_KEY，請設定環境變數")
    bot.run(DISCORD_TOKEN)
