"""F1 可观测性 + F2 审批驾驶舱：埋点记录、聚合口径、API 端点、权限。

验证契约：
1. MetricsRecorder 追加埋点 → summary 聚合（总量 / P50/P95 / 每日趋势）；
2. 对话 ask 自动埋点（延迟 / 检索命中 / LLM 使用）；
3. agent/run 自动埋点（延迟 / 意图 / 结果）；
4. /api/v1/metrics/summary 与 /api/v1/dashboard/approval-stats 仅管理员可访问；
5. ApprovalStats 按流程类型统计单量/平均耗时/积压/SLA 逾期，按审批人统计待办/已办。
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from campus_agent_platform.api.app import create_app
from campus_agent_platform.domain import constants as C
from campus_agent_platform.storage.metrics import EVENT_AGENT_RUN, EVENT_CHAT_ASK

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture()
def client(app):
    return TestClient(create_app(app_container=app))


def login_headers(client, username="admin", password="admin123") -> dict:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ----------------------------------------------------------------------
# F1：埋点记录与聚合
# ----------------------------------------------------------------------
def test_metrics_recorder_summary(app):
    m = app.metrics
    for i, (lat, tin, tout, hits) in enumerate([
        (100, 10, 20, 2), (200, 30, 40, 3), (300, 50, 60, 1),
    ]):
        m.record(event_type=EVENT_CHAT_ASK, user_id="S10001", session_id=f"S-{i}",
                 latency_ms=lat, tokens_in=tin, tokens_out=tout,
                 retrieval_hits=hits, llm_used=True)
    s = m.summary(days=7)
    assert s["total_asks"] == 3
    assert s["tokens_total"] == 210          # (10+20)+(30+40)+(50+60)
    assert s["llm_used_asks"] == 3
    assert s["p50_latency_ms"] == 200
    assert s["p95_latency_ms"] == 290        # 线性插值：0.95*(3-1)=1.9 → 200+0.9*100
    assert s["avg_retrieval_hits"] == 2.0    # (2+3+1)/3
    assert len(s["trend"]) == 7
    assert s["trend"][-1]["asks"] == 3       # 今天 3 条


def test_chat_ask_auto_records_metric(app):
    """对话 ask 后自动写入 chat_ask 埋点。"""
    sid = app.chat.create_session("S10001", "测试")["session_id"]
    app.chat.ask(sid, "S10001", "请假需要什么材料")
    row = app.db.execute(
        "SELECT event_type, user_id, session_id, latency_ms, retrieval_hits, llm_used "
        "FROM metric_events WHERE event_type=? AND session_id=?",
        (EVENT_CHAT_ASK, sid),
    ).fetchone()
    assert row is not None
    assert row["user_id"] == "S10001"
    assert row["latency_ms"] >= 0
    assert row["retrieval_hits"] >= 0


def test_agent_run_records_metric(client):
    """agent/run 后自动写入 agent_run 埋点（通过聚合端点反查）。"""
    h = login_headers(client)
    r = client.post("/api/v1/agent/run", json={
        "intent": "submit",
        "applicant_id": "S10001",
        "process_type": C.PROCESS_LEAVE,
        "payload": {"leave_type": "sick", "start_date": _D(4),
                    "end_date": _D(5), "reason": "就医"},
        "client_request_no": "OBS-AGENT-001",
    }, headers=h)
    assert r.status_code == 200
    h2 = login_headers(client)
    s = client.get("/api/v1/metrics/summary", headers=h2).json()
    assert s["total_agent_runs"] >= 1


def test_metrics_endpoint_admin_only(client):
    """metrics/summary 仅管理员可访问。"""
    h_stu = login_headers(client, "S10001", "123456")
    r = client.get("/api/v1/metrics/summary", headers=h_stu)
    assert r.status_code == 403
    h_admin = login_headers(client)
    r = client.get("/api/v1/metrics/summary", headers=h_admin)
    assert r.status_code == 200
    assert "total_asks" in r.json()


# ----------------------------------------------------------------------
# F2：审批驾驶舱
# ----------------------------------------------------------------------
def test_approval_stats_by_process_type_and_approver(app):
    """驾驶舱统计：流程类型单量/平均耗时/积压/逾期；审批人待办/已办。"""
    engine = app.engine
    # 1) 旧单（60h 前提交，pending_counselor）→ 请假 SLA 48h 逾期
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": _D(0),
                 "end_date": _D(1), "reason": "就医"},
        client_request_no="OBS-1",
    )
    app.db.execute("UPDATE approval_requests SET created_at=? WHERE request_no=?",
                   (time.time() - 60 * 3600, req.request_no))
    app.db.commit()  # G1：裸写后必须先提交，否则隐式事务会让下一个 BEGIN IMMEDIATE 失败
    # 2) 新单（未逾期）
    req2 = engine.submit(
        applicant_id="S10002",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "personal", "start_date": _D(4),
                 "end_date": _D(5), "reason": "家事"},
        client_request_no="OBS-2",
    )
    # 3) 辅导员通过新单（2 天假只有辅导员节点）→ 直接终态 approved（已办 +1）
    engine.advance(request_no=req2.request_no, approver_id="C30001",
                   decision=C.DECISION_APPROVE, comment="ok")
    app.db.commit()

    stats = app.approval_stats.stats(days=7)
    leaves = next(t for t in stats["by_process_type"] if t["process_type"] == C.PROCESS_LEAVE)
    assert leaves["count"] == 2
    assert leaves["pending"] == 1        # 仅旧单仍在 pending_counselor
    assert leaves["terminal"] == 1       # 新单已 approved
    assert leaves["overdue"] == 1        # 旧单超 48h
    assert stats["total_overdue"] == 1
    # 审批人：C30001 已办 1、待办 1（旧单仍在 counselor 节点）
    c_row = next(a for a in stats["by_approver"] if a["approver_id"] == "C30001")
    assert c_row["handled"] == 1
    assert c_row["pending"] == 1
    assert len(stats["trend"]) == 7
    # 旧单被挪到 ~2.5 天前，趋势总和 = 2 条（今天的 1 条 + 挪走日期的 1 条）
    assert sum(t["submitted"] for t in stats["trend"]) == 2


def test_approval_stats_endpoint_admin_only(client):
    """approval-stats 仅管理员可访问；结构完整。"""
    h_stu = login_headers(client, "S10001", "123456")
    r = client.get("/api/v1/dashboard/approval-stats", headers=h_stu)
    assert r.status_code == 403
    h_admin = login_headers(client)
    r = client.get("/api/v1/dashboard/approval-stats", headers=h_admin)
    assert r.status_code == 200
    body = r.json()
    assert "by_process_type" in body and "by_approver" in body and "trend" in body


# ----------------------------------------------------------------------
# F1 配套：埋点保留期清理
# ----------------------------------------------------------------------
def test_metrics_cleanup_retention(app):
    """cleanup 只删超过保留期的埋点，近 N 天保留。"""
    m = app.metrics
    m.record(event_type=EVENT_CHAT_ASK, user_id="S10001", latency_ms=10)
    # 把已写入的埋点全部挪到 100 天前（模拟历史积累）
    app.db.execute("UPDATE metric_events SET created_at=?", (time.time() - 100 * 86400,))
    app.db.commit()  # G1：裸写后必须先提交
    # 再写一条"今天"的
    m.record(event_type=EVENT_CHAT_ASK, user_id="S10002", latency_ms=20)

    deleted = m.cleanup(retention_days=90)
    assert deleted >= 1
    left = app.db.execute("SELECT COUNT(*) AS c FROM metric_events").fetchone()["c"]
    assert left == 1
    row = app.db.execute("SELECT user_id FROM metric_events").fetchone()
    assert row["user_id"] == "S10002"


def test_metrics_cleanup_endpoint_admin_only(client):
    """cleanup 端点仅管理员可访问。"""
    h_stu = login_headers(client, "S10001", "123456")
    r = client.post("/api/v1/metrics/cleanup", headers=h_stu)
    assert r.status_code == 403
    h_admin = login_headers(client)
    r = client.post("/api/v1/metrics/cleanup", json={"days": 90}, headers=h_admin)
    assert r.status_code == 200
    assert "deleted" in r.json()
