"""审批工作流引擎（单写者）。

设计文档核心机制：
- 所有审批推进统一由本引擎执行（单写者），专业 Agent 不直接改状态
- advance_approval 非幂等写操作，乐观锁（版本号）防并发双审，后到者 409
- 所有写操作先经 RBAC check_permission（deny by default）
- submit_approval_request 带 client_request_no 去重键，重试安全
- 状态提交与通知事件同事务写入 outbox（不丢通知）
- 全操作审计 append-only
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any, Callable

from ..domain import constants as C
from ..domain.errors import (
    DuplicateRequestError,
    NotFoundError,
    OptimisticLockError,
    PermissionDeniedError,
    RateLimitError,
    StateTransitionError,
    TemplateNotFoundError,
    ValidationError,
)
from ..domain.models import (
    ApprovalRecord,
    ApprovalRequest,
    AuditEvent,
    ProcessTemplate,
    ProcessTemplateNode,
)
from ..storage.audit_log import AuditLog
from ..storage.course_store import CourseEnrollmentStore
from ..storage.database import Database
from ..storage.outbox import Outbox
from ..storage.repository import ApprovalRecordRepository, RequestRepository, TemplateRepository
from . import rules as R
from .state_machine import apply_decision, is_terminal, status_of_node, validate_transition


# ----------------------------------------------------------------------
# RBAC 权限矩阵（deny by default，设计文档 5.4 / B1）
# ----------------------------------------------------------------------
class PermissionMatrix:
    """角色-动作授权表；资源级判定（本人 / 当前节点审批人）在引擎内完成。"""

    # 动作级授权（粗粒度）：哪些角色可以执行哪些动作
    ROLE_ACTIONS: dict[str, set[str]] = {
        # 管理员：平台全权限（含注册模板 / 归档 / 审批）
        "admin": {
            C.ACTION_SUBMIT, C.ACTION_VIEW, C.ACTION_RETURN,
            C.ACTION_APPROVE, C.ACTION_REJECT,
            C.ACTION_ARCHIVE, C.ACTION_VALIDATE, C.ACTION_NOTIFY,
            C.ACTION_REGISTER_TEMPLATE, C.ACTION_QUERY_COURSES,
            C.ACTION_CHECK_LIMIT,
        },
        C.ROLE_STUDENT: {
            C.ACTION_SUBMIT, C.ACTION_VIEW, C.ACTION_RETURN, C.ACTION_QUERY_COURSES,
        },
        C.ROLE_ADVISOR: {
            C.ACTION_APPROVE, C.ACTION_REJECT, C.ACTION_RETURN, C.ACTION_VIEW,
        },
        C.ROLE_COUNSELOR: {
            C.ACTION_SUBMIT, C.ACTION_APPROVE, C.ACTION_REJECT, C.ACTION_RETURN, C.ACTION_VIEW,
        },
        C.ROLE_COLLEGE_ADMIN: {
            C.ACTION_APPROVE, C.ACTION_REJECT, C.ACTION_RETURN, C.ACTION_VIEW,
            C.ACTION_ARCHIVE,
        },
        C.ROLE_UNIVERSITY_LEADER: {
            C.ACTION_APPROVE, C.ACTION_REJECT, C.ACTION_RETURN, C.ACTION_VIEW,
        },
        C.ROLE_LOGISTICS: {
            C.ACTION_APPROVE, C.ACTION_REJECT, C.ACTION_RETURN, C.ACTION_VIEW,
        },
        C.ROLE_FINANCE: {C.ACTION_CHECK_LIMIT, C.ACTION_VIEW, C.ACTION_APPROVE},
        C.ROLE_SYSTEM: {
            C.ACTION_VALIDATE, C.ACTION_NOTIFY, C.ACTION_ARCHIVE,
            C.ACTION_REGISTER_TEMPLATE, C.ACTION_VIEW, C.ACTION_QUERY_COURSES,
        },
    }

    def __init__(
        self,
        user_roles: dict[str, set[str]] | None = None,
        role_loader: Callable[[str], set[str] | None] | None = None,
    ):
        """user_roles: user_id -> 角色集合（演示环境默认映射，deny by default 兜底）。

        role_loader: 可选实时角色加载器，优先于默认映射。
        返回 None 表示该用户无 DB 记录（如种子演示账号），回退到 user_roles 默认映射；
        返回角色集合则以 DB 实际角色为准（管理员批量导入的学生因此可被正确授权）。
        """
        self._user_roles = user_roles or default_roles()
        self._role_loader = role_loader

    def roles_of(self, user_id: str) -> set[str]:
        if self._role_loader is not None:
            loaded = self._role_loader(user_id)
            if loaded is not None:
                return loaded
        return self._user_roles.get(user_id, set())

    def can(self, user_id: str, action: str) -> bool:
        return any(action in self.ROLE_ACTIONS[r] for r in self.roles_of(user_id))

    def require(self, user_id: str, action: str, *, detail: str = "") -> None:
        if not self.can(user_id, action):
            raise PermissionDeniedError(
                f"权限不足: 用户 {user_id} 无权执行 {action}",
                details={"user_id": user_id, "action": action, "detail": detail},
            )

    def resolve_approver_roles(self, node: ProcessTemplateNode) -> set[str]:
        """节点配置的审批人角色 → 可执行审批的账号集合。"""
        role = node.approver_role
        holder = R.holder_for_role(role)
        out = set()
        for user_id, roles in self._user_roles.items():
            if role in roles:
                out.add(user_id)
        if holder:
            out.add(holder)
        return out


def default_roles() -> dict[str, set[str]]:
    """演示环境默认账号-角色映射（后续对接校园 SSO 时替换）。"""
    return {
        "S10001": {C.ROLE_STUDENT},
        "S10002": {C.ROLE_STUDENT},
        "T10001": {C.ROLE_ADVISOR},
        "T10002": {C.ROLE_ADVISOR},
        "C30001": {C.ROLE_COUNSELOR},
        "A20001": {C.ROLE_COLLEGE_ADMIN},
        "U50001": {C.ROLE_UNIVERSITY_LEADER},
        "H60001": {C.ROLE_LOGISTICS},
        "F40001": {C.ROLE_FINANCE},
        "SYS001": {C.ROLE_SYSTEM},
    }


def db_role_loader(db: Database) -> Callable[[str], set[str] | None]:
    """从 users 表实时解析用户角色（管理员/学生/审批人），作为权限矩阵权威来源。

    - 查不到该用户（如种子演示账号 SYS001 / C30001）→ 返回 None，回退默认映射；
    - 查到且 status=active → 返回其真实角色集合；
    - 被禁用（status != active）→ 返回空集合，deny by default。
    """

    def _loader(user_id: str) -> set[str] | None:
        row = db.execute(
            "SELECT role, status FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "active":
            return set()
        return {row["role"]}

    return _loader


# ----------------------------------------------------------------------
# 限流（按申请人 / 操作人，需求约束）
# ----------------------------------------------------------------------
class RateLimiter:
    def __init__(self, limit_per_minute: int = C.RATE_LIMIT_PER_ACTOR):
        self.limit = limit_per_minute
        self._window_start = time.monotonic()
        self._counts: dict[str, int] = {}

    def check(self, actor: str) -> None:
        now = time.monotonic()
        if now - self._window_start >= 60:
            self._window_start = now
            self._counts.clear()
        self._counts[actor] = self._counts.get(actor, 0) + 1
        if self._counts[actor] > self.limit:
            raise RateLimitError(f"操作过于频繁: {actor}")


# ----------------------------------------------------------------------
class WorkflowEngine:
    """审批引擎：依赖仓储 / 审计 / outbox，负责所有状态写操作。"""

    def __init__(
        self,
        db: Database,
        *,
        matrix: PermissionMatrix | None = None,
        limiter: RateLimiter | None = None,
    ):
        self.db = db
        self.requests = RequestRepository(db)
        self.records = ApprovalRecordRepository(db)
        self.templates = TemplateRepository(db)
        self.audit = AuditLog(db)
        self.outbox = Outbox(db)
        self.matrix = matrix or PermissionMatrix()
        self.limiter = limiter or RateLimiter()
        # G2：选课占课入库（原子扣减 + 重启不丢名额）
        self.courses = CourseEnrollmentStore(
            db,
            catalog=R.COURSE_CATALOG,
            initial=R.COURSE_ENROLLMENT_INITIAL,
        )

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _audit(self, event_type: str, entity_id: str, actor: str, detail: dict) -> None:
        self.audit.append(
            AuditEvent(event_type=event_type, entity_id=entity_id, actor_id=actor, detail=detail)
        )

    def _notify(self, request_no: str, recipient: str, channel: str, template: str, payload: dict) -> None:
        self.outbox.enqueue(
            request_no=request_no,
            recipient_id=recipient,
            channel=channel,
            template=template,
            payload=payload,
        )

    def _applicant_name(self, applicant_id: str) -> str:
        row = self.db.execute(
            "SELECT name FROM users WHERE user_id=?", (applicant_id,)
        ).fetchone()
        return row["name"] if row else ""

    def _check_venue_time_conflict(self, payload: dict[str, Any]) -> None:
        """场地预约防重复：同一物理场地、时段重叠且占用中（approved/pending_*/returned）即拒。
        占用口径：approved ∪ pending_* ∪ returned；rejected/archived/draft 释放。
        重叠判定：新开始 < 旧结束 且 新结束 > 旧开始（边界相接不算冲突）。
        """
        from datetime import datetime
        venue_id = str(payload.get("venue_id", "")).strip()
        venue_name = str(payload.get("venue_name", "")).strip()
        start_s = str(payload.get("start_time", ""))
        end_s = str(payload.get("end_time", ""))
        try:
            ns = datetime.strptime(start_s, "%Y-%m-%d %H:%M")
            ne = datetime.strptime(end_s, "%Y-%m-%d %H:%M")
        except ValueError:
            return  # 时间格式由 venue_conflict 规则负责
        rows = self.db.execute(
            "SELECT payload, status FROM approval_requests WHERE process_type = ?",
            (C.PROCESS_VENUE_RESERVATION,),
        ).fetchall()
        for row in rows:
            status = row["status"]
            occupied = (
                status == C.STATUS_APPROVED
                or status.startswith(C.STATUS_PENDING_PREFIX)
                or status == C.STATUS_RETURNED
            )
            if not occupied:
                continue
            old = json.loads(row["payload"] or "{}")
            old_vid = str(old.get("venue_id", "")).strip()
            # 同一物理场地：优先 venue_id；旧单无 venue_id 时按 venue_name 兜底
            if venue_id:
                if old_vid != venue_id:
                    continue
            elif str(old.get("venue_name", "")) != venue_name:
                continue
            os_ = old.get("start_time")
            oe_ = old.get("end_time")
            if not os_ or not oe_:
                continue
            try:
                os_dt = datetime.strptime(str(os_), "%Y-%m-%d %H:%M")
                oe_dt = datetime.strptime(str(oe_), "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if ns < oe_dt and ne > os_dt:
                raise ValidationError(
                    "场地时段冲突",
                    details={"conflict": f"该场地在 {os_} ~ {oe_} 已被占用，请选择其他时段"},
                )

    def _resolve_nodes(self, process_type: str, payload: dict[str, Any]) -> list[ProcessTemplateNode] | None:
        """按业务规则解析本单实际审批链。

        返回 list（可能为空 []）：本单审批链由规则决定，空链=零节点自动通过；
        返回 None：本流程无动态规则，回退模板静态 nodes。
        """
        if process_type == C.PROCESS_LEAVE:
            return [ProcessTemplateNode(**n) for n in R.resolve_leave_nodes(payload)]
        if process_type == C.PROCESS_VENUE_RESERVATION:
            return [ProcessTemplateNode(**n) for n in R.resolve_venue_nodes(payload)]
        if process_type == C.PROCESS_COURSE_SELECTION:
            return []  # 选课零节点：提交即自动通过（不进人工审批）
        return None

    def _effective_nodes(
        self, req: ApprovalRequest, template: ProcessTemplate
    ) -> list[ProcessTemplateNode]:
        """本单实际审批链：优先用提交时解析并存档的 resolved_nodes，否则用模板 nodes。"""
        if req.resolved_nodes:
            return [ProcessTemplateNode(**n) for n in req.resolved_nodes]
        return list(template.nodes)

    # ------------------------------------------------------------------
    # 1. 提交申请（幂等：client_request_no 去重）
    # ------------------------------------------------------------------
    def submit(
        self,
        *,
        applicant_id: str,
        process_type: str,
        payload: dict[str, Any],
        attachment_urls: list[str] | None = None,
        attachments: list[dict] | None = None,
        client_request_no: str | None = None,
    ) -> ApprovalRequest:
        self.limiter.check(applicant_id)
        self.matrix.require(applicant_id, C.ACTION_SUBMIT, detail="提交申请")

        # 学生端不开放报销：学生提交报销一律拒绝
        if process_type == C.PROCESS_REIMBURSEMENT and C.ROLE_STUDENT in self.matrix.roles_of(applicant_id):
            raise PermissionDeniedError(
                "学生端暂不支持报销申请，请联系辅导员或财务处",
                details={"applicant_id": applicant_id, "process_type": process_type},
            )

        # 幂等：同 (applicant_id, client_request_no) 直接返回已有记录（作用域 = 申请人，
        # 不同申请人撞键互不干扰，见 database.py 复合唯一索引）
        if client_request_no:
            existing = self.requests.get_by_client_no(client_request_no, applicant_id)
            if existing is not None:
                return existing

        # 输入清洗（B2 特殊字符注入拦截）
        R.sanitize_payload(payload)

        template = self.templates.get_latest(process_type)
        # 业务规则校验（规则绑定自模板 validation_rules；选课名额以 DB 权威来源判定）
        R.ensure_valid(template.validation_rules, payload, course_store=self.courses)

        # 场地预约：同场地时段重叠防重复占用（需查历史单，引擎层做）
        if process_type == C.PROCESS_VENUE_RESERVATION:
            self._check_venue_time_conflict(payload)

        # 解析本单实际审批链：None=回退模板；[]=零节点自动通过；非空=人工链
        resolved = self._resolve_nodes(process_type, payload)
        if resolved is None:
            resolved = list(template.nodes)
        auto_approved = len(resolved) == 0
        first_node = resolved[0] if resolved else None

        # 附件视觉校验：模板开了 auto_pass_if_doc_valid 且附件真实 → 自动通过
        doc_check: dict = {}
        attachments = attachments or []
        if template.auto_pass_rules.get("auto_pass_if_doc_valid") and not auto_approved:
            from ..tools.doc_verifier import verify_attachments
            doc_check = verify_attachments(process_type, attachments)
            if doc_check.get("authentic") is True:
                auto_approved = True
                resolved = []
                first_node = None

        req = ApprovalRequest(
            applicant_id=applicant_id,
            process_type=process_type,
            payload=payload,
            attachment_urls=attachment_urls or [],
            client_request_no=client_request_no,
            status=C.STATUS_APPROVED if auto_approved else status_of_node(first_node.node_id),
            current_node_id=None if auto_approved else first_node.node_id,
            resolved_nodes=[n.model_dump() for n in resolved],
            doc_check=doc_check,
        )

        with self.db.transaction():
            self.requests.insert(req)
            if auto_approved:
                # 零节点（如教室/选课）：自动通过，直接通知申请人 approved
                if process_type == C.PROCESS_COURSE_SELECTION:
                    # 选课无审批环节，提交即占课（原子扣减；与状态提交/通知同事务）
                    for cid in (payload.get("course_ids") or []):
                        if not self.courses.try_enroll(cid):
                            raise ValidationError(
                                f"课程 {cid} 名额已满", details={"course_id": cid}
                            )
                self._notify(
                    req.request_no, applicant_id, C.CHANNEL_IM, "approved",
                    {"request_no": req.request_no, "status": C.STATUS_APPROVED, "auto": True},
                )
            else:
                approver = R.holder_for_role(first_node.approver_role)
                self._notify(
                    req.request_no, approver, C.CHANNEL_IM, "approval_required",
                    {"request_no": req.request_no, "applicant": applicant_id,
                     "process_type": process_type, "node": first_node.node_id},
                )
            self._audit(
                C.EVENT_REQUEST_SUBMITTED, req.request_no, applicant_id,
                {"process_type": process_type, "status": req.status,
                 "node": first_node.node_id if first_node else None,
                 "client_request_no": client_request_no,
                 "resolved_nodes": [n.node_id for n in resolved],
                 "auto_approved": auto_approved},
            )
        return req

    # ------------------------------------------------------------------
    # 2. 审批推进（单写者 + 乐观锁；非幂等写）
    # ------------------------------------------------------------------
    def advance(
        self,
        *,
        request_no: str,
        approver_id: str,
        decision: str,
        comment: str = "",
    ) -> ApprovalRequest:
        self.limiter.check(approver_id)
        if decision not in C.ALL_DECISIONS:
            raise StateTransitionError(f"非法决策: {decision}")

        req = self.requests.get(request_no)
        template = self.templates.get_latest(req.process_type)
        nodes = self._effective_nodes(req, template)

        # 权限：审批人必须是当前节点配置角色的持有者
        self._require_node_approver(req, nodes, approver_id, decision)

        # 转移合法性（红牌「跳过审批节点」拦截）
        validate_transition(nodes, req.status, req.current_node_id or "", decision)

        new_status, new_node = apply_decision(nodes, req.status, req.current_node_id or "", decision)

        # 乐观锁：expected_version 不匹配 → 行数 0 → 409
        with self.db.transaction():
            rowcount = self.requests.update_status(
                request_no, new_status, new_node, expected_version=req.version
            )
            if rowcount == 0:
                self._audit(
                    C.EVENT_OPTIMISTIC_LOCK_CONFLICT, request_no, approver_id,
                    {"decision": decision, "expected_version": req.version},
                )
                raise OptimisticLockError(
                    "并发冲突：申请单已被其他审批人更新，请刷新后重试",
                    details={"request_no": request_no, "expected_version": req.version},
                )

            self.records.insert(
                ApprovalRecord(
                    request_no=request_no,
                    node_id=req.current_node_id or "",
                    approver_id=approver_id,
                    decision=decision,
                    comment=comment,
                )
            )

            # 副作用：通知 + 业务副作用（与状态提交同事务 → outbox 不丢、
            # 占课/释放原子一致；任一失败整体回滚）
            self._side_effects_after_advance(req, nodes, decision, new_status, new_node)
            self._apply_business_side_effect(req, decision, new_status)

            self._audit(
                C.EVENT_REQUEST_ADVANCED, request_no, approver_id,
                {"decision": decision, "from": req.status, "to": new_status,
                 "node": req.current_node_id, "comment": comment},
            )

        return self.requests.get(request_no)

    def _require_node_approver(
        self, req: ApprovalRequest, nodes: list[ProcessTemplateNode], approver_id: str, decision: str
    ) -> None:
        """权限前置：当前节点审批人校验（B1 学生尝试管理员操作被拦截）。"""
        if decision == C.DECISION_RETURN and req.current_node_id is None:
            # 无当前节点（draft 重填场景）：仅申请人可操作
            self.matrix.require(approver_id, C.ACTION_RETURN)
            if approver_id != req.applicant_id:
                raise PermissionDeniedError("仅申请人可退回重填", details={"request_no": req.request_no})
            return

        if req.current_node_id is None:
            raise StateTransitionError(f"当前无待审节点: {req.request_no}")

        node = next((n for n in nodes if n.node_id == req.current_node_id), None)
        if node is None:
            raise StateTransitionError(f"节点不在审批链中: {req.current_node_id}")
        allowed = self.matrix.resolve_approver_roles(node)
        self.matrix.require(approver_id, C.ACTION_APPROVE, detail=f"node={node.node_id}")
        if approver_id not in allowed:
            raise PermissionDeniedError(
                f"用户 {approver_id} 不是节点 {node.node_id} 的审批人",
                details={"request_no": req.request_no, "node": node.node_id, "allowed": sorted(allowed)},
            )
        # 归属校验（设计文档 5.1「权限（该单导师）」）：导师节点仅该申请人的导师可审
        if node.approver_role == C.ROLE_ADVISOR:
            own_advisor = R.advisor_of(req.applicant_id)
            if approver_id != own_advisor:
                raise PermissionDeniedError(
                    f"用户 {approver_id} 不是申请人 {req.applicant_id} 的导师",
                    details={"request_no": req.request_no, "applicant": req.applicant_id,
                             "own_advisor": own_advisor},
                )
        # S3 纵深防御：辅导员节点仅本班学生申请可审（与 auto_review 班级过滤同口径；
        # 申请人未分班时不拦截，保持既有行为）
        if node.approver_role == C.ROLE_COUNSELOR:
            srow = self.db.execute(
                "SELECT class_id FROM users WHERE user_id=?", (req.applicant_id,)
            ).fetchone()
            applicant_class = srow["class_id"] if srow else ""
            if applicant_class:
                rows = self.db.execute(
                    "SELECT class_id FROM classes WHERE counselor_id=?", (approver_id,)
                ).fetchall()
                my_classes = {r["class_id"] for r in rows if r["class_id"]}
                if applicant_class not in my_classes:
                    raise PermissionDeniedError(
                        f"用户 {approver_id} 不是申请人 {req.applicant_id} 所在班级的辅导员",
                        details={"request_no": req.request_no, "applicant": req.applicant_id,
                                 "class_id": applicant_class},
                    )

    def _side_effects_after_advance(
        self,
        req: ApprovalRequest,
        nodes: list[ProcessTemplateNode],
        decision: str,
        new_status: str,
        new_node: str | None,
    ) -> None:
        """审批后的通知副作用（写入 outbox，同事务）。"""
        applicant = req.applicant_id
        if decision == C.DECISION_APPROVE and new_node:
            # 推进下一节点 → 通知下一审批人
            node = next((n for n in nodes if n.node_id == new_node), None)
            if node:
                approver = R.holder_for_role(node.approver_role)
                self._notify(
                    req.request_no, approver, C.CHANNEL_IM, "approval_required",
                    {"request_no": req.request_no, "node": node.node_id},
                )
        elif decision == C.DECISION_APPROVE and not new_node:
            # 末节点通过 → 通知申请人
            self._notify(
                req.request_no, applicant, C.CHANNEL_IM, "approved",
                {"request_no": req.request_no, "status": C.STATUS_APPROVED},
            )
        elif decision == C.DECISION_REJECT:
            self._notify(
                req.request_no, applicant, C.CHANNEL_IM, "rejected",
                {"request_no": req.request_no, "status": C.STATUS_REJECTED},
            )
        elif decision == C.DECISION_RETURN:
            # 退回：始终通知申请人（可多次退回，均留痕）
            self._notify(
                req.request_no, applicant, C.CHANNEL_IM, "returned",
                {"request_no": req.request_no, "status": new_status, "node": new_node},
            )

    def _apply_business_side_effect(
        self, req: ApprovalRequest, decision: str, new_status: str
    ) -> None:
        """业务侧副作用：选课占课 / 退选释放（A2，DB 原子操作，随事务提交）。"""
        if req.process_type != C.PROCESS_COURSE_SELECTION:
            return
        course_ids = req.payload.get("course_ids") or []
        if decision == C.DECISION_APPROVE and is_terminal(new_status):
            for cid in course_ids:
                if not self.courses.try_enroll(cid):
                    raise ValidationError(
                        f"课程 {cid} 名额已满", details={"course_id": cid}
                    )
        elif decision == C.DECISION_REJECT:
            for cid in course_ids:
                self.courses.release(cid)

    # ------------------------------------------------------------------
    # 3. 归档（幂等：同单归档返回同一记录）
    # ------------------------------------------------------------------
    def archive(self, *, request_no: str, actor_id: str = C.ROLE_SYSTEM) -> ApprovalRequest:
        self.matrix.require(actor_id, C.ACTION_ARCHIVE, detail="归档")
        req = self.requests.get(request_no)
        if req.status == C.STATUS_ARCHIVED:
            return req  # 幂等
        if not is_terminal(req.status):
            raise StateTransitionError(
                f"仅终态申请可归档: {request_no} (status={req.status})"
            )

        content = json.dumps(
            {
                "request_no": req.request_no,
                "applicant_id": req.applicant_id,
                "applicant_name": self._applicant_name(req.applicant_id),
                "process_type": req.process_type,
                "payload": req.payload,
                "status": req.status,
                "records": [r.model_dump() for r in self.records.list_by_request(request_no)],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

        with self.db.transaction():
            rowcount = self.requests.mark_archived(request_no, digest, expected_version=req.version)
            if rowcount == 0:
                raise OptimisticLockError("归档冲突：申请单版本已变化", details={"request_no": request_no})
            self._audit(
                C.EVENT_REQUEST_ARCHIVED, request_no, actor_id,
                {"archive_hash": digest, "final_status": req.status},
            )
        return self.requests.get(request_no)

    # ------------------------------------------------------------------
    # 4. 模板注册（扩展框架 5.3：不改核心引擎、不新增 Agent）
    # ------------------------------------------------------------------
    def register_template(
        self,
        *,
        process_type: str,
        nodes: list[dict[str, str]],
        validation_rules: list[str],
        actor_id: str = C.ROLE_SYSTEM,
        version: int | None = None,
        auto_pass_rules: dict | None = None,
    ) -> ProcessTemplate:
        self.matrix.require(actor_id, C.ACTION_REGISTER_TEMPLATE, detail="注册流程模板")
        latest = self.templates.get_optional_latest(process_type)
        next_version = (latest.version + 1) if latest else (version or 1)
        tpl = ProcessTemplate(
            process_type=process_type,
            version=next_version,
            nodes=[ProcessTemplateNode(**n) for n in nodes],
            validation_rules=validation_rules,
            auto_pass_rules=auto_pass_rules or {},
        )
        with self.db.transaction():
            self.templates.insert(tpl)
            self._audit(
                C.EVENT_TEMPLATE_REGISTERED, process_type, actor_id,
                {"version": tpl.version, "nodes": [n.model_dump() for n in tpl.nodes],
                 "validation_rules": tpl.validation_rules,
                 "auto_pass_rules": tpl.auto_pass_rules},
            )
        return tpl

    # ------------------------------------------------------------------
    # 5. 查询
    # ------------------------------------------------------------------
    def get_status(self, request_no: str) -> ApprovalRequest:
        return self.requests.get(request_no)

    def status_view(self, request_no: str) -> dict[str, Any]:
        req = self.requests.get(request_no)
        return {
            "request_no": req.request_no,
            "applicant_id": req.applicant_id,
            "applicant_name": self._applicant_name(req.applicant_id),
            "process_type": req.process_type,
            "status": req.status,
            "current_node_id": req.current_node_id,
            "payload": req.payload,
            "attachment_urls": req.attachment_urls,
            "attachments": [{"url": u, "name": u.split("/").pop(), "type": "image"} for u in (req.attachment_urls or [])],
            "doc_check": req.doc_check,
            "resolved_nodes": req.resolved_nodes,
            "client_request_no": req.client_request_no,
            "version": req.version,
            "created_at": req.created_at,
            "updated_at": req.updated_at,
            "archived_at": req.archived_at,
            "archive_hash": req.archive_hash,
            "records": [r.model_dump() for r in self.records.list_by_request(request_no)],
        }


# 兼容别名：引擎实例对工具层暴露统一入口
Engine = WorkflowEngine
