from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import settings

# bcrypt 只处理前 72 字节，超出部分会被忽略/报错，统一截断让行为可预期
_BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """把明文密码变成 bcrypt 哈希（结果里已含随机 salt）。"""
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。哈希格式不对时返回 False，而不是抛异常。"""
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, hashed.encode("ascii"))
    except ValueError:
        return False


def create_access_token(subject: int) -> str:
    """签发 access token。subject 是用户 id。"""
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),  # JWT 规范要求 sub 是字符串
        "iat": now,           #签发时间
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),     #过期时间
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> int:
    """校验签名与过期时间，返回用户 id。token 无效时抛 jwt.InvalidTokenError。"""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],  # 必须是列表：防算法混淆攻击
    )
    return int(payload["sub"])