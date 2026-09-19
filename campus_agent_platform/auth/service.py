"""用户/学生管理服务：登录、改密、管理员增删学生。"""

from __future__ import annotations

import secrets
import time

from ..storage.database import Database
from . import security


class AuthError(Exception):
    def __init__(self, message: str, code: str = "auth_error"):
        super().__init__(message)
        self.message = message
        self.code = code


class AuthService:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    def seed_admin(self, admin_id: str = "admin", password: str = "admin123") -> None:
        """首次启动种子管理员。"""
        row = self.db.execute("SELECT user_id FROM users WHERE user_id=?", (admin_id,)).fetchone()
        if row:
            return
        pw_hash, salt = security.hash_password(password)
        self.db.execute(
            "INSERT INTO users (user_id, username, password_hash, salt, role, name, email, status, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (admin_id, admin_id, pw_hash, salt, "admin", "系统管理员", "", "active", time.time()),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> dict:
        row = self.db.execute(
            "SELECT user_id, password_hash, salt, role, name, status FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if row is None:
            raise AuthError("用户不存在", "user_not_found")
        if row["status"] != "active":
            raise AuthError("账号已被禁用", "user_disabled")
        if not security.verify_password(password, row["password_hash"], row["salt"]):
            raise AuthError("密码错误", "wrong_password")
        token = security.issue_token(row["user_id"], row["role"], row["name"])
        return {
            "token": token,
            "user_id": row["user_id"],
            "role": row["role"],
            "name": row["name"],
        }

    # ------------------------------------------------------------------
    def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        if len(new_password) < 6:
            raise AuthError("新密码至少 6 位", "weak_password")
        row = self.db.execute(
            "SELECT password_hash, salt FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        if row is None:
            raise AuthError("用户不存在", "user_not_found")
        if not security.verify_password(old_password, row["password_hash"], row["salt"]):
            raise AuthError("原密码错误", "wrong_old_password")
        pw_hash, salt = security.hash_password(new_password)
        self.db.execute(
            "UPDATE users SET password_hash=?, salt=? WHERE user_id=?",
            (pw_hash, salt, user_id),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    def add_students(self, students: list[dict]) -> dict:
        """管理员批量导入学生。students: [{username, name, email, password?}]"""
        created, skipped = [], []
        for s in students:
            username = (s.get("username") or "").strip()
            if not username:
                skipped.append({"student": s, "reason": "缺少 username"})
                continue
            exists = self.db.execute(
                "SELECT user_id FROM users WHERE username=?", (username,)
            ).fetchone()
            if exists:
                skipped.append({"student": s, "reason": f"{username} 已存在"})
                continue
            user_id = "S" + username[-5:].zfill(5) if username[:1].isalpha() else "S" + username[-5:]
            # 避免 id 冲突
            while self.db.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
                user_id = "S" + secrets.token_hex(3).upper()
            password = s.get("password") or "123456"
            pw_hash, salt = security.hash_password(password)
            self.db.execute(
                "INSERT INTO users (user_id, username, password_hash, salt, role, name, email, status, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (user_id, username, pw_hash, salt, "student", s.get("name", ""),
                 s.get("email", ""), "active", time.time()),
            )
            created.append({"user_id": user_id, "username": username, "name": s.get("name", "")})
        self.db.commit()
        return {"created": created, "skipped": skipped, "count": len(created)}

    # ------------------------------------------------------------------
    def list_students(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT user_id, username, name, email, status, created_at FROM users "
            "WHERE role='student' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    def disable_student(self, user_id: str) -> None:
        self.db.execute(
            "UPDATE users SET status='disabled' WHERE user_id=? AND role='student'",
            (user_id,),
        )
        self.db.commit()

    # ------------------------------------------------------------------
    def get_user(self, user_id: str) -> dict | None:
        row = self.db.execute(
            "SELECT user_id, username, role, name, email, status FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
