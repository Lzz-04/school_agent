"""规则校验类工具：validate_request_rules / check_reimbursement_limit / query_courses。

- validate_request_rules 按模板规则校验申请（写审计）
- check_reimbursement_limit / query_courses 为只读规则源
"""

from __future__ import annotations

from typing import Any

from ..domain import constants as C
from ..domain.models import AuditEvent
from ..workflows import rules as R
from ..workflows.engine import WorkflowEngine
from .registry import register_tool


def bind_validation_tools(engine: WorkflowEngine) -> None:
    def validate_request_rules(request_no: str) -> dict[str, Any]:
        req = engine.requests.get(request_no)
        tpl = engine.templates.get_latest(req.process_type)
        violations = R.validate_rules(
            tpl.validation_rules, req.payload, course_store=engine.courses
        )
        engine.audit.append(
            AuditEvent(
                event_type=C.EVENT_REQUEST_VALIDATED,
                entity_id=request_no,
                actor_id=C.ROLE_SYSTEM,
                detail={"violations": violations, "rules": tpl.validation_rules},
            )
        )
        engine.db.commit()
        return {"request_no": request_no, "valid": not violations, "violations": violations}

    def check_reimbursement_limit(
        applicant_id: str, amount: float, category: str
    ) -> dict[str, Any]:
        limit = R.REIMBURSEMENT_LIMITS.get(category, R.REIMBURSEMENT_LIMITS["other"])
        allowed = 0 <= amount <= limit
        return {
            "applicant_id": applicant_id,
            "category": category,
            "amount": amount,
            "limit": limit,
            "allowed": allowed,
            "message": "OK" if allowed else f"超出限额 {limit}",
        }

    def query_courses(course_ids: list[str], semester: str = "") -> dict[str, Any]:
        out = {}
        for cid in course_ids:
            course = R.COURSE_CATALOG.get(cid)
            if course is None:
                out[cid] = {"exists": False}
                continue
            out[cid] = {
                "exists": True,
                "name": course["name"],
                "quota": course["quota"],
                "enrolled": engine.courses.enrolled(cid),
                "available": engine.courses.remaining(cid) > 0,
                "prerequisite": course["prerequisite"],
                "schedule": course["schedule"],
                "credit": course["credit"],
                "major": course["major"],
            }
        return {"semester": semester, "courses": out}

    register_tool("validate_request_rules", validate_request_rules)
    register_tool("check_reimbursement_limit", check_reimbursement_limit)
    register_tool("query_courses", query_courses)
