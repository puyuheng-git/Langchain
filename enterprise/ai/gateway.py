"""本地优先的模型网关。

领域工作流不得直接实例化 OpenAI 客户端。网关统一执行敏感等级检查、脱敏、
超时控制和结构化 JSON 解析。任何 L2/L3 数据都不会静默回退到外部模型。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from enterprise.core.settings import merge_system_settings


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

    def __init__(
        self,
        settings_provider: Callable[[], dict[str, Any]] | None = None,
        event_store: Any = None,
    ) -> None:
        """绑定动态配置提供器和可选运行事件仓储。"""

        self.settings_provider = settings_provider or (lambda: {})
        self.event_store = event_store

    def settings(self) -> dict[str, Any]:
        """返回环境默认值与页面保存值合并后的实时配置。"""

        return merge_system_settings(self.settings_provider())

    def status(self) -> dict[str, Any]:
        """返回不包含密钥的模型配置和本地服务可达状态。"""

        config = self.settings()
        reachable = False
        error = ""
        if not config["local_enabled"]:
            error = "本地模型已停用"
        else:
            try:
                import requests

                root_url = str(config["local_base_url"]).removesuffix("/v1")
                response = requests.get(f"{root_url}/api/tags", timeout=2)
                reachable = response.ok
                if not response.ok:
                    error = f"HTTP {response.status_code}"
            except Exception as exc:  # 网络状态只用于诊断，不影响确定性功能。
                error = str(exc)
        return {
            "local_enabled": bool(config["local_enabled"]),
            "local_base_url": config["local_base_url"],
            "local_model": config["local_model"],
            "local_key_configured": bool(config["local_api_key"]),
            "local_reachable": reachable,
            "local_error": error,
            "external_enabled": bool(config["external_enabled"]),
            "external_provider": config["external_provider"],
            "external_base_url": config["external_base_url"],
            "external_model": config["external_model"],
            "external_key_configured": bool(config["external_api_key"]),
            "model_timeout": config["model_timeout"],
        }

    def run_json(
        self,
        task: str,
        system_prompt: str,
        user_content: str,
        sensitivity: str,
        allow_external: bool = False,
    ) -> ModelResponse:
        """按实时安全策略调用本地模型，并决定是否允许外部回退。"""

        config = self.settings()
        if config["local_enabled"]:
            local = self._call_openai_compatible(
                task=task,
                base_url=str(config["local_base_url"]),
                api_key=str(config["local_api_key"] or "ollama"),
                model=str(config["local_model"]),
                system_prompt=system_prompt,
                user_content=user_content,
                route="local",
                provider="local",
                timeout=float(config["model_timeout"]),
                sensitivity=sensitivity,
            )
        else:
            self._record_model_decision(
                task,
                "local",
                "skipped",
                str(config["local_model"]),
                sensitivity,
                "本地模型已停用",
            )
            local = ModelResponse(False, "deterministic", error="本地模型已停用")
        if local.success:
            return local
        if not allow_external:
            return ModelResponse(
                success=False,
                route="deterministic",
                error=f"本地模型不可用，已按策略停止模型调用：{local.error}",
            )
        level = config["security_levels"].get(sensitivity)
        if not level:
            self._record_model_decision(
                task, "gateway", "blocked", "", sensitivity, "未知敏感等级，禁止外发"
            )
            return ModelResponse(False, "deterministic", error="未知敏感等级，禁止外发")
        policy = level.get("policy", "local_only")
        if policy == "local_only":
            self._record_model_decision(
                task,
                str(config["external_provider"]),
                "blocked",
                str(config["external_model"]),
                sensitivity,
                f"{sensitivity} 当前配置为仅本地处理",
            )
            return ModelResponse(False, "deterministic", error=f"{sensitivity} 当前配置为仅本地处理")
        if policy not in {"redacted_external", "external_allowed"}:
            self._record_model_decision(
                task,
                "gateway",
                "blocked",
                "",
                sensitivity,
                f"未知模型路由策略: {policy}",
            )
            return ModelResponse(False, "deterministic", error="未知模型路由策略，禁止外发")
        if not config["external_enabled"]:
            self._record_model_decision(
                task,
                str(config["external_provider"]),
                "skipped",
                str(config["external_model"]),
                sensitivity,
                "外部模型已停用",
            )
            return ModelResponse(False, "deterministic", error="外部模型已停用")
        external_content, counts = redact_text(user_content)
        route = "external-redacted"
        external = self._external_call(
            config,
            task,
            system_prompt,
            external_content,
            route,
            sensitivity,
        )
        external.redacted = True
        if external.success and counts:
            external.text = f"脱敏统计: {counts}\n{external.text}".strip()
        return external

    def _external_call(
        self,
        config: dict[str, Any],
        task: str,
        system_prompt: str,
        user_content: str,
        route: str,
        sensitivity: str,
    ) -> ModelResponse:
        """使用页面配置调用 OpenAI 兼容外部服务。"""

        api_key = str(config["external_api_key"] or "")
        if not api_key or api_key.startswith("your_"):
            self._record_model_decision(
                task,
                str(config["external_provider"]),
                route,
                str(config["external_model"]),
                sensitivity,
                "外部模型密钥未配置",
            )
            return ModelResponse(False, "deterministic", error="外部模型密钥未配置")
        return self._call_openai_compatible(
            task=task,
            base_url=str(config["external_base_url"]),
            api_key=api_key,
            model=str(config["external_model"]),
            system_prompt=system_prompt,
            user_content=user_content,
            route=route,
            provider=str(config["external_provider"]),
            timeout=float(config["model_timeout"]),
            sensitivity=sensitivity,
        )

    def _call_openai_compatible(
        self,
        task: str,
        base_url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_content: str,
        route: str,
        provider: str,
        timeout: float,
        sensitivity: str = "",
    ) -> ModelResponse:
        """执行一次 OpenAI 兼容调用，并记录模型、路线、耗时和结果。"""

        event_id = ""
        started = time.monotonic()
        if self.event_store:
            try:
                event_id = self.event_store.start_runtime_event(
                    category="model",
                    event_type=task,
                    title=f"模型调用｜{task}",
                    actor="system",
                    details={
                        "task": task,
                        "provider": provider,
                        "route": route,
                        "base_url": base_url,
                        "model": model,
                        "sensitivity": sensitivity,
                        "redacted": route == "external-redacted",
                    },
                )
            except Exception:
                event_id = ""
        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
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
            result = ModelResponse(True, route, data=data, text=text)
            if event_id:
                try:
                    self.event_store.complete_runtime_event(
                        event_id,
                        "成功",
                        {"duration_ms": round((time.monotonic() - started) * 1000)},
                    )
                except Exception:
                    pass
            return result
        except Exception as exc:
            if event_id:
                try:
                    self.event_store.complete_runtime_event(
                        event_id,
                        "失败",
                        {
                            "duration_ms": round((time.monotonic() - started) * 1000),
                            "error": str(exc),
                        },
                    )
                except Exception:
                    pass
            return ModelResponse(False, route, error=str(exc))

    def _record_model_decision(
        self,
        task: str,
        provider: str,
        route: str,
        model: str,
        sensitivity: str,
        reason: str,
    ) -> None:
        """记录因配置而跳过或阻止的模型调用尝试。"""

        if not self.event_store:
            return
        try:
            event_id = self.event_store.start_runtime_event(
                category="model",
                event_type=task,
                title=f"模型调用｜{task}",
                actor="system",
                details={
                    "task": task,
                    "provider": provider,
                    "route": route,
                    "model": model,
                    "sensitivity": sensitivity,
                    "reason": reason,
                },
            )
            self.event_store.complete_runtime_event(event_id, "跳过", {"error": reason})
        except Exception:
            pass


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
