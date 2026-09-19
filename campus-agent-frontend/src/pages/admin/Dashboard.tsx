import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge } from "../../components/ui";
import { toast } from "../../store/toast";

export default function Dashboard() {
  const [s, setS] = useState<any>(null);

  useEffect(() => { api.stats().then(setS).catch(e => toast(e.message, "err")); }, []);
  if (!s) return <div className="empty">加载中…</div>;

  const byStatus = s.by_status || {};
  const cards = [
    { label: "申请总数", num: s.total_requests, foot: "全部流程", color: "var(--brand-600)" },
    { label: "进行中", num: Object.entries(byStatus).filter(([k]) => k.startsWith("pending_")).reduce((a, [, v]) => a + (v as number), 0), foot: "待审批", color: "var(--warn)" },
    { label: "已通过", num: byStatus.approved || 0, foot: "含已归档", color: "var(--ok)" },
    { label: "审计事件", num: s.audit_events, foot: "append-only", color: "var(--ink-2)" },
  ];

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">数据看板</h1>
        <div className="view-sub">平台运行概览</div>
      </div>
      <div className="stat-grid">
        {cards.map((c, i) => (
          <div className="stat" key={i}>
            <div className="stat-label">{c.label}</div>
            <div className="stat-num" style={{ color: c.color }}>{c.num}</div>
            <div className="stat-foot">{c.foot}</div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="card-title"><span className="tick"></span>按状态分布</div>
        <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
          {Object.entries(byStatus).length ? Object.entries(byStatus).map(([k, v]) => (
            <div key={k} style={{ padding: "10px 14px", background: "var(--surface-2)", borderRadius: 10, border: "1px solid var(--line-2)" }}>
              <Badge status={k} />
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 6 }}>{Number(v)}</div>
            </div>
          )) : <div className="hint">暂无数据</div>}
        </div>
      </div>

      <div className="card">
        <div className="card-title"><span className="tick"></span>其他指标</div>
        <table className="table" style={{ marginTop: 10 }}>
          <tbody>
            <tr><td>已注册流程模板</td><td className="mono">{s.templates}</td></tr>
            <tr><td>待投递通知（outbox）</td><td className="mono">{s.pending_notifications}</td></tr>
          </tbody>
        </table>
      </div>
    </>
  );
}
