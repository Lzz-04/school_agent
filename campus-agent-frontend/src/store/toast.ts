import { create } from "zustand";

interface Toast { id: number; msg: string; kind: "info" | "ok" | "err" }
interface ToastState {
  toasts: Toast[];
  push: (msg: string, kind?: Toast["kind"]) => void;
  remove: (id: number) => void;
}

let seq = 1;
export const useToast = create<ToastState>((set, get) => ({
  toasts: [],
  push(msg, kind = "info") {
    const id = seq++;
    set({ toasts: [...get().toasts, { id, msg, kind }] });
    setTimeout(() => get().remove(id), 3200);
  },
  remove(id) { set({ toasts: get().toasts.filter(t => t.id !== id) }); },
}));

export function toast(msg: string, kind?: "info" | "ok" | "err") {
  useToast.getState().push(msg, kind);
}
