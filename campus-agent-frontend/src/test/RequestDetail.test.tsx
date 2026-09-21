// 申请单详情：流程标题 / 状态徽标 / 请假字段 / 审批记录
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import RequestDetail from "../components/RequestDetail";

vi.mock("../api/client", () => ({
  api: {
    listCourses: vi.fn().mockResolvedValue({ courses: {} }),
    listVenues: vi.fn().mockResolvedValue({ venues: {} }),
  },
}));

const leaveDetail = {
  request_no: "RQ202609250001",
  process_type: "leave",
  status: "pending_counselor",
  applicant_id: "S10001",
  applicant_name: "张三",
  created_at: 1720000000,
  version: 1,
  payload: { leave_type: "sick", start_date: "2026-09-25", end_date: "2026-09-26", reason: "就医" },
  resolved_nodes: [{ node_id: "counselor", approver_role: "counselor" }],
  current_node_id: "counselor",
  attachments: [],
  doc_check: null,
  records: [],
};

describe("RequestDetail 申请单详情", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("渲染请假类型 / 起止日期 / 事由 / 单号 / 状态", () => {
    render(<RequestDetail detail={leaveDetail} />);
    expect(screen.getByText("请假申请")).toBeInTheDocument();
    expect(screen.getByText("病假")).toBeInTheDocument();
    expect(screen.getByText(/2026-09-25 ~ 2026-09-26/)).toBeInTheDocument();
    expect(screen.getByText("就医")).toBeInTheDocument();
    expect(screen.getByText("RQ202609250001")).toBeInTheDocument();
    expect(screen.getByText("待辅导员审批")).toBeInTheDocument();
  });

  it("无审批记录时显示占位提示", () => {
    render(<RequestDetail detail={leaveDetail} />);
    expect(screen.getByText("暂无审批记录")).toBeInTheDocument();
  });
});
