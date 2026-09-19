import { NavLink } from "react-router-dom";
import { useAuth } from "../store/auth";

interface NavEntry {
  section?: string;
  to?: string;
  label?: string;
  icon?: string;
  badge?: number;
}

const ICONS = {
  chat: "M21 11.5a8.4 8.4 0 0 1-8.5 8.4c-1.5 0-3-.4-4.2-1.1L3 20l1.2-4.3A8.2 8.2 0 0 1 3 11.5 8.4 8.4 0 0 1 11.5 3 8.4 8.4 0 0 1 21 11.5z",
  apply: "M12 4v16m-8-8h16",
  myreq: "M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2",
  workbench: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
  dashboard: "M3 3v18h18M8 17V9m5 8V5m5 12v-6",
  students: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm14 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  template: "M4 6h16M4 12h16M4 18h10",
  audit: "M12 8v4l3 2m6-2a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  profile: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
};

function navFor(role: string): NavEntry[] {
  if (role === "student") {
    return [
      { section: "学生服务" },
      { to: "/chat", label: "智能对话", icon: ICONS.chat },
      { to: "/apply", label: "发起申请", icon: ICONS.apply },
      { to: "/my-requests", label: "我的申请", icon: ICONS.myreq },
      { section: "账户" },
      { to: "/profile", label: "个人中心", icon: ICONS.profile },
    ];
  }
  if (role === "admin") {
    return [
      { section: "管理台" },
      { to: "/admin/dashboard", label: "数据看板", icon: ICONS.dashboard },
      { to: "/admin/students", label: "学生管理", icon: ICONS.students },
      { to: "/admin/process-types", label: "流程模板", icon: ICONS.template },
      { to: "/admin/audit", label: "审计日志", icon: ICONS.audit },
      { section: "其他" },
      { to: "/chat", label: "智能对话", icon: ICONS.chat },
      { to: "/profile", label: "个人中心", icon: ICONS.profile },
    ];
  }
  if (role === "counselor") {
    return [
      { section: "审核" },
      { to: "/counselor", label: "请假审核", icon: ICONS.workbench },
      { section: "其他" },
      { to: "/chat", label: "智能对话", icon: ICONS.chat },
      { to: "/profile", label: "个人中心", icon: ICONS.profile },
    ];
  }
  // 审批人：college_admin / university_leader / logistics / advisor
  return [
    { section: "审批" },
    { to: "/workbench", label: "审批工作台", icon: ICONS.workbench },
    { section: "其他" },
    { to: "/chat", label: "智能对话", icon: ICONS.chat },
    { to: "/profile", label: "个人中心", icon: ICONS.profile },
  ];
}

export default function Sidebar() {
  const { user } = useAuth();
  const items = navFor(user?.role || "");
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-seal"><span>审</span></div>
        <div>
          <div className="brand-name">校园流程自动化<br />Agent 平台</div>
          <div className="brand-sub">Campus Flow Agent</div>
        </div>
      </div>
      {items.map((item, i) =>
        item.section ? (
          <div key={i} className="nav-section">{item.section}</div>
        ) : (
          <NavLink key={item.to} to={item.to!} className={({ isActive }) => "nav-item" + (isActive ? " on" : "")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <path d={item.icon} />
            </svg>
            {item.label}
          </NavLink>
        )
      )}
      <div className="sidebar-foot">LangGraph · Supervisor · v1.0</div>
    </aside>
  );
}
