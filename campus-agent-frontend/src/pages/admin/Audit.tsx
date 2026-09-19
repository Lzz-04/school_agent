import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import { fmtTime } from "../../constants";

const EVENT_LABEL: Record<string, string> = {
  request_submitted: "提交申请",
  request_validated: "校验",
  request_advanced: "审批推进",
  request_archived: "归档",
  template_registered: "注册模板",
  notification_sent: "发送通知",
  permission_denied: "权限拒绝",
  optimistic_lock_conflict: "乐观锁冲突",
};

export default function Audit() {
  const [list, setList] = useState<any[]>([]);
  const [pending, setPending] = useState<number | null>(null);

  async function load() {
    api.audit(200).then(setList).catch(e => toast(e.message, "err"));
  }
  useEffect(() => { load(); }, []);

  async function dispatch() {
    try {
      const r = await api.dispatchOutbox();
      toast(`已投递 ${r.dispatched} 条，剩余待发 ${r.pending}`, "ok");
      setPending(r.pending);
    } catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">审计日志</h1>
        <div className="view-sub">append-only 操作留痕 · Outbox 通知投递</div>
      </div>

      <div className="toolbar">
        <button className="btn btn-primary btn-sm" onClick={dispatch}>投递待发通知 {pending !== null ? `(${pending})` : ""}</button>
        <button className="btn btn-ghost btn-sm" onClick={load}>刷新</button>
      </div>

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead><tr><th>时间</th><th>事件</th><th>实体</th><th>操作人</th><th>详情</th></tr></thead>
          <tbody>
            {list.map(e => (
              <tr key={e.id}>
                <td className="hint" style={{ whiteSpace: "nowrap" }}>{fmtTime(e.created_at)}</td>
                <td><span className="badge b-pend">{EVENT_LABEL[e.event_type] || e.event_type}</span></td>
                <td className="mono" style={{ fontSize: 12 }}>{e.entity_id}</td>
                <td className="mono">{e.actor_id || "-"}</td>
                <td className="hint" style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {e.detail ? JSON.stringify(e.detail) : "-"}
                </td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan={5} className="hint" style={{ textAlign: "center" }}>暂无审计事件</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
