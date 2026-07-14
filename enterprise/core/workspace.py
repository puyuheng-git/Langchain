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

from .catalog import WORKFLOW_DEPARTMENTS
from .knowledge import KnowledgeBase, build_analysis_query, compare_analysis_matches
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
        self.knowledge = KnowledgeBase(self.store)
        self.model_gateway = model_gateway or ModelGateway(
            settings_provider=self.store.get_system_settings,
            event_store=self.store,
        )
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

        configured = self.model_gateway.settings()["workflow_sensitivity"]
        return [
            {
                "id": workflow.workflow_id,
                "label": workflow.label,
                "sensitivity": configured.get(workflow.workflow_id, workflow.sensitivity),
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
        sensitivity = self._workflow_sensitivity(workflow)
        options["_sensitivity"] = sensitivity
        case_title = title.strip() or f"{workflow.label} - {uploads[0][0] if uploads else '新任务'}"
        case_id = self.store.create_case(
            workflow_id,
            case_title,
            actor,
            sensitivity,
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
        sensitivity = self._workflow_sensitivity(workflow)
        options["_sensitivity"] = sensitivity
        names = [Path(path).name for path in file_paths]
        case_title = title.strip() or f"{workflow.label} - {names[0] if names else '新任务'}"
        case_id = self.store.create_case(
            workflow_id,
            case_title,
            actor,
            sensitivity,
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
        rerun_options = dict(options or {})
        rerun_options["_sensitivity"] = self._workflow_sensitivity(workflow)
        return self._execute_archived(case_id, workflow, paths, actor, rerun_options)

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
            if options.get("knowledge_enabled", True):
                department = WORKFLOW_DEPARTMENTS[workflow.workflow_id]
                default_limit = int(self.model_gateway.settings()["knowledge_default_limit"])
                result.knowledge_matches = compare_analysis_matches(
                    result,
                    self.knowledge.search(
                        build_analysis_query(result, documents),
                        departments=[department, "公司级"],
                        document_types=options.get("knowledge_types") or None,
                        limit=int(options.get("knowledge_limit", default_limit)),
                        exclude_source_ref=case_id,
                    ),
                    documents,
                )
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

    def update_case_status(self, case_id: str, status: str, actor: str) -> None:
        """更新案件状态，并仅把负责人确认后的案件沉淀为历史记忆。"""

        self.store.update_case_status(case_id, status, actor)
        if status not in {"已确认", "已关闭"}:
            return
        case = self.store.get_case(case_id)
        if not case or not case["executions"] or not case["executions"][0].get("result"):
            return
        latest_execution = case["executions"][0]
        result = latest_execution["result"]
        latest_findings = [
            item
            for item in case["findings"]
            if item["execution_id"] == latest_execution["id"]
            and item["review_status"] in {"已接受", "已整改"}
        ]
        try:
            self.knowledge.remember_case(
                case_id,
                case["workflow_id"],
                result.get("title") or case["title"],
                result.get("summary", ""),
                latest_findings,
                actor,
            )
        except Exception as memory_error:
            self.store.log(
                actor,
                "memory_failure",
                "case",
                case_id,
                {"error": str(memory_error)},
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

    def _workflow_sensitivity(self, workflow: Workflow) -> str:
        """读取页面配置的工作流安全等级，异常值回退到代码默认值。"""

        configured = self.model_gateway.settings()["workflow_sensitivity"].get(
            workflow.workflow_id, workflow.sensitivity
        )
        return configured if configured in {"L1", "L2", "L3"} else workflow.sensitivity


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
