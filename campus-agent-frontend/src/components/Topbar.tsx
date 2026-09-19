import { useNavigate } from "react-router-dom";
import { useAuth } from "../store/auth";
import { ROLE_META } from "../constants";

export default function Topbar({ crumb }: { crumb?: string }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  function doLogout() {
    if (!confirm("退出当前账号？")) return;
    logout();
    nav("/login", { replace: true });
  }
  return (
    <header className="topbar">
      <div className="crumb">工作台 / <b>{crumb || "首页"}</b></div>
      <div className="topbar-spacer"></div>
      <div className="conn">
        <span className="dot live"></span>
        <span>后端已连通</span>
      </div>
      <div className="user-chip" onClick={doLogout} title="点击退出登录">
        <span className="avatar">{user?.name?.[0] || "?"}</span>
        <span className="user-meta">
          <span className="u-name">{user?.name}</span>
          <span className="u-role">{ROLE_META[user?.role || ""] || user?.role} · {user?.user_id}</span>
        </span>
      </div>
    </header>
  );
}
