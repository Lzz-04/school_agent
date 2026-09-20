import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import type { CourseFields, FormDraft, SubmitInfo } from "./formTypes";
import { fmtSchedule } from "./formTypes";
import { useFormSubmit } from "./useFormSubmit";
import { CancelledCard, FormActions, SubmittedResultCard } from "./SubmittedResultCard";

interface CourseItem {
  name: string;
  teacher: string;
  location: string;
  schedule: string;
  quota: number;
  enrolled?: number;
}

/** 对话内可编辑的选课申请表单卡片：拉取课程目录按课程名勾选，学生确认后才提交。 */
export function CourseFormCard({
  draft,
  user,
  messageId,
}: {
  draft: FormDraft;
  user: { user_id: string };
  messageId?: string;
}) {
  const f = (draft.fields || {}) as CourseFields;
  const [selected, setSelected] = useState<string[]>(Array.isArray(f.course_ids) ? f.course_ids : []);
  const [catalog, setCatalog] = useState<Record<string, CourseItem>>({});
  const { state, busy, result, info, finish, cancel } = useFormSubmit(draft, messageId);

  useEffect(() => {
    api.listCourses().then((r) => setCatalog(r.courses || {})).catch(() => {});
  }, []);

  const entries = Object.entries(catalog);

  function toggle(cid: string, remaining: number) {
    if (remaining <= 0) return;
    setSelected((sel) => (sel.includes(cid) ? sel.filter((c) => c !== cid) : [...sel, cid]));
  }

  async function submit() {
    if (!selected.length) return toast("请至少勾选一门课程", "err");
    await finish(async () => {
      const r = await api.submit({
        applicant_id: user.user_id,
        process_type: "course_selection",
        payload: { course_ids: selected },
        attachments: [],
        attachment_urls: [],
        client_request_no: "chat-" + Date.now(),
      });
      const names = selected.map((cid) => catalog[cid]?.name || cid).join("、");
      const summary =
        `✅ 选课申请已提交\n` +
        `单号：${r.request_no}\n` +
        `课程：${names}\n` +
        `当前状态：${r.status}`;
      const info: SubmitInfo = {
        request_no: r.request_no,
        status: r.status,
        courses: names,
      };
      return { summary, info };
    });
  }

  if (state === "cancelled") return <CancelledCard />;

  if (state === "submitted") {
    return (
      <SubmittedResultCard
        title="选课申请已提交"
        result={result}
        info={info}
        rows={[
          { label: "课程", value: String(info?.courses || ""), valueStyle: { lineHeight: 1.6 } },
        ]}
      />
    );
  }

  return (
    <div className="form-card">
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>📋 选课申请表单（按课程名勾选后提交）</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 280, overflowY: "auto", marginBottom: 10 }}>
        {entries.length === 0 && <div style={{ fontSize: 12, color: "#888" }}>课程目录加载中…</div>}
        {entries.map(([cid, c]) => {
          const remain = (c.quota ?? 0) - (c.enrolled ?? 0);
          const full = remain <= 0;
          const checked = selected.includes(cid);
          return (
            <label key={cid} style={{
              fontSize: 12, display: "flex", alignItems: "flex-start", gap: 8,
              opacity: full ? 0.5 : 1, cursor: full ? "not-allowed" : "pointer",
              border: "1px solid var(--line)", borderRadius: 8, padding: 8, margin: 0,
            }}>
              <input type="checkbox" checked={checked} disabled={full} onChange={() => toggle(cid, remain)} style={{ marginTop: 2 }} />
              <span>
                <b>{c.name}</b>（{cid}）
                <span style={{ color: "var(--text-2, #888)" }}> · {c.teacher} · {c.location} · {fmtSchedule(c.schedule)}</span>
                <br />
                <span style={{ color: checked ? "var(--ok, #16a34a)" : "#888" }}>
                  剩余名额：{remain}/{c.quota}{full ? " · 已满，不可选" : ""}
                </span>
              </span>
            </label>
          );
        })}
      </div>
      <FormActions busy={busy} onSubmit={submit} onCancel={cancel} />
    </div>
  );
}
