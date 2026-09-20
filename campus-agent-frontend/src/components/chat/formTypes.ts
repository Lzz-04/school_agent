// 对话表单卡片共享类型 / 常量 / 工具（从 pages/Chat.tsx 拆出）

export interface LeaveFields {
  leave_type: string;
  start_date: string;
  end_date: string;
  reason: string;
}

export interface CourseFields {
  course_ids: string[];
}

export interface ReimbursementFields {
  amount: number;
  category: string;
  reason: string;
  receipts?: { type: string; amount: string }[];
}

export interface VenueFields {
  venue_id?: string;
  venue_type?: string;
  start_time?: string;
  end_time?: string;
  purpose?: string;
  participants?: number;
}

export type AnyFields = LeaveFields | CourseFields | ReimbursementFields | VenueFields;

export interface FormDraft {
  process_type: string;
  fields: AnyFields;
  _submitted?: boolean;
  _cancelled?: boolean;
  result?: string;
  request_no?: string;
  info?: SubmitInfo | null;
}

/** 提交成功后的结构化摘要信息（各表单字段不同，允许任意键） */
export type SubmitInfo = Record<string, string | number | undefined>;

/** api.submit 返回的申请单 */
export interface SubmitResponse {
  request_no: string;
  status: string;
  [key: string]: unknown;
}

export interface Attachment {
  url: string;
  name: string;
  type?: string;
  size?: number;
}

// ---------- 共享工具 ----------
export function daysBetween(a: string, b: string): number {
  if (!a || !b) return 0;
  const d1 = new Date(a).getTime(), d2 = new Date(b).getTime();
  if (isNaN(d1) || isNaN(d2)) return 0;
  return Math.round(Math.abs(d2 - d1) / 86400000) + 1;
}

export function nextApproverText(days: number): string {
  if (days <= 3) return "辅导员审批";
  if (days <= 7) return "辅导员 → 学院领导";
  return "辅导员 → 学院领导 → 学校领导";
}

const WEEKDAY_CN: Record<string, string> = { Mon: "周一", Tue: "周二", Wed: "周三", Thu: "周四", Fri: "周五" };
export function fmtSchedule(s: string): string {
  let out = s || "";
  for (const [en, cn] of Object.entries(WEEKDAY_CN)) out = out.replace(en, cn);
  return out;
}

// ---------- 共享常量 ----------
/** 提交后状态徽章配色（公共超集，各表单按实际出现状态命中） */
export const STATUS_MAP: Record<string, [string, string, string]> = {
  approved: ["#dcfce7", "#16a34a", "已通过"],
  pending_counselor: ["#ffedd5", "#ea580c", "待辅导员审批"],
  pending_advisor: ["#ffedd5", "#ea580c", "待导师审批"],
  pending_venue: ["#ffedd5", "#ea580c", "待后勤审核"],
  pending: ["#ffedd5", "#ea580c", "审批中"],
  rejected: ["#fee2e2", "#dc2626", "已驳回"],
};

export const REIMBURSEMENT_CATS: Record<string, string> = {
  textbook: "教材", conference: "学术会议", travel: "差旅", equipment: "设备", other: "其他",
};

export const VENUE_TYPES: Record<string, string> = {
  classroom: "教室（提交即通过）", activity_room: "活动室", lecture_hall: "报告厅", computer_lab: "机房",
};
