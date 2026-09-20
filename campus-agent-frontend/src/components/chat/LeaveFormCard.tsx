import { useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../../api/client";
import { toast } from "../../store/toast";
import type { Attachment, FormDraft, LeaveFields, SubmitInfo } from "./formTypes";
import { daysBetween, nextApproverText } from "./formTypes";
import { useFormSubmit } from "./useFormSubmit";
import { CancelledCard, FormActions, SubmittedResultCard } from "./SubmittedResultCard";

/** 对话内可编辑的请假申请表单卡片：预填 LLM 抽取值，学生确认后才提交。 */
export function LeaveFormCard({
  draft,
  user,
  messageId,
  defaultAttachment,
}: {
  draft: FormDraft;
  user: { user_id: string };
  messageId?: string;
  defaultAttachment?: Attachment | null;
}) {
  const f = (draft.fields || {}) as LeaveFields;
  const [leaveType, setLeaveType] = useState(f.leave_type || "sick");
  const [startDate, setStartDate] = useState(f.start_date || "");
  const [endDate, setEndDate] = useState(f.end_date || "");
  const [reason, setReason] = useState(f.reason || "");
  const [att, setAtt] = useState<Attachment | null>(defaultAttachment || null);
  const fileRef = useRef<HTMLInputElement>(null);
  const { state, busy, result, info, finish, cancel } = useFormSubmit(draft, messageId);

  useEffect(() => { setAtt(defaultAttachment || null); }, [defaultAttachment]);

  const days = daysBetween(startDate, endDate);

  async function submit() {
    if (!startDate || !endDate) return toast("请先选择起止日期", "err");
    if (endDate < startDate) return toast("结束日期不能早于开始日期", "err");
    await finish(async () => {
      const attachments = att ? [{ url: att.url, name: att.name, type: att.type || "image", size: att.size || 0 }] : [];
      const r = await api.submit({
        applicant_id: user.user_id,
        process_type: "leave",
        payload: { leave_type: leaveType, start_date: startDate, end_date: endDate, reason },
        attachments,
        attachment_urls: att ? [att.url] : [],
        client_request_no: "chat-" + Date.now(),
      });
      const summary =
        `✅ 请假申请已提交\n` +
        `单号：${r.request_no}\n` +
        `时间：${startDate} ~ ${endDate}（共 ${days} 天）\n` +
        `原因：${reason || "个人原因"}\n` +
        (att ? `附件：${att.name}\n` : "") +
        `当前状态：${r.status}\n` +
        `下一步：等待${nextApproverText(days)}`;
      const info: SubmitInfo = {
        request_no: r.request_no,
        status: r.status,
        type_cn: leaveType === "sick" ? "病假" : "事假",
        range: `${startDate} ~ ${endDate}（共 ${days} 天）`,
        reason: reason || "个人原因",
        attachment: att ? att.name : "",
        next: "等待" + nextApproverText(days),
      };
      return { summary, info };
    });
  }

  async function pickFile(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    try {
      const r = await uploadFile(file);
      setAtt(r);
      toast("附件已附加", "ok");
    } catch (e: any) { toast(e.message, "err"); }
  }

  if (state === "cancelled") return <CancelledCard />;

  if (state === "submitted") {
    return (
      <SubmittedResultCard
        title="请假申请已提交"
        result={result}
        info={info}
        rows={[
          { label: "类型", value: String(info?.type_cn || "") },
          { label: "时间", value: String(info?.range || "") },
          { label: "事由", value: String(info?.reason || "") },
          { label: "附件", value: "🖼️ " + String(info?.attachment || ""), show: !!info?.attachment },
          { label: "下一步", value: String(info?.next || "") },
        ]}
      />
    );
  }

  return (
    <div className="form-card">
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>📋 请假申请表单（请核对后提交）</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <label style={{ fontSize: 12 }}>
          请假类型
          <select className="input" value={leaveType} onChange={(e) => setLeaveType(e.target.value)}>
            <option value="sick">病假</option>
            <option value="personal">事假</option>
          </select>
        </label>
        <label style={{ fontSize: 12 }}>
          请假天数
          <input className="input" readOnly value={days ? `${days} 天（含首尾）` : "请选日期"} />
        </label>
        <label style={{ fontSize: 12 }}>
          开始日期
          <input type="date" className="input" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label style={{ fontSize: 12 }}>
          结束日期
          <input type="date" className="input" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
      </div>
      <label style={{ fontSize: 12, display: "block", marginTop: 10 }}>
        请假事由
        <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
      </label>
      <div style={{ marginTop: 10 }}>
        <input ref={fileRef} type="file" accept="image/*" hidden onChange={e => pickFile(e.target.files)} />
        <div style={{ fontSize: 12, marginBottom: 4 }}>证明材料（病假建议上传）</div>
        {att ? (
          <span className="att-chip">🖼️ {att.name} <a onClick={() => setAtt(null)} style={{ color: "var(--danger)", cursor: "pointer" }}>✕</a></span>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={() => fileRef.current?.click()}>＋ 添加证明图片</button>
        )}
      </div>
      <FormActions busy={busy} onSubmit={submit} onCancel={cancel} />
    </div>
  );
}
