"""
Discord AI Assistant Bot - é²éç v2.0
åè½ï¼AI å°è©±ãå¤©æ°£ãè¡ç¥¨ãæ°èãæ¯æ¥æ¨å ±ãç¿»è­¯ãåçåæãæä»¶åæãæé
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

# ââ è¨­å® ââââââââââââââââââââââââââââââââââââââââââââââ
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SUMMARY_CHANNEL_ID = int(os.getenv("SUMMARY_CHANNEL_ID", "1498980534704017428"))
WEATHER_CITY = os.getenv("WEATHER_CITY", "Kaohsiung")

# Notion æ´å
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_DB_ID  = os.getenv("NOTION_DB_ID", "32b3dd73-128c-4ca1-880f-00c896953656")

# Google Calendarï¼ç§äºº iCal ç¶²åï¼
GCAL_ICAL_URL = os.getenv("GCAL_ICAL_URL", "")

# å°ç£æå UTC+8
TAIWAN_TZ = datetime.timezone(datetime.timedelta(hours=8))

# ç¨æ¶åå¥½æªæ¡
USERS_FILE = "users.json"


# ââ ç¨æ¶åå¥½ç®¡ç ââââââââââââââââââââââââââââââââââââââ
def load_users() -> dict:
    """è¼å¥ç¨æ¶åå¥½è¨­å®"""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_users(data: dict):
    """å²å­ç¨æ¶åå¥½è¨­å®"""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_prefs(display_name: str) -> dict:
    """åå¾ç¨æ¶åå¥½ï¼è¥ç¡ååå³é è¨­å¼"""
    users = load_users()
    return users.get(display_name, {"èªè¨": "ç¹é«ä¸­æ", "èªåç¿»è­¯": True})


def set_user_pref(display_name: str, key: str, value):
    """æ´æ°å®ä¸ç¨æ¶åå¥½"""
    users = load_users()
    if display_name not in users:
        users[display_name] = {"èªè¨": "ç¹é«ä¸­æ", "èªåç¿»è­¯": True}
    users[display_name][key] = value
    save_users(users)


def build_user_system_prompt(display_name: str) -> str:
    """æ ¹æç¨æ¶åå¥½å»ºç«åäººåç³»çµ±æç¤ºè©"""
    prefs = get_user_prefs(display_name)
    lang = prefs.get("èªè¨", "ç¹é«ä¸­æ")
    auto_translate = prefs.get("èªåç¿»è­¯", True)

    prompt = SYSTEM_PROMPT
    if lang:
        prompt += f"\nè«ä¸å¾ä½¿ç¨ã{lang}ãåè¦æ­¤ç¨æ¶ï¼{display_name}ï¼ã"
    if auto_translate:
        prompt += "\nè¥ç¨æ¶ä»¥å¶ä»èªè¨æåï¼ä»ä»¥å¶åå¥½èªè¨åè¦ï¼ä¸éç¹å¥èªªæã"
    return prompt

# è¡ç¥¨æ¸å®
STOCKS = {
    "0056":  "åå¤§é«è¡æ¯",
    "00878": "åæ³°æ°¸çºé«è¡æ¯",
    "009816": "ä¸­ä¿¡æé·é«è¡æ¯",
}

# ééµå­èªåeè¦
KEYWORD_REPLIES = {
    "ä½ å¥½": "ä½ å¥½ï¼æä»éº¼æå¯ä»¥å¹«ä½ çåï¼ð",
    "hello": "Hello! How can I help you? ð",
    "å¹«å©": (
        "ð **å¯ç¨æä»¤ï¼**\n"
        "`/ask` å AI æå\n"
        "`/weather` é«éå¤©æ°£é å ±\n"
        "`/stocks` è¡ç¥¨è¡æ\n"
        "`/news` ææ°æ°è\n"
        "`/morning` ä»æ¥æ¨å ±\n"
        "`/translate` ç¿»è­¯\n"
        "`/remind` è¨­å®æé\n"
        "`/summary` é »éæè¦\n"
        "`/clear` æ¸é¤å°è©±è¨æ¶\n\n"
        "ä¹å¯ä»¥ç´æ¥ **@ç§äººAIå©ç** ä¸¦éä¸åçææä»¶ï¼"
    ),
}

# ç³»çµ±æç¤ºè©
SYSTEM_PROMPT = """ä½ æ¯ä¸åååãè°æç Discord ç§äººå©çã
ä½ çåå­å«åãå°å©çãã
è«ç¨ç¹é«ä¸­æåç­ï¼ä¿æç°¡æ½ä½æå¹«å©ã
å¨ Discord ä¸­åè¦æï¼é©ç¶ä½¿ç¨ emoji è®å°è©±æ´çåã
ä½ å¯ä»¥åæåçåæä»¶ï¼æä¾ç¿»è­¯ï¼åç­åç¨®åé¡ã"""

# ââ Bot åå§å ââââââââââââââââââââââââââââââââââââââââââ
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
conversation_history: dict[int, list] = {}
pending_reminders: list = []


# ââ å·¥å·å½å¼ ââââââââââââââââââââââââââââââââââââââââââ
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
            {"type": "text", "text": user_message or "è«æè¿°éå¼µåççå§å®¹"},
        ]
    else:
        content = user_message

    conversation_history[user_id].append({"role": "user", "content": content})
    recent = conversation_history[user_id][-10:]

    # æ ¹æç¨æ¶åå¥½é¸æç³»çµ±æç¤ºè©
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
    """ä½¿ç¨ Claude å°æ¨é¡æ¹æ¬¡ç¿»è­¯æç¹é«ä¸­æ"""
    if not titles:
        return titles
    try:
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system="ä½ æ¯å°æ¥­ç¿»è­¯å¡ãå°ä»¥ä¸ç·¨èæ°èæ¨é¡ç¿»è­¯æç¹é«ä¸­æï¼ä¿æç¸åç·¨èæ ¼å¼ï¼åªè¼¸åºç¿»è­¯çµæï¼ä¸å ä»»ä½è§£éæåæã",
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
                labels = ["ä»å¤©", "æå¤©", "å¾å¤©"]
                fc_lines = []
                for i, day in enumerate(forecast[:3]):
                    mx = day["maxtempC"]
                    mn = day["mintempC"]
                    d = day["hourly"][4]["weatherDesc"][0]["value"]
                    fc_lines.append(f"  {labels[i]}ï¼{mn}Â°~{mx}Â° {d}")

                return (
                    f"ð¤ï¸ **{area} å³æå¤©æ°£**\n"
                    f"ð¡ï¸ æ°£æº«ï¼{temp}Â°Cï¼é«æ {feels}Â°Cï¼\n"
                    f"ð§ æ¿åº¦ï¼{humidity}%ãâï¸ UVï¼{uv}\n"
                    f"ð çæ³ï¼{desc}\n\n"
                    f"ð **ä¸æ¥é å ±**\n" + "\n".join(fc_lines)
                )
    except Exception as e:
        return f"â å¤©æ°£è³æåå¾å¤±æï¼{e}"


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
                        arrow = "ð" if change >= 0 else "ð"
                        sign = "+" if change >= 0 else ""
                        results.append(
                            f"{arrow} **{ticker} {name}**\n"
                            f"   ç¾å¹ï¼**{price:.2f}** åã{sign}{change} ({sign}{pct}%)"
                        )
                except Exception:
                    results.append(f"â ï¸ **{ticker} {name}**ï¼è³æåå¾å¤±æ")
    except Exception as e:
        return f"â è¡ç¥¨æ¥è©¢å¤±æï¼{e}"

    return "ð¹ **å°è¡è¡æ**\n" + "\n".join(results)


async def get_news(category: str = "ç¶å", translate_intl: bool = False) -> str:
    tw_urls = {
        "ç¶å": "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "è²¡ç¶": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtcFVHZ0pVVWlnQVAB?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
        "ç§æ": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtcFVHZ0pVVWlnQVAB?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
    }
    intl_urls = {
        "ç¶å": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
        "è²¡ç¶": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx6TVdZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
        "ç§æ": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlnQVAB?hl=en-US&gl=US&ceid=US:en",
    }
    try:
        tw_feed = feedparser.parse(tw_urls.get(category, tw_urls["ç¶å"]))
        intl_feed = feedparser.parse(intl_urls.get(category, intl_urls["ç¶å"]))

        def clean(title):
            return re.sub(r"\s*[-â]\s*[^-â]+$", "", title).strip()

        tw_lines = [f"â¢ {clean(e.title)}" for e in tw_feed.entries[:3]]
        raw_intl = [clean(e.title) for e in intl_feed.entries[:3]]

        # è¥éåèªåç¿»è­¯ï¼å°åéæ°èè±ææ¨é¡ç¿»è­¯æç¹é«ä¸­æ
        if translate_intl:
            raw_intl = translate_titles_to_chinese(raw_intl)

        intl_lines = [f"â¢ {t}" for t in raw_intl]
        emoji = {"ç¶å": "ð°", "è²¡ç¶": "ð°", "ç§æ": "ð»"}.get(category, "ð°")

        return (
            f"{emoji} **{category}æ°è**\n"
            f"ð¹ð¼ åå§ï¼\n" + "\n".join(tw_lines) + "\n"
            f"ð åéï¼å·²ç¿»è­¯ï¼ï¼\n" + "\n".join(intl_lines)
            if translate_intl else
            f"{emoji} **{category}æ°è**\n"
            f"ð¹ð¼ åå§ï¼\n" + "\n".join(tw_lines) + "\n"
            f"ð åéï¼\n" + "\n".join(intl_lines)
        )
    except Exception as e:
        return f"â æ°èåå¾å¤±æï¼{e}"


async def get_notion_todos() -> str:
    """å¾ Notion åå¾å¾èç / èçä¸­çå¾è¾¦äºé """
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
                            {"property": "çæ", "select": {"equals": "ð å¾èç"}},
                            {"property": "çæ", "select": {"equals": "ð èçä¸­"}},
                        ]
                    },
                    "sorts": [{"property": "æªæ­¢æ¥æ", "direction": "ascending"}],
                    "page_size": 10,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                results = data.get("results", [])
                if not results:
                    return "ð **ä»æ¥å¾è¾¦ (Notion)**\nâ¢ æ²æå¾è¾¦äºé ï¼ä»å¤©è¾è¦äºï¼ð"
                lines = []
                for page in results:
                    props = page.get("properties", {})
                    title_rich = props.get("å¾è¾¦äºé ", {}).get("title", [])
                    title = title_rich[0]["plain_text"] if title_rich else "ï¼ç¡æ¨é¡ï¼"
                    status_obj = props.get("çæ", {}).get("select") or {}
                    status = status_obj.get("name", "")
                    due_obj = props.get("æªæ­¢æ¥æ", {}).get("date") or {}
                    due_str = f"  â° {due_obj['start']}" if due_obj.get("start") else ""
                    lines.append(f"â¢ {status} {title}{due_str}")
                return "ð **ä»æ¥å¾è¾¦ (Notion)**\n" + "\n".join(lines)
    except Exception as e:
        return f"ð **ä»æ¥å¾è¾¦ (Notion)**\nâ¢ åå¾å¤±æï¼{e}"


async def get_calendar_events() -> str:
    """å¾ Google Calendar ç§äºº iCal ç¶²ååå¾ä»æ¥è¡ç¨"""
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
            summary = str(component.get("SUMMARY", "ï¼ç¡æ¨é¡ï¼"))
            dtstart = component.get("DTSTART")
            if dtstart is None:
                continue
            dt_val = dtstart.dt
            # å¨å¤©äºä»¶æ¯ date åå¥ï¼ææéçäºä»¶æ¯ datetime
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
            return "ð **ä»æ¥è¡ç¨ (Google Calendar)**\nâ¢ ä»å¤©æ²æè¡ç¨ï¼æ¾é¬ä¸ä¸ï¼ð"
        events.sort(key=lambda x: (x[2], x[0] if not x[2] else datetime.datetime.min))
        lines = []
        for dt_val, title, all_day in events:
            if all_day:
                lines.append(f"â¢ ð {title}ï¼å¨å¤©ï¼")
            else:
                lines.append(f"â¢ {dt_val.strftime('%H:%M')} {title}")
        return "ð **ä»æ¥è¡ç¨ (Google Calendar)**\n" + "\n".join(lines)
    except Exception as e:
        return f"ð **ä»æ¥è¡ç¨ (Google Calendar)**\nâ¢ åå¾å¤±æï¼{e}"


async def build_morning_summary() -> str:
    now = datetime.datetime.now(TAIWAN_TZ)
    weekdays = ["ææä¸", "ææäº", "ææä¸", "ææå", "ææäº", "ææå­", "æææ¥"]
    date_str = f"{now.strftime('%Y/%m/%d')} {weekdays[now.weekday()]}"

    # ä¸¦è¡åå¾ææè³æï¼å éæ¨å ±çæ
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
        get_news("ç¶å", translate_intl=True),
        get_news("è²¡ç¶", translate_intl=True),
        get_news("ç§æ", translate_intl=True),
        get_notion_todos(),
        get_calendar_events(),
    )

    divider = f"\n{'â'*32}\n\n"
    sections = [
        f"ð **æ©å®ï¼ä»æ¥æ¨å ± {date_str}**\n{'â'*32}\n",
        weather,
        stocks,
    ]

    # å å¥è¡ç¨èå¾è¾¦ï¼å¦æè¨­å®å°±é¡¯ç¤ºï¼
    if calendar_events:
        sections.append(calendar_events)
    if notion_todos:
        sections.append(notion_todos)

    sections += [news_gen, news_fin, news_tech]

    return divider.join(sections) + f"\n{'â'*32}\nHave a productive day! ðªâ¨"


# ââ æç¨ä»»å ââââââââââââââââââââââââââââââââââââââââââ
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
                await ch.send(f"â° <@{r['user_id']}> æéï¼**{r['message']}**")
            done.append(r)
    for r in done:
        pending_reminders.remove(r)


# ââ äºä»¶èç ââââââââââââââââââââââââââââââââââââââââââ
@bot.event
async def on_ready():
    print(f"â Bot å·²ä¸ç·ï¼{bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"â åæ­¥äº {len(synced)} åæç·æä»¤")
    except Exception as e:
        print(f"â åæ­¥å¤±æï¼{e}")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.listening, name="/ask ä¾æå")
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
                        clean = f"è«åæä»¥ä¸æä»¶ï¼\n\n{doc[:3000]}\n\n{clean}"
                        break

                if clean or image_data:
                    reply = get_ai_response(message.author.id, clean, image_data, message.author.display_name)
                    for chunk in split_message(reply):
                        await message.reply(chunk)
            except Exception as e:
                await message.reply(f"â é¯èª¤ï¼{e}")
        return

    await bot.process_commands(message)


# ââ æç·æä»¤ ââââââââââââââââââââââââââââââââââââââââââ
@bot.tree.command(name="ask", description="å AI å©çæå")
@app_commands.describe(åé¡="ä½ æ³åä»éº¼ï¼")
async def ask(interaction: discord.Interaction, åé¡: str):
    await interaction.response.defer(thinking=True)
    try:
        reply = get_ai_response(interaction.user.id, åé¡, display_name=interaction.user.display_name)
        chunks = split_message(reply)
        await interaction.followup.send(chunks[0])
        for c in chunks[1:]:
            await interaction.channel.send(c)
    except Exception as e:
        await interaction.followup.send(f"â é¯èª¤ï¼{e}")


@bot.tree.command(name="weather", description="æ¥è©¢é«éå³æå¤©æ°£èä¸æ¥é å ±")
async def weather_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await get_weather())


@bot.tree.command(name="stocks", description="æ¥è©¢ 0056ã00878ã009816 è¡ç¥¨è¡æ")
async def stocks_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await get_stock_prices())


@bot.tree.command(name="news", description="æ¥çææ°æ°èï¼åå§å¤å 3 åï¼")
@app_commands.describe(é¡å¥="æ°èé¡å¥")
@app_commands.choices(
    é¡å¥=[
        app_commands.Choice(name="ç¶åé ­æ¢", value="ç¶å"),
        app_commands.Choice(name="è²¡ç¶", value="è²¡ç¶"),
        app_commands.Choice(name="ç§æ", value="ç§æ"),
    ]
)
async def news_cmd(interaction: discord.Interaction, é¡å¥: str = "ç¶å"):
    await interaction.response.defer(thinking=True)
    await interaction.followup.send(await get_news(é¡å¥))


@bot.tree.command(name="morning", description="ç«å³åå¾ä»æ¥æ¨å ±ï¼å¤©æ°£ï¼è¡ç¥¨ï¼æ°èï¼")
async def morning_cmd(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    summary = await build_morning_summary()
    chunks = split_message(summary)
    await interaction.followup.send(chunks[0])
    for c in chunks[1:]:
        await interaction.channel.send(c)


@bot.tree.command(name="translate", description="ç¿»è­¯æå­")
@app_commands.describe(æå­="è¦ç¿»è­¯çæå­", èªè¨="ç®æ¨èªè¨ï¼é è¨­è±æï¼")
async def translate_cmd(interaction: discord.Interaction, æå­: str, èªè¨: str = "è±æ"):
    await interaction.response.defer(thinking=True)
    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system="ä½ æ¯å°æ¥­ç¿»è­¯å¡ï¼åªè¼¸åºç¿»è­¯çµæï¼ä¸å ä»»ä½è§£éã",
            messages=[{"role": "user", "content": f"ç¿»è­¯æ{èªè¨}ï¼{æå­}"}],
        )
        await interaction.followup.send(f"ð **â {èªè¨}**\n{resp.content[0].text}")
    except Exception as e:
        await interaction.followup.send(f"â ç¿»è­¯å¤±æï¼{e}")


@bot.tree.command(name="remind", description="è¨­å®åæ¸æé")
@app_commands.describe(åé="å¹¾åéå¾æé", å§å®¹="æéå§å®¹")
async def remind_cmd(interaction: discord.Interaction, åé: int, å§å®¹: str):
    t = datetime.datetime.now(TAIWAN_TZ) + datetime.timedelta(minutes=åé)
    pending_reminders.append({
        "time": t,
        "message": å§å®¹,
        "channel_id": interaction.channel_id,
        "user_id": interaction.user.id,
    })
    await interaction.response.send_message(
        f"â° **{åé} åéå¾**æéä½ ï¼{å§å®¹}", ephemeral=True
    )


@bot.tree.command(name="clear", description="æ¸é¤è AI çå°è©±è¨æ¶")
async def clear_cmd(interaction: discord.Interaction):
    if interaction.user.id in conversation_history:
        conversation_history.pop(interaction.user.id)
        await interaction.response.send_message("ðï¸ å·²æ¸é¤å°è©±è¨æ¶ï¼", ephemeral=True)
    else:
        await interaction.response.send_message("ç®åæ²æå°è©±è¨æ¶ã", ephemeral=True)


@bot.tree.command(name="summary", description="æè¦æ­¤é »éæè¿çè¨æ¯")
@app_commands.describe(æ¸é="è¨æ¯æ¸éï¼é è¨­ 20ï¼æå¤ 50ï¼")
async def summary_cmd(interaction: discord.Interaction, æ¸é: int = 20):
    await interaction.response.defer(thinking=True)
    æ¸é = min(æ¸é, 50)
    try:
        msgs = []
        async for m in interaction.channel.history(limit=æ¸é + 1):
            if not m.author.bot:
                msgs.append(f"{m.author.display_name}: {m.content}")
        msgs.reverse()
        if not msgs:
            await interaction.followup.send("â æ¾ä¸å°å¯æè¦çè¨æ¯ã")
            return
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"è«ç¨ç¹é«ä¸­ææ¢åæè¦ï¼\n\n{chr(10).join(msgs)}"}],
        )
        reply = f"ð **æè¿ {æ¸é} åè¨æ¯æè¦ï¼**\n\n{resp.content[0].text}"
        chunks = split_message(reply)
        await interaction.followup.send(chunks[0])
        for c in chunks[1:]:
            await interaction.channel.send(c)
    except Exception as e:
        await interaction.followup.send(f"â æè¦å¤±æï¼{e}")


@bot.tree.command(name="profile", description="æ¥çä½ çåäººåå¥½è¨­å®")
async def profile_cmd(interaction: discord.Interaction):
    name = interaction.user.display_name
    prefs = get_user_prefs(name)
    lang = prefs.get("èªè¨", "ç¹é«ä¸­æ")
    auto_tr = "â éå" if prefs.get("èªåç¿»è­¯", True) else "â éé"
    await interaction.response.send_message(
        f"ð¤ **{name} çåå¥½è¨­å®**\n"
        f"ð åè¦èªè¨ï¼**{lang}**\n"
        f"ð èªåç¿»è­¯ï¼**{auto_tr}**\n\n"
        f"ä½¿ç¨ `/setlang` æ´æ¹èªè¨ï¼`/autotranslate` åæèªåç¿»è­¯",
        ephemeral=True,
    )


@bot.tree.command(name="setlang", description="è¨­å® AI åè¦èªè¨")
@app_commands.describe(èªè¨="åå¥½çåè¦èªè¨ï¼ä¾å¦ï¼ç¹é«ä¸­æãEnglishãæ¥æ¬èªï¼")
async def setlang_cmd(interaction: discord.Interaction, èªè¨: str):
    name = interaction.user.display_name
    set_user_pref(name, "èªè¨", èªè¨)
    await interaction.response.send_message(
        f"â å·²å°ä½ çåè¦èªè¨è¨­çºï¼**{èªè¨}**", ephemeral=True
    )


@bot.tree.command(name="autotranslate", description="åæèªåç¿»è­¯ï¼é/éï¼")
async def autotranslate_cmd(interaction: discord.Interaction):
    name = interaction.user.display_name
    prefs = get_user_prefs(name)
    current = prefs.get("èªåç¿»è­¯", True)
    new_val = not current
    set_user_pref(name, "èªåç¿»è­¯", new_val)
    status = "â å·²éå" if new_val else "â å·²éé"
    await interaction.response.send_message(
        f"ð èªåç¿»è­¯ï¼**{status}**", ephemeral=True
    )


@bot.tree.command(name="keyword", description="æ¥çééµå­èªååè¦æ¸å®")
async def keyword_cmd(interaction: discord.Interaction):
    lines = ["ð **ééµå­èªååè¦æ¸å®ï¼**\n"]
    for kw, r in KEYWORD_REPLIES.items():
        lines.append(f"â¢ `{kw}` â {str(r)[:50]}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


# ââ åå ââââââââââââââââââââââââââââââââââââââââââââââ
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("â ç¼ºå° DISCORD_TOKENï¼è«è¨­å®ç°å¢è®æ¸")
    if not ANTHROPIC_API_KEY:
        raise ValueError("â ç¼ºå° ANTHROPIC_API_KEYï¼è«è¨­å®ç°å¢è®æ¸")
    bot.run(DISCORD_TOKEN)
