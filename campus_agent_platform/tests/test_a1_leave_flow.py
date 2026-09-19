"""A1 请假全流程测试（设计文档第 7 节）。

请假审批链按天数动态分级（业务规则）：
  - 所有请假：辅导员必审
  - > 3 天：追加学院领导
  - > 7 天：追加学校领导

本文件覆盖三档：
  A1a  ≤3 天 → 辅导员单节点
  A1b  4~7 天 → 辅导员 + 学院领导
  A1c  >7 天 → 辅导员 + 学院领导 + 学校领导
"""

from __future__ import annotations

from datetime import date, timedelta

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import ValidationError
from campus_agent_platform.workflows import rules as R


def _leave_payload(days: int = 2, start: str | None = None, **overrides):
    """构造请假 payload，从明天起连续 days 天。"""
    if start is None:
        start_d = date.today() + timedelta(days=1)
        start = start_d.isoformat()
        end = (start_d + timedelta(days=days - 1)).isoformat()
    else:
        start_d = date.fromisoformat(start)
        end = (start_d + timedelta(days=days - 1)).isoformat()
    payload = {
        "leave_type": "sick",
        "start_date": start,
        "end_date": end,
        "reason": "生病就医",
    }
    payload.update(overrides)
    return payload


# ----------------------------------------------------------------------
# A1a：≤3 天 → 辅导员单节点
# ----------------------------------------------------------------------
def test_a1_short_leave_single_node(app):
    """2 天请假：辅导员 approve 即 approved（无学院/学校节点）。"""
    engine = app.engine
    payload = _leave_payload(days=2)
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=payload,
        client_request_no="A1-SHORT",
    )
    assert req.status == "pending_counselor"
    assert req.current_node_id == "counselor"
    # 动态节点链已落库
    assert [n["node_id"] for n in req.resolved_nodes] == ["counselor"]

    # 辅导员 approve → 直接 approved（末节点）
    req = engine.advance(
        request_no=req.request_no, approver_id="C30001",
        decision=C.DECISION_APPROVE, comment="同意",
    )
    assert req.status == C.STATUS_APPROVED

    # 归档（幂等）
    req = engine.archive(request_no=req.request_no, actor_id="SYS001")
    assert req.status == C.STATUS_ARCHIVED
    assert req.archive_hash
    again = engine.archive(request_no=req.request_no, actor_id="SYS001")
    assert again.archive_hash == req.archive_hash


# ----------------------------------------------------------------------
# A1b：>3 天 → 辅导员 + 学院领导
# ----------------------------------------------------------------------
def test_a1_medium_leave_two_nodes(app):
    """5 天请假：辅导员 → 学院领导。"""
    engine = app.engine
    payload = _leave_payload(days=5)
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=payload,
        client_request_no="A1-MEDIUM",
    )
    assert req.status == "pending_counselor"
    assert [n["node_id"] for n in req.resolved_nodes] == ["counselor", "college"]

    req = engine.advance(
        request_no=req.request_no, approver_id="C30001",
        decision=C.DECISION_APPROVE, comment="同意",
    )
    assert req.status == "pending_college"

    req = engine.advance(
        request_no=req.request_no, approver_id="A20001",
        decision=C.DECISION_APPROVE, comment="同意",
    )
    assert req.status == C.STATUS_APPROVED


# ----------------------------------------------------------------------
# A1c：>7 天 → 辅导员 + 学院领导 + 学校领导
# ----------------------------------------------------------------------
def test_a1_long_leave_three_nodes(app):
    """10 天请假：辅导员 → 学院领导 → 学校领导。"""
    engine = app.engine
    payload = _leave_payload(days=10)
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=payload,
        client_request_no="A1-LONG",
    )
    assert req.status == "pending_counselor"
    assert [n["node_id"] for n in req.resolved_nodes] == ["counselor", "college", "university"]

    req = engine.advance(
        request_no=req.request_no, approver_id="C30001",
        decision=C.DECISION_APPROVE,
    )
    assert req.status == "pending_college"

    req = engine.advance(
        request_no=req.request_no, approver_id="A20001",
        decision=C.DECISION_APPROVE,
    )
    assert req.status == "pending_university"

    req = engine.advance(
        request_no=req.request_no, approver_id="U50001",
        decision=C.DECISION_APPROVE,
    )
    assert req.status == C.STATUS_APPROVED


# ----------------------------------------------------------------------
# 通知与校验
# ----------------------------------------------------------------------
def test_a1_notifications_enqueued(app):
    """2 天请假：提交通知辅导员；辅导员 approve 后无下一节点，通知申请人通过。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=_leave_payload(days=2),
    )
    assert engine.outbox.count_pending() >= 1  # 提交即通知辅导员

    engine.advance(
        request_no=req.request_no, approver_id="C30001",
        decision=C.DECISION_APPROVE,
    )
    # 末节点通过 → 通知申请人 approved
    assert engine.outbox.count_pending() >= 2


def test_a1_rule_validation_blocked(app):
    """请假时间早于今天 → 提交被拦截（B2 联动）。"""
    engine = app.engine
    try:
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_LEAVE,
            payload=_leave_payload(start="2020-01-01", days=2),
        )
        assert False, "应被规则校验拦截"
    except ValidationError as exc:
        assert any("早于今天" in v for v in exc.details["violations"])


def test_a1_leave_days_calculation():
    """天数计算：含首尾自然日。"""
    assert R.leave_days({"start_date": "2026-09-21", "end_date": "2026-09-22"}) == 2
    assert R.leave_days({"start_date": "2026-09-21", "end_date": "2026-09-25"}) == 5
    assert R.leave_days({"start_date": "2026-09-21", "end_date": "2026-09-30"}) == 10
