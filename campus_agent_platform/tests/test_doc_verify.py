"""附件视觉校验 + 自动通过流程测试。

通过 monkeypatch doc_verifier.verify_attachments 模拟 VL 判断结果，
避免在单元测试里真调模型。
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C


@pytest.fixture()
def leave_tpl_auto_pass(app):
    """把 leave 模板升级一版，开启 auto_pass_if_doc_valid。"""
    app.engine.register_template(
        process_type=C.PROCESS_LEAVE,
        nodes=[{"node_id": "counselor", "approver_role": C.ROLE_COUNSELOR}],
        validation_rules=["date_validity"],
        actor_id="SYS001",
        auto_pass_rules={"auto_pass_if_doc_valid": True},
    )
    return app


def _leave_payload():
    return {"start_date": "2026-10-01", "end_date": "2026-10-02", "reason": "病假"}


def test_attachment_valid_auto_approve(leave_tpl_auto_pass, monkeypatch):
    """附件识别为真实 → 直接 approved，不走辅导员。"""
    from campus_agent_platform.tools import doc_verifier
    monkeypatch.setattr(doc_verifier, "verify_attachments",
                        lambda pt, atts: {"authentic": True, "reason": "清晰病假条", "checks": []})

    req = leave_tpl_auto_pass.engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=_leave_payload(),
        attachments=[{"url": "/uploads/x.png", "name": "病假条.png", "type": "image"}],
        client_request_no="DOC-OK",
    )
    assert req.status == C.STATUS_APPROVED
    assert req.current_node_id is None
    assert req.doc_check["authentic"] is True


def test_attachment_suspicious_still_manual(leave_tpl_auto_pass, monkeypatch):
    """附件识别为可疑 → 仍走人工辅导员审批。"""
    from campus_agent_platform.tools import doc_verifier
    monkeypatch.setattr(doc_verifier, "verify_attachments",
                        lambda pt, atts: {"authentic": False, "reason": "表情包", "checks": []})

    req = leave_tpl_auto_pass.engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=_leave_payload(),
        attachments=[{"url": "/uploads/x.png", "name": "meme.png", "type": "image"}],
        client_request_no="DOC-BAD",
    )
    assert req.status == "pending_counselor"
    assert req.doc_check["authentic"] is False


def test_no_attachment_manual_review(leave_tpl_auto_pass, monkeypatch):
    """无附件 → 走人工，doc_check 记录无附件。"""
    from campus_agent_platform.tools import doc_verifier
    called = {}
    def fake(pt, atts):
        called["n"] = len(atts)
        return {"authentic": None, "reason": "无附件", "checks": []}
    monkeypatch.setattr(doc_verifier, "verify_attachments", fake)

    req = leave_tpl_auto_pass.engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload=_leave_payload(),
        client_request_no="DOC-NONE",
    )
    assert req.status == "pending_counselor"
    assert req.doc_check.get("authentic") is None


def test_default_no_auto_pass(app, monkeypatch):
    """模板没开开关（默认）→ 即使附件真实也走人工。"""
    from campus_agent_platform.tools import doc_verifier
    monkeypatch.setattr(doc_verifier, "verify_attachments",
                        lambda pt, atts: {"authentic": True, "reason": "ok", "checks": []})

    req = app.engine.submit(
        applicant_id="S10001",
        process_type=C.PROCESS_LEAVE,
        payload={"start_date": "2026-10-01", "end_date": "2026-10-02", "reason": "病假"},
        attachments=[{"url": "/uploads/x.png", "type": "image"}],
        client_request_no="DOC-DEFAULT",
    )
    # 2 天请假本就单节点；模板没开 auto_pass → 仍 pending
    assert req.status == "pending_counselor"
