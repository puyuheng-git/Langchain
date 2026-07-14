"""SQLite 持久化与受控文件存储。

每次上传、执行、发现项和人工复核都在本机保存。数据库只保存结构化元数据，
原始文件保存在独立案件目录中，方便后续追溯和重新执行。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .models import Finding, new_id, utc_now


def _json(value: Any) -> str:
    """用统一参数生成可读、支持中文的 JSON。"""

    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None, fallback: Any) -> Any:
    """安全解析数据库中的 JSON 字段。"""

    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def sanitize_filename(name: str) -> str:
    """移除路径穿越和 Windows 非法字符，仅保留安全文件名。"""

    raw_name = Path(name).name.strip() or "uploaded_file"
    cleaned = "".join("_" if char in '<>:"/\\|?*' or ord(char) < 32 else char for char in raw_name)
    return cleaned[:180]


class EnterpriseStore:
    """企业工作台的 SQLite 仓储和文件归档服务。"""

    def __init__(self, root: str | Path = "data/enterprise") -> None:
        """初始化目录、数据库连接参数和数据表。"""

        self.root = Path(root).resolve()
        self.upload_dir = self.root / "uploads"
        self.report_dir = self.root / "reports"
        self.sample_dir = self.root / "samples"
        self.db_path = self.root / "enterprise.db"
        for directory in (self.root, self.upload_dir, self.report_dir, self.sample_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """创建启用外键和字典行访问的短连接。"""

        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        """以幂等方式创建 MVP 所需数据表和索引。"""

        schema = """
        CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            actor TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            input_summary TEXT NOT NULL,
            result_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            file_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            mime_type TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            model_route TEXT NOT NULL,
            options_json TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
            case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            rule_id TEXT,
            rule_version TEXT,
            confidence REAL NOT NULL,
            recommendation TEXT,
            review_status TEXT NOT NULL,
            review_comment TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            case_id TEXT REFERENCES cases(id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            owner TEXT,
            due_date TEXT,
            priority TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT,
            details TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            requester TEXT NOT NULL,
            approver TEXT,
            status TEXT NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id TEXT PRIMARY KEY,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            details_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cases_updated ON cases(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_executions_case ON executions(case_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_findings_case ON findings(case_id, severity);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, due_date);
        CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at DESC);
        """
        with self._connect() as connection:
            connection.executescript(schema)

    def log(
        self, actor: str, action: str, entity_type: str, entity_id: str, details: Any = None
    ) -> None:
        """记录关键数据变更，形成最小审计轨迹。"""

        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_logs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("log"),
                    actor,
                    action,
                    entity_type,
                    entity_id,
                    _json(details or {}),
                    utc_now(),
                ),
            )

    def create_case(
        self,
        workflow_id: str,
        title: str,
        actor: str,
        sensitivity: str,
        input_summary: dict[str, Any],
    ) -> str:
        """创建一个持久化案件并返回案件编号。"""

        case_id = new_id("case")
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO cases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    case_id,
                    workflow_id,
                    title,
                    "处理中",
                    actor,
                    sensitivity,
                    _json(input_summary),
                    None,
                    now,
                    now,
                ),
            )
        self.log(actor, "create", "case", case_id, {"workflow_id": workflow_id, "title": title})
        return case_id

    def start_execution(self, case_id: str, workflow_id: str, options: dict[str, Any]) -> str:
        """登记一次重新可追溯的工作流执行。"""

        execution_id = new_id("exec")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    execution_id,
                    case_id,
                    workflow_id,
                    "运行中",
                    "deterministic",
                    _json(options),
                    None,
                    None,
                    utc_now(),
                    None,
                ),
            )
        return execution_id

    def save_upload(
        self, case_id: str, file_name: str, content: bytes, mime_type: str = ""
    ) -> Path:
        """保存上传字节并登记 SHA-256，保证上传后不会因页面刷新丢失。"""

        safe_name = sanitize_filename(file_name)
        target_dir = self.upload_dir / case_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe_name
        if target.exists():
            target = target_dir / f"{target.stem}_{new_id('copy')[-8:]}{target.suffix}"
        target.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("artifact"),
                    case_id,
                    target.name,
                    str(target),
                    digest,
                    mime_type,
                    utc_now(),
                ),
            )
        return target

    def archive_file(self, case_id: str, source: str | Path) -> Path:
        """把 CLI 或样本目录中的文件复制到案件归档目录。"""

        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"文件不存在: {source_path}")
        return self.save_upload(case_id, source_path.name, source_path.read_bytes())

    def complete_execution(
        self,
        execution_id: str,
        case_id: str,
        result: dict[str, Any],
        findings: Iterable[Finding],
        model_route: str,
        actor: str,
    ) -> None:
        """原子保存执行结果、发现项和案件摘要。"""

        now = utc_now()
        findings = list(findings)
        result_summary = {
            "summary": result.get("summary", ""),
            "metrics": result.get("metrics", {}),
            "finding_count": len(findings),
        }
        with self._connect() as connection:
            connection.execute(
                "UPDATE executions SET status=?, model_route=?, result_json=?, completed_at=? WHERE id=?",
                ("已完成", model_route, _json(result), now, execution_id),
            )
            connection.execute(
                "UPDATE cases SET status=?, result_summary=?, updated_at=? WHERE id=?",
                ("待人工复核", _json(result_summary), now, case_id),
            )
            for item in findings:
                connection.execute(
                    """INSERT INTO findings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        item.id,
                        execution_id,
                        case_id,
                        item.category,
                        item.severity.value,
                        item.title,
                        item.description,
                        _json([evidence.to_dict() for evidence in item.evidence]),
                        item.rule_id,
                        item.rule_version,
                        item.confidence,
                        item.recommendation,
                        item.review_status,
                        item.review_comment,
                        now,
                        now,
                    ),
                )
        self.log(actor, "complete", "execution", execution_id, result_summary)

    def fail_execution(self, execution_id: str, case_id: str, error: str, actor: str) -> None:
        """保存失败状态和错误信息，避免失败操作从历史中消失。"""

        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE executions SET status=?, error=?, completed_at=? WHERE id=?",
                ("失败", error, now, execution_id),
            )
            connection.execute(
                "UPDATE cases SET status=?, updated_at=? WHERE id=?",
                ("执行失败", now, case_id),
            )
        self.log(actor, "fail", "execution", execution_id, {"error": error})

    def list_cases(self, workflow_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """按最近更新时间列出案件。"""

        query = "SELECT * FROM cases"
        params: list[Any] = []
        if workflow_id:
            query += " WHERE workflow_id=?"
            params.append(workflow_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._decode_case(dict(row)) for row in rows]

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        """读取案件、附件、执行和发现项的完整详情。"""

        with self._connect() as connection:
            case = connection.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if not case:
                return None
            artifacts = connection.execute(
                "SELECT * FROM artifacts WHERE case_id=? ORDER BY created_at", (case_id,)
            ).fetchall()
            executions = connection.execute(
                "SELECT * FROM executions WHERE case_id=? ORDER BY started_at DESC", (case_id,)
            ).fetchall()
            findings = connection.execute(
                "SELECT * FROM findings WHERE case_id=? ORDER BY created_at", (case_id,)
            ).fetchall()
        payload = self._decode_case(dict(case))
        payload["artifacts"] = [dict(row) for row in artifacts]
        payload["executions"] = [self._decode_execution(dict(row)) for row in executions]
        payload["findings"] = [self._decode_finding(dict(row)) for row in findings]
        return payload

    def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """按执行编号读取结构化结果。"""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM executions WHERE id=?", (execution_id,)
            ).fetchone()
        return self._decode_execution(dict(row)) if row else None

    def update_finding_review(self, finding_id: str, status: str, comment: str, actor: str) -> None:
        """记录人工接受、驳回或待补充结论。"""

        with self._connect() as connection:
            connection.execute(
                "UPDATE findings SET review_status=?, review_comment=?, updated_at=? WHERE id=?",
                (status, comment, utc_now(), finding_id),
            )
        self.log(actor, "review", "finding", finding_id, {"status": status, "comment": comment})

    def update_case_status(self, case_id: str, status: str, actor: str) -> None:
        """更新案件生命周期状态。"""

        with self._connect() as connection:
            connection.execute(
                "UPDATE cases SET status=?, updated_at=? WHERE id=?", (status, utc_now(), case_id)
            )
        self.log(actor, "status_change", "case", case_id, {"status": status})

    def create_task(
        self,
        title: str,
        owner: str = "",
        due_date: str = "",
        priority: str = "中",
        case_id: str | None = None,
        source: str = "手工",
        details: str = "",
    ) -> str:
        """创建管理任务或会议行动项。"""

        task_id = new_id("task")
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    case_id,
                    title,
                    owner,
                    due_date,
                    priority,
                    "待处理",
                    source,
                    details,
                    now,
                    now,
                ),
            )
        return task_id

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """读取任务中心列表。"""

        query = "SELECT * FROM tasks"
        params: list[Any] = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY CASE priority WHEN '高' THEN 1 WHEN '中' THEN 2 ELSE 3 END, due_date"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def update_task(self, task_id: str, status: str, owner: str, due_date: str) -> None:
        """更新任务状态、负责人和截止日期。"""

        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status=?, owner=?, due_date=?, updated_at=? WHERE id=?",
                (status, owner, due_date, utc_now(), task_id),
            )

    def create_approval(self, case_id: str, action: str, requester: str) -> str:
        """为最终业务动作创建一条待审批记录。"""

        approval_id = new_id("approval")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (approval_id, case_id, action, requester, None, "待审批", "", utc_now(), None),
            )
        self.log(
            requester, "request", "approval", approval_id, {"case_id": case_id, "action": action}
        )
        return approval_id

    def list_approvals(self, case_id: str | None = None) -> list[dict[str, Any]]:
        """列出全部或指定案件的审批记录。"""

        query = "SELECT * FROM approvals"
        params: list[Any] = []
        if case_id:
            query += " WHERE case_id=?"
            params.append(case_id)
        query += " ORDER BY created_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def decide_approval(self, approval_id: str, decision: str, comment: str, actor: str) -> None:
        """由不同于申请人的操作人批准或驳回最终动作。"""

        if decision not in {"已批准", "已驳回"}:
            raise ValueError("审批决定只能是已批准或已驳回")
        with self._connect() as connection:
            approval = connection.execute(
                "SELECT * FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
            if not approval:
                raise ValueError("审批记录不存在")
            if approval["status"] != "待审批":
                raise ValueError("该审批已经处理")
            if approval["requester"].strip() == actor.strip():
                raise ValueError("申请人不能审批自己的申请，请更换当前操作人")
            connection.execute(
                "UPDATE approvals SET approver=?, status=?, comment=?, decided_at=? WHERE id=?",
                (actor, decision, comment, utc_now(), approval_id),
            )
        self.log(
            actor, "decide", "approval", approval_id, {"decision": decision, "comment": comment}
        )

    def dashboard_metrics(self) -> dict[str, int]:
        """计算操作台首页的实时统计数字。"""

        with self._connect() as connection:
            case_count = connection.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
            pending_cases = connection.execute(
                "SELECT COUNT(*) FROM cases WHERE status IN ('待人工复核', '处理中')"
            ).fetchone()[0]
            high_findings = connection.execute(
                "SELECT COUNT(*) FROM findings WHERE severity='高' AND review_status='待复核'"
            ).fetchone()[0]
            open_tasks = connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status NOT IN ('已完成', '已取消')"
            ).fetchone()[0]
            pending_approvals = connection.execute(
                "SELECT COUNT(*) FROM approvals WHERE status='待审批'"
            ).fetchone()[0]
        return {
            "case_count": case_count,
            "pending_cases": pending_cases,
            "high_findings": high_findings,
            "open_tasks": open_tasks,
            "pending_approvals": pending_approvals,
        }

    @staticmethod
    def _decode_case(row: dict[str, Any]) -> dict[str, Any]:
        """解析案件 JSON 字段。"""

        row["input_summary"] = _loads(row.get("input_summary"), {})
        row["result_summary"] = _loads(row.get("result_summary"), {})
        return row

    @staticmethod
    def _decode_execution(row: dict[str, Any]) -> dict[str, Any]:
        """解析执行 JSON 字段。"""

        row["options"] = _loads(row.pop("options_json", None), {})
        row["result"] = _loads(row.pop("result_json", None), None)
        return row

    @staticmethod
    def _decode_finding(row: dict[str, Any]) -> dict[str, Any]:
        """解析发现项证据字段。"""

        row["evidence"] = _loads(row.pop("evidence_json", None), [])
        return row
