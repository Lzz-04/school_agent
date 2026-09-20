"""方向 B：对话 → 全流程表单草稿测试（选课 / 报销 / 场地预约）。

验证通用表单管道（FORM_SPECS）：
- 各 action 生成正确草稿（process_type + fields），不直接提交申请
- 非法输入被代码层拦截：不弹表单 / 返回明确提示
- 未登记的 action 原样返回 LLM 文本
"""

from __future__ import annotations

import pytest

from campus_agent_platform.rag.chat_agent import _ACTION_TO_SPEC, FORM_SPECS


@pytest.fixture()
def chat(app):
    c = app.chat
    c.user_id = "S10001"
    return c


def request_count(app) -> int:
    return app.db.execute("SELECT COUNT(*) AS c FROM approval_requests").fetchone()["c"]


# ----------------------------------------------------------------------
# 表单契约完整性
# ----------------------------------------------------------------------
def test_all_flow_types_have_action(app):
    """四个流程都在 FORM_SPECS 注册，action 不重复。"""
    assert set(FORM_SPECS) == {"leave", "course_selection", "reimbursement", "venue_reservation"}
    actions = [s["action"] for s in FORM_SPECS.values()]
    assert len(actions) == len(set(actions)) == 4


# ----------------------------------------------------------------------
# 选课
# ----------------------------------------------------------------------
def test_course_selection_draft(chat, app):
    raw = '{"action":"submit_course_selection","course_ids":["CS101","MATH101"],"reason":"补修"}'
    msg = chat._maybe_run_tool(raw)
    draft = chat._pending_draft
    assert draft["process_type"] == "course_selection"
    assert draft["fields"]["course_ids"] == ["CS101", "MATH101"]
    assert "选课申请表单" in msg
    assert request_count(app) == 0  # 不直接提交


def test_course_selection_dedup_and_upper(chat):
    raw = '{"action":"submit_course_selection","course_ids":["cs101","CS101"],"reason":""}'
    chat._maybe_run_tool(raw)
    assert chat._pending_draft["fields"]["course_ids"] == ["CS101"]
    # 超 5 门拦截（校验失败不产生新草稿）
    chat._pending_draft = None
    raw6 = '{"action":"submit_course_selection","course_ids":["CS101","MATH101","PHY101","ART101","CS202","A2"],"reason":""}'
    msg = chat._maybe_run_tool(raw6)
    assert "5 门" in msg
    assert chat._pending_draft is None


def test_course_selection_unknown_course(chat):
    raw = '{"action":"submit_course_selection","course_ids":["CS999"],"reason":""}'
    msg = chat._maybe_run_tool(raw)
    assert "不存在" in msg
    assert "CS101" in msg  # 提示里带可选课程目录
    assert chat._pending_draft is None


def test_course_selection_missing_courses(chat):
    raw = '{"action":"submit_course_selection","course_ids":[],"reason":""}'
    msg = chat._maybe_run_tool(raw)
    assert "请告诉我想选的课程" in msg
    assert chat._pending_draft is None


# ----------------------------------------------------------------------
# 报销（报销仅教职工可发起：草稿层角色兜底与学生端禁报销一致）
# ----------------------------------------------------------------------
def test_reimbursement_draft(chat, app):
    chat.user_id = "C30001"  # 辅导员（教职工）可发起报销
    raw = '{"action":"submit_reimbursement","amount":120,"category":"textbook","reason":"购买教材"}'
    msg = chat._maybe_run_tool(raw)
    draft = chat._pending_draft
    assert draft["process_type"] == "reimbursement"
    assert draft["fields"]["amount"] == 120.0
    assert draft["fields"]["category"] == "textbook"
    assert "报销申请表单" in msg
    assert request_count(app) == 0


def test_reimbursement_chinese_category_mapped(chat):
    chat.user_id = "C30001"
    raw = '{"action":"submit_reimbursement","amount":500,"category":"差旅","reason":"出差"}'
    chat._maybe_run_tool(raw)
    assert chat._pending_draft["fields"]["category"] == "travel"


def test_reimbursement_invalid_amount(chat):
    chat.user_id = "C30001"
    raw = '{"action":"submit_reimbursement","amount":-10,"category":"textbook","reason":""}'
    msg = chat._maybe_run_tool(raw)
    assert "大于 0" in msg
    raw2 = '{"action":"submit_reimbursement","amount":"abc","category":"textbook","reason":""}'
    msg2 = chat._maybe_run_tool(raw2)
    assert "金额格式不正确" in msg2
    assert chat._pending_draft is None


def test_reimbursement_unknown_category(chat):
    chat.user_id = "C30001"
    raw = '{"action":"submit_reimbursement","amount":100,"category":"food","reason":""}'
    msg = chat._maybe_run_tool(raw)
    assert "不支持" in msg
    assert chat._pending_draft is None


