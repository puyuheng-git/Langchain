"""酒店经营日报的映射、归档与版本读取。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise.adapters.documents import parse_document


@dataclass(frozen=True, slots=True)
class DailyReportVersion:
    """一次可追溯的营业日报导入结果。"""

    id: str
    template_name: str
    business_date: date
    version: int
    records: list[dict[str, Any]]
    mapping: dict[str, str]
    source_name: str
    stored_path: str
    sha256: str
    imported_at: str


class HotelDataWorkspace:
    """酒店经营数据导入与读取的稳定公共边界。"""

    def __init__(self, root: str | Path = "data/enterprise") -> None:
        self.root = Path(root).resolve()
        self.db_path = self.root / "enterprise.db"
        self.import_dir = self.root / "hotel_imports"
        self.import_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def save_mapping(self, template_name: str, mapping: dict[str, str]) -> None:
        """保存报表模板的“标准字段 → 来源表头”映射。"""

        name = template_name.strip()
        if not name:
            raise ValueError("模板名称不能为空")
        if not mapping.get("business_date", "").strip():
            raise ValueError("字段映射必须包含 business_date")
        normalized = {
            str(field).strip(): str(source).strip()
            for field, source in mapping.items()
            if str(field).strip() and str(source).strip()
        }
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO hotel_report_mappings
                   (template_name, mapping_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(template_name) DO UPDATE SET
                       mapping_json=excluded.mapping_json,
                       updated_at=excluded.updated_at""",
                (name, _json(normalized), now, now),
            )

    def import_report(
        self, file_path: str | Path, template_name: str
    ) -> DailyReportVersion:
        """按已保存映射导入一个只包含单一营业日的 CSV/XLSX 报表。"""

        source = Path(file_path)
        mapping = self._get_mapping(template_name)
        document = parse_document(source)
        source_records = [record for table in document.tables for record in table]
        if not source_records:
            raise ValueError("经营日报没有可导入的数据行")
        missing_headers = [
            source_header
            for source_header in mapping.values()
            if any(source_header not in record for record in source_records)
        ]
        if missing_headers:
            raise ValueError(f"缺少已映射字段: {', '.join(missing_headers)}")
        records = [
            {field: record.get(source_header) for field, source_header in mapping.items()}
            for record in source_records
        ]
        business_dates = {_parse_business_date(record.get("business_date")) for record in records}
        if len(business_dates) != 1:
            conflicts = "、".join(item.isoformat() for item in sorted(business_dates))
            raise ValueError(f"发现多个营业日: {conflicts}")
        business_date = business_dates.pop()
        for record in records:
            record["business_date"] = business_date.isoformat()

        report_id = f"report_{uuid4().hex}"
        report_dir = self.import_dir / report_id
        report_dir.mkdir(parents=True, exist_ok=False)
        stored_path = report_dir / source.name
        shutil.copy2(source, stored_path)
        sha256 = hashlib.sha256(stored_path.read_bytes()).hexdigest()
        imported_at = _utc_now()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT COALESCE(MAX(version), 0) AS latest
                   FROM hotel_report_versions
                   WHERE template_name=? AND business_date=?""",
                (template_name, business_date.isoformat()),
            ).fetchone()
            version = int(row["latest"]) + 1
            connection.execute(
                """UPDATE hotel_report_versions SET is_active=0
                   WHERE template_name=? AND business_date=?""",
                (template_name, business_date.isoformat()),
            )
            connection.execute(
                """INSERT INTO hotel_report_versions
                   (id, template_name, business_date, version, records_json, mapping_json,
                    source_name, stored_path, sha256, imported_at, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    report_id,
                    template_name,
                    business_date.isoformat(),
                    version,
                    _json(records),
                    _json(mapping),
                    source.name,
                    str(stored_path),
                    sha256,
                    imported_at,
                ),
            )

        return DailyReportVersion(
            report_id,
            template_name,
            business_date,
            version,
            records,
            mapping,
            source.name,
            str(stored_path),
            sha256,
            imported_at,
        )

    def get_active_report(
        self, business_date: date, template_name: str
    ) -> DailyReportVersion | None:
        """读取模板在指定营业日的当前生效版本。"""

        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM hotel_report_versions
                   WHERE template_name=? AND business_date=? AND is_active=1""",
                (template_name, business_date.isoformat()),
            ).fetchone()
        return _decode_report(row) if row else None

    def list_report_versions(
        self, business_date: date, template_name: str
    ) -> list[DailyReportVersion]:
        """按新到旧返回模板在指定营业日的完整版本历史。"""

        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM hotel_report_versions
                   WHERE template_name=? AND business_date=?
                   ORDER BY version DESC""",
                (template_name, business_date.isoformat()),
            ).fetchall()
        return [_decode_report(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS hotel_report_mappings (
            template_name TEXT PRIMARY KEY,
            mapping_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS hotel_report_versions (
            id TEXT PRIMARY KEY,
            template_name TEXT NOT NULL,
            business_date TEXT NOT NULL,
            version INTEGER NOT NULL,
            records_json TEXT NOT NULL,
            mapping_json TEXT NOT NULL,
            source_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            is_active INTEGER NOT NULL,
            UNIQUE(template_name, business_date, version)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_hotel_report_active
            ON hotel_report_versions(template_name, business_date)
            WHERE is_active=1;
        """
        with self._connect() as connection:
            connection.executescript(schema)

    def _get_mapping(self, template_name: str) -> dict[str, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT mapping_json FROM hotel_report_mappings WHERE template_name=?",
                (template_name,),
            ).fetchone()
        if not row:
            raise ValueError(f"尚未保存字段映射: {template_name}")
        return json.loads(row["mapping_json"])


def _parse_business_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError(f"无法识别营业日: {value}") from exc


def _decode_report(row: sqlite3.Row) -> DailyReportVersion:
    return DailyReportVersion(
        id=row["id"],
        template_name=row["template_name"],
        business_date=date.fromisoformat(row["business_date"]),
        version=int(row["version"]),
        records=json.loads(row["records_json"]),
        mapping=json.loads(row["mapping_json"]),
        source_name=row["source_name"],
        stored_path=row["stored_path"],
        sha256=row["sha256"],
        imported_at=row["imported_at"],
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
