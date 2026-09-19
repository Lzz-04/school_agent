"""数据模型（Pydantic v2）。

与设计文档 5.2 工具契约对齐：
- 申请单（approval_requests）：申请号、申请人、流程类型、业务字段、附件、状态、版本号（乐观锁）
- 审批记录（approval_records）：节点、审批人、决策、意见
- 流程模板（process_templates）：节点序列 + 审批人角色规则 + 规则引用 + 版本
- 审计事件（audit_events）：append-only
- 通知 outbox（outbox_messages）：状态提交与通知事件解耦，保证不丢通知（5.4）
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator

from . import constants as C


def new_request_no() -> str:
    """生成申请号：RQ + 时间戳 + 随机后缀。"""
    return f"RQ{int(time.time() * 1000)}{uuid.uuid4().hex[:6].upper()}"


def new_id() -> str:
    return uuid.uuid4().hex


class ApprovalRequest(BaseModel):
    """审批申请单（核心聚合根）。"""

    request_no: str = Field(default_factory=new_request_no)
    applicant_id: str
    process_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    attachment_urls: list[str] = Field(default_factory=list)
    client_request_no: str | None = None          # 幂等去重键
    status: str = C.STATUS_DRAFT
    current_node_id: str | None = None            # 当前审批节点
    resolved_nodes: list[dict[str, str]] = Field(default_factory=list)
    # 提交时按业务规则解析出的实际审批链（如请假按天数动态分级）；
    # 空则回退到模板静态 nodes。元素形如 {"node_id": ..., "approver_role": ...}
    version: int = 0                              # 乐观锁版本号
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    archived_at: float | None = None
    archive_hash: str | None = None               # 归档哈希（防篡改，5.4）
    doc_check: dict[str, Any] = Field(default_factory=dict)  # 附件视觉校验结果

    @field_validator("process_type")
    @classmethod
    def _process_type_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("process_type 不能为空")
        return v


class ApprovalRecord(BaseModel):
    """审批记录：每个节点的审批人决策留痕。"""

    id: str = Field(default_factory=new_id)
    request_no: str
    node_id: str
    approver_id: str
    decision: str
    comment: str = ""
    created_at: float = Field(default_factory=time.time)


class ProcessTemplateNode(BaseModel):
    """模板节点：节点 id + 审批人角色规则。"""

    node_id: str
    approver_role: str


class ProcessTemplate(BaseModel):
    """流程模板（扩展框架核心，5.3）。

    示例：
    {
      "process_type": "venue_reservation",
      "version": 1,
      "nodes": [
        {"node_id": "advisor", "approver_role": "advisor"},
        {"node_id": "college", "approver_role": "college_admin"}
      ],
      "validation_rules": ["date_validity", "venue_conflict"]
    }
    """

    process_type: str
    version: int = 1
    nodes: list[ProcessTemplateNode] = Field(default_factory=list)
    validation_rules: list[str] = Field(default_factory=list)
    auto_pass_rules: dict = Field(default_factory=dict)  # {"auto_pass_if_doc_valid": true}
    created_at: float = Field(default_factory=time.time)

    @field_validator("nodes")
    @classmethod
    def _nodes_not_empty(cls, v: list[ProcessTemplateNode]) -> list[ProcessTemplateNode]:
        if not v:
            raise ValueError("流程模板至少需要一个审批节点")
        ids = [n.node_id for n in v]
        if len(ids) != len(set(ids)):
            raise ValueError("模板节点 node_id 不能重复")
        return v

    def node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes]

    def status_of_node(self, node_id: str) -> str:
        return f"{C.STATUS_PENDING_PREFIX}{node_id}"


class AuditEvent(BaseModel):
    """审计事件（append-only，不可篡改依赖存储实现完整性校验）。"""

    id: str = Field(default_factory=new_id)
    event_type: str
    entity_type: str = "request"
    entity_id: str
    actor_id: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class OutboxMessage(BaseModel):
    """通知 outbox：状态提交与通知投递解耦（5.4 崩溃窗口补偿）。"""

    id: str = Field(default_factory=new_id)
    request_no: str
    recipient_id: str
    channel: str = C.CHANNEL_IM
    template: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"          # pending / sent / failed
    created_at: float = Field(default_factory=time.time)
