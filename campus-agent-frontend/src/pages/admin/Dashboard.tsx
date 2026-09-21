import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge } from "../../components/ui";
import { toast } from "../../store/toast";

// 轻量柱状图（CSS，不引第三方图表库，保持主包体积）
function Bars({ data, color = "var(--brand-500)", height = 110 }: {
  data: { label: string; value: number }[];
  color?: string;
  height?: number;
}) {
  const max = Math.max(1, ...data.map(d => d.value));
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height, paddingTop: 8 }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6, minWidth: 0 }}>
          <div
            style={{
              width: "72%", background: color, borderRadius: "6px 6px 0 0",
              height: Math.max(2, (d.value / max) * (height - 30)),
              opacity: d.value ? 1 : 0.25, transition: "height .3s",
            }}
            title={`${d.label}: ${d.value}`}
          />
          <div style={{ fontSize: 11, color: "var(--ink-2)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", maxWidth: "100%" }}>
            {d.label}
          </div>
        </div>
      ))}
    </div>
  );
}

const PROCESS_CN: Record<string, string> = {
  leave: "请假", course_selection: "选课", reimbursement: "报销", venue_reservation: "场地预约",
};

export default function Dashboard() {
  const [s, setS] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [metrics, setMetrics] = useState<any>(null);

  useEffect(() => {
    api.stats().then(setS).catch(e => toast(e.message, "err"));
    api.approvalStats(7).then(setStats).catch(e => toast(e.message, "err"));
    api.metricsSummary(7).then(setMetrics).catch(e => toast(e.message, "err"));
  }, []);

  if (!s) return <div className="empty">加载中…</div>;

  const byStatus = s.by_status || {};
  const cards = [
    { label: "申请总数", num: s.total_requests, foot: "全部流程", color: "var(--brand-600)" },
    { label: "进行中", num: Object.entries(byStatus).filter(([k]) => k.startsWith("pending_")).reduce((a, [, v]) => a + (v as number), 0), foot: "待审批", color: "var(--warn)" },
    { label: "已通过", num: byStatus.approved || 0, foot: "含已归档", color: "var(--ok)" },
    { label: "审计事件", num: s.audit_events, foot: "append-only", color: "var(--ink-2)" },
  ];

  const pending = stats?.total_pending ?? 0;
  const overdue = stats?.total_overdue ?? 0;
  const trend = stats?.trend || [];
  const askTrend = metrics?.trend || [];

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">数据看板 · 审批驾驶舱</h1>
        <div className="view-sub">平台运行概览 + 可观测性（近 7 日）</div>
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

      {/* ===== F2 审批驾驶舱 ===== */}
      <div className="card">
        <div className="card-title">
          <span className="tick"></span>审批驾驶舱
          <span className="hint" style={{ marginLeft: 10 }}>
            积压 {pending} · SLA 逾期 {overdue}
            {overdue > 0 && <b style={{ color: "#e5484d", marginLeft: 6 }}>⚠ 需关注</b>}
          </span>
        </div>
        <div className="metric-grid" style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12 }}>
          <div className="stat" style={{ minWidth: 140 }}>
            <div className="stat-label">待审批（积压）</div>
            <div className="stat-num" style={{ color: "var(--warn)" }}>{pending}</div>
            <div className="stat-foot">全部流程</div>
          </div>
          <div className="stat" style={{ minWidth: 140 }}>
            <div className="stat-label">SLA 逾期</div>
            <div className="stat-num" style={{ color: overdue ? "var(--danger, #e5484d)" : "var(--ok)" }}>{overdue}</div>
            <div className="stat-foot">超 {stats?.days ?? 7} 日内口径</div>
          </div>
        </div>

        <table className="table" style={{ marginTop: 14 }}>
          <thead>
            <tr><th>流程类型</th><th>单量</th><th>已办结</th><th>积压</th><th>SLA 逾期</th><th>平均办结耗时</th></tr>
          </thead>
          <tbody>
            {(stats?.by_process_type || []).map((t: any) => (
              <tr key={t.process_type}>
                <td>{PROCESS_CN[t.process_type] || t.process_type}</td>
                <td className="mono">{t.count}</td>
                <td className="mono">{t.terminal}</td>
                <td className="mono">{t.pending}</td>
                <td className="mono" style={{ color: t.overdue ? "#e5484d" : "inherit" }}>{t.overdue}</td>
                <td className="mono">{t.avg_duration_h ? `${t.avg_duration_h} h` : "—"}</td>
              </tr>
            ))}
            {(stats?.by_process_type || []).length === 0 && (
              <tr><td colSpan={6} className="hint">近 7 日暂无申请单</td></tr>
            )}
          </tbody>
        </table>

        <div className="card-title" style={{ marginTop: 18 }}>
          <span className="tick"></span>近 7 日提交 / 办结趋势
        </div>
        <div style={{ display: "flex", gap: 26, alignItems: "flex-start", marginTop: 8 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 2 }}>提交</div>
            <Bars data={trend.map((d: any) => ({ label: d.date.slice(5), value: d.submitted }))} color="var(--brand-500)" />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 2 }}>办结</div>
            <Bars data={trend.map((d: any) => ({ label: d.date.slice(5), value: d.terminal }))} color="var(--ok)" />
          </div>
        </div>

        <div className="card-title" style={{ marginTop: 18 }}>
          <span className="tick"></span>审批人负载
        </div>
        <table className="table" style={{ marginTop: 10 }}>
          <thead><tr><th>审批人</th><th>待办</th><th>已办</th></tr></thead>
          <tbody>
            {(stats?.by_approver || []).map((a: any) => (
              <tr key={a.approver_id}>
                <td>{a.name || a.approver_id}<span className="mono" style={{ color: "var(--ink-2)", marginLeft: 8 }}>{a.approver_id}</span></td>
                <td className="mono">{a.pending}</td>
                <td className="mono">{a.handled}</td>
              </tr>
            ))}
            {(stats?.by_approver || []).length === 0 && (
              <tr><td colSpan={3} className="hint">暂无审批记录</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* ===== F1 对话可观测性 ===== */}
      <div className="card">
        <div className="card-title"><span className="tick"></span>对话可观测性（近 7 日）</div>
        <div className="stat-grid" style={{ marginTop: 12 }}>
          <div className="stat"><div className="stat-label">对话轮次</div><div className="stat-num">{metrics?.total_asks ?? 0}</div><div className="stat-foot">LLM 生成 {metrics?.llm_used_asks ?? 0}</div></div>
          <div className="stat"><div className="stat-label">Token 消耗</div><div className="stat-num">{metrics?.tokens_total ?? 0}</div><div className="stat-foot">输入+输出</div></div>
          <div className="stat"><div className="stat-label">平均延迟</div><div className="stat-num">{metrics?.avg_latency_ms ?? 0}<span style={{ fontSize: 13 }}>ms</span></div><div className="stat-foot">P50 {metrics?.p50_latency_ms ?? 0} / P95 {metrics?.p95_latency_ms ?? 0} ms</div></div>
          <div className="stat"><div className="stat-label">平均检索命中</div><div className="stat-num">{metrics?.avg_retrieval_hits ?? 0}</div><div className="stat-foot">RAG chunk / 轮</div></div>
          <div className="stat"><div className="stat-label">Agent 编排</div><div className="stat-num">{metrics?.total_agent_runs ?? 0}</div><div className="stat-foot">/api/v1/agent/run</div></div>
        </div>
        <div className="card-title" style={{ marginTop: 18 }}>
          <span className="tick"></span>每日对话趋势
        </div>
        <div style={{ display: "flex", gap: 26, alignItems: "flex-start", marginTop: 8 }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 2 }}>对话数</div>
            <Bars data={askTrend.map((d: any) => ({ label: d.date.slice(5), value: d.asks }))} color="var(--brand-500)" />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: "var(--ink-2)", marginBottom: 2 }}>Token 数</div>
            <Bars data={askTrend.map((d: any) => ({ label: d.date.slice(5), value: d.tokens }))} color="var(--warn)" />
          </div>
        </div>
      </div>

      {/* ===== 原有：状态分布 / 其他指标 ===== */}
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
