"""A3 报销流程测试。

链路：submit(reimbursement) → check_reimbursement_limit → advance×2
覆盖：金额合理性、票据完整性、预算科目、限额。
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import ValidationError
from campus_agent_platform.workflows import rules as R


def _reimb_payload(amount=200.0, category="textbook", receipts=None, **overrides):
    half = amount / 2.0
    payload = {
        "category": category,
        "amount": amount,
        "purpose": "购买教材",
        "receipts": receipts if receipts is not None else [
            {"type": "receipt", "amount": half},
            {"type": "invoice", "amount": half},
        ],
    }
    payload.update(overrides)
    return payload


def test_a3_check_reimbursement_limit(engine):
    """check_reimbursement_limit：限额内放行、超限拒绝。"""
    from campus_agent_platform.tools import registry as tools

    ok = tools.call_tool("check_reimbursement_limit", applicant_id="C30001", amount=200.0, category="textbook")
    assert ok["ok"] and ok["data"]["allowed"] is True

    over = tools.call_tool("check_reimbursement_limit", applicant_id="C30001", amount=500.0, category="textbook")
    assert over["ok"] and over["data"]["allowed"] is False


def test_a3_reimbursement_full_flow(app):
    engine = app.engine
    req = engine.submit(
        applicant_id="C30001",
        process_type=C.PROCESS_REIMBURSEMENT,
        payload=_reimb_payload(),
        client_request_no="A3-001",
    )
    assert req.status == "pending_advisor"

    req = engine.advance(request_no=req.request_no, approver_id="T10001", decision=C.DECISION_APPROVE)
    assert req.status == "pending_college"

    req = engine.advance(request_no=req.request_no, approver_id="A20001", decision=C.DECISION_APPROVE)
    assert req.status == C.STATUS_APPROVED

    req = engine.archive(request_no=req.request_no, actor_id="SYS001")
    assert req.status == C.STATUS_ARCHIVED


def test_a3_negative_amount_blocked(app):
    """负数金额 → 拦截（B2 联动）。"""
    engine = app.engine
    with pytest.raises(ValidationError) as exc:
        engine.submit(
            applicant_id="C30001",
            process_type=C.PROCESS_REIMBURSEMENT,
            payload=_reimb_payload(amount=-50.0),
        )
    assert any("负数" in v for v in exc.value.details["violations"])


def test_a3_receipt_completeness_blocked(app):
    """票据缺失（无发票）→ 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError) as exc:
        engine.submit(
            applicant_id="C30001",
            process_type=C.PROCESS_REIMBURSEMENT,
            payload=_reimb_payload(receipts=[{"type": "receipt", "amount": 200.0}]),
        )
    assert any("发票" in v for v in exc.value.details["violations"])


def test_a3_receipt_total_mismatch_blocked(app):
    """票据合计与申请金额不一致 → 拦截。"""
    engine = app.engine
    # 合计 300 != 申请 200
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="C30001",
            process_type=C.PROCESS_REIMBURSEMENT,
            payload=_reimb_payload(
                receipts=[{"type": "receipt", "amount": 150.0}, {"type": "invoice", "amount": 150.0}],
            ),
        )
