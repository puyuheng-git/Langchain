"""本地优先的模型网关。

领域工作流不得直接实例化 OpenAI 客户端。网关统一执行敏感等级检查、脱敏、
超时控制和结构化 JSON 解析。任何 L2/L3 数据都不会静默回退到外部模型。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ModelResponse:
    """模型调用的可审计结果。"""

    success: bool
    route: str
    data: dict[str, Any] | None = None
    text: str = ""
    error: str = ""
    redacted: bool = False


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """脱敏常见身份、联系方式、账号和金额信息。"""

    patterns = {
        "身份证": r"(?<!\d)\d{17}[\dXx](?!\d)",
        "手机号": r"(?<!\d)1[3-9]\d{9}(?!\d)",
        "邮箱": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "银行卡": r"(?<!\d)\d{16,19}(?!\d)",
        "金额": r"(?:人民币|RMB|¥|￥)\s*[\d,]+(?:\.\d{1,2})?",
        "姓名或主体": r"(?m)((?:姓名|员工|劳动者|申请人|报销人|候选人|甲方|乙方|用人单位|公司名称)[^：:\n]{0,12}[：:]\s*)[^\n，,；;]+",
        "薪酬费用预算": r"((?:工资|月薪|薪酬|报销金额|费用金额|预算金额|实际发生)[^：:\n]{0,12}[：:]?\s*)(?:人民币|RMB|¥|￥)?\s*[\d,]+(?:\.\d{1,2})?",
        "发票单据": r"((?:发票号|发票号码|单据号|报销单号)[：:]\s*)[A-Za-z0-9_-]+",
    }
    counts: dict[str, int] = {}
    redacted = text
    for label, pattern in patterns.items():
        if label in {"姓名或主体", "薪酬费用预算", "发票单据"}:
            redacted, count = re.subn(pattern, rf"\1[{label}已脱敏]", redacted)
        else:
            redacted, count = re.subn(pattern, f"[{label}已脱敏]", redacted)
        counts[label] = count
    return redacted, counts


class ModelGateway:
    """封装 Ollama 本地模型和显式授权后的外部模型。"""

    def __init__(self) -> None:
        """从环境变量读取模型路由配置。"""

        self.local_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.local_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.external_provider = os.getenv("ENTERPRISE_EXTERNAL_PROVIDER", "deepseek")
        self.timeout = float(os.getenv("ENTERPRISE_MODEL_TIMEOUT", "20"))

    def status(self) -> dict[str, Any]:
        """返回不包含密钥的模型配置和本地服务可达状态。"""

        reachable = False
        error = ""
        try:
            import requests

            root_url = self.local_base_url.removesuffix("/v1")
            response = requests.get(f"{root_url}/api/tags", timeout=2)
            reachable = response.ok
            if not response.ok:
                error = f"HTTP {response.status_code}"
        except Exception as exc:  # 网络状态只用于诊断，不影响确定性功能。
            error = str(exc)
        return {
            "local_base_url": self.local_base_url,
            "local_model": self.local_model,
            "local_reachable": reachable,
            "local_error": error,
            "external_provider": self.external_provider,
        }

    def run_json(
        self,
        task: str,
        system_prompt: str,
        user_content: str,
        sensitivity: str,
        allow_external: bool = False,
    ) -> ModelResponse:
        """先调用本地模型，失败后仅按明确授权规则决定是否调用外部模型。"""

        local = self._call_openai_compatible(
            base_url=self.local_base_url,
            api_key="ollama",
            model=self.local_model,
            system_prompt=system_prompt,
            user_content=user_content,
            route="local",
        )
        if local.success:
            return local
        if not allow_external:
            return ModelResponse(
                success=False,
                route="deterministic",
                error=f"本地模型不可用，已按策略停止模型调用：{local.error}",
            )
        if sensitivity not in {"L1", "L2", "L3"}:
            return ModelResponse(False, "deterministic", error="未知敏感等级，禁止外发")
        redacted_content, counts = redact_text(user_content)
        external = self._external_call(system_prompt, redacted_content)
        external.redacted = True
        if external.success:
            external.text = f"脱敏统计: {counts}\n{external.text}".strip()
        return external

    def _external_call(self, system_prompt: str, user_content: str) -> ModelResponse:
        """调用显式配置的 OpenAI 兼容外部服务。"""

        provider = self.external_provider.lower()
        if provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY", "")
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            model = os.getenv(
                "ENTERPRISE_EXTERNAL_MODEL", os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
            )
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY", "")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
            model = os.getenv("ENTERPRISE_EXTERNAL_MODEL", "deepseek-chat")
        if not api_key or api_key.startswith("your_"):
            return ModelResponse(False, "deterministic", error="外部模型密钥未配置")
        return self._call_openai_compatible(
            base_url=base_url,
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_content=user_content,
            route="external-redacted",
        )

    def _call_openai_compatible(
        self,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_content: str,
        route: str,
    ) -> ModelResponse:
        """执行一次 OpenAI 兼容的非流式 JSON 调用。"""

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.timeout, max_retries=0)
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            text = response.choices[0].message.content or ""
            data = _extract_json(text)
            return ModelResponse(True, route, data=data, text=text)
        except Exception as exc:
            return ModelResponse(False, route, error=str(exc))


def _extract_json(text: str) -> dict[str, Any] | None:
    """从纯 JSON 或 Markdown 代码块中提取对象。"""

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
        return payload if isinstance(payload, dict) else {"items": payload}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
            return payload if isinstance(payload, dict) else None
        except json.JSONDecodeError:
            return None
