"""Notion 庫存查詢：兩個 bot 共用
透過環境變數設定 DB ID 與屬性名稱，避免寫死。
"""
import os
import time
import aiohttp

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
INVENTORY_DB_ID = os.getenv("INVENTORY_NOTION_DB_ID", "")

# Notion 屬性名稱（可在 .env 覆寫，預設值為一般中文命名）
NAME_PROP = os.getenv("INVENTORY_NAME_PROP", "品名")
STOCK_PROP = os.getenv("INVENTORY_STOCK_PROP", "庫存")

_NOTION_VERSION = "2022-06-28"
_CACHE_TTL_SEC = 300

_cache = {"items": None, "ts": 0.0}


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _extract_title(props: dict) -> str | None:
    title = props.get(NAME_PROP, {}).get("title", [])
    return title[0]["plain_text"] if title else None


def _extract_stock(props: dict):
    prop = props.get(STOCK_PROP, {})
    if "number" in prop and prop["number"] is not None:
        return prop["number"]
    if "formula" in prop:
        f = prop["formula"]
        return f.get("number") if f.get("type") == "number" else f.get("string")
    if "rich_text" in prop and prop["rich_text"]:
        return prop["rich_text"][0]["plain_text"]
    return "?"


async def _fetch_all() -> list[dict]:
    """分頁抓出庫存 DB 全部資料"""
    if not NOTION_TOKEN or not INVENTORY_DB_ID:
        return []
    items: list[dict] = []
    cursor = None
    async with aiohttp.ClientSession() as session:
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            async with session.post(
                f"https://api.notion.com/v1/databases/{INVENTORY_DB_ID}/query",
                headers=_headers(),
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return items
                data = await resp.json()
            items.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
    return items


async def _get_items_cached() -> list[dict]:
    now = time.time()
    if _cache["items"] is not None and (now - _cache["ts"] < _CACHE_TTL_SEC):
        return _cache["items"]
    items = await _fetch_all()
    _cache["items"] = items
    _cache["ts"] = now
    return items


def invalidate_cache():
    _cache["items"] = None


async def get_product_root_names() -> list[str]:
    """回傳產品名「根」（去掉括號後的規格部分）以供關鍵字比對
    例如「一生紅床包 (5尺 (高35))」→「一生紅床包」
    結果依長度排序（長的優先比對）以避免短詞誤命中
    """
    items = await _get_items_cached()
    roots = set()
    for it in items:
        name = _extract_title(it.get("properties", {}))
        if not name:
            continue
        root = name.split("(")[0].strip()
        if root:
            roots.add(root)
    return sorted(roots, key=len, reverse=True)


async def search(keyword: str) -> str:
    """以關鍵字搜尋庫存並回傳格式化字串"""
    items = await _get_items_cached()
    if not items:
        return "📦 庫存資料目前無法取得（請確認 INVENTORY_NOTION_DB_ID 與 NOTION_TOKEN）"

    matched = []
    for it in items:
        props = it.get("properties", {})
        name = _extract_title(props)
        if not name:
            continue
        if keyword in name:
            matched.append((name, _extract_stock(props)))

    if not matched:
        return f"📦 找不到「{keyword}」的庫存資料"

    lines = [f"📦 「{keyword}」庫存查詢："]
    for name, stock in matched:
        lines.append(f"• {name}:{stock}")
    return "\n".join(lines)


async def detect_keyword(text: str) -> str | None:
    """掃訊息看有沒有命中任何產品名根；命中就回傳該根，否則 None"""
    for name in await get_product_root_names():
        if name and name in text:
            return name
    return None
