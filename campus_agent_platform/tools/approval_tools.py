"""审批类工具：submit_approval_request / advance_approval / get_approval_status。

- submit 幂等（client_request_no 去重）
- advance 非幂等写（乐观锁）
- get_status 只读
"""

from __future__ import annotations

from typing import Any

from ..workflows.engine import WorkflowEngine
from .registry import register_tool


def bind_approval_tools(engine: WorkflowEngine) -> None:
    """绑定审批类工具到指定引擎实例（依赖注入）。"""

    def submit(
        applicant_id: str,
        process_type: str,
        payload: dict[str, Any],
        attachment_urls: list[str] | None = None,
        client_request_no: str | None = None,
    ) -> dict[str, Any]:
        req = engine.submit(
            applicant_id=applicant_id,
            process_type=process_type,
            payload=payload,
            attachment_urls=attachment_urls,
            client_request_no=client_request_no,
        )
        return {
            "request_no": req.request_no,
            "status": req.status,
            "current_node_id": req.current_node_id,
            "process_type": req.process_type,
            "duplicated": client_request_no is not None
            and engine.requests.get_by_client_no(client_request_no) is req,
        }

    def advance(
        request_no: str,
        approver_id: str,
        decision: str,
        comment: str = "",
    ) -> dict[str, Any]:
        req = engine.advance(
            request_no=request_no, approver_id=approver_id,
            decision=decision, comment=comment,
        )
        return {
            "request_no": req.request_no,
            "status": req.status,
            "current_node_id": req.current_node_id,
            "version": req.version,
        }

    def get_status(request_no: str) -> dict[str, Any]:
        return engine.status_view(request_no)

    register_tool("submit_approval_request", submit)
    register_tool("advance_approval", advance)
    register_tool("get_approval_status", get_status)
