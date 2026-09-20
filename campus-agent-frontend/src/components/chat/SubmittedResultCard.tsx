import { Fragment } from "react";
import type { CSSProperties, ReactNode } from "react";
import { STATUS_MAP } from "./formTypes";
import type { SubmitInfo } from "./formTypes";

/** 表单已取消占位卡（四个表单卡片共用，样式与原实现一致） */
export function CancelledCard() {
  return (
    <div className="form-card" style={{ opacity: 0.55 }}>
      <div style={{ fontSize: 13, color: "var(--text-2, #888)" }}>已取消本次申请</div>
    </div>
  );
}

/** 表单底部操作按钮行（提交 / 取消 / 可选附加按钮） */
export function FormActions({
  busy,
  onSubmit,
  onCancel,
  extra,
}: {
  busy: boolean;
  onSubmit: () => void;
  onCancel: () => void;
  extra?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
      <button className="btn btn-primary" disabled={busy} onClick={onSubmit}>
        {busy ? "提交中…" : "提交申请"}
      </button>
      <button className="btn btn-ghost" disabled={busy} onClick={onCancel}>
        取消
      </button>
      {extra}
    </div>
  );
}

export interface SubmittedRow {
  label: string;
  value: string;
  show?: boolean;
  valueStyle?: CSSProperties;
}

/**
 * 提交成功结果卡：单号 + 状态徽章 + 详情网格。
 * 单号/状态优先取结构化 info，缺失时从摘要文本正则兜底（刷新后不丢）。
 */
export function SubmittedResultCard({
  title,
  result,
  info,
  rows,
}: {
  title: string;
  result: string;
  info: SubmitInfo | null;
  rows: SubmittedRow[];
}) {
  const no =
    (info?.request_no !== undefined ? String(info.request_no) : "") ||
    (result.match(/单号：(\S+)/) || [])[1] ||
    "";
  const status =
    (info?.status !== undefined ? String(info.status) : "") ||
    (result.match(/当前状态：(\S+)/) || [])[1] ||
    "";
  const [bg, fg, label] = STATUS_MAP[status] || ["#f1f5f9", "#64748b", status || ""];
  return (
    <div className="form-card">
      <div style={{ fontSize: 14, fontWeight: 600, color: "#16a34a", marginBottom: 10 }}>✅ {title}</div>
      <div
        style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          padding: "10px 12px", background: "#f8fafc", borderRadius: 8, marginBottom: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: "#94a3b8" }}>申请单号</div>
          <div style={{ fontSize: 13, fontFamily: "monospace" }}>{no}</div>
        </div>
        {label && (
          <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 10, background: bg, color: fg }}>{label}</span>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "72px 1fr", gap: "8px 12px", fontSize: 13 }}>
        {rows.filter((r) => r.show !== false).map((r) => (
          <Fragment key={r.label}>
            <span style={{ color: "#94a3b8" }}>{r.label}</span>
            <span style={r.valueStyle}>{r.value}</span>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
