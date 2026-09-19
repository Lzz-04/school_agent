"""审批状态机（设计文档 5.1）。

状态：draft → pending_<node> → approved / rejected；任意非终态可 return 回退上一节点。
规则：任一节点 approve 才流转；reject 终止；return 回退（可多次）。
节点链由「流程模板静态 nodes」或「申请单提交时解析出的动态节点链」决定，
本模块只认节点 id 列表，不关心节点来自模板还是动态解析（扩展框架）。
"""

from __future__ import annotations

from ..domain import constants as C
from ..domain.errors import StateTransitionError
from ..domain.models import ProcessTemplateNode


def is_terminal(status: str) -> bool:
    return status in C.TERMINAL_STATUSES


def is_pending(status: str) -> bool:
    return status.startswith(C.STATUS_PENDING_PREFIX)


def node_of_status(status: str) -> str | None:
    """从 pending_<node_id> 解析节点 id；非待审状态返回 None。"""
    if is_pending(status):
        return status[len(C.STATUS_PENDING_PREFIX):]
    return None


def status_of_node(node_id: str) -> str:
    return f"{C.STATUS_PENDING_PREFIX}{node_id}"


def node_ids(nodes: list[ProcessTemplateNode]) -> list[str]:
    return [n.node_id for n in nodes]


def next_pending_status(nodes: list[ProcessTemplateNode], current_node_id: str) -> str:
    """返回当前节点在节点链中的下一节点状态；已是末节点返回空串。"""
    ids = [n.node_id for n in nodes]
    try:
        idx = ids.index(current_node_id)
    except ValueError:
        raise StateTransitionError(f"节点不在审批链中: {current_node_id}") from None
    if idx + 1 >= len(ids):
        return ""
    return status_of_node(ids[idx + 1])


def apply_decision(
    nodes: list[ProcessTemplateNode],
    current_status: str,
    current_node_id: str,
    decision: str,
) -> tuple[str, str | None]:
    """依据决策计算目标状态与目标节点（不落库，纯函数便于测试）。

    返回 (new_status, new_node_id)。
    - approve : 推进下一节点；末节点 approve → approved
    - reject  : → rejected（终止）
    - return  : 回退上一节点；首节点回退 → draft（退回重填，可再次提交）
    """
    if decision not in C.ALL_DECISIONS:
        raise StateTransitionError(f"非法决策: {decision}")

    if decision == C.DECISION_REJECT:
        return C.STATUS_REJECTED, None

    if decision == C.DECISION_RETURN:
        ids = [n.node_id for n in nodes]
        idx = ids.index(current_node_id)
        if idx <= 0:
            return C.STATUS_DRAFT, None          # 首节点退回重填
        prev = ids[idx - 1]
        return status_of_node(prev), prev

    # approve
    nxt = next_pending_status(nodes, current_node_id)
    if not nxt:
        return C.STATUS_APPROVED, None           # 末节点通过 → 终态
    return nxt, nxt[len(C.STATUS_PENDING_PREFIX):]


def validate_transition(
    nodes: list[ProcessTemplateNode],
    current_status: str,
    current_node_id: str,
    decision: str,
) -> None:
    """校验转移合法性（红牌「跳过审批节点」拦截点）。"""
    if is_terminal(current_status):
        raise StateTransitionError(f"终态不可再审批: {current_status}")
    if current_status != status_of_node(current_node_id):
        raise StateTransitionError(
            f"状态与当前节点不一致: status={current_status}, node={current_node_id}"
        )
    if decision not in C.ALL_DECISIONS:
        raise StateTransitionError(f"非法决策: {decision}")
