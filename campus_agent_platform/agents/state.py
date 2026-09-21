"""Agent 共享状态（LangGraph StateGraph 的 TypedDict）。

对齐 multi-agent-architect 技能的状态设计 + 校园审批域：
- user_goal / intent：本次 Agent 会话要完成的动作
- next_agent：supervisor 路由决策（允许名单校验）
- context：各 Agent 产生的工具结果
- step_count：防无限路由循环
"""

from __future__ import annotations

from typing import Any, TypedDict

from ..domain import constants as C


class AgentState(TypedDict, total=False):
    # --- 会话目标 ---
    intent: str                      # submit / advance / archive / register / status
    user_goal: str                   # 原始自然语言目标（LLM 模式使用）

    # --- 申请相关 ---
    request_no: str
    applicant_id: str
    process_type: str
    payload: dict[str, Any]
    attachment_urls: list[str]
    client_request_no: str
    approver_id: str
    decision: str
    comment: str
    actor_id: str                    # 操作人（归档/注册等系统动作的实际身份；API 层注入 JWT 当前用户）

    # --- 编排状态 ---
    tasks: list[str]
    completed_tasks: list[str]
    next_agent: str                  # 路由目标（允许名单）
    context: dict[str, Any]          # Agent 间传递的工具结果
    step_count: int
    error: str | None

    # --- 聚合结果 ---
    result: dict[str, Any] | None


# 允许名单：supervisor 只能路由到这些 Agent（防幻觉路由，技能最佳实践）
ALLOWED_AGENTS = {
    "data_specialist",
    "communication_specialist",
    "file_specialist",
    "development_specialist",
    "END",
}


def new_state(**kwargs: Any) -> AgentState:
    state: AgentState = {
        "intent": kwargs.get("intent", ""),
        "user_goal": kwargs.get("user_goal", ""),
        "request_no": kwargs.get("request_no", ""),
        "applicant_id": kwargs.get("applicant_id", ""),
        "process_type": kwargs.get("process_type", ""),
        "payload": kwargs.get("payload", {}),
        "attachment_urls": kwargs.get("attachment_urls", []),
        "client_request_no": kwargs.get("client_request_no", ""),
        "approver_id": kwargs.get("approver_id", ""),
        "decision": kwargs.get("decision", ""),
        "comment": kwargs.get("comment", ""),
        "actor_id": kwargs.get("actor_id", ""),
        "tasks": [],
        "completed_tasks": [],
        "next_agent": "END",
        "context": {},
        "step_count": 0,
        "error": None,
        "result": None,
    }
    return state


def intents() -> set[str]:
    return {"submit", "advance", "archive", "register", "status"}


def is_valid_intent(intent: str) -> bool:
    return intent in intents()
