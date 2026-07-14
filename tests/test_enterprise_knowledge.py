"""企业工作台知识对照与历史记忆行为测试。"""

from pathlib import Path

import pytest

from enterprise import EnterpriseStore, ReviewWorkspace
from enterprise.adapters.documents import ParsedDocument
from enterprise.core.knowledge import compare_analysis_matches
from enterprise.core.models import WorkflowResult


def test_department_knowledge_supports_hybrid_semantic_search(tmp_path: Path) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    workspace = ReviewWorkspace(store)
    workspace.knowledge.add_text(
        title="酒店费用报销管理办法",
        content="员工出差发生的住宿费应在返程后十个工作日内提交发票并完成费用报销。",
        department="财务管理",
        document_type="部门制度",
        actor="财务负责人",
    )
    workspace.knowledge.add_text(
        title="员工招聘管理办法",
        content="候选人录用前应完成面试评价和背景核验。",
        department="人力管理",
        document_type="部门制度",
        actor="人力负责人",
    )

    matches = workspace.knowledge.search("差旅报账需要在多久内完成", departments=["财务管理"])

    assert matches
    assert matches[0]["title"] == "酒店费用报销管理办法"
    assert all(item["department"] == "财务管理" for item in matches)
    assert matches[0]["score"] > 0


def test_analysis_compares_rag_evidence_and_persists_case_memory(tmp_path: Path) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    workspace = ReviewWorkspace(store)
    workspace.knowledge.add_text(
        title="酒店集团费用管理制度（规划样本）",
        content="招待费单笔超过5000元须由酒店总经理审批，申请人和审批人不得为同一人。",
        department="财务管理",
        document_type="部门制度",
        actor="财务负责人",
        version="V1.0",
    )
    csv_content = (
        "单据号,申请人,部门,费用日期,费用类别,金额,发票号,预算余额,附件,审批人,说明\n"
        "CLM-001,张三,餐饮部,2026-07-01,招待费,6800,INV-001,10000,是,张三,客户接待\n"
    ).encode("utf-8-sig")

    first = workspace.execute_uploads(
        "expense_review",
        [("expenses.csv", csv_content, "text/csv")],
        actor="财务负责人",
        options={"use_ai": False, "expense_limit": 5000},
    )

    assert first.success
    assert first.result is not None
    assert first.result.knowledge_matches
    match = first.result.knowledge_matches[0]
    assert match["title"] == "酒店集团费用管理制度（规划样本）"
    assert "5000" in match["excerpt"]
    assert match["authority_label"].startswith("二级")
    assert match["related_findings"]
    assert match["comparison_status"] == "存在需逐条核验的本次发现"
    persisted = store.get_execution(first.execution_id)
    assert persisted is not None
    assert persisted["result"]["knowledge_matches"]
    report = Path(first.report_path).read_text(encoding="utf-8")
    assert "效力层级" in report
    assert "当前材料证据" in report

    assert not workspace.knowledge.list_documents(document_type="历史案例")
    case = store.get_case(first.case_id)
    accepted_finding = case["findings"][0]
    store.update_finding_review(
        accepted_finding["id"], "已接受", "负责人确认该问题成立", "财务负责人"
    )
    workspace.update_case_status(first.case_id, "已确认", "财务负责人")
    memories = workspace.knowledge.list_documents(document_type="历史案例")
    assert len(memories) == 1
    assert memories[0]["source_ref"] == first.case_id
    assert accepted_finding["title"] in memories[0]["content"]
    assert "[中/待复核]" not in memories[0]["content"]
    assert "经人工确认的问题" in memories[0]["content"]

    second = workspace.execute_uploads(
        "expense_review",
        [("expenses-again.csv", csv_content, "text/csv")],
        actor="财务负责人",
        options={"use_ai": False, "expense_limit": 5000},
    )
    assert second.success
    assert any(item["document_type"] == "历史案例" for item in second.result.knowledge_matches)


