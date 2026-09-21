"""平台入口：CLI 演示 / 交互式审批 / FastAPI 服务。

用法：
    python -m campus_agent_platform.main demo   # 请假全流程演示
    python -m campus_agent_platform.main api    # FastAPI 服务 (http://127.0.0.1:8000/docs)
    python -m campus_agent_platform.main graph  # LangGraph 编排 submit 流程
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# 允许从项目根直接运行（python -m campus_agent_platform.main）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 加载 .env（在任何配置读取之前）
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("campus-agent")


def demo_leave_flow() -> None:
    """请假动态分级审批演示：10 天请假走 辅导员→学院领导→学校领导→归档。"""
    from campus_agent_platform.app import CampusAgentApp
    from campus_agent_platform.domain import constants as C
    from campus_agent_platform.workflows import rules as R

    app = CampusAgentApp()
    engine = app.engine

    print("=" * 70)
    print("校园审批工作流 Agent 平台 —— 请假动态分级审批演示")
    print("规则：学生请假 -> 辅导员必审；>3 天加学院领导；>7 天加学校领导")
    print("=" * 70)

    # 1. 学生提交 10 天请假（>7 天 → 三级审批：辅导员→学院→学校）
    req = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={
            "leave_type": "sick",
            "start_date": "2026-09-21",
            "end_date": "2026-09-30",
            "reason": "生病就医",
        },
        attachment_urls=["https://campus.example/att/med1.pdf"],
        client_request_no=f"CLI-LEAVE-{int(time.time())}",
    )
    chain = " -> ".join(n["node_id"] for n in req.resolved_nodes)
    print(f"\n[1] 提交申请  request_no={req.request_no}")
    print(f"    请假 10 天 → 动态审批链: {chain}")
    print(f"    当前节点: {req.status} (node={req.current_node_id})")

    # 2. 规则校验（data_specialist 工具）
    tpl = engine.templates.get_latest(C.PROCESS_LEAVE)
    violations = R.validate_rules(
        tpl.validation_rules, req.payload, course_store=engine.courses
    )
    print(f"[2] 规则校验  valid={not violations} violations={violations}")

    # 3. 辅导员 approve → pending_college
    req = engine.advance(
        request_no=req.request_no, approver_id="C30001",
        decision=C.DECISION_APPROVE, comment="情况属实，同意",
    )
    print(f"[3] 辅导员审批 status={req.status} node={req.current_node_id}")

    # 4. 学院领导 approve → pending_university
    req = engine.advance(
        request_no=req.request_no, approver_id="A20001",
        decision=C.DECISION_APPROVE, comment="同意",
    )
    print(f"[4] 学院领导   status={req.status} node={req.current_node_id}")

    # 5. 学校领导 approve → approved
    req = engine.advance(
        request_no=req.request_no, approver_id="U50001",
        decision=C.DECISION_APPROVE, comment="同意，注意返校时间",
    )
    print(f"[5] 学校领导   status={req.status}")

    # 6. 归档（file_specialist 工具）
    req = engine.archive(request_no=req.request_no, actor_id="SYS001")
    print(f"[6] 归档       status={req.status} hash={req.archive_hash[:16]}...")

    # 7. 状态与审计
    view = engine.status_view(req.request_no)
    print("\n[7] 审批链记录:")
    for rec in view["records"]:
        print(f"    - {rec['node_id']:10s} {rec['approver_id']} {rec['decision']:8s} {rec['comment']}")
    print(f"[8] 审计事件数={engine.audit.count()}  待发通知={engine.outbox.count_pending()}")


    # ==================================================================
    # 场地预约演示：教室自动通过；活动室走后勤人工审核
    # ==================================================================
    print("=" * 70)
    print("场地预约演示：教室自动通过；活动室/报告厅/机房 后勤人工审核")
    print("=" * 70)

    v1 = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_VENUE_RESERVATION,
        payload={
            "venue_name": "教室A101", "venue_type": "classroom",
            "start_time": "2026-10-01 14:00", "end_time": "2026-10-01 16:00",
            "activity_theme": "项目组例会", "attendees": 20,
            "contact_person": "S10001", "note": "",
        },
        client_request_no=f"CLI-VENUE-CLASS-{int(time.time())}",
    )
    print(f"[教室] 提交即自动通过 status={v1.status} node={v1.current_node_id}")

    v2 = engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_VENUE_RESERVATION,
        payload={
            "venue_name": "活动室B201", "venue_type": "activity_room",
            "start_time": "2026-10-02 09:00", "end_time": "2026-10-02 11:00",
            "activity_theme": "社团招新", "attendees": 50,
            "contact_person": "S10001", "note": "需音响",
        },
        client_request_no=f"CLI-VENUE-ACT-{int(time.time())}",
    )
    print(f"[活动室] 待后勤审核   status={v2.status} node={v2.current_node_id}")
    v2 = engine.advance(
        request_no=v2.request_no, approver_id="H60001",
        decision=C.DECISION_APPROVE, comment="同意使用",
    )
    print(f"[活动室] 后勤通过     status={v2.status}")
    app.close()


def demo_graph_run() -> None:
    """走 LangGraph 编排：supervisor → data_specialist → communication_specialist → END。"""
    from campus_agent_platform.app import CampusAgentApp

    app = CampusAgentApp()
    result = app.graph.run(
        intent="submit",
        applicant_id="S10002",
        process_type="leave",
        payload={
            "leave_type": "personal",
            "start_date": "2026-09-28",
            "end_date": "2026-09-29",
            "reason": "家中有事",
        },
        client_request_no="CLI-GRAPH-001",
    )
    print("LangGraph 编排结果:", result)
    app.close()


def run_api(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn
    from campus_agent_platform.app import get_app

    get_app()  # 预初始化容器
    uvicorn.run(
        "campus_agent_platform.api.app:app",
        host=host, port=port, reload=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="校园审批工作流 Agent 平台")
    parser.add_argument("cmd", nargs="?", default="demo", choices=["demo", "api", "graph"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.cmd == "demo":
        demo_leave_flow()
    elif args.cmd == "graph":
        demo_graph_run()
    else:
        run_api(args.host, args.port)


if __name__ == "__main__":
    main()
