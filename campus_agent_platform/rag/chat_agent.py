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
from .form_validators import _ACTION_TO_SPEC, FORM_SPECS, form_prompt_section
from .retriever import Retriever

MAX_MEMORY_TURNS = 10  # 短期记忆：带最近 10 条（5 轮对话）

# 日期/时间表达检测：直触关键词（我要请假/我要预约等）只在"无实质信息"时生效；
# 一旦问题含日期/时间（明天/周X/月X日/下午X点…），必须走 LLM 完整抽取 + 代码层校验，
# 避免直触截胡完整请求、丢失日期原因或绕过过去日期拦截。
_HAS_DATETIME_RE = re.compile(
    r"(今天|明天|后天|昨天|前天|下周|本周|下个|周[一二三四五六日]|星期[一二三四五六日]|"
    r"月\d+[日号]?|\d+[日号]|\d+天|上午|下午|晚上|\d+点|大后天)",
)

# 课程口语别名：直触预选时的中文口语归一（高数=高等数学 等）
_COURSE_ALIASES = {
    "高数": "高等数学",
    "程序设计": "程序设计基础",
    "物理": "大学物理",
    "艺术": "艺术鉴赏",
    "数据结构": "数据结构",
}


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


# ----------------------------------------------------------------------
# 流程无关的表单契约（4 个校验函数 / FORM_SPECS / 提示词段落）已拆至 form_validators.py。
# 对话管道统一入口：_maybe_run_tool 查 _ACTION_TO_SPEC → spec["validate"](data)。
# 新增流程类型只需在 form_validators.py 登记 action / 校验函数 / 提示文本，本文件无需改动。
# ----------------------------------------------------------------------


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
        elif any(k in question for k in ("有哪些课", "有什么课", "可选课程", "课程目录", "哪些选修课", "看看课", "有什么选修", "哪些课可选")):
            answer = self._run_list_courses()
            cited = []
        elif self._match_named_course(question):
            # 点名具体课程（含"选"动词 + 课程名/课号/口语别名命中）→ 确定性预选，不走 LLM
            from ..workflows import rules as R
            picked = self._match_named_course(question)
            self._pending_draft = {"process_type": "course_selection", "fields": {"course_ids": picked}}
            names = "、".join(R.COURSE_CATALOG[c]["name"] for c in picked)
            answer = f"已为您预选：{names}。请在下方核对/增删课程后点「提交申请」（满员课程自动不可选）。"
            cited = []
        elif any(k in question for k in ("我要选课", "我想选课", "我要选", "帮我选课", "我想选", "选选修课", "要选课")) and not _HAS_DATETIME_RE.search(question):
            # 直接弹出选课卡片（按课程名勾选），不再文字追问；点名的课程自动预选
            from ..workflows import rules as R
            picked = self._match_named_course(question)
            self._pending_draft = {"process_type": "course_selection", "fields": {"course_ids": picked} if picked else {}}
            if picked:
                names = "、".join(R.COURSE_CATALOG[c]["name"] for c in picked)
                answer = f"已为您预选：{names}。请在下方核对/增删课程后点「提交申请」（满员课程自动不可选）。"
            else:
                answer = "请在下方勾选要选的课程（显示课程名/教师/地点/时间/剩余名额，满员自动不可选），选好后点「提交申请」即可。"
            cited = []
        elif any(k in question for k in ("有哪些场地", "哪些场地", "场地目录", "可预约什么", "能预约什么", "看看场地", "场地列表", "有哪些教室", "哪些教室")):
            answer = "🏫 以下是当前可预约的场地，点卡片即可直接预约："
            self._pending_draft = {"process_type": "venue_catalog", "fields": {}}
            cited = []
        elif any(k in question for k in ("我要预约", "我想预约", "我要订", "帮我预约", "要预约", "我要借", "想预约场地")) and not _HAS_DATETIME_RE.search(question):
            # 直接弹出场地卡片（按具体场地勾选），不再文字追问；点名的场地自动预选。
            # 注意：问题含日期/时间（如"预约活动中心301 明天下午2点…"）时不下沉到这里，
            # 必须走 LLM 完整抽取 + 代码层校验（时间倒挂/过去日期/缺人数用途均有确定性拦截）。
            from ..workflows import rules as R
            picked = ""
            for vid, v in R.VENUE_CATALOG.items():
                if v["name"] in question:
                    picked = vid
                    break
            if not picked:
                type_cn = {"教室": "classroom", "活动室": "activity_room", "报告厅": "lecture_hall", "机房": "computer_lab"}
                for cn, en in type_cn.items():
                    if cn in question:
                        matches = [vid for vid, v in R.VENUE_CATALOG.items() if v["type"] == en]
                        if matches:
                            picked = matches[0]
                        break
            self._pending_draft = {"process_type": "venue_reservation", "fields": {"venue_id": picked} if picked else {}}
            if picked:
                v = R.VENUE_CATALOG[picked]
                mark = "提交即通过" if v["type"] in R.VENUE_TYPES_AUTO_APPROVE else "需后勤审核"
                answer = f"已为您预选：{v['name']}（{mark}）。请在下方补充时间、人数和用途后点「提交申请」。"
            else:
                answer = "请在下方选择场地（显示名称/容量/审批方式），并补充时间、人数和用途后点「提交申请」。"
            cited = []
        elif any(k in question for k in ("我要请假", "我想请假", "帮我请假", "请病假", "请事假", "想请假", "请个假", "请假两天", "请假一天", "我要请")) and not _HAS_DATETIME_RE.search(question):
            # 纯请假意图（无日期/原因）→ 弹请假卡片引导填写；
            # 含日期时间（如"我要请病假，明天开始3天"）→ 走 LLM 完整抽取 + 代码层日期校验。
            leave_type = "sick" if "病" in question else "personal"
            self._pending_draft = {"process_type": "leave", "fields": {"leave_type": leave_type}}
            type_cn = "病假" if leave_type == "sick" else "事假"
            answer = f"已为您选择{type_cn}。请在下方选择起止日期并填写事由后点「提交申请」（病假建议上传证明图片）。"
            cited = []
        elif self._role_of(user_id) == "admin" and any(k in question for k in ("导入学生", "批量添加学生", "添加账号", "导入名单")) and re.search(r"\d{6,12}", question):
            # 管理员导入学生：名单里含学号 → 确定性正则解析，不依赖 LLM 输出 JSON
            answer = self._run_import_students_from_text(question)
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

        # 查当前用户角色：辅导员可见自动审核能力；管理员可见导入学生能力
        _role = self._role_of(self.user_id) or "student"
        counselor_hint = ""
        admin_hint = ""
        if _role == "counselor":
            counselor_hint = (
                "\n【辅导员权限】仅当当前用户是辅导员、且辅导员明确要求「自动审核/批量审批/帮我审一下待办」时，"
                "单独输出一行 JSON（不要包在代码块里）：\n"
                '    {"action":"auto_review"}\n'
                "输出后用一句话告知「正在为您自动审核待办请假单」。学生身份绝不输出此 JSON。\n"
            )
        if _role == "admin":
            admin_hint = (
                "\n【管理员权限】当管理员要求「导入学生/批量添加学生/添加账号」并给出学生名单时，"
                "把学生信息解析成 JSON 数组，单独一行输出（不要包在代码块里）：\n"
                '    {"action":"import_students","students":[{"username":"20240001","name":"张三","email":"","password":"","class_name":"2024级软件工程01班"}]}\n'
                "字段：username=学号/登录账号（必填），name=姓名，email=邮箱（可空），password=密码（可空则默认123456），"
                "class_name=班级全名（如2024级软件工程01班，可空）。输出后用一句话告知「正在导入学生」。\n"
                "管理员在对话里还可以：查询学生/班级、查看审核情况等，正常回答即可。\n"
            )
        student_hint = ""
        if _role == "student":
            student_hint = "\n【学生限制】学生端不支持报销，绝不输出 submit_reimbursement JSON；被问报销时回复：学生端暂不支持报销，请联系辅导员或财务处。\n"
        system = (
            "你是大学校园助手，既能回答制度问题，也能帮学生发起各类申请（请假/选课/场地预约）。\n"
            f"【当前日期】\n{date_hint}\n"
            "【意图判断·优先级】用户表达申请动作（请假/选课/预约/报销/导入学生）且信息足够时，"
            "优先输出对应表单 JSON；只有当用户询问制度/规则/条件（如「…是什么」「…怎么申请」「…标准」）"
            "时才做制度问答。申请意图绝不答制度条文。\n"
            "【制度问答】只能依据下方「制度条文」回答，不要编造条文里没有的数字；"
            "条文没有就说不清楚并建议联系辅导员/教务处。\n"
            "【多轮对话】若用户上一轮已表达申请意图（如「我要请假/选课/预约」），"
            "本轮补充日期/原因/人数等信息时，直接输出对应表单 JSON；不要重新询问，也不要做制度问答。\n"
            "【请假相对日期示例（假设今天2026-09-19周六）】\n"
            f'学生说：我要请病假，下周三到下周五 → 输出 {{"action":"submit_leave","start_date":"{nw3}","end_date":"{nw5}","reason":"病假"}}\n'
            f'学生说：2023年10月20日到10月22日请病假 → 输出 {{"action":"submit_leave","start_date":"{today.year}-10-20","end_date":"{today.year}-10-22","reason":"病假"}}\n'
            f'学生说：明天开始请3天事假 → 输出 {{"action":"submit_leave","start_date":"{tmw}","end_date":"{tmw3}","reason":"事假"}}\n'
            "【选课示例】\n"
            f'学生说：帮我选 CS101 和 MATH101 → 输出 {{"action":"submit_course_selection","course_ids":["CS101","MATH101"]}}\n'
            "【场地预约示例】\n"
            f'学生说：预约活动中心301 明天下午2点到4点，30人，班级团建 → 输出 {{"action":"submit_venue_reservation","venue_id":"V101","start_time":"{tmw} 14:00","end_time":"{tmw} 16:00","purpose":"班级团建","participants":30}}\n'
            f"{form_prompt_section()}"
            f"{counselor_hint}{admin_hint}{student_hint}回答用中文，简洁分点，不要引用检索过程。"
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
        llm = get_llm()
        try:
            raw = llm.chat(system, messages, timeout=90.0)
        except Exception:
            # 瞬时超时/失败：重试一次；仍失败由 _generate 回退规则模板（降级不丢可用性）
            time.sleep(1.0)
            raw = llm.chat(system, messages, timeout=90.0)
        return self._maybe_run_tool(raw)

    def _maybe_run_tool(self, raw: str) -> str:
        """从 LLM 回复里抽取 action JSON，转为对话内可编辑的申请表单草稿。

        不再直接调审批引擎提交——LLM 给出完整申请信息后，系统在对话流里
        弹出预填表单，学生核对/修改后由前端点「提交」才真正提交。
        本层做确定性兜底：角色校验 + 字段合法性（FORM_SPECS 校验器），
        不依赖 LLM 自觉。新增流程类型只改 FORM_SPECS，管道不变。
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

        if data.get("action") == "import_students":
            if self._role_of(self.user_id) != "admin":
                return "抱歉，只有管理员可以导入学生。"
            return self._run_import_students(data.get("students") or [])

        if data.get("action") == "list_courses":
            # 课程目录查询：任何角色可问
            return self._run_list_courses()

        if data.get("action") == "list_venues":
            # 场地目录查询：任何角色可问
            return self._run_list_venues()

        if data.get("action") == "submit_reimbursement" and self._role_of(self.user_id) == "student":
            # 【报销权限确定性兜底】学生端禁报销（与引擎 submit 403 一致）：
            # 即使 LLM 输出报销 JSON，也在草稿层拦截，不依赖 LLM 自觉。
            return "学生端暂不支持报销，请联系辅导员或财务处。"

        # 表单类 action：查 FORM_SPECS 通用管道
        entry = _ACTION_TO_SPEC.get(data.get("action"))
        if entry is None:
            return raw
        process_type, spec = entry
        fields, err = spec["validate"](data)
        if fields is None:
            # err 为空 = 无法处理，原样返回 LLM 文本；否则返回明确提示让用户补充
            return raw if err is None else err
        self._pending_draft = {"process_type": process_type, "fields": fields}
        return spec["draft_msg"]

    _WEEKDAY_CN = {"Mon": "周一", "Tue": "周二", "Wed": "周三", "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日"}

    def _match_named_course(self, question: str) -> list[str]:
        """q 含「选」动词且点名课程（目录名/课号/口语别名命中）时，返回匹配的课程号列表。

        确定性预选：选课这类高频、结构化意图不经 LLM，直接从文本匹配课程。
        口语别名（高数→高等数学）由模块级 _COURSE_ALIASES 归一，匹配失败返回空列表。
        """
        if "选" not in question:
            return []
        from ..workflows import rules as R
        picked: list[str] = []
        for cid, c in R.COURSE_CATALOG.items():
            if c["name"] in question or cid in question.upper():
                picked.append(cid)
        if not picked:
            for alias, name in _COURSE_ALIASES.items():
                if alias in question:
                    for cid, c in R.COURSE_CATALOG.items():
                        if c["name"] == name:
                            picked.append(cid)
                    break
        return picked

    def _run_import_students_from_text(self, question: str) -> str:
        """管理员导入学生：从问题文本确定性解析「学号+姓名」名单，不走 LLM。

        支持「导入学生：20240001 张三、20240002 李四」这类带学号的名单，
        学号 6~12 位数字；姓名缺失时留空由 AuthService 校验。
        """
        pairs = re.findall(r"(\d{6,12})\s*([\u4e00-\u9fa5]{1,8})?", question)
        students = [
            {"username": no, "name": name or "", "email": "", "password": "", "class_name": ""}
            for no, name in pairs
        ]
        return self._run_import_students(students)

    def _run_list_courses(self) -> str:
        """对话查询全部可选选修课：课程名/教师/地点/时间/剩余名额。"""
        from ..workflows import rules as R
        lines = [f"📚 本学期可选选修课（共 {len(R.COURSE_CATALOG)} 门）："]
        for cid, c in R.COURSE_CATALOG.items():
            remain = c["quota"] - R.COURSE_ENROLLMENT.get(cid, 0)
            sched = c["schedule"]
            for en, cn in self._WEEKDAY_CN.items():
                sched = sched.replace(en, cn)
            lines.append(
                f"  {c['name']}（{cid}）｜教师：{c.get('teacher', '-')}｜地点：{c.get('location', '-')}"
                f"｜时间：{sched}｜剩余名额：{remain}/{c['quota']}"
            )
        lines.append("直接告诉我课程名称即可为您选课，例如：「我要选程序设计基础和艺术鉴赏」。")
        return "\n".join(lines)

    def _run_list_venues(self) -> str:
        """对话查询全部可预约场地：名称/地点/容量/审批方式。"""
        from ..workflows import rules as R
        lines = [f"🏫 可预约场地（共 {len(R.VENUE_CATALOG)} 个）："]
        for vid, v in R.VENUE_CATALOG.items():
            auto = v["type"] in R.VENUE_TYPES_AUTO_APPROVE
            mark = "提交即通过" if auto else "需后勤审核"
            lines.append(
                f"  {v['name']}（{vid}）｜{v['location']}｜容量 {v['capacity']} 人｜{mark}"
            )
        lines.append("直接告诉我场地名称和时间即可预约，例如：「我要预约 活动中心301，明天下午2点到4点」。")
        return "\n".join(lines)

    def _run_import_students(self, students: list) -> str:
        """管理员对话导入学生：解析名单并调用 auth.add_students。"""
        if not students:
            return "未识别到学生信息，请按「学号 姓名 邮箱」格式提供名单。"
        # 匹配班级
        rows = self.db.execute("SELECT class_id, grade, major, name FROM classes").fetchall()
        class_map = {f"{r['grade']}级{r['major']}{r['name']}": r["class_id"] for r in rows}
        norm = []
        for s in students:
            username = (s.get("username") or "").strip()
            if not username:
                continue
            class_name = (s.get("class_name") or "").strip()
            norm.append({
                "username": username,
                "name": (s.get("name") or "").strip(),
                "email": (s.get("email") or "").strip(),
                "password": (s.get("password") or "").strip(),
                "class_id": class_map.get(class_name, ""),
            })
        if not norm:
            return "未识别到有效学生（缺少学号）。"
        auth = self.engine.auth if hasattr(self.engine, "auth") else None
        # 直接走数据库：调用 AuthService.add_students
        from ..auth.service import AuthService
        svc = AuthService(self.db)
        result = svc.add_students(norm)
        created = result.get("created", [])
        skipped = result.get("skipped", [])
        lines = [f"✅ 成功导入 {len(created)} 人"]
        for c in created[:10]:
            lines.append(f"  - 学号 {c.get('username')}（{c.get('name') or '未填姓名'}）")
        if skipped:
            lines.append(f"⚠️ 跳过 {len(skipped)} 人（已存在或缺少学号）")
            for sk in skipped[:5]:
                stu = sk.get("student")
                if isinstance(stu, dict):
                    stu_label = f"学号 {stu.get('username') or '未知'}（{stu.get('name') or '未填姓名'}）"
                else:
                    stu_label = str(stu)
                lines.append(f"  - {stu_label}：{sk.get('reason')}")
        return "\n".join(lines)

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
