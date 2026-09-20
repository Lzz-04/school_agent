"""验证旧库幂等键迁移：数据保留 + 复合唯一生效（独立脚本，不依赖 pytest）。"""
import sqlite3
import tempfile
import time
from pathlib import Path

from campus_agent_platform.app import CampusAgentApp

# 1) 构造旧结构库：其余表与 database.py 建表一致，仅 approval_requests 用列级 UNIQUE
p = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
c = sqlite3.connect(p)
c.executescript(
    """
    CREATE TABLE approval_requests (
      request_no TEXT PRIMARY KEY, applicant_id TEXT NOT NULL, process_type TEXT NOT NULL,
      payload TEXT NOT NULL DEFAULT '{}', attachment_urls TEXT NOT NULL DEFAULT '[]',
      client_request_no TEXT UNIQUE, status TEXT NOT NULL, current_node_id TEXT,
      resolved_nodes TEXT NOT NULL DEFAULT '[]', version INTEGER NOT NULL DEFAULT 0,
      created_at REAL NOT NULL, updated_at REAL NOT NULL, archived_at REAL, archive_hash TEXT,
      doc_check TEXT NOT NULL DEFAULT '{}');
    CREATE TABLE approval_records (
      id TEXT PRIMARY KEY, request_no TEXT NOT NULL, node_id TEXT NOT NULL,
      approver_id TEXT NOT NULL, decision TEXT NOT NULL, comment TEXT NOT NULL DEFAULT '',
      created_at REAL NOT NULL);
    CREATE TABLE process_templates (
      process_type TEXT NOT NULL, version INTEGER NOT NULL, nodes TEXT NOT NULL,
      validation_rules TEXT NOT NULL DEFAULT '[]', auto_pass_rules TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL, PRIMARY KEY (process_type, version));
    CREATE TABLE audit_events (
      id TEXT PRIMARY KEY, event_type TEXT NOT NULL, entity_type TEXT NOT NULL DEFAULT 'request',
      entity_id TEXT NOT NULL, actor_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL);
    CREATE TABLE outbox_messages (
      id TEXT PRIMARY KEY, request_no TEXT NOT NULL, recipient_id TEXT NOT NULL,
      channel TEXT NOT NULL, template TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL DEFAULT '{}',
      status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL);
    CREATE TABLE users (
      user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
      salt TEXT NOT NULL, role TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
      email TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
      created_at REAL NOT NULL);
    CREATE TABLE chat_sessions (
      session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT '',
      created_at REAL NOT NULL);
    CREATE TABLE chat_messages (
      id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
      content TEXT NOT NULL, retrieved_chunks TEXT NOT NULL DEFAULT '[]',
      attachments TEXT NOT NULL DEFAULT '[]', form_draft TEXT NOT NULL DEFAULT '{}',
      created_at REAL NOT NULL);
    CREATE TABLE knowledge_chunks (
      chunk_id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
      content TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '');
    CREATE TABLE classes (
      class_id TEXT PRIMARY KEY, grade TEXT NOT NULL, major TEXT NOT NULL, name TEXT NOT NULL,
      counselor_id TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
    """
)
t = time.time()
c.execute(
    "INSERT INTO approval_requests (request_no, applicant_id, process_type, payload, client_request_no, status, version, created_at, updated_at) "
    "VALUES ('RQ_OLD_1','S10001','leave','{}','OLD-KEY-1','pending_counselor',0,?,?)",
    (t, t),
)
c.execute(
    "INSERT INTO users (user_id, username, password_hash, salt, role, name, email, status, created_at) "
    "VALUES ('admin','admin','x','x','admin','管理员','','active',?)",
    (t,),
)
c.commit()
c.close()

# 2) 打开旧库 → 触发迁移
inst = CampusAgentApp(db_path=p)
db = inst.db
idxs = db.execute("PRAGMA index_list('approval_requests')").fetchall()
names = [r["name"] for r in idxs]
print("indexes:", names)
uniq_auto = [r for r in idxs if r["origin"] == "u"]
assert not uniq_auto, f"列级 UNIQUE 自动索引未移除: {uniq_auto}"
assert "idx_requests_idem" in names, "复合唯一索引未创建"

row = db.execute(
    "SELECT request_no, applicant_id, client_request_no, status FROM approval_requests"
).fetchone()
print("data preserved:", dict(row) if row else None)
assert row is not None and row["request_no"] == "RQ_OLD_1"

# 3) 复合唯一生效：同申请人同键再插 → 冲突被拦
try:
    db.execute(
        "INSERT INTO approval_requests (request_no, applicant_id, process_type, payload, client_request_no, status, version, created_at, updated_at) "
        "VALUES ('RQ_OLD_2','S10001','leave','{}','OLD-KEY-1','pending_counselor',0,1,1)"
    )
    db.commit()
    print("duplicate insert: UNEXPECTED OK")
    raise SystemExit(1)
except sqlite3.IntegrityError:
    print("duplicate insert blocked: OK")

inst.close()
Path(p).unlink(missing_ok=True)
print("MIGRATION VERIFIED")
