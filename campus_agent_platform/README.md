# 校园审批工作流 Agent 平台

基于《校园审批工作流 Agent - 设计方案.md》实现的 **Supervisor（编排者 + 专业 Agent）模式多 Agent 审批系统**：

**5 个 Agent、10 个工具、审批状态机、流程模板扩展机制**，带 **LangGraph 编排、FastAPI 接口层、SQLite 持久化、审计 / 幂等 / 乐观锁**。

技术栈：Python 3.12+・LangGraph・LangChain Core・FastAPI・SQLite・Pydantic v2・pytest



***

## 一、架构总览



```
&#x20;                        ┌───────────────────────────┐

&#x20;                        │   supervisor（审批编排 Agent）│

&#x20;                        │ 意图识别·路由·任务分解·聚合   │

&#x20;                        └──────────┬────────────────┘

&#x20;       ┌──────────────┬────────────┼──────────────┬──────────────┐

&#x20;       ▼              ▼            ▼              ▼              │

&#x20;data\_specialist communication file\_specialist development     共享

&#x20;(规则校验)    (通知)       (归档审计)   (流程扩展)    workflow\_engine

&#x20;       └──────────────┴────────────┴──────────────┴──────────────┘

&#x20;                       supervisor ↔ 专业 Agent 双向，共 8 条链路

&#x20;                        专业 Agent 之间不直接通信
```



* **supervisor\_agent（审批编排）**：接收申请、意图识别、流程类型路由、任务分解、进度监控、结果聚合；绑定 `submit_approval_request` / `get_approval_status` / `check_permission`

* **data\_specialist（规则校验）**：日期有效性、名额、先修课、时间冲突、报销限额、票据完整性；绑定 `validate_request_rules` / `check_reimbursement_limit` / `query_courses`

* **communication\_specialist（通知）**：outbox 模式发送 IM / 邮件 / SMS；绑定 `send_notification`

* **file\_specialist（归档审计）**：终态归档、不可变审计记录、归档哈希；绑定 `archive_record`

* **development\_specialist（流程扩展）**：注册新流程模板（版本化）；绑定 `register_process_type`

* **工作流引擎（单写者）**：所有状态推进统一执行，绑定 `advance_approval`（权限 + 乐观锁）

## 二、核心机制

### 审批状态机（请假主场景）



```
draft ──提交──▶ pending\_advisor ──导师approve──▶ pending\_college ──学院approve──▶ approved ──归档──▶ archived

&#x20;                 │  ▲                              │

&#x20;                 │  │ return（退回重填）              │ return（回退上一节点）

&#x20;                 ▼  │                              ▼

&#x20;              returned ◀────────────────────   returned

&#x20;                 │

&#x20;                 └── reject 任一节点 ──▶ rejected（终止）
```

规则：任一节点 **approve** 才流转；**reject** 终止；**return** 回退（可多次）。节点与审批人规则由流程模板配置，同一状态机骨架复用。

### 强性质保证



| 性质     | 机制                                                 |
| ------ | -------------------------------------------------- |
| 不重复提交  | `client_request_no` 唯一索引，重试安全                      |
| 不丢审批   | 工作流引擎单写者 + 审计日志可重放；通知走 **outbox 模式**（状态提交与通知事件同事务） |
| 审批不可篡改 | 审计事件 append-only + 归档 SHA-256 哈希                   |
| 并发双审   | 乐观锁版本号，后到者 409                                     |
| 权限     | RBAC deny by default + 导师归属校验（该单导师）                |

### 扩展框架（新增流程类型不改引擎）



```
{

&#x20; "process\_type": "venue\_reservation",

&#x20; "nodes": \[

&#x20;   {"node\_id": "advisor", "approver\_role": "advisor"},

&#x20;   {"node\_id": "college", "approver\_role": "college\_admin"}

&#x20; ],

&#x20; "validation\_rules": \["date\_validity", "venue\_conflict"]

}
```

## 三、快速开始



```
\# 1. 安装依赖（开发含测试工具：`requirements-dev.txt`）

pip install -r requirements-dev.txt

\# 2. 运行 CLI 演示（请假全流程：提交→导师→学院→归档）

python -m campus\_agent\_platform.main demo

\# 3. 运行 LangGraph 编排演示（supervisor → 校验 → 通知）

python -m campus\_agent\_platform.main graph

\# 4. 启动 API 服务（Swagger 文档：http://127.0.0.1:8000/docs）

python -m campus\_agent\_platform.main api

\# 5. 运行测试（153 用例，含 G1/G2 事务与占课、F1/F2 可观测性回归）

python -m pytest campus\_agent\_platform/tests -q

\# 6. 容器化一键启动（后端托管前端产物，单端口 8000；需 Docker）

docker compose up -d --build

\# 7. 前端开发模式（热更新，/api 代理到 127.0.0.1:8001）

cd campus-agent-frontend \&\& npm run dev
```

## 四、API 端点



