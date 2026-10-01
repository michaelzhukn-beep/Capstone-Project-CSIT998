"""密码哈希。只用标准库 hashlib.scrypt,不引入新依赖。

存储格式:scrypt$<n>$<r>$<p>$<salt hex>$<hash hex>。参数写进字符串里,
以后调高强度时旧哈希仍可校验(verify 按字符串里的参数算)。
"""
import hashlib
import hmac
import secrets

N, R, P, DKLEN = 2 ** 14, 8, 1, 32          # 约 16 MB 内存、单次约几十毫秒:对登录够用,对暴力破解够贵


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=N, r=R, p=P, dklen=DKLEN)
    return f'scrypt${N}${R}${P}${salt.hex()}${digest.hex()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split('$')
        if scheme != 'scrypt':
            return False
        got = hashlib.scrypt(password.encode('utf-8'), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, bytes.fromhex(digest))       # 定时比较,不泄露前缀是否相同


# 用户不存在时也跑一次同样代价的计算,让「用户不存在」和「密码错」在耗时上分不出来
DUMMY_HASH = hash_password(secrets.token_hex(16))
