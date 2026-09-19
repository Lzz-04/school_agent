# 校园流程自动化 Agent 平台 · 前端（正式工程版）

Vite + React 18 + TypeScript + React Router + Zustand。深色 AI 控制台风格，纯真实后端（无 mock、无演示账号）。

## 启动

```bash
# 1) 后端（项目根目录）
cd D:\code\doubao_code\project-02
D:\code\doubao_code\project-02\campus_agent_platform\.venv\Scripts\python.exe -m campus_agent_platform.main api --host 127.0.0.1 --port 8000

# 2) 前端（另开终端）
cd D:\code\doubao_code\project-02\campus-agent-frontend
npm install
npm run dev
# 打开 http://127.0.0.1:5173
```

生产构建：`npm run build` → `dist/`。Vite 已配置 `/api` 代理到 `127.0.0.1:8000`。

## 账号（已写入 users 表）

| 用户名 | 密码 | 角色 | 说明 |
| --- | --- | --- | --- |
| admin | admin123 | 系统管理员 | 学生管理 |
| T10001 | 123456 | 导师 | 审批名下学生 |
| A20001 | 123456 | 学院管理员 | 学院节点 + 归档 |
| 20240001 | 123456 | 学生 | 张三 |
| 20240101 / 20240102 | 123456 | 学生 | 测试同学 A/B |

## 目录

```
src/
  api/client.ts          fetch 封装 + Bearer token + 401 跳登录
  store/auth.ts          Zustand：登录态 / bootstrap / logout
  constants.ts           业务元数据（流程/状态/课程/限额）
  tasks.ts               待办审批筛选（导师归属）
  components/            Sidebar / Topbar
  pages/                 Login Dashboard Submit Requests Approvals Reviewer Chat Agents Audit
  styles/global.css      深色主题（自旧单文件迁移）
```

## 与旧 demo 的差异

- 删除 MockDB/MockAPI、演示角色切换、"切换为演示数据"
- 登录后 `user_id` 直接作为 approver_id / actor_id，不再有演示 ID
- 路由守卫：未登录强制跳 `/login`，401 自动登出
- 九个页面：仪表盘 / 发起 / 我的 / 审批中心 / 审核工作台 / 智能对话 / Agent 编排 / 审计 / 登录
