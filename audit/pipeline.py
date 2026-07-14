#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旧 `/review` 命令的兼容适配器。

实际业务逻辑已迁移到统一 ReviewWorkspace。CLI 仍可使用，但所有上传和结果也会写入
企业工作台数据库，业务人员可以随后在 Web 历史页面查看。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from enterprise import ReviewWorkspace


class ContractReviewPipeline:
    """把旧合同审阅返回结构映射到统一商业合同工作流。"""

    def __init__(self, workspace: ReviewWorkspace | None = None) -> None:
        """惰性创建统一工作区，不在初始化时发起任何模型请求。"""

        self.workspace = workspace or ReviewWorkspace()

    def review(self, file_path: str, save_report: bool = True) -> dict[str, Any]:
        """审阅单份合同并返回旧接口兼容字典。"""

        use_ai = os.getenv("LLM_PROVIDER", "").lower() == "ollama"
        execution = self.workspace.execute_files(
            "commercial_contract",
            [file_path],
            actor="CLI 用户",
            options={"use_ai": use_ai, "allow_external": False},
        )
        if not execution.success or not execution.result:
            print(f"[失败] {Path(file_path).name}: {execution.error}")
            return {
                "success": False,
                "file_name": Path(file_path).name,
                "contract": None,
                "extraction": None,
                "risks": None,
                "report_path": None,
                "error": execution.error,
            }
        result = execution.result
        risks = [
            {
                "level": item.severity.value,
                "clause": item.title,
                "reason": item.description,
                "suggestion": item.recommendation,
                "category": item.category,
                "rule_id": item.rule_id,
            }
            for item in result.findings
        ]
        print(f"\n合同审阅完成: {result.title}")
        print(result.summary)
        for item in risks:
            print(f"  [{item['level']}] {item['clause']} - {item['suggestion']}")
        print(f"报告: {execution.report_path}")
        return {
            "success": True,
            "file_name": Path(file_path).name,
            "contract": {"file_name": Path(file_path).name, "case_id": execution.case_id},
            "extraction": {"success": True, "fields": result.fields, "error": None},
            "risks": {"success": True, "risks": risks, "error": None},
            "report_path": execution.report_path if save_report else None,
            "case_id": execution.case_id,
            "error": None,
        }

    def review_batch(self, directory: str, save_report: bool = True) -> dict[str, Any]:
        """批量审阅目录中的受支持合同，每份单独归档为案件。"""

        directory_path = Path(directory)
        if not directory_path.is_dir():
            return {"success": False, "results": [], "error": f"目录不存在: {directory}"}
        supported = {".pdf", ".docx", ".txt", ".md"}
        files = sorted(
            path
            for path in directory_path.iterdir()
            if path.is_file() and path.suffix.lower() in supported
        )
        if not files:
            return {"success": False, "results": [], "error": "目录中没有受支持的合同文件"}
        results = [self.review(str(path), save_report=save_report) for path in files]
        successful = [item for item in results if item["success"]]
        print(f"\n批量完成: {len(successful)}/{len(results)} 份成功，结果已进入企业工作台历史。")
        return {
            "success": bool(successful),
            "results": results,
            "total": len(results),
            "success_count": len(successful),
            "failed_count": len(results) - len(successful),
            "report_path": None,
            "error": None if successful else "全部合同审阅失败",
        }
