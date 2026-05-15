"""使用紀錄與統計：記錄每次指令呼叫，提供查詢介面"""
import json
from .storage import connect


def log_usage(
    platform: str,
    user_key: str,
    command: str,
    display_name: str = "",
    details: dict | None = None,
):
    """記錄一次使用事件
    platform: 'discord' | 'line'
    user_key: 平台原生 id（Discord user_id / Line userId）
    command: 指令名稱或事件類型，例如 'ask'、'weather'、'mention'
    """
    payload = json.dumps(details, ensure_ascii=False) if details else None
    with connect() as conn:
        conn.execute(
            "INSERT INTO usage_logs (platform, user_key, display_name, command, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (platform, str(user_key), display_name or None, command, payload),
        )


def user_summary(user_key: str | None = None, display_name: str | None = None) -> dict:
    """回傳指定使用者的使用統計；user_key 與 display_name 二擇一"""
    if not user_key and not display_name:
        raise ValueError("需提供 user_key 或 display_name")

    where = "user_key = ?" if user_key else "display_name = ?"
    arg = str(user_key) if user_key else display_name

    with connect() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM usage_logs WHERE {where}", (arg,)
        ).fetchone()[0]
        by_command = conn.execute(
            f"SELECT command, COUNT(*) AS c FROM usage_logs WHERE {where} "
            "GROUP BY command ORDER BY c DESC LIMIT 10",
            (arg,),
        ).fetchall()
        by_platform = conn.execute(
            f"SELECT platform, COUNT(*) AS c FROM usage_logs WHERE {where} GROUP BY platform",
            (arg,),
        ).fetchall()
        last = conn.execute(
            f"SELECT command, platform, created_at FROM usage_logs WHERE {where} "
            "ORDER BY created_at DESC LIMIT 1",
            (arg,),
        ).fetchone()

    return {
        "total": total,
        "by_command": [(r["command"], r["c"]) for r in by_command],
        "by_platform": [(r["platform"], r["c"]) for r in by_platform],
        "last_used": dict(last) if last else None,
    }


def format_summary(summary: dict, name: str) -> str:
    """把 user_summary 結果格式化成 Discord/Line 可直接顯示的字串"""
    if summary["total"] == 0:
        return f"📊 **{name} 的使用統計**\n還沒有任何使用紀錄。"

    lines = [f"📊 **{name} 的使用統計**", f"總使用次數：**{summary['total']}**"]

    if summary["by_platform"]:
        plat_str = "、".join(f"{p}：{c}" for p, c in summary["by_platform"])
        lines.append(f"平台分佈：{plat_str}")

    if summary["by_command"]:
        lines.append("\n🏆 **最常用指令：**")
        for cmd, count in summary["by_command"]:
            lines.append(f"• `{cmd}` × {count}")

    if summary["last_used"]:
        lines.append(
            f"\n🕒 最近一次：`{summary['last_used']['command']}` "
            f"({summary['last_used']['platform']}) @ {summary['last_used']['created_at']}"
        )

    return "\n".join(lines)
