"""财务领域工作流：费用审阅与预算分析。"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from enterprise.adapters.documents import ParsedDocument
from enterprise.ai.gateway import ModelGateway
from enterprise.core.models import Evidence, Finding, Severity, WorkflowResult
from enterprise.domains.common import number, parse_date

EXPENSE_ALIASES = {
    "单据号": ["单据号", "报销单号", "claim_id", "id"],
    "申请人": ["申请人", "报销人", "employee", "applicant"],
    "部门": ["部门", "department", "dept"],
    "费用日期": ["费用日期", "发生日期", "date", "expense_date"],
    "费用类别": ["费用类别", "类别", "category", "expense_type"],
    "金额": ["金额", "报销金额", "amount", "total"],
    "发票号": ["发票号", "发票号码", "invoice_no", "invoice"],
    "预算余额": ["预算余额", "可用预算", "budget_balance"],
    "附件": ["附件", "凭证", "receipt", "has_receipt"],
    "审批人": ["审批人", "approver"],
    "说明": ["说明", "事由", "description", "narrative"],
}

BUDGET_ALIASES = {
    "部门": ["部门", "department", "dept"],
    "科目": ["科目", "预算科目", "account", "category"],
    "期间": ["期间", "月份", "month", "period"],
    "预算": ["预算", "预算金额", "budget"],
    "实际": ["实际", "实际发生", "actual"],
}


class ExpenseReviewWorkflow:
    """使用可复算规则检查费用明细，不执行付款。"""

    workflow_id = "expense_review"
    label = "费用审阅"
    sensitivity = "L3"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """审阅所有上传表格中的费用记录。"""

        records, sources = _collect_records(documents, EXPENSE_ALIASES)
        if not records:
            raise ValueError("未从文件中读取到费用明细，请检查表头和文件格式")
        threshold = number(options.get("expense_limit", 5000)) or 5000
        findings: list[Finding] = []
        invoice_counter = Counter(
            str(row["发票号"]).strip() for row in records if str(row["发票号"]).strip()
        )
        split_groups: dict[tuple[str, str, str], list[tuple[int, float]]] = defaultdict(list)
        total = 0.0
        for index, row in enumerate(records, start=1):
            amount = number(row["金额"])
            total += amount
            row["金额"] = round(amount, 2)
            row["行号"] = index + 1
            source = sources[index - 1]
            evidence = [Evidence(source, f"数据行 {index + 1}", _row_excerpt(row))]
            invoice = str(row["发票号"] or "").strip()
            if invoice and invoice_counter[invoice] > 1:
                findings.append(
                    _finance_finding(
                        "重复报销",
                        Severity.HIGH,
                        "发票号重复",
                        f"发票号 {invoice} 出现 {invoice_counter[invoice]} 次。",
                        "FIN-EX-001",
                        "核对是否重复提交、冲销或分次报销。",
                        evidence,
                    )
                )
            if amount > threshold:
                findings.append(
                    _finance_finding(
                        "限额",
                        Severity.MEDIUM,
                        "单笔费用超过复核阈值",
                        f"单笔金额 {amount:,.2f} 超过阈值 {threshold:,.2f}。",
                        "FIN-EX-002",
                        "核对审批层级、合同/订单和付款依据。",
                        evidence,
                    )
                )
            if not invoice and amount > 0:
                findings.append(
                    _finance_finding(
                        "单据完整性",
                        Severity.MEDIUM,
                        "未填写发票号",
                        "费用记录未填写发票号或等效凭证编号。",
                        "FIN-EX-003",
                        "补充合法有效票据，或记录无票报销依据和批准。",
                        evidence,
                    )
                )
            if str(row["附件"]).strip().lower() in {"", "否", "无", "false", "0", "none"}:
                findings.append(
                    _finance_finding(
                        "单据完整性",
                        Severity.MEDIUM,
                        "缺少附件或凭证",
                        "费用记录未标记已附支持性材料。",
                        "FIN-EX-004",
                        "上传发票、行程、合同、验收等支持材料。",
                        evidence,
                    )
                )
            budget_balance = number(row["预算余额"])
            if row["预算余额"] not in (None, "") and amount > budget_balance:
                findings.append(
                    _finance_finding(
                        "预算控制",
                        Severity.HIGH,
                        "费用超过可用预算",
                        f"费用 {amount:,.2f} 高于预算余额 {budget_balance:,.2f}。",
                        "FIN-EX-005",
                        "暂停审批并确认预算调整或例外授权。",
                        evidence,
                    )
                )
            if (
                row["申请人"]
                and row["审批人"]
                and str(row["申请人"]).strip() == str(row["审批人"]).strip()
            ):
                findings.append(
                    _finance_finding(
                        "审批冲突",
                        Severity.HIGH,
                        "申请人与审批人相同",
                        "同一人员同时作为费用申请人和审批人。",
                        "FIN-EX-006",
                        "转交独立、有权限的审批人复核。",
                        evidence,
                    )
                )
            parsed_date = parse_date(row["费用日期"])
            if parsed_date and parsed_date > __import__("datetime").date.today():
                findings.append(
                    _finance_finding(
                        "日期异常",
                        Severity.HIGH,
                        "费用日期晚于当前日期",
                        f"费用日期为 {parsed_date}。",
                        "FIN-EX-007",
                        "核对日期录入、预付款性质和支持材料。",
                        evidence,
                    )
                )
            key = (str(row["申请人"]), str(row["费用日期"]), str(row["费用类别"]))
            split_groups[key].append((index, amount))
        for key, values in split_groups.items():
            if (
                len(values) >= 2
                and sum(value for _, value in values) > threshold
                and all(value <= threshold for _, value in values)
            ):
                indices = [index + 1 for index, _ in values]
                findings.append(
                    _finance_finding(
                        "拆分报销",
                        Severity.HIGH,
                        "同日同类费用可能拆分提交",
                        f"{key[0]} 在 {key[1]} 的 {key[2]} 共 {len(values)} 笔，合计 {sum(v for _, v in values):,.2f}。",
                        "FIN-EX-008",
                        "结合行程、供应商、事项和审批阈值人工复核。",
                        [
                            Evidence(
                                "费用明细",
                                f"数据行 {indices}",
                                "；".join(str(records[i - 1]) for i in indices),
                            )
                        ],
                    )
                )
        duplicate_findings = _deduplicate_findings(findings)
        by_category: dict[str, float] = defaultdict(float)
        by_department: dict[str, float] = defaultdict(float)
        for row in records:
            by_category[str(row["费用类别"] or "未分类")] += number(row["金额"])
            by_department[str(row["部门"] or "未填写")] += number(row["金额"])
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=f"费用审阅 - {Path(documents[0].name).stem}",
            summary=f"已复算 {len(records)} 笔费用，金额合计 {total:,.2f}，识别 {len(duplicate_findings)} 条待复核事项。系统不会执行付款。",
            fields={
                "审阅阈值": threshold,
                "费用类别汇总": dict(by_category),
                "部门汇总": dict(by_department),
            },
            records=records,
            metrics={
                "费用笔数": len(records),
                "费用总额": round(total, 2),
                "高风险": sum(item.severity == Severity.HIGH for item in duplicate_findings),
                "重复发票数": sum(count > 1 for count in invoice_counter.values()),
            },
            findings=duplicate_findings,
            suggested_actions=[
                "财务复核重复票据和高风险记录",
                "业务负责人补齐说明和附件",
                "人工审批完成后再进入付款系统",
            ],
        )
        _finance_ai_summary(result, documents, options, model_gateway)
        return result


class BudgetAnalysisWorkflow:
    """从预算与实际表中进行权威确定性计算，并生成管理提示。"""

    workflow_id = "budget_analysis"
    label = "预算分析"
    sensitivity = "L3"

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """按部门、科目和期间计算预算执行差异。"""

        records, sources = _collect_records(documents, BUDGET_ALIASES)
        if not records:
            raise ValueError("未从文件中读取到预算与实际数据")
        findings: list[Finding] = []
        total_budget = 0.0
        total_actual = 0.0
        rates: list[float] = []
        for index, row in enumerate(records, start=1):
            budget = number(row["预算"])
            actual = number(row["实际"])
            variance = actual - budget
            rate = actual / budget * 100 if budget else (100.0 if actual else 0.0)
            total_budget += budget
            total_actual += actual
            rates.append(rate)
            row.update(
                {
                    "预算": round(budget, 2),
                    "实际": round(actual, 2),
                    "差异": round(variance, 2),
                    "执行率%": round(rate, 1),
                    "余额": round(budget - actual, 2),
                }
            )
            evidence = [Evidence(sources[index - 1], f"数据行 {index + 1}", _row_excerpt(row))]
            if budget == 0 and actual > 0:
                findings.append(
                    _finance_finding(
                        "无预算支出",
                        Severity.HIGH,
                        "零预算科目发生支出",
                        f"{row['部门']}/{row['科目']} 实际发生 {actual:,.2f}。",
                        "FIN-BG-001",
                        "核对预算归属、预算调整和例外授权。",
                        evidence,
                    )
                )
            elif rate > 100:
                severity = Severity.HIGH if rate >= 120 else Severity.MEDIUM
                findings.append(
                    _finance_finding(
                        "预算超支",
                        severity,
                        "预算执行超过 100%",
                        f"{row['部门']}/{row['科目']} 执行率 {rate:.1f}%，超支 {variance:,.2f}。",
                        "FIN-BG-002",
                        "分析驱动因素并确认预算调整、控费或业务例外。",
                        evidence,
                    )
                )
            elif budget > 0 and rate < 20:
                findings.append(
                    _finance_finding(
                        "预算闲置",
                        Severity.LOW,
                        "预算执行率较低",
                        f"{row['部门']}/{row['科目']} 执行率仅 {rate:.1f}%。",
                        "FIN-BG-003",
                        "确认项目延期、预算高估或资金可重新配置。",
                        evidence,
                    )
                )
        total_variance = total_actual - total_budget
        execution_rate = total_actual / total_budget * 100 if total_budget else 0.0
        department_summary: dict[str, dict[str, float]] = defaultdict(
            lambda: {"预算": 0.0, "实际": 0.0}
        )
        for row in records:
            department = str(row["部门"] or "未填写")
            department_summary[department]["预算"] += number(row["预算"])
            department_summary[department]["实际"] += number(row["实际"])
        for summary in department_summary.values():
            summary["差异"] = round(summary["实际"] - summary["预算"], 2)
            summary["执行率%"] = (
                round(summary["实际"] / summary["预算"] * 100, 1) if summary["预算"] else 0.0
            )
            summary["预算"] = round(summary["预算"], 2)
            summary["实际"] = round(summary["实际"], 2)
        result = WorkflowResult(
            workflow_id=self.workflow_id,
            title=f"预算分析 - {Path(documents[0].name).stem}",
            summary=f"已分析 {len(records)} 条预算数据。总预算 {total_budget:,.2f}，实际 {total_actual:,.2f}，执行率 {execution_rate:.1f}%，差异 {total_variance:,.2f}。所有金额由本地规则计算。",
            fields={"部门汇总": dict(department_summary)},
            records=records,
            metrics={
                "总预算": round(total_budget, 2),
                "实际发生": round(total_actual, 2),
                "执行率%": round(execution_rate, 1),
                "预算差异": round(total_variance, 2),
                "超支项目": sum(number(row["实际"]) > number(row["预算"]) for row in records),
                "平均行执行率%": round(mean(rates), 1) if rates else 0,
            },
            findings=findings,
            suggested_actions=[
                "部门负责人解释超支和低执行项目",
                "财务确认预测和预算调整需求",
                "所有预算变更须走人工批准流程",
            ],
        )
        _finance_ai_summary(result, documents, options, model_gateway)
        return result


def _collect_records(
    documents: list[ParsedDocument], aliases: dict[str, list[str]]
) -> tuple[list[dict[str, Any]], list[str]]:
    """汇总所有表格，并按别名映射为规范字段。"""

    normalized: list[dict[str, Any]] = []
    sources: list[str] = []
    for document in documents:
        for table in document.tables:
            for row in table:
                normalized.append(_normalize_row(row, aliases))
                sources.append(document.name)
    return normalized, sources


def _normalize_row(row: dict[str, Any], aliases: dict[str, list[str]]) -> dict[str, Any]:
    """把中英文常见表头映射成统一业务字段。"""

    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    output: dict[str, Any] = {}
    for canonical, names in aliases.items():
        output[canonical] = next(
            (lowered[name.lower()] for name in names if name.lower() in lowered), ""
        )
    return output


def _finance_finding(
    category: str,
    severity: Severity,
    title: str,
    description: str,
    rule_id: str,
    recommendation: str,
    evidence: list[Evidence],
) -> Finding:
    """构造财务发现项。"""

    return Finding(
        category, severity, title, description, evidence, rule_id, "1.0", 1.0, recommendation
    )


def _row_excerpt(row: dict[str, Any]) -> str:
    """生成适合证据卡片显示的紧凑行摘要。"""

    return "；".join(f"{key}={value}" for key, value in row.items() if value not in (None, ""))[
        :500
    ]


def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """避免同一规则、标题和证据重复展示。"""

    seen: set[tuple[str, str, str]] = set()
    result: list[Finding] = []
    for item in findings:
        locator = item.evidence[0].locator if item.evidence else ""
        key = (item.rule_id, item.title, locator)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _finance_ai_summary(
    result: WorkflowResult,
    documents: list[ParsedDocument],
    options: dict[str, Any],
    gateway: ModelGateway,
) -> None:
    """让模型解释规则结果，但禁止模型重算权威数字。"""

    if not options.get("use_ai", True):
        return
    content = "\n\n".join(document.text[:5000] for document in documents)
    response = gateway.run_json(
        task=result.workflow_id,
        system_prompt='你是财务管理助手。只返回 JSON：{"management_summary":"..."}。不得重算金额，不得批准费用、付款或预算调整。',
        user_content=f"材料节选：\n{content}\n\n本地确定性计算结果：{result.summary}",
        sensitivity=str(options.get("_sensitivity", "L3")),
        allow_external=bool(options.get("allow_external", False)),
    )
    if response.success and response.data and response.data.get("management_summary"):
        result.summary += f"\n\nAI 管理摘要：{response.data['management_summary']}"
        result.model_route = response.route
    elif response.error:
        result.warnings.append(response.error)
