"""鉴权模块：PBKDF2 密码哈希 + JWT 签发/校验。"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import sys
import time

import jwt

logger = logging.getLogger(__name__)

# 毕设演示用密钥；生产环境应从环境变量读取
JWT_SECRET = os.getenv("CAMPUS_JWT_SECRET", "campus-agent-demo-secret-change-me")
JWT_ALG = "HS256"
JWT_EXPIRE_SECONDS = 60 * 60 * 8  # 8 小时

# 部署提示：非测试环境使用演示默认密钥时打 warning，提醒设置 CAMPUS_JWT_SECRET
if JWT_SECRET == "campus-agent-demo-secret-change-me" and "pytest" not in sys.modules:
    logger.warning(
        "JWT_SECRET 未配置，正在使用演示默认密钥（仅限本地演示；部署/对外展示请设置环境变量 CAMPUS_JWT_SECRET）"
    )

PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """返回 (password_hash, salt)。"""
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return dk.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(dk.hex(), password_hash)


def issue_token(user_id: str, role: str, name: str = "", ver: int = 0) -> str:
    """签发 JWT；ver 为用户当前 token_version（改密/禁用时递增，用于撤销旧 token）。"""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": role,
        "name": name,
        "ver": ver,
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
