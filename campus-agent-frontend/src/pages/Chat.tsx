import { useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../api/client";
import { useAuth } from "../store/auth";
import { toast } from "../store/toast";
import { CourseFormCard } from "../components/chat/CourseFormCard";
import { LeaveFormCard } from "../components/chat/LeaveFormCard";
import { ReimbursementFormCard } from "../components/chat/ReimbursementFormCard";
import { VenueCatalogCard } from "../components/chat/VenueCatalogCard";
import { VenueFormCard } from "../components/chat/VenueFormCard";
import type { Attachment, FormDraft } from "../components/chat/formTypes";

interface ChatSession {
  session_id: string;
  title?: string;
}

interface ChatMessage {
  id?: string;
  role: string;
  content: string;
  created_at?: string;
  form_draft?: FormDraft | null;
}

interface Msg extends ChatMessage {
  form_state?: "editing" | "submitted" | "cancelled";
  att?: string;
  _pendingAtt?: Attachment | null;
}

interface ChatAskResult {
  answer: string;
  citations?: { title: string; category: string }[];
  memory_turns?: number;
  form_draft?: FormDraft | null;
}

interface RetrieverInfo {
  mode?: string;
  chunk_count?: number;
}

/** 不同角色登录时，对话页的引导文案（placeholder / 副标题 / 空状态示例） */
const CHAT_HINTS: Record<string, { placeholder: string; subtitle: string; example: string }> = {
  student: {
    placeholder: "向 Agent 提问，或让它帮你提交请假/选课/场地预约…",
    subtitle: "RAG 制度问答 + 短期记忆；说出需求会弹出预填表单，核对后提交",
    example: "试试问：\"我要选课\" / \"帮我选 程序设计基础 和 艺术鉴赏\" / \"明天到后天请假\"",
  },
  counselor: {
    placeholder: "向 Agent 提问，或让它帮你审核待办请假…",
    subtitle: "RAG 制度问答 + 短期记忆；说「自动审核待办」可批量处理本班请假申请",
    example: "试试问：\"帮我自动审核一下待办请假单\"",
  },
  admin: {
    placeholder: "向 Agent 提问，或让它帮你导入学生…",
    subtitle: "RAG 制度问答 + 短期记忆；直接说出学生名单即可批量导入",
    example: "试试问：\"帮我导入几个学生：20240002 李四，2024级软件工程01班\"",
  },
};
const DEFAULT_HINT = {
  placeholder: "向 Agent 提问，或咨询审批与制度问题…",
  subtitle: "RAG 制度问答 + 短期记忆",
  example: "试试问：\"请假审批流程是什么？\"",
};

export default function Chat() {
  const { user } = useAuth();
  const hint = CHAT_HINTS[user?.role || ""] || DEFAULT_HINT;
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sid, setSid] = useState<string>("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [memTurns, setMemTurns] = useState(0);
  const [retriever, setRetriever] = useState<RetrieverInfo | null>(null);
  const [pendingImg, setPendingImg] = useState<Attachment | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const skipLoadRef = useRef(false);
  const pendingBySid = useRef<Map<string, Msg[]>>(new Map());
  const sidRef = useRef(sid);
  useEffect(() => { sidRef.current = sid; }, [sid]);
  const msgsRef = useRef<Msg[]>([]);
  useEffect(() => { msgsRef.current = msgs; }, [msgs]);

  async function loadSessions() {
    try {
      const s = await api.chatSessions();
      setSessions(s);
      if (!sidRef.current && s.length) setSid(s[0].session_id);
    } catch { /* ignore */ }
  }
  useEffect(() => {
    loadSessions();
    api.chatRetrieverInfo().then(setRetriever).catch(() => {});
  }, []);
  useEffect(() => {
    if (!sid) return;
    if (skipLoadRef.current) { skipLoadRef.current = false; return; }
    const pending = pendingBySid.current.get(sid);
    if (pending) {
      setMsgs(pending);
      pendingBySid.current.delete(sid); // 看过即清，之后以数据库历史为准
      return;
    }
    api.chatMessages(sid).then((h: ChatMessage[]) => setMsgs(h.map((m) => ({
      ...m,
      form_draft: m.form_draft && Object.keys(m.form_draft).length ? m.form_draft : null,
    })))).catch(() => setMsgs([]));
  }, [sid]);
  useEffect(() => { boxRef.current?.scrollTo({ top: boxRef.current.scrollHeight }); }, [msgs, busy]);

  async function newSession() {
    try {
      const s = await api.chatCreateSession({ title: "新对话 " + new Date().toLocaleTimeString() });
      setSid(s.session_id); setMsgs([]); loadSessions();
    } catch (e: any) { toast(e.message, "err"); }
  }

  async function delSession(s: ChatSession) {
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
        currentSid = s.session_id;
        skipLoadRef.current = true;
        sidRef.current = currentSid; // 手动同步，避免 loadSessions 闭包中旧 sid 触发自动切换
        setSid(currentSid);
        loadSessions();
      } catch (e: any) { toast(e.message, "err"); return; }
    }
    const attachments = pendingImg ? [pendingImg] : [];
    const attRef = pendingImg;
    const optimistic: Msg[] = [
      ...msgsRef.current,
      { role: "user", content: q || "[图片]", ...(pendingImg ? { att: pendingImg.url } : {}) },
      { role: "assistant", content: "思考中…" },
    ];
    pendingBySid.current.set(currentSid, optimistic);
    setMsgs(optimistic);
    setInput(""); setPendingImg(null); setBusy(true);
    try {
      const r: ChatAskResult = await api.chatAsk(currentSid, q, attachments);
      setMemTurns(r.memory_turns || 0);
      const cite = (r.citations || []).map((c) => `<span class="cite-chip">${c.title} · ${c.category}</span>`).join("");
      const draft: FormDraft | null = r.form_draft && Object.keys(r.form_draft).length ? r.form_draft : null;
      const updated: Msg[] = [
        ...optimistic.slice(0, -1),
        {
          role: "assistant",
          content: r.answer + (cite ? "\n\n__CITE__" + cite : ""),
          form_draft: draft,
          _pendingAtt: attRef,
        },
      ];
      pendingBySid.current.set(currentSid, updated);
      if (sidRef.current === currentSid) setMsgs(updated);
    } catch (e: any) {
      const updated: Msg[] = [
        ...optimistic.slice(0, -1),
        { role: "assistant", content: "请求失败：" + e.message },
      ];
      pendingBySid.current.set(currentSid, updated);
      if (sidRef.current === currentSid) setMsgs(updated);
    } finally { setBusy(false); }
  }

  function renderMsg(m: Msg, i: number) {
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
          {!isUser && m.form_draft && user && (
            (() => {
              const p = m.form_draft.process_type;
              if (p === "leave") return <LeaveFormCard draft={m.form_draft} user={user} messageId={m.id} defaultAttachment={m._pendingAtt || null} />;
              if (p === "course_selection") return <CourseFormCard draft={m.form_draft} user={user} messageId={m.id} />;
              if (p === "reimbursement") return <ReimbursementFormCard draft={m.form_draft} user={user} messageId={m.id} />;
              if (p === "venue_reservation") return <VenueFormCard draft={m.form_draft} user={user} messageId={m.id} />;
              if (p === "venue_catalog") return <VenueCatalogCard user={user} messageId={m.id} />;
              return null;
            })()
          )}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">智能对话</h1>
        <div className="view-sub">{hint.subtitle}</div>
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
                <span style={{ fontSize: 12 }}>{hint.example}</span>
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
            <textarea value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }}
              placeholder={hint.placeholder} />
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
