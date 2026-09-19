"""应用组装：初始化数据库、种子模板、引擎、工具绑定、编排图。

单例容器，供 API / CLI / 测试共用。
"""

from __future__ import annotations

import logging
import os

from .auth import AuthService
from .configs.settings import Settings, settings as _settings
from .domain import constants as C
from .graphs.approval_graph import ApprovalAgentGraph
from .rag import ChatAgent, Retriever, seed_knowledge
from .storage.database import Database
from .storage.outbox import NotificationDispatcher
from .tools import misc_tools
from .tools.registry import TOOL_SCHEMAS
from .workflows.engine import PermissionMatrix, RateLimiter, WorkflowEngine, db_role_loader

logger = logging.getLogger(__name__)

# 内置种子模板（设计文档 5.3：请假 / 选课 / 报销；扩展示例 venue_reservation）
SEED_TEMPLATES = [
    {
        "process_type": C.PROCESS_LEAVE,
        # 实际审批链在提交时按请假天数动态解析（辅导员必审，>3 天加学院领导，
        # >7 天加学校领导）；此处静态 nodes 仅作兜底/展示用。
        "nodes": [
            {"node_id": "counselor", "approver_role": C.ROLE_COUNSELOR},
        ],
        "validation_rules": ["date_validity"],
    },
    {
        "process_type": C.PROCESS_COURSE_SELECTION,
        "nodes": [
            {"node_id": "advisor", "approver_role": C.ROLE_ADVISOR},
            {"node_id": "college", "approver_role": C.ROLE_COLLEGE_ADMIN},
        ],
        "validation_rules": ["course_quota", "prerequisite", "schedule_conflict"],
    },
    {
        "process_type": C.PROCESS_REIMBURSEMENT,
        "nodes": [
            {"node_id": "advisor", "approver_role": C.ROLE_ADVISOR},
            {"node_id": "college", "approver_role": C.ROLE_COLLEGE_ADMIN},
        ],
        "validation_rules": ["amount_validity", "reimbursement_limit", "receipt_completeness"],
    },
    {
        "process_type": C.PROCESS_VENUE_RESERVATION,
        # 实际审批链在提交时按 venue_type 动态解析：
        #   教室(classroom) 空链自动通过；活动室/报告厅/机房 走后勤人工审核
        "nodes": [
            {"node_id": "venue", "approver_role": C.ROLE_LOGISTICS},
        ],
        "validation_rules": ["venue_conflict"],
    },
]


class CampusAgentApp:
    """平台容器：统一持有 DB / 引擎 / 图 / 派发器。"""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        seed: bool = True,
        db_path: str | None = None,
    ):
        self.settings = settings or _settings
        if db_path:
            self.settings = Settings()
            self.settings.db_path = db_path
        self.settings.ensure_data_dir()
        self.db = Database(self.settings.db_path)
        self.engine = WorkflowEngine(
            self.db,
            # 角色权威来源：users 表实时角色（管理员批量导入的学生可正常授权）；
            # DB 无记录的种子演示账号回退默认映射
            matrix=PermissionMatrix(role_loader=db_role_loader(self.db)),
            limiter=RateLimiter(self.settings.rate_limit_per_minute),
        )
        misc_tools.bind_all_tools(self.engine)
        self.dispatcher = NotificationDispatcher(self.engine.outbox, sink=self.settings.notify_sink)
        self.graph = ApprovalAgentGraph(self.engine)
        # 鉴权 + RAG 对话
        self.auth = AuthService(self.db)
        self.retriever = Retriever(self.db)
        self.chat = ChatAgent(self.db, self.retriever, engine=self.engine)
        if seed:
            self._seed_templates()
            self.auth.seed_admin()
            seed_knowledge(self.db)
            self.retriever.load()

    # ------------------------------------------------------------------
    def _seed_templates(self) -> None:
        for tpl in SEED_TEMPLATES:
            if not self.engine.templates.exists(tpl["process_type"]):
                self.engine.register_template(
                    process_type=tpl["process_type"],
                    nodes=tpl["nodes"],
                    validation_rules=tpl["validation_rules"],
                    actor_id="SYS001",
                )
        self.db.commit()

    def dispatch_pending_notifications(self) -> int:
        return self.dispatcher.dispatch_pending()

    def close(self) -> None:
        self.db.close()


_app: CampusAgentApp | None = None


def get_app() -> CampusAgentApp:
    """获取全局应用实例（API 进程内单例）。"""
    global _app
    if _app is None:
        _app = CampusAgentApp()
    return _app
