import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import type { FormDraft, SubmitInfo, VenueFields } from "./formTypes";
import { useFormSubmit } from "./useFormSubmit";
import { CancelledCard, FormActions, SubmittedResultCard } from "./SubmittedResultCard";

interface VenueItem {
  name: string;
  location: string;
  capacity: number;
  type?: string;
  auto_approve?: boolean;
  approval?: string;
}

/** 对话内可编辑的场地预约表单卡片（预填 LLM 抽取值，学生确认后才提交）。 */
export function VenueFormCard({
  draft,
  user,
  messageId,
  onBack,
}: {
  draft: FormDraft;
  user: { user_id: string };
  messageId?: string;
  onBack?: () => void;
}) {
  const f = (draft.fields || {}) as VenueFields;
  const [venueId, setVenueId] = useState<string>(f.venue_id || "");
  const [venueCatalog, setVenueCatalog] = useState<Record<string, VenueItem>>({});
  useEffect(() => {
    api.listVenues().then((r) => setVenueCatalog(r.venues || {})).catch(() => {});
  }, []);
  const [date, setDate] = useState(f.start_time ? String(f.start_time).slice(0, 10) : "");
  const [startT, setStartT] = useState(f.start_time ? String(f.start_time).slice(11, 16) : "");
  const [endT, setEndT] = useState(f.end_time ? String(f.end_time).slice(11, 16) : "");
  const [purpose, setPurpose] = useState(f.purpose || "");
  const [participants, setParticipants] = useState(f.participants ? String(f.participants) : "");
  const { state, busy, result, info, finish, cancel } = useFormSubmit(draft, messageId);

  async function submit() {
    if (!venueId) return toast("请选择要预约的场地", "err");
    if (!date || !startT || !endT) return toast("请选择日期与起止时间", "err");
    if (endT <= startT) return toast("结束时间必须晚于开始时间", "err");
    const num = parseInt(participants, 10);
    if (!num || num <= 0) return toast("请填写参加人数", "err");
    await finish(async () => {
      const r = await api.submit({
        applicant_id: user.user_id,
        process_type: "venue_reservation",
        payload: {
          venue_id: venueId,
          start_time: `${date} ${startT}`,
          end_time: `${date} ${endT}`,
          purpose: purpose || "活动",
          participants: num,
        },
        attachments: [],
        attachment_urls: [],
        client_request_no: "chat-" + Date.now(),
      });
      const summary =
        `✅ 场地预约已提交\n` +
        `单号：${r.request_no}\n` +
        `场地：${venueCatalog[venueId]?.name || venueId}\n` +
        `时间：${date} ${startT} ~ ${endT}\n` +
        `主题：${purpose || "活动"}（${num} 人）\n` +
        `当前状态：${r.status}`;
      const info: SubmitInfo = {
        request_no: r.request_no,
        status: r.status,
        venue_name: venueCatalog[venueId]?.name || venueId,
        time: `${date} ${startT} ~ ${endT}`,
        purpose: purpose || "活动",
        participants: num,
      };
      return { summary, info };
    }, true); // 场地预约的 form_draft 落库额外保存结构化 info（与原实现一致）
  }

  if (state === "cancelled") return <CancelledCard />;

  if (state === "submitted") {
    return (
      <SubmittedResultCard
        title="场地预约已提交"
        result={result}
        info={info}
        rows={[
          { label: "场地", value: String(info?.venue_name || "") },
          { label: "时间", value: String(info?.time || "") },
          { label: "用途", value: String(info?.purpose || "") },
          { label: "人数", value: info?.participants ? info.participants + " 人" : "" },
        ]}
      />
    );
  }

  return (
    <div className="form-card">
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>📋 场地预约表单（请核对后提交）</div>
      <div style={{ fontSize: 12, marginBottom: 6 }}>选择场地</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto", marginBottom: 10 }}>
        {Object.entries(venueCatalog).length === 0 && <div style={{ fontSize: 12, color: "#888" }}>场地目录加载中…</div>}
        {Object.entries(venueCatalog).map(([vid, v]) => {
          const checked = venueId === vid;
          return (
            <label key={vid} style={{
              fontSize: 12, display: "flex", alignItems: "flex-start", gap: 8, cursor: "pointer",
              border: "1px solid var(--line)", borderRadius: 8, padding: 8, margin: 0,
              borderColor: checked ? "var(--primary, #2563eb)" : "var(--line)",
              background: checked ? "#eef4ff" : "transparent",
            }}>
              <input type="radio" name="venue" checked={checked} onChange={() => setVenueId(vid)} style={{ marginTop: 2 }} />
              <span>
                <b>{v.name}</b>（{vid}）
                <span style={{ color: "var(--text-2, #888)" }}> · {v.location} · 容量 {v.capacity} 人</span>
                <br />
                <span style={{ color: checked ? "var(--primary, #2563eb)" : "#888" }}>{v.approval}</span>
              </span>
            </label>
          );
        })}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
        <label style={{ fontSize: 12 }}>
          日期
          <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label style={{ fontSize: 12 }}>
          开始时间
          <input type="time" className="input" value={startT} onChange={(e) => setStartT(e.target.value)} />
        </label>
        <label style={{ fontSize: 12 }}>
          结束时间
          <input type="time" className="input" value={endT} onChange={(e) => setEndT(e.target.value)} />
        </label>
        <label style={{ fontSize: 12 }}>
          参加人数
          <input type="number" className="input" value={participants} onChange={(e) => setParticipants(e.target.value)} />
        </label>
      </div>
      <label style={{ fontSize: 12, display: "block", marginTop: 10 }}>
        活动主题/用途
        <input className="input" value={purpose} onChange={(e) => setPurpose(e.target.value)} />
      </label>
      <FormActions
        busy={busy}
        onSubmit={submit}
        onCancel={cancel}
        extra={onBack ? (
          <button className="btn btn-ghost" disabled={busy} onClick={onBack}>
            ← 返回列表
          </button>
        ) : undefined}
      />
    </div>
  );
}
