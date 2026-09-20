import { useEffect, useState } from "react";
import { ReactNode } from "react";
import { Badge, FlowSteps, DocCheck, Attachments } from "./ui";
import { PROCESS_META, NODE_META, fmtTime } from "../constants";
import { api } from "../api/client";

function Row({ k, v }: { k: string; v: any }) {
  return (
    <div style={{ display: "flex", padding: "7px 0", borderBottom: "1px dashed var(--line-2)", fontSize: 13.5 }}>
      <span style={{ width: 110, color: "var(--mute)", flex: "none" }}>{k}</span>
      <span style={{ color: "var(--ink)" }}>{String(v ?? "-")}</span>
    </div>
  );
}

const WEEKDAY_CN: Record<string, string> = { Mon: "周一", Tue: "周二", Wed: "周三", Thu: "周四", Fri: "周五" };
function fmtSchedule(s: string) {
  let out = s || "";
  for (const [en, cn] of Object.entries(WEEKDAY_CN)) out = out.replace(en, cn);
  return out;
}

function payloadView(d: any, catalog: Record<string, any>, venues: Record<string, any>) {
  const p = d.payload || {};
  if (d.process_type === "leave") return (
    <>
      <Row k="请假类型" v={p.leave_type === "sick" ? "病假" : p.leave_type === "personal" ? "事假" : p.leave_type} />
      <Row k="起止" v={`${p.start_date} ~ ${p.end_date}`} />
      <Row k="事由" v={p.reason} />
    </>
  );
  if (d.process_type === "course_selection") {
    const ids: string[] = p.course_ids || [];
    return (
      <div style={{ display: "flex", flexDirection: "column" }}>
        {ids.length === 0 && <Row k="申请课程" v="-" />}
        {ids.map((cid) => {
          const c = catalog[cid];
          if (!c) return <Row key={cid} k="申请课程" v={cid} />;
          return (
            <div key={cid} style={{ padding: "7px 0", borderBottom: "1px dashed var(--line-2)", fontSize: 13.5 }}>
              <b>{c.name}</b>（{cid}）
              <span style={{ color: "var(--mute)" }}> · {c.teacher} · {c.location} · {fmtSchedule(c.schedule)}</span>
            </div>
          );
        })}
      </div>
    );
  }
  if (d.process_type === "reimbursement") return (
    <>
      <Row k="金额" v={"¥ " + p.amount} />
      <Row k="事由" v={p.note} />
    </>
  );
  if (d.process_type === "venue_reservation") {
    const vid = p.venue_id || p.venue;
    const v = vid ? venues[vid] : null;
    const venueName = v ? `${v.name}（${vid}）` : (p.venue || vid || "-");
    return (
      <>
        <Row k="场地" v={venueName} />
        <Row k="时间" v={`${p.start_time} ~ ${p.end_time}`} />
        <Row k="用途" v={p.purpose} />
        {p.participants ? <Row k="人数" v={p.participants + " 人"} /> : null}
      </>
    );
  }
  return <pre style={{ fontSize: 12, color: "var(--ink-2)", margin: 0 }}>{JSON.stringify(p, null, 2)}</pre>;
}

export default function RequestDetail({ detail, extra }: { detail: any; extra?: ReactNode }) {
  const [catalog, setCatalog] = useState<Record<string, any>>({});
  const [venues, setVenues] = useState<Record<string, any>>({});
  useEffect(() => {
    api.listCourses().then((r) => setCatalog(r.courses || {})).catch(() => {});
    api.listVenues().then((r) => setVenues(r.venues || {})).catch(() => {});
  }, []);
  const nodes: string[] = (detail.resolved_nodes || []).map((n: any) => n.node_id || n);
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 20 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ fontSize: 17, margin: 0 }}>{PROCESS_META[detail.process_type]?.name || detail.process_type}</h2>
        <Badge status={detail.status} />
        <span className="mono hint" style={{ marginLeft: "auto" }}>{detail.request_no}</span>
      </div>
      <div className="hint" style={{ marginTop: 6 }}>
        提交人 <b style={{ color: "var(--ink-2)" }}>{detail.applicant_name || detail.applicant_id}</b> · {fmtTime(detail.created_at)} · v{detail.version}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-title"><span className="tick"></span>申请内容</div>
        <div style={{ marginTop: 10 }}>{payloadView(detail, catalog, venues)}</div>
      </div>

      {nodes.length > 0 && (
        <div className="card" style={{ marginTop: 14 }}>
          <div className="card-title"><span className="tick"></span>审批流程</div>
          <FlowSteps nodes={nodes} status={detail.status} currentNode={detail.current_node_id} />
        </div>
      )}

      {detail.process_type !== "course_selection" && (
      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-title"><span className="tick"></span>附件</div>
        <div style={{ marginTop: 10 }}>
          <Attachments items={detail.attachments?.length ? detail.attachments : (detail.attachment_urls || []).map((u: string) => ({ url: u }))} />
          <DocCheck docCheck={detail.doc_check} />
        </div>
      </div>
      )}

      <div className="card" style={{ marginTop: 14 }}>
        <div className="card-title"><span className="tick"></span>审批记录</div>
        <div style={{ marginTop: 8 }}>
          {(detail.records || []).map((rc: any) => (
            <div key={rc.id} className="tl-item">
              <span className={`tl-dot ${rc.decision === "approve" ? "ok" : ""}`}></span>
              <div style={{ flex: 1 }}>
                <b>{rc.approver_id}</b> · {NODE_META[rc.node_id] || rc.node_id}
                <span className={`badge ${rc.decision === "approve" ? "b-ok" : rc.decision === "reject" ? "b-rej" : "b-adv"}`} style={{ marginLeft: 8 }}>
                  {rc.decision === "approve" ? "通过" : rc.decision === "reject" ? "驳回" : "退回"}
                </span>
                <span className="hint" style={{ marginLeft: 8 }}>{fmtTime(rc.created_at)}</span>
                {rc.comment && <div className="tl-comment">{rc.comment}</div>}
              </div>
            </div>
          ))}
          {!(detail.records || []).length && <div className="hint">暂无审批记录</div>}
        </div>
      </div>

      {extra}
    </div>
  );
}
