"""企业工作流的板块归属与负责人管理视角。"""

WORKFLOW_GROUPS = {
    "审计与合同": ["commercial_contract"],
    "人力管理": ["labor_contract", "recruitment_match"],
    "行政管理": ["policy_review", "meeting_actions"],
    "财务管理": ["expense_review", "budget_analysis"],
}

WORKFLOW_DEPARTMENTS = {
    workflow_id: department
    for department, workflow_ids in WORKFLOW_GROUPS.items()
    for workflow_id in workflow_ids
}

LEADER_FOCUS = {
    "审计与合同": ["重大授权与章程边界", "采购及供应商异常", "经营收入完整性", "历史整改复发"],
    "人力管理": ["编制与人工成本", "关键岗位任用", "劳动用工一致性", "人才流动与历史争议"],
    "行政管理": ["制度有效性与冲突", "印章档案闭环", "安全证照到期", "会议决议执行"],
    "财务管理": ["预算与滚动预测", "收入资金完整性", "费用支付合规", "历史差异与整改"],
}
