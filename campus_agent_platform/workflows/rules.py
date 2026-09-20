"""业务规则校验器（设计文档 5.2 validate_request_rules / 规则源）。

按流程模板的 validation_rules 引用执行对应校验器，返回违规项列表。
规则源（query_courses / check_reimbursement_limit）由工具层提供，
此处实现确定性校验逻辑，保证测试可复现。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable

from ..domain import constants as C
from ..domain.errors import ValidationError

# 预置课程目录（A2 选课场景规则源：名额 / 先修课 / 时间冲突 / 教师 / 地点）
# 全校选修课：所有专业学生均可选择（不做培养方案限制）
COURSE_CATALOG: dict[str, dict[str, Any]] = {
    "CS101": {"name": "程序设计基础", "teacher": "王老师", "location": "教学楼A101",
              "quota": 2, "prerequisite": [], "credit": 3,
              "schedule": "Mon 10:00-12:00", "major": ["CS", "SE"]},
    "CS202": {"name": "数据结构", "teacher": "李老师", "location": "教学楼A203",
              "quota": 3, "prerequisite": ["CS101"], "credit": 4,
              "schedule": "Tue 10:00-12:00", "major": ["CS", "SE"]},
    "MATH101": {"name": "高等数学", "teacher": "张教授", "location": "教学楼B201",
                "quota": 5, "prerequisite": [], "credit": 5,
                "schedule": "Mon 10:00-12:00", "major": ["ALL"]},
    "PHY101": {"name": "大学物理", "teacher": "刘老师", "location": "理科楼305",
               "quota": 4, "prerequisite": ["MATH101"], "credit": 4,
               "schedule": "Wed 14:00-16:00", "major": ["ALL"]},
    "ART101": {"name": "艺术鉴赏", "teacher": "陈老师", "location": "艺术楼201",
               "quota": 10, "prerequisite": [], "credit": 2,
               "schedule": "Fri 10:00-12:00", "major": ["ALL"]},
}

# 选课在册记录：course_id -> 已选人数（A2 退选释放：退选后减一）
COURSE_ENROLLMENT: dict[str, int] = {"CS101": 1, "CS202": 0, "MATH101": 2, "PHY101": 0, "ART101": 0}

# 场地目录（具体场地实例，与课程目录对齐）：
#   venue_id -> {name, type, capacity, location}
#   type 决定审批链：classroom 提交即自动通过；其余走后勤人工审核
VENUE_CATALOG: dict[str, dict[str, Any]] = {
    "V001": {"name": "教室A101", "type": "classroom", "capacity": 40, "location": "教学楼A座"},
    "V002": {"name": "教室A203", "type": "classroom", "capacity": 60, "location": "教学楼A座"},
    "V101": {"name": "活动中心301", "type": "activity_room", "capacity": 100, "location": "学生活动中心"},
    "V102": {"name": "活动中心302", "type": "activity_room", "capacity": 60, "location": "学生活动中心"},
    "V201": {"name": "学术报告厅", "type": "lecture_hall", "capacity": 300, "location": "图书馆一层"},
    "V301": {"name": "计算中心机房", "type": "computer_lab", "capacity": 50, "location": "实验楼C座"},
}

# 报销限额（A3：按类别预算，check_reimbursement_limit 规则源）
REIMBURSEMENT_LIMITS: dict[str, float] = {
    "textbook": 300.0,     # 教材
    "conference": 1500.0,  # 学术会议
    "travel": 800.0,       # 差旅
    "equipment": 2000.0,   # 设备
    "other": 500.0,
}

# 报销票据完整性要求：必需票据类型（收据 / 发票）
REQUIRED_RECEIPTS = ("receipt", "invoice")

# 审批人角色到人员 id 的映射（演示环境：固定账号，后续可接校园 SSO）
ROLE_HOLDER: dict[str, str] = {
    "advisor": "T10001",
    "college_admin": "A20001",
    "counselor": "C30001",
    "university_leader": "U50001",
    "logistics": "H60001",
    "finance": "F40001",
}

# 学生 → 导师归属（设计文档 5.1「权限（该单导师）」：导师节点仅该单导师可审）
STUDENT_ADVISOR: dict[str, str] = {
    "S10001": "T10001",
    "S10002": "T10001",
    "S10003": "T10002",
    "C30001": "T10001",
}


def advisor_of(student_id: str) -> str:
    return STUDENT_ADVISOR.get(student_id, "")


def holder_for_role(role: str) -> str:
    return ROLE_HOLDER.get(role, "")


def enroll_course(course_id: str) -> None:
    """占课（提交选课通过后调用）；退选释放由 drop_course 处理。"""
    if course_id in COURSE_ENROLLMENT:
        COURSE_ENROLLMENT[course_id] += 1


def drop_course(course_id: str) -> None:
    """退选释放名额（A2：退选后名额释放）。"""
    if course_id in COURSE_ENROLLMENT and COURSE_ENROLLMENT[course_id] > 0:
        COURSE_ENROLLMENT[course_id] -= 1


# ----------------------------------------------------------------------
# 各规则校验器：签名 (payload: dict) -> list[str]（违规项描述）
# ----------------------------------------------------------------------
def _check_date_validity(payload: dict) -> list[str]:
    """请假日期有效：开始不早于今天、结束不早于开始。"""
    violations: list[str] = []
    start = payload.get("start_date")
    end = payload.get("end_date")
    if not start or not end:
        violations.append("请假起止日期必填")
        return violations
    try:
        d_start = date.fromisoformat(str(start))
        d_end = date.fromisoformat(str(end))
    except ValueError:
        violations.append("请假日期格式非法（应为 YYYY-MM-DD）")
        return violations
    if d_start < date.today():
        violations.append("请假开始日期早于今天")
    if d_end < d_start:
        violations.append("请假结束日期早于开始日期")
    return violations


def _check_course_quota(payload: dict) -> list[str]:
    """选课规则：课程存在 + 名额。"""
    violations: list[str] = []
    course_ids = payload.get("course_ids") or []
    if not course_ids:
        violations.append("选课列表为空")
        return violations
    if len(course_ids) != len(set(course_ids)):
        violations.append("选课课程重复")
    for cid in course_ids:
        course = COURSE_CATALOG.get(cid)
        if course is None:
            violations.append(f"课程不存在: {cid}")
            continue
        if COURSE_ENROLLMENT.get(cid, 0) >= course["quota"]:
            violations.append(f"课程 {cid} 名额已满")
    return violations


def _check_prerequisite(payload: dict) -> list[str]:
    """选课规则：先修课。"""
    violations: list[str] = []
    passed = set(payload.get("passed_courses", []))
    for cid in payload.get("course_ids") or []:
        course = COURSE_CATALOG.get(cid)
        if course is None:
            continue
        missing = [p for p in course["prerequisite"] if p not in passed]
        if missing:
            violations.append(f"课程 {cid} 缺少先修课: {missing}")
    return violations


def _check_schedule_conflict(payload: dict) -> list[str]:
    """选课规则：时间冲突（选修课面向全校，不做专业培养方案限制）。"""
    violations: list[str] = []
    selected_schedules: list[str] = []
    for cid in payload.get("course_ids") or []:
        course = COURSE_CATALOG.get(cid)
        if course is None:
            continue
        if course["schedule"] in selected_schedules:
            violations.append(f"课程 {cid} 与已选课程时间冲突")
        selected_schedules.append(course["schedule"])
    return violations


def _check_receipt_completeness(payload: dict) -> list[str]:
    """报销票据完整性。"""
    violations: list[str] = []
    receipts = payload.get("receipts") or []
    if not receipts:
        violations.append("缺少报销票据")
        return violations
    types = {r.get("type") for r in receipts}
    for required in REQUIRED_RECEIPTS:
        label = {"receipt": "收据", "invoice": "发票"}.get(required, required)
        if required not in types:
            violations.append(f"缺少必需票据类型: {label}")
    total = 0.0
    for r in receipts:
        try:
            total += float(r.get("amount", 0))
        except (TypeError, ValueError):
            violations.append("票据金额非法")
    if abs(total - float(payload.get("amount", 0))) > 0.01:
        violations.append("票据金额合计与申请金额不一致")
    return violations


def _check_reimbursement_limit(payload: dict) -> list[str]:
    """报销限额。"""
    violations: list[str] = []
    category = payload.get("category", "other")
    limit = REIMBURSEMENT_LIMITS.get(category, REIMBURSEMENT_LIMITS["other"])
    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        violations.append("报销金额非法")
        return violations
    if amount < 0:
        violations.append("报销金额为负数")
    if amount > limit:
        violations.append(f"报销金额 {amount} 超出 {category} 限额 {limit}")
    return violations


def _check_amount_validity(payload: dict) -> list[str]:
    """金额合理性（负数 / 非数值拦截，B2）。"""
    violations: list[str] = []
    try:
        amount = float(payload.get("amount", 0))
    except (TypeError, ValueError):
        violations.append("报销金额非法")
        return violations
    if amount < 0:
        violations.append("报销金额为负数")
    return violations


def _check_venue_rules(payload: dict) -> list[str]:
    """场地预约规则（扩展示例 5.3）：日期有效 + 场地存在 + 场地冲突占位。"""
    violations: list[str] = []
    start = payload.get("start_time")
    end = payload.get("end_time")
    if not start or not end:
        violations.append("预约起止时间必填")
        return violations
    if start >= end:
        violations.append("预约结束时间须晚于开始时间")
    # 场地必须可识别：venue_id 在目录中，或 venue_type 为合法类型（兼容旧数据）
    # VENUE_TYPES_* 在文件后部定义，函数运行时引用，顺序无碍
    if venue_type_of(payload) not in (VENUE_TYPES_AUTO_APPROVE | VENUE_TYPES_MANUAL):
        violations.append("场地不合法：请从场地目录中选择具体场地")
    # 时段重叠冲突查询历史单的逻辑在 engine.submit（需访问仓储），此处只做静态校验
    return violations


_RULE_REGISTRY: dict[str, Callable[[dict], list[str]]] = {
    "date_validity": _check_date_validity,
    "course_quota": _check_course_quota,
    "schedule_conflict": _check_schedule_conflict,
    "reimbursement_limit": _check_reimbursement_limit,
    "receipt_completeness": _check_receipt_completeness,
    "amount_validity": _check_amount_validity,
    "venue_conflict": _check_venue_rules,
}


def validate_rules(validation_rules: list[str], payload: dict) -> list[str]:
    """按规则名列表执行校验，汇总违规项。"""
    violations: list[str] = []
    for rule in validation_rules:
        checker = _RULE_REGISTRY.get(rule)
        if checker is None:
            continue
        violations.extend(checker(payload))
    return violations


def ensure_valid(validation_rules: list[str], payload: dict) -> None:
    """校验并抛错（失败时带明细，供 B2 测试断言）。"""
    violations = validate_rules(validation_rules, payload)
    if violations:
        raise ValidationError("业务规则校验未通过", details={"violations": violations})


# ----------------------------------------------------------------------
_SQL_INJECTION_PATTERN = re.compile(r"[\s;'\"]*(--|select|insert|update|delete|drop|union)\b", re.IGNORECASE)
_SPECIAL_CHARS_PATTERN = re.compile(r"[\x00-\x1f<>\"'`]")


def sanitize_text(value: str, *, field: str = "文本") -> None:
    """特殊字符注入拦截（B2：特殊字符注入）。"""
    if not isinstance(value, str):
        return
    if _SQL_INJECTION_PATTERN.search(value):
        raise ValidationError(f"{field} 含可疑 SQL 关键字", details={"field": field})
    if _SPECIAL_CHARS_PATTERN.search(value):
        raise ValidationError(f"{field} 含非法特殊字符", details={"field": field})


def sanitize_payload(payload: dict) -> None:
    """递归清洗 payload 中的字符串字段。"""
    for key, value in payload.items():
        if isinstance(value, str):
            sanitize_text(value, field=key)
        elif isinstance(value, dict):
            sanitize_payload(value)


# ----------------------------------------------------------------------
# 请假动态审批链（业务规则）：
#   学生提交 -> 辅导员必审
#   请假 > 3 天 -> 追加学院领导审批
#   请假 > 7 天 -> 追加学校领导审批
# ----------------------------------------------------------------------
def leave_days(payload: dict) -> int:
    """计算请假天数（含首尾，自然日）；日期非法返回 0。"""
    start = payload.get("start_date")
    end = payload.get("end_date")
    if not start or not end:
        return 0
    try:
        d_start = date.fromisoformat(str(start))
        d_end = date.fromisoformat(str(end))
    except ValueError:
        return 0
    if d_end < d_start:
        return 0
    return (d_end - d_start).days + 1


def resolve_leave_nodes(payload: dict) -> list[dict[str, str]]:
    """按请假天数动态决定审批链：
    - 所有请假：辅导员（counselor）必审
    - > 3 天：追加学院领导（college_admin）
    - > 7 天：追加学校领导（university_leader）
    """
    nodes: list[dict[str, str]] = [
        {"node_id": "counselor", "approver_role": "counselor"},
    ]
    days = leave_days(payload)
    if days > 3:
        nodes.append({"node_id": "college", "approver_role": "college_admin"})
    if days > 7:
        nodes.append({"node_id": "university", "approver_role": "university_leader"})
    return nodes


# ----------------------------------------------------------------------
# 场地预约动态审批链（业务规则）：
#   教室（classroom）：自动审批，即时通过（无人工节点 → 空链）
#   活动室 / 报告厅 / 机房：后勤（logistics）人工审核
# ----------------------------------------------------------------------
VENUE_TYPES_AUTO_APPROVE = {"classroom"}
VENUE_TYPES_MANUAL = {"activity_room", "lecture_hall", "computer_lab"}


def venue_type_of(payload: dict) -> str:
    """从 payload 解析场地类型：优先 venue_id 查目录，兼容旧 venue_type 字段。"""
    venue_id = str(payload.get("venue_id", "")).strip()
    if venue_id and venue_id in VENUE_CATALOG:
        return VENUE_CATALOG[venue_id]["type"]
    return str(payload.get("venue_type", "")).strip().lower()


def resolve_venue_nodes(payload: dict) -> list[dict[str, str]]:
    """按场地类型决定审批链：
    - 教室：空链 → 提交即自动 approved
    - 其他类型（活动室/报告厅/机房）：后勤单节点人工审核
    """
    venue_type = venue_type_of(payload)
    if venue_type in VENUE_TYPES_AUTO_APPROVE:
        return []
    # 未知类型或其他场地默认走人工审核（兜底，避免漏审）
    return [{"node_id": "venue", "approver_role": "logistics"}]


# ----------------------------------------------------------------------
# 辅导员自动审核：单条请假单的纯规则评估（对话端 / API 端共用）
# ----------------------------------------------------------------------
def evaluate_leave_auto_review(payload: dict, attachment_urls: list[str]) -> tuple[list[str], int]:
    """评估单条待审请假单，返回 (violations, days)。

    判定：
    - violations 非空 → 应自动驳回；
    - days > 7 → 超辅导员权限，应跳过（转学校领导）；
    - violations 为空且 days <= 7 → 应自动通过。
    违规措辞保持与原对话/API 两端一致，仅合并重复判断。
    """
    start = payload.get("start_date")
    end = payload.get("end_date")
    leave_type = payload.get("leave_type", "")
    reason = (payload.get("reason") or "").strip()
    atts = attachment_urls or []

    violations: list[str] = []
    if not start or not end:
        violations.append("起止日期必填")
    else:
        try:
            ds = date.fromisoformat(str(start))
            de = date.fromisoformat(str(end))
            if ds < date.today():
                violations.append("开始日期早于今天")
            if de < ds:
                violations.append("结束日期早于开始")
        except ValueError:
            violations.append("日期格式错误")
    if leave_type == "sick" and not atts:
        violations.append("病假缺证明材料")
    if not reason:
        violations.append("请假事由为空")

    days = 0
    if start and end:
        try:
            ds = date.fromisoformat(str(start))
            de = date.fromisoformat(str(end))
            days = (de - ds).days + 1
        except ValueError:
            pass
    return violations, days
