import { create } from "zustand";
import { api, setToken } from "../api/client";

export interface AuthUser {
  user_id: string;
  role: string;
  name: string;
}

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => void;
  bootstrap: () => Promise<void>;
}

function loadCached(): AuthUser | null {
  try { return JSON.parse(localStorage.getItem("campus_auth_user") || "null"); } catch { return null; }
}

export const useAuth = create<AuthState>((set, get) => ({
  user: loadCached(),
  loading: true,
  async login(u, p) {
    const r = await api.login({ username: u, password: p });
    setToken(r.token);
    const user: AuthUser = { user_id: r.user_id, role: r.role, name: r.name };
    localStorage.setItem("campus_auth_user", JSON.stringify(user));
    set({ user });
  },
  logout() {
    setToken(null);
    localStorage.removeItem("campus_auth_user");
    set({ user: null });
  },
  async bootstrap() {
    const t = localStorage.getItem("campus_token");
    if (!t) { set({ loading: false }); return; }
    try {
      const me = await api.me();
      const user: AuthUser = { user_id: me.user_id, role: me.role, name: me.name };
      localStorage.setItem("campus_auth_user", JSON.stringify(user));
      set({ user, loading: false });
    } catch {
      get().logout();
      set({ loading: false });
    }
  },
}));
