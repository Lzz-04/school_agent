"""FastAPI 接口层测试：REST 端点冒烟 + 关键业务链路（均带 JWT 登录态）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from campus_agent_platform.api.app import create_app
from campus_agent_platform.domain import constants as C


@pytest.fixture()
def client(app):
    return TestClient(create_app(app_container=app))


def login_headers(client, username: str = "admin", password: str = "admin123") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_submit_and_status(client):
    h = login_headers(client, "S10001", "123456")
    r = client.post("/api/v1/requests", json={
        "applicant_id": "S10001",
        "process_type": C.PROCESS_LEAVE,
        "payload": {"leave_type": "sick", "start_date": "2026-09-21",
                    "end_date": "2026-09-22", "reason": "就医"},
        "client_request_no": "API-001",
    }, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending_counselor"
    assert body["applicant_id"] == "S10001"

    r2 = client.get(f"/api/v1/requests/{body['request_no']}", headers=h)
    assert r2.status_code == 200
    assert r2.json()["request_no"] == body["request_no"]


def test_advance_and_archive(client):
    h_stu = login_headers(client, "S10001", "123456")
    r = client.post("/api/v1/requests", json={
        "applicant_id": "S10001",
        "process_type": C.PROCESS_LEAVE,
        "payload": {"leave_type": "sick", "start_date": "2026-09-21",
                    "end_date": "2026-09-25", "reason": "就医"},
    }, headers=h_stu)
    rn = r.json()["request_no"]

    h_c = login_headers(client, "C30001", "123456")
    r = client.post(f"/api/v1/requests/{rn}/advance", json={
        "approver_id": "C30001", "decision": C.DECISION_APPROVE, "comment": "ok",
    }, headers=h_c)
    assert r.json()["status"] == "pending_college"

    h_a = login_headers(client, "A20001", "123456")
    r = client.post(f"/api/v1/requests/{rn}/advance", json={
        "approver_id": "A20001", "decision": C.DECISION_APPROVE,
    }, headers=h_a)
    assert r.json()["status"] == C.STATUS_APPROVED

    r = client.post(f"/api/v1/requests/{rn}/archive", json={"actor_id": "A20001"}, headers=h_a)
    assert r.json()["status"] == C.STATUS_ARCHIVED


def test_permission_denied_via_api(client):
    """学生越权审批 → 403（操作人身份取自 JWT）。"""
    h = login_headers(client, "S10001", "123456")
    r = client.post("/api/v1/requests", json={
        "applicant_id": "S10001",
        "process_type": C.PROCESS_LEAVE,
        "payload": {"leave_type": "sick", "start_date": "2026-09-21",
                    "end_date": "2026-09-22", "reason": "就医"},
    }, headers=h)
    rn = r.json()["request_no"]
    r = client.post(f"/api/v1/requests/{rn}/advance", json={
        "approver_id": "C30001", "decision": C.DECISION_APPROVE,
    }, headers=h)  # JWT 是 S10001，冒充辅导员无效
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "permission_denied"


def test_process_types(client):
    h = login_headers(client)
    r = client.post("/api/v1/process-types", json={
        "process_type": "event_apply",
        "nodes": [{"node_id": "advisor", "approver_role": "advisor"}],
        "validation_rules": ["date_validity"],
        "actor_id": "SYS001",
    }, headers=h)
    assert r.status_code == 201
    assert r.json()["version"] >= 1

    r2 = client.get("/api/v1/process-types", headers=h)
    types = {t["process_type"] for t in r2.json()}
    assert "event_apply" in types


def test_courses_endpoint(client):
    r = client.get("/api/v1/courses", params={"course_ids": "CS101,MATH101"})
    assert r.status_code == 200
    data = r.json()["courses"]
    assert data["CS101"]["exists"] and data["MATH101"]["exists"]


def test_audit_events(client):
    h_stu = login_headers(client, "S10001", "123456")
    client.post("/api/v1/requests", json={
        "applicant_id": "S10001",
        "process_type": C.PROCESS_LEAVE,
        "payload": {"leave_type": "sick", "start_date": "2026-09-21",
                    "end_date": "2026-09-22", "reason": "就医"},
    }, headers=h_stu)
    h_admin = login_headers(client)
    r = client.get("/api/v1/audit/events", headers=h_admin)
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_dashboard_stats(client):
    h = login_headers(client)
    r = client.get("/api/v1/dashboard/stats", headers=h)
    assert r.status_code == 200
    assert "total_requests" in r.json()


def test_agent_run_submit(client):
    """端到端 Agent 编排：submit 意图（申请人身份取自 JWT）。"""
    h = login_headers(client)
    r = client.post("/api/v1/agent/run", json={
        "intent": "submit",
        "applicant_id": "S10001",
        "process_type": C.PROCESS_LEAVE,
        "payload": {"leave_type": "sick", "start_date": "2026-09-25",
                    "end_date": "2026-09-26", "reason": "就医"},
        "client_request_no": "API-AGENT-001",
    }, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["request_no"]
    assert "validate_rules" in body["completed_tasks"]
    assert "notify_stakeholders" in body["completed_tasks"]
