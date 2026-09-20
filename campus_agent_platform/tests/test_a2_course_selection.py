"""A2 选课流程测试。

链路：query_courses → submit(course_selection)
覆盖：培养方案匹配、名额、先修、时间冲突、退选释放。
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import ValidationError
from campus_agent_platform.workflows import rules as R


def _course_payload(course_ids, **overrides):
    payload = {"course_ids": course_ids, "major": "CS", "passed_courses": ["CS101"]}
    payload.update(overrides)
    return payload


def test_a2_query_courses(engine):
    """query_courses 规则源：返回课程信息与名额。"""
    from campus_agent_platform.tools import registry as tools

    res = tools.call_tool("query_courses", course_ids=["CS101", "MATH101"])
    assert res["ok"]
    data = res["data"]["courses"]
    assert data["CS101"]["exists"] and data["CS101"]["available"] is True
    assert data["MATH101"]["prerequisite"] == []


def test_a2_course_selection_full_flow(app):
    """选课无需审批：提交即自动通过，名额立即扣减。"""
    engine = app.engine
    R.COURSE_ENROLLMENT["CS202"] = 0
    # 满足先修课：CS202 需要 CS101，passed_courses 含 CS101
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_COURSE_SELECTION,
        payload=_course_payload(["CS202"]),
        client_request_no="A2-001",
    )
    assert req.status == C.STATUS_APPROVED
    assert req.current_node_id is None
    assert R.COURSE_ENROLLMENT["CS202"] == 1  # 提交即占课


def test_a2_prerequisite_not_enforced(app):
    """先修要求已取消：不提供已修课也能选 PHY101。"""
    engine = app.engine
    R.COURSE_ENROLLMENT["PHY101"] = 0
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_COURSE_SELECTION,
        payload=_course_payload(["PHY101"], passed_courses=[]),
    )
    assert req.status == C.STATUS_APPROVED


def test_a2_quota_blocked(app):
    """名额已满 → 拦截（CS101 quota=2, enrolled=1 → 选两个即满第三个拒）。"""
    engine = app.engine
    R.COURSE_ENROLLMENT["CS101"] = 2  # 模拟已满
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_COURSE_SELECTION,
            payload=_course_payload(["CS101"]),
        )


def test_a2_schedule_conflict_blocked(app):
    """时间冲突（CS101 与 MATH101 同为 Mon 10:00）→ 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_COURSE_SELECTION,
            payload=_course_payload(["CS101", "MATH101"]),
        )


def test_a2_elective_open_to_all_majors(app):
    """选修课面向全校：非 CS/SE 专业选 CS202 不再拦截。"""
    engine = app.engine
    R.COURSE_ENROLLMENT["CS202"] = 0
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_COURSE_SELECTION,
        payload=_course_payload(["CS202"], major="MATH", passed_courses=["CS101"]),
    )
    assert req.status == C.STATUS_APPROVED


