"""企业审阅工作区：一个稳定入口执行所有确定性领域流程。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from enterprise.adapters.documents import parse_document
from enterprise.ai.gateway import ModelGateway
from enterprise.domains.admin import MeetingActionWorkflow, PolicyReviewWorkflow
from enterprise.domains.base import Workflow
from enterprise.domains.contract import CommercialContractWorkflow
from enterprise.domains.finance import BudgetAnalysisWorkflow, ExpenseReviewWorkflow
from enterprise.domains.hr import LaborContractWorkflow, RecruitmentMatchWorkflow

from .models import ExecutionResult
from .reporting import save_markdown_report
from .storage import EnterpriseStore


class ReviewWorkspace:
    """协调文件归档、解析、工作流执行、报告和历史记录。"""

    def __init__(
        self,
        store: EnterpriseStore | None = None,
        model_gateway: ModelGateway | None = None,
    ) -> None:
        """初始化默认仓储、模型网关和工作流注册表。"""

        self.store = store or EnterpriseStore()
        self.model_gateway = model_gateway or ModelGateway()
        workflows: list[Workflow] = [
            CommercialContractWorkflow(),
            LaborContractWorkflow(),
            RecruitmentMatchWorkflow(),
            PolicyReviewWorkflow(),
            MeetingActionWorkflow(),
            ExpenseReviewWorkflow(),
            BudgetAnalysisWorkflow(),
        ]
        self.workflows = {workflow.workflow_id: workflow for workflow in workflows}

    def catalog(self) -> list[dict[str, str]]:
        """返回 UI 可直接使用的工作流目录。"""

        return [
            {
                "id": workflow.workflow_id,
                "label": workflow.label,
                "sensitivity": workflow.sensitivity,
            }
            for workflow in self.workflows.values()
        ]

    def execute_uploads(
        self,
        workflow_id: str,
        uploads: list[tuple[str, bytes, str]],
        actor: str = "本地用户",
        title: str = "",
        options: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """保存浏览器上传内容后执行工作流。"""

        options = dict(options or {})
        workflow = self._workflow(workflow_id)
        case_title = title.strip() or f"{workflow.label} - {uploads[0][0] if uploads else '新任务'}"
        case_id = self.store.create_case(
            workflow_id,
            case_title,
            actor,
            workflow.sensitivity,
            {"files": [item[0] for item in uploads], "options": _safe_options(options)},
        )
        try:
            paths = [
                self.store.save_upload(case_id, name, content, mime)
                for name, content, mime in uploads
            ]
        except Exception as exc:
            return self._record_preparation_failure(case_id, workflow, actor, options, exc)
        return self._execute_archived(case_id, workflow, paths, actor, options)

    def execute_files(
        self,
        workflow_id: str,
        file_paths: list[str | Path],
        actor: str = "本地用户",
        title: str = "",
        options: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """归档本地文件后执行工作流，供 CLI、样本和测试使用。"""

        options = dict(options or {})
        workflow = self._workflow(workflow_id)
        names = [Path(path).name for path in file_paths]
        case_title = title.strip() or f"{workflow.label} - {names[0] if names else '新任务'}"
        case_id = self.store.create_case(
            workflow_id,
            case_title,
            actor,
            workflow.sensitivity,
            {"files": names, "options": _safe_options(options)},
        )
        try:
            paths = [self.store.archive_file(case_id, path) for path in file_paths]
        except Exception as exc:
            return self._record_preparation_failure(case_id, workflow, actor, options, exc)
        return self._execute_archived(case_id, workflow, paths, actor, options)

    def rerun(
        self, case_id: str, actor: str = "本地用户", options: dict[str, Any] | None = None
    ) -> ExecutionResult:
        """使用已保存的原始附件重新执行案件。"""

        case = self.store.get_case(case_id)
        if not case:
            raise ValueError(f"案件不存在: {case_id}")
        paths = [Path(item["stored_path"]) for item in case["artifacts"]]
        workflow = self._workflow(case["workflow_id"])
        return self._execute_archived(case_id, workflow, paths, actor, dict(options or {}))

    def _execute_archived(
        self,
        case_id: str,
        workflow: Workflow,
        paths: list[Path],
        actor: str,
        options: dict[str, Any],
    ) -> ExecutionResult:
        """执行已经归档的文件，并保证成功或失败都会写入历史。"""

        execution_id = self.store.start_execution(
            case_id, workflow.workflow_id, _safe_options(options)
        )
        try:
            documents = [parse_document(path) for path in paths]
            result = workflow.execute(documents, options, self.model_gateway)
            payload = result.to_dict()
            report_path = save_markdown_report(self.store.report_dir, case_id, execution_id, result)
            self.store.complete_execution(
                execution_id, case_id, payload, result.findings, result.model_route, actor
            )
            if workflow.workflow_id == "meeting_actions" and options.get("create_tasks", True):
                self._create_meeting_tasks(case_id, result.records)
            return ExecutionResult(
                True, case_id, execution_id, workflow.workflow_id, result, str(report_path)
            )
        except Exception as exc:
            self.store.fail_execution(execution_id, case_id, str(exc), actor)
            return ExecutionResult(
                False, case_id, execution_id, workflow.workflow_id, error=str(exc)
            )

    def _record_preparation_failure(
        self,
        case_id: str,
        workflow: Workflow,
        actor: str,
        options: dict[str, Any],
        error: Exception,
    ) -> ExecutionResult:
        """把文件归档阶段的失败也保存成可查询执行记录。"""

        execution_id = self.store.start_execution(
            case_id, workflow.workflow_id, _safe_options(options)
        )
        self.store.fail_execution(execution_id, case_id, str(error), actor)
        return ExecutionResult(False, case_id, execution_id, workflow.workflow_id, error=str(error))

    def _create_meeting_tasks(self, case_id: str, records: list[dict[str, Any]]) -> None:
        """把提取出的会议行动项同步到任务中心。"""

        for item in records:
            self.store.create_task(
                title=str(item.get("事项", "会议行动项")),
                owner=str(item.get("负责人", "")),
                due_date=str(item.get("截止日期", "")),
                priority=str(item.get("优先级", "中")),
                case_id=case_id,
                source="会议纪要",
                details=str(item.get("来源", "")),
            )

    def _workflow(self, workflow_id: str) -> Workflow:
        """查找工作流，不存在时给出可操作错误。"""

        try:
            return self.workflows[workflow_id]
        except KeyError as exc:
            supported = "、".join(self.workflows)
            raise ValueError(f"未知工作流 {workflow_id}，可选：{supported}") from exc


def _safe_options(options: dict[str, Any]) -> dict[str, Any]:
    """仅保存简单配置，防止把文件或密钥写入案件摘要。"""

    safe: dict[str, Any] = {}
    for key, value in options.items():
        if any(secret in key.lower() for secret in ("key", "token", "password", "secret")):
            safe[key] = "[已隐藏]"
        elif isinstance(value, (str, int, float, bool, list, dict, type(None))):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe
