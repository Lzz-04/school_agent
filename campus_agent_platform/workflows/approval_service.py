"""审批服务层：跨入口复用的审批业务（当前为 auto_review 统一入口）。

背景（S3/S4 修复）：API 端 auto_review 与对话端 _run_auto_review 曾各写一份
班级过滤逻辑，且都基于 requests.list_all() 全表遍历（LIMIT 100，待办超 100 条
会漏审旧单）。此处收敛为单一入口 + 按 status/班级直接 SQL 查询，
两处调用方行为一致，班级归属校验只维护一份。
"""

from __future__ import annotations

from ..domain import constants as C
from . import rules as R
from .engine import WorkflowEngine


class ApprovalService:
    """审批服务：以 engine 为唯一写入口，提供跨端复用的审批操作。"""

    def __init__(self, engine: WorkflowEngine):
        self.engine = engine

    # ------------------------------------------------------------------
    def auto_review(self, approver_id: str) -> dict:
        """辅导员自动审核本班待办请假单（API 端与对话端共用）。

        - 仅处理 status=pending_counselor 且申请人属于该辅导员所带班级的请假单；
        - 按 SQL 直查（走 status/班级索引），不遍历全校、不受 list_all LIMIT 100 截断；
        - 通过/驳回走 engine.advance（权限矩阵 + 乐观锁兜底）。
        """
        db = self.engine.db
        rows = db.execute(
            "SELECT class_id FROM classes WHERE counselor_id=?", (approver_id,)
        ).fetchall()
        my_class_ids = {r["class_id"] for r in rows if r["class_id"]}
        pending = self.engine.requests.list_pending_leave_by_class(my_class_ids)

        approves: list[str] = []
        rejects: list[dict] = []
        skipped: list[dict] = []
        for r in pending:
            if r.process_type != "leave":
                continue
            if r.status != f"{C.STATUS_PENDING_PREFIX}counselor":
                continue
            violations, days = R.evaluate_leave_auto_review(
                r.payload or {}, r.attachment_urls or []
            )
            if days > 7:
                skipped.append({"request_no": r.request_no,
                                "reason": f"请假{days}天，需学校领导审批"})
                continue
            if violations:
                try:
                    self.engine.advance(
                        request_no=r.request_no, approver_id=approver_id,
                        decision="reject", comment="自动驳回：" + "；".join(violations),
                    )
                    rejects.append({"request_no": r.request_no, "reasons": violations})
                except Exception as e:  # noqa: BLE001 - 单条失败不阻断批量
                    skipped.append({"request_no": r.request_no, "reason": str(e)})
                continue
            try:
                self.engine.advance(
                    request_no=r.request_no, approver_id=approver_id,
                    decision="approve", comment="自动通过：符合规则",
                )
                approves.append(r.request_no)
            except Exception as e:  # noqa: BLE001
                skipped.append({"request_no": r.request_no, "reason": str(e)})
        return {"approved": approves, "rejected": rejects, "skipped": skipped}
