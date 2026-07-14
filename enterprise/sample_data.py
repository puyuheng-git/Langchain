"""生成不含真实人员和财务信息的标准 MVP 样本。"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from random import Random
from typing import Any


def generate_samples(root: str | Path = "data/enterprise/samples") -> dict[str, Any]:
    """幂等生成覆盖六类业务流程的样本和预期异常清单。"""

    root_path = Path(root)
    directories = {
        "contracts": root_path / "hr" / "contracts",
        "jobs": root_path / "hr" / "job_descriptions",
        "resumes": root_path / "hr" / "resumes",
        "policies": root_path / "admin" / "policies",
        "meetings": root_path / "admin" / "meeting_minutes",
        "finance": root_path / "finance",
        "commercial": root_path / "audit" / "contracts",
    }
    for directory in directories.values():
        directory.mkdir(parents=True, exist_ok=True)
    expected: dict[str, list[dict[str, Any]]] = {
        "labor_contracts": [],
        "policies": [],
        "meetings": [],
        "expenses": [],
        "budgets": [],
    }
    for index in range(1, 21):
        employee = f"样本员工{index:02d}"
        omissions = []
        social_clause = "甲方依法为乙方缴纳社会保险。" if index % 4 else ""
        workplace = "上海市浦东新区" if index % 5 else "公司指定地点或全国范围"
        signature = "签订日期：2026年1月2日" if index % 3 else ""
        non_compete = "乙方离职后两年内承担竞业限制义务。" if index % 6 == 0 else ""
        if not social_clause:
            omissions.append("HR-LC-009")
        if not signature:
            omissions.append("HR-LC-008")
        if "全国" in workplace:
            omissions.append("HR-LC-013")
        if non_compete:
            omissions.append("HR-LC-012")
        text = f"""劳动合同
用人单位（甲方）：示例科技有限公司
劳动者（乙方）：{employee}
工作岗位：数据分析专员
工作地点：{workplace}
合同期限：固定期限，自2026年1月1日至2028年12月31日
试用期为2个月。
劳动报酬：月工资人民币12000元。
工时制度：标准工时制。
{social_clause}
双方应遵守保密义务。
{non_compete}
双方可依制度和法律解除或终止劳动合同。
{signature}
"""
        file_path = directories["contracts"] / f"labor_contract_{index:02d}.txt"
        file_path.write_text(text, encoding="utf-8")
        expected["labor_contracts"].append({"file": file_path.name, "expected_rules": omissions})
    skills = ["Python", "SQL", "Excel", "Power BI", "审计", "预算", "招聘", "劳动法"]
    for index in range(1, 6):
        selected = skills[(index - 1) : (index + 3)]
        text = f"""岗位说明：企业数据分析师{index}
岗位职责：负责业务数据分析、项目交付和管理报告。
任职要求：3年以上工作经验；熟练掌握{"、".join(selected)}；具备沟通和项目管理能力。
"""
        (directories["jobs"] / f"job_{index:02d}.txt").write_text(text, encoding="utf-8")
    for index in range(1, 31):
        rng = Random(index)
        candidate_skills = rng.sample(skills, k=3)
        text = f"""姓名：样本候选人{index:02d}
性别：{"男" if index % 2 else "女"}
手机：1380000{index:04d}
工作经验：{1 + index % 7}年
技能：{"、".join(candidate_skills)}
项目经历：负责企业管理系统数据分析项目并完成上线交付。
行业经历：制造与互联网。
"""
        (directories["resumes"] / f"resume_{index:02d}.txt").write_text(text, encoding="utf-8")
    for index in range(1, 11):
        missing_exception = index % 2 == 0
        sod_issue = index % 5 == 0
        text = f"""费用管理制度
制度编号：ADM-FIN-{index:03d}
版本：V1.{index}
适用范围：公司全体员工
归口部门：财务部
审批人：总经理
生效日期：2026年2月1日
职责：申请人提交，部门负责人审核，财务复核。
审批流程：系统提交后按权限审批。
权限标准：5000元以上由分管领导审批。
{"经办人自行审批紧急事项。" if sod_issue else "申请人与审批人不得为同一人。"}
{"例外事项须由总经理批准并补录。" if not missing_exception else ""}
资料保存期限：十年。
修订记录：首次发布。
"""
        file_path = directories["policies"] / f"policy_{index:02d}.txt"
        file_path.write_text(text, encoding="utf-8")
        expected["policies"].append(
            {
                "file": file_path.name,
                "expected_rules": (["ADM-PL-008"] if missing_exception else [])
                + (["ADM-PL-007"] if sod_issue else []),
            }
        )
    for index in range(1, 21):
        owner = "负责人：张三" if index % 3 else ""
        deadline = f"截止日期：2026-12-{(index % 20) + 1:02d}" if index % 4 else ""
        text = f"""经营分析会议
