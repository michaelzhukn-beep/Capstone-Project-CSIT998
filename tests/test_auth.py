"""账号注册 / 登录回归。只挂 /api/auth 路由的最小应用 + 真实 Postgres;测试账号跑完即删。

    python tests/test_auth.py
"""
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import favorites, passwords, routes, store
from app.core.db import get_connection

store.ensure_schema()
app = FastAPI(); app.include_router(routes.router)
tag = secrets.token_hex(3)
name, other = f'test_{tag}', f'other_{tag}'
email = f'{name}@example.com'
checks = 0


def check(ok, msg):
    global checks
    assert ok, msg
    checks += 1


def cleanup():
    with get_connection() as conn:
        conn.cursor().execute("DELETE FROM users WHERE username_key IN (%s, %s)", (name.lower(), other.lower()))


try:
    c = TestClient(app)
    # 注册:成功即登录,Cookie 为 HttpOnly
    r = c.post('/api/auth/register', json={'username': name, 'email': email, 'password': 'correct horse 9'})
    check(r.status_code == 200 and r.json()['user']['username'] == name, f'register: {r.text}')
    cookie = r.headers.get('set-cookie', '')
    check('nw_session=' in cookie and 'HttpOnly' in cookie and 'samesite=lax' in cookie.lower(), f'cookie flags: {cookie}')
    check(c.get('/api/auth/me').json()['user']['username'] == name, 'me after register')

    # 数据库里没有明文密码,也没有明文令牌
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE username_key = %s", (name.lower(),))
        stored = cur.fetchone()[0]
        cur.execute("SELECT token_hash FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.username_key = %s", (name.lower(),))
        token_hashes = [row[0] for row in cur.fetchall()]
    check(stored.startswith('scrypt$') and 'correct horse' not in stored, 'password stored as scrypt hash')
    check(c.cookies.get('nw_session') not in token_hashes and len(token_hashes) == 1, 'session token stored hashed')

    # 重名:大小写不同也算同一个;邮箱同理
    anon = TestClient(app)
    r = anon.post('/api/auth/register', json={'username': name.upper(), 'password': 'another pass 1'})
    check(r.status_code == 409 and r.json()['error'] == 'username_taken', f'dup username: {r.text}')
    r = anon.post('/api/auth/register', json={'username': other, 'email': email.upper(), 'password': 'another pass 1'})
    check(r.status_code == 409 and r.json()['error'] == 'email_taken', f'dup email: {r.text}')

    # 输入校验:错误码稳定,文案由前端给
    for body, code in (({'username': 'ab', 'password': 'long enough 1'}, 'username_invalid'),
                       ({'username': 'bad name!', 'password': 'long enough 1'}, 'username_invalid'),
                       ({'username': other, 'email': 'not-an-email', 'password': 'long enough 1'}, 'email_invalid'),
                       ({'username': other, 'password': 'short'}, 'password_length'),
                       ({'username': other, 'password': other}, 'password_is_username')):
        r = anon.post('/api/auth/register', json=body)
        check(r.status_code == 400 and r.json()['error'] == code, f'{code}: {r.text}')
    zh_name = f'中文{tag}'
    r = TestClient(app).post('/api/auth/register', json={'username': zh_name, 'password': 'long enough 1'})
    with get_connection() as conn:
        conn.cursor().execute("DELETE FROM users WHERE username_key = %s", (zh_name.lower(),))
    check(r.status_code == 200 and r.json()['user']['username'] == zh_name, f'chinese username: {r.text}')

    # 登出:Cookie 清掉,服务端会话也删掉(旧令牌不能再用)
    old = c.cookies.get('nw_session')
    check(c.post('/api/auth/logout').status_code == 200 and c.get('/api/auth/me').json()['user'] is None, 'logout')
    check(store.user_for_session(old) is None, 'old token revoked server-side')

    # 登录:用户名(任意大小写)或邮箱都行
    check(c.post('/api/auth/login', json={'login': name.upper(), 'password': 'correct horse 9'}).status_code == 200, 'login by username')
    check(c.post('/api/auth/login', json={'login': email, 'password': 'correct horse 9'}).status_code == 200, 'login by email')

    # 失败:不存在的人与密码错返回同一个错误码
    wrong = anon.post('/api/auth/login', json={'login': name, 'password': 'wrong password'})
    ghost = anon.post('/api/auth/login', json={'login': f'ghost_{tag}', 'password': 'wrong password'})
    check(wrong.status_code == ghost.status_code == 401 and wrong.json() == ghost.json(), 'no user enumeration')

    # 限流:同一 IP + 账号连续失败 5 次后,连正确密码也暂时拒绝
    for _ in range(4):
        anon.post('/api/auth/login', json={'login': name, 'password': 'wrong password'})
    r = anon.post('/api/auth/login', json={'login': name, 'password': 'correct horse 9'})
    check(r.status_code == 429 and r.json()['error'] == 'too_many_attempts', f'lockout: {r.text}')

    check(not passwords.verify_password('x', 'garbage') and not passwords.verify_password('x', 'md5$abc'), 'malformed hash rejected')

    # 收藏:需要登录;快照由服务端从 properties 取;重复收藏幂等;删除后不再出现
    fav = FastAPI(); fav.include_router(routes.router); fav.include_router(favorites.router)
    fc, guest = TestClient(fav), TestClient(fav)
    check(fc.post('/api/auth/login', json={'login': name, 'password': 'correct horse 9'}).status_code in (200, 429), 'fav login')
    routes._fails.clear()
    check(fc.post('/api/auth/login', json={'login': name, 'password': 'correct horse 9'}).status_code == 200, 'fav login ok')
    with get_connection() as conn:
        cur = conn.cursor(); cur.execute("SELECT id, suburb, price FROM properties ORDER BY id LIMIT 1")
        pid, suburb, price = cur.fetchone()
    check(guest.get('/api/favorites').status_code == 401 and guest.put(f'/api/favorites/{pid}').status_code == 401, 'favorites need login')
    check(fc.put(f'/api/favorites/{pid}').status_code == 200 and fc.put(f'/api/favorites/{pid}').status_code == 200, 'add is idempotent')
    items = fc.get('/api/favorites').json()['items']
    check(len(items) == 1 and items[0]['id'] == pid and items[0]['snapshot']['suburb'] == suburb
          and items[0]['snapshot']['price'] == price, f'snapshot from DB: {items}')
    check('gross_yield' not in items[0]['snapshot'], 'no model/assumption numbers frozen into the snapshot')
    check(fc.put('/api/favorites/999999999').status_code == 404, 'unknown property rejected')
    check(fc.delete(f'/api/favorites/{pid}').status_code == 200 and fc.get('/api/favorites').json()['items'] == [], 'remove')
finally:
    cleanup()
    routes._fails.clear()
print(f'账号注册/登录 全部通过:{checks} 项检查(真实数据库,测试账号已清理)')