| 方法   | 路径                                      | 说明                                   |
| ---- | --------------------------------------- | ------------------------------------ |
| POST | `/api/v1/requests`                      | 提交申请（幂等：`client_request_no` 去重）      |
| GET  | `/api/v1/requests/{request_no}`         | 查询申请状态与审批链                           |
| GET  | `/api/v1/requests?applicant_id=`        | 按申请人查询                               |
| POST | `/api/v1/requests/{request_no}/advance` | 审批推进：`approve` / `reject` / `return` |
| POST | `/api/v1/requests/{request_no}/archive` | 归档（终态）                               |
| POST | `/api/v1/process-types`                 | 注册新流程模板（扩展框架）                        |
| GET  | `/api/v1/process-types`                 | 模板列表                                 |
| GET  | `/api/v1/courses?course_ids=`           | 课程目录（规则源）                            |
| GET  | `/api/v1/audit/events`                  | 审计日志                                 |
| POST | `/api/v1/notifications/outbox/dispatch` | 通知 outbox 投递                         |
| POST | `/api/v1/check-permission`              | RBAC 权限判定                            |
| POST | `/api/v1/agent/run`                     | 端到端多 Agent 编排                        |
| GET  | `/api/v1/dashboard/stats`               | 仪表盘统计                                |
| GET  | `/api/v1/metrics/summary`               | 对话/编排可观测性聚合（token / 延迟 P50/P95 / 检索命中，管理员） |
| GET  | `/api/v1/dashboard/approval-stats`      | 审批驾驶舱（流程类型/审批人耗时、积压、SLA 逾期，管理员） |
| GET  | `/health`                               | 健康检查                                 |

## 五、目录结构



```
campus\_agent\_platform/

├── agents/          # 5 个 Agent 节点 + 共享状态（TypedDict）

├── tools/           # 10 个工具实现 + 注册表（schema 对齐 tools.json）

├── workflows/       # 状态机 + 审批引擎（单写者·乐观锁·幂等）+ 业务规则

├── graphs/          # LangGraph 编排（supervisor 路由 + step\_count 防护）

├── storage/         # SQLite 仓储 / 审计（append-only）/ outbox / 占课库 / 可观测性埋点

├── domain/          # 数据模型（Pydantic v2）+ 常量 + 异常

├── configs/         # 配置加载（无密钥硬编码，环境变量可覆盖）

├── prompts/         # 各 Agent 系统提示词（LLM 模式预留）

├── api/             # FastAPI 接口层（含可观测性/驾驶舱端点）

├── tests/           # A1-A3 核心场景 + B1-B4 原子场景 + 安全两轮 + G1/G2 + F1/F2 + 红牌穿透

├── app.py           # 应用组装（种子模板、工具绑定、编排图、埋点/统计）

├── requirements.txt # 运行时依赖（版本锁定）

├── requirements-dev.txt # 开发/CI 依赖（含 pytest-cov）

├── Dockerfile       # 多阶段：前端构建并入 static，单容器部署

└── main.py          # CLI 演示 / API 启动入口
```

## 六、测试与验收（对照设计文档第 7 节）



| 场景       | 覆盖点                           | 结果 |
| -------- | ----------------------------- | -- |
| A1 请假全流程 | 提交→导师→学院→归档、通知、幂等归档           | ✅  |
| A2 选课流程  | 培养方案匹配、名额、先修、时间冲突、退选释放        | ✅  |
| A3 报销流程  | 金额合理性、票据完整性、限额                | ✅  |
| B1 权限校验  | 学生越权拦截、该单导师校验、deny by default | ✅  |
| B2 异常输入  | 过去日期、负数金额、SQL 注入、特殊字符         | ✅  |
| B3 流程回退  | 驳回终止、退回上一节点、多级回退、通知           | ✅  |
| B4 数据一致性 | 申请单 / 审批链 / 审计一致、幂等、乐观锁       | ✅  |
| 红牌穿透     | 跳节点、异常放行、状态不一致、权限绕过           | ✅  |

运行 `python -m pytest campus_agent_platform/tests -q` → **153 passed**（覆盖率 82%，`--cov-fail-under=80` CI 门槛）。
后续迭代记录：`安全加固迭代记录_20260920.md`（第一轮）→ `安全加固迭代记录_第二轮_20260921.md`（P0 安全收口）→ `P1迭代记录_20260921.md`（显式事务/占课入库/可观测性/驾驶舱/Docker+CI）。

## 七、演示账号（RBAC）



| 账号              | 角色             | 说明              |
| --------------- | -------------- | --------------- |
| S10001 / S10002 | student        | 学生（导师均为 T10001） |
| T10001 / T10002 | advisor        | 导师              |
| C30001          | counselor      | 辅导员             |
| A20001          | college\_admin | 学院管理员           |
| F40001          | finance        | 财务              |
| SYS001          | system         | 系统（归档 / 模板注册）   |

## 八、设计文档对照



| 设计文档章节                          | 落地位置                                 |
| ------------------------------- | ------------------------------------ |
| §4 采用合同（Agent 定义）               | `agents/`、`tools/`                   |
| §5.1 审批状态机                      | `workflows/state_machine.py`         |
| §5.2 工具契约（10 schema）            | `tools/registry.py`（对齐 `tools.json`） |
| §5.3 扩展框架                       | `engine.register_template` + 种子模板    |
| §5.4 强性质（幂等 / 乐观锁 / 审计 /outbox） | `storage/`、`engine.py`               |
| §7 测试与验收                        | `tests/`                             |
| §10.1 Mermaid 架构图               | `graphs/approval_graph.py`           |

> 已知边界：真实校园 SSO / 课程目录 / 财务预算系统接口为协议假设（文档 §9 开放问题），当前以演示数据源实现，接口层已预留替换点。