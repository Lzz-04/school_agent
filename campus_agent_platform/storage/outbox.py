"""通知 outbox：状态提交与通知投递解耦（设计文档 5.4）。

崩溃窗口补偿：状态已提交但通知未发出 → 通知事件与状态提交同事务写入 outbox，
由 dispatch 任务（或补偿任务）异步投递，投递失败保留 failed 状态供重试 / 人工升级。
"""

from __future__ import annotations

import logging
from typing import Any

from ..domain.models import OutboxMessage
from .database import Database, dumps, loads

logger = logging.getLogger(__name__)


class Outbox:
    def __init__(self, db: Database):
        self.db = db

    def enqueue(
        self,
        *,
        request_no: str,
        recipient_id: str,
        channel: str,
        template: str,
        payload: dict[str, Any],
    ) -> OutboxMessage:
        msg = OutboxMessage(
            request_no=request_no,
            recipient_id=recipient_id,
            channel=channel,
            template=template,
            payload=payload,
        )
        self.db.execute(
            "INSERT INTO outbox_messages (id, request_no, recipient_id, channel, "
            "template, payload, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                msg.id,
                msg.request_no,
                msg.recipient_id,
                msg.channel,
                msg.template,
                dumps(msg.payload),
                msg.status,
                msg.created_at,
            ),
        )
        return msg

    def mark_sent(self, msg_id: str) -> None:
        self.db.execute(
            "UPDATE outbox_messages SET status = 'sent' WHERE id = ?", (msg_id,)
        )

    def mark_failed(self, msg_id: str) -> None:
        self.db.execute(
            "UPDATE outbox_messages SET status = 'failed' WHERE id = ?", (msg_id,)
        )

    def pending(self, limit: int = 100) -> list[OutboxMessage]:
        rows = self.db.execute(
            "SELECT * FROM outbox_messages WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            OutboxMessage(
                id=r["id"],
                request_no=r["request_no"],
                recipient_id=r["recipient_id"],
                channel=r["channel"],
                template=r["template"],
                payload=loads(r["payload"], {}),
                status=r["status"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def count_pending(self) -> int:
        return self.db.execute(
            "SELECT COUNT(*) AS c FROM outbox_messages WHERE status = 'pending'"
        ).fetchone()["c"]


class NotificationDispatcher:
    """投递器：默认写日志（可替换为真实 IM / 邮件 / SMS 实现）。

    与设计文档「通知服务（IM / 邮件 / SMS）」契约对齐，
    投递失败降级为人工升级（Guardrails）。
    """

    def __init__(self, outbox: Outbox, *, sink: str = "log"):
        self.outbox = outbox
        self.sink = sink

    def dispatch_pending(self, limit: int = 100) -> int:
        """投递所有 pending 消息，返回成功条数。"""
        sent = 0
        for msg in self.outbox.pending(limit):
            try:
                self._deliver(msg)
                self.outbox.mark_sent(msg.id)
                sent += 1
            except Exception as exc:  # noqa: BLE001 - 投递失败留 failed 供重试/人工升级
                logger.error("通知投递失败 %s: %s", msg.id, exc)
                self.outbox.mark_failed(msg.id)
        return sent

    def _deliver(self, msg: OutboxMessage) -> None:
        if self.sink == "log":
            logger.info(
                "[notify] channel=%s to=%s template=%s payload=%s",
                msg.channel,
                msg.recipient_id,
                msg.template,
                msg.payload,
            )
        else:
            raise NotImplementedError(f"未实现的投递通道: {self.sink}")
