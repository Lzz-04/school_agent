"""审批编排 Agent（supervisor_agent）。

职责（设计文档 4）：
- 接收学生申请，意图识别与流程类型路由、任务分解、进度监控、质量把控、结果聚合
- 不直接落审批决策（关键审批保留人工，Agent 只推进状态）
- 绑定工具：submit_approval_request / get_approval_status / check_permission

路由：supervisor ↔ 每个专业 Agent 双向（8 条通信链路），专业 Agent 之间不直接通信。

实现要点：supervisor 是"状态感知协调器"——每个意图只执行一次核心动作，
之后依据已完成任务（completed_tasks）决定下一步，避免多轮往返重复执行。
"""

from __future__ import annotations

import logging
from typing import Any

from ..tools import registry as tools
from .state import ALLOWED_AGENTS, AgentState, is_valid_intent

logger = logging.getLogger(__name__)


def _completed(state: AgentState) -> list[str]:
    return state.get("completed_tasks", [])


def _done(state: AgentState, task: str) -> bool:
    return task in _completed(state)


def _fail(state: AgentState, message: str) -> dict[str, Any]:
    state["error"] = message
    state["next_agent"] = "END"
    state["result"] = {"ok": False, "error": message}
    return dict(state)


# ----------------------------------------------------------------------
def supervisor_node(state: AgentState, *, llm_router=None) -> dict[str, Any]:
    """supervisor 节点：意图识别 → 任务分解 → 路由（状态感知）。

    默认使用确定性规则路由（intent 字段）；llm_router 提供时走 LLM 意图识别。
    """
    state["step_count"] = state.get("step_count", 0) + 1
    intent = state.get("intent", "")

    # LLM 模式：从自然语言识别意图（预留接口，默认关闭）
    if llm_router is not None and not intent:
        intent = llm_router(state.get("user_goal", ""))
    if not is_valid_intent(intent):
        return _fail(state, f"未知意图: {intent}（允许: submit/advance/archive/register/status）")
    state["intent"] = intent

    if intent == "submit":
        return _supervise_submit(state)
    if intent == "advance":
        return _supervise_advance(state)
    if intent == "archive":
        return _supervise_archive(state)
    if intent == "register":
        return _supervise_register(state)
    if intent == "status":
        return _supervise_status(state)
    return _fail(state, f"未知意图: {intent}")


# ----------------------------------------------------------------------
def _supervise_submit(state: AgentState) -> dict[str, Any]:
    """submit 编排：提交 → 校验 → 通知 → 结束。"""
    ctx = state.setdefault("context", {})

    # 阶段 1：创建申请单（仅一次；client_request_no 幂等）
    if "submit" not in ctx:
        state["tasks"] = ["validate_rules", "notify_stakeholders"]
        res = tools.call_tool(
            "submit_approval_request",
            applicant_id=state["applicant_id"],
            process_type=state["process_type"],
            payload=state["payload"],
            attachment_urls=state.get("attachment_urls") or [],
            client_request_no=state.get("client_request_no") or None,
        )
        if not res["ok"]:
            return _fail(state, res["error"]["message"])
        ctx["submit"] = res["data"]
        state["request_no"] = res["data"]["request_no"]
        state["next_agent"] = "data_specialist"
        return dict(state)

    # 阶段 2：校验
    if not _done(state, "validate_rules"):
        state["next_agent"] = "data_specialist"
        return dict(state)

    # 阶段 3：通知（校验失败 → 通知申请人；通过 → 通知首节点审批人）
    validation_failed = ctx.get("validation_failed", False)
    notify_task = "notify_applicant" if validation_failed else "notify_stakeholders"
    if not _done(state, notify_task):
        state["next_agent"] = "communication_specialist"
        return dict(state)

    # 阶段 4：聚合结束
    state["next_agent"] = "END"
    state["result"] = {
        "ok": True,
        "request_no": state["request_no"],
        "status": ctx["submit"].get("status"),
        "validation_failed": validation_failed,
    }
    return dict(state)


def _supervise_advance(state: AgentState) -> dict[str, Any]:
    """advance 编排：推进状态（仅一次）→ 通知 → 结束。"""
    ctx = state.setdefault("context", {})

    if "advance" not in ctx:
        state["tasks"] = ["advance_approval", "notify_stakeholders"]
        res = tools.call_tool(
            "advance_approval",
            request_no=state["request_no"],
            approver_id=state["approver_id"],
            decision=state["decision"],
            comment=state.get("comment", ""),
        )
        if not res["ok"]:
            return _fail(state, res["error"]["message"])
        ctx["advance"] = res["data"]
        state["next_agent"] = "communication_specialist"
        return dict(state)

    if not _done(state, "notify_stakeholders"):
        state["next_agent"] = "communication_specialist"
        return dict(state)

    state["next_agent"] = "END"
    state["result"] = {"ok": True, "request_no": state["request_no"],
                       "status": ctx["advance"].get("status")}
    return dict(state)


def _supervise_archive(state: AgentState) -> dict[str, Any]:
    """archive 编排：归档（file_specialist）→ 结束。"""
    if "archive" not in state.get("context", {}):
        state["tasks"] = ["archive_record"]
        state["next_agent"] = "file_specialist"
        return dict(state)
    state["next_agent"] = "END"
    # 修复：专业 Agent 已标记错误时保留其结构化失败结果，不再覆盖为 ok:True
    # （否则工具收敛的 error.code 会丢失，API 层无法映射 403）
    if state.get("error") is None:
        state["result"] = {"ok": True, "request_no": state["request_no"]}
    return dict(state)


def _supervise_register(state: AgentState) -> dict[str, Any]:
    """register 编排：注册模板（development_specialist）→ 结束。"""
    if "register" not in state.get("context", {}):
        state["tasks"] = ["register_process_type"]
        state["next_agent"] = "development_specialist"
        return dict(state)
    state["next_agent"] = "END"
    # 修复：同上，保留专业 Agent 的结构化失败结果
    if state.get("error") is None:
        state["result"] = {"ok": True, "process_type": state.get("process_type")}
    return dict(state)


def _supervise_status(state: AgentState) -> dict[str, Any]:
    """status 编排：只读查询 → 结束。"""
    res = tools.call_tool("get_approval_status", request_no=state["request_no"])
    state["context"]["status"] = res
    state["next_agent"] = "END"
    state["result"] = {"ok": res["ok"], "data": res.get("data") or res.get("error")}
    return dict(state)


# ----------------------------------------------------------------------
def route_after_supervisor(state: AgentState) -> str:
    """supervisor 条件路由：仅允许名单内目标，防幻觉路由（技能最佳实践）。"""
    target = state.get("next_agent", "END")
    if target not in ALLOWED_AGENTS:
        logger.warning("非法路由目标 %s，强制结束", target)
        return "END"
    # step_count 防护：超过上限强制结束，避免无限循环
    if state.get("step_count", 0) > 50:
        state["error"] = "step_count 超限，强制结束"
        return "END"
    return target


def aggregate_result(state: AgentState) -> dict[str, Any]:
    """结果聚合：把各专业 Agent 的产出汇总为最终结果。"""
    ok = state.get("error") is None
    return {
        "ok": ok,
        "intent": state.get("intent"),
        "request_no": state.get("request_no"),
        "completed_tasks": _completed(state),
        "context": state.get("context", {}),
        "error": state.get("error"),
        "result": state.get("result"),
    }
