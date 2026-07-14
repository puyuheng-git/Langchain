"""系统配置、模型路由与运行监控测试。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from enterprise import EnterpriseStore, ReviewWorkspace
from enterprise.ai.gateway import ModelGateway
from enterprise.core.settings import default_system_settings


def test_system_settings_persist_and_override_environment_defaults(tmp_path: Path) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    settings = default_system_settings()
    settings.update(
        {
            "local_base_url": "http://model.local/v1",
            "local_api_key": "local-secret",
            "local_model": "qwen-custom",
            "external_enabled": True,
            "external_base_url": "https://external.example/v1",
            "external_api_key": "external-secret",
            "external_model": "external-model",
            "model_timeout": 35.0,
        }
    )

    store.save_system_settings(settings, actor="系统管理员")
    workspace = ReviewWorkspace(store)
    resolved = workspace.model_gateway.settings()

    assert resolved["local_base_url"] == "http://model.local/v1"
    assert resolved["local_api_key"] == "local-secret"
    assert resolved["external_base_url"] == "https://external.example/v1"
    assert resolved["external_api_key"] == "external-secret"
    assert resolved["model_timeout"] == 35.0
    assert b"external-secret" not in store.db_path.read_bytes()
    secret_files = list((store.root / "secrets").glob("*.secret"))
    assert secret_files
    assert all(b"external-secret" not in path.read_bytes() for path in secret_files)


@pytest.mark.parametrize("policy", ["redacted_external", "external_allowed"])
def test_model_gateway_applies_security_policy_and_records_call(
    tmp_path: Path, monkeypatch, policy: str
) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    settings = default_system_settings()
    settings.update(
        {
            "local_enabled": False,
            "external_enabled": True,
            "external_provider": "custom",
            "external_base_url": "https://external.example/v1",
            "external_api_key": "secret-key",
            "external_model": "analysis-model",
            "security_levels": {
                **settings["security_levels"],
                "L2": {
                    "name": "内部资料",
                    "description": "外发前脱敏",
                    "policy": policy,
                },
            },
        }
    )
    store.save_system_settings(settings, actor="系统管理员")
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content='{"management_summary":"ok"}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    gateway = ModelGateway(settings_provider=store.get_system_settings, event_store=store)

    response = gateway.run_json(
        task="policy_summary",
        system_prompt="return json",
        user_content="申请人：张三，手机13800138000",
        sensitivity="L2",
        allow_external=True,
    )

    assert response.success
    assert response.route == "external-redacted"
    assert "13800138000" not in captured["messages"][1]["content"]
    assert captured["client"]["base_url"] == "https://external.example/v1"
    events = store.list_runtime_events(category="model")
    successful = [item for item in events if item["status"] == "成功"]
    assert len(successful) == 1
    assert successful[0]["details"]["model"] == "analysis-model"
    assert any(item["status"] == "跳过" for item in events)
    assert "secret-key" not in str(events)


def test_runtime_events_expose_running_and_completed_tasks(tmp_path: Path) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    event_id = store.start_runtime_event(
        category="operation",
        event_type="knowledge_rebuild",
        title="重建知识索引",
        actor="系统管理员",
        details={"document_count": 12},
    )

    running = store.list_runtime_events(status="运行中")
    assert [item["id"] for item in running] == [event_id]

    store.complete_runtime_event(
        event_id,
        status="成功",
        details={"document_count": 12, "processed": 12},
    )

    assert not store.list_runtime_events(status="运行中")
    completed = store.list_runtime_events(category="operation")
    assert completed[0]["status"] == "成功"
    assert completed[0]["details"]["processed"] == 12


def test_unknown_security_policy_fails_closed(tmp_path: Path, monkeypatch) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    settings = default_system_settings()
    settings.update(
        {
            "local_enabled": False,
            "external_enabled": True,
            "external_api_key": "secret-key",
            "security_levels": {
                **settings["security_levels"],
                "L2": {"name": "内部", "description": "", "policy": "invalid-policy"},
            },
        }
    )
    store.save_system_settings(settings, actor="系统管理员")
    called = False

    class FailIfCalled:
        def __init__(self, **kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr("openai.OpenAI", FailIfCalled)
    gateway = ModelGateway(settings_provider=store.get_system_settings, event_store=store)

    response = gateway.run_json("test", "system", "内部材料", "L2", allow_external=True)

    assert not response.success
    assert "未知模型路由策略" in response.error
    assert not called


def test_workflow_sensitivity_mapping_changes_new_cases(tmp_path: Path) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    settings = default_system_settings()
    settings["workflow_sensitivity"]["commercial_contract"] = "L1"
    store.save_system_settings(settings, actor="系统管理员")
    workspace = ReviewWorkspace(store)

    execution = workspace.execute_uploads(
        "commercial_contract",
        [("contract.txt", "采购合同\n甲方：A\n乙方：B".encode(), "text/plain")],
        options={"use_ai": False},
    )

    assert execution.success
    assert store.get_case(execution.case_id)["sensitivity"] == "L1"
    assert next(item for item in workspace.catalog() if item["id"] == "commercial_contract")[
        "sensitivity"
    ] == "L1"
    settings["workflow_sensitivity"]["commercial_contract"] = "L3"
    store.save_system_settings(settings, actor="系统管理员")

    rerun = workspace.rerun(execution.case_id, options={"use_ai": False})

    assert rerun.success
    assert store.get_execution(rerun.execution_id)["options"]["_sensitivity"] == "L3"
    assert store.get_case(execution.case_id)["executions"][0]["id"] == rerun.execution_id


def test_stale_running_event_is_marked_interrupted(tmp_path: Path) -> None:
    store = EnterpriseStore(tmp_path / "enterprise")
    event_id = store.start_runtime_event(
        "operation", "long_task", "长时间任务", "系统管理员"
    )
    with store._connect() as connection:
        connection.execute(
            "UPDATE runtime_events SET started_at=? WHERE id=?",
            ("2020-01-01T00:00:00+00:00", event_id),
        )

    reconciled = store.reconcile_stale_runtime_events(max_age_minutes=1)

    assert reconciled == 1
    assert store.list_runtime_events()[0]["status"] == "已中断"
