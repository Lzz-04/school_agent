"""B2 异常输入测试。

覆盖：请假时间早于今天、负数金额、特殊字符注入。
"""

from __future__ import annotations

import pytest

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import ValidationError

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


def test_b2_leave_date_in_past(app):
    """请假时间早于今天 → 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_LEAVE,
            payload={"leave_type": "sick", "start_date": "2020-01-01",
                     "end_date": "2020-01-02", "reason": "x"},
        )


def test_b2_leave_end_before_start(app):
    """结束早于开始 → 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_LEAVE,
            payload={"leave_type": "sick", "start_date": _D(1),
                     "end_date": _D(0), "reason": "x"},
        )


def test_b2_invalid_date_format(app):
    """日期格式非法 → 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_LEAVE,
            payload={"leave_type": "sick", "start_date": "not-a-date",
                     "end_date": _D(1), "reason": "x"},
        )


def test_b2_negative_amount(app):
    """负数金额 → 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="C30001",
            process_type=C.PROCESS_REIMBURSEMENT,
            payload={"category": "textbook", "amount": -10.0, "receipts": [
                {"type": "receipt", "amount": -10.0}, {"type": "invoice", "amount": -10.0}]},
        )


def test_b2_sql_injection_blocked(app):
    """特殊字符 / SQL 注入 → 拦截（sanitize_payload）。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_LEAVE,
            payload={"leave_type": "sick; DROP TABLE approval_requests; --",
                     "start_date": _D(0), "end_date": _D(1), "reason": "x"},
        )


def test_b2_special_chars_blocked(app):
    """<> 引号等非法字符 → 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_LEAVE,
            payload={"leave_type": "sick", "start_date": _D(0),
                     "end_date": _D(1), "reason": "<script>alert(1)</script>"},
        )


def test_b2_empty_course_list(app):
    """选课列表为空 → 拦截。"""
    engine = app.engine
    with pytest.raises(ValidationError):
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_COURSE_SELECTION,
            payload={"course_ids": [], "major": "CS", "passed_courses": []},
        )
