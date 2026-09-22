"""B3 流程回退测试。

覆盖：驳回 / 退回后状态正确回退、通知发出。
请假动态链：2 天=辅导员单节点；5 天=辅导员→学院。
"""

from __future__ import annotations

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import StateTransitionError

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


def _submit_short(engine):
    """2 天请假：仅辅导员节点。"""
    return engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": _D(0),
                 "end_date": _D(1), "reason": "就医"},
    )


def _submit_medium(engine):
    """5 天请假：辅导员→学院。"""
    return engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": _D(0),
                 "end_date": _D(4), "reason": "就医"},
    )


def test_b3_reject_terminates(app):
    """辅导员 reject → rejected（终止）。"""
    engine = app.engine
    req = _submit_short(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001",
                         decision=C.DECISION_REJECT, comment="理由不足")
    assert req.status == C.STATUS_REJECTED

    # 终态不可再审批
    try:
        engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)
        assert False, "终态不可再审批"
    except StateTransitionError:
        pass


def test_b3_return_from_college_to_counselor(app):
    """学院 return → 回退到辅导员节点（pending_counselor），可再次审批。"""
    engine = app.engine
    req = _submit_medium(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    assert req.status == "pending_college"

    req = engine.advance(request_no=req.request_no, approver_id="A20001",
                         decision=C.DECISION_RETURN, comment="材料不全退回")
    assert req.status == "pending_counselor"
    assert req.current_node_id == "counselor"

    # 辅导员可再次审批（回退后可继续流转）
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    assert req.status == "pending_college"


def test_b3_return_from_counselor_to_draft(app):
    """辅导员（首节点）return → draft（退回重填）。"""
    engine = app.engine
    req = _submit_short(engine)
    req = engine.advance(request_no=req.request_no, approver_id="C30001",
                         decision=C.DECISION_RETURN, comment="信息有误请重填")
    assert req.status == C.STATUS_DRAFT
    assert req.current_node_id is None


def test_b3_notifications_on_return(app):
    """退回后通知申请人（outbox 有记录）。"""
    engine = app.engine
    req = _submit_short(engine)
    before = engine.outbox.count_pending()
    engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_RETURN)
    after = engine.outbox.count_pending()
    assert after > before  # 退回产生新通知


def test_b3_multi_return_chain(app):
    """多次回退：学院 return 辅导员、辅导员再 return draft。"""
    engine = app.engine
    req = _submit_medium(engine)
    engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    req = engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_RETURN)
    assert req.status == "pending_counselor"
    req = engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_RETURN)
    assert req.status == C.STATUS_DRAFT
