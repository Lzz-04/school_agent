"""B1 权限校验测试。

覆盖：学生尝试管理员操作被拦截、非当前节点审批人被拦截、deny by default。
请假首节点为辅导员（C30001）；2 天请假仅辅导员单节点。
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import PermissionDeniedError


def _submit_leave(engine, applicant="S10001"):
    return engine.submit(
        applicant_id=applicant,
        process_type=C.PROCESS_LEAVE,
        payload={"leave_type": "sick", "start_date": "2026-09-21",
                 "end_date": "2026-09-22", "reason": "就医"},
    )


def test_b1_student_cannot_approve(app):
    """学生尝试审批自己的申请 → 403。"""
    engine = app.engine
    req = _submit_leave(engine)
    with pytest.raises(PermissionDeniedError):
        engine.advance(request_no=req.request_no, approver_id="S10001", decision=C.DECISION_APPROVE)


def test_b1_wrong_approver_blocked(app):
    """非当前节点审批人（导师 T10002 不是辅导员）→ 403。"""
    engine = app.engine
    req = _submit_leave(engine, applicant="S10002")
    with pytest.raises(PermissionDeniedError):
        engine.advance(request_no=req.request_no, approver_id="T10002", decision=C.DECISION_APPROVE)


def test_b1_college_admin_cannot_skip(app):
    """学院管理员不能越过辅导员直接审批（跳过节点被拦截）。"""
    engine = app.engine
    req = _submit_leave(engine)
    with pytest.raises(PermissionDeniedError):
        engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)


def test_b1_check_permission_tool(app):
    """check_permission 工具断言。"""
    engine = app.engine
    req = _submit_leave(engine)

    from campus_agent_platform.tools import registry as tools
    res = tools.call_tool("check_permission", user_id="S10001", action="approve", resource_no=req.request_no)
    assert res["ok"] and res["data"]["allowed"] is False

    # 辅导员是当前节点审批人
    res2 = tools.call_tool("check_permission", user_id="C30001", action="approve", resource_no=req.request_no)
    assert res2["ok"] and res2["data"]["allowed"] is True

    # deny by default：未注册角色
    res3 = tools.call_tool("check_permission", user_id="UNKNOWN", action="view", resource_no=req.request_no)
    assert res3["ok"] and res3["data"]["allowed"] is False


def test_b1_student_cannot_archive(app):
    """学生无权归档。"""
    engine = app.engine
    req = _submit_leave(engine)
    with pytest.raises(PermissionDeniedError):
        engine.archive(request_no=req.request_no, actor_id="S10001")


def test_b1_imported_student_can_submit(app):
    """回归：管理员批量导入的学生（不在默认角色映射中）应能正常提交申请。

    此前 PermissionMatrix 仅用硬编码 default_roles（S10001/S10002…），
    批量导入的学生 user_id 无角色 → 提交被拒「无权限」。
    """
    engine = app.engine
    app.auth.add_students([{"username": "20250001", "name": "新生", "password": "123456"}])
    row = engine.db.execute(
        "SELECT user_id FROM users WHERE username='20250001'"
    ).fetchone()
    assert row is not None
    student_id = row["user_id"]
    # 确认该学生不在默认映射里（否则用例失去回归意义）
    from campus_agent_platform.workflows.engine import default_roles
    assert student_id not in default_roles()

    req = _submit_leave(engine, applicant=student_id)
    assert req.status == "pending_counselor"
    assert req.applicant_id == student_id


def test_b1_imported_student_disabled_cannot_submit(app):
    """被管理员禁用的学生 deny by default：提交申请被拦截。"""
    engine = app.engine
    app.auth.add_students([{"username": "20250002", "name": "待禁用"}])
    row = engine.db.execute(
        "SELECT user_id FROM users WHERE username='20250002'"
    ).fetchone()
    student_id = row["user_id"]
    app.auth.disable_student(student_id)
    with pytest.raises(PermissionDeniedError):
        _submit_leave(engine, applicant=student_id)
