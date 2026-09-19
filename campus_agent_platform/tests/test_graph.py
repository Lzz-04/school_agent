"""LangGraph 编排图测试：5 Agent / 8 条链路 / step_count 防护。"""

from __future__ import annotations

from campus_agent_platform.domain import constants as C


def test_graph_submit_flow(graph):
    """submit 意图：supervisor → data_specialist → communication_specialist → END。"""
    result = graph.run(
        intent="submit",
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-21",
                 "end_date": "2026-09-22", "reason": "就医"},
        client_request_no="GRAPH-001",
    )
    assert result["ok"] is True
    assert result["request_no"]
    assert "validate_rules" in result["completed_tasks"]
    assert "notify_stakeholders" in result["completed_tasks"]
    assert result["context"]["submit"]["status"] == "pending_counselor"


def test_graph_submit_invalid_payload(graph, app):
    """非法 payload → 提交阶段即被拦截，不进入审批链。"""
    result = graph.run(
        intent="submit",
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2000-01-01",
                 "end_date": "2000-01-02", "reason": "x"},
    )
    assert result["ok"] is False
    assert "校验" in result["error"]
    # 校验失败发生在落库前：无申请进入审批链
    assert len(app.engine.requests.list_all()) == 0


def test_graph_advance_flow(graph, app):
    """advance 意图：supervisor 推进状态 + 通知。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-21",
                 "end_date": "2026-09-25", "reason": "就医"},
    )
    result = graph.run(
        intent="advance",
        request_no=req.request_no,
        approver_id="C30001",
        decision=C.DECISION_APPROVE,
        comment="同意",
    )
    assert result["ok"] is True
    assert result["context"]["advance"]["status"] == "pending_college"


def test_graph_archive_flow(graph, app):
    """archive 意图：file_specialist 归档。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-21",
                 "end_date": "2026-09-25", "reason": "就医"},
    )
    engine.advance(request_no=req.request_no, approver_id="C30001", decision=C.DECISION_APPROVE)
    engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)

    result = graph.run(intent="archive", request_no=req.request_no)
    assert result["ok"] is True
    assert result["context"]["archive"]["data"]["status"] == C.STATUS_ARCHIVED


def test_graph_register_flow(graph, app):
    """register 意图：development_specialist 注册新流程类型。"""
    result = graph.run(
        intent="register",
        process_type="lab_booking",
        payload={
            "nodes": [{"node_id": "advisor", "approver_role": "advisor"}],
            "validation_rules": ["date_validity"],
        },
    )
    assert result["ok"] is True
    assert result["context"]["register"]["data"]["process_type"] == "lab_booking"
    assert app.engine.templates.exists("lab_booking")


def test_graph_status_flow(graph, app):
    """status 意图：只读查询。"""
    engine = app.engine
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-21",
                 "end_date": "2026-09-22", "reason": "就医"},
    )
    result = graph.run(intent="status", request_no=req.request_no)
    assert result["ok"] is True
    assert result["result"]["data"]["request_no"] == req.request_no


def test_graph_unknown_intent(graph):
    """未知意图 → 结构化错误。"""
    result = graph.run(intent="hack", request_no="X")
    assert result["ok"] is False
    assert "未知意图" in result["error"]


def test_graph_step_count_guard(graph):
    """step_count 防护：路由目标非允许名单 → 强制 END。"""
    from campus_agent_platform.agents.supervisor_agent import route_after_supervisor
    from campus_agent_platform.agents.state import new_state

    state = new_state(intent="submit", applicant_id="S10001")
    state["next_agent"] = "evil_agent"
    assert route_after_supervisor(state) == "END"
