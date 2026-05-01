FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY discord_bot.py .

ENV TZ=Asia/Taipei

CMD ["python", "-u", "discord_bot.py"]
