import { ReactNode } from "react";
import { statusMeta, NODE_META, PROCESS_META } from "../constants";

export function Badge({ status }: { status: string }) {
  const m = statusMeta(status);
  return <span className={`badge ${m.cls}`}>{m.label}</span>;
}

export function TypeName({ type }: { type: string }) {
  return <>{PROCESS_META[type]?.name || type}</>;
}

// 横向审批步骤条
export function FlowSteps({ nodes, status, currentNode }: { nodes: string[]; status: string; currentNode: string | null }) {
  if (!nodes?.length) return null;
  const rejected = status === "rejected";
  const approved = status === "approved" || status === "archived";
  const curIdx = currentNode ? nodes.indexOf(currentNode) : -1;
  return (
    <div className="flow">
      {nodes.map((n, i) => {
        const passed = approved || (curIdx >= 0 && i < curIdx);
        const current = !approved && !rejected && n === currentNode;
        const isRejected = rejected && n === currentNode;
        return (
          <div key={n} className={`flow-node ${passed ? "passed" : ""} ${current ? "current" : ""} ${isRejected ? "rejected" : ""}`}>
            {i > 0 && <div className="flow-line" />}
            <div className="flow-circle">{passed ? "✓" : isRejected ? "✕" : i + 1}</div>
            <div className="flow-label">{NODE_META[n] || n}</div>
          </div>
        );
      })}
    </div>
  );
}

// VL 附件校验结果
export function DocCheck({ docCheck }: { docCheck?: { authentic?: boolean | null; reason?: string; confidence?: number } | null }) {
  if (!docCheck || docCheck.authentic === undefined || docCheck.authentic === null) {
    return (
      <div className="doccheck none">
        <div className="dc-icon">📎</div>
        <div>
          <div className="dc-title">附件校验：未执行</div>
          <div className="dc-body">非图片附件或未上传附件，视觉模型未做真伪判断。</div>
        </div>
      </div>
    );
  }
  const ok = docCheck.authentic === true;
  const conf = typeof docCheck.confidence === "number" ? `置信度 ${(docCheck.confidence * 100).toFixed(0)}%` : "";
  return (
    <div className={`doccheck ${ok ? "ok" : "warn"}`}>
      <div className="dc-icon">{ok ? "✅" : "⚠️"}</div>
      <div>
        <div className="dc-title">{ok ? "附件通过视觉校验" : "附件疑似不实"}</div>
        <div className="dc-body">{docCheck.reason || (ok ? "证明材料与申请类型匹配。" : "请人工复核。")}　{conf}</div>
      </div>
    </div>
  );
}

export function Empty({ icon = "📭", text }: { icon?: string; text: string }) {
  return <div className="empty"><div className="empty-icon">{icon}</div><div>{text}</div></div>;
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <div className="field">
      <label>{label}</label>
      {children}
      {hint && !error && <div className="field-hint">{hint}</div>}
      {error && <div className="field-error">{error}</div>}
    </div>
  );
}

// 附件缩略图列表
export function Attachments({ items, base = "" }: { items: any[]; base?: string }) {
  if (!items?.length) return <div className="hint">无附件</div>;
  return (
    <div className="att-list">
      {items.map((a, i) => {
        const url = a.url || a;
        const full = /^https?:/.test(url) ? url : (base || "") + url;
        const isImg = a.type === "image" || /\.(png|jpe?g|gif|webp)$/i.test(url);
        return isImg ? (
          <a key={i} href={full} target="_blank" rel="noreferrer">
            <img className="att-thumb" src={full} alt={a.name || "附件"} />
          </a>
        ) : (
          <a key={i} className="att-chip" href={full} target="_blank" rel="noreferrer">
            📄 {a.name || url}
          </a>
        );
      })}
    </div>
  );
}
