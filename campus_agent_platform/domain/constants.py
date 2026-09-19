"""领域常量：状态、决策、角色、动作、流程类型。"""

# ---------------------------------------------------------------
# 审批状态机（设计文档 5.1）
#   draft -> pending_<node> -> approved / rejected / archived
#   请假按天数动态节点链：counselor [+college] [+university]
#   任意非终态可 return 回退上一节点；终态：approved / rejected / archived
# ---------------------------------------------------------------
STATUS_DRAFT = "draft"
STATUS_PENDING_PREFIX = "pending_"          # 动态节点状态：pending_<node_id>
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_RETURNED = "returned"                # 回退到上一节点后的过渡标记（可继续审批）
STATUS_ARCHIVED = "archived"

TERMINAL_STATUSES = {STATUS_APPROVED, STATUS_REJECTED, STATUS_ARCHIVED}
ACTIVE_STATUSES = {
    STATUS_DRAFT,
    STATUS_RETURNED,
} | {f"{STATUS_PENDING_PREFIX}{n}" for n in ("advisor", "college", "counselor", "university")}

# 审批决策（advance_approval 的 decision 枚举，约束转移合法性）
DECISION_APPROVE = "approve"                # 任一节点 approve 才流转
DECISION_REJECT = "reject"                  # reject 终止
DECISION_RETURN = "return"                  # return 回退上一节点（可多次）

ALL_DECISIONS = {DECISION_APPROVE, DECISION_REJECT, DECISION_RETURN}

# ---------------------------------------------------------------
# RBAC 角色与动作（deny by default，设计文档 5.4）
# ---------------------------------------------------------------
ROLE_STUDENT = "student"
ROLE_ADVISOR = "advisor"
ROLE_COUNSELOR = "counselor"
ROLE_COLLEGE_ADMIN = "college_admin"
ROLE_UNIVERSITY_LEADER = "university_leader"
ROLE_LOGISTICS = "logistics"
ROLE_FINANCE = "finance"
ROLE_SYSTEM = "system"

ALL_ROLES = {
    ROLE_STUDENT,
    ROLE_ADVISOR,
    ROLE_COUNSELOR,
    ROLE_COLLEGE_ADMIN,
    ROLE_UNIVERSITY_LEADER,
    ROLE_LOGISTICS,
    ROLE_FINANCE,
    ROLE_SYSTEM,
}

# 动作
ACTION_SUBMIT = "submit"                    # 提交申请
ACTION_APPROVE = "approve"                  # 审批通过
ACTION_REJECT = "reject"                    # 审批驳回
ACTION_RETURN = "return"                    # 退回
ACTION_VIEW = "view"                        # 查看申请 / 状态
ACTION_ARCHIVE = "archive"                  # 归档
ACTION_VALIDATE = "validate"                # 业务规则校验
ACTION_NOTIFY = "notify"                    # 发送通知
ACTION_QUERY_COURSES = "query_courses"      # 查询课程
ACTION_CHECK_LIMIT = "check_limit"          # 检查报销限额
ACTION_REGISTER_TEMPLATE = "register_template"  # 注册流程模板

ALL_ACTIONS = {
    ACTION_SUBMIT,
    ACTION_APPROVE,
    ACTION_REJECT,
    ACTION_RETURN,
    ACTION_VIEW,
    ACTION_ARCHIVE,
    ACTION_VALIDATE,
    ACTION_NOTIFY,
    ACTION_QUERY_COURSES,
    ACTION_CHECK_LIMIT,
    ACTION_REGISTER_TEMPLATE,
}

# ---------------------------------------------------------------
# 流程类型（内置种子模板）
# ---------------------------------------------------------------
PROCESS_LEAVE = "leave"                     # 请假
PROCESS_COURSE_SELECTION = "course_selection"  # 选课
PROCESS_REIMBURSEMENT = "reimbursement"     # 报销
PROCESS_VENUE_RESERVATION = "venue_reservation"  # 场地预约（扩展示例，设计文档 5.3）

# 通知渠道
CHANNEL_IM = "im"
CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"

ALL_CHANNELS = {CHANNEL_IM, CHANNEL_EMAIL, CHANNEL_SMS}

# 审计事件类型
EVENT_REQUEST_SUBMITTED = "request_submitted"
EVENT_REQUEST_VALIDATED = "request_validated"
EVENT_REQUEST_ADVANCED = "request_advanced"
EVENT_REQUEST_ARCHIVED = "request_archived"
EVENT_TEMPLATE_REGISTERED = "template_registered"
EVENT_NOTIFICATION_SENT = "notification_sent"
EVENT_PERMISSION_DENIED = "permission_denied"
EVENT_OPTIMISTIC_LOCK_CONFLICT = "optimistic_lock_conflict"

# 默认限流：按申请人 / 操作人（需求约束）
RATE_LIMIT_PER_ACTOR = 60                   # 每分钟
