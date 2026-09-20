"""pytest 公共 fixture：独立临时数据库 + 引擎 + 工具 + 编排图 + 可登录演示账号。"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from campus_agent_platform.app import CampusAgentApp
from campus_agent_platform.auth import security

# 测试用可登录账号（写入 users 表；密码统一 123456）
DEMO_USERS: list[tuple[str, str, str]] = [
    ("S10001", "student", "张三"),
    ("S10002", "student", "李四"),
    ("T10001", "advisor", "王导师"),
    ("C30001", "counselor", "陈辅导员"),
    ("A20001", "college_admin", "院领导"),
    ("U50001", "university_leader", "校领导"),
    ("H60001", "logistics", "后勤"),
    ("F40001", "finance", "财务"),
]
DEMO_PASSWORD = "123456"


def seed_demo_users(app: CampusAgentApp) -> None:
    """把演示账号写入 users 表（幂等），使 API 鉴权测试可登录。"""
    for uid, role, name in DEMO_USERS:
        if app.db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
            continue
        pw_hash, salt = security.hash_password(DEMO_PASSWORD)
        app.db.execute(
            "INSERT INTO users (user_id, username, password_hash, salt, role, name, email, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, uid, pw_hash, salt, role, name, "", "active", time.time()),
        )
    app.db.commit()


@pytest.fixture()
def app() -> CampusAgentApp:
    """独立应用实例（临时 SQLite 文件，含种子模板 + 可登录演示账号）。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    Path(tmp.name).unlink(missing_ok=True)
    instance = CampusAgentApp(db_path=tmp.name)
    seed_demo_users(instance)
    yield instance
    instance.close()
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture()
def engine(app: CampusAgentApp):
    return app.engine


@pytest.fixture()
def graph(app: CampusAgentApp):
    return app.graph