会议日期：2026-07-{(index % 12) + 1:02d}
参会人员：总经理、财务部、人力部、行政部
会议决定：推进预算整改和招聘计划。
行动项：完成预算差异说明，{owner}，{deadline}
行动项：行政部负责更新制度版本，负责人：李四，截止日期：2026-12-20
"""
        file_path = directories["meetings"] / f"meeting_{index:02d}.txt"
        file_path.write_text(text, encoding="utf-8")
        expected["meetings"].append(
            {"file": file_path.name, "missing_owner": not owner, "missing_deadline": not deadline}
        )
    expense_path = directories["finance"] / "expenses.csv"
    expense_headers = [
        "单据号",
        "申请人",
        "部门",
        "费用日期",
        "费用类别",
        "金额",
        "发票号",
        "预算余额",
        "附件",
        "审批人",
        "说明",
    ]
    expense_rows = []
    for index in range(1, 201):
        invoice = f"INV-{index:05d}"
        if index in {20, 21}:
            invoice = "INV-DUP-001"
        amount = 800 + (index % 11) * 650
        row = [
            f"CLM-{index:05d}",
            f"员工{index % 20 + 1:02d}",
            ["研发部", "销售部", "财务部", "人力部"][index % 4],
            f"2026-{(index % 6) + 1:02d}-{(index % 27) + 1:02d}",
            ["差旅费", "招待费", "办公费", "培训费"][index % 4],
            amount,
            "" if index % 17 == 0 else invoice,
            5000 if index % 13 == 0 else 20000,
            "否" if index % 19 == 0 else "是",
            f"员工{index % 20 + 1:02d}" if index % 37 == 0 else f"经理{index % 5 + 1}",
            "客户拜访及项目沟通",
        ]
        expense_rows.append(row)
    _write_csv(expense_path, expense_headers, expense_rows)
    expected["expenses"].append(
        {
            "file": expense_path.name,
            "expected_rules": [
                "FIN-EX-001",
                "FIN-EX-002",
                "FIN-EX-003",
                "FIN-EX-004",
                "FIN-EX-005",
                "FIN-EX-006",
            ],
        }
    )
    budget_path = directories["finance"] / "budget_vs_actual.csv"
    budget_headers = ["部门", "科目", "期间", "预算", "实际"]
    budget_rows = []
    for department_index, department in enumerate(["研发部", "销售部", "财务部", "人力部"]):
        for month in range(1, 13):
            budget = 100000 + department_index * 20000
            actual = budget * (
                1.25
                if month in {6, 12} and department_index == 1
                else (0.1 if month == 1 else 0.75 + month * 0.02)
            )
            budget_rows.append(
                [department, "运营费用", f"2026-{month:02d}", budget, round(actual, 2)]
            )
    budget_rows.append(["行政部", "临时项目", "2026-07", 0, 50000])
    _write_csv(budget_path, budget_headers, budget_rows)
    expected["budgets"].append(
        {"file": budget_path.name, "expected_rules": ["FIN-BG-001", "FIN-BG-002", "FIN-BG-003"]}
    )
    commercial_path = directories["commercial"] / "purchase_contract.txt"
    commercial_path.write_text(
        """采购合同
甲方：示例制造有限公司
乙方：示例供应商有限公司
合同总金额：人民币100万元
付款方式：货到后甲方适时付款。
违约责任：乙方违约应支付合同金额30%的违约金。
甲方盖章：        乙方盖章：
""",
        encoding="utf-8",
    )
    (root_path / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "root": str(root_path.resolve()),
        "counts": {
            "劳动合同": 20,
            "岗位": 5,
            "简历": 30,
            "制度": 10,
            "会议": 20,
            "费用": 200,
            "预算": len(budget_rows),
        },
    }


def _write_csv(path: Path, headers: list[str], rows: list[list[Any]]) -> None:
    """以 Excel 兼容的 UTF-8 BOM 写入 CSV。"""

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


if __name__ == "__main__":
    print(json.dumps(generate_samples(), ensure_ascii=False, indent=2))
