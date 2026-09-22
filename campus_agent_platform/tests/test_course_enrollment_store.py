"""G2：选课占课入库（CourseEnrollmentStore）回归测试。

验证契约：
1. 种子：目录课程幂等建行，初始在册基线不覆盖已有数据；
2. try_enroll 原子：enrolled < quota 才 +1，满员/未知课程返回 False；
3. release 下限 0：重复退选不把名额扣成负数；
4. 并发占课不超卖：N 线程抢 quota=2 的课程，恰好 2 个成功；
5. 校验/占课/释放全链路以 DB 为权威来源（引擎 submit 满员拦截）。
"""

from __future__ import annotations

import threading

from campus_agent_platform.domain import constants as C
from campus_agent_platform.domain.errors import ValidationError
from campus_agent_platform.workflows import rules as R

from datetime import date, timedelta


def _D(n: int) -> str:
    """相对今天的日期（今天+n 天），避免测试因日期过期而腐烂"""
    return (date.today() + timedelta(days=n)).isoformat()


def test_store_seeded_from_catalog_and_initial(app):
    """种子：全部课程建行，初始在册基线生效；重复构造不覆盖。"""
    store = app.engine.courses
    assert store.enrolled("CS101") == 1   # 初始基线
    assert store.enrolled("MATH101") == 2
    assert store.enrolled("ART101") == 0
    assert store.remaining("CS101") == 1  # quota=2 - enrolled=1
    assert store.is_full("MATH101") is False  # quota=5 - 2 = 3


def test_try_enroll_atomic_up_to_quota(app):
    """占课原子：quota=2 的课程第 3 次占课失败。"""
    store = app.engine.courses
    store.set_enrolled("CS202", 0)  # quota=3
    assert store.try_enroll("CS202") is True
    assert store.try_enroll("CS202") is True
    assert store.try_enroll("CS202") is True
    assert store.try_enroll("CS202") is False  # 3/3 满员
    assert store.enrolled("CS202") == 3
    # 未知课程：不报错，返回 False
    assert store.try_enroll("NO-SUCH") is False


def test_release_floor_zero(app):
    """释放下限 0：满员释放后回 1，重复释放不扣成负数。"""
    store = app.engine.courses
    store.set_enrolled("PHY101", 2)  # quota=4
    store.release("PHY101")
    assert store.enrolled("PHY101") == 1
    store.release("PHY101")
    store.release("PHY101")  # 已到 0
    assert store.enrolled("PHY101") == 0


def test_concurrent_try_enroll_no_oversell(app):
    """并发抢课不超卖：quota=2，8 线程同时占课，恰好 2 个成功。"""
    store = app.engine.courses
    store.set_enrolled("CS101", 0)  # quota=2
    results: list[bool] = []
    lock = threading.Lock()

    def worker():
        ok = store.try_enroll("CS101")
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 2, f"应恰好 2 个成功，实际 {sum(results)}"
    assert store.enrolled("CS101") == 2


def test_engine_submit_uses_db_quota(app):
    """全链路：引擎 submit 的满员拦截以 DB 在册人数为权威来源。"""
    engine = app.engine
    engine.courses.set_enrolled("CS101", 2)  # 满员（quota=2）
    try:
        engine.submit(
            applicant_id="S10001",
            process_type=C.PROCESS_COURSE_SELECTION,
            payload={"course_ids": ["CS101"], "major": "CS", "passed_courses": []},
            client_request_no="G2-FULL-001",
        )
        raise AssertionError("满员课程不应提交成功")
    except ValidationError as e:
        assert any("CS101" in v and "名额已满" in v for v in e.details["violations"])


def test_quota_check_without_store_skips_enrolled(app):
    """无 store 时名额判定跳过（存在性/其他规则仍生效），兼容只读/演示调用。"""
    violations = R.validate_rules(["course_quota"], {"course_ids": ["CS101"]})
    assert violations == []
    violations = R.validate_rules(["course_quota"], {"course_ids": ["NO-SUCH"]})
    assert any("课程不存在" in v for v in violations)
