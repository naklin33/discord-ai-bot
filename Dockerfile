FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY discord_bot.py line_bot.py ./
COPY shared ./shared

ENV TZ=Asia/Taipei \
    BOT_DB_PATH=/app/data/bot.db

# 預設啟動 Discord bot；docker-compose 會用 command 覆寫切換到 Line bot
CMD ["python", "-u", "discord_bot.py"]
