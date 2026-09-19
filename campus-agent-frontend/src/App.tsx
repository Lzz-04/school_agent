import { useEffect } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./store/auth";
import { setUnauthorizedHandler } from "./api/client";
import { useToast } from "./store/toast";
import Sidebar from "./components/Sidebar";
import Topbar from "./components/Topbar";
import Login from "./pages/Login";
import Chat from "./pages/Chat";
import Apply from "./pages/Apply";
import MyRequests from "./pages/MyRequests";
import Profile from "./pages/Profile";
import Workbench from "./pages/Workbench";
import LeaveReview from "./pages/counselor/LeaveReview";
import AdminDashboard from "./pages/admin/Dashboard";
import AdminStudents from "./pages/admin/Students";
import AdminProcessTypes from "./pages/admin/ProcessTypes";
import AdminAudit from "./pages/admin/Audit";
import { homePath } from "./constants";

// 每个角色允许访问的路径前缀
function allowedPrefix(role: string): string[] {
  if (role === "student") return ["/chat", "/apply", "/my-requests", "/profile"];
  if (role === "admin") return ["/admin/", "/chat", "/profile"];
  if (role === "counselor") return ["/counselor", "/workbench", "/chat", "/profile"];
  return ["/workbench", "/chat", "/profile"]; // 各审批人
}

const TITLES: Record<string, string> = {
  "/chat": "智能对话",
  "/apply": "发起申请",
  "/my-requests": "我的申请",
  "/workbench": "审批工作台",
  "/counselor": "请假审核",
  "/profile": "个人中心",
  "/admin/dashboard": "数据看板",
  "/admin/students": "学生管理",
  "/admin/process-types": "流程模板",
  "/admin/audit": "审计日志",
};

function toastView({ toasts, remove }: { toasts: any[]; remove: (id: number) => void }) {
  return (
    <div className="toast-wrap">
      {toasts.map(t => (
        <div key={t.id} className={`toast ${t.kind === "ok" ? "ok" : t.kind === "err" ? "err" : ""}`}
          onClick={() => remove(t.id)}>{t.msg}</div>
      ))}
    </div>
  );
}

export default function App() {
  const { user, loading, bootstrap, logout } = useAuth();
  const { toasts, remove } = useToast();
  const loc = useLocation();
  const isLogin = loc.pathname === "/login";

  useEffect(() => {
    bootstrap();
    setUnauthorizedHandler(() => logout());
  }, []);

  if (isLogin) {
    // 已登录再访问 /login：直接进对应角色首页，不再停在"已登录"卡片
    if (!loading && user) return <Navigate to={homePath(user.role)} replace />;
    return <><Login />{toastView({toasts, remove})}</>;
  }
  if (loading) return <div style={{ padding: 60, color: "#64748B" }}>加载中…</div>;
  if (!user) return <Navigate to="/login" replace />;

  const prefixes = allowedPrefix(user.role);
  const ok = prefixes.some(p => (p.endsWith("/") ? loc.pathname.startsWith(p) : loc.pathname === p));
  if (!ok) return <Navigate to={homePath(user.role)} replace />;

  const crumb = TITLES[loc.pathname] || (loc.pathname.startsWith("/admin/") ? "管理台" : "工作台");

  return (
    <div className="app">
      <Sidebar />
      <div className="main-col">
        <Topbar crumb={crumb} />
        <main className="main">
          <Routes>
            <Route path="/chat" element={<Chat />} />
            <Route path="/apply" element={<Apply />} />
            <Route path="/my-requests" element={<MyRequests />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/workbench" element={<Workbench />} />
            <Route path="/counselor" element={<LeaveReview />} />
            <Route path="/admin/dashboard" element={<AdminDashboard />} />
            <Route path="/admin/students" element={<AdminStudents />} />
            <Route path="/admin/process-types" element={<AdminProcessTypes />} />
            <Route path="/admin/audit" element={<AdminAudit />} />
            <Route path="*" element={<Navigate to={homePath(user.role)} replace />} />
          </Routes>
        </main>
      </div>
      {toastView({toasts, remove})}
    </div>
  );
}
