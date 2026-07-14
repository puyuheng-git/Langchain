"""企业工作台公共接口的行为测试。"""

from pathlib import Path

import pytest

from enterprise import EnterpriseStore, ReviewWorkspace
from enterprise.ai.gateway import redact_text
from enterprise.sample_data import generate_samples


@pytest.fixture()
def sample_root(tmp_path: Path) -> Path:
    """为每个测试生成隔离的标准样本。"""

    root = tmp_path / "samples"
    generate_samples(root)
    return root


@pytest.fixture()
def workspace(tmp_path: Path) -> ReviewWorkspace:
    """创建使用临时 SQLite 和文件目录的工作区。"""

    return ReviewWorkspace(EnterpriseStore(tmp_path / "enterprise"))


def test_all_priority_workflows_execute_offline_and_persist_history(
    workspace: ReviewWorkspace, sample_root: Path
) -> None:
    """六类优先流程和原商业合同流程均可在无模型时完成并留档。"""

    cases = {
        "commercial_contract": [sample_root / "audit/contracts/purchase_contract.txt"],
        "labor_contract": [sample_root / "hr/contracts/labor_contract_06.txt"],
        "recruitment_match": [
            sample_root / "hr/job_descriptions/job_01.txt",
            sample_root / "hr/resumes/resume_01.txt",
            sample_root / "hr/resumes/resume_02.txt",
        ],
        "policy_review": [sample_root / "admin/policies/policy_10.txt"],
        "meeting_actions": [sample_root / "admin/meeting_minutes/meeting_03.txt"],
        "expense_review": [sample_root / "finance/expenses.csv"],
        "budget_analysis": [sample_root / "finance/budget_vs_actual.csv"],
    }

    for workflow_id, paths in cases.items():
        execution = workspace.execute_files(
            workflow_id,
            paths,
            actor="测试用户",
            options={"use_ai": False, "create_tasks": True, "expense_limit": 5000},
        )
        assert execution.success, execution.error
        assert execution.result is not None
        assert execution.result.workflow_id == workflow_id
        assert Path(execution.report_path or "").is_file()

    assert len(workspace.store.list_cases()) == len(cases)
    assert workspace.store.list_tasks(), "会议行动项应同步到任务中心"


def test_uploaded_bytes_survive_refresh_and_can_be_rerun(workspace: ReviewWorkspace) -> None:
    """浏览器上传内容写入案件目录后可从历史重新执行。"""

    content = """劳动合同
用人单位（甲方）：示例公司
劳动者（乙方）：样本员工
工作岗位：会计
工作地点：上海市
合同期限：固定期限，自2026年1月1日至2028年12月31日
劳动报酬：月工资人民币10000元
工时制度：标准工时制
甲方依法缴纳社会保险
签订日期：2026年1月1日
""".encode()
    first = workspace.execute_uploads(
        "labor_contract",
        [("../不安全/劳动合同.txt", content, "text/plain")],
        options={"use_ai": False},
    )

    assert first.success
    case = workspace.store.get_case(first.case_id)
    assert case is not None
    artifact = case["artifacts"][0]
    stored_path = Path(artifact["stored_path"])
    assert stored_path.is_file()
    assert stored_path.parent.name == first.case_id
    assert stored_path.name == "劳动合同.txt"

    rerun = workspace.rerun(first.case_id, options={"use_ai": False})
    assert rerun.success
    assert len(workspace.store.get_case(first.case_id)["executions"]) == 2


def test_failed_execution_is_visible_in_history(workspace: ReviewWorkspace) -> None:
    """格式不支持的上传也要保留失败案件和错误。"""

    execution = workspace.execute_uploads(
        "policy_review",
        [("policy.exe", b"not a document", "application/octet-stream")],
        options={"use_ai": False},
    )

    assert not execution.success
    case = workspace.store.get_case(execution.case_id)
    assert case is not None
    assert case["status"] == "执行失败"
    assert case["executions"][0]["error"]


def test_missing_local_file_is_recorded_as_failed_case(workspace: ReviewWorkspace) -> None:
    """本地文件归档失败也不能留下永久“处理中”的案件。"""

    execution = workspace.execute_files(
        "commercial_contract", ["missing-contract.txt"], options={"use_ai": False}
    )

    assert not execution.success
    case = workspace.store.get_case(execution.case_id)
    assert case["status"] == "执行失败"
    assert case["executions"][0]["status"] == "失败"


def test_sensitive_text_redaction_covers_common_identifiers() -> None:
    """外部模型授权前会移除身份证、手机、邮箱、银行卡和金额。"""

    text = """姓名：张三
身份证310101199001011234，手机13800138000，邮箱user@example.com
卡号6222021234567890，工资：人民币12000.00，发票号：INV-001
"""
    redacted, counts = redact_text(text)

    assert "310101199001011234" not in redacted
    assert "13800138000" not in redacted
    assert "user@example.com" not in redacted
    assert "6222021234567890" not in redacted
    assert "12000.00" not in redacted
    assert "张三" not in redacted
    assert "INV-001" not in redacted
    assert sum(counts.values()) >= 7


def test_requester_cannot_approve_own_final_action(workspace: ReviewWorkspace) -> None:
    """轻量审批仍强制申请人与审批人分离。"""

    execution = workspace.execute_uploads(
        "policy_review",
        [("policy.txt", "制度\n适用范围：全员".encode(), "text/plain")],
        actor="申请人",
        options={"use_ai": False},
    )
    approval_id = workspace.store.create_approval(execution.case_id, "制度发布", "申请人")

    with pytest.raises(ValueError, match="不能审批自己的申请"):
        workspace.store.decide_approval(approval_id, "已批准", "同意", "申请人")

    workspace.store.decide_approval(approval_id, "已批准", "复核通过", "审批人")
    assert workspace.store.list_approvals(execution.case_id)[0]["status"] == "已批准"


def test_finance_numbers_are_calculated_by_local_rules(
    workspace: ReviewWorkspace, sample_root: Path
) -> None:
    """费用和预算的权威数字来自本地表格计算。"""

    expense = workspace.execute_files(
        "expense_review",
        [sample_root / "finance/expenses.csv"],
        options={"use_ai": False, "expense_limit": 5000},
    )
    budget = workspace.execute_files(
        "budget_analysis",
        [sample_root / "finance/budget_vs_actual.csv"],
        options={"use_ai": False},
    )

    assert expense.result.metrics["费用笔数"] == 200
    assert expense.result.metrics["费用总额"] == 805450.0
    assert budget.result.metrics["总预算"] == 6240000.0
    assert budget.result.metrics["实际发生"] == 5269600.0
    assert budget.result.metrics["执行率%"] == 84.4
