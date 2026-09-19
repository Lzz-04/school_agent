"""红牌穿透测试（设计文档 7「可推翻性」）。

必须击穿四类错误：
1. 跳过审批节点（学院直接审批）
2. 异常输入放行（非法数据进入审批链）
3. 状态不一致（越权推进 / 终态再操作）
4. 权限绕过（非审批人伪造审批）
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import (
    PermissionDeniedError,
    StateTransitionError,
    ValidationError,
)


def _submit_leave(engine, applicant="S10001"):
    return engine.submit(
        applicant_id=applicant,
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-21",
                 "end_date": "2026-09-22", "reason": "就医"},
    )


def test_red_flag_skip_approval_node(app):
    """红牌①：跳过审批节点——学院管理员直接审批未过辅导员的单 → 拦截。"""
    engine = app.engine
    req = _submit_leave(engine)
    assert req.status == "pending_counselor"
    with pytest.raises(PermissionDeniedError):
        engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)


def test_red_flag_invalid_input_passes(app):
    """红牌②：异常输入放行——非法申请必须被拒绝进入审批链。"""
    engine = app.engine
    cases = [
        {"process_type": C.PROCESS_LEAVE,
         "payload": {"start_date": "1999-01-01", "end_date": "1999-01-02", "reason": "x"}},
        {"process_type": C.PROCESS_REIMBURSEMENT,
         "payload": {"category": "textbook", "amount": -1.0, "receipts": []}},
        {"process_type": C.PROCESS_COURSE_SELECTION,
         "payload": {"course_ids": ["UNKNOWN_COURSE"], "major": "CS", "passed_courses": []}},
    ]
    for case in cases:
        with pytest.raises(ValidationError):
            engine.submit(applicant_id="S10001", **case)
    # 校验失败发生在落库前，无任何申请进入审批链
    assert len(engine.requests.list_all()) == 0


def test_red_flag_state_inconsistency(app):
    """红牌③：状态不一致——终态再操作 / 非待审节点推进 → 拦截。"""
    engine = app.engine
    req = _submit_leave(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    # 2 天请假辅导员即末节点 → approved（终态）
    assert req.status == C.STATUS_APPROVED

    # 终态再审批 → 拦截
    with pytest.raises(StateTransitionError):
        engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)

    # 未归档终态不可归档拦截（非终态也不可归档：draft 不可归档）
    draft = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-23",
                 "end_date": "2026-09-24", "reason": "x"},
    )
    with pytest.raises(StateTransitionError):
        engine.archive(request_no=draft.request_no, actor_id="SYS001")


def test_red_flag_permission_bypass(app):
    """红牌④：权限绕过——伪造审批人 / 学生越权 → 拦截。"""
    engine = app.engine
    req = _submit_leave(engine)
    # 学生伪装导师审批
    with pytest.raises(PermissionDeniedError):
        engine.advance(request_no=req.request_no, approver_id="S10001", decision=C.DECISION_APPROVE)
    # 无角色账号
    with pytest.raises(PermissionDeniedError):
        engine.advance(request_no=req.request_no, approver_id="INTRUDER", decision=C.DECISION_APPROVE)
    # 归档越权（学生归档）
    with pytest.raises(PermissionDeniedError):
        engine.archive(request_no=req.request_no, actor_id="S10001")
