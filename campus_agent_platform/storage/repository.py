"""仓储层：申请单 / 审批记录 / 流程模板的读写。

所有写操作均通过 SQL 层完成；乐观锁由 advance 流程在引擎中实现。
"""

from __future__ import annotations

from typing import Any

from ..domain import constants as C
from ..domain.errors import NotFoundError, TemplateNotFoundError
from ..domain.models import ApprovalRecord, ApprovalRequest, ProcessTemplate
from .database import Database, dumps, loads

_REQUEST_COLS = (
    "request_no, applicant_id, process_type, payload, attachment_urls, "
    "client_request_no, status, current_node_id, resolved_nodes, version, created_at, "
    "updated_at, archived_at, archive_hash, doc_check"
)


class RequestRepository:
    """申请单仓储。"""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    def insert(self, req: ApprovalRequest) -> None:
        self.db.execute(
            f"INSERT INTO approval_requests ({_REQUEST_COLS}) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                req.request_no,
                req.applicant_id,
                req.process_type,
                dumps(req.payload),
                dumps(req.attachment_urls),
                req.client_request_no,
                req.status,
                req.current_node_id,
                dumps(req.resolved_nodes),
                req.version,
                req.created_at,
                req.updated_at,
                req.archived_at,
                req.archive_hash,
                dumps(req.doc_check),
            ),
        )

    def get(self, request_no: str) -> ApprovalRequest:
        row = self.db.execute(
            "SELECT * FROM approval_requests WHERE request_no = ?", (request_no,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"申请单不存在: {request_no}")
        return self._row_to_model(row)

    def get_optional(self, request_no: str) -> ApprovalRequest | None:
        row = self.db.execute(
            "SELECT * FROM approval_requests WHERE request_no = ?", (request_no,)
        ).fetchone()
        return self._row_to_model(row) if row else None

    def get_by_client_no(
        self, client_request_no: str, applicant_id: str | None = None
    ) -> ApprovalRequest | None:
        """按幂等键查已有申请。幂等键作用域 = 申请人（(applicant_id, client_request_no) 复合唯一）。"""
        if applicant_id is None:
            row = self.db.execute(
                "SELECT * FROM approval_requests WHERE client_request_no = ?",
                (client_request_no,),
            ).fetchone()
        else:
            row = self.db.execute(
                "SELECT * FROM approval_requests WHERE applicant_id = ? AND client_request_no = ?",
                (applicant_id, client_request_no),
            ).fetchone()
        return self._row_to_model(row) if row else None

    def update_status(
        self,
        request_no: str,
        status: str,
        node_id: str | None,
        *,
        expected_version: int | None = None,
        archive_hash: str | None = None,
    ) -> int:
        """按乐观锁更新状态；返回受影响行数（0 = 版本冲突）。

        注意：本方法执行 UPDATE，随后由调用方负责 commit。
        """
        now = _now()
        sets = ["status = ?", "current_node_id = ?", "updated_at = ?"]
        params: list[Any] = [status, node_id, now]
        if archive_hash is not None:
            sets.append("archive_hash = ?")
            params.append(archive_hash)
            sets.append("archived_at = ?")
            params.append(now)
        params.append(request_no)
        if expected_version is not None:
            sets.append("version = version + 1")
            where = " AND version = ?"
            params.append(expected_version)
        else:
            where = ""
        cur = self.db.execute(
            f"UPDATE approval_requests SET {', '.join(sets)} WHERE request_no = ?{where}",
            tuple(params),
        )
        return cur.rowcount

    def mark_archived(self, request_no: str, archive_hash: str, expected_version: int) -> int:
        return self.update_status(
            request_no,
            C.STATUS_ARCHIVED,
            None,
            expected_version=expected_version,
            archive_hash=archive_hash,
        )

    def list_by_applicant(self, applicant_id: str) -> list[ApprovalRequest]:
        rows = self.db.execute(
            "SELECT * FROM approval_requests WHERE applicant_id = ? ORDER BY created_at DESC",
            (applicant_id,),
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    def list_all(self, limit: int = 100) -> list[ApprovalRequest]:
        rows = self.db.execute(
            "SELECT * FROM approval_requests ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    # ------------------------------------------------------------------
    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            request_no=row["request_no"],
            applicant_id=row["applicant_id"],
            process_type=row["process_type"],
            payload=loads(row["payload"], {}),
            attachment_urls=loads(row["attachment_urls"], []),
            client_request_no=row["client_request_no"],
            status=row["status"],
            current_node_id=row["current_node_id"],
            resolved_nodes=loads(row["resolved_nodes"], []),
            version=row["version"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            archived_at=row["archived_at"],
            archive_hash=row["archive_hash"],
            doc_check=loads(row["doc_check"], {}),
        )


class ApprovalRecordRepository:
    """审批记录仓储。"""

    def __init__(self, db: Database):
        self.db = db

    def insert(self, rec: ApprovalRecord) -> None:
        self.db.execute(
            "INSERT INTO approval_records (id, request_no, node_id, approver_id, "
            "decision, comment, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                rec.id,
                rec.request_no,
                rec.node_id,
                rec.approver_id,
                rec.decision,
                rec.comment,
                rec.created_at,
            ),
        )

    def list_by_request(self, request_no: str) -> list[ApprovalRecord]:
        rows = self.db.execute(
            "SELECT * FROM approval_records WHERE request_no = ? ORDER BY created_at ASC",
            (request_no,),
        ).fetchall()
        return [
            ApprovalRecord(
                id=r["id"],
                request_no=r["request_no"],
                node_id=r["node_id"],
                approver_id=r["approver_id"],
                decision=r["decision"],
                comment=r["comment"],
                created_at=r["created_at"],
            )
            for r in rows
        ]


class TemplateRepository:
    """流程模板仓储（模板版本化：process_type + version 唯一）。"""

    def __init__(self, db: Database):
        self.db = db

    def insert(self, tpl: ProcessTemplate) -> None:
        self.db.execute(
            "INSERT INTO process_templates (process_type, version, nodes, "
            "validation_rules, auto_pass_rules, created_at) VALUES (?,?,?,?,?,?)",
            (
                tpl.process_type,
                tpl.version,
                dumps([n.model_dump() for n in tpl.nodes]),
                dumps(tpl.validation_rules),
                dumps(tpl.auto_pass_rules),
                tpl.created_at,
            ),
        )

    def get_latest(self, process_type: str) -> ProcessTemplate:
        row = self.db.execute(
            "SELECT * FROM process_templates WHERE process_type = ? "
            "ORDER BY version DESC LIMIT 1",
            (process_type,),
        ).fetchone()
        if row is None:
            raise TemplateNotFoundError(f"流程模板未注册: {process_type}")
        return self._row_to_model(row)

    def get_optional_latest(self, process_type: str) -> ProcessTemplate | None:
        row = self.db.execute(
            "SELECT * FROM process_templates WHERE process_type = ? "
            "ORDER BY version DESC LIMIT 1",
            (process_type,),
        ).fetchone()
        return self._row_to_model(row) if row else None

    def exists(self, process_type: str) -> bool:
        return self.get_optional_latest(process_type) is not None

    def list_all(self) -> list[ProcessTemplate]:
        rows = self.db.execute(
            "SELECT * FROM process_templates ORDER BY process_type, version DESC"
        ).fetchall()
        return [self._row_to_model(r) for r in rows]

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> ProcessTemplate:
        nodes = [
            {"node_id": n["node_id"], "approver_role": n["approver_role"]}
            for n in loads(row["nodes"], [])
        ]
        return ProcessTemplate(
            process_type=row["process_type"],
            version=row["version"],
            nodes=nodes,
            validation_rules=loads(row["validation_rules"], []),
            auto_pass_rules=loads(row["auto_pass_rules"], {}),
            created_at=row["created_at"],
        )


def _now() -> float:
    import time

    return time.time()
