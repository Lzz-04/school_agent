"""对话 Agent：短期记忆（DB 存最近 N 轮）+ RAG 检索 + 规则回答。

预留 LLM 接口：`_generate_with_llm` 是真实大模型生成的位置，
当前用规则模板兜底，保证毕设可离线演示。
"""

from __future__ import annotations

import json
import re
import time
import uuid

from ..storage.database import Database
from .retriever import Retriever

MAX_MEMORY_TURNS = 10  # 短期记忆：带最近 10 条（5 轮对话）


def _next_weekday(base, weekday: int):
    """今天起下一个 weekday（周一=0）；若今天就是该天则取 7 天后（下周）。"""
    from datetime import timedelta
    days = (weekday - base.weekday()) % 7
    if days == 0:
        days = 7
    return base + timedelta(days=days)


def _extract_action_json(raw: str) -> dict | None:
    """从 LLM 文本提取第一个 {"action": ...} JSON 对象。

    括号平衡扫描 + 字符串状态机，容错：
    - JSON 前后有自然语言说明文字；
    - JSON 内 reason 含花括号/引号等；
    - 输出多个 JSON 块时只取第一个。
    """
    m = re.search(r'\{\s*"action"\s*:\s*"([a-z_]+)"', raw)
    if not m:
        return None
    start = m.start()
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except Exception:
                    return None
    return None


