import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { api } from "../api/client";
import { homePath } from "../constants";

export default function Login() {
  const { user, login, logout } = useAuth();
  const nav = useNavigate();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function doLogin(e?: React.FormEvent) {
    e?.preventDefault();
    if (!u || !p) { setErr("请输入用户名和密码"); return; }
    setBusy(true); setErr("");
    try {
      await login(u.trim(), p);
      const me = await api.me();
      nav(homePath(me.role), { replace: true });
    } catch (e: any) {
      setErr(e.message || "用户名或密码错误");
    } finally { setBusy(false); }
  }

  if (user) {
    return (
      <div className="auth-wrap">
        <div className="auth-card">
          <div className="auth-logo">审</div>
          <div className="auth-title">校园流程自动化 Agent 平台</div>
          <div className="auth-sub">已登录，进入工作台</div>
          <div style={{ marginTop: 8, padding: 14, background: "var(--brand-50)", border: "1px solid var(--brand-100)", borderRadius: 12, color: "var(--brand-700)", fontSize: 13.5, lineHeight: 1.7 }}>
            <b>{user.name}</b><br />
            <span style={{ fontSize: 12, opacity: .85 }}>{user.role} · <span className="mono">{user.user_id}</span></span>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <button className="btn btn-primary" style={{ flex: 1 }} onClick={() => nav(homePath(user.role))}>进入工作台</button>
            <button className="btn btn-ghost" onClick={logout}>退出登录</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-logo">审</div>
        <div className="auth-title">校园流程自动化 Agent 平台</div>
        <div className="auth-sub">多 Agent 校园审批 / 咨询系统</div>
        <form onSubmit={doLogin}>
          <div className="auth-field">
            <label className="auth-label">用户名</label>
            <input className="auth-input" value={u} onChange={e => setU(e.target.value)} placeholder="用户名或学号" autoComplete="username" />
          </div>
          <div className="auth-field">
            <label className="auth-label">密码</label>
            <input className="auth-input" type="password" value={p} onChange={e => setP(e.target.value)} placeholder="密码" autoComplete="current-password" />
          </div>
          {err && <div className="auth-err show">{err}</div>}
          <button className="auth-btn" disabled={busy}>{busy ? "登录中…" : "登 录"}</button>
        </form>
        <div className="auth-foot">
          <span className="hint">管理员 admin / admin123 · 学生 20240001 / 123456</span>
        </div>
      </div>
    </div>
  );
}
