// 路由守卫：未登录跳登录页；角色无权访问路径时重定向回角色首页
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { useAuth } from "../store/auth";

// 页面副作用里的 API 调用统一 mock（守卫测试只关心跳转，不关心业务数据）
vi.mock("../api/client", () => {
  const handler = { get: () => vi.fn().mockResolvedValue({}) };
  return { api: new Proxy({}, handler), setToken: vi.fn(), setUnauthorizedHandler: vi.fn() };
});

function setAuth(user: unknown, loading = false) {
  useAuth.setState({ user, loading } as never);
}

describe("App 路由守卫", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("未登录访问 /apply → 重定向到 /login（显示登录表单）", () => {
    setAuth(null);
    render(
      <MemoryRouter initialEntries={["/apply"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getByPlaceholderText("用户名或学号")).toBeInTheDocument();
  });

  it("已登录学生访问 /admin/dashboard → 无权限，重定向到学生首页 /chat", () => {
    setAuth({ user_id: "S10001", role: "student", name: "张三" });
    render(
      <MemoryRouter initialEntries={["/admin/dashboard"]}>
        <App />
      </MemoryRouter>
    );
    // 管理页内容不应出现；Sidebar 学生导航（智能对话）应出现
    expect(screen.queryByText("学生管理")).not.toBeInTheDocument();
    expect(screen.getAllByText("智能对话").length).toBeGreaterThan(0);
  });

  it("辅导员访问 /counselor → 放行（面包屑显示 请假审核）", () => {
    setAuth({ user_id: "C30001", role: "counselor", name: "陈老师" });
    render(
      <MemoryRouter initialEntries={["/counselor"]}>
        <App />
      </MemoryRouter>
    );
    expect(screen.getAllByText("请假审核").length).toBeGreaterThan(0);
  });
});
