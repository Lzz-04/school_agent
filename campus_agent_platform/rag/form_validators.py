"""对话表单校验：LLM 输出 JSON → 代码层确定性校验 → 表单草稿。

从 rag/chat_agent.py 拆出的独立模块（职责单一化）：
- 流程无关的表单契约统一登记在 FORM_SPECS，对话管道无需改动；
- 新增流程类型只需在此登记 action / 校验函数 / 提示文本。

校验函数签名：validate(data: dict) -> (fields: dict | None, error: str | None)
  - fields=None 且 error=None：无法处理，原样返回 LLM 文本（不弹表单）
  - fields=None 且 error 非空：校验失败，返回明确提示让用户在对话里补充

公共辅助（收敛跨表单重复）：
  - _normalize_reason：reason 归一化（去空白 + 兜底默认值），请假/选课/报销共用；
  - _parse_dt_range：场地预约起止时间解析（"%Y-%m-%d %H:%M"）。
"""

from __future__ import annotations

from datetime import date, datetime

from ..tools.leave_tool import _to_date  # 日期归一化统一入口（保留原实现）
from ..workflows import rules as R

# 校验结果类型：成功返回 (fields, None)；失败返回 (None, 错误提示)；无法处理返回 (None, None)
ValidatorResult = tuple[dict | None, str | None]


def _normalize_reason(data: dict, default: str) -> str:
    """表单通用：reason 归一化（去空白，空值兜底为默认文案）。"""
    return (data.get("reason") or default).strip() or default


