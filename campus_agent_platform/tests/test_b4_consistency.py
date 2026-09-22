"""B4 数据一致性测试。

覆盖：流程后申请单 / 审批链 / 审计日志一致；
     幂等（client_request_no 去重、归档幂等）；
     乐观锁并发双审（后到者 409）。
用 5 天请假（辅导员→学院两节点）保持两次审批的断言。
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import OptimisticLockError, PermissionDeniedError

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


def _submit_leave(engine, client_no=None, days=5):
    return engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": _D(0),
                 "end_date": f"2026-09-{20 + days}", "reason": "就医"},
        client_request_no=client_no,
    )


def test_b4_state_records_audit_consistent(app):
    """全流程后：申请单状态、审批链、审计日志一一对应。"""
    engine = app.engine
    req = _submit_leave(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    req = engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)
    req = engine.archive(request_no=req.request_no, actor_id="SYS001")

    view = engine.status_view(req.request_no)
    assert view["status"] == C.STATUS_ARCHIVED
    assert len(view["records"]) == 2  # 两个节点两次审批

    assert [r["decision"] for r in view["records"]] == ["approve", "approve"]

    events = engine.audit.list_by_entity(req.request_no)
    event_types = [e.event_type for e in events]
    assert C.EVENT_REQUEST_SUBMITTED in event_types
    assert event_types.count(C.EVENT_REQUEST_ADVANCED) == 2
    assert C.EVENT_REQUEST_ARCHIVED in event_types

    assert engine.audit.count() >= 4


def test_b4_client_request_no_idempotent(app):
    """同一 client_request_no 重复提交 → 返回同一记录，不产生重复。"""
    engine = app.engine
    r1 = _submit_leave(engine, client_no="IDEM-001")
    r2 = _submit_leave(engine, client_no="IDEM-001")
    assert r1.request_no == r2.request_no
    assert len(engine.requests.list_by_applicant("S10001")) == 1


def test_b4_archive_idempotent(app):
    """归档幂等：同单归档返回同一 hash。"""
    engine = app.engine
    req = _submit_leave(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    req = engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)
    a1 = engine.archive(request_no=req.request_no, actor_id="SYS001")
    a2 = engine.archive(request_no=req.request_no, actor_id="SYS001")
    assert a1.archive_hash == a2.archive_hash


def test_b4_archive_timestamp_written(app):
    """回归：归档时间戳必须落库（archived_at 非空，且与更新时间一致）。"""
    engine = app.engine
    req = _submit_leave(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    req = engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)
    req = engine.archive(request_no=req.request_no, actor_id="SYS001")
    assert req.archived_at is not None, "归档后 archived_at 必须写入"
    assert req.archived_at == req.updated_at, "归档时间戳应与更新时间一致"
    # 从库中重读，确认已落库而非仅内存值
    again = engine.requests.get(req.request_no)
    assert again.archived_at == req.archived_at


def test_b4_optimistic_lock_conflict(app):
    """乐观锁：并发双审（后到者基于旧版本）→ 0 行更新（引擎据此 409）。"""
    engine = app.engine
    req = _submit_leave(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    assert req.version == 1
    assert req.status == "pending_college"

    # 并发第二写：仍携带旧版本 0 → 乐观锁冲突（rowcount=0）
    rowcount = engine.requests.update_status(
        req.request_no, C.STATUS_REJECTED, None, expected_version=0,
    )
    assert rowcount == 0
    after = engine.requests.get(req.request_no)
    assert after.status == "pending_college" and after.version == 1


def test_b4_duplicate_advance_blocked(app):
    """同审批人对同一节点二次 approve → 被拦截（节点已流转，非当前审批人）。"""
    engine = app.engine
    req = _submit_leave(engine)
    engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)

    with pytest.raises(PermissionDeniedError):
        # 辅导员已不在当前节点（现在是 pending_college），再次以辅导员审批被权限拦截
        engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
