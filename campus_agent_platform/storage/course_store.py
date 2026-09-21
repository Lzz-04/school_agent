"""选课占课存储：内存 dict → DB 表 + 原子扣减（G2 修复）。

设计要点：
- 校验 / 占课 / 释放全部走 DB：`UPDATE ... SET enrolled=enrolled+1
  WHERE course_id=? AND enrolled < quota` 单条原子，以 affected rowcount 判成败；
- 进程重启名额不丢失；多 worker 共用同一库口径一致；
- 种子幂等（INSERT OR IGNORE + MAX 合并），不覆盖已存在数据；
- 释放下限 0，防重复退选把名额扣成负数。
"""

from __future__ import annotations

from typing import Any

from .database import Database


class CourseEnrollmentStore:
    def __init__(
        self,
        db: Database,
        catalog: dict[str, dict[str, Any]] | None = None,
        initial: dict[str, int] | None = None,
    ):
        self.db = db
        self._catalog = catalog or {}
        self._seed(initial or {})

    # ------------------------------------------------------------------
    def _seed(self, initial: dict[str, int]) -> None:
        """幂等种子：目录内每门课一行；initial 作为初始在册基线（只增不减）。"""
        for cid, course in self._catalog.items():
            self.db.execute(
                "INSERT OR IGNORE INTO course_enrollments (course_id, quota, enrolled) "
                "VALUES (?, ?, 0)",
                (cid, int(course["quota"])),
            )
        for cid, n in initial.items():
            if cid in self._catalog:
                self.db.execute(
                    "UPDATE course_enrollments SET enrolled = MAX(enrolled, ?) "
                    "WHERE course_id = ?",
                    (max(0, int(n)), cid),
                )
        self.db.commit()

    # ------------------------------------------------------------------
    def enrolled(self, course_id: str) -> int:
        """当前在册人数（无记录视为 0，兼容未种子化的课程）。"""
        row = self.db.execute(
            "SELECT enrolled FROM course_enrollments WHERE course_id = ?", (course_id,)
        ).fetchone()
        return row["enrolled"] if row else 0

    def remaining(self, course_id: str) -> int:
        """剩余名额（quota - enrolled，下限 0）。"""
        row = self.db.execute(
            "SELECT quota, enrolled FROM course_enrollments WHERE course_id = ?",
            (course_id,),
        ).fetchone()
        if row is None:
            return 0
        return max(0, int(row["quota"]) - int(row["enrolled"]))

    def is_full(self, course_id: str) -> bool:
        return self.remaining(course_id) <= 0

    def try_enroll(self, course_id: str) -> bool:
        """原子占课：仅当 enrolled < quota 时 +1；返回是否占课成功。

        单条 UPDATE + WHERE 条件即原子判定，校验与占课之间不存在窗口。
        """
        cur = self.db.execute(
            "UPDATE course_enrollments SET enrolled = enrolled + 1 "
            "WHERE course_id = ? AND enrolled < quota",
            (course_id,),
        )
        return cur.rowcount == 1

    def release(self, course_id: str) -> None:
        """退选释放名额（下限 0，防重复退选扣成负数）。"""
        self.db.execute(
            "UPDATE course_enrollments SET enrolled = MAX(enrolled - 1, 0) "
            "WHERE course_id = ?",
            (course_id,),
        )

    def set_enrolled(self, course_id: str, n: int) -> None:
        """直接设置在册人数（测试重置基线 / 运维校正用）。"""
        self.db.execute(
            "UPDATE course_enrollments SET enrolled = ? WHERE course_id = ?",
            (max(0, int(n)), course_id),
        )
        self.db.commit()

    def list_enrolled(self) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT course_id, enrolled FROM course_enrollments"
        ).fetchall()
        return {r["course_id"]: r["enrolled"] for r in rows}
