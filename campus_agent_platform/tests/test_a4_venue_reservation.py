"""A4 场地预约流程测试。

业务规则：
  - 填写表单：场地名称、时间、活动主题、人数、负责人、备注
  - 教室(classroom)：自动审批，即时通过（提交即 approved，无人工节点）
  - 活动室/报告厅/机房：后勤(H60001) 人工审核
  - 状态：待审核 / 已通过 / 驳回
"""

from __future__ import annotations

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import PermissionDeniedError, ValidationError
from campus_agent_platform.workflows import rules as R


def _venue_payload(venue_type: str, **overrides):
    payload = {
        "venue_name": "教室A101" if venue_type == "classroom" else "活动室B201",
        "venue_type": venue_type,
        "start_time": "2026-10-01 14:00",
        "end_time": "2026-10-01 16:00",
        "activity_theme": "项目组例会",
        "attendees": 20,
        "contact_person": "S10001",
        "note": "",
    }
    payload.update(overrides)
    return payload


def test_a4_classroom_auto_approved(app):
    """教室：提交即自动 approved，无待审节点。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_VENUE_RESERVATION,
        payload=_venue_payload("classroom"),
        client_request_no="A4-CLASS",
    )
    assert req.status == C.STATUS_APPROVED
    assert req.current_node_id is None
    assert req.resolved_nodes == []  # 空链 = 自动通过


def test_a4_activity_room_manual_review(app):
    """活动室：提交后待后勤审核，H60001 通过 → approved。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_VENUE_RESERVATION,
        payload=_venue_payload("activity_room"),
        client_request_no="A4-ACT",
    )
    assert req.status == "pending_venue"
    assert req.current_node_id == "venue"
    assert [n["node_id"] for n in req.resolved_nodes] == ["venue"]

    # 学生不能审自己的单
    try:
        engine.advance(request_no=req.request_no, approver_id="S10001",
                       decision=C.DECISION_APPROVE)
        assert False, "学生越权应被拦截"
    except PermissionDeniedError:
        pass

    # 后勤 H60001 通过
    req = engine.advance(
        request_no=req.request_no, approver_id="H60001",
        decision=C.DECISION_APPROVE, comment="同意使用",
    )
    assert req.status == C.STATUS_APPROVED


def test_a4_lecture_hall_and_computer_lab_manual(app):
    """报告厅、机房同样走后勤人工审核。"""
    engine = app.engine
    for vt in ("lecture_hall", "computer_lab"):
        req = engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_VENUE_RESERVATION,
            payload=_venue_payload(vt),
        )
        assert req.status == "pending_venue", vt
        req = engine.advance(request_no=req.request_no, approver_id="H60001",
                             decision=C.DECISION_APPROVE)
        assert req.status == C.STATUS_APPROVED, vt


def test_a4_reject_to_rejected(app):
    """后勤驳回 → rejected。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_VENUE_RESERVATION,
        payload=_venue_payload("computer_lab"),
    )
    req = engine.advance(
        request_no=req.request_no, approver_id="H60001",
        decision=C.DECISION_REJECT, comment="时段冲突",
    )
    assert req.status == C.STATUS_REJECTED


def test_a4_view_my_reservations(app):
    """「我的预约」：按申请人列出状态。"""
    engine = app.engine
    r1 = engine.submit(applicant_id="S10001", process_type=C.PROCESS_VENUE_RESERVATION,
                       payload=_venue_payload("classroom"))  # 自动 approved
    r2 = engine.submit(applicant_id="S10001", process_type=C.PROCESS_VENUE_RESERVATION,
                       payload=_venue_payload("activity_room"))  # pending_venue
    mine = engine.requests.list_by_applicant("S10001")
    statuses = {r.request_no: r.status for r in mine}
    assert statuses[r1.request_no] == C.STATUS_APPROVED
    assert statuses[r2.request_no] == "pending_venue"


def test_a4_missing_time_rejected(app):
    """缺时间字段 → 规则校验拦截。"""
    engine = app.engine
    bad = _venue_payload("activity_room")
    del bad["start_time"]
    del bad["end_time"]
    try:
        engine.submit(applicant_id="S10001", process_type=C.PROCESS_VENUE_RESERVATION,
                      payload=bad)
        assert False, "缺时间应被拦截"
    except ValidationError:
        pass


def test_a4_resolver_classification():
    """解析器单测：教室空链，其他类型单节点后勤。"""
    assert R.resolve_venue_nodes({"venue_type": "classroom"}) == []
    for vt in ("activity_room", "lecture_hall", "computer_lab"):
        nodes = R.resolve_venue_nodes({"venue_type": vt})
        assert nodes == [{"node_id": "venue", "approver_role": "logistics"}], vt
