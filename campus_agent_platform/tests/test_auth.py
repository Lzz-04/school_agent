"""鉴权与学生管理测试：登录、改密、管理员增删学生、JWT、越权。"""

from __future__ import annotations

import pytest

from campus_agent_platform.auth import AuthError, decode_token, issue_token, verify_password
from campus_agent_platform.auth.security import hash_password

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


def test_password_hash_roundtrip():
    h, s = hash_password("mypassword")
    assert verify_password("mypassword", h, s)
    assert not verify_password("wrong", h, s)


def test_jwt_issue_decode():
    tok = issue_token("S10001", "student", "张三")
    payload = decode_token(tok)
    assert payload is not None
    assert payload["sub"] == "S10001"
    assert payload["role"] == "student"
    assert decode_token("bad.token") is None


def test_admin_login(app):
    """种子管理员 admin/admin123 能登录。"""
    r = app.auth.login("admin", "admin123")
    assert r["role"] == "admin"
    assert r["token"]


def test_login_wrong_password(app):
    with pytest.raises(AuthError):
        app.auth.login("admin", "wrong")


def test_add_students_and_login(app):
    result = app.auth.add_students([
        {"username": "20240001", "name": "张三", "email": "z@x.com"},
        {"username": "20240002", "name": "李四"},
    ])
    assert result["count"] == 2
    # 默认密码 123456
    r = app.auth.login("20240001", "123456")
    assert r["role"] == "student"
    assert r["name"] == "张三"


def test_duplicate_student_skipped(app):
    app.auth.add_students([{"username": "20240003", "name": "王五"}])
    result = app.auth.add_students([{"username": "20240003", "name": "王五改"}])
    assert result["count"] == 0
    assert result["skipped"]


def test_change_password(app):
    app.auth.add_students([{"username": "20240004", "name": "赵六"}])
    login = app.auth.login("20240004", "123456")
    uid = login["user_id"]
    app.auth.change_password(uid, "123456", "newpass789")
    # 旧密码失效
    with pytest.raises(AuthError):
        app.auth.login("20240004", "123456")
    # 新密码可用
    assert app.auth.login("20240004", "newpass789")["user_id"] == uid


def test_disable_student(app):
    app.auth.add_students([{"username": "20240005", "name": "钱七"}])
    students = app.auth.list_students()
    uid = next(s["user_id"] for s in students if s["username"] == "20240005")
    app.auth.disable_student(uid)
    with pytest.raises(AuthError):
        app.auth.login("20240005", "123456")


def test_list_students_only_students(app):
    app.auth.add_students([{"username": "20240006", "name": "孙八"}])
    students = app.auth.list_students()
    assert all(s["username"] != "admin" for s in students)
    assert any(s["username"] == "20240006" for s in students)
