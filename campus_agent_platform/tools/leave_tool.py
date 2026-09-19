"""对话工具：从自然语言抽取的参数提交请假申请，返回可读结果。"""

from __future__ import annotations

from datetime import date, datetime

from ..workflows.engine import WorkflowEngine as ApprovalEngine  # 兼容别名
from ..domain import constants as C


def _to_date(s: str) -> str:
    """接受 2026-10-01 / 2026/10/1 / 10月1日 等常见写法，归一化为 YYYY-MM-DD。"""
    s = s.strip().replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    # 中文无年份：默认今年
    parts = [p for p in s.split("-") if p]
    if len(parts) == 2:
        parts = [str(date.today().year)] + parts
    if len(parts) != 3:
        raise ValueError(f"无法解析日期: {s}")
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    return date(y, m, d).isoformat()


def submit_leave_via_chat(engine: ApprovalEngine, *, student_id: str,
                          start_date: str, end_date: str, reason: str) -> dict:
    """对话侧提交请假。返回 {ok, message, request_no, status, days, next_approver}。"""
    try:
        s = _to_date(start_date)
        e = _to_date(end_date)
    except Exception as ex:
        return {"ok": False, "message": f"日期解析失败：{ex}"}

    if e < s:
        return {"ok": False, "message": "结束日期早于开始日期，请检查。"}

    days = (datetime.fromisoformat(e) - datetime.fromisoformat(s)).days + 1
    payload = {"start_date": s, "end_date": e, "reason": reason or "个人原因"}
    try:
        req = engine.submit(
            applicant_id=student_id,
            process_type=C.PROCESS_LEAVE,
            payload=payload,
            client_request_no=f"CHAT-{student_id}-{s}-{e}",
        )
    except Exception as ex:
        return {"ok": False, "message": f"提交失败：{ex}"}

    # 推断接下来谁审
    if req.status == C.STATUS_APPROVED:
        nxt = "无需审批，已自动通过"
    else:
        node = next((n for n in (req.resolved_nodes or []) if n.get("node_id") == req.current_node_id), None)
        role = (node or {}).get("approver_role", req.current_node_id)
        role_cn = {"counselor": "辅导员", "college_admin": "学院领导", "university_leader": "学校领导"}.get(role, role)
        nxt = f"等待{role_cn}审批"

    msg = (
        f"✅ 请假申请已提交\n"
        f"单号：{req.request_no}\n"
        f"时间：{s} ~ {e}（共 {days} 天）\n"
        f"原因：{payload['reason']}\n"
        f"状态：{req.status}\n"
        f"下一步：{nxt}"
    )
    return {"ok": True, "message": msg, "request_no": req.request_no,
            "status": req.status, "days": days, "next_approver": nxt}
