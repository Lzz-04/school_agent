import { useState } from "react";
import { useAuth } from "../store/auth";
import { api } from "../api/client";
import { toast } from "../store/toast";
import { ROLE_META } from "../constants";

export default function Profile() {
  const { user } = useAuth();
  const [oldP, setOldP] = useState("");
  const [newP, setNewP] = useState("");
  const [newP2, setNewP2] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (newP.length < 6) return toast("新密码至少 6 位", "err");
    if (newP !== newP2) return toast("两次新密码不一致", "err");
    setBusy(true);
    try {
      await api.changePassword({ old_password: oldP, new_password: newP });
      toast("密码已修改", "ok");
      setOldP(""); setNewP(""); setNewP2("");
    } catch (e: any) {
      toast(e.message || "修改失败", "err");
    } finally { setBusy(false); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">个人中心</h1>
        <div className="view-sub">查看账户信息与修改密码</div>
      </div>
      <div style={{ maxWidth: 560 }}>
        <div className="card">
          <div className="card-title"><span className="tick"></span>账户信息</div>
          <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 14 }}>
            <div className="avatar" style={{ width: 52, height: 52, fontSize: 22 }}>{user?.name?.[0] || "?"}</div>
            <div>
              <div style={{ fontSize: 17, fontWeight: 700 }}>{user?.name}</div>
              <div className="hint" style={{ marginTop: 3 }}>{ROLE_META[user?.role || ""] || user?.role} · <span className="mono">{user?.user_id}</span></div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title"><span className="tick"></span>修改密码</div>
          <form onSubmit={save} style={{ marginTop: 14 }}>
            <div className="cp-row"><label>原密码</label><input className="auth-input" type="password" value={oldP} onChange={e => setOldP(e.target.value)} /></div>
            <div className="cp-row"><label>新密码（≥6 位）</label><input className="auth-input" type="password" value={newP} onChange={e => setNewP(e.target.value)} /></div>
            <div className="cp-row"><label>确认新密码</label><input className="auth-input" type="password" value={newP2} onChange={e => setNewP2(e.target.value)} /></div>
            <div className="cp-actions">
              <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? "提交中…" : "确认修改"}</button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
