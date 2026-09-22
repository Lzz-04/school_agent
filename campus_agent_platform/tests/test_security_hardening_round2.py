"""安全加固第二轮回归测试（编排链路二次审计 + 会话安全闭环）。

覆盖 P0 第二轮修复：
1. S1 编排 status 越权读（IDOR）：他人走 /api/v1/agent/run intent=status → 403；本人 → 200
2. S2 编排 archive 越权归档：学生走 agent/run intent=archive → 403（权限矩阵拒绝）且单未归档；
   admin 走 agent/run intent=archive → 成功；同源 register 意图学生 → 403
3. S3 对话端 auto_review 班级过滤：非本班单不被处理
4. S4 待办 > 100 条不截断：最旧的本班单不被漏审（旧实现 list_all LIMIT 100 会漏）
5. S5 form_result 消息归属：他人改写 → 403；本人改写 → 200
6. S6 JWT 撤销 + 登录频控 + 账号枚举：
   - 改密/禁用后旧 token → 401
   - 连续 5 次登录失败 → 锁定（正确密码也拒绝）
   - 用户不存在与密码错误返回同一错误文案
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from campus_agent_platform.api.app import create_app
from campus_agent_platform.auth import AuthError
from campus_agent_platform.workflows.approval_service import ApprovalService

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture()
def client(app):
    return TestClient(create_app(app_container=app))


def login_headers(client, username: str = "admin", password: str = "admin123") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def submit_leave(client, headers, start=_D(0), end=_D(1), key=None):
    body = {
        "applicant_id": "S10001",
        "process_type": "leave",
        "payload": {"leave_type": "personal", "start_date": start, "end_date": end, "reason": "个人事务"},
    }
    if key:
        body["client_request_no"] = key
    return client.post("/api/v1/requests", json=body, headers=headers)


def _setup_class_with_student(client, admin_h, class_id, counselor_id, student_id):
    r = client.post("/api/v1/admin/classes", json={
        "class_id": class_id, "grade": "2024", "major": "软件工程", "name": "01班",
        "counselor_id": counselor_id,
    }, headers=admin_h)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/admin/students/{student_id}/assign-class", json={"class_id": class_id},
                    headers=admin_h)
    assert r.status_code == 200, r.text


# ----------------------------------------------------------------------
# 1. S1：编排接口 status 越权读（IDOR）
# ----------------------------------------------------------------------
def test_agent_run_status_idor_blocked(client):
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")
    rn = submit_leave(client, h1).json()["request_no"]

    # 他人走编排 status → 403（与直接端点同口径）
    r = client.post("/api/v1/agent/run", json={"intent": "status", "request_no": rn}, headers=h2)
    assert r.status_code == 403
    # 申请人本人走编排 status → 200 且拿到 payload
    r2 = client.post("/api/v1/agent/run", json={"intent": "status", "request_no": rn}, headers=h1)
    assert r2.status_code == 200
    assert r2.json()["ok"] is True


# ----------------------------------------------------------------------
# 2. S2：编排接口 archive 越权归档（+ 同源 register）
# ----------------------------------------------------------------------
def test_agent_run_archive_blocked_for_student(client):
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")
    hc = login_headers(client, "C30001", "123456")
    rn = submit_leave(client, h1).json()["request_no"]
    # 合法推进到终态 approved
    r = client.post(f"/api/v1/requests/{rn}/advance", json={"approver_id": "C30001", "decision": "approve"},
                    headers=hc)
    assert r.status_code == 200

    # 学生借编排 archive → 403（权限矩阵 deny，actor 已从 JWT 取，不再借 SYS001）
    r2 = client.post("/api/v1/agent/run", json={"intent": "archive", "request_no": rn}, headers=h2)
    assert r2.status_code == 403
    after = client.get(f"/api/v1/requests/{rn}", headers=h1).json()
    assert after["status"] == "approved"
    assert after["archived_at"] is None


def test_agent_run_archive_by_admin_ok(client):
    h1 = login_headers(client, "S10001", "123456")
    hc = login_headers(client, "C30001", "123456")
    ha = login_headers(client)
    rn = submit_leave(client, h1).json()["request_no"]
    client.post(f"/api/v1/requests/{rn}/advance", json={"approver_id": "C30001", "decision": "approve"},
                headers=hc)
    r = client.post("/api/v1/agent/run", json={"intent": "archive", "request_no": rn}, headers=ha)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert client.get(f"/api/v1/requests/{rn}", headers=h1).json()["status"] == "archived"


def test_agent_run_register_blocked_for_student(client):
    """同源修复：register 意图不再静默回退 SYS001，学生借编排注册模板 → 403。"""
    h2 = login_headers(client, "S10002", "123456")
    r = client.post("/api/v1/agent/run", json={
        "intent": "register", "process_type": "custom_flow",
        "payload": {"nodes": [{"node_id": "counselor", "approver_role": "counselor"}],
                    "validation_rules": []},
    }, headers=h2)
    assert r.status_code == 403


# ----------------------------------------------------------------------
# 3. S3：对话端 auto_review 班级过滤
# ----------------------------------------------------------------------
def test_chat_auto_review_only_own_class(app, client):
    admin_h = login_headers(client)
    _setup_class_with_student(client, admin_h, "CLS-T2", "C30001", "S10001")
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")
    rn1 = submit_leave(client, h1).json()["request_no"]
    rn2 = submit_leave(client, h2, key="KEY-S10002-R2").json()["request_no"]

    sid = app.chat.create_session("C30001")["session_id"]
    answer = app.chat.ask(sid, "C30001", "自动审核待办")["answer"]
    assert "通过 1 条" in answer
    # 非本班单保持待审、未被对话端越权处理
    assert app.engine.requests.get(rn1).status == "approved"
    assert app.engine.requests.get(rn2).status == "pending_counselor"


# ----------------------------------------------------------------------
# 4. S4：待办 > 100 条不截断（最旧的本班单不被漏审）
# ----------------------------------------------------------------------
def test_auto_review_beyond_100_pending_not_truncated(app, client):
    admin_h = login_headers(client)
    _setup_class_with_student(client, admin_h, "CLS-T3", "C30001", "S10001")
    engine = app.engine
    # 测试内调高引擎限流上限（默认 60 次/分钟），避免 102 次提交被限流误伤
    engine.limiter.limit = 10000
    # 1) 本班 S10001 先提交最旧的 1 条（2 天假 → pending_counselor）
    old = engine.submit(
        applicant_id="S10001", process_type="leave",
        payload={"leave_type": "personal", "start_date": "2026-10-10",
                 "end_date": "2026-10-11", "reason": "最旧本班单"},
        client_request_no="OLD-1",
    )
    # 2) 非本班 S10002 提交 102 条（旧实现 list_all LIMIT 100 会取最新 100 条，漏掉最旧的 OLD-1）
    for i in range(102):
        engine.submit(
            applicant_id="S10002", process_type="leave",
            payload={"leave_type": "personal", "start_date": "2026-10-20",
                     "end_date": "2026-10-21", "reason": f"外班待办 {i}"},
            client_request_no=f"OUT-{i:03d}",
        )
    # 3) auto_review：只处理本班 1 条，且是最旧那条（未被 100 条截断漏掉）
    res = ApprovalService(engine).auto_review("C30001")
    assert old.request_no in res["approved"]
    assert len(res["approved"]) == 1
    # 外班 102 条全部保持 pending_counselor
    n_pending = engine.db.execute(
        "SELECT COUNT(*) AS c FROM approval_requests WHERE status='pending_counselor'"
    ).fetchone()["c"]
    assert n_pending == 102


# ----------------------------------------------------------------------
# 5. S5：form_result 消息归属校验
# ----------------------------------------------------------------------
def test_form_result_requires_owner(client, app):
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")
    sid = app.chat.create_session("S10001")["session_id"]
    mid = "MSG-OWNER-001"
    app.db.execute(
        "INSERT INTO chat_messages (id, session_id, role, content, retrieved_chunks, attachments, form_draft, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (mid, sid, "assistant", "请填写表单", "[]", "[]", '{"action":"leave"}', time.time()),
    )
    app.db.commit()
    # 他人改写 → 403
    r = client.post(f"/api/v1/chat/messages/{mid}/form-result",
                    json={"result": "ok", "request_no": "R1"}, headers=h2)
    assert r.status_code == 403
    # 本人改写 → 200
    r2 = client.post(f"/api/v1/chat/messages/{mid}/form-result",
                     json={"result": "ok", "request_no": "R1"}, headers=h1)
    assert r2.status_code == 200
    row = app.db.execute("SELECT form_draft FROM chat_messages WHERE id=?", (mid,)).fetchone()
    assert '"_submitted"' in row["form_draft"]


# ----------------------------------------------------------------------
# 6. S6：JWT 撤销 + 登录频控 + 账号枚举
# ----------------------------------------------------------------------
def test_token_invalidated_after_password_change(client, app):
    h = login_headers(client, "S10001", "123456")
    # 改密（旧 token 立即失效）
    r = client.post("/api/v1/auth/change-password",
                    json={"old_password": "123456", "new_password": "newpass888"}, headers=h)
    assert r.status_code == 200
    r2 = client.get("/api/v1/auth/me", headers=h)
    assert r2.status_code == 401


def test_token_invalidated_after_disable(client, app):
    h = login_headers(client, "S10001", "123456")
    admin_h = login_headers(client)
    uid = app.auth.login("S10001", "123456")["user_id"]
    assert client.delete(f"/api/v1/admin/students/{uid}", headers=admin_h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401


def test_login_rate_limit_locks_account(app):
    """连续 5 次失败 → 锁定：即使第 6 次密码正确也拒绝。"""
    for _ in range(5):
        with pytest.raises(AuthError):
            app.auth.login("admin", "wrong-pass")
    with pytest.raises(AuthError) as ei:
        app.auth.login("admin", "admin123")
    assert ei.value.code == "login_locked"


def test_login_unified_error_message(app):
    """账号枚举堵口：用户不存在与密码错误返回同一错误文案。"""
    with pytest.raises(AuthError) as e1:
        app.auth.login("no_such_user_xyz", "whatever")
    with pytest.raises(AuthError) as e2:
        app.auth.login("admin", "wrong-pass")
    assert e1.value.code == e2.value.code == "invalid_credentials"
    assert e1.value.message == e2.value.message == "用户名或密码错误"