def _parse_dt_range(start_s: str, end_s: str) -> tuple[datetime, datetime] | None:
    """表单通用：解析 '%Y-%m-%d %H:%M' 起止时间；格式非法返回 None。"""
    try:
        s = datetime.strptime(start_s, "%Y-%m-%d %H:%M")
        e = datetime.strptime(end_s, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return s, e


def _validate_leave(data: dict) -> ValidatorResult:
    try:
        start = _to_date(data.get("start_date", ""))
        end = _to_date(data.get("end_date", ""))
    except Exception:
        return None, None  # 日期归一化失败：不弹表单，让 LLM 继续追问
    # 年份幻觉校正：早于今年（如 2023）一律按今年处理
    _now_year = date.today().year
    if int(start[:4]) < _now_year:
        start = f"{_now_year}{start[4:]}"
    if int(end[:4]) < _now_year:
        end = f"{_now_year}{end[4:]}"
    try:
        ds = date.fromisoformat(start)
        de = date.fromisoformat(end)
    except ValueError:
        return None, "请假日期格式不正确，请重新告诉我起止日期（例如：10月1日到10月3日）。"
    if de < ds:
        return None, "结束日期不能早于开始日期，请核对后再告诉我。"
    if ds < date.today():
        return None, "开始日期早于今天，不能提交过去日期的请假申请，请重新确认请假时间。"
    # 缺原因必须追问（与「缺任一 → 先追问」一致），不能用默认值静默兜底
    reason = (data.get("reason") or "").strip()
    if not reason:
        return None, "请补充请假原因（如病假/事假/丧假等），以便提交申请。"
    return {
        "leave_type": "sick" if "病" in reason else "personal",
        "start_date": start,
        "end_date": end,
        "reason": reason,
    }, None


def _validate_course_selection(data: dict) -> ValidatorResult:
    course_ids = data.get("course_ids")
    if not isinstance(course_ids, list) or not course_ids:
        return None, "请告诉我想选的课程名称（例如：选 程序设计基础 和 艺术鉴赏）。"
    course_ids = [str(c).strip().upper() for c in course_ids]
    course_ids = list(dict.fromkeys(course_ids))  # 去重保序
    if len(course_ids) > 5:
        return None, "一次最多选 5 门课程，请分批申请。"
    unknown = [c for c in course_ids if c not in R.COURSE_CATALOG]
    if unknown:
        catalog = "、".join(f"{k} {R.COURSE_CATALOG[k]['name']}" for k in R.COURSE_CATALOG)
        return None, f"以下课程不存在：{'、'.join(unknown)}。可选课程：{catalog}。"
    reason = _normalize_reason(data, "个人选课需求")
    return {"course_ids": course_ids, "reason": reason}, None


def _validate_reimbursement(data: dict) -> ValidatorResult:
    try:
        amount = round(float(data.get("amount", 0)), 2)
    except (TypeError, ValueError):
        return None, "报销金额格式不正确，请告诉我具体金额（例如：120 元）。"
    if amount <= 0:
        return None, "报销金额必须是大于 0 的数字。"
    category = str(data.get("category", "")).strip().lower()
    cat_map = {"教材": "textbook", "课本": "textbook", "会议": "conference", "学术会议": "conference",
               "差旅": "travel", "出差": "travel", "设备": "equipment", "器材": "equipment",
               "其他": "other", "其它": "other"}
    if category in cat_map:
        category = cat_map[category]
    if category not in R.REIMBURSEMENT_LIMITS:
        cats = "、".join(f"{k}（限额 {R.REIMBURSEMENT_LIMITS[k]:g} 元）" for k in R.REIMBURSEMENT_LIMITS)
        return None, f"报销类别不支持「{category}」。支持：{cats}。"
    reason = _normalize_reason(data, "报销申请")
    return {"amount": amount, "category": category, "reason": reason}, None


def _validate_venue_reservation(data: dict) -> ValidatorResult:
    venue_id = str(data.get("venue_id", "")).strip()
    venue_type = ""
    if venue_id in R.VENUE_CATALOG:
        venue_type = R.VENUE_CATALOG[venue_id]["type"]
    else:
        venue_id = ""
        venue_type = str(data.get("venue_type", "")).strip().lower()
        type_map = {"教室": "classroom", "活动室": "activity_room", "报告厅": "lecture_hall", "机房": "computer_lab"}
        if venue_type in type_map:
            venue_type = type_map[venue_type]
    all_types = R.VENUE_TYPES_AUTO_APPROVE | R.VENUE_TYPES_MANUAL
    if venue_type not in all_types:
        return None, "请先选择要预约的场地（可问「有哪些场地」查看目录）。"
    start_time = str(data.get("start_time") or "").strip()
    end_time = str(data.get("end_time") or "").strip()
    if not start_time or not end_time:
        return None, "请告诉我预约的起止时间（例如：10月1日下午2点到4点）。"
    parsed = _parse_dt_range(start_time, end_time)
    if parsed is None:
        return None, "时间格式不正确，请用「日期 时:分」描述（例如：2026-10-01 14:00 到 16:00）。"
    s, e = parsed
    if e <= s:
        return None, "预约结束时间必须晚于开始时间。"
    if s.date() < date.today():
        return None, "预约日期早于今天，请重新选择时间。"
    if e.date() != s.date():
        return None, "暂不支持跨天预约，请在同一天内选择起止时间。"
    try:
        participants = int(data.get("participants") or 0)
    except (TypeError, ValueError):
        participants = 0
    if participants <= 0:
        return None, "请告诉我预计参加人数（例如：30 人）。"
    purpose = (data.get("purpose") or data.get("activity_theme") or "").strip()
    if not purpose:
        return None, "请告诉我活动的主题/用途（例如：班级团建活动）。"
    fields = {
        "venue_type": venue_type,
        "start_time": start_time,
        "end_time": end_time,
        "purpose": purpose,
        "participants": participants,
    }
    if venue_id:
        fields["venue_id"] = venue_id
    return fields, None


FORM_SPECS: dict[str, dict] = {
    "leave": {
        "action": "submit_leave",
        "label": "请假申请",
        "validate": _validate_leave,
        "draft_msg": "已根据您的描述为您预填了请假申请表单，请核对下面的起止时间与事由，确认无误后点击「提交申请」；如需修改可直接在表单里编辑。",
    },
    "course_selection": {
        "action": "submit_course_selection",
        "label": "选课申请",
        "validate": _validate_course_selection,
        "draft_msg": "已为您预填选课申请表单，请核对所选课程，确认无误后点击「提交申请」；如需增删课程可直接在表单里修改。",
    },
    "reimbursement": {
        "action": "submit_reimbursement",
        "label": "报销申请",
        "validate": _validate_reimbursement,
        "draft_msg": "已为您预填报销申请表单，请核对金额与类别，并补充票据信息后提交；如需修改可直接编辑。",
    },
    "venue_reservation": {
        "action": "submit_venue_reservation",
        "label": "场地预约",
        "validate": _validate_venue_reservation,
        "draft_msg": "已为您预填场地预约表单，请核对时间与人数，确认无误后点击「提交申请」。",
    },
}

_ACTION_TO_SPEC: dict[str, tuple[str, dict]] = {
    spec["action"]: (ptype, spec) for ptype, spec in FORM_SPECS.items()
}


def form_prompt_section() -> str:
    """系统提示词中的「申请表单」说明：由 FORM_SPECS 驱动的规则源（课程/类别/场地）生成，
    避免在提示词里硬编码，新增流程类型自动生效。"""
    catalog = "、".join(f"{k} {R.COURSE_CATALOG[k]['name']}" for k in R.COURSE_CATALOG)
    venues = "、".join(f"{vid} {v['name']}({v['type']})" for vid, v in R.VENUE_CATALOG.items())
    cats = "、".join(f"{k}({R.REIMBURSEMENT_LIMITS[k]:g}元)" for k in R.REIMBURSEMENT_LIMITS)
    return (
        "【申请表单】当学生明确表达要提交申请（请假/选课/报销/场地预约）时：\n"
        "  - 所需字段齐备才输出 JSON；缺任一 → 先追问，绝不输出 JSON；\n"
        "  - JSON 必须单独一行、不要包在代码块里；\n"
        "  - 输出 JSON 的同时用一句话告知「已为您预填xx申请表单，请核对」。\n"
        "支持的表单与 JSON 格式：\n"
        '  1. 请假：{"action":"submit_leave","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","reason":"病假"}\n'
        f'  2. 选课：{{"action":"submit_course_selection","course_ids":["CS101"]}}\n'
        f"     可选课程（学生只说课程中文名，你负责映射成课程号）：{catalog}\n"
        "     选课只要课程名即可，绝不追问课程号、先修要求、选课理由、已选课程数量；\n"
        f'  3. 报销：{{"action":"submit_reimbursement","amount":120,"category":"textbook","reason":"购买教材"}}\n'
        f"     类别（英文）：{cats}\n"
        f'  4. 场地预约：{{"action":"submit_venue_reservation","venue_id":"V101","start_time":"2026-10-01 14:00","end_time":"2026-10-01 16:00","purpose":"班级团建","participants":30}}\n'
        f"     可选场地（学生只说场地中文名，你负责映射成 venue_id）：{venues}\n"
        "【不要这样】\n"
        "学生说：我想请个假 → 缺日期与原因，先追问，不输出 JSON；\n"
        "学生说：9月25号到26号请假 → 缺原因，先追问，不输出 JSON；\n"
        "学生说：请问奖学金怎么申请 → 制度问答，不输出 JSON；\n"
        "学生说：昨天开始请事假 → 开始日期早于今天，不输出 JSON，提示日期不合法；\n"
        "学生说：帮我退课/取消报名/其他未支持操作 → 制度问答或引导使用页面，不输出 JSON。\n"
        "学生说：我要选课/我想选课 → 不要列问题、不要追问，系统会直接弹出选课卡片，你回一句引导勾选即可。\n"
        "学生说「有哪些课/看看可选课程/课程目录/有什么选修课」→ 输出 {\"action\":\"list_courses\"}（纯查询，不弹表单）。\n"
        "学生说：我要预约场地/我想预约 → 不要追问时间地点，系统会直接弹出场地卡片，你回一句引导选择即可。\n"
        "学生说「有哪些场地/场地目录/能预约什么地方」→ 输出 {\"action\":\"list_venues\"}（纯查询，不弹表单）。\n"
    )
