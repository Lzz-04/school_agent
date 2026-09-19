import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../../store/auth";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import { Badge, Empty } from "../../components/ui";
import RequestDetail from "../../components/RequestDetail";
import { fmtTime } from "../../constants";

type Tab = "todo" | "done" | "all";

/** 辅导员请假审核台：只关注自己节点（counselor）的请假申请。 */
export default function LeaveReview() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("todo");
  const [reqs, setReqs] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<any>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);

  // 只保留请假类申请
  const leaves = useMemo(() => reqs.filter(r => r.process_type === "leave"), [reqs]);

  const todo = useMemo(
    () => leaves.filter(r => r.current_node_id === "counselor" && r.status === "pending_counselor"),
    [leaves]
  );
  // 已审：已离开"待辅导员审批"状态的请假单（列表接口不返回 records，按状态粗筛）
  const done = useMemo(
    () => leaves.filter(r => r.status !== "pending_counselor" && r.status !== "draft"),
    [leaves]
  );

  async function load() {
    const r = await api.listRequests();
    setReqs(r || []);
  }
  useEffect(() => {
    load().catch(e => toast(e.message, "err"));
  }, [user?.user_id]);
  useEffect(() => {
    // 默认选中第一条待办
    if (!selected && todo.length) setSelected(todo[0].request_no);
  }, [todo]);
  useEffect(() => {
    if (selected) api.getRequest(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  async function runAutoReview() {
    if (!user) return;
    if (!todo.length) return toast("暂无待办", "err");
    if (!confirm(`将自动审核 ${todo.length} 条待办请假单，按规则自动通过或驳回，确定？`)) return;
    setAutoBusy(true);
    try {
      const r = await api.autoReview(user.user_id);
      toast(`自动审核完成：通过 ${r.approved?.length || 0} 条，驳回 ${r.rejected?.length || 0} 条，跳过 ${r.skipped?.length || 0} 条`, "ok");
      await load();
      if (selected) setDetail(await api.getRequest(selected).catch(() => null));
    } catch (e: any) {
      toast(e.message || "自动审核失败", "err");
    } finally { setAutoBusy(false); }
  }

  const list = tab === "todo" ? todo : tab === "done" ? done : leaves;
  const isMyNode = detail && todo.some(r => r.request_no === selected);

  async function act(decision: "approve" | "reject") {
    if (!user || !detail) return;
    if (decision === "reject" && !comment.trim()) {
      return toast("驳回时必须填写原因", "err");
    }
    setBusy(true);
    try {
      await api.advance({ request_no: detail.request_no, approver_id: user.user_id, decision, comment });
      toast(decision === "approve" ? "已通过该请假申请" : "已驳回", "ok");
      setComment("");
      await load();
      setDetail(await api.getRequest(detail.request_no));
    } catch (e: any) {
      toast(e.message || "操作失败", "err");
    } finally { setBusy(false); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">请假审核</h1>
        <div className="view-sub">{user?.name} · 待办 {todo.length} 单 · 已办 {done.length} 单</div>
      </div>
      <div className="chat-layout" style={{ height: "calc(100vh - 150px)", minHeight: 560 }}>
        <div className="chat-side">
          <div style={{ display: "flex", gap: 6, padding: 12, borderBottom: "1px solid var(--line)" }}>
            <button className={`btn btn-sm ${tab === "todo" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("todo")}>待办 {todo.length}</button>
            <button className={`btn btn-sm ${tab === "done" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("done")}>已办 {done.length}</button>
            <button className={`btn btn-sm ${tab === "all" ? "btn-primary" : "btn-ghost"}`} onClick={() => setTab("all")}>全部</button>
            <button className="btn btn-sm btn-primary" style={{ marginLeft: "auto" }} disabled={autoBusy || !todo.length} onClick={runAutoReview}>
              {autoBusy ? "审核中…" : "🤖 自动审核"}
            </button>
          </div>
          <div className="chat-slist">
            {!list.length && <div className="chat-guard">{tab === "todo" ? "暂无待办请假单" : "暂无记录"}</div>}
            {list.map((r: any) => {
              const days = r.payload?.days || "-";
              return (
                <div key={r.request_no} className={`req-row ${r.request_no === selected ? "on" : ""}`} onClick={() => setSelected(r.request_no)}>
                  <div className="rr-main">
                    <div className="rr-title">
                      {r.applicant_name || r.applicant_id} · {r.payload?.leave_type === "sick" ? "病假" : "事假"}
                      <span style={{ marginLeft: 6, color: "var(--mute)", fontWeight: 400 }}>{r.payload?.start_date} ~ {r.payload?.end_date}</span>
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
            <Empty icon="📋" text="从左侧选择一条请假申请开始审核" />
          ) : (
            <RequestDetail detail={detail} extra={
              <>
                {isMyNode && (
                  <div className="card" style={{ marginTop: 14, borderColor: "var(--brand-100)" }}>
                    <div className="card-title"><span className="tick"></span>审批意见</div>
                    <textarea className="input" rows={3} style={{ marginTop: 10 }}
                      placeholder="审批意见（驳回必填原因）" value={comment}
                      onChange={e => setComment(e.target.value)} />
                    <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
                      <button className="btn btn-jade" disabled={busy} onClick={() => act("approve")}>通过</button>
                      <button className="btn btn-danger" disabled={busy} onClick={() => act("reject")}>驳回</button>
                    </div>
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
