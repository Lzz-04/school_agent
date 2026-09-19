import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import { Field } from "../../components/ui";
import { fmtTime } from "../../constants";

export default function Students() {
  const [list, setList] = useState<any[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ username: "", name: "", email: "", password: "" });
  const [bulk, setBulk] = useState("");
  const [showBulk, setShowBulk] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() { api.adminStudents().then(setList).catch(e => toast(e.message, "err")); }
  useEffect(() => { load(); }, []);

  async function addOne() {
    if (!form.username) return toast("请填写用户名", "err");
    setBusy(true);
    try {
      const r = await api.adminAddStudents({ students: [form] });
      toast(`导入成功 ${r.created?.length || 0} 人`, "ok");
      setForm({ username: "", name: "", email: "", password: "" });
      setShowAdd(false);
      load();
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }

  async function addBulk() {
    const lines = bulk.split("\n").map(l => l.trim()).filter(Boolean);
    const students = lines.map(l => {
      const [username, name, email, password] = l.split(/[,，\t]/).map(s => s?.trim());
      return { username, name: name || "", email: email || "", password: password || "" };
    }).filter(s => s.username);
    if (!students.length) return toast("请填写至少一行：username,姓名,邮箱", "err");
    setBusy(true);
    try {
      const r = await api.adminAddStudents({ students });
      toast(`成功 ${r.created?.length || 0}，跳过 ${r.skipped?.length || 0}`, "ok");
      if (r.skipped?.length) console.warn("skipped", r.skipped);
      setBulk(""); setShowBulk(false);
      load();
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }

  async function disable(uid: string) {
    if (!confirm("禁用学生 " + uid + "？")) return;
    try { await api.adminDeleteStudent(uid); toast("已禁用", "ok"); load(); }
    catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">学生管理</h1>
        <div className="view-sub">共 {list.length} 个学生账号；默认初始密码 123456</div>
      </div>

      <div className="toolbar">
        <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(v => !v)}>＋ 单个添加</button>
        <button className="btn btn-ghost btn-sm" onClick={() => setShowBulk(v => !v)}>批量导入</button>
      </div>

      {showAdd && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title"><span className="tick"></span>添加学生</div>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <Field label="用户名（学号）*"><input className="input" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></Field>
            <Field label="姓名"><input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="邮箱"><input className="input" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="初始密码" hint="留空默认 123456"><input className="input" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></Field>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={addOne}>保存</button>
            <button className="btn btn-ghost" onClick={() => setShowAdd(false)}>取消</button>
          </div>
        </div>
      )}

      {showBulk && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title"><span className="tick"></span>批量导入（每行一个：username,姓名,邮箱,密码可空）</div>
          <textarea className="input" rows={5} style={{ marginTop: 10 }}
            placeholder={"S2024001,张三,zhang@xx.edu.cn\nS2024002,李四,li@xx.edu.cn"}
            value={bulk} onChange={e => setBulk(e.target.value)} />
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={addBulk}>导入</button>
            <button className="btn btn-ghost" onClick={() => setShowBulk(false)}>取消</button>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead><tr><th>学号</th><th>用户名</th><th>姓名</th><th>邮箱</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
          <tbody>
            {list.map(s => (
              <tr key={s.user_id}>
                <td className="mono">{s.user_id}</td>
                <td>{s.username}</td>
                <td>{s.name}</td>
                <td>{s.email || "-"}</td>
                <td><span className={`badge ${s.status === "active" ? "b-ok" : "b-st"}`}>{s.status}</span></td>
                <td className="hint">{fmtTime(s.created_at)}</td>
                <td><button className="btn btn-ghost btn-sm" onClick={() => disable(s.user_id)}>禁用</button></td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan={7} className="hint" style={{ textAlign: "center" }}>暂无学生</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
