"""LangGraph 编排：supervisor 路由 + 4 个专业 Agent（8 条通信链路）。

图结构（对齐设计文档 10.1 Mermaid 架构图）：
    supervisor
      ├──→ data_specialist          (校验)
      ├──→ communication_specialist (通知)
      ├──→ file_specialist          (归档)
      └──→ development_specialist   (扩展)
    每个专业 Agent ──→ supervisor（双向，8 条链路）
    专业 Agent 之间不直接通信；step_count 防循环。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from ..agents.specialist_agents import (
    communication_specialist_node,
    data_specialist_node,
    development_specialist_node,
    file_specialist_node,
)
from ..agents.state import AgentState, new_state
from ..agents.supervisor_agent import aggregate_result, route_after_supervisor, supervisor_node
from ..configs.settings import settings
from ..domain.errors import DomainError
from ..workflows.engine import WorkflowEngine

logger = logging.getLogger(__name__)

# 节点名 → 节点函数
NODES = {
    "supervisor": supervisor_node,
    "data_specialist": data_specialist_node,
    "communication_specialist": communication_specialist_node,
    "file_specialist": file_specialist_node,
    "development_specialist": development_specialist_node,
}

# supervisor 条件路由映射（允许名单）
ROUTE_MAP = {
    "data_specialist": "data_specialist",
    "communication_specialist": "communication_specialist",
    "file_specialist": "file_specialist",
    "development_specialist": "development_specialist",
    "END": END,
}


class ApprovalAgentGraph:
    """校园审批工作流 Agent 编排图。"""

    def __init__(
        self,
        engine: WorkflowEngine,
        *,
        llm_router: Callable[[str], str] | None = None,
        max_steps: int | None = None,
    ):
        self.engine = engine
        self.llm_router = llm_router
        self.max_steps = max_steps or settings.max_agent_steps
        self.graph = self._build()

    # ------------------------------------------------------------------
    def _build(self):
        g = StateGraph(AgentState)

        def _supervisor(state: AgentState) -> dict[str, Any]:
            return supervisor_node(state, llm_router=self.llm_router)

        g.add_node("supervisor", _supervisor)
        for name in ("data_specialist", "communication_specialist",
                     "file_specialist", "development_specialist"):
            g.add_node(name, NODES[name])

        g.add_edge(START, "supervisor")

        # 专业 Agent 完成后回 supervisor（双向链路）
        for name in ("data_specialist", "communication_specialist",
                     "file_specialist", "development_specialist"):
            g.add_edge(name, "supervisor")

        # supervisor 条件路由（允许名单 + step_count 防护）
        g.add_conditional_edges("supervisor", route_after_supervisor, ROUTE_MAP)

        return g.compile()

    # ------------------------------------------------------------------
    def run(self, **inputs: Any) -> dict[str, Any]:
        """运行编排图，返回聚合结果。

        输入示例：
            intent="submit", applicant_id="S10001", process_type="leave", payload={...}
            intent="advance", request_no="...", approver_id="T10001", decision="approve"
            intent="archive", request_no="..."
            intent="register", process_type="venue_reservation", payload={nodes, validation_rules}
            intent="status", request_no="..."
        """
        state = new_state(**inputs)
        try:
            final = self.graph.invoke(state)
        except Exception as exc:  # noqa: BLE001 - 编排异常收敛为结构化结果
            logger.exception("Agent 编排执行失败")
            # 领域错误透传结构化 code/status_code（供 API 层映射 HTTP 语义，如 403/409/429）
            if isinstance(exc, DomainError):
                return {"ok": False, "intent": state.get("intent"), "error": exc.message,
                        "error_code": exc.code, "status_code": exc.status_code,
                        "result": None, "context": state.get("context", {})}
            return {"ok": False, "intent": state.get("intent"), "error": str(exc),
                    "result": None, "context": state.get("context", {})}
        final["result"] = aggregate_result(final)
        return final["result"]
