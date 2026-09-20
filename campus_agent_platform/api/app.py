"""FastAPI 接口层。

端点（对应设计文档集成需求 REST API + Dashboard 数据）：
- POST   /api/v1/requests                提交申请（走 Agent 编排）
- GET    /api/v1/requests/{request_no}   查询状态
- POST   /api/v1/requests/{request_no}/advance  审批推进（人工决策注入）
- POST   /api/v1/requests/{request_no}/archive  归档
- GET    /api/v1/requests                按申请人查询
- POST   /api/v1/process-types           注册流程模板（扩展框架）
- GET    /api/v1/process-types           模板列表
- GET    /api/v1/courses                 课程目录查询（规则源）
- GET    /api/v1/audit/events            审计日志
- POST   /api/v1/notifications/outbox/dispatch  通知 outbox 投递
- GET    /api/v1/dashboard/stats         仪表盘统计
- GET    /health                         健康检查
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..app import CampusAgentApp
from ..auth import AuthError, decode_token
from ..configs.settings import settings as app_settings
from ..domain import constants as C
from ..domain.errors import DomainError
from ..domain.models import AuditEvent
from ..storage.repository import TemplateRepository
from ..tools import registry as tools
from ..workflows import rules as R


def _request_visible_to(engine, req, user: dict) -> bool:
    """申请单可见性（数据越权防线，列表/详情共用）：

    - admin：全可见
    - counselor：仅本班学生申请
    - 申请人本人可见
    - 当前节点审批人（按角色匹配 resolved_nodes/模板 nodes）可见
    - 自己审过（approval_records 有记录）可见
    其余一律不可见。
    """
    uid, role = user["user_id"], user["role"]
    if role == "admin":
        return True
    if role == "counselor":
        srow = engine.db.execute(
            "SELECT class_id FROM users WHERE user_id=?", (req.applicant_id,)
        ).fetchone()
        rows = engine.db.execute(
            "SELECT class_id FROM classes WHERE counselor_id=?", (uid,)
        ).fetchall()
        my_classes = {r["class_id"] for r in rows if r["class_id"]}
        return (srow["class_id"] if srow else "") in my_classes
    if req.applicant_id == uid:
        return True
    if req.current_node_id:
        nodes = req.resolved_nodes
        if not nodes:
            try:
                tpl = engine.templates.get_latest(req.process_type)
                nodes = [n.model_dump() for n in tpl.nodes]
            except Exception:  # noqa: BLE001 - 模板缺失时按不可见处理
                nodes = []
        for n in nodes:
            if n.get("node_id") == req.current_node_id and n.get("approver_role") == role:
                return True
    row = engine.db.execute(
        "SELECT 1 FROM approval_records WHERE request_no=? AND approver_id=?",
        (req.request_no, uid),
    ).fetchone()
    return row is not None


# ----------------------------------------------------------------------
# 请求 / 响应模型
# ----------------------------------------------------------------------
class SubmitRequest(BaseModel):
    applicant_id: str
    process_type: str
    payload: dict[str, Any]
    attachment_urls: list[str] = Field(default_factory=list)
    attachments: list[dict] = Field(default_factory=list)
    client_request_no: str | None = None


class AdvanceRequest(BaseModel):
    approver_id: str
    decision: str
    comment: str = ""


class ArchiveRequest(BaseModel):
    actor_id: str = C.ROLE_SYSTEM


class RegisterTemplateRequest(BaseModel):
    process_type: str
    nodes: list[dict[str, str]]
    validation_rules: list[str] = Field(default_factory=list)
    auto_pass_rules: dict = Field(default_factory=dict)
    actor_id: str = C.ROLE_SYSTEM


class AgentRunRequest(BaseModel):
    intent: str
    applicant_id: str = ""
    process_type: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    attachment_urls: list[str] = Field(default_factory=list)
    client_request_no: str | None = None
    request_no: str = ""
    approver_id: str = ""
    decision: str = ""
    comment: str = ""
    user_goal: str = ""


class SendNotificationRequest(BaseModel):
    recipient_id: str
    channel: str = C.CHANNEL_IM
    template: str
    payload: dict[str, Any] = Field(default_factory=dict)
    request_no: str = ""


class CheckPermissionRequest(BaseModel):
    user_id: str
    action: str
    resource_no: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class AddStudentRequest(BaseModel):
    students: list[dict]


class AskRequest(BaseModel):
    question: str
    attachments: list[dict] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    title: str = ""


# ----------------------------------------------------------------------
def create_app(app_container: CampusAgentApp | None = None) -> FastAPI:
    app = FastAPI(
        title="校园审批工作流 Agent 平台 API",
        version="1.0.0",
        description="Supervisor 模式多 Agent 审批平台：5 Agent / 10 工具 / 状态机 / 审计 / 幂等 / 乐观锁",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    container = app_container

    def _c() -> CampusAgentApp:
        nonlocal container
        if container is None:
            container = CampusAgentApp()  # 延迟到首个请求时初始化
        return container

    # ------------------------------------------------------------------
    # 鉴权依赖（前移：所有需要登录/管理员的端点共用）
    # ------------------------------------------------------------------
    def _current_user(request: Request) -> dict:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="未登录")
        payload = decode_token(auth[7:])
        if payload is None:
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
        return {"user_id": payload["sub"], "role": payload["role"], "name": payload.get("name", "")}

    def _require_admin(user: dict = Depends(_current_user)) -> dict:
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user

    # ------------------------------------------------------------------
    @app.exception_handler(DomainError)
    async def _domain_error_handler(request: Request, exc: DomainError):
        raise HTTPException(status_code=exc.status_code, detail={
            "code": exc.code, "message": exc.message, "details": exc.details,
        }) from exc

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "campus-approval-agent"}

    # ------------------------- 申请 -------------------------
    @app.post("/api/v1/requests", status_code=201)
    def submit_application(body: SubmitRequest, user: dict = Depends(_current_user)):
        """提交申请（幂等：client_request_no 按申请人去重；申请人身份取自 JWT，忽略 body）。"""
        engine = _c().engine
        req = engine.submit(
            applicant_id=user["user_id"],
            process_type=body.process_type,
            payload=body.payload,
            attachment_urls=body.attachment_urls,
            attachments=body.attachments,
            client_request_no=body.client_request_no,
        )
        return engine.status_view(req.request_no)

    @app.get("/api/v1/requests/{request_no}")
    def get_application(request_no: str, user: dict = Depends(_current_user)):
        engine = _c().engine
        req = engine.requests.get(request_no)
        if not _request_visible_to(engine, req, user):
            raise HTTPException(status_code=403, detail="无权查看该申请")
        return engine.status_view(request_no)

    @app.get("/api/v1/requests")
    def list_applications(applicant_id: str | None = Query(default=None),
                          user: dict = Depends(_current_user)):
        """按申请人查询；可见性收口：学生仅本人、辅导员仅本班、审批角色仅自己相关、admin 全量。"""
        engine = _c().engine
        reqs = (
            engine.requests.list_by_applicant(applicant_id)
            if applicant_id else engine.requests.list_all()
        )
        out = []
        for r in reqs:
            if not _request_visible_to(engine, r, user):
                continue
            d = r.model_dump()
            d["applicant_name"] = engine._applicant_name(d.get("applicant_id", ""))
            out.append(d)
        return out

    @app.post("/api/v1/requests/{request_no}/advance")
    def advance_application(request_no: str, body: AdvanceRequest, user: dict = Depends(_current_user)):
        """审批推进：approve / reject / return（操作人身份取自 JWT，忽略 body 中 approver_id）。"""
        req = _c().engine.advance(
            request_no=request_no,
            approver_id=user["user_id"],
            decision=body.decision,
            comment=body.comment,
        )
        return _c().engine.status_view(req.request_no)

    @app.post("/api/v1/requests/{request_no}/archive")
    def archive_application(request_no: str, body: ArchiveRequest | None = None,
                            user: dict = Depends(_current_user)):
        """归档（操作人身份取自 JWT；需具备 ARCHIVE 权限的角色，如管理员/学院管理员）。"""
        req = _c().engine.archive(request_no=request_no, actor_id=user["user_id"])
        return _c().engine.status_view(req.request_no)

    @app.post("/api/v1/requests/auto-review")
    def auto_review(user: dict = Depends(_current_user)):
        """辅导员端一键自动审核：仅辅导员角色可用，且只审核本班学生的待办请假单。"""
        if user["role"] != "counselor":
            raise HTTPException(status_code=403, detail="仅辅导员可执行自动审核")
        approver_id = user["user_id"]
        engine = _c().engine
        rows = engine.db.execute(
            "SELECT class_id FROM classes WHERE counselor_id=?", (approver_id,)
        ).fetchall()
        my_class_ids = {r["class_id"] for r in rows if r["class_id"]}
        all_reqs = engine.requests.list_all()
        approves, rejects, skipped = [], [], []
        for r in all_reqs:
            if r.process_type != "leave":
                continue
            if r.status != "pending_counselor":
                continue
            srow = engine.db.execute(
                "SELECT class_id FROM users WHERE user_id=?", (r.applicant_id,)
            ).fetchone()
            if not srow or (srow["class_id"] or "") not in my_class_ids:
                skipped.append({"request_no": r.request_no, "reason": "非本班学生申请"})
                continue
            violations, days = R.evaluate_leave_auto_review(
                r.payload or {}, r.attachment_urls or []
            )
            if days > 7:
                skipped.append({"request_no": r.request_no, "reason": f"请假{days}天，需学校领导审批"})
                continue
            if violations:
                try:
                    engine.advance(request_no=r.request_no, approver_id=approver_id,
                                   decision="reject", comment="自动驳回：" + "；".join(violations))
                    rejects.append({"request_no": r.request_no, "reasons": violations})
                except Exception as e:
                    skipped.append({"request_no": r.request_no, "reason": str(e)})
                continue
            try:
                engine.advance(request_no=r.request_no, approver_id=approver_id,
                               decision="approve", comment="自动通过：符合规则")
                approves.append(r.request_no)
            except Exception as e:
                skipped.append({"request_no": r.request_no, "reason": str(e)})
        return {"approved": approves, "rejected": rejects, "skipped": skipped}

    # ------------------------- 流程模板 -------------------------
    @app.post("/api/v1/process-types", status_code=201)
    def register_process_type(body: RegisterTemplateRequest, user: dict = Depends(_current_user)):
        """注册流程模板（仅管理员；操作人身份取自 JWT，忽略 body 中 actor_id）。"""
        tpl = _c().engine.register_template(
            process_type=body.process_type,
            nodes=body.nodes,
            validation_rules=body.validation_rules,
            auto_pass_rules=body.auto_pass_rules,
            actor_id=user["user_id"],
        )
        return tpl.model_dump()

    @app.get("/api/v1/process-types")
    def list_process_types(user: dict = Depends(_current_user)):
        return [t.model_dump() for t in _c().engine.templates.list_all()]

    # ------------------------- 规则源 -------------------------
    @app.get("/api/v1/courses")
    def list_courses(course_ids: str | None = Query(default=None, description="逗号分隔课程编号；不传则返回全部课程")):
        ids = [c.strip() for c in course_ids.split(",") if c.strip()] if course_ids else list(R.COURSE_CATALOG.keys())
        out = {}
        for cid in ids:
            exists = cid in R.COURSE_CATALOG
            item: dict = {"exists": exists}
            if exists:
                c = R.COURSE_CATALOG[cid]
                item.update({k: v for k, v in c.items()})
                item["enrolled"] = R.COURSE_ENROLLMENT.get(cid, 0)
                item["remaining"] = max(0, c["quota"] - item["enrolled"])
            out[cid] = item
        return {"courses": out}

    @app.get("/api/v1/venues")
    def list_venues(venue_ids: str | None = Query(default=None, description="逗号分隔场地编号；不传则返回全部场地")):
        ids = [v.strip() for v in venue_ids.split(",") if v.strip()] if venue_ids else list(R.VENUE_CATALOG.keys())
        out = {}
        for vid in ids:
            v = R.VENUE_CATALOG.get(vid)
            if v is None:
                out[vid] = {"exists": False}
                continue
            auto = v["type"] in R.VENUE_TYPES_AUTO_APPROVE
            out[vid] = {
                "venue_id": vid,
                "exists": True,
                **v,
                "auto_approve": auto,
                "approval": "提交即通过" if auto else "后勤审核",
            }
        return {"venues": out}

    # ------------------------- 审计（仅管理员） -------------------------
    @app.get("/api/v1/audit/events")
    def audit_events(entity_id: str | None = Query(default=None), limit: int = Query(default=200, le=1000),
                     _: dict = Depends(_require_admin)):
        audit = _c().engine.audit
        events = audit.list_by_entity(entity_id) if entity_id else audit.list_all(limit)
        return [e.model_dump() for e in events]

    # ------------------------- 通知 -------------------------
    @app.post("/api/v1/notifications")
    def send_notification(body: SendNotificationRequest, user: dict = Depends(_current_user)):
        engine = _c().engine
        msg = engine.outbox.enqueue(
            request_no=body.request_no,
            recipient_id=body.recipient_id,
            channel=body.channel,
            template=body.template,
            payload=body.payload,
        )
        engine.audit.append(AuditEvent(
            event_type=C.EVENT_NOTIFICATION_SENT, entity_id=body.request_no or msg.id,
            actor_id=C.ROLE_SYSTEM,
            detail={"msg_id": msg.id, "channel": body.channel, "recipient": body.recipient_id},
        ))
        engine.db.commit()
        return {"message_id": msg.id, "status": "queued"}

    @app.post("/api/v1/notifications/outbox/dispatch")
    def dispatch_outbox(user: dict = Depends(_current_user)):
        sent = _c().dispatch_pending_notifications()
        pending = _c().engine.outbox.count_pending()
        return {"dispatched": sent, "pending": pending}

    # ------------------------- 权限 -------------------------
    @app.post("/api/v1/check-permission")
    def check_permission(body: CheckPermissionRequest, user: dict = Depends(_current_user)):
        res = tools.call_tool(
            "check_permission",
            user_id=body.user_id, action=body.action, resource_no=body.resource_no,
        )
        return res.get("data") if res["ok"] else res["error"]

    # ------------------------- Agent 编排 -------------------------
    @app.post("/api/v1/agent/run")
    def run_agent(body: AgentRunRequest, user: dict = Depends(_current_user)):
        """端到端运行多 Agent 编排（supervisor + 专业 Agent）；身份取自 JWT，防止冒充他人操作。"""
        data = body.model_dump()
        # 编排输入里的申请人/审批人一律以当前登录身份为准，防止借编排接口伪造身份
        data["applicant_id"] = user["user_id"]
        if data.get("approver_id"):
            data["approver_id"] = user["user_id"]
        result = _c().graph.run(**data)
        if not result.get("ok"):
            raise HTTPException(status_code=422, detail=result)
        return result

    # ------------------------- 仪表盘（仅管理员） -------------------------
    @app.get("/api/v1/dashboard/stats")
    def dashboard_stats(_: dict = Depends(_require_admin)):
        engine = _c().engine
        rows = engine.db.execute(
            "SELECT status, COUNT(*) AS c FROM approval_requests GROUP BY status"
        ).fetchall()
        return {
            "by_status": {r["status"]: r["c"] for r in rows},
            "total_requests": engine.db.execute(
                "SELECT COUNT(*) AS c FROM approval_requests").fetchone()["c"],
            "audit_events": engine.audit.count(),
            "pending_notifications": engine.outbox.count_pending(),
            "templates": len(engine.templates.list_all()),
        }

    # ==================================================================
    # 鉴权（JWT Bearer）—— _current_user / _require_admin 已在文件上部定义
    # ==================================================================
    @app.post("/api/v1/auth/login")
    def login(body: LoginRequest):
        try:
            return _c().auth.login(body.username, body.password)
        except AuthError as e:
            raise HTTPException(status_code=401, detail={"code": e.code, "message": e.message})

    @app.post("/api/v1/auth/change-password")
    def change_password(body: ChangePasswordRequest, user: dict = Depends(_current_user)):
        try:
            _c().auth.change_password(user["user_id"], body.old_password, body.new_password)
            return {"ok": True}
        except AuthError as e:
            raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message})

    @app.get("/api/v1/auth/me")
    def me(user: dict = Depends(_current_user)):
        return user

    # ==================================================================
    # 学生管理（仅管理员）
    # ==================================================================
    @app.get("/api/v1/admin/students")
    def list_students(_: dict = Depends(_require_admin)):
        return _c().auth.list_students()

    @app.post("/api/v1/admin/students", status_code=201)
    def add_students(body: AddStudentRequest, _: dict = Depends(_require_admin)):
        return _c().auth.add_students(body.students)

    @app.delete("/api/v1/admin/students/{user_id}")
    def disable_student(user_id: str, _: dict = Depends(_require_admin)):
        _c().auth.disable_student(user_id)
        return {"ok": True}

    @app.post("/api/v1/admin/students/{user_id}/assign-class")
    def assign_student_class(user_id: str, body: dict, _: dict = Depends(_require_admin)):
        """把学生分配到班级。"""
        db = _c().db
        class_id = (body.get("class_id") or "").strip()
        if class_id:
            row = db.execute("SELECT class_id FROM classes WHERE class_id=?", (class_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="班级不存在")
        db.execute("UPDATE users SET class_id=? WHERE user_id=?", (class_id, user_id))
        db.commit()
        return {"ok": True, "user_id": user_id, "class_id": class_id}

    # ------------------------- 班级管理 -------------------------
    @app.get("/api/v1/admin/counselors")
    def list_counselors(_: dict = Depends(_require_admin)):
        db = _c().db
        rows = db.execute(
            "SELECT user_id, username, name, email FROM users WHERE role='counselor' AND status='active' ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    @app.get("/api/v1/admin/classes")
    def list_classes(_: dict = Depends(_require_admin)):
        db = _c().db
        rows = db.execute(
            "SELECT c.class_id, c.grade, c.major, c.name, c.counselor_id, c.created_at,"
            "       u.name AS counselor_name,"
            "       (SELECT COUNT(*) FROM users s WHERE s.class_id=c.class_id AND s.role='student') AS student_count"
            " FROM classes c LEFT JOIN users u ON u.user_id=c.counselor_id"
            " ORDER BY c.grade DESC, c.major, c.name"
        ).fetchall()
        return [dict(r) for r in rows]

    @app.post("/api/v1/admin/classes", status_code=201)
    def create_class(body: dict, _: dict = Depends(_require_admin)):
        import time as _t, uuid as _uuid
        db = _c().db
        grade = (body.get("grade") or "").strip()
        major = (body.get("major") or "").strip()
        name = (body.get("name") or "").strip()
        counselor_id = (body.get("counselor_id") or "").strip()
        if not grade or not major or not name:
            raise HTTPException(status_code=400, detail="年级/专业/班名必填")
        class_id = body.get("class_id") or ("CLS-" + _uuid.uuid4().hex[:8].upper())
        exists = db.execute("SELECT class_id FROM classes WHERE class_id=?", (class_id,)).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="班级已存在")
        if counselor_id:
            cr = db.execute("SELECT user_id FROM users WHERE user_id=? AND role='counselor'", (counselor_id,)).fetchone()
            if not cr:
                raise HTTPException(status_code=400, detail="辅导员不存在或不是辅导员角色")
        db.execute(
            "INSERT INTO classes (class_id, grade, major, name, counselor_id, created_at) VALUES (?,?,?,?,?,?)",
            (class_id, grade, major, name, counselor_id, _t.time()),
        )
        db.commit()
        return {"class_id": class_id, "grade": grade, "major": major, "name": name, "counselor_id": counselor_id}

    @app.post("/api/v1/admin/classes/{class_id}/assign-counselor")
    def assign_class_counselor(class_id: str, body: dict, _: dict = Depends(_require_admin)):
        db = _c().db
        row = db.execute("SELECT class_id FROM classes WHERE class_id=?", (class_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="班级不存在")
        counselor_id = (body.get("counselor_id") or "").strip()
        if counselor_id:
            cr = db.execute("SELECT user_id FROM users WHERE user_id=? AND role='counselor'", (counselor_id,)).fetchone()
            if not cr:
                raise HTTPException(status_code=400, detail="辅导员不存在")
        db.execute("UPDATE classes SET counselor_id=? WHERE class_id=?", (counselor_id, class_id))
        db.commit()
        return {"ok": True, "class_id": class_id, "counselor_id": counselor_id}

    @app.delete("/api/v1/admin/classes/{class_id}")
    def delete_class(class_id: str, _: dict = Depends(_require_admin)):
        db = _c().db
        db.execute("UPDATE users SET class_id='' WHERE class_id=?", (class_id,))
        db.execute("DELETE FROM classes WHERE class_id=?", (class_id,))
        db.commit()
        return {"ok": True}

    @app.get("/api/v1/counselor/my-classes")
    def my_classes(user: dict = Depends(_current_user)):
        """辅导员看自己带的班级。"""
        db = _c().db
        rows = db.execute(
            "SELECT c.class_id, c.grade, c.major, c.name,"
            " (SELECT COUNT(*) FROM users s WHERE s.class_id=c.class_id AND s.role='student') AS student_count"
            " FROM classes c WHERE c.counselor_id=? ORDER BY c.grade DESC, c.major, c.name",
            (user["user_id"],),
        ).fetchall()
        return [dict(r) for r in rows]

    # ==================================================================
    # Agent 对话（短期记忆 + RAG）
    # ==================================================================
    @app.post("/api/v1/chat/sessions", status_code=201)
    def create_session(body: CreateSessionRequest, user: dict = Depends(_current_user)):
        return _c().chat.create_session(user["user_id"], body.title)

    @app.get("/api/v1/chat/sessions")
    def list_sessions(user: dict = Depends(_current_user)):
        return _c().chat.list_sessions(user["user_id"])


    @app.delete("/api/v1/chat/sessions/{session_id}")
    def delete_session(session_id: str, user: dict = Depends(_current_user)):
        ok = _c().chat.delete_session(session_id, user["user_id"])
        if not ok:
            raise HTTPException(status_code=404, detail="会话不存在或无权删除")
        return {"deleted": session_id}
    @app.get("/api/v1/chat/retriever-info")
    def retriever_info(_: dict = Depends(_current_user)):
        """返回当前 RAG 检索模式（vector / tfidf）与 chunk 数。"""
        return _c().retriever.stats()

    @app.get("/api/v1/chat/sessions/{session_id}/messages")
    def session_history(session_id: str, user: dict = Depends(_current_user)):
        s = _c().db.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if s is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if s["user_id"] != user["user_id"] and user["role"] != "admin":
            raise HTTPException(status_code=403, detail="无权访问该会话")
        return _c().chat.history(session_id)

    @app.post("/api/v1/chat/sessions/{session_id}/ask")
    def ask(session_id: str, body: AskRequest, user: dict = Depends(_current_user)):
        s = _c().db.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if s is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if s["user_id"] != user["user_id"]:
            raise HTTPException(status_code=403, detail="无权访问该会话")
        if not body.question.strip():
            raise HTTPException(status_code=400, detail="问题不能为空")
        return _c().chat.ask(session_id, user["user_id"], body.question.strip(),
                             attachments=body.attachments)

    @app.post("/api/v1/chat/messages/{message_id}/form-result")
    def save_form_result(message_id: str, body: dict, user: dict = Depends(_current_user)):
        """表单提交/取消后，把状态写回 form_draft：_submitted 或 _cancelled。
        切会话回来仍按此状态渲染，不再重复弹"编辑中"卡片。"""
        import json as _json
        row = _c().db.execute("SELECT form_draft FROM chat_messages WHERE id=? AND role=?", (message_id, "assistant")).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="消息不存在")
        try:
            draft = _json.loads(row["form_draft"] or "{}")
        except Exception:
            draft = {}
        if body.get("cancelled"):
            draft["_cancelled"] = True
        else:
            draft["_submitted"] = True
            draft["result"] = body.get("result", "")
            draft["request_no"] = body.get("request_no", "")
        _c().db.execute("UPDATE chat_messages SET form_draft=? WHERE id=?",
                         (_json.dumps(draft, ensure_ascii=False), message_id))
        _c().db.commit()
        return {"ok": True}

    # ==================================================================
    # 文件/图片上传
    # ==================================================================
    UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
    UPLOAD_DIR.mkdir(exist_ok=True)
    ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".doc", ".docx", ".txt", ".md", ".zip"}

    @app.post("/api/v1/upload")
    async def upload_file(file: UploadFile = File(...), user: dict = Depends(_current_user)):
        """上传文件/图片，返回可访问的 URL 与元信息。流式读取，累计超 10MB 即中止（不先读后判）。"""
        import secrets, time
        MAX_BYTES = 10 * 1024 * 1024
        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型 {ext}，允许：{sorted(ALLOWED_EXT)}")
        # 防重名 / 防路径穿越
        safe_name = f"{int(time.time())}_{secrets.token_hex(6)}{ext}"
        dest = UPLOAD_DIR / safe_name
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                raise HTTPException(status_code=413, detail="文件不能超过 10MB")
            chunks.append(chunk)
        content = b"".join(chunks)
        dest.write_bytes(content)
        is_image = ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
        return {
            "url": f"/uploads/{safe_name}",
            "name": file.filename,
            "type": "image" if is_image else "file",
            "size": len(content),
        }

    # ==================================================================
    # 前端页面
    # ==================================================================
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(str(static_dir / "index.html"))

    return app


app = create_app()
