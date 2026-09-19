import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { api, uploadFile } from "../api/client";
import { toast } from "../store/toast";
import { PROCESS_META } from "../constants";
import { Field } from "../components/ui";

type PT = "leave" | "course_selection" | "reimbursement" | "venue_reservation";

function daysBetween(a: string, b: string): number {
  if (!a || !b) return 0;
  const d1 = new Date(a).getTime(), d2 = new Date(b).getTime();
  if (isNaN(d1) || isNaN(d2)) return 0;
  return Math.round(Math.abs(d2 - d1) / 86400000) + 1; // 含首尾
}

export default function Apply() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [type, setType] = useState<PT | "">("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // leave
  const [leaveType, setLeaveType] = useState("sick");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");
  // course
  const [courseIds, setCourseIds] = useState("");
  const [passedCourses, setPassedCourses] = useState("");
  // reimbursement
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  // venue
  const [venue, setVenue] = useState("classroom");
  const [venueStart, setVenueStart] = useState("");
  const [venueEnd, setVenueEnd] = useState("");
  const [purpose, setPurpose] = useState("");
  // attachments
  const [atts, setAtts] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);

  const leaveDays = type === "leave" ? daysBetween(startDate, endDate) : 0;
  const levelHint =
    type !== "leave" ? "" :
    leaveDays <= 1 ? "约 1 天：辅导员审批" :
    leaveDays <= 3 ? `${leaveDays} 天：辅导员审批` :
    leaveDays <= 7 ? `${leaveDays} 天：辅导员 → 学院领导` :
    `${leaveDays} 天：辅导员 → 学院领导 → 学校领导`;

  async function onPickFiles(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const f of Array.from(files)) {
        const r = await uploadFile(f);
        setAtts(prev => [...prev, r]);
      }
      toast("附件上传完成", "ok");
    } catch (e: any) {
      toast(e.message || "上传失败", "err");
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = ""; }
  }

  function buildPayload(): { process_type: PT; payload: any } {
    if (type === "leave") return { process_type: "leave", payload: { leave_type: leaveType, start_date: startDate, end_date: endDate, reason } };
    if (type === "course_selection") return {
      process_type: "course_selection",
      payload: {
        course_ids: courseIds.split(/[,，\s]+/).filter(Boolean),
        passed_courses: passedCourses.split(/[,，\s]+/).filter(Boolean),
      },
    };
    if (type === "reimbursement") return { process_type: "reimbursement", payload: { amount: Number(amount), note } };
    return {
      process_type: "venue_reservation",
      payload: { venue, start_time: venueStart, end_time: venueEnd, purpose },
    };
  }

  async function submit() {
    if (!type) return toast("请先选择申请类型", "err");
    if (!user) return;
    if (type === "leave") {
      if (!startDate || !endDate) return toast("请选择请假起止日期", "err");
      if (endDate < startDate) return toast("结束日期不能早于开始日期", "err");
    }
    if (type === "reimbursement" && (!amount || Number(amount) <= 0)) return toast("请填写有效金额", "err");
    const { process_type, payload } = buildPayload();
    setBusy(true);
    try {
      const r = await api.submit({
        applicant_id: user.user_id,
        process_type,
        payload,
        attachments: atts,
        attachment_urls: atts.map(a => a.url),
        client_request_no: "web-" + Date.now(),
      });
      toast("提交成功：" + r.request_no, "ok");
      nav("/my-requests");
    } catch (e: any) {
      toast(e.message || "提交失败", "err");
    } finally { setBusy(false); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">发起申请</h1>
        <div className="view-sub">选择类型并填写表单；带图片的证明材料将由视觉模型自动校验真伪</div>
      </div>

      <div className="type-grid">
        {Object.entries(PROCESS_META).map(([k, m]) => (
          <div key={k} className={`type-card ${type === k ? "on" : ""}`} onClick={() => setType(k as PT)}>
            <div className="type-icon">{m.icon}</div>
            <div className="type-name">{m.name}</div>
            <div className="type-desc">{m.desc}</div>
          </div>
        ))}
      </div>

      {type && (
        <div className="card">
          <div className="card-title"><span className="tick"></span>{PROCESS_META[type].name}表单</div>
          <div style={{ marginTop: 14 }}>
            {type === "leave" && (
              <div className="form-grid">
                <Field label="请假类型">
                  <select className="input" value={leaveType} onChange={e => setLeaveType(e.target.value)}>
                    <option value="sick">病假</option>
                    <option value="personal">事假</option>
                  </select>
                </Field>
                <Field label="天数预估" hint={levelHint}>
                  <input className="input" value={leaveDays ? leaveDays + " 天（含首尾）" : "选择起止日期后自动计算"} readOnly />
                </Field>
                <Field label="开始日期">
                  <input type="date" className="input" value={startDate} onChange={e => setStartDate(e.target.value)} />
                </Field>
                <Field label="结束日期">
                  <input type="date" className="input" value={endDate} onChange={e => setEndDate(e.target.value)} />
                </Field>
                <div className="full">
                  <Field label="请假事由">
                    <textarea className="input" value={reason} onChange={e => setReason(e.target.value)} placeholder="请简要说明请假原因" />
                  </Field>
                </div>
              </div>
            )}

            {type === "course_selection" && (
              <div className="form-grid">
                <div className="full">
                  <Field label="申请课程编号" hint="多个用逗号分隔，如 CS101, MA201">
                    <input className="input" value={courseIds} onChange={e => setCourseIds(e.target.value)} placeholder="CS101, MA201" />
                  </Field>
                </div>
                <div className="full">
                  <Field label="已修先修课" hint="没有可留空">
                    <input className="input" value={passedCourses} onChange={e => setPassedCourses(e.target.value)} placeholder="PHY101" />
                  </Field>
                </div>
              </div>
            )}

            {type === "reimbursement" && (
              <div className="form-grid">
                <Field label="金额（元）">
                  <input className="input" type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
                </Field>
                <div className="full">
                  <Field label="事由">
                    <textarea className="input" value={note} onChange={e => setNote(e.target.value)} placeholder="报销事由" />
                  </Field>
                </div>
              </div>
            )}

            {type === "venue_reservation" && (
              <div className="form-grid">
                <Field label="场地类型" hint={venue === "classroom" ? "教室为空链自动通过" : "需后勤人工审核"}>
                  <select className="input" value={venue} onChange={e => setVenue(e.target.value)}>
                    <option value="classroom">教室（自动通过）</option>
                    <option value="activity_room">活动室</option>
                    <option value="lecture_hall">报告厅</option>
                    <option value="computer_lab">机房</option>
                  </select>
                </Field>
                <Field label="用途">
                  <input className="input" value={purpose} onChange={e => setPurpose(e.target.value)} placeholder="如：班级会议" />
                </Field>
                <Field label="开始时间">
                  <input type="datetime-local" className="input" value={venueStart} onChange={e => setVenueStart(e.target.value)} />
                </Field>
                <Field label="结束时间">
                  <input type="datetime-local" className="input" value={venueEnd} onChange={e => setVenueEnd(e.target.value)} />
                </Field>
              </div>
            )}

            <div className="field" style={{ marginTop: 6 }}>
              <label>证明材料（可选，图片将做真伪校验）</label>
              <input ref={fileRef} type="file" multiple accept="image/*,.pdf,.doc,.docx" hidden onChange={e => onPickFiles(e.target.files)} />
              <div className="att-drop" onClick={() => fileRef.current?.click()}>
                {uploading ? "上传中…" : "点击选择图片 / PDF / 文档（≤10MB）"}
              </div>
              <div className="att-list">
                {atts.map((a, i) => (
                  <span key={i} className="att-chip">
                    {a.type === "image" ? "🖼️" : "📄"} {a.name}
                    <a style={{ color: "var(--danger)", cursor: "pointer" }} onClick={() => setAtts(prev => prev.filter((_, j) => j !== i))}>✕</a>
                  </span>
                ))}
              </div>
            </div>

            <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
              <button className="btn btn-primary" disabled={busy || uploading} onClick={submit}>
                {busy ? "提交中…" : "提交申请"}
              </button>
              <button className="btn btn-ghost" onClick={() => nav(-1)}>取消</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
