// 统一 fetch 封装：带 token、统一错误、401 跳登录
const BASE = import.meta.env.VITE_API_BASE || ""; // vite proxy /api -> 8000

let token: string | null = localStorage.getItem("campus_token");
export function setToken(t: string | null) {
  token = t;
  if (t) localStorage.setItem("campus_token", t);
  else localStorage.removeItem("campus_token");
}
export function getToken() { return token; }

type Handler = (status: number) => void;
let onUnauthorized: Handler | null = null;
export function setUnauthorizedHandler(h: Handler | null) { onUnauthorized = h; }

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(msg: string, status: number, data: any) {
    super(msg);
    this.status = status;
    this.data = data;
  }
}

async function req<T = any>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;
  const r = await fetch(BASE + path, { ...opts, headers: { ...headers, ...(opts.headers as any || {}) } });
  const text = await r.text();
  let data: any = null;
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!r.ok) {
    if (r.status === 401 && token) onUnauthorized?.(401);
    let msg = r.statusText;
    if (data && typeof data === "object") {
      const d = data.detail;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d)) msg = d.map((e: any) => `${e?.loc?.join(".") || ""}: ${e?.msg || e}`).join("; ");
      else if (d) {
        const v = d?.details?.violations;
        msg = (d.message || "请求无效") + (Array.isArray(v) && v.length ? "：" + v.join("、") : "");
      }
    } else if (typeof data === "string" && data) {
      msg = data;
    }
    throw new ApiError(msg, r.status, data);
  }
  return data as T;
}

export const api = {
  // auth
  login: (body: { username: string; password: string }) =>
    req("/api/v1/auth/login", { method: "POST", body: JSON.stringify(body) }),
  me: () => req("/api/v1/auth/me"),
  changePassword: (body: { old_password: string; new_password: string }) =>
    req("/api/v1/auth/change-password", { method: "POST", body: JSON.stringify(body) }),

  // requests
  listRequests: (applicantId?: string) =>
    req("/api/v1/requests" + (applicantId ? "?applicant_id=" + encodeURIComponent(applicantId) : "")),
  getRequest: (no: string) => req("/api/v1/requests/" + encodeURIComponent(no)),
  listCourses: () => req("/api/v1/courses"),
  listVenues: () => req("/api/v1/venues"),
  submit: (body: any) => req("/api/v1/requests", { method: "POST", body: JSON.stringify(body) }),
  advance: (body: { request_no: string; approver_id: string; decision: string; comment?: string }) =>
    req(`/api/v1/requests/${encodeURIComponent(body.request_no)}/advance`, {
      method: "POST",
      body: JSON.stringify({ approver_id: body.approver_id, decision: body.decision, comment: body.comment || "" }),
    }),
  autoReview: (approverId: string) =>
    req("/api/v1/requests/auto-review", { method: "POST", body: JSON.stringify({ approver_id: approverId }) }),
  archive: (body: { request_no: string; actor_id: string }) =>
    req(`/api/v1/requests/${encodeURIComponent(body.request_no)}/archive`, {
      method: "POST", body: JSON.stringify({ actor_id: body.actor_id }),
    }),

  // templates / dashboard / audit / notifications
  listTemplates: () => req("/api/v1/process-types"),
  registerTemplate: (body: any) => req("/api/v1/process-types", { method: "POST", body: JSON.stringify(body) }),
  stats: () => req("/api/v1/dashboard/stats"),
  audit: (limit = 100) => req("/api/v1/audit/events?limit=" + limit),
  dispatchOutbox: () => req("/api/v1/notifications/outbox/dispatch", { method: "POST" }),
  sendNotification: (body: any) => req("/api/v1/notifications", { method: "POST", body: JSON.stringify(body) }),

  // chat
  chatSessions: () => req("/api/v1/chat/sessions"),
  chatCreateSession: (body: { title: string }) => req("/api/v1/chat/sessions", { method: "POST", body: JSON.stringify(body) }),
  chatDeleteSession: (sid: string) => req("/api/v1/chat/sessions/" + encodeURIComponent(sid), { method: "DELETE" }),
  chatMessages: (sid: string) => req(`/api/v1/chat/sessions/${encodeURIComponent(sid)}/messages`),
  chatSaveFormResult: (mid: string, body: any) => req("/api/v1/chat/messages/" + encodeURIComponent(mid) + "/form-result", { method: "POST", body: JSON.stringify(body) }),
  chatAsk: (sid: string, question: string, attachments: any[] = []) =>
    req(`/api/v1/chat/sessions/${encodeURIComponent(sid)}/ask`, {
      method: "POST", body: JSON.stringify({ question, attachments }),
    }),
  chatRetrieverInfo: () => req("/api/v1/chat/retriever-info"),

  // admin
  adminStudents: () => req("/api/v1/admin/students"),
  adminAddStudents: (body: any) => req("/api/v1/admin/students", { method: "POST", body: JSON.stringify(body) }),
  adminDeleteStudent: (uid: string) => req(`/api/v1/admin/students/${encodeURIComponent(uid)}`, { method: "DELETE" }),
  adminAssignStudentClass: (uid: string, classId: string) => req(`/api/v1/admin/students/${encodeURIComponent(uid)}/assign-class`, { method: "POST", body: JSON.stringify({ class_id: classId }) }),
  adminClasses: () => req("/api/v1/admin/classes"),
  adminCounselors: () => req("/api/v1/admin/counselors"),
  adminCreateClass: (body: any) => req("/api/v1/admin/classes", { method: "POST", body: JSON.stringify(body) }),
  adminDeleteClass: (cid: string) => req(`/api/v1/admin/classes/${encodeURIComponent(cid)}`, { method: "DELETE" }),
  adminAssignClassCounselor: (cid: string, cid2: string) => req(`/api/v1/admin/classes/${encodeURIComponent(cid)}/assign-counselor`, { method: "POST", body: JSON.stringify({ counselor_id: cid2 }) }),
  myClasses: () => req("/api/v1/counselor/my-classes"),
};

// 文件上传（FormData，非 JSON）
export async function uploadFile(file: File): Promise<{ url: string; name: string; type: string; size: number }> {
  const fd = new FormData();
  fd.append("file", file);
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = "Bearer " + token;
  const r = await fetch(BASE + "/api/v1/upload", { method: "POST", body: fd, headers });
  const text = await r.text();
  let data: any = null;
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!r.ok) {
    if (r.status === 401 && token) onUnauthorized?.(401);
    throw new ApiError(typeof data === "string" ? data : (data?.detail || r.statusText), r.status, data);
  }
  return data;
}