class ChatAgent:
    def __init__(self, db: Database, retriever: Retriever | None = None, engine=None, user_id: str = ""):
        self.db = db
        self.retriever = retriever or Retriever(db)
        self.engine = engine          # 对话工具：审批引擎（提交请假等）
        self.user_id = user_id        # 当前学生（由 ask 调用时覆盖）
        self._pending_draft: dict | None = None  # 当轮 LLM 产出的申请表单草稿

    def _role_of(self, user_id: str) -> str | None:
        """查用户角色；DB 无记录返回 None。"""
        row = self.db.execute(
            "SELECT role FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        return row["role"] if row else None

    # ------------------------------------------------------------------
    def create_session(self, user_id: str, title: str = "") -> dict:
        sid = "S-" + uuid.uuid4().hex[:12].upper()
        self.db.execute(
            "INSERT INTO chat_sessions (session_id, user_id, title, created_at) VALUES (?,?,?,?)",
            (sid, user_id, title or "新对话", time.time()),
        )
        self.db.commit()
        return {"session_id": sid, "user_id": user_id, "title": title}

    def list_sessions(self, user_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT session_id, title, created_at FROM chat_sessions WHERE user_id=? "
            "ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, session_id: str, user_id: str) -> bool:
        """删除会话及其全部消息。返回是否真的删了。"""
        row = self.db.execute(
            "SELECT user_id FROM chat_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if row is None:
            return False
        if row["user_id"] != user_id:
            return False
        self.db.execute("DELETE FROM chat_messages WHERE session_id=?", (session_id,))
        self.db.execute("DELETE FROM chat_sessions WHERE session_id=?", (session_id,))
        self.db.commit()
        return True

    def history(self, session_id: str) -> list[dict]:
        rows = self.db.execute(
            "SELECT id, role, content, attachments, form_draft, created_at FROM chat_messages WHERE session_id=? "
            "ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["attachments"] = json.loads(d.get("attachments") or "[]")
            d["form_draft"] = json.loads(d.get("form_draft") or "{}")
            out.append(d)
        return out

    # ------------------------------------------------------------------
    def ask(self, session_id: str, user_id: str, question: str,
            attachments: list[dict] | None = None) -> dict:
        """attachments: [{"url": "...", "name": "...", "type": "image/file"}]"""
        attachments = attachments or []
        self.user_id = user_id
        # 1. 短期记忆：取最近 N 条
        recent = self.db.execute(
            "SELECT role, content, attachments FROM chat_messages WHERE session_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (session_id, MAX_MEMORY_TURNS),
        ).fetchall()
        memory = [{"role": r["role"], "content": r["content"]} for r in reversed(recent)]

        # 2. RAG 检索：融合短期记忆（最近 1~2 条用户问题）+ 当前问题，
        #    解决「到后天结束」这类指代性追问检索跑偏（如误命中场地制度）的问题
        query = question
        if attachments:
            names = " ".join(a.get("name", "") for a in attachments)
            query = f"{question} {names}"
        prev_user_qs = [
            m["content"] for m in memory
            if m["role"] == "user" and m["content"].strip() != question.strip()
        ][-2:]
        if prev_user_qs:
            query = " ".join(prev_user_qs + [query]).strip()
        hits = self.retriever.retrieve(query, top_k=3)

        # 3. 生成回答（LLM 可能产出申请表单草稿 _pending_draft）
        # 【关键词直触】辅导员说自动审核/批量审批，直接跑工具，不等 LLM 决策
        if self._role_of(user_id) == "counselor" and any(k in question for k in ("自动审核", "批量审批", "自动审批", "审一下待办", "审核待办", "帮我审")):
            answer = self._run_auto_review()
            cited = []
        else:
            answer, cited = self._generate(question, memory, hits, attachments)
        draft = self._pending_draft
        self._pending_draft = None

        # 4. 落库：用户消息 + 助手消息（表单草稿随助手消息保存）
        now = time.time()
        self.db.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, retrieved_chunks, attachments, created_at, form_draft) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("M" + uuid.uuid4().hex[:12].upper(), session_id, "user", question, "[]",
             json.dumps(attachments, ensure_ascii=False), now, "{}"),
        )
        self.db.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, retrieved_chunks, attachments, created_at, form_draft) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("M" + uuid.uuid4().hex[:12].upper(), session_id, "assistant", answer,
             json.dumps(cited, ensure_ascii=False), "[]", now + 0.001,
             json.dumps(draft or {}, ensure_ascii=False)),
        )
        self.db.commit()

        return {
            "answer": answer,
            "citations": cited,
            "memory_turns": len(memory),
            "form_draft": draft,
        }

    # ------------------------------------------------------------------
    def _generate(self, question: str, memory: list[dict], hits: list[dict],
                  attachments: list[dict] | None = None) -> tuple[str, list[dict]]:
        """优先调 LLM 生成；未配置或调用失败时回退规则模板。"""
        cited = [
            {"chunk_id": h["chunk_id"], "title": h["title"], "category": h["category"]}
            for h in hits
        ]

        # 1. 配了 LLM key 就走大模型
        from ..llm import get_llm
        llm = get_llm()
        if llm.enabled:
            try:
                answer = self._generate_with_llm(question, memory, hits, attachments or [])
                return answer, cited
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("LLM 调用失败，回退规则模板: %s", e)

        # 2. 规则模板兜底
        if not hits:
            return (
                "抱歉，我在学校规章制度库里没有检索到与您问题直接相关的条文。"
                "您可以换个问法（例如「请假几天要找学院」「奖学金多少钱」），"
                "或联系辅导员/教务处咨询。",
                [],
            )

        top = hits[0]
        lines = [f"根据《{top['title']}》：", "", top["content"]]
        if len(hits) > 1:
            lines.append("")
            lines.append(f"另可参考：{ '、'.join(h['title'] for h in hits[1:]) }")
        if memory:
            user_prev = [m["content"] for m in memory if m["role"] == "user"]
            if user_prev and user_prev[-1].strip() != question.strip():
                # 结合上一轮用户问题组织回答，体现短期记忆对上下文的影响
                lines.insert(0, f"结合您之前说的「{user_prev[-1]}」，为您整理如下：")
                lines.insert(1, "")
        return "\n".join(lines), cited

    def _generate_with_llm(self, question: str, memory: list[dict], hits: list[dict],
                           attachments: list[dict]) -> str:
        """调大模型：制度片段 + 对话历史 + 图片 → 自然语言回答。"""
        import base64
        from pathlib import Path as _Path
        from ..llm import get_llm
        from datetime import date as _date

        # 【日期工具】注入当前日期与相对时间推算基准，避免"明天/下周"推算错误与年份幻觉
        from datetime import timedelta as _td
        today = _date.today()
        weekday_cn = "一二三四五六日"[today.weekday()]
        nw3 = _next_weekday(today, 2).isoformat()   # 示例：下周三
        nw5 = _next_weekday(today, 4).isoformat()   # 示例：下周五
        tmw = (today + _td(days=1)).isoformat()
        tmw2 = (today + _td(days=2)).isoformat()
        tmw3 = (today + _td(days=3)).isoformat()
        date_hint = (
            f"今天是 {today.isoformat()}（星期{weekday_cn}）。\n"
            "【相对时间推算规则，以此为准，禁止自行猜测】\n"
            f"- 明天={tmw}，后天={tmw2}，昨天={(today - _td(days=1)).isoformat()}；\n"
            "- 本周X = 本周一之后最近的星期X；下周X = 从下个周一开始那一周的星期X；\n"
            f"- 示例（今天{today.isoformat()}）：「下周三」={nw3}，「下周五」={nw5}；\n"
            "- 用户给出具体日期（如 10月1日、2023年5月1日）时直接采用，不套用相对规则；\n"
            f"- 年份缺失或早于今年（{today.year}）的日期，一律按今年处理，仍是请假申请，不要当作历史事件跳过。"
        )

        # 查当前用户角色：辅导员可见自动审核能力
        _role = self._role_of(self.user_id) or "student"
        counselor_hint = ""
        if _role == "counselor":
            counselor_hint = (
                "\n【辅导员权限】仅当当前用户是辅导员、且辅导员明确要求「自动审核/批量审批/帮我审一下待办」时，"
                "单独输出一行 JSON（不要包在代码块里）：\n"
                '    {"action":"auto_review"}\n'
                "输出后用一句话告知「正在为您自动审核待办请假单」。学生身份绝不输出此 JSON。\n"
            )
        system = (
            "你是大学校园助手，既能回答制度问题，也能帮学生发起请假申请。\n"
            f"【当前日期】\n{date_hint}\n"
            "【制度问答】只能依据下方「制度条文」回答，不要编造条文里没有的数字；"
            "条文没有就说不清楚并建议联系辅导员/教务处。\n"
            "【请假申请】当学生明确表达要请假（病假/事假/丧假等）时：\n"
            "  - 开始日期、结束日期、请假原因 三者齐备才输出 JSON；缺任一 → 先追问，绝不输出 JSON；\n"
            '  - JSON 必须单独一行、不要包在代码块里，格式：{"action":"submit_leave","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","reason":"病假"}\n'
            "  - reason 从学生原话提取（病假/事假/丧假/个人原因等）；\n"
            "  - 输出 JSON 的同时，用一句话告知「已为您预填请假申请表单，请核对」。\n"
            "【JSON 输出示例（假设今天2026-09-19周六）】\n"
            f'学生说：我要请病假，下周三到下周五 → 输出 {{"action":"submit_leave","start_date":"{nw3}","end_date":"{nw5}","reason":"病假"}}\n'
            f'学生说：2023年10月20日到10月22日请病假 → 输出 {{"action":"submit_leave","start_date":"{today.year}-10-20","end_date":"{today.year}-10-22","reason":"病假"}}\n'
            f'学生说：明天开始请3天事假 → 输出 {{"action":"submit_leave","start_date":"{tmw}","end_date":"{tmw3}","reason":"事假"}}\n'
            "【不要这样】\n"
            "学生说：我想请个假 → 缺日期与原因，先追问，不输出 JSON；\n"
            "学生说：9月25号到26号请假 → 缺原因，先追问，不输出 JSON；\n"
            "学生说：请问奖学金怎么申请 → 制度问答，不输出 JSON；\n"
            "学生说：帮我选一下高数课 → 选课需求，不输出 JSON；\n"
            "学生说：昨天开始请事假 → 开始日期早于今天，不输出 JSON，提示日期不合法；\n"
            "其他请求（选课、报销、场地）不要输出 JSON，正常回答即可。\n"
            f"{counselor_hint}回答用中文，简洁分点，不要引用检索过程。"
        )
        if hits:
            context = "\n\n".join(f"《{h['title']}》：{h['content']}" for h in hits)
        else:
            context = "（未检索到相关条文）"

        # 把图片附件转成 base64 data URL（视觉模型可读）
        uploads_dir = _Path(__file__).resolve().parent.parent / "uploads"
        image_b64 = []
        for a in attachments:
            if a.get("type") != "image":
                continue
            fname = _Path(a["url"]).name
            fpath = uploads_dir / fname
            if not fpath.exists():
                continue
            ext = fpath.suffix.lstrip(".").lower()
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}.get(ext, "jpeg")
            b64 = base64.b64encode(fpath.read_bytes()).decode("ascii")
            image_b64.append(f"data:image/{mime};base64,{b64}")

        messages = []
        for m in memory[-8:]:
            role = "user" if m["role"] == "user" else "assistant"
            messages.append({"role": role, "content": m["content"]})

        text_part = f"制度条文：\n{context}\n\n学生问题：{question}"
        if image_b64:
            content = [{"type": "text", "text": text_part}]
            for url in image_b64:
                content.append({"type": "image_url", "image_url": {"url": url}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": text_part})
        raw = get_llm().chat(system, messages, timeout=60.0)
        return self._maybe_run_tool(raw)

    def _maybe_run_tool(self, raw: str) -> str:
        """从 LLM 回复里抽取 action JSON，转为对话内可编辑的申请表单草稿。

        不再直接调审批引擎提交——LLM 给出完整请假信息后，系统在对话流里
        弹出预填表单，学生核对/修改后由前端点「提交」才真正提交。
        本层做确定性兜底：角色校验 + 日期合法性，不依赖 LLM 自觉。
        """
        if not self.engine or self.user_id in (None, ""):
            return raw
        data = _extract_action_json(raw)
        if not data:
            return raw

        if data.get("action") == "get_date":
            # 【日期工具】LLM 不确定今天日期时可调用，返回当前日历日期
            from datetime import date as _date
            today = _date.today()
            weekday_cn = "一二三四五六日"[today.weekday()]
            return f"今天是 {today.isoformat()}（星期{weekday_cn}）。"

        if data.get("action") == "auto_review":
            # 【自动审核工具】安全兜底：仅辅导员可执行（LLM 输出不受信任）
            if self._role_of(self.user_id) != "counselor":
                return "抱歉，只有辅导员可以执行自动审核。如需审核请假单，请联系辅导员。"
            return self._run_auto_review()

        if data.get("action") != "submit_leave":
            return raw

        from ..tools.leave_tool import _to_date
        from datetime import date as _date
        try:
            start = _to_date(data.get("start_date", ""))
            end = _to_date(data.get("end_date", ""))
        except Exception:
            # 日期归一化失败：不弹表单，让学生继续在对话里补
            return raw

        # 年份幻觉校正：早于今年（如 2023）一律按今年处理
        _now_year = _date.today().year
        if int(start[:4]) < _now_year:
            start = f"{_now_year}{start[4:]}"
        if int(end[:4]) < _now_year:
            end = f"{_now_year}{end[4:]}"

        # 日期合法性校验（代码层保证，不依赖 LLM 判断）
        try:
            ds = _date.fromisoformat(start)
            de = _date.fromisoformat(end)
        except ValueError:
            return "请假日期格式不正确，请重新告诉我起止日期（例如：10月1日到10月3日）。"
        if de < ds:
            return "结束日期不能早于开始日期，请核对后再告诉我。"
        if ds < _date.today():
            return "开始日期早于今天，不能提交过去日期的请假申请，请重新确认请假时间。"

        reason = (data.get("reason") or "个人原因").strip() or "个人原因"
        self._pending_draft = {
            "process_type": "leave",
            "fields": {
                "leave_type": "sick" if "病" in reason else "personal",
                "start_date": start,
                "end_date": end,
                "reason": reason,
            },
        }
        return (
            "已根据您的描述为您预填了请假申请表单，请核对下面的起止时间与事由，"
            "确认无误后点击「提交申请」；如需修改可直接在表单里编辑。"
        )

    def _run_auto_review(self) -> str:
        """按规则自动审核当前辅导员的待办请假单，返回自然语言摘要。"""
        from ..workflows import rules as R
        approver = self.user_id
        all_reqs = self.engine.requests.list_all()
        approves, rejects, skipped = [], [], []
        for r in all_reqs:
            if r.process_type != "leave":
                continue
            if r.status != "pending_counselor":
                continue
            violations, days = R.evaluate_leave_auto_review(
                r.payload or {}, r.attachment_urls or []
            )
            if days > 7:
                skipped.append((r.request_no, f"请假{days}天需学校领导审"))
                continue
            if violations:
                try:
                    self.engine.advance(request_no=r.request_no, approver_id=approver,
                                        decision="reject", comment="自动驳回：" + "；".join(violations))
                    rejects.append((r.request_no, violations))
                except Exception as e:
                    skipped.append((r.request_no, str(e)))
                continue
            try:
                self.engine.advance(request_no=r.request_no, approver_id=approver,
                                     decision="approve", comment="自动通过：符合规则")
                approves.append(r.request_no)
            except Exception as e:
                skipped.append((r.request_no, str(e)))
        parts = [f"自动审核完成：通过 {len(approves)} 条，驳回 {len(rejects)} 条，跳过 {len(skipped)} 条。"]
        if approves:
            parts.append("通过单号：" + "、".join(approves))
        for no, vs in rejects:
            parts.append(f"驳回 {no}：" + "；".join(vs))
        for no, why in skipped:
            parts.append(f"跳过 {no}：{why}")
        return "\n".join(parts)
