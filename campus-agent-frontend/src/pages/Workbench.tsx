import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../store/auth";
import { api } from "../api/client";
import { toast } from "../store/toast";
import { Badge, Empty } from "../components/ui";
import RequestDetail from "../components/RequestDetail";
import { PROCESS_META, NODE_ROLE, fmtTime } from "../constants";

type Tab = "todo" | "done" | "all";

// 审批节点顺序：数字越大越靠后。用于粗判"已办"（已离开我这一级）
const NODE_RANK: Record<string, number> = { student: 0, counselor: 1, advisor: 1, venue: 1, college: 2, university: 3, archived: 9 };
const ROLE_NODE: Record<string, string> = { counselor: "counselor", college_admin: "college", university_leader: "university", logistics: "venue", advisor: "advisor" };

// 判断这单当前节点是否归当前用户审（粗筛，最终权限以后端为准）
function isMyTodo(req: any, userId: string, role: string): boolean {
  if (!req.current_node_id) return false;
  if (!req.status || !req.status.startsWith("pending_")) return false;
  const needRole = NODE_ROLE[req.current_node_id];
  return needRole === role;
}

export default function Workbench() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("todo");
  const [reqs, setReqs] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<any>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  const todo = useMemo(
    () => (user ? reqs.filter(r => isMyTodo(r, user.user_id, user.role)) : []),
    [user, reqs]
  );
  // 列表接口不返回 records，按状态粗筛已办：
  // 已结束（approved/rejected/archived），或已流转到我之后的节点（说明我已批过）
  const done = useMemo(() => {
    if (!user) return [];
    const myNode = ROLE_NODE[user.role];
    const myRank = myNode ? NODE_RANK[myNode] ?? -1 : -1;
    return reqs.filter(r => {
      if (r.status === "draft") return false;
      if (!r.status) return false;
      if (!r.status.startsWith("pending_")) return true; // 终态
      const curNode = r.current_node_id || r.status.slice("pending_".length);
      return myRank >= 0 && (NODE_RANK[curNode] ?? -1) > myRank;
    });
  }, [reqs, user]);

  async function load() {
    const r = await api.listRequests();
    setReqs(r || []);
    if (!selected && todo.length) setSelected(todo[0].request_no);
  }
  useEffect(() => { load().catch(e => toast(e.message, "err")); }, [user?.user_id]);
  useEffect(() => {
    if (selected) api.getRequest(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  const list = tab === "todo" ? todo : tab === "done" ? done : reqs;
  const isMyNode = detail && todo.some(r => r.request_no === selected);
  const canArchive = user?.role === "college_admin" && detail && ["approved", "rejected"].includes(detail.status);

  async function act(decision: string) {
    if (!user || !detail) return;
    if (decision !== "approve" && !comment.trim()) {
      return toast("请填写" + (decision === "reject" ? "驳回原因" : "退回说明"), "err");
    }
    setBusy(true);
    try {
      await api.advance({ request_no: detail.request_no, approver_id: user.user_id, decision, comment });
      toast(decision === "approve" ? "已通过" : decision === "reject" ? "已驳回" : "已退回", "ok");
      setComment("");
      await load();
      setDetail(await api.getRequest(detail.request_no));
    } catch (e: any) {
      toast(e.message || "操作失败", "err");
    } finally { setBusy(false); }
  }

  async function archive() {
    if (!user || !detail) return;
    if (!confirm("确认归档 " + detail.request_no + "？归档后不可再审批")) return;
    try {
      await api.archive({ request_no: detail.request_no, actor_id: user.user_id });
      toast("已归档", "ok");
      setDetail(await api.getRequest(detail.request_no));
    } catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">审批工作台</h1>
        <div className="view-sub">{user?.name} · 待办 {todo.length} · 已办 {done.length}</div>
      </div>
      <div className="chat-layout" style={{ height: "calc(100vh - 150px)", minHeight: 560 }}>
        <div className="chat-side">
          <div style={{ display: "flex", gap: 6, padding: 12, borderBottom: "1px solid var(--line)" }}>
            <button className={`btn btn-sm ${tab === "todo" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("todo")}>待办 {todo.length}</button>
            <button className={`btn btn-sm ${tab === "done" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("done")}>已办 {done.length}</button>
            <button className={`btn btn-sm ${tab === "all" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("all")}>全部</button>
          </div>
          <div className="chat-slist">
            {!list.length && <div className="chat-guard">{tab === "todo" ? "暂无待办" : "暂无记录"}</div>}
            {list.map((r: any) => {
              const suspicious = r.doc_check && r.doc_check.authentic === false;
              return (
                <div key={r.request_no} className={`req-row ${r.request_no === selected ? "on" : ""}`} onClick={() => setSelected(r.request_no)}>
                  <div className="rr-main">
                    <div className="rr-title">
                      {r.applicant_name || r.applicant_id} · {PROCESS_META[r.process_type]?.name || r.process_type}
                      {suspicious && <span style={{ color: "var(--danger)", marginLeft: 6 }} title="附件疑似不实">⚠</span>}
                    </div>
                    <div className="rr-sub">{r.request_no} · {fmtTime(r.created_at)}</div>
                  </div>
                  <Badge status={r.status} />
                </div>
              );
            })}
          </div>
        </div>

        <div className="chat-main">
          {!detail ? (
            <Empty icon="✅" text="从左侧选择一单开始审核" />
          ) : (
            <RequestDetail detail={detail} extra={
              <>
                {isMyNode && (
                  <div className="card" style={{ marginTop: 14, borderColor: "var(--brand-100)" }}>
                    <div className="card-title"><span className="tick"></span>我的审批意见</div>
                    <textarea className="input" rows={3} style={{ marginTop: 10 }}
                      placeholder="审批意见（驳回/退回必填）" value={comment}
                      onChange={e => setComment(e.target.value)} />
                    <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                      <button className="btn btn-jade" disabled={busy} onClick={() => act("approve")}>通过</button>
                      <button className="btn btn-amber" disabled={busy} onClick={() => act("return")}>退回上一级</button>
                      <button className="btn btn-danger" disabled={busy} onClick={() => act("reject")}>驳回</button>
                    </div>
                  </div>
                )}
                {canArchive && (
                  <div className="card" style={{ marginTop: 14 }}>
                    <button className="btn btn-dark" onClick={archive}>归档（SHA-256 留痕）</button>
                  </div>
                )}
              </>
            } />
          )}
        </div>
      </div>
    </>
  );
}
