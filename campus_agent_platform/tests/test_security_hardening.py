"""安全加固回归测试（方向 A）：

覆盖本次修复的 5 项 P0：
1. 列表接口数据越权（学生不可见他人申请 / 未登录 401 / 详情越权 403）
2. auto-review 身份绑定（非辅导员 403 / 仅审本班）
3. 幂等键作用域 = 申请人（跨用户撞键不串单 / 同键重试幂等保持）
4. 上传流式限流（超大文件 413 且不落盘）+ 未登录 401
5. 管理端点仅管理员（审计 / 仪表盘非管理员 403）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from campus_agent_platform.api.app import create_app


@pytest.fixture()
def client(app):
    return TestClient(create_app(app_container=app))


def login_headers(client, username: str = "admin", password: str = "admin123") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def submit_leave(client, headers, start="2026-09-21", end="2026-09-22", key=None, leave_type="personal"):
    body = {
        "applicant_id": "S10001",
        "process_type": "leave",
        "payload": {"leave_type": leave_type, "start_date": start, "end_date": end, "reason": "个人事务"},
    }
    if key:
        body["client_request_no"] = key
    return client.post("/api/v1/requests", json=body, headers=headers)


# ----------------------------------------------------------------------
# 1. 鉴权强制：未登录访问业务端点一律 401
# ----------------------------------------------------------------------
def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/v1/requests").status_code == 401
    assert client.post("/api/v1/requests", json={
        "applicant_id": "S10001", "process_type": "leave", "payload": {}}).status_code == 401
    assert client.post("/api/v1/requests/auto-review").status_code == 401
    assert client.get("/api/v1/audit/events").status_code == 401
    assert client.get("/api/v1/dashboard/stats").status_code == 401
    assert client.post("/api/v1/agent/run", json={"intent": "status", "request_no": "x"}).status_code == 401
    r = client.post("/api/v1/upload", files={"file": ("a.png", b"x", "image/png")})
    assert r.status_code == 401


# ----------------------------------------------------------------------
# 2. 列表/详情数据越权
# ----------------------------------------------------------------------
def test_student_cannot_see_others_requests(client):
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")
    r = submit_leave(client, h1)
    assert r.status_code == 201

    # 学生不传 applicant_id：只返回自己的
    lst = client.get("/api/v1/requests", headers=h2).json()
    assert all(x["applicant_id"] == "S10002" for x in lst)
    # 学生伪造他人 applicant_id：仍看不到
    lst2 = client.get("/api/v1/requests?applicant_id=S10001", headers=h2).json()
    assert all(x["applicant_id"] == "S10002" for x in lst2)
    # 学生查他人单详情：403
    rn = r.json()["request_no"]
    assert client.get(f"/api/v1/requests/{rn}", headers=h2).status_code == 403


def test_admin_sees_all(client):
    h_stu = login_headers(client, "S10001", "123456")
    submit_leave(client, h_stu)
    h_admin = login_headers(client)
    lst = client.get("/api/v1/requests", headers=h_admin).json()
    assert len(lst) == 1


# ----------------------------------------------------------------------
# 3. auto-review：仅辅导员 + 仅本班
# ----------------------------------------------------------------------
def _setup_class_with_student(client, admin_h, class_id, counselor_id, student_id):
    r = client.post("/api/v1/admin/classes", json={
        "class_id": class_id, "grade": "2024", "major": "软件工程", "name": "01班",
        "counselor_id": counselor_id,
    }, headers=admin_h)
    assert r.status_code == 201, r.text
    r = client.post(f"/api/v1/admin/students/{student_id}/assign-class", json={"class_id": class_id},
                    headers=admin_h)
    assert r.status_code == 200, r.text


def test_auto_review_requires_counselor(client):
    h_stu = login_headers(client, "S10001", "123456")
    assert client.post("/api/v1/requests/auto-review", headers=h_stu).status_code == 403
    h_admin = login_headers(client)
    assert client.post("/api/v1/requests/auto-review", headers=h_admin).status_code == 403


def test_auto_review_only_own_class(client):
    admin_h = login_headers(client)
    _setup_class_with_student(client, admin_h, "CLS-T1", "C30001", "S10001")
    # S10002 不入班；C30001 只该审 S10001
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")
    r1 = submit_leave(client, h1)
    r2 = submit_leave(client, h2, key="KEY-S10002")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r2.json()["applicant_id"] == "S10002"

    h_c = login_headers(client, "C30001", "123456")
    res = client.post("/api/v1/requests/auto-review", headers=h_c).json()
    # S10001 的单被处理，S10002 的单因非本班被跳过
    assert r1.json()["request_no"] in res["approved"]
    assert any(s["request_no"] == r2.json()["request_no"] for s in res["skipped"])


# ----------------------------------------------------------------------
# 4. 幂等键作用域 = 申请人
# ----------------------------------------------------------------------
def test_idempotency_key_scoped_to_applicant(client):
    h1 = login_headers(client, "S10001", "123456")
    h2 = login_headers(client, "S10002", "123456")

    r_a = submit_leave(client, h1, key="SHARED-KEY")
    assert r_a.status_code == 201
    # 另一学生用同一键：不返回 S10001 的单，而是自己的新单
    r_b = submit_leave(client, h2, key="SHARED-KEY")
    assert r_b.status_code == 201
    assert r_b.json()["request_no"] != r_a.json()["request_no"]
    assert r_b.json()["applicant_id"] == "S10002"
    # 同一人同键重试：幂等返回原单
    r_a2 = submit_leave(client, h1, key="SHARED-KEY")
    assert r_a2.json()["request_no"] == r_a.json()["request_no"]
    assert r_a2.status_code == 201


# ----------------------------------------------------------------------
# 5. 上传：超大文件 413 且不落盘
# ----------------------------------------------------------------------
def test_upload_rejects_oversize_without_writing(client, app):
    h = login_headers(client)
    uploads_dir = app.settings.project_root / "uploads"
    before = len(list(uploads_dir.glob("*"))) if uploads_dir.exists() else 0
    big = b"x" * (11 * 1024 * 1024)
    r = client.post("/api/v1/upload", files={"file": ("big.png", big, "image/png")}, headers=h)
    assert r.status_code == 413
    after = len(list(uploads_dir.glob("*"))) if uploads_dir.exists() else 0
    assert after == before  # 未落盘


def test_upload_ok_normal(client):
    h = login_headers(client)
    r = client.post("/api/v1/upload", files={"file": ("ok.png", b"tiny", "image/png")}, headers=h)
    assert r.status_code == 200
    assert r.json()["size"] == 4


# ----------------------------------------------------------------------
# 6. 管理端点仅管理员
# ----------------------------------------------------------------------
def test_admin_endpoints_forbidden_for_student(client):
    h = login_headers(client, "S10001", "123456")
    assert client.get("/api/v1/audit/events", headers=h).status_code == 403
    assert client.get("/api/v1/dashboard/stats", headers=h).status_code == 403
    assert client.get("/api/v1/admin/students", headers=h).status_code == 403
