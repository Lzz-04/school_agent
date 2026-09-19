// 业务元数据（与后端 domain/constants.py、workflows/rules.py 对齐）

export const PROCESS_META: Record<string, { name: string; icon: string; desc: string }> = {
  leave: { name: "请假申请", icon: "🗓️", desc: "病假/事假，按天数分级审批" },
  course_selection: { name: "选课申请", icon: "📚", desc: "课程选课申请与先修校验" },
  reimbursement: { name: "报销申请", icon: "💰", desc: "经费报销，学院审核" },
  venue_reservation: { name: "场地预约", icon: "🏫", desc: "教室/活动室/报告厅预约" },
};

export const STATUS_META: Record<string, { label: string; cls: string }> = {
  draft: { label: "草稿", cls: "b-st" },
  approved: { label: "已通过", cls: "b-ok" },
  rejected: { label: "已驳回", cls: "b-rej" },
  returned: { label: "已退回", cls: "b-adv" },
  archived: { label: "已归档", cls: "b-arc" },
};

// 动态状态 pending_<node> 统一渲染为"待审批"
export function statusMeta(status: string): { label: string; cls: string } {
  if (STATUS_META[status]) return STATUS_META[status];
  if (status && status.startsWith("pending_")) {
    const node = status.slice("pending_".length);
    return { label: `待${NODE_META[node] || node}审批`, cls: "b-pend" };
  }
  return { label: status || "-", cls: "b-st" };
}

export const NODE_META: Record<string, string> = {
  student: "学生提交",
  counselor: "辅导员",
  college: "学院领导",
  university: "学校领导",
  venue: "后勤",
  advisor: "导师",
  archived: "归档",
};

// 角色 → 显示名
export const ROLE_META: Record<string, string> = {
  student: "学生",
  counselor: "辅导员",
  college_admin: "学院领导",
  university_leader: "学校领导",
  logistics: "后勤",
  finance: "财务",
  advisor: "导师",
  admin: "管理员",
  system: "系统",
};

// 节点 → 审批人角色（来自 workflows/rules.py，用于前端粗筛待办；最终权限以后端为准）
export const NODE_ROLE: Record<string, string> = {
  counselor: "counselor",
  college: "college_admin",
  university: "university_leader",
  venue: "logistics",
  advisor: "advisor",
};

export function fmtTime(ts?: number | string | null): string {
  if (!ts) return "-";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function fmtDate(ts?: number | string | null): string {
  if (!ts) return "-";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d.getTime())) return String(ts);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

// 登录后默认落地页
export function homePath(role: string): string {
  if (role === "student") return "/chat";
  if (role === "admin") return "/admin/dashboard";
  if (role === "counselor") return "/counselor";
  return "/workbench";
}
