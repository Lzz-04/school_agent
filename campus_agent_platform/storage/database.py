"""SQLite 数据库连接与建表。

表结构：
- approval_requests : 申请单（(applicant_id, client_request_no) 复合唯一索引实现按申请人幂等；version 乐观锁）
- approval_records  : 审批记录（节点、审批人、决策）
- process_templates : 流程模板（process_type+version 唯一，支持版本化灰度/回滚）
- audit_events      : 审计日志（append-only）
- outbox_messages   : 通知 outbox（状态提交与通知投递解耦）
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class Database:
    """轻量 SQLite 封装，线程安全（单写连接 + 锁）。"""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._create_tables()
        self._migrate()

    # ------------------------------------------------------------------
    def _create_tables(self) -> None:
        with self._lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    request_no        TEXT PRIMARY KEY,
                    applicant_id      TEXT NOT NULL,
                    process_type      TEXT NOT NULL,
                    payload           TEXT NOT NULL DEFAULT '{}',
                    attachment_urls   TEXT NOT NULL DEFAULT '[]',
                    client_request_no TEXT,
                    status            TEXT NOT NULL,
                    current_node_id   TEXT,
                    resolved_nodes    TEXT NOT NULL DEFAULT '[]',
                    version           INTEGER NOT NULL DEFAULT 0,
                    created_at        REAL NOT NULL,
                    updated_at        REAL NOT NULL,
                    archived_at       REAL,
                    archive_hash      TEXT,
                    doc_check         TEXT NOT NULL DEFAULT '{}'
                );
                -- 幂等键作用域 = 申请人：同一个人重试同键返回同一单；不同人同键互不干扰
                CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_idem
                    ON approval_requests(applicant_id, client_request_no)
                    WHERE client_request_no IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_requests_applicant
                    ON approval_requests(applicant_id);
                CREATE INDEX IF NOT EXISTS idx_requests_status
                    ON approval_requests(status);

                CREATE TABLE IF NOT EXISTS approval_records (
                    id          TEXT PRIMARY KEY,
                    request_no  TEXT NOT NULL,
                    node_id     TEXT NOT NULL,
                    approver_id TEXT NOT NULL,
                    decision    TEXT NOT NULL,
                    comment     TEXT NOT NULL DEFAULT '',
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_records_request
                    ON approval_records(request_no, created_at);

                CREATE TABLE IF NOT EXISTS process_templates (
                    process_type     TEXT NOT NULL,
                    version          INTEGER NOT NULL,
                    nodes            TEXT NOT NULL,
                    validation_rules TEXT NOT NULL DEFAULT '[]',
                    auto_pass_rules  TEXT NOT NULL DEFAULT '{}',
                    created_at       REAL NOT NULL,
                    PRIMARY KEY (process_type, version)
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id          TEXT PRIMARY KEY,
                    event_type  TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'request',
                    entity_id   TEXT NOT NULL,
                    actor_id    TEXT NOT NULL DEFAULT '',
                    detail      TEXT NOT NULL DEFAULT '{}',
                    created_at  REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_entity
                    ON audit_events(entity_type, entity_id);

                CREATE TABLE IF NOT EXISTS outbox_messages (
                    id           TEXT PRIMARY KEY,
                    request_no   TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    channel      TEXT NOT NULL,
                    template     TEXT NOT NULL DEFAULT '',
                    payload      TEXT NOT NULL DEFAULT '{}',
                    status       TEXT NOT NULL DEFAULT 'pending',
                    created_at   REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_status
                    ON outbox_messages(status, created_at);

                CREATE TABLE IF NOT EXISTS users (
                    user_id       TEXT PRIMARY KEY,
                    username      TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    salt          TEXT NOT NULL,
                    role          TEXT NOT NULL,
                    name          TEXT NOT NULL DEFAULT '',
                    email         TEXT NOT NULL DEFAULT '',
                    status        TEXT NOT NULL DEFAULT 'active',
                    created_at    REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id    TEXT NOT NULL,
                    title      TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
                    ON chat_sessions(user_id, created_at);

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id             TEXT PRIMARY KEY,
                    session_id     TEXT NOT NULL,
                    role           TEXT NOT NULL,
                    content        TEXT NOT NULL,
                    retrieved_chunks TEXT NOT NULL DEFAULT '[]',
                    attachments    TEXT NOT NULL DEFAULT '[]',
                    form_draft     TEXT NOT NULL DEFAULT '{}',
                    created_at     REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_chat_messages_session
                    ON chat_messages(session_id, created_at);

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    chunk_id  TEXT PRIMARY KEY,
                    category  TEXT NOT NULL,
                    title     TEXT NOT NULL,
                    content   TEXT NOT NULL,
                    keywords  TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_category
                    ON knowledge_chunks(category);
                """
            )

    def _migrate(self) -> None:
        """对老库补列（幂等）。"""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(approval_requests)").fetchall()}
        if "doc_check" not in cols:
            self.conn.execute("ALTER TABLE approval_requests ADD COLUMN doc_check TEXT NOT NULL DEFAULT '{}'")
        tcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(process_templates)").fetchall()}
        if "auto_pass_rules" not in tcols:
            self.conn.execute("ALTER TABLE process_templates ADD COLUMN auto_pass_rules TEXT NOT NULL DEFAULT '{}'")
        mcols = {r["name"] for r in self.conn.execute("PRAGMA table_info(chat_messages)").fetchall()}
        if "form_draft" not in mcols:
            self.conn.execute("ALTER TABLE chat_messages ADD COLUMN form_draft TEXT NOT NULL DEFAULT '{}'")
        ucols = {r["name"] for r in self.conn.execute("PRAGMA table_info(users)").fetchall()}
        if "class_id" not in ucols:
            self.conn.execute("ALTER TABLE users ADD COLUMN class_id TEXT NOT NULL DEFAULT ''")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS classes ("
            " class_id TEXT PRIMARY KEY,"
            " grade TEXT NOT NULL,"
            " major TEXT NOT NULL,"
            " name TEXT NOT NULL,"
            " counselor_id TEXT NOT NULL DEFAULT '',"
            " created_at REAL NOT NULL)"
        )
        self._migrate_idempotency_key()
        self.conn.commit()

    def _migrate_idempotency_key(self) -> None:
        """旧库：client_request_no 列级 UNIQUE（全表唯一）→ (applicant_id, client_request_no) 复合唯一。

        SQLite 无法直接删除列级 UNIQUE 自动索引，采用「建新表 → 复制数据 → 换名」迁移；
        已迁移（无 autoindex）或新库（直接按新结构建表）时跳过。数据完整保留。
        """
        idxs = self.conn.execute("PRAGMA index_list('approval_requests')").fetchall()
        # 列级 UNIQUE 约束的自动索引 origin='u'（注意：序号 1 的 autoindex 可能是主键 origin='pk'）
        has_old_autoindex = any(r["origin"] == "u" for r in idxs)
        if not has_old_autoindex:
            return
        self.conn.executescript(
            """
            CREATE TABLE approval_requests_new (
                request_no        TEXT PRIMARY KEY,
                applicant_id      TEXT NOT NULL,
                process_type      TEXT NOT NULL,
                payload           TEXT NOT NULL DEFAULT '{}',
                attachment_urls   TEXT NOT NULL DEFAULT '[]',
                client_request_no TEXT,
                status            TEXT NOT NULL,
                current_node_id   TEXT,
                resolved_nodes    TEXT NOT NULL DEFAULT '[]',
                version           INTEGER NOT NULL DEFAULT 0,
                created_at        REAL NOT NULL,
                updated_at        REAL NOT NULL,
                archived_at       REAL,
                archive_hash      TEXT,
                doc_check         TEXT NOT NULL DEFAULT '{}'
            );
            INSERT INTO approval_requests_new (
                request_no, applicant_id, process_type, payload, attachment_urls,
                client_request_no, status, current_node_id, resolved_nodes, version,
                created_at, updated_at, archived_at, archive_hash, doc_check
            ) SELECT
                request_no, applicant_id, process_type, payload, attachment_urls,
                client_request_no, status, current_node_id, resolved_nodes, version,
                created_at, updated_at, archived_at, archive_hash, doc_check
            FROM approval_requests;
            DROP TABLE approval_requests;
            ALTER TABLE approval_requests_new RENAME TO approval_requests;
            """
        )
        self.conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_idem "
            "ON approval_requests(applicant_id, client_request_no) WHERE client_request_no IS NOT NULL"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_applicant ON approval_requests(applicant_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_requests_status ON approval_requests(status)"
        )

    # ------------------------------------------------------------------
    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq: list[tuple]) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.executemany(sql, seq)

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def transaction(self):
        """事务上下文：with db.transaction(): ... 提交 / 回滚。"""
        return _Transaction(self)

    def close(self) -> None:
        with self._lock:
            self.conn.close()


class _Transaction:
    def __init__(self, db: Database):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._db.commit()
        else:
            self._db.conn.rollback()
        return False


# ----------------------------------------------------------------------
def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(raw: str | None, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default