def test_reimbursement_student_blocked(chat):
    """学生端禁报销：即使 LLM 输出报销 JSON，草稿层也确定性拦截（与引擎 submit 403 一致）。"""
    chat.user_id = "S10001"
    raw = '{"action":"submit_reimbursement","amount":120,"category":"textbook","reason":"购买教材"}'
    msg = chat._maybe_run_tool(raw)
    assert "暂不支持报销" in msg
    assert chat._pending_draft is None


# ----------------------------------------------------------------------
# 场地预约
# ----------------------------------------------------------------------
def test_venue_draft(chat, app):
    raw = ('{"action":"submit_venue_reservation","venue_type":"activity_room",'
           '"start_time":"2026-10-01 14:00","end_time":"2026-10-01 16:00",'
           '"purpose":"班级团建","participants":30}')
    msg = chat._maybe_run_tool(raw)
    draft = chat._pending_draft
    assert draft["process_type"] == "venue_reservation"
    assert draft["fields"]["venue_type"] == "activity_room"
    assert draft["fields"]["participants"] == 30
    assert "场地预约表单" in msg
    assert request_count(app) == 0


def test_venue_chinese_type_mapped(chat):
    raw = ('{"action":"submit_venue_reservation","venue_type":"教室",'
           '"start_time":"2026-10-02 09:00","end_time":"2026-10-02 11:00",'
           '"purpose":"班会","participants":40}')
    chat._maybe_run_tool(raw)
    assert chat._pending_draft["fields"]["venue_type"] == "classroom"


def test_venue_invalid(chat):
    # 非法类型
    raw = ('{"action":"submit_venue_reservation","venue_type":"体育馆",'
           '"start_time":"2026-10-01 14:00","end_time":"2026-10-01 16:00",'
           '"purpose":"活动","participants":10}')
    assert "选择要预约的场地" in chat._maybe_run_tool(raw)
    # 时间倒挂
    raw2 = ('{"action":"submit_venue_reservation","venue_type":"activity_room",'
            '"start_time":"2026-10-01 16:00","end_time":"2026-10-01 14:00",'
            '"purpose":"活动","participants":10}')
    assert "晚于开始时间" in chat._maybe_run_tool(raw2)
    # 缺人数
    raw3 = ('{"action":"submit_venue_reservation","venue_type":"activity_room",'
            '"start_time":"2026-10-01 14:00","end_time":"2026-10-01 16:00",'
            '"purpose":"活动"}')
    assert "参加人数" in chat._maybe_run_tool(raw3)
    # 缺用途
    raw4 = ('{"action":"submit_venue_reservation","venue_type":"activity_room",'
            '"start_time":"2026-10-01 14:00","end_time":"2026-10-01 16:00",'
            '"participants":10}')
    assert "主题/用途" in chat._maybe_run_tool(raw4)
    assert chat._pending_draft is None


def test_venue_past_date_rejected(chat):
    raw = ('{"action":"submit_venue_reservation","venue_type":"activity_room",'
           '"start_time":"2020-01-01 14:00","end_time":"2020-01-01 16:00",'
           '"purpose":"活动","participants":10}')
    msg = chat._maybe_run_tool(raw)
    assert "早于今天" in msg
    assert chat._pending_draft is None


# ----------------------------------------------------------------------
# 通用管道行为
# ----------------------------------------------------------------------
def test_unknown_action_passthrough(chat):
    """未登记的 action：原样返回 LLM 文本，不弹表单。"""
    raw = '{"action":"submit_flight_ticket","destination":"北京"}'
    assert chat._maybe_run_tool(raw) == raw
    assert chat._pending_draft is None


def test_draft_not_created_without_engine(chat):
    """没有引擎（纯问答模式）时不处理 action。"""
    from campus_agent_platform.rag import ChatAgent
    bare = ChatAgent(chat.db, chat.retriever, engine=None, user_id="S10001")
    raw = '{"action":"submit_leave","start_date":"2026-10-01","end_date":"2026-10-02","reason":"病假"}'
    assert bare._maybe_run_tool(raw) == raw
    assert bare._pending_draft is None


def test_leave_still_works_after_refactor(chat):
    """重构后请假行为不变（回归）。"""
    raw = '{"action":"submit_leave","start_date":"2026-10-01","end_date":"2026-10-03","reason":"事假"}'
    msg = chat._maybe_run_tool(raw)
    draft = chat._pending_draft
    assert draft["process_type"] == "leave"
    assert draft["fields"]["leave_type"] == "personal"
    assert draft["fields"]["end_date"] == "2026-10-03"
    assert "表单" in msg


def test_action_to_spec_lookup_complete():
    """_ACTION_TO_SPEC 覆盖全部 FORM_SPECS。"""
    assert set(_ACTION_TO_SPEC) == {s["action"] for s in FORM_SPECS.values()}
    for action, (ptype, spec) in _ACTION_TO_SPEC.items():
        assert FORM_SPECS[ptype] is spec
