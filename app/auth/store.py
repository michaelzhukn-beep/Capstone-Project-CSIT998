"""users / sessions 两张表。和房源同一个 Postgres,借 app.core.db 的连接池。

- 用户名与邮箱都按小写做唯一约束(Alice 与 alice 是同一个人);显示时保留原样。
- 会话令牌只存 sha256 哈希:数据库泄露也拿不到能用的 Cookie。
- 建表语句同时写在 db/schema.sql;已有数据库不会重跑初始化脚本,所以启动时再幂等建一次。
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import psycopg2.errors

from app.core.db import get_connection

SESSION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    username       TEXT NOT NULL,
    username_key   TEXT NOT NULL UNIQUE,
    email          TEXT,
    email_key      TEXT UNIQUE,
    password_hash  TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions(user_id);
-- 收藏:不对 properties 建外键 —— 数据集会被整体重新下载(房源 id 可能变),外键会挡住重新导入。
-- snapshot 是收藏时服务端从 properties 取的事实字段,房源表重建后列表照样能显示。
CREATE TABLE IF NOT EXISTS favorites (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    property_id  INTEGER NOT NULL,
    snapshot     JSONB NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, property_id)
);
"""


class Taken(ValueError):
    """用户名或邮箱已被注册;args[0] 是字段名。"""


def ensure_schema() -> None:
    with get_connection() as conn:
        conn.cursor().execute(SCHEMA)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('ascii')).hexdigest()


def create_user(username: str, email: str | None, password_hash: str) -> dict:
    name_key, email_key = username.lower(), email.lower() if email else None
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT username_key, email_key FROM users WHERE username_key = %s OR email_key = %s",
                        (name_key, email_key))
            rows = cur.fetchall()
            if any(r[0] == name_key for r in rows):
                raise Taken('username')
            if rows:
                raise Taken('email')
            cur.execute("INSERT INTO users (username, username_key, email, email_key, password_hash) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (username, name_key, email, email_key, password_hash))
            return {'id': cur.fetchone()[0], 'username': username, 'email': email}
    except psycopg2.errors.UniqueViolation as exc:      # 两人同时注册同名:先查后插之间的竞争,由唯一约束兜底
        raise Taken('email' if 'email' in str(exc) else 'username') from exc


def find_for_login(login: str) -> dict | None:
    """按用户名或邮箱找人(不区分大小写)。"""
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, email, password_hash FROM users WHERE username_key = %s OR email_key = %s",
                    (login.lower(), login.lower()))
        row = cur.fetchone()
    return dict(zip(('id', 'username', 'email', 'password_hash'), row)) if row else None


def create_session(user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE expires_at < now()")          # 顺手清掉过期会话
        cur.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                    (_token_hash(token), user_id, expires))
    return token, expires


def user_for_session(token: str | None) -> dict | None:
    if not token or not token.isascii():        # 令牌只会是 token_urlsafe 的 ASCII;非 ASCII 的 Cookie 一律当未登录,不能抛 500
        return None
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT u.id, u.username, u.email FROM sessions s JOIN users u ON u.id = s.user_id "
                    "WHERE s.token_hash = %s AND s.expires_at > now()", (_token_hash(token),))
        row = cur.fetchone()
    return dict(zip(('id', 'username', 'email'), row)) if row else None


def delete_session(token: str | None) -> None:
    if token and token.isascii():
        with get_connection() as conn:
            conn.cursor().execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))


def delete_user(user_id: int) -> None:
    """测试清理用;会话随外键级联删除。"""
    with get_connection() as conn:
        conn.cursor().execute("DELETE FROM users WHERE id = %s", (user_id,))
