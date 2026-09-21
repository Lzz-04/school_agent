"""G1：显式事务（BEGIN IMMEDIATE + 事务期持锁）回归测试。

验证契约：
1. 事务打开期间，其他线程的写操作被阻塞——不再混入隐式事务、
   污染 commit/rollback 边界（旧实现下"outbox 与状态提交同事务"在并发时不成立）；
2. 事务内写入 + 异常 → 全部回滚；且其他线程先完成（或后完成）的写不受影响；
3. 事务内写入 + 正常退出 → 全部提交；
4. 嵌套 transaction() 显式报错（不再静默共享同一事务）。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest


def _insert_course(db, key: str, quota: int = 5) -> None:
    db.execute(
        "INSERT OR REPLACE INTO course_enrollments (course_id, quota, enrolled) "
        "VALUES (?, ?, 0)",
        (key, quota),
    )
    db.commit()


def _start_worker(db, sql: str, params: tuple, done: list) -> threading.Thread:
    """启动一个会在 db 上执行写操作的后台线程。"""
    t = threading.Thread(target=lambda: (db.execute(sql, params), db.commit(), done.append(True)), daemon=True)
    t.start()
    return t


def test_concurrent_write_blocked_while_transaction_open(app):
    """事务打开期间其他线程的写应被阻塞；提交后其写入独立生效。"""
    db = app.db
    _insert_course(db, "T-BLOCK")

    tx = db.transaction()
    tx.__enter__()
    started = threading.Event()
    done: list[bool] = []

    def worker():
        started.set()
        db.execute("UPDATE course_enrollments SET enrolled = 1 WHERE course_id = ?", ("T-BLOCK",))
        db.commit()
        done.append(True)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    assert started.wait(2), "worker 未启动"
    t.join(0.8)
    # G1 修复后：事务期持锁 → worker 被阻塞；修复前：立即执行完（写混入本事务）
    assert t.is_alive(), "事务打开期间其他线程的写不应混入（应被阻塞直到提交）"

    tx.__exit__(None, None, None)
    t.join(2)
    assert done, "事务提交后 worker 应完成自己的独立事务"
    row = db.execute(
        "SELECT enrolled FROM course_enrollments WHERE course_id=?", ("T-BLOCK",)
    ).fetchone()
    assert row["enrolled"] == 1


def test_rollback_does_not_touch_other_thread_write(app):
    """主事务回滚只撤销自己的写，不影响其他线程独立完成的事务。"""
    db = app.db
    _insert_course(db, "T-RB")

    tx = db.transaction()
    tx.__enter__()
    db.execute("UPDATE course_enrollments SET enrolled = 7 WHERE course_id = ?", ("T-RB",))
    started = threading.Event()
    done: list[bool] = []

    def worker():
        started.set()
        db.execute("UPDATE course_enrollments SET enrolled = 3 WHERE course_id = ?", ("T-RB",))
        db.commit()
        done.append(True)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    assert started.wait(2), "worker 未启动"
    t.join(0.8)
    assert t.is_alive(), "事务打开期间其他线程的写不应混入（应被阻塞直到回滚）"

    # 主事务回滚：enrolled=7 撤销；worker 的 enrolled=3 保持（独立事务，不受影响）
    tx.__exit__(RuntimeError, RuntimeError("boom"), None)
    t.join(2)
    assert done, "回滚后 worker 应完成自己的独立事务"
    row = db.execute(
        "SELECT enrolled FROM course_enrollments WHERE course_id=?", ("T-RB",)
    ).fetchone()
    assert row["enrolled"] == 3, "主事务回滚不应连带回滚其他线程的独立写"


def test_commit_applies_all_writes_atomically(app):
    """事务内多写（状态 + outbox + 审计）正常退出时一起提交。"""
    db = app.db
    with db.transaction():
        _insert_course(db, "T-COMMIT")
        db.execute("UPDATE course_enrollments SET enrolled = 9 WHERE course_id = ?", ("T-COMMIT",))
    row = db.execute(
        "SELECT enrolled FROM course_enrollments WHERE course_id=?", ("T-COMMIT",)
    ).fetchone()
    assert row["enrolled"] == 9


def test_rollback_discards_all_writes_atomically(app):
    """事务内异常 → 全部写回滚（含同事务插入的新行）。"""
    db = app.db
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute(
                "INSERT INTO course_enrollments (course_id, quota, enrolled) VALUES (?,?,0)",
                ("T-ROLLBACK", 5),
            )
            db.execute("UPDATE course_enrollments SET enrolled = 4 WHERE course_id = ?", ("T-ROLLBACK",))
            raise RuntimeError("模拟失败")
    row = db.execute(
        "SELECT enrolled FROM course_enrollments WHERE course_id=?", ("T-ROLLBACK",)
    ).fetchone()
    assert row is None, "事务回滚后同事务插入的行不应存在"


def test_nested_transaction_fails_loudly(app):
    """嵌套 transaction() 显式报错（不再静默共享同一事务）。"""
    db = app.db
    with pytest.raises(sqlite3.OperationalError):
        with db.transaction():
            with db.transaction():
                pass
