"""工具层：10 个工具契约（对齐设计文档 5.2 与 tools.json schema）。

- 幂等：submit_approval_request（client_request_no 去重）、archive_record（同单幂等）、读类工具
- 非幂等写：advance_approval（乐观锁防并发双审）
- 权限前置：所有写操作先经 check_permission（RBAC deny by default）
"""
