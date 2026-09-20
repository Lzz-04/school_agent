import { useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import type { FormDraft, ReimbursementFields, SubmitInfo } from "./formTypes";
import { REIMBURSEMENT_CATS } from "./formTypes";
import { useFormSubmit } from "./useFormSubmit";
import { CancelledCard, FormActions } from "./SubmittedResultCard";

interface ReceiptRow {
  type: string;
  amount: string;
}

/** 对话内可编辑的报销申请表单卡片：预填金额/类别，票据由用户在表单内补充。 */
export function ReimbursementFormCard({
  draft,
  user,
  messageId,
}: {
  draft: FormDraft;
  user: { user_id: string };
  messageId?: string;
}) {
  const f = (draft.fields || {}) as ReimbursementFields;
  const [amount, setAmount] = useState(f.amount != null ? String(f.amount) : "");
  const [category, setCategory] = useState(f.category || "textbook");
  const [reason, setReason] = useState(f.reason || "");
  const [receipts, setReceipts] = useState<ReceiptRow[]>(
    Array.isArray(f.receipts) ? f.receipts.map((r) => ({ type: r.type || "receipt", amount: String(r.amount ?? "") })) : []
  );
  const { state, busy, result, finish, cancel } = useFormSubmit(draft, messageId);

  async function submit() {
    const amt = parseFloat(amount);
    if (isNaN(amt) || amt <= 0) return toast("请填写正确的报销金额", "err");
    const receiptsPayload = receipts
      .filter((r) => r.type && r.amount)
      .map((r) => ({ type: r.type, amount: parseFloat(r.amount) || 0 }));
    await finish(async () => {
      const r = await api.submit({
        applicant_id: user.user_id,
        process_type: "reimbursement",
        payload: { amount: amt, category, reason: reason || "报销申请", receipts: receiptsPayload },
        attachments: [],
        attachment_urls: [],
        client_request_no: "chat-" + Date.now(),
      });
      const summary =
        `✅ 报销申请已提交\n` +
        `单号：${r.request_no}\n` +
        `金额：¥${amt.toFixed(2)}\n` +
        `类别：${REIMBURSEMENT_CATS[category] || category}\n` +
        `票据：${receiptsPayload.length} 张\n` +
        `当前状态：${r.status}`;
      const info: SubmitInfo = { request_no: r.request_no, status: r.status };
      return { summary, info };
    });
  }

  function setReceipt(i: number, patch: Partial<ReceiptRow>) {
    setReceipts((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  if (state === "cancelled") return <CancelledCard />;

  if (state === "submitted") {
    return (
      <div className="form-card">
        <div style={{ fontSize: 13, color: "var(--ok, #16a34a)", marginBottom: 6 }}>📋 报销申请表单（已提交）</div>
        <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 13 }}>{result}</pre>
      </div>
    );
  }

  return (
    <div className="form-card">
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>📋 报销申请表单（请核对后提交）</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={{ fontSize: 12 }}>
          报销金额（元）
          <input type="number" className="input" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label style={{ fontSize: 12 }}>
          报销类别
          <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
            {Object.entries(REIMBURSEMENT_CATS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
      </div>
      <label style={{ fontSize: 12, display: "block", marginTop: 10 }}>
        报销事由
        <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
      </label>
      <div style={{ fontSize: 12, marginTop: 10, marginBottom: 4 }}>票据（收据/发票，合计应与报销金额一致）</div>
      {receipts.map((r, i) => (
        <div key={i} style={{ display: "flex", gap: 6, marginBottom: 6 }}>
          <select className="input" style={{ flex: 1 }} value={r.type}
            onChange={(e) => setReceipt(i, { type: e.target.value })}>
            <option value="receipt">收据</option>
            <option value="invoice">发票</option>
          </select>
          <input type="number" className="input" style={{ flex: 1 }} placeholder="金额"
            value={r.amount} onChange={(e) => setReceipt(i, { amount: e.target.value })} />
          <button className="btn btn-ghost btn-sm" onClick={() => setReceipts((rs) => rs.filter((_, idx) => idx !== i))}>✕</button>
        </div>
      ))}
      <button className="btn btn-ghost btn-sm" onClick={() => setReceipts((rs) => [...rs, { type: "receipt", amount: "" }])}>
        ＋ 添加票据
      </button>
      <FormActions busy={busy} onSubmit={submit} onCancel={cancel} />
    </div>
  );
}
