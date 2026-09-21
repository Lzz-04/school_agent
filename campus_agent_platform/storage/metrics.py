"""可观测性：对话/编排埋点（F1）+ 审批驾驶舱统计（F2）。

F1：每次 chat/ask 与 agent/run 记录 token 数、延迟、检索命中 chunk，
    聚合端点 `/api/v1/metrics/summary` 提供近 N 日趋势与 P50/P95 分位数——
    「我能量化系统成本和效果，说得出哪里慢、为什么」。

F2：审批驾驶舱——按流程类型统计单量/平均耗时/积压/SLA 逾期，
    按审批人统计待办/已办，近 N 日提交/办结趋势（`/api/v1/dashboard/approval-stats`）。

埋点只做追加写，不影响业务事务；失败静默（可观测性不得拖垮主流程）。
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Callable

from ..domain import constants as C
from ..storage.database import Database, dumps

EVENT_CHAT_ASK = "chat_ask"
EVENT_AGENT_RUN = "agent_run"


def _pct(values: list[float], p: float) -> float:
    """线性插值分位数；空列表返回 0。"""
    if not values:
        return 0.0
    s = sorted(values)
    pos = (p / 100.0) * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 1)


class MetricsRecorder:
    """F1：对话/编排埋点记录与聚合。"""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    def record(
        self,
        *,
        event_type: str,
        user_id: str,
        session_id: str = "",
        intent: str = "",
        latency_ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        retrieval_hits: int = 0,
        llm_used: bool = False,
        detail: dict | None = None,
    ) -> None:
        """追加一条埋点（独立小事务；失败不影响主流程）。"""
        try:
            self.db.execute(
                "INSERT INTO metric_events (id, event_type, user_id, session_id, intent, "
                "latency_ms, tokens_in, tokens_out, retrieval_hits, llm_used, detail, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "MTR-" + uuid.uuid4().hex[:12].upper(),
                    event_type,
                    user_id,
                    session_id,
                    intent,
                    float(latency_ms),
                    int(tokens_in),
                    int(tokens_out),
                    int(retrieval_hits),
                    1 if llm_used else 0,
                    dumps(detail or {}),
                    time.time(),
                ),
            )
            self.db.commit()
        except Exception:  # noqa: BLE001 - 埋点失败不影响业务
            import logging
            logging.getLogger(__name__).warning("metric 埋点失败", exc_info=True)

    # ------------------------------------------------------------------
    def summary(self, days: int = 7) -> dict:
        """近 N 日聚合：总量 / 分位数 / 每日趋势。"""
        days = max(1, min(int(days), 90))
        since = time.time() - days * 86400
        rows = self.db.execute(
            "SELECT event_type, latency_ms, tokens_in, tokens_out, retrieval_hits, "
            "llm_used, created_at FROM metric_events WHERE created_at >= ? ORDER BY created_at",
            (since,),
        ).fetchall()
        chat = [r for r in rows if r["event_type"] == EVENT_CHAT_ASK]
        runs = [r for r in rows if r["event_type"] == EVENT_AGENT_RUN]
        lat = [r["latency_ms"] for r in chat]
        hits = [r["retrieval_hits"] for r in chat]

        day0 = date.fromtimestamp(time.time()) - timedelta(days=days - 1)
        trend = []
        for i in range(days):
            d = day0 + timedelta(days=i)
            t0 = datetime(d.year, d.month, d.day).timestamp()
            t1 = t0 + 86400
            drow = [r for r in rows if t0 <= r["created_at"] < t1]
            dchat = [r for r in drow if r["event_type"] == EVENT_CHAT_ASK]
            trend.append({
                "date": d.isoformat(),
                "asks": len(dchat),
                "agent_runs": sum(1 for r in drow if r["event_type"] == EVENT_AGENT_RUN),
                "tokens": sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in dchat),
                "llm_used": sum(1 for r in dchat if r["llm_used"]),
            })

        return {
            "days": days,
            "total_asks": len(chat),
            "total_agent_runs": len(runs),
            "tokens_total": sum(int(r["tokens_in"]) + int(r["tokens_out"]) for r in chat),
            "avg_latency_ms": round(sum(lat) / len(lat), 1) if lat else 0.0,
            "p50_latency_ms": _pct(lat, 50),
            "p95_latency_ms": _pct(lat, 95),
            "llm_used_asks": sum(1 for r in chat if r["llm_used"]),
            "avg_retrieval_hits": round(sum(hits) / len(hits), 2) if hits else 0.0,
            "trend": trend,
        }

    # ------------------------------------------------------------------
    def cleanup(self, retention_days: int = 90) -> int:
        """清理超过保留期的埋点（默认 90 天），返回删除条数；失败静默返回 0。"""
        retention_days = max(1, int(retention_days))
        since = time.time() - retention_days * 86400
        try:
            cur = self.db.execute(
                "DELETE FROM metric_events WHERE created_at < ?", (since,)
            )
            self.db.commit()
            return max(int(cur.rowcount or 0), 0)
        except Exception:  # noqa: BLE001 - 清理失败不影响主流程
            import logging
            logging.getLogger(__name__).warning("metric 清理失败", exc_info=True)
            return 0


class ApprovalStats:
    """F2：审批驾驶舱统计（基于 approval_requests / approval_records）。"""

    # 各流程 SLA（小时）：超时未办结视为逾期（驾驶舱口径，可按需调）
    SLA_HOURS: dict[str, int] = {
        C.PROCESS_LEAVE: 48,
        C.PROCESS_COURSE_SELECTION: 24,
        C.PROCESS_REIMBURSEMENT: 72,
        C.PROCESS_VENUE_RESERVATION: 48,
    }

    TERMINAL = (C.STATUS_APPROVED, C.STATUS_REJECTED, C.STATUS_ARCHIVED)

    def __init__(
        self,
        db: Database,
        holder_for_role: Callable[[str], str] | None = None,
        name_of: Callable[[str], str] | None = None,
    ):
        self.db = db
        self._holder = holder_for_role or (lambda role: "")
        self._name_of = name_of or (lambda uid: uid)

    # ------------------------------------------------------------------
    def stats(self, days: int = 7, sla_hours: dict | None = None) -> dict:
        days = max(1, min(int(days), 90))
        sla = dict(self.SLA_HOURS)
        if sla_hours:
            for k, v in sla_hours.items():
                if v:
                    sla[k] = int(v)
        since = time.time() - days * 86400
        reqs = self.db.execute(
            "SELECT request_no, process_type, status, current_node_id, resolved_nodes, "
            "created_at, updated_at FROM approval_requests WHERE created_at >= ?",
            (since,),
        ).fetchall()
        records = self.db.execute(
            "SELECT request_no, approver_id FROM approval_records"
        ).fetchall()
        now = time.time()

        # --- 按流程类型 ---
        by_type: dict[str, dict[str, Any]] = {}
        for r in reqs:
            pt = r["process_type"]
            t = by_type.setdefault(pt, {
                "process_type": pt, "count": 0, "terminal": 0, "pending": 0,
                "overdue": 0, "durations_h": [],
            })
            t["count"] += 1
            if r["status"] in self.TERMINAL:
                t["terminal"] += 1
                dur_h = max(0.0, (r["updated_at"] or r["created_at"]) - r["created_at"]) / 3600.0
                t["durations_h"].append(dur_h)
            elif r["status"].startswith(C.STATUS_PENDING_PREFIX):
                t["pending"] += 1
                if now - r["created_at"] > sla.get(pt, 48) * 3600:
                    t["overdue"] += 1

        by_process_type = []
        for t in by_type.values():
            durs = t.pop("durations_h")
            by_process_type.append({
                **t,
                "avg_duration_h": round(sum(durs) / len(durs), 2) if durs else 0.0,
            })

        # --- 按审批人：待办（当前节点审批人）+ 已办（records 去重）---
        pending_by_approver: dict[str, int] = {}
        for r in reqs:
            if not r["status"].startswith(C.STATUS_PENDING_PREFIX):
                continue
            try:
                nodes = json.loads(r["resolved_nodes"] or "[]")
            except Exception:
                nodes = []
            node = next((n for n in nodes if n.get("node_id") == r["current_node_id"]), None)
            if node:
                approver = self._holder(str(node.get("approver_role", "")))
                if approver:
                    pending_by_approver[approver] = pending_by_approver.get(approver, 0) + 1
        handled_by_approver: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for rec in records:
            key = (rec["request_no"], rec["approver_id"])
            if key in seen:
                continue
            seen.add(key)
            handled_by_approver[rec["approver_id"]] = handled_by_approver.get(rec["approver_id"], 0) + 1

        approver_ids = sorted(set(pending_by_approver) | set(handled_by_approver))
        by_approver = [
            {
                "approver_id": uid,
                "name": self._name_of(uid),
                "pending": pending_by_approver.get(uid, 0),
                "handled": handled_by_approver.get(uid, 0),
            }
            for uid in approver_ids
        ]

        # --- 近 N 日趋势：提交 / 办结 ---
        day0 = date.fromtimestamp(time.time()) - timedelta(days=days - 1)
        trend = []
        for i in range(days):
            d = day0 + timedelta(days=i)
            t0 = datetime(d.year, d.month, d.day).timestamp()
            t1 = t0 + 86400
            dreq = [r for r in reqs if t0 <= r["created_at"] < t1]
            trend.append({
                "date": d.isoformat(),
                "submitted": len(dreq),
                "terminal": sum(1 for r in dreq if r["status"] in self.TERMINAL),
            })

        return {
            "days": days,
            "by_process_type": by_process_type,
            "by_approver": by_approver,
            "trend": trend,
            "total_pending": sum(t["pending"] for t in by_process_type),
            "total_overdue": sum(t["overdue"] for t in by_process_type),
        }
