import { useEffect, useState } from "react";
import { useAuth } from "../store/auth";
import { api } from "../api/client";
import { Badge, Empty } from "../components/ui";
import RequestDetail from "../components/RequestDetail";
import { PROCESS_META, fmtTime } from "../constants";

export default function MyRequests() {
  const { user } = useAuth();
  const [list, setList] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  async function load() {
    if (!user) return;
    setLoading(true);
    try {
      const r = await api.listRequests(user.user_id);
      setList(r || []);
      if (!selected && r?.length) setSelected(r[0].request_no);
    } finally { setLoading(false); }
  }
  useEffect(() => { load(); }, [user?.user_id]);
  useEffect(() => {
    if (selected) api.getRequest(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected]);

  return (
    <>
      <div className="view-head">
        <h1 className="view-title">我的申请</h1>
        <div className="view-sub">查看你提交的所有申请与审批进度</div>
      </div>
      <div className="chat-layout" style={{ height: "calc(100vh - 150px)", minHeight: 520 }}>
        <div className="chat-side">
          <div className="chat-side-head">
            <button className="chat-new" onClick={() => (window.location.hash = "#/apply")}>＋ 发起新申请</button>
          </div>
          <div className="chat-slist">
            {loading && <div className="chat-guard">加载中…</div>}
            {!loading && !list.length && <div className="chat-guard">还没有申请记录</div>}
            {list.map((r: any) => (
              <div key={r.request_no} className={`req-row ${r.request_no === selected ? "on" : ""}`} onClick={() => setSelected(r.request_no)}>
                <div className="rr-main">
                  <div className="rr-title">{PROCESS_META[r.process_type]?.name || r.process_type}</div>
                  <div className="rr-sub">{r.request_no} · {fmtTime(r.created_at)}</div>
                </div>
                <Badge status={r.status} />
              </div>
            ))}
          </div>
        </div>
        <div className="chat-main">
          {!detail ? <Empty icon="📋" text="从左侧选择一单查看详情" /> : <RequestDetail detail={detail} />}
        </div>
      </div>
    </>
  );
}
