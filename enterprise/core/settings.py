"""企业工作台可持久化运行配置的默认值与选项。"""

from __future__ import annotations

import os
from typing import Any

SECURITY_POLICY_OPTIONS = {
    "local_only": "仅本地处理",
    "redacted_external": "本地失败后允许脱敏外发",
    "external_allowed": "允许外部调用（仍执行基础脱敏）",
}

SECRET_SETTING_KEYS = {"local_api_key", "external_api_key"}


def default_system_settings() -> dict[str, Any]:
    """根据环境变量生成首次启动配置，数据库配置可覆盖这些值。"""

    provider = os.getenv("ENTERPRISE_EXTERNAL_PROVIDER", "deepseek")
    if provider.lower() == "openai":
        external_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        external_api_key = os.getenv("OPENAI_API_KEY", "")
        external_model = os.getenv("ENTERPRISE_EXTERNAL_MODEL", "gpt-4o-mini")
    else:
        external_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        external_api_key = os.getenv("DEEPSEEK_API_KEY", "")
        external_model = os.getenv("ENTERPRISE_EXTERNAL_MODEL", "deepseek-chat")
    return {
        "security_levels": {
            "L1": {
                "name": "公开/低敏资料",
                "description": "公开岗位说明、公开制度和通用写作材料。",
                "policy": "external_allowed",
            },
            "L2": {
                "name": "内部资料",
                "description": "内部制度、会议纪要、一般合同和经营材料。",
                "policy": "redacted_external",
            },
            "L3": {
                "name": "敏感业务资料",
                "description": "员工、简历、薪酬、发票、费用和未发布预算。",
                "policy": "local_only",
            },
        },
        "workflow_sensitivity": {
            "commercial_contract": "L2",
            "labor_contract": "L3",
            "recruitment_match": "L3",
            "policy_review": "L2",
            "meeting_actions": "L2",
            "expense_review": "L3",
            "budget_analysis": "L3",
        },
        "local_enabled": True,
        "local_base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        "local_api_key": os.getenv("OLLAMA_API_KEY", "ollama"),
        "local_model": os.getenv("OLLAMA_MODEL", "qwen2.5:7b"),
        "external_enabled": bool(external_api_key),
        "external_provider": provider,
        "external_base_url": external_base_url,
        "external_api_key": external_api_key,
        "external_model": external_model,
        "model_timeout": float(os.getenv("ENTERPRISE_MODEL_TIMEOUT", "20")),
        "knowledge_default_limit": 6,
    }


def merge_system_settings(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """合并环境默认值和数据库覆盖值，并保留未配置的安全等级字段。"""

    settings = default_system_settings()
    overrides = dict(overrides or {})
    security_overrides = overrides.pop("security_levels", {})
    settings.update(overrides)
    for level, values in security_overrides.items():
        if level in settings["security_levels"] and isinstance(values, dict):
            settings["security_levels"][level].update(values)
    return settings
