"""校园审批工作流 Agent 平台（Campus Approval Workflow Agent Platform）。

基于设计文档《校园审批工作流Agent-设计方案.md》实现：
- Supervisor（编排者 + 专业 Agent）模式，5 个 Agent，8 条通信链路
- 10 个工具契约，审批状态机，流程模板扩展机制，审计 / 幂等 / 乐观锁
- FastAPI 接口层 + LangGraph 编排 + SQLite 持久化
"""

__version__ = "1.0.0"
