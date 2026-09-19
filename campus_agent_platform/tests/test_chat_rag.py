"""Agent 对话测试：短期记忆 + RAG 检索（请假/奖学金/学分）。"""

from __future__ import annotations


def test_knowledge_seeded(app):
    n = app.db.execute("SELECT COUNT(*) AS c FROM knowledge_chunks").fetchone()["c"]
    assert n >= 6


def test_ask_leave_question(app):
    """问请假天数审批 → 命中请假制度。"""
    s = app.chat.create_session("S10001", "请假咨询")
    r = app.chat.ask(s["session_id"], "S10001", "请假几天需要找学院领导审批？")
    assert "学院" in r["answer"] or "辅导员" in r["answer"]
    assert r["citations"], "应返回引用"
    assert r["citations"][0]["category"] == "leave"


def test_ask_scholarship_question(app):
    """问奖学金金额 → 命中奖学金制度。"""
    s = app.chat.create_session("S10001", "奖学金")
    r = app.chat.ask(s["session_id"], "S10001", "国家奖学金多少钱？申请条件是什么？")
    assert "奖学金" in r["answer"]
    assert r["citations"][0]["category"] == "scholarship"


def test_ask_credit_question(app):
    """问学分 → 命中学分制度。"""
    s = app.chat.create_session("S10001", "学分")
    r = app.chat.ask(s["session_id"], "S10001", "毕业需要修多少学分？")
    assert "学分" in r["answer"]
    assert r["citations"][0]["category"] == "credit"


def test_short_term_memory(app):
    """多轮对话：第二轮回答应带「我记得您之前问过」。"""
    s = app.chat.create_session("S10001", "记忆测试")
    app.chat.ask(s["session_id"], "S10001", "请假超过几天要找学校领导？")
    r = app.chat.ask(s["session_id"], "S10001", "那奖学金怎么评？")
    # memory_turns >= 2 表示带上了上一轮
    assert r["memory_turns"] >= 2
    history = app.chat.history(s["session_id"])
    assert len(history) == 4  # 2 user + 2 assistant


def test_no_result_graceful(app):
    """无关问题 → 友好兜底，不报错。"""
    s = app.chat.create_session("S10001", "闲聊")
    r = app.chat.ask(s["session_id"], "S10001", "量子力学和弦理论哪个更优美？")
    assert r["citations"] == []
    assert "抱歉" in r["answer"]


def test_session_isolation(app):
    """不同用户不能访问对方会话。"""
    s = app.chat.create_session("S10001", "私密")
    app.chat.ask(s["session_id"], "S10001", "请假要几天？")
    # S10002 历史查不到这条会话的消息（chat.history 本身不过滤，但 list_sessions 按 user）
    sessions = app.chat.list_sessions("S10002")
    assert s["session_id"] not in [x["session_id"] for x in sessions]


def test_followup_anaphora_retrieves_leave_policy(app):
    """回归：指代性追问（「到后天结束」）应结合上一轮记忆检索到请假制度，
    而不是跑偏命中《场地预约管理办法》。"""
    s = app.chat.create_session("S10001", "指代测试")
    app.chat.ask(s["session_id"], "S10001", "我要请两天病假，身体不舒服，从明天开始")
    r = app.chat.ask(s["session_id"], "S10001", "到后天结束")
    assert r["citations"], "指代性追问应命中制度条文"
    assert r["citations"][0]["category"] == "leave"
    assert "请假" in r["answer"]


def test_get_date_tool_returns_today(app):
    """日期工具：LLM 输出 {action:get_date} 时返回今天的日历日期。"""
    from datetime import date as _date
    chat = app.chat
    chat.user_id = "S10001"
    msg = chat._maybe_run_tool('{"action":"get_date"}')
    today = _date.today()
    weekday_cn = "一二三四五六日"[today.weekday()]
    assert today.isoformat() in msg
    assert f"星期{weekday_cn}" in msg


def test_submit_action_becomes_form_draft_not_direct_submit(app):
    """回归：LLM 输出 submit_leave action 时，应转为对话内表单草稿，
    而不是像旧版那样直接调审批引擎提交。"""
    chat = app.chat
    chat.user_id = "S10001"
    raw = '{"action":"submit_leave","start_date":"2026-10-01","end_date":"2026-10-03","reason":"病假"}'
    msg = chat._maybe_run_tool(raw)
    draft = chat._pending_draft
    assert draft is not None, "action 应产出表单草稿"
    assert draft["process_type"] == "leave"
    assert draft["fields"]["start_date"] == "2026-10-01"
    assert draft["fields"]["end_date"] == "2026-10-03"
    assert draft["fields"]["leave_type"] == "sick"
    assert "表单" in msg
    # 关键：没有直接提交申请
    cnt = app.db.execute("SELECT COUNT(*) c FROM approval_requests").fetchone()["c"]
    assert cnt == 0, "action 不应直接产生申请单"


def test_form_draft_persists_in_history(app):
    """表单草稿随助手消息落库，history 可取回（刷新页面不丢）。"""
    chat = app.chat
    s = chat.create_session("S10001", "草稿落库测试")
    # 模拟 LLM 经 _maybe_run_tool 产出的草稿，ask 应随助手消息落库并原样返回
    chat._pending_draft = {
        "process_type": "leave",
        "fields": {"leave_type": "sick", "start_date": "2026-10-01",
                   "end_date": "2026-10-03", "reason": "病假"},
    }
    r = chat.ask(s["session_id"], "S10001", "我要请假")
    assert r["form_draft"]["process_type"] == "leave"

    hist = chat.history(s["session_id"])
    assert len(hist) == 2
    assistant_msg = [m for m in hist if m["role"] == "assistant"][0]
    assert assistant_msg["form_draft"] == {
        "process_type": "leave",
        "fields": {"leave_type": "sick", "start_date": "2026-10-01",
                   "end_date": "2026-10-03", "reason": "病假"},
    }
