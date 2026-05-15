"""驗證 Notion 庫存 DB 連線：
- 確認 NOTION_TOKEN + INVENTORY_NOTION_DB_ID 可以打通
- 列出 DB 所有屬性名稱與型別，方便比對 INVENTORY_NAME_PROP / INVENTORY_STOCK_PROP
- 抓前 3 筆資料看實際內容

用法：python3 tools/verify_notion.py
"""
import os
import sys
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
DB_ID = os.getenv("INVENTORY_NOTION_DB_ID", "")
NAME_PROP = os.getenv("INVENTORY_NAME_PROP", "品項名稱")
STOCK_PROP = os.getenv("INVENTORY_STOCK_PROP", "庫存")


def fail(msg: str):
    print(f"❌ {msg}")
    sys.exit(1)


def headers() -> dict:
    return {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


async def main():
    if not NOTION_TOKEN:
        fail("NOTION_TOKEN 沒設（檢查 .env）")
    if not DB_ID:
        fail("INVENTORY_NOTION_DB_ID 沒設（檢查 .env）")

    async with aiohttp.ClientSession() as session:
        # 1. DB metadata
        print(f"🔎 查 DB metadata：{DB_ID}")
        async with session.get(
            f"https://api.notion.com/v1/databases/{DB_ID}", headers=headers()
        ) as resp:
            if resp.status == 401:
                fail("401：NOTION_TOKEN 無效")
            if resp.status == 404:
                fail("404：DB 找不到或 integration 沒被加進該 DB 的 connections")
            if resp.status != 200:
                fail(f"取得 DB metadata 失敗：HTTP {resp.status} {await resp.text()}")
            meta = await resp.json()

        title = "".join(t.get("plain_text", "") for t in meta.get("title", []))
        print(f"✅ DB 名稱：{title or '(無)'}\n")

        props = meta.get("properties", {})
        print("📋 DB 所有欄位：")
        for name, info in props.items():
            mark = ""
            if name == NAME_PROP:
                mark = "  ← NAME_PROP"
            elif name == STOCK_PROP:
                mark = "  ← STOCK_PROP"
            print(f"   • {name}（型別：{info.get('type')}）{mark}")

        if NAME_PROP not in props:
            print(f"\n⚠️  找不到欄位「{NAME_PROP}」")
            print(f"   請把 .env 的 INVENTORY_NAME_PROP 改成上面其中一個欄位名")
        if STOCK_PROP not in props:
            print(f"\n⚠️  找不到欄位「{STOCK_PROP}」")
            print(f"   請把 .env 的 INVENTORY_STOCK_PROP 改成上面其中一個欄位名")

        # 2. 前 3 筆資料
        print("\n🔎 抓前 3 筆資料試試...")
        async with session.post(
            f"https://api.notion.com/v1/databases/{DB_ID}/query",
            headers=headers(),
            json={"page_size": 3},
        ) as resp:
            if resp.status != 200:
                fail(f"查詢失敗：HTTP {resp.status} {await resp.text()}")
            data = await resp.json()

        items = data.get("results", [])
        if not items:
            print("⚠️  DB 是空的，但連線成功 ✅")
            return

        print(f"✅ 共 {len(items)} 筆：")
        for it in items:
            p = it.get("properties", {})
            name_field = p.get(NAME_PROP, {})
            name = ""
            if name_field.get("type") == "title":
                t = name_field.get("title", [])
                name = t[0]["plain_text"] if t else "(空白)"
            else:
                name = f"(欄位「{NAME_PROP}」不是 title 型別)"

            stock_field = p.get(STOCK_PROP, {})
            stock = "?"
            if stock_field.get("type") == "number":
                stock = stock_field.get("number")
            elif stock_field.get("type") == "formula":
                f = stock_field.get("formula", {})
                stock = f.get("number") if f.get("type") == "number" else f.get("string")
            elif stock_field.get("type") == "rich_text":
                rt = stock_field.get("rich_text", [])
                stock = rt[0]["plain_text"] if rt else ""

            print(f"   • {name}：{stock}")

        print("\n🎉 全部正常！可以執行 ./deploy.sh tunnel 啟動服務")


if __name__ == "__main__":
    asyncio.run(main())
