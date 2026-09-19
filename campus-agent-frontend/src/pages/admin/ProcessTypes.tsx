import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import { Badge, Field } from "../../components/ui";
import { NODE_META, fmtTime } from "../../constants";

export default function ProcessTypes() {
  const [list, setList] = useState<any[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({
    process_type: "",
    nodes: [{ node_id: "", approver_role: "counselor" }],
    validation_rules: "",
    auto_pass: false,
  });

  async function load() { api.listTemplates().then(setList).catch(e => toast(e.message, "err")); }
  useEffect(() => { load(); }, []);

  function setNode(i: number, k: string, v: string) {
    setForm(f => {
      const nodes = f.nodes.map((n, j) => j === i ? { ...n, [k]: v } : n);
      return { ...f, nodes };
    });
  }

  async function save() {
    if (!form.process_type.trim()) return toast("请填写流程类型 key", "err");
    const nodes = form.nodes.filter(n => n.node_id.trim() && n.approver_role);
    if (!nodes.length) return toast("至少一个节点", "err");
    setBusy(true);
    try {
      await api.registerTemplate({
        process_type: form.process_type.trim(),
        nodes,
        validation_rules: form.validation_rules.split(/[,，\n]/).map(s => s.trim()).filter(Boolean),
        auto_pass_rules: form.auto_pass ? { auto_pass_if_doc_valid: true } : {},
      });
      toast("模板已注册", "ok");
      setShowForm(false);
      setForm({ process_type: "", nodes: [{ node_id: "", approver_role: "counselor" }], validation_rules: "", auto_pass: false });
      load();
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">流程模板</h1>
        <div className="view-sub">版本化审批模板；管理员可注册新流程类型</div>
      </div>

      <div className="toolbar">
        <button className="btn btn-primary btn-sm" onClick={() => setShowForm(v => !v)}>＋ 注册新模板</button>
      </div>

      {showForm && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title"><span className="tick"></span>注册新流程</div>
          <div style={{ marginTop: 14 }}>
            <Field label="流程类型 key" hint="如 leave / venue_reservation / 自定义 key">
              <input className="input" value={form.process_type} onChange={e => setForm({ ...form, process_type: e.target.value })} placeholder="my_process" />
            </Field>
            <label style={{ fontSize: 13, fontWeight: 600, color: "var(--ink-2)", display: "block", margin: "8px 0 6px" }}>审批节点</label>
            {form.nodes.map((n, i) => (
              <div key={i} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                <input className="input" placeholder="node_id" value={n.node_id} onChange={e => setNode(i, "node_id", e.target.value)} style={{ flex: 1 }} />
                <select className="input" value={n.approver_role} onChange={e => setNode(i, "approver_role", e.target.value)} style={{ flex: 1 }}>
                  <option value="counselor">辅导员 counselor</option>
                  <option value="college_admin">学院领导 college_admin</option>
                  <option value="university_leader">学校领导 university_leader</option>
                  <option value="logistics">后勤 logistics</option>
                  <option value="advisor">导师 advisor</option>
                </select>
                {form.nodes.length > 1 && (
                  <button className="btn btn-ghost btn-sm" onClick={() => setForm({ ...form, nodes: form.nodes.filter((_, j) => j !== i) })}>✕</button>
                )}
              </div>
            ))}
            <button className="btn btn-ghost btn-sm" onClick={() => setForm({ ...form, nodes: [...form.nodes, { node_id: "", approver_role: "counselor" }] })}>＋ 加节点</button>
            <Field label="校验规则" hint="逗号分隔，如 date_validity, venue_conflict" >
              <input className="input" value={form.validation_rules} onChange={e => setForm({ ...form, validation_rules: e.target.value })} />
            </Field>
            <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13.5, marginTop: 6 }}>
              <input type="checkbox" checked={form.auto_pass} onChange={e => setForm({ ...form, auto_pass: e.target.checked })} />
              附件通过视觉校验后自动审批通过
            </label>
            <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
              <button className="btn btn-primary" disabled={busy} onClick={save}>注册</button>
              <button className="btn btn-ghost" onClick={() => setShowForm(false)}>取消</button>
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead><tr><th>流程类型</th><th>版本</th><th>审批链</th><th>校验规则</th><th>自动通过</th><th>注册时间</th></tr></thead>
          <tbody>
            {list.map(t => (
              <tr key={t.process_type + t.version}>
                <td style={{ fontWeight: 600 }}>{t.process_type}</td>
                <td className="mono">v{t.version}</td>
                <td>{(t.nodes || []).map((n: any) => NODE_META[n.node_id] || n.node_id).join(" → ")}</td>
                <td className="hint">{(t.validation_rules || []).join(", ") || "-"}</td>
                <td>{t.auto_pass_rules?.auto_pass_if_doc_valid ? <span className="badge b-ok">已开启</span> : <span className="badge b-st">默认关</span>}</td>
                <td className="hint">{fmtTime(t.created_at)}</td>
              </tr>
            ))}
            {!list.length && <tr><td colSpan={6} className="hint" style={{ textAlign: "center" }}>暂无模板</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
