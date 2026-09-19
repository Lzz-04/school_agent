"""通知 / 归档 / 扩展 / 权限类工具。

- send_notification  : outbox 入队 + 审计
- archive_record     : 幂等归档（同单返回同一记录）
- register_process_type : 模板注册（版本化）
- check_permission   : RBAC deny by default（只读）
"""

from __future__ import annotations

from typing import Any

from ..domain import constants as C
from ..domain.models import AuditEvent
from ..workflows.engine import WorkflowEngine
from .approval_tools import bind_approval_tools
from .registry import register_tool
from .validation_tools import bind_validation_tools


def bind_notification_tools(engine: WorkflowEngine) -> None:
    def send_notification(
        recipient_id: str,
        channel: str,
        template: str,
        payload: dict[str, Any],
        request_no: str = "",
    ) -> dict[str, Any]:
        if channel not in C.ALL_CHANNELS:
            raise ValueError(f"非法通知渠道: {channel}")
        msg = engine.outbox.enqueue(
            request_no=request_no,
            recipient_id=recipient_id,
            channel=channel,
            template=template,
            payload=payload,
        )
        engine.audit.append(
            AuditEvent(
                event_type=C.EVENT_NOTIFICATION_SENT,
                entity_id=request_no or msg.id,
                actor_id=C.ROLE_SYSTEM,
                detail={"msg_id": msg.id, "channel": channel, "recipient": recipient_id,
                        "template": template},
            )
        )
        engine.db.commit()
        return {"message_id": msg.id, "status": "queued"}

    register_tool("send_notification", send_notification)


def bind_archive_tools(engine: WorkflowEngine) -> None:
    def archive_record(request_no: str, actor_id: str = C.ROLE_SYSTEM) -> dict[str, Any]:
        req = engine.archive(request_no=request_no, actor_id=actor_id)
        return {
            "request_no": req.request_no,
            "status": req.status,
            "archive_hash": req.archive_hash,
            "archived_at": req.archived_at,
        }

    register_tool("archive_record", archive_record)


def bind_extension_tools(engine: WorkflowEngine) -> None:
    def register_process_type(
        process_type: str,
        nodes: list[dict[str, str]],
        validation_rules: list[str],
        actor_id: str = C.ROLE_SYSTEM,
    ) -> dict[str, Any]:
        tpl = engine.register_template(
            process_type=process_type,
            nodes=nodes,
            validation_rules=validation_rules,
            actor_id=actor_id,
        )
        return {
            "process_type": tpl.process_type,
            "version": tpl.version,
            "nodes": [n.model_dump() for n in tpl.nodes],
            "validation_rules": tpl.validation_rules,
        }

    register_tool("register_process_type", register_process_type)


def bind_permission_tool(engine: WorkflowEngine) -> None:
    def check_permission(user_id: str, action: str, resource_no: str = "") -> dict[str, Any]:
        """只读判定：allowed=false 时给出原因，不抛异常（供 B1 断言）。"""
        allowed = engine.matrix.can(user_id, action)
        reason = ""
        if not allowed:
            reason = f"用户 {user_id} 的角色无权执行 {action}"
        # 资源级：提交仅限本人、审批仅限当前节点审批人
        elif resource_no:
            req = engine.requests.get_optional(resource_no)
            if req is None:
                allowed, reason = False, f"资源不存在: {resource_no}"
            elif action == C.ACTION_SUBMIT and req.applicant_id != user_id:
                allowed, reason = False, "仅申请人本人可提交"
            elif action in {C.ACTION_APPROVE, C.ACTION_REJECT, C.ACTION_RETURN}:
                try:
                    tpl = engine.templates.get_latest(req.process_type)
                    nodes = engine._effective_nodes(req, tpl)
                    engine._require_node_approver(req, nodes, user_id, action)
                except Exception:  # noqa: BLE001
                    allowed, reason = False, f"用户 {user_id} 不是当前节点审批人"
        return {"user_id": user_id, "action": action, "resource_no": resource_no,
                "allowed": allowed, "reason": reason}

    register_tool("check_permission", check_permission)


def bind_all_tools(engine: WorkflowEngine) -> None:
    """绑定全部 10 个工具到引擎实例。"""
    bind_approval_tools(engine)
    bind_validation_tools(engine)
    bind_notification_tools(engine)
    bind_archive_tools(engine)
    bind_extension_tools(engine)
    bind_permission_tool(engine)
