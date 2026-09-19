"""审计日志：append-only 写入 + 查询。

设计文档 5.4「审批不可篡改」：审计事件只允许 INSERT / SELECT，
不允许 UPDATE / DELETE，完整性校验由归档哈希辅助。
"""

from __future__ import annotations

from ..domain.models import AuditEvent
from .database import Database, dumps


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def append(self, event: AuditEvent) -> None:
        """追加审计事件（仅插入，不提供更新/删除接口）。"""
        self.db.execute(
            "INSERT INTO audit_events (id, event_type, entity_type, entity_id, "
            "actor_id, detail, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                event.id,
                event.event_type,
                event.entity_type,
                event.entity_id,
                event.actor_id,
                dumps(event.detail),
                event.created_at,
            ),
        )

    def list_by_entity(self, entity_id: str) -> list[AuditEvent]:
        rows = self.db.execute(
            "SELECT * FROM audit_events WHERE entity_id = ? ORDER BY created_at ASC",
            (entity_id,),
        ).fetchall()
        return self._rows(rows)

    def list_all(self, limit: int = 200) -> list[AuditEvent]:
        rows = self.db.execute(
            "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return self._rows(rows)

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) AS c FROM audit_events").fetchone()["c"]

    @staticmethod
    def _rows(rows) -> list[AuditEvent]:
        out = []
        for r in rows:
            out.append(
                AuditEvent(
                    id=r["id"],
                    event_type=r["event_type"],
                    entity_type=r["entity_type"],
                    entity_id=r["entity_id"],
                    actor_id=r["actor_id"],
                    detail=__import__("json").loads(r["detail"] or "{}"),
                    created_at=r["created_at"],
                )
            )
        return out
