"""验证 /api/v1/agent/run 编排接口的两个越权路径（临时库，只读验证）。

第二轮修复后（走 API 入口验证，与真实攻击路径一致）：
1. intent=status：他人走编排接口 → 403（与直接端点同口径，堵 IDOR）
2. intent=archive：他人走编排接口 → 403（权限矩阵拒绝，不再借硬编码 SYS001）
3. 对照：他人直接 GET /api/v1/requests/{no} → 403（第一轮已收口）
4. 正向：申请人本人走编排 status → 200
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient

from campus_agent_platform.app import CampusAgentApp
from campus_agent_platform.api.app import create_app
from campus_agent_platform.auth import security


def seed_users(app: CampusAgentApp):
    for uid, role, name in [("S10001", "student", "张三"), ("S10002", "student", "李四"),
                            ("C30001", "counselor", "陈辅导员")]:
        if app.db.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone():
            continue
        pw, salt = security.hash_password("123456")
        app.db.execute(
            "INSERT INTO users (user_id, username, password_hash, salt, role, name, email, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (uid, uid, pw, salt, role, name, "", "active", time.time()),
        )
    app.db.commit()


def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    Path(tmp.name).unlink(missing_ok=True)
    app = CampusAgentApp(db_path=tmp.name)
    seed_users(app)
    client = TestClient(create_app(app))

    # S10001 提交一张请假单
    req = app.engine.submit(
        applicant_id="S10001", process_type="leave",
        payload={"start_date": "2026-10-10", "end_date": "2026-10-12", "reason": "病假"},
    )
    rno = req.request_no
    print(f"[S10001 提交] request_no={rno} status={req.status}")

    tok2 = app.auth.login("S10002", "123456")["token"]
    h2 = {"Authorization": f"Bearer {tok2}"}
    tok1 = app.auth.login("S10001", "123456")["token"]
    h1 = {"Authorization": f"Bearer {tok1}"}

    # ---- 场景 1：S10002（他人）走编排接口查状态（修复后应 403）----
    r = client.post("/api/v1/agent/run", json={"intent": "status", "request_no": rno}, headers=h2)
    print(f"\n[场景1] S10002 通过 agent/run intent=status 查 S10001 的单")
    print(f"  HTTP {r.status_code}（期望 403，修复前泄露 payload）")
    assert r.status_code == 403, r.text

    # ---- 场景 2：S10002（他人）走编排接口归档 S10001 的已通过单（修复后应 403）----
    app.engine.advance(request_no=rno, approver_id="C30001", decision="approve")
    before = app.engine.requests.get(rno)
    print(f"\n[场景2 前置] 辅导员通过后 status={before.status}")
    r2 = client.post("/api/v1/agent/run", json={"intent": "archive", "request_no": rno}, headers=h2)
    after = app.engine.requests.get(rno)
    print(f"[场景2] S10002 通过 agent/run intent=archive 触发归档")
    print(f"  HTTP {r2.status_code}（期望 403）；归档后 status={after.status} archived_at={after.archived_at}（期望 approved/None）")
    assert r2.status_code == 403, r2.text
    assert after.status == "approved" and after.archived_at is None

    # ---- 对照：S10002 直接 GET /api/v1/requests/{no} 应被 403 ----
    r3 = client.get(f"/api/v1/requests/{rno}", headers=h2)
    print(f"\n[对照] S10002 直接 GET /api/v1/requests/{rno} → HTTP {r3.status_code}（应为 403）")
    assert r3.status_code == 403

    # ---- 正向：S10001 本人走编排 status → 200 ----
    r4 = client.post("/api/v1/agent/run", json={"intent": "status", "request_no": rno}, headers=h1)
    print(f"\n[正向] S10001 本人通过 agent/run intent=status → HTTP {r4.status_code}（应为 200）")
    assert r4.status_code == 200

    print("\n✅ 全部断言通过：两个越权路径已收口，正常路径不受影响。")

    app.close()
    Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
