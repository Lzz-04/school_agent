"""工具注册表：10 个工具的 schema 与实现绑定。

- get_tool_schema(name) -> dict（OpenAI function-calling 风格）
- call_tool(name, **kwargs) -> dict（统一调用入口，供 LangGraph ToolNode / Agent 使用）
"""

from __future__ import annotations

from typing import Any, Callable

from ..domain.errors import DomainError

# ----------------------------------------------------------------------
# 工具 schema（OpenAI 风格；字段与 tools.json 对齐）
# ----------------------------------------------------------------------
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "submit_approval_request": {
        "name": "submit_approval_request",
        "description": (
            "提交校园审批申请（请假/选课/报销），创建申请记录并推进到第一个审批节点；"
            "携带 client_request_no 幂等去重，重试安全"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "applicant_id": {"type": "string", "description": "申请人学号"},
                "process_type": {
                    "type": "string",
                    "enum": ["leave", "course_selection", "reimbursement"],
                    "description": "审批流程类型",
                },
                "payload": {
                    "type": "object",
                    "description": "流程特定业务字段：请假为起止日期/事由；选课为课程列表；报销为类别/金额/票据",
                },
                "attachment_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "证明材料（病假条/发票等）",
                },
                "client_request_no": {
                    "type": "string",
                    "description": "客户端幂等去重键，同一键重试返回已有记录",
                },
            },
            "required": ["applicant_id", "process_type", "payload"],
        },
    },
    "validate_request_rules": {
        "name": "validate_request_rules",
        "description": "按流程模板规则校验申请（日期有效性/名额/先修课/时间冲突/报销限额/票据完整性）",
        "parameters": {
            "type": "object",
            "properties": {
                "request_no": {"type": "string", "description": "待校验申请号"},
            },
            "required": ["request_no"],
        },
    },
    "check_permission": {
        "name": "check_permission",
        "description": "基于 RBAC（deny by default）检查用户是否可对资源执行动作：学生/导师/辅导员/学院管理员/财务",
        "parameters": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "操作人账号"},
                "action": {"type": "string", "description": "动作：submit/approve/reject/return/view/archive"},
                "resource_no": {"type": "string", "description": "目标申请号"},
            },
            "required": ["user_id", "action", "resource_no"],
        },
    },
    "advance_approval": {
        "name": "advance_approval",
        "description": "推进审批：approve 流转下一节点、reject 终止、return 回退上一节点；乐观锁防并发双审，后到者 409",
        "parameters": {
            "type": "object",
            "properties": {
                "request_no": {"type": "string", "description": "申请号"},
                "approver_id": {"type": "string", "description": "审批人账号"},
                "decision": {"type": "string", "enum": ["approve", "reject", "return"], "description": "审批决策"},
                "comment": {"type": "string", "description": "审批意见"},
            },
            "required": ["request_no", "approver_id", "decision"],
        },
    },
    "get_approval_status": {
        "name": "get_approval_status",
        "description": "查询申请当前状态、审批链记录与归档信息（只读、幂等）",
        "parameters": {
            "type": "object",
            "properties": {
                "request_no": {"type": "string", "description": "申请号"},
            },
            "required": ["request_no"],
        },
    },
    "send_notification": {
        "name": "send_notification",
        "description": "发送通知（IM/邮件/SMS），经 outbox 投递保证不丢；失败降级人工升级",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient_id": {"type": "string", "description": "接收人账号"},
                "channel": {"type": "string", "enum": ["im", "email", "sms"], "description": "通知渠道"},
                "template": {"type": "string", "description": "通知模板标识"},
                "payload": {"type": "object", "description": "模板变量"},
                "request_no": {"type": "string", "description": "关联申请号"},
            },
            "required": ["recipient_id", "channel", "template", "payload"],
        },
    },
    "archive_record": {
        "name": "archive_record",
        "description": "终态申请归档：不可变审计记录 + 归档哈希；幂等（同单归档返回同一记录）",
        "parameters": {
            "type": "object",
            "properties": {
                "request_no": {"type": "string", "description": "申请号"},
                "actor_id": {"type": "string", "description": "操作人（默认系统）"},
            },
            "required": ["request_no"],
        },
    },
    "register_process_type": {
        "name": "register_process_type",
        "description": "注册新流程模板（节点序列+审批人角色规则+规则引用），版本化，不改核心引擎",
        "parameters": {
            "type": "object",
            "properties": {
                "process_type": {"type": "string", "description": "流程类型标识"},
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "node_id": {"type": "string"},
                            "approver_role": {"type": "string"},
                        },
                        "required": ["node_id", "approver_role"],
                    },
                    "description": "审批节点序列",
                },
                "validation_rules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "规则引用列表",
                },
                "actor_id": {"type": "string", "description": "操作人（需 system 角色）"},
            },
            "required": ["process_type", "nodes", "validation_rules"],
        },
    },
    "query_courses": {
        "name": "query_courses",
        "description": "查询课程目录（名额/先修课/时间/培养方案），选课规则校验的数据源（只读）",
        "parameters": {
            "type": "object",
            "properties": {
                "course_ids": {"type": "array", "items": {"type": "string"}, "description": "课程编号列表"},
                "semester": {"type": "string", "description": "学期（预留）"},
            },
            "required": ["course_ids"],
        },
    },
    "check_reimbursement_limit": {
        "name": "check_reimbursement_limit",
        "description": "检查报销金额是否超出类别限额（教材/会议/差旅/设备/其他）（只读）",
        "parameters": {
            "type": "object",
            "properties": {
                "applicant_id": {"type": "string", "description": "申请人"},
                "amount": {"type": "number", "description": "报销金额"},
                "category": {"type": "string", "description": "报销类别"},
            },
            "required": ["applicant_id", "amount", "category"],
        },
    },
}

TOOL_NAMES = list(TOOL_SCHEMAS.keys())

# 工具 → Agent 归属（设计文档 4 采用合同）
TOOL_OWNERSHIP: dict[str, list[str]] = {
    "supervisor": ["submit_approval_request", "get_approval_status", "check_permission"],
    "data_specialist": ["validate_request_rules", "check_reimbursement_limit", "query_courses"],
    "communication_specialist": ["send_notification"],
    "file_specialist": ["archive_record"],
    "development_specialist": ["register_process_type"],
    "workflow_engine": ["advance_approval"],  # 共享单写者，非 Agent 专属
}


# ----------------------------------------------------------------------
# 工具实现注册：名称 -> 可调用函数（返回 dict 结果）
# ----------------------------------------------------------------------
_TOOL_IMPLS: dict[str, Callable[..., dict[str, Any]]] = {}


def register_tool(name: str, fn: Callable[..., dict[str, Any]]) -> None:
    if name not in TOOL_SCHEMAS:
        raise KeyError(f"未知工具 schema: {name}")
    _TOOL_IMPLS[name] = fn


def call_tool(name: str, **kwargs: Any) -> dict[str, Any]:
    """统一工具调用入口：异常收敛为结构化错误，供 Agent / API 层消费。"""
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        raise DomainError(f"工具未实现: {name}")
    try:
        return {"ok": True, "tool": name, "data": impl(**kwargs)}
    except DomainError as exc:
        return {
            "ok": False,
            "tool": name,
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }


def get_tool_schema(name: str) -> dict[str, Any]:
    return TOOL_SCHEMAS[name]


def all_schemas() -> list[dict[str, Any]]:
    return list(TOOL_SCHEMAS.values())
