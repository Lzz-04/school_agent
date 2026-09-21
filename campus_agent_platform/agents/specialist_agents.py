"""专业 Agent：规则校验 / 通知 / 归档审计 / 流程引擎扩展。

每个 Agent 单一职责（技能最佳实践），只绑定自己需要的工具；
完成后回传 supervisor（supervisor ↔ specialist 双向链路）。
"""

from __future__ import annotations

import logging
from typing import Any

from ..tools import registry as tools
from .state import AgentState

logger = logging.getLogger(__name__)


def _mark_completed(state: AgentState, task: str) -> None:
    completed = state.setdefault("completed_tasks", [])
    if task not in completed:
        completed.append(task)


def data_specialist_node(state: AgentState) -> dict[str, Any]:
    """规则校验 Agent：绑定 validate_request_rules / check_reimbursement_limit / query_courses。

    校验失败 → 标记错误并结束（异常输入不放行，红牌拦截点）。
    """
    request_no = state.get("request_no", "")
    if not request_no:
        state["error"] = "data_specialist: 缺少 request_no"
        state["next_agent"] = "END"
        return dict(state)

    res = tools.call_tool("validate_request_rules", request_no=request_no)
    state["context"]["validation"] = res
    _mark_completed(state, "validate_rules")

    if not res["ok"]:
        state["error"] = res["error"]["message"]
        state["next_agent"] = "END"
        state["result"] = {"ok": False, "error": res["error"]}
        return dict(state)

    if not res["data"].get("valid", False):
        # 规则校验失败：通知申请人并结束（不进入审批链）
        state["error"] = "业务规则校验未通过"
        state["next_agent"] = "communication_specialist"  # 通知申请人失败原因
        state["context"]["validation_failed"] = True
        return dict(state)

    # 校验通过 → 通知首节点审批人
    state["context"]["validation_failed"] = False
    state["next_agent"] = "communication_specialist"
    return dict(state)


def communication_specialist_node(state: AgentState) -> dict[str, Any]:
    """通知 Agent：绑定 send_notification（outbox 投递，不丢通知）。"""
    request_no = state.get("request_no", "")
    validation = state.get("context", {}).get("validation", {})
    validation_failed = state.get("context", {}).get("validation_failed", False)

    if validation_failed:
        # 校验失败通知申请人
        res = tools.call_tool(
            "send_notification",
            recipient_id=state.get("applicant_id", ""),
            channel="im",
            template="validation_failed",
            payload={"request_no": request_no, "violations": validation.get("data", {}).get("violations", [])},
            request_no=request_no,
        )
    else:
        # 正常通知：告知申请人已受理并转首节点审批（首节点审批人通知由引擎提交事务内发出）
        submit = state.get("context", {}).get("submit", {})
        res = tools.call_tool(
            "send_notification",
            recipient_id=state.get("applicant_id", ""),
            channel="im",
            template="request_accepted",
            payload={"request_no": request_no, "process_type": state.get("process_type", ""),
                     "status": submit.get("data", {}).get("status", "")},
            request_no=request_no,
        )
    state["context"]["notification"] = res
    _mark_completed(state, "notify_stakeholders" if not validation_failed else "notify_applicant")
    state["next_agent"] = "END"
    return dict(state)


def file_specialist_node(state: AgentState) -> dict[str, Any]:
    """归档审计 Agent：绑定 archive_record（幂等，终态归档 + 哈希）。

    S2 修复：归档操作人身份取自编排输入（API 层注入 JWT 当前用户），
    不再硬编码 SYS001——避免任意登录用户借系统角色越权归档终态单；
    SYS001 仅保留给系统内部调用（种子模板/CLI）。
    """
    request_no = state.get("request_no", "")
    actor_id = state.get("actor_id") or "SYS001"
    res = tools.call_tool("archive_record", request_no=request_no, actor_id=actor_id)
    state["context"]["archive"] = res
    _mark_completed(state, "archive_record")
    state["next_agent"] = "END"
    if not res["ok"]:
        state["error"] = res["error"]["message"]
        state["result"] = {"ok": False, "error": res["error"]}
    return dict(state)


def development_specialist_node(state: AgentState) -> dict[str, Any]:
    """流程引擎扩展 Agent：绑定 register_process_type（模板版本化，不改引擎）。

    同源修复（S2 同款）：注册操作人身份取自编排输入（API 层注入 JWT 当前用户），
    不再静默回退 SYS001——避免任意登录用户借系统角色注册流程模板。
    """
    res = tools.call_tool(
        "register_process_type",
        process_type=state.get("process_type", ""),
        nodes=state.get("payload", {}).get("nodes", []),
        validation_rules=state.get("payload", {}).get("validation_rules", []),
        actor_id=state.get("actor_id") or "SYS001",
    )
    state["context"]["register"] = res
    _mark_completed(state, "register_process_type")
    state["next_agent"] = "END"
    if not res["ok"]:
        state["error"] = res["error"]["message"]
        state["result"] = {"ok": False, "error": res["error"]}
    else:
        state["result"] = {"ok": True, "data": res["data"]}
    return dict(state)
