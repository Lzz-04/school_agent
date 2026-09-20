import { useEffect, useState } from "react";
import * as XLSX from "xlsx";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import { Field } from "../../components/ui";
import { fmtTime } from "../../constants";

function fullClass(s: any) {
  if (!s?.class_id) return "";
  return `${s.grade || ""}级${s.major || ""}${s.class_name || ""}`;
}

type Panel = "add" | "bulk" | "class" | null;

export default function Students() {
  const [list, setList] = useState<any[]>([]);
  const [classes, setClasses] = useState<any[]>([]);
  const [counselors, setCounselors] = useState<any[]>([]);
  const [panel, setPanel] = useState<Panel>(null);
  const [form, setForm] = useState({ username: "", name: "", email: "", password: "", class_id: "" });
  const [bulkRows, setBulkRows] = useState<any[]>([]);
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [classForm, setClassForm] = useState({ grade: "2024", major: "软件工程", name: "01班", counselor_id: "" });

  const toggle = (p: Panel) => setPanel(cur => (cur === p ? null : p));

  async function load() {
    Promise.all([api.adminStudents(), api.adminClasses(), api.adminCounselors()]).then(([s, c, co]) => {
      setList(s); setClasses(c); setCounselors(co || []);
    }).catch(e => toast(e.message, "err"));
  }
  useEffect(() => { load(); }, []);

  async function addOne() {
    if (!form.username) return toast("请填写用户名", "err");
    setBusy(true);
    try {
      const r = await api.adminAddStudents({ students: [form] });
      toast(`导入成功 ${r.created?.length || 0} 人`, "ok");
      setForm({ username: "", name: "", email: "", password: "", class_id: "" });
      setPanel(null);
      load();
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }

  function onExcel(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFileName(f.name);
    const reader = new FileReader();
    reader.onload = (ev) => {
      try {
        const wb = XLSX.read(ev.target!.result, { type: "array" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const aoa = XLSX.utils.sheet_to_json<any[]>(ws, { header: 1, defval: "" });
        if (!aoa.length) { toast("Excel 为空", "err"); return; }
        // 第一行当表头，做模糊列名匹配；匹配不到按位置兜底
        const header = aoa[0].map((h: any) => String(h).trim().toLowerCase());
        const findCol = (keys: string[]) => header.findIndex((h: string) => keys.some(k => h.includes(k)));
        let colSid = findCol(["学号", "username", "账号", "登录", "id"]);
        let colName = findCol(["姓名", "name", "名字"]);
        let colEmail = findCol(["邮箱", "email", "邮件"]);
        let colPwd = findCol(["密码", "password", "pwd"]);
        let colCls = findCol(["班级", "class", "班"]);
        const hasHeader = colSid >= 0 || colName >= 0;
        if (!hasHeader) {
          colSid = 0; colName = 1; colEmail = 2; colPwd = 3; colCls = 4;
        }
        const dataRows = hasHeader ? aoa.slice(1) : aoa;
        const mapped = dataRows
          .filter((row: any[]) => row && row.length && row.some((c: any) => String(c).trim()))
          .map((row: any[]) => {
            const username = String(colSid >= 0 ? row[colSid] : row[0]).trim();
            const name = String(colName >= 0 ? row[colName] : row[1] || "").trim();
            const email = String(colEmail >= 0 ? row[colEmail] : row[2] || "").trim();
            const password = String(colPwd >= 0 ? row[colPwd] : row[3] || "").trim();
            const className = String(colCls >= 0 ? row[colCls] : row[4] || "").trim();
            const cls = classes.find(c => `${c.grade}级${c.major}${c.name}` === className);
            return { username, name, email, password, class_id: cls ? cls.class_id : "", class_name: className || "" };
          })
          .filter((r: any) => r.username);
        if (!mapped.length) { toast("未解析到学生，请检查列格式", "err"); return; }
        setBulkRows(mapped);
        toast(`已解析 ${mapped.length} 个学生`, "ok");
      } catch (err: any) {
        toast("解析失败：" + err.message, "err");
      }
    };
    reader.readAsArrayBuffer(f);
  }

  async function addBulk() {
    if (!bulkRows.length) return toast("请先选择 Excel 文件", "err");
    setBusy(true);
    try {
      const r = await api.adminAddStudents({ students: bulkRows });
      toast(`成功 ${r.created?.length || 0}，跳过 ${r.skipped?.length || 0}`, "ok");
      setBulkRows([]); setFileName(""); setPanel(null);
      load();
    } catch (e: any) { toast(e.message, "err"); } finally { setBusy(false); }
  }

  async function disable(uid: string) {
    if (!confirm("禁用学生 " + uid + "？")) return;
    try { await api.adminDeleteStudent(uid); toast("已禁用", "ok"); load(); }
    catch (e: any) { toast(e.message, "err"); }
  }

  async function assignClass(uid: string, classId: string) {
    try { await api.adminAssignStudentClass(uid, classId); toast("已分配班级", "ok"); load(); }
    catch (e: any) { toast(e.message, "err"); }
  }

  async function createClass() {
    if (!classForm.grade || !classForm.major || !classForm.name) return toast("年级/专业/班名必填", "err");
    try {
      await api.adminCreateClass(classForm);
      toast("班级已创建", "ok");
      setClassForm({ grade: "2024", major: "软件工程", name: "01班", counselor_id: "" });
      load();
    } catch (e: any) { toast(e.message, "err"); }
  }

  async function deleteClass(cid: string) {
    if (!confirm("删除该班级？班内学生将被移出班级。")) return;
    try { await api.adminDeleteClass(cid); toast("已删除", "ok"); load(); }
    catch (e: any) { toast(e.message, "err"); }
  }

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">学生管理</h1>
        <div className="view-sub">共 {list.length} 个学生账号；默认初始密码 123456</div>
      </div>

      <div className="toolbar">
        <button className={`btn btn-sm ${panel === "add" ? "btn-primary" : "btn-ghost"}`} onClick={() => toggle("add")}>＋ 单个添加</button>
        <button className={`btn btn-sm ${panel === "bulk" ? "btn-primary" : "btn-ghost"}`} onClick={() => toggle("bulk")}>批量导入</button>
        <button className={`btn btn-sm ${panel === "class" ? "btn-primary" : "btn-ghost"}`} onClick={() => toggle("class")}>班级管理</button>
      </div>

      {panel === "add" && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title"><span className="tick"></span>添加学生</div>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <Field label="学号（登录账号）*"><input className="input" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} /></Field>
            <Field label="姓名"><input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="邮箱"><input className="input" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="初始密码" hint="留空默认 123456"><input className="input" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></Field>
            <Field label="班级">
              <select className="input" value={form.class_id} onChange={e => setForm({ ...form, class_id: e.target.value })}>
                <option value="">未分配</option>
                {classes.map(c => <option key={c.class_id} value={c.class_id}>{c.grade}级{c.major}{c.name}</option>)}
              </select>
            </Field>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button className="btn btn-primary" disabled={busy} onClick={addOne}>保存</button>
            <button className="btn btn-ghost" onClick={() => setPanel(null)}>取消</button>
          </div>
        </div>
      )}

      {panel === "bulk" && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title"><span className="tick"></span>批量导入（Excel：学号 / 姓名 / 邮箱 / 密码可空）</div>
          <input type="file" accept=".xlsx,.xls,.csv" className="input" style={{ marginTop: 10 }} onChange={onExcel} />
          {fileName && <div className="hint" style={{ marginTop: 6 }}>已选：{fileName}（{bulkRows.length} 行）</div>}
          {bulkRows.length > 0 && (
            <table className="table" style={{ marginTop: 10 }}>
              <thead><tr><th>学号</th><th>姓名</th><th>邮箱</th><th>班级</th></tr></thead>
              <tbody>
                {bulkRows.slice(0, 10).map((r, i) => (
                  <tr key={i}><td>{r.username}</td><td>{r.name}</td><td>{r.email}</td><td>{r.class_name || (r.class_id ? "已匹配" : "未匹配")}</td></tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button className="btn btn-primary" disabled={busy || !bulkRows.length} onClick={addBulk}>导入</button>
            <button className="btn btn-ghost" onClick={() => { setBulkRows([]); setFileName(""); setPanel(null); }}>取消</button>
          </div>
        </div>
      )}

      {panel === "class" && (
        <div className="card" style={{ marginBottom: 14 }}>
          <div className="card-title"><span className="tick"></span>班级管理</div>
          <div className="form-grid" style={{ marginTop: 12 }}>
            <Field label="年级（如2024）*"><input className="input" value={classForm.grade} onChange={e => setClassForm({ ...classForm, grade: e.target.value })} /></Field>
            <Field label="专业（如软件工程）*"><input className="input" value={classForm.major} onChange={e => setClassForm({ ...classForm, major: e.target.value })} /></Field>
            <Field label="班名（如01班）*"><input className="input" value={classForm.name} onChange={e => setClassForm({ ...classForm, name: e.target.value })} /></Field>
            <Field label="辅导员">
              <select className="input" value={classForm.counselor_id} onChange={e => setClassForm({ ...classForm, counselor_id: e.target.value })}>
                <option value="">不分配</option>
                {counselors.map(c => <option key={c.user_id} value={c.user_id}>{c.name || c.username}（{c.user_id}）</option>)}
              </select>
            </Field>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <button className="btn btn-primary" onClick={createClass}>新建班级</button>
            <button className="btn btn-ghost" onClick={() => setPanel(null)}>关闭</button>
          </div>
          <table className="table" style={{ marginTop: 12 }}>
            <thead><tr><th>班级</th><th>辅导员</th><th>学生数</th><th></th></tr></thead>
            <tbody>
              {classes.map(c => (
                <tr key={c.class_id}>
                  <td>{c.grade}级{c.major}{c.name}</td>
                  <td>{c.counselor_name || "未分配"}</td>
                  <td>{c.student_count}</td>
                  <td><button className="btn btn-ghost btn-sm" onClick={() => deleteClass(c.class_id)}>删除</button></td>
                </tr>
              ))}
              {!classes.length && <tr><td colSpan={4} className="hint" style={{ textAlign: "center" }}>暂无班级</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead><tr><th>学号</th><th>姓名</th><th>班级</th><th>邮箱</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
          <tbody>
            {list.map(s => (
              <tr key={s.user_id}>
                <td className="mono">{s.username}</td>
                <td>{s.name}</td>
                <td>
                  <select className="input" style={{ minWidth: 180 }} value={s.class_id || ""}
                    onChange={e => assignClass(s.user_id, e.target.value)}>
                    <option value="">未分配</option>
                    {classes.map(c => <option key={c.class_id} value={c.class_id}>{c.grade}级{c.major}{c.name}</option>)}
                  </select>
                </td>
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
