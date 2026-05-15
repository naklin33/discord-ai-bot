#!/usr/bin/env bash
# 在全新的 Ubuntu/Debian VPS 上一鍵搭好環境
# 用法：在 VPS 上以 root 或 sudo 身分執行
#   curl -fsSL https://raw.githubusercontent.com/naklin33/discord-ai-bot/claude/analyze-user-habits-Eiamw/bootstrap.sh | bash
# 或：bash bootstrap.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/naklin33/discord-ai-bot.git}"
BRANCH="${BRANCH:-claude/analyze-user-habits-Eiamw}"
TARGET_DIR="${TARGET_DIR:-$HOME/discord-ai-bot}"

log() { echo -e "\033[1;36m▶ $*\033[0m"; }
warn() { echo -e "\033[1;33m⚠ $*\033[0m"; }
fail() { echo -e "\033[1;31m✗ $*\033[0m"; exit 1; }

# 1. 必要套件
log "更新套件索引並安裝相依工具..."
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq curl git ca-certificates
else
  fail "目前只支援 apt 系（Ubuntu/Debian）。請手動安裝 docker + git 後再執行 deploy.sh"
fi

# 2. Docker
if ! command -v docker >/dev/null 2>&1; then
  log "安裝 Docker..."
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
  warn "已把 $USER 加入 docker group，需要重新登入才會生效（這次 shell 仍會用 sudo）"
else
  log "Docker 已安裝：$(docker --version)"
fi

# 3. Docker Compose（v2 plugin）
if ! docker compose version >/dev/null 2>&1; then
  log "安裝 docker compose plugin..."
  sudo apt-get install -y -qq docker-compose-plugin || {
    warn "apt 抓不到 plugin，改用獨立 binary 安裝"
    sudo curl -fsSL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
      -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
  }
fi
log "Docker Compose：$(docker compose version)"

# 4. Clone repo
if [[ -d "$TARGET_DIR/.git" ]]; then
  log "Repo 已存在於 $TARGET_DIR，拉最新 commit..."
  cd "$TARGET_DIR"
  git fetch origin
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  log "Clone $REPO_URL → $TARGET_DIR"
  git clone "$REPO_URL" "$TARGET_DIR"
  cd "$TARGET_DIR"
  git checkout "$BRANCH"
fi

# 5. 建 data 目錄與 .env 模板
mkdir -p data
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn ".env 是從範例複製來的，全部還是 placeholder，需要手動填"
fi

cat <<'EOF'

═══════════════════════════════════════════════════════
✅ 環境準備完成。接下來只剩三件事必須由你來做：

1. 編輯 .env，把所有 your_xxx_here 改成真的值：
     nano .env
   至少要填這些：
     DISCORD_TOKEN, LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN,
     ANTHROPIC_API_KEY, NOTION_TOKEN, INVENTORY_NOTION_DB_ID,
     CLOUDFLARE_TUNNEL_TOKEN（從 Cloudflare Zero Trust → Tunnels 拿）

2. 驗證 Notion 庫存 DB 設定正確（會列出 DB 欄位）：
     python3 tools/verify_notion.py
   （需要先 sudo apt install python3 python3-pip && pip3 install aiohttp python-dotenv）

3. 啟動服務：
     ./deploy.sh tunnel

啟動後到 Line Developers Console：
  • Webhook URL → https://你的cloudflare網域/callback
  • Use webhook = ON
  • Auto-reply messages = OFF
═══════════════════════════════════════════════════════
EOF