def test_seed_hotel_management_baseline_covers_four_departments(tmp_path: Path) -> None:
    workspace = ReviewWorkspace(EnterpriseStore(tmp_path / "enterprise"))

    result = workspace.knowledge.seed_hotel_baseline(actor="系统管理员")

    assert result["created"] >= 8
    departments = {item["department"] for item in workspace.knowledge.list_documents()}
    assert {"审计与合同", "人力管理", "行政管理", "财务管理"} <= departments
    assert any(
        item["document_type"] == "公司章程" for item in workspace.knowledge.list_documents()
    )
    assert {item["status"] for item in workspace.knowledge.list_documents()} == {"规划样本"}
    matches = workspace.knowledge.search("重大投资授权由谁审议", departments=["公司级"])
    assert matches[0]["authority_label"] == "规划样本｜不具正式效力"


def test_same_source_update_replaces_old_knowledge_chunks(tmp_path: Path) -> None:
    workspace = ReviewWorkspace(EnterpriseStore(tmp_path / "enterprise"))
    source_ref = "managed:财务管理:部门制度:资金制度"
    workspace.knowledge.add_text(
        "资金制度",
        "旧版本专属标记 legacytoken",
        "财务管理",
        "部门制度",
        source_ref=source_ref,
        version="V1.0",
    )
    workspace.knowledge.add_text(
        "资金制度",
        "新版本专属标记 currenttoken",
        "财务管理",
        "部门制度",
        source_ref=source_ref,
        version="V2.0",
    )

    assert len(workspace.knowledge.list_documents()) == 1
    assert workspace.knowledge.list_documents()[0]["version"] == "V2.0"
    assert not workspace.knowledge.search("legacytoken", departments=["财务管理"])
    current = workspace.knowledge.search("currenttoken", departments=["财务管理"])
    assert current and "currenttoken" in current[0]["excerpt"]


def test_retrieval_displays_governance_authority_before_history(tmp_path: Path) -> None:
    workspace = ReviewWorkspace(EnterpriseStore(tmp_path / "enterprise"))
    workspace.knowledge.add_text(
        "预算授权章程",
        "年度预算调整必须提交治理机构审议。",
        "公司级",
        "公司章程",
    )
    workspace.knowledge.add_text(
        "预算调整历史案件",
        "已确认的年度预算调整事项未提交治理机构审议。",
        "财务管理",
        "历史案例",
        confirmed_history=True,
    )

    matches = workspace.knowledge.search(
        "年度预算调整应由谁审议", departments=["公司级", "财务管理"]
    )

    assert [item["document_type"] for item in matches[:2]] == ["公司章程", "历史案例"]
    assert matches[0]["authority_rank"] < matches[1]["authority_rank"]


def test_manual_history_is_rejected_and_unruled_match_cites_current_material(
    tmp_path: Path,
) -> None:
    workspace = ReviewWorkspace(EnterpriseStore(tmp_path / "enterprise"))
    with pytest.raises(ValueError, match="历史案例只能由已确认"):
        workspace.knowledge.add_text(
            "未经确认的历史问题", "机器初步发现。", "财务管理", "历史案例"
        )
    workspace.knowledge.add_text(
        "差旅报销制度",
        "员工出差返程后十个工作日内提交发票并完成报销。",
        "财务管理",
        "部门制度",
    )
    document = ParsedDocument("当前申请.txt", "本次出差返程后第八个工作日提交差旅报销。")
    result = WorkflowResult("expense_review", "差旅申请", "未识别到规则异常")
    matches = workspace.knowledge.search("出差返程后提交差旅报销", departments=["财务管理"])

    compared = compare_analysis_matches(result, matches, [document])

    assert compared[0]["current_evidence"]
    evidence = compared[0]["current_evidence"][0]["evidence"][0]
    assert evidence["source"] == "当前申请.txt"
    assert "第八个工作日" in evidence["excerpt"]
