import { useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../api/client";
import { useAuth } from "../store/auth";
import { toast } from "../store/toast";

interface LeaveFields {
  leave_type: string;
  start_date: string;
  end_date: string;
  reason: string;
}

interface FormDraft {
  process_type: string;
  fields: LeaveFields;
}

interface Msg {
  id?: string;
  role: string;
  content: string;
  created_at?: string;
  form_draft?: FormDraft | null;
  form_state?: "editing" | "submitted" | "cancelled";
}

function daysBetween(a: string, b: string): number {
  if (!a || !b) return 0;
  const d1 = new Date(a).getTime(), d2 = new Date(b).getTime();
  if (isNaN(d1) || isNaN(d2)) return 0;
  return Math.round(Math.abs(d2 - d1) / 86400000) + 1; // 含首尾
}

function nextApproverText(days: number): string {
  if (days <= 3) return "辅导员审批";
  if (days <= 7) return "辅导员 → 学院领导";
  return "辅导员 → 学院领导 → 学校领导";
}

/** 对话内可编辑的请假申请表单卡片：预填 LLM 抽取值，学生确认后才提交。 */
function LeaveFormCard({
  draft,
  user,
  onSubmitted,
}: {
  draft: FormDraft;
  user: { user_id: string };
  onSubmitted: (msg: Msg) => void;
}) {
  const f = draft.fields;
  const [leaveType, setLeaveType] = useState(f.leave_type || "sick");
  const [startDate, setStartDate] = useState(f.start_date || "");
  const [endDate, setEndDate] = useState(f.end_date || "");
  const [reason, setReason] = useState(f.reason || "");
  const [state, setState] = useState<"editing" | "submitted" | "cancelled">("editing");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");

  const days = daysBetween(startDate, endDate);

  async function submit() {
    if (!startDate || !endDate) return toast("请先选择起止日期", "err");
    if (endDate < startDate) return toast("结束日期不能早于开始日期", "err");
    setBusy(true);
    try {
      const r = await api.submit({
        applicant_id: user.user_id,
        process_type: "leave",
        payload: { leave_type: leaveType, start_date: startDate, end_date: endDate, reason },
        attachments: [],
        attachment_urls: [],
        client_request_no: "chat-" + Date.now(),
      });
      const summary =
        `✅ 请假申请已提交\n` +
        `单号：${r.request_no}\n` +
        `时间：${startDate} ~ ${endDate}（共 ${days} 天）\n` +
        `原因：${reason || "个人原因"}\n` +
        `当前状态：${r.status}\n` +
        `下一步：等待${nextApproverText(days)}`;
      setResult(summary);
      setState("submitted");
      toast("提交成功：" + r.request_no, "ok");
    } catch (e: any) {
      toast(e.message || "提交失败", "err");
    } finally {
      setBusy(false);
    }
  }

  if (state === "cancelled") {
    return (
      <div className="form-card" style={{ opacity: 0.55 }}>
        <div style={{ fontSize: 13, color: "var(--text-2, #888)" }}>已取消本次申请</div>
      </div>
    );
  }

  if (state === "submitted") {
    return (
      <div className="form-card">
        <div style={{ fontSize: 13, color: "var(--ok, #16a34a)", marginBottom: 6 }}>📋 请假申请表单（已提交）</div>
        <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontSize: 13 }}>{result}</pre>
      </div>
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
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button className="btn btn-primary" disabled={busy} onClick={submit}>
          {busy ? "提交中…" : "提交申请"}
        </button>
        <button className="btn btn-ghost" disabled={busy} onClick={() => setState("cancelled")}>
          取消
        </button>
      </div>
    </div>
  );
}

