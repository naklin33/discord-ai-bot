#!/usr/bin/env bash
# 一鍵部署腳本：檢查 .env、建置、啟動 Discord + Line bot
# 用法：./deploy.sh        → 只啟動兩個 bot
#       ./deploy.sh tunnel → 額外啟動 cloudflared tunnel
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "❌ 找不到 .env，請先 cp .env.example .env 並填好變數"
  exit 1
fi

REQUIRED=(
  DISCORD_TOKEN
  ANTHROPIC_API_KEY
  LINE_CHANNEL_SECRET
  LINE_CHANNEL_ACCESS_TOKEN
  NOTION_TOKEN
  INVENTORY_NOTION_DB_ID
)

missing=()
for var in "${REQUIRED[@]}"; do
  val=$(grep -E "^${var}=" .env | head -1 | cut -d= -f2- || true)
  if [[ -z "$val" || "$val" == *"your_"* || "$val" == *"_here"* ]]; then
    missing+=("$var")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "❌ .env 中以下變數尚未設定或仍是預設值："
  printf '   - %s\n' "${missing[@]}"
  exit 1
fi

mkdir -p data
echo "🔨 建置 Docker 映像..."
docker compose build

if [[ "${1:-}" == "tunnel" ]]; then
  token=$(grep -E "^CLOUDFLARE_TUNNEL_TOKEN=" .env | head -1 | cut -d= -f2-)
  if [[ -z "$token" ]]; then
    echo "❌ 要跑 cloudflared 但 CLOUDFLARE_TUNNEL_TOKEN 沒設"
    exit 1
  fi
  echo "🚀 啟動 discord-bot + line-bot + cloudflared..."
  docker compose --profile tunnel up -d
else
  echo "🚀 啟動 discord-bot + line-bot..."
  docker compose up -d
fi

echo ""
echo "✅ 已啟動。實用指令："
echo "   docker compose ps                 查看狀態"
echo "   docker compose logs -f line-bot   看 Line bot log"
echo "   docker compose logs -f discord-bot"
echo "   docker compose down               停止全部"
echo ""
echo "下一步："
echo "  1. 確認 Line Developers Console 的 Webhook URL 指向你的 HTTPS 網域 + /callback"
echo "  2. Webhook 開啟、Auto-reply messages 關閉"
echo "  3. 在 Line 對 bot 傳「品項名稱」測試庫存查詢"
