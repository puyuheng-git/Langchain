"""领域工作流协议。"""

from __future__ import annotations

from typing import Any, Protocol

from enterprise.adapters.documents import ParsedDocument
from enterprise.ai.gateway import ModelGateway
from enterprise.core.models import WorkflowResult


class Workflow(Protocol):
    """所有确定性业务流程需要实现的最小接口。"""

    workflow_id: str
    label: str
    sensitivity: str

    def execute(
        self,
        documents: list[ParsedDocument],
        options: dict[str, Any],
        model_gateway: ModelGateway,
    ) -> WorkflowResult:
        """执行领域分析并返回统一结果。"""

        ...