export default function Chat() {
  const { user } = useAuth();
  const [sessions, setSessions] = useState<any[]>([]);
  const [sid, setSid] = useState<string>("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [memTurns, setMemTurns] = useState(0);
  const [retriever, setRetriever] = useState<any>(null);
  const [pendingImg, setPendingImg] = useState<any | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function loadSessions() {
    try {
      const s = await api.chatSessions();
      setSessions(s);
      if (!sid && s.length) setSid(s[0].session_id);
    } catch { /* ignore */ }
  }
  useEffect(() => {
    loadSessions();
    api.chatRetrieverInfo().then(setRetriever).catch(() => {});
  }, []);
  useEffect(() => { if (sid) api.chatMessages(sid).then((h: any[]) => setMsgs(h.map((m) => ({
    ...m,
    form_draft: m.form_draft && Object.keys(m.form_draft).length ? m.form_draft : null,
  })))).catch(() => setMsgs([])); }, [sid]);
  useEffect(() => { boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight }); }, [msgs, busy]);

  async function newSession() {
    try {
      const s = await api.chatCreateSession({ title: "新对话 " + new Date().toLocaleTimeString() });
      setSid(s.session_id); setMsgs([]); loadSessions();
    } catch (e: any) { toast(e.message, "err"); }
  }

  async function delSession(s: any) {
    if (!confirm(`删除对话「${s.title || "未命名"}」？此操作不可恢复。`)) return;
    try {
      await api.chatDeleteSession(s.session_id);
      toast("已删除", "ok");
      const next = sessions.filter(x => x.session_id !== s.session_id);
      setSessions(next);
      if (sid === s.session_id) {
        setSid(next[0]?.session_id || "");
        setMsgs([]);
      }
    } catch (e: any) { toast(e.message || "删除失败", "err"); }
  }

  async function onPickImg(files: FileList | null) {
    const f = files?.[0];
    if (!f) return;
    try {
      const r = await uploadFile(f);
      setPendingImg(r);
      toast("图片已附加，发送时一并询问", "ok");
    } catch (e: any) { toast(e.message, "err"); }
  }

  async function ask() {
    const q = input.trim();
    if ((!q && !pendingImg) || busy) return;
    let currentSid = sid;
    if (!currentSid) {
      try {
        const s = await api.chatCreateSession({ title: (q || "图片提问").slice(0, 18) });
        currentSid = s.session_id; setSid(currentSid); loadSessions();
      } catch (e: any) { toast(e.message, "err"); return; }
    }
    const attachments = pendingImg ? [pendingImg] : [];
    setMsgs(m => [...m, { role: "user", content: q || "[图片]", ...(pendingImg ? { att: pendingImg.url } : {}) }, { role: "assistant", content: "思考中…" }]);
    setInput(""); setPendingImg(null); setBusy(true);
    try {
      const r = await api.chatAsk(currentSid, q, attachments);
      setMemTurns(r.memory_turns || 0);
      const cite = (r.citations || []).map((c: any) => `<span class="cite-chip">${c.title} · ${c.category}</span>`).join("");
      const draft: FormDraft | null = r.form_draft && Object.keys(r.form_draft).length ? r.form_draft : null;
      setMsgs(m => {
        const copy = [...m];
        copy[copy.length - 1] = {
          role: "assistant",
          content: r.answer + (cite ? "\n\n__CITE__" + cite : ""),
          form_draft: draft,
        };
        return copy;
      });
    } catch (e: any) {
      setMsgs(m => [...m.slice(0, -1), { role: "assistant", content: "请求失败：" + e.message }]);
    } finally { setBusy(false); }
  }

  function renderMsg(m: Msg & { att?: string }, i: number) {
    const isUser = m.role === "user";
    let html = m.content;
    let cite = "";
    if (!isUser && m.content.includes("__CITE__")) {
      const parts = m.content.split("__CITE__");
      html = parts[0]; cite = parts[1] || "";
    }
    return (
      <div key={i} className={`msg ${isUser ? "user" : "bot"}`}>
        <div className="msg-av">{isUser ? (user?.name?.[0] || "我") : "AI"}</div>
        <div style={{ maxWidth: "100%" }}>
          {m.att && <img src={m.att} alt="附件" style={{ maxWidth: 220, borderRadius: 10, marginBottom: 6, display: "block" }} />}
          <div className="msg-bub">
            <span style={{ whiteSpace: "pre-wrap" }} dangerouslySetInnerHTML={{ __html: html.replace(/</g, "&lt;") }} />
          </div>
          {cite && <div className="cite"><div className="cite-t">引用条文（RAG 检索）</div><span dangerouslySetInnerHTML={{ __html: cite }} /></div>}
          {!isUser && m.form_draft && m.form_draft.process_type === "leave" && user && (
            <LeaveFormCard draft={m.form_draft} user={user} onSubmitted={() => {}} />
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">智能对话</h1>
        <div className="view-sub">RAG 制度问答 + 短期记忆；说「我要请假」会弹出预填表单，核对后提交</div>
      </div>
      <div className="chat-layout" style={{ height: "calc(100vh - 150px)", minHeight: 560 }}>
        <div className="chat-side">
          <div className="chat-side-head"><button className="chat-new" onClick={newSession}>＋ 新对话</button></div>
          <div className="chat-slist">
            {sessions.map(s => (
              <div key={s.session_id} className={`chat-sitem ${s.session_id === sid ? "on" : ""}`} onClick={() => setSid(s.session_id)}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{s.title || "未命名"}</span>
                <span
                  className="chat-del"
                  title="删除对话"
                  onClick={(e) => { e.stopPropagation(); delSession(s); }}
                >✕</span>
              </div>
            ))}
            {!sessions.length && <div className="chat-guard">暂无会话</div>}
          </div>
        </div>
        <div className="chat-main">
          <div className="chat-msgs" ref={boxRef}>
            {msgs.length ? msgs.map(renderMsg) : (
              <div className="chat-guard" style={{ margin: "auto 0" }}>
                <div style={{ fontSize: 34, marginBottom: 8 }}>💬</div>
                选择左侧会话，或点「新对话」开始<br />
                <span style={{ fontSize: 12 }}>试试问："奖学金申请条件？" / "我要请病假 10 月 1 号到 3 号"</span>
              </div>
            )}
          </div>
          {pendingImg && (
            <div style={{ padding: "8px 12px", borderTop: "1px solid var(--line)", background: "var(--surface-2)" }}>
              <span className="att-chip">🖼️ {pendingImg.name} <a onClick={() => setPendingImg(null)} style={{ color: "var(--danger)", cursor: "pointer" }}>✕</a></span>
            </div>
          )}
          <div className="chat-input">
            <input ref={fileRef} type="file" accept="image/*" hidden onChange={e => onPickImg(e.target.files)} />
            <button className="chat-attach" title="上传图片提问" onClick={() => fileRef.current?.click()}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></svg>
            </button>
            <textarea value={input} onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }}
              placeholder="向 Agent 提问，或让它帮你提交请假…" />
            <button className="chat-send" disabled={busy} onClick={ask} title="发送">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
            </button>
          </div>
          <div className="chat-meta">
            memory {memTurns} turns · RAG {retriever?.mode || "vector"}（{retriever?.chunk_count ?? "-"} chunks）
          </div>
        </div>
      </div>
    </>
  );
}
