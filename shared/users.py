"""使用者偏好：兩個 bot 共用同一份偏好設定"""
from .storage import connect

DEFAULT_PREFS = {"語言": "繁體中文", "自動翻譯": True}


def get_user_prefs(display_name: str) -> dict:
    """取得使用者偏好；找不到回傳預設值"""
    with connect() as conn:
        row = conn.execute(
            "SELECT language, auto_translate FROM users WHERE display_name = ?",
            (display_name,),
        ).fetchone()
    if row is None:
        return dict(DEFAULT_PREFS)
    return {
        "語言": row["language"],
        "自動翻譯": bool(row["auto_translate"]),
    }


def set_user_pref(display_name: str, key: str, value):
    """更新單一偏好欄位（語言 / 自動翻譯）"""
    column = {"語言": "language", "自動翻譯": "auto_translate"}.get(key)
    if column is None:
        raise ValueError(f"未知的偏好欄位：{key}")
    stored = 1 if value else 0 if column == "auto_translate" else value
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (display_name) VALUES (?) ON CONFLICT(display_name) DO NOTHING",
            (display_name,),
        )
        conn.execute(
            f"UPDATE users SET {column} = ?, updated_at = CURRENT_TIMESTAMP WHERE display_name = ?",
            (stored, display_name),
        )
