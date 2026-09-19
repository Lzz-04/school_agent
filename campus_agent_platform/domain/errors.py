"""领域异常定义。"""


class DomainError(Exception):
    """领域错误基类。"""

    code = "domain_error"
    status_code = 400

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(DomainError):
    """业务规则校验失败（B2 异常输入 / 规则放行拦截）。"""

    code = "validation_failed"
    status_code = 422


class PermissionDeniedError(DomainError):
    """权限不足（RBAC deny by default，B1）。"""

    code = "permission_denied"
    status_code = 403


class StateTransitionError(DomainError):
    """非法状态转移（跳过审批节点 / 终态再操作，红牌拦截）。"""

    code = "invalid_state_transition"
    status_code = 409


class OptimisticLockError(DomainError):
    """乐观锁冲突：并发双审，后到者 409（设计文档 5.4）。"""

    code = "optimistic_lock_conflict"
    status_code = 409


class DuplicateRequestError(DomainError):
    """重复提交：client_request_no 唯一索引命中，返回已有记录（幂等）。"""

    code = "duplicate_request"
    status_code = 409


class NotFoundError(DomainError):
    """资源不存在。"""

    code = "not_found"
    status_code = 404


class TemplateNotFoundError(NotFoundError):
    """流程模板未注册。"""

    code = "template_not_found"


class RateLimitError(DomainError):
    """限流触发。"""

    code = "rate_limited"
    status_code = 429


class AgentExecutionError(DomainError):
    """Agent 编排执行失败。"""

    code = "agent_execution_failed"
    status_code = 500
