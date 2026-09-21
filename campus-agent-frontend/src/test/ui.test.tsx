// 共享 UI 组件：状态徽标 / 审批步骤条 / 附件校验三态
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge, DocCheck, FlowSteps } from "../components/ui";

describe("Badge 状态徽标", () => {
  it("approved 显示 已通过", () => {
    render(<Badge status="approved" />);
    expect(screen.getByText("已通过")).toBeInTheDocument();
  });
  it("rejected 显示 已驳回", () => {
    render(<Badge status="rejected" />);
    expect(screen.getByText("已驳回")).toBeInTheDocument();
  });
  it("pending_counselor 动态映射为 待辅导员审批", () => {
    render(<Badge status="pending_counselor" />);
    expect(screen.getByText("待辅导员审批")).toBeInTheDocument();
  });
  it("未知状态原样展示", () => {
    render(<Badge status="weird" />);
    expect(screen.getByText("weird")).toBeInTheDocument();
  });
});

describe("FlowSteps 审批步骤条", () => {
  it("进行中：已过节点标记 passed，当前节点标记 current", () => {
    const { container } = render(
      <FlowSteps nodes={["counselor", "college"]} status="pending_college" currentNode="college" />
    );
    expect(container.querySelectorAll(".flow-node.passed").length).toBe(1);
    expect(container.querySelectorAll(".flow-node.current").length).toBe(1);
    expect(screen.getByText("辅导员")).toBeInTheDocument();
    expect(screen.getByText("学院领导")).toBeInTheDocument();
  });
  it("终态 approved：全部节点 passed", () => {
    const { container } = render(
      <FlowSteps nodes={["counselor", "college"]} status="approved" currentNode={null} />
    );
    expect(container.querySelectorAll(".flow-node.passed").length).toBe(2);
  });
  it("rejected：驳回节点标记 rejected", () => {
    const { container } = render(
      <FlowSteps nodes={["counselor", "college"]} status="rejected" currentNode="college" />
    );
    expect(container.querySelectorAll(".flow-node.rejected").length).toBe(1);
  });
});

describe("DocCheck 附件视觉校验三态", () => {
  it("未执行（无结果）", () => {
    render(<DocCheck docCheck={null} />);
    expect(screen.getByText(/附件校验：未执行/)).toBeInTheDocument();
  });
  it("通过：显示置信度", () => {
    render(<DocCheck docCheck={{ authentic: true, reason: "证明材料与申请类型匹配", confidence: 0.95 }} />);
    expect(screen.getByText(/附件通过视觉校验/)).toBeInTheDocument();
    expect(screen.getByText(/95%/)).toBeInTheDocument();
  });
  it("疑似不实", () => {
    render(<DocCheck docCheck={{ authentic: false, reason: "图片为演示样例", confidence: 0.98 }} />);
    expect(screen.getByText(/附件疑似不实/)).toBeInTheDocument();
    expect(screen.getByText(/演示样例/)).toBeInTheDocument();
  });
});
