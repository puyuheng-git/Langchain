"""酒店经营日报的映射、归档与版本读取。"""

from __future__ import annotations  # 延迟解析类型标注，方便类型引用保持简洁。

import hashlib  # 计算归档文件摘要，证明文件内容是否发生变化。
import json  # 把映射和标准化记录保存为 SQLite 可存储的文本。
import shutil  # 在不修改来源文件的前提下复制原始日报。
import sqlite3  # 使用项目现有的本地 SQLite 数据库保存版本。
from dataclasses import dataclass  # 用轻量对象表达稳定的领域结果。
from datetime import date, datetime, timezone  # 统一营业日和导入时间口径。
from pathlib import Path  # 以跨平台方式处理数据目录和日报路径。
from typing import Any  # 来源报表单元格可能包含字符串、数字或日期。
from uuid import uuid4  # 为每次导入生成不会碰撞的报告编号。

from enterprise.adapters.documents import parse_document  # 复用 CSV/XLSX 解析能力。


@dataclass(frozen=True, slots=True)
class DailyReportVersion:
    """一次可追溯的营业日报导入结果。

    Attributes:
        id: 本次导入的唯一编号。
        template_name: 解释来源表头所使用的模板名称。
        business_date: PMS 夜审确定的营业日。
        version: 同模板、同营业日下从一开始递增的版本号。
        records: 按标准字段名称保存的数据行。
        mapping: 导入当时使用的字段映射快照。
        source_name: 用户选择的原始文件名。
        stored_path: 本地归档文件的绝对路径。
        sha256: 归档文件内容的 SHA-256 摘要。
        imported_at: 带时区的 UTC 导入时间。
    """

    id: str  # 保存导入编号，便于关联归档文件和数据库记录。
    template_name: str  # 保存模板名称，区分 PMS、POS 等日报。
    business_date: date  # 使用 date 类型避免把营业日误当成导入时间。
    version: int  # 显式保存版本号，支持修订历史排序。
    records: list[dict[str, Any]]  # 保留来源单元格的数字或文本类型。
    mapping: dict[str, str]  # 冻结映射，避免模板更新改变历史解释。
    source_name: str  # 保留负责人熟悉的原始文件名。
    stored_path: str  # 返回路径，方便后续下载或核验原件。
    sha256: str  # 保存摘要，用于检查归档内容完整性。
    imported_at: str  # 使用 ISO 文本与项目其他时间字段保持一致。


@dataclass(frozen=True, slots=True)
class _NormalizedDailyReport:
    """通过模板校验、可进入版本存储的标准化日报。

    Attributes:
        business_date: 该批记录唯一的营业日。
        records: 已替换为标准字段名称的数据行。
        mapping: 本次标准化实际使用的字段映射。
    """

    business_date: date  # 作为版本归属和后续指标计算的时间主键。
    records: list[dict[str, Any]]  # 作为持久化和指标输入的标准记录。
    mapping: dict[str, str]  # 随版本保存，保证历史结果可解释。


@dataclass(frozen=True, slots=True)
class _ArchivedReportFile:
    """已复制到本地数据空间、可追溯的原始日报文件。

    Attributes:
        report_id: 与日报版本共用的唯一编号。
        source_name: 原始日报文件名。
        stored_path: 归档副本的绝对路径。
        sha256: 归档副本的内容摘要。
    """

    report_id: str  # 让归档目录和版本记录使用同一编号。
    source_name: str  # 保留来源文件名供负责人识别。
    stored_path: str  # 指向不会随来源文件移动而失效的副本。
    sha256: str  # 用于以后验证归档文件没有被替换。


class HotelDataWorkspace:
    """酒店经营数据导入与读取的稳定公共边界。

    Args:
        root: 本地个人数据空间目录，数据库和归档均保存于此。
    """

    def __init__(self, root: str | Path = "data/enterprise") -> None:
        """初始化数据目录并将酒店经营表迁移到最新版本。

        Args:
            root: 本地个人数据空间目录。

        Returns:
            None.
        """

        # 把相对目录转成绝对路径，避免工作目录变化导致数据分散。
        self.root = Path(root).resolve()
        # 与现有企业工作区共用数据库，保持单一备份边界。
        self.db_path = self.root / "enterprise.db"
        # 原始经营日报放到独立目录，便于归档和迁移。
        self.import_dir = self.root / "hotel_imports"
        # 首次启动时创建目录，重复启动不会覆盖已有文件。
        self.import_dir.mkdir(parents=True, exist_ok=True)
        # 在开放公共方法前完成事务化数据库迁移。
        self._initialize()

    def save_mapping(self, template_name: str, mapping: dict[str, str]) -> None:
        """保存报表模板的“标准字段 → 来源表头”映射。

        Args:
            template_name: 可重复使用的模板名称，例如 ``pms-daily``。
            mapping: 标准字段名称到来源报表表头的映射。

        Returns:
            None.

        Raises:
            ValueError: 模板名为空或缺少 ``business_date`` 映射时抛出。
        """

        # 去除首尾空白，避免视觉相同的模板被保存成两个名称。
        name = template_name.strip()
        # 空名称无法在后续导入时被稳定引用，因此立即拒绝。
        if not name:
            raise ValueError("模板名称不能为空")
        # 每份日报必须能映射到 PMS 营业日，这是版本归属的必要字段。
        if not mapping.get("business_date", "").strip():
            raise ValueError("字段映射必须包含 business_date")
        # 同时清理标准字段和来源表头，避免空格造成匹配失败。
        normalized = {
            str(field).strip(): str(source).strip()
            for field, source in mapping.items()
            if str(field).strip() and str(source).strip()
        }
        # 使用一次统一时间，确保新增和更新时间在首次保存时一致。
        now = _utc_now()
        # 上下文管理器会在成功时提交，在异常时回滚映射变更。
        with self._connect() as connection:
            # 按模板名称执行 upsert，让负责人可以修正已有字段映射。
            connection.execute(
                """INSERT INTO hotel_report_mappings
                   (template_name, mapping_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(template_name) DO UPDATE SET
                       mapping_json=excluded.mapping_json,
                       updated_at=excluded.updated_at""",
                (name, _json(normalized), now, now),
            )

    def get_mapping(self, template_name: str) -> dict[str, str] | None:
        """读取指定模板已保存的“标准字段 → 来源表头”映射。

        Args:
            template_name: 页面选择或输入的日报模板名称。

        Returns:
            模板存在时返回字段映射，否则返回 ``None``。
        """

        # 查询使用清理后的名称，与 save_mapping 的模板主键保持一致。
        name = template_name.strip()
        # 空名称不对应任何可恢复模板，直接返回空状态。
        if not name:
            return None
        # 使用短连接读取最新映射，页面重启后无需依赖内存状态。
        with self._connect() as connection:
            row = connection.execute(
                "SELECT mapping_json FROM hotel_report_mappings WHERE template_name=?",
                (name,),
            ).fetchone()
        # 没有记录时由页面使用首版默认表头。
        if row is None:
            return None
        # JSON 对象恢复成调用方可复用的字符串字典。
        return json.loads(row["mapping_json"])

    def list_mapping_templates(self) -> list[str]:
        """按名称返回全部已保存 PMS 日报模板。

        Returns:
            可供页面选择的模板名称列表。
        """

        # 名称排序让下拉框在每次启动时保持稳定顺序。
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT template_name FROM hotel_report_mappings ORDER BY template_name"
            ).fetchall()
        # SQLite 行转换为普通字符串，避免 UI 依赖数据库类型。
        return [str(row["template_name"]) for row in rows]

    def import_report(
        self, file_path: str | Path, template_name: str
    ) -> DailyReportVersion:
        """按已保存映射导入一个只包含单一营业日的 CSV/XLSX 报表。

        Args:
            file_path: 用户选择的 CSV 或 XLSX 日报路径。
            template_name: 解析该日报时使用的已保存模板名称。

        Returns:
            新生成且当前生效的日报版本。

        Raises:
            FileNotFoundError: 来源文件不存在时抛出。
            ValueError: 模板、文件类型、字段或营业日不符合要求时抛出。
        """

        # 使用 Path 统一处理调用方传入的字符串或路径对象。
        source = Path(file_path)
        # 读取负责人此前确认过的字段映射。
        mapping = self._get_mapping(template_name)
        # 解析和校验独立于归档，失败时不会留下无效文件副本。
        normalized = _normalize_report(source, mapping)
        # 校验成功后再归档原件，保证每个版本都有可核验来源。
        archived = self._archive_report(source)
        # 最后以事务方式分配版本号、切换生效版本并返回结果。
        return self._persist_report(template_name, normalized, archived)

    def _archive_report(self, source: Path) -> _ArchivedReportFile:
        """把校验通过的来源日报复制到独立版本目录。

        Args:
            source: 已通过格式和内容校验的来源日报路径。

        Returns:
            包含归档编号、路径和摘要的不可变描述对象。
        """

        # UUID 避免不同营业日或同名文件覆盖彼此。
        report_id = f"report_{uuid4().hex}"
        # 每次导入使用独立目录，后续删除或迁移可按版本操作。
        report_dir = self.import_dir / report_id
        # exist_ok=False 可在极小概率编号碰撞时立即报错，而非覆盖。
        report_dir.mkdir(parents=True, exist_ok=False)
        # Path.name 会丢弃来源目录，只保留安全的文件名部分。
        stored_path = report_dir / source.name
        # copy2 同时保留常见文件元数据，来源文件本身保持不变。
        shutil.copy2(source, stored_path)
        # 对归档副本计算摘要，确保记录与真正保存的内容一致。
        sha256 = hashlib.sha256(stored_path.read_bytes()).hexdigest()
        # 返回领域对象，避免多个字符串参数在后续调用中顺序混淆。
        return _ArchivedReportFile(report_id, source.name, str(stored_path), sha256)

    def _persist_report(
        self,
        template_name: str,
        report: _NormalizedDailyReport,
        archived: _ArchivedReportFile,
    ) -> DailyReportVersion:
        """保存标准化日报，并原子切换同营业日的生效版本。

        Args:
            template_name: 本次导入使用的模板名称。
            report: 已验证营业日和字段的标准化日报。
            archived: 已归档原始文件的追溯信息。

        Returns:
            新生成且当前生效的日报版本。
        """

        # 记录一次统一导入时间，数据库行和返回对象使用同一值。
        imported_at = _utc_now()
        # 数据库上下文会在任何写入失败时回滚整个版本切换。
        with self._connect() as connection:
            # 立即写锁可防止两个并发导入分配到相同版本号。
            connection.execute("BEGIN IMMEDIATE")
            # 查找当前最大版本；首次导入时 COALESCE 返回零。
            row = connection.execute(
                """SELECT COALESCE(MAX(version), 0) AS latest
                   FROM hotel_report_versions
                   WHERE template_name=? AND business_date=?""",
                (template_name, report.business_date.isoformat()),
            ).fetchone()
            # 新版本始终在同模板、同营业日范围内递增一。
            version = int(row["latest"]) + 1
            # 在插入新版本前取消旧版本的生效标志。
            connection.execute(
                """UPDATE hotel_report_versions SET is_active=0
                   WHERE template_name=? AND business_date=?""",
                (template_name, report.business_date.isoformat()),
            )
            # 一次写入标准化记录、映射快照和原件追溯信息。
            connection.execute(
                """INSERT INTO hotel_report_versions
                   (id, template_name, business_date, version, records_json, mapping_json,
                    source_name, stored_path, sha256, imported_at, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    archived.report_id,
                    template_name,
                    report.business_date.isoformat(),
                    version,
                    _json(report.records),
                    _json(report.mapping),
                    archived.source_name,
                    archived.stored_path,
                    archived.sha256,
                    imported_at,
                ),
            )

        # 返回与数据库内容一致的不可变对象，供页面立即展示。
        return DailyReportVersion(
            archived.report_id,
            template_name,
            report.business_date,
            version,
            report.records,
            report.mapping,
            archived.source_name,
            archived.stored_path,
            archived.sha256,
            imported_at,
        )

    def get_active_report(
        self, business_date: date, template_name: str
    ) -> DailyReportVersion | None:
        """读取模板在指定营业日的当前生效版本。

        Args:
            business_date: PMS 夜审确定的营业日。
            template_name: 需要查询的日报模板名称。

        Returns:
            当前生效日报；没有导入记录时返回 ``None``。
        """

        # 使用短连接完成只读查询，避免页面长时间占用数据库。
        with self._connect() as connection:
            # 部分唯一索引保证此查询最多返回一行。
            row = connection.execute(
                """SELECT * FROM hotel_report_versions
                   WHERE template_name=? AND business_date=?
                     AND is_active=1 AND is_valid=1""",
                (template_name, business_date.isoformat()),
            ).fetchone()
        # 数据库行统一经解码器恢复领域类型。
        return _decode_report(row) if row else None

    def list_report_versions(
        self, business_date: date, template_name: str
    ) -> list[DailyReportVersion]:
        """按新到旧返回模板在指定营业日的完整版本历史。

        Args:
            business_date: PMS 夜审确定的营业日。
            template_name: 需要查询的日报模板名称。

        Returns:
            从最新到最旧排列的日报版本列表。
        """

        # 版本查询不依赖当前生效标志，因此修订历史不会丢失。
        with self._connect() as connection:
            # 由数据库排序，调用方无需再次处理版本顺序。
            rows = connection.execute(
                """SELECT * FROM hotel_report_versions
                   WHERE template_name=? AND business_date=?
                   ORDER BY version DESC""",
                (template_name, business_date.isoformat()),
            ).fetchall()
        # 将所有 SQLite 行转换成稳定的公共领域对象。
        return [_decode_report(row) for row in rows]

    def reject_report_version(self, report_id: str) -> None:
        """停用未通过指标校验的日报，并恢复此前最新有效版本。

        Args:
            report_id: 已归档但未通过驾驶舱数据质量校验的日报编号。

        Returns:
            None.

        Raises:
            ValueError: 指定日报编号不存在时抛出。
        """

        # 生效切换必须使用一个写事务，避免页面刷新看到中间状态。
        with self._connect() as connection:
            # 立即写锁保证停用失败版本和恢复旧版本原子完成。
            connection.execute("BEGIN IMMEDIATE")
            # 读取失败日报的模板、营业日、版本和当前生效状态。
            rejected = connection.execute(
                """SELECT id, template_name, business_date, version, is_active
                   FROM hotel_report_versions WHERE id=?""",
                (report_id,),
            ).fetchone()
            # 不存在的编号说明调用方状态错误，不能静默忽略。
            if rejected is None:
                raise ValueError(f"日报版本不存在: {report_id}")
            # 无论当前是否生效，都明确标记校验失败并取消生效状态。
            connection.execute(
                """UPDATE hotel_report_versions
                   SET is_active=0, is_valid=0 WHERE id=?""",
                (report_id,),
            )
            # 并发场景中目标已非生效时，不应覆盖后来成功导入的新版本。
            if not rejected["is_active"]:
                return
            # 查找失败版本之前最新的有效历史日报作为恢复候选。
            previous = connection.execute(
                """SELECT id FROM hotel_report_versions
                   WHERE template_name=? AND business_date=?
                     AND version<? AND is_valid=1
                   ORDER BY version DESC LIMIT 1""",
                (
                    rejected["template_name"],
                    rejected["business_date"],
                    rejected["version"],
                ),
            ).fetchone()
            # 首次导入失败时没有旧版本，驾驶舱应保持空状态。
            if previous is not None:
                connection.execute(
                    "UPDATE hotel_report_versions SET is_active=1 WHERE id=?",
                    (previous["id"],),
                )

    def _connect(self) -> sqlite3.Connection:
        """创建启用字典行和 WAL 模式的短生命周期数据库连接。

        Returns:
            可通过字段名读取结果的 SQLite 连接。
        """

        # timeout 给短暂并发写入留出等待时间，避免立即提示数据库锁定。
        connection = sqlite3.connect(self.db_path, timeout=30)
        # sqlite3.Row 让解码代码使用字段名，而不是脆弱的列位置。
        connection.row_factory = sqlite3.Row
        # WAL 提升本地页面同时读写日报时的可用性。
        connection.execute("PRAGMA journal_mode = WAL")
        # 返回连接，由调用方的 with 语句负责提交、回滚和关闭语义。
        return connection

    def _initialize(self) -> None:
        """在单个事务中识别旧结构并应用全部缺失迁移。

        Returns:
            None.
        """

        # 迁移使用同一数据库连接，任何步骤失败都会整体回滚。
        with self._connect() as connection:
            # 立即取得写锁，避免两个进程同时执行相同迁移。
            connection.execute("BEGIN IMMEDIATE")
            # 迁移台账先于业务表创建，用于可靠判断当前版本。
            connection.execute(
                """CREATE TABLE IF NOT EXISTS hotel_schema_migrations (
                       version INTEGER PRIMARY KEY,
                       applied_at TEXT NOT NULL
                   )"""
            )
            # 兼容早期开发版本：它已有业务表但还没有迁移台账。
            existing_columns = _table_columns(connection, "hotel_report_versions")
            # 仅在检测到旧业务表时推断并登记已经具备的结构版本。
            if existing_columns:
                # 有效性列存在表示连续失败版本恢复迁移已经完成。
                if "is_valid" in existing_columns:
                    inferred_version = 3
                # 映射快照列存在表示版本二迁移已经完成。
                elif "mapping_json" in existing_columns:
                    inferred_version = 2
                # 其余早期日报表只具备版本一结构。
                else:
                    inferred_version = 1
                # 补写从一到推断版本的连续迁移记录。
                for version in range(1, inferred_version + 1):
                    _record_migration(connection, version)
            # 一次读取所有已应用版本，后续判断保持清晰。
            applied = {
                int(row["version"])
                for row in connection.execute(
                    "SELECT version FROM hotel_schema_migrations"
                ).fetchall()
            }
            # 版本一创建映射表、日报表和当前版本唯一索引。
            if 1 not in applied:
                _create_hotel_report_schema(connection)
                _record_migration(connection, 1)
            # 版本二为每份历史日报冻结当时使用的映射快照。
            if 2 not in applied:
                _add_mapping_snapshot(connection)
                _record_migration(connection, 2)
            # 版本三标记指标校验结果，避免连续失败时复活无效修订。
            if 3 not in applied:
                _add_report_validity_flag(connection)
                _record_migration(connection, 3)

    def _get_mapping(self, template_name: str) -> dict[str, str]:
        """按模板名称读取已保存的标准字段映射。

        Args:
            template_name: 负责人保存过的模板名称。

        Returns:
            标准字段名称到来源表头的映射。

        Raises:
            ValueError: 指定模板尚未保存时抛出。
        """

        # 复用公共读取接口，确保页面恢复和导入使用相同名称清理规则。
        mapping = self.get_mapping(template_name)
        # 没有模板时禁止猜测字段，避免静默导入错误数据。
        if mapping is None:
            raise ValueError(f"尚未保存字段映射: {template_name}")
        # 返回已经恢复的字符串字典供标准化步骤使用。
        return mapping


def _normalize_report(source: Path, mapping: dict[str, str]) -> _NormalizedDailyReport:
    """解析来源文件，并按字段映射生成单一营业日的标准化记录。

    Args:
        source: 用户选择的来源日报路径。
        mapping: 标准字段名称到来源表头的映射。

    Returns:
        通过文件类型、字段和营业日校验的标准化日报。

    Raises:
        ValueError: 文件类型、映射表头或营业日不符合要求时抛出。
    """

    # 产品首版只承诺 CSV/XLSX，拒绝通用解析器支持的其他格式。
    if source.suffix.lower() not in {".csv", ".xlsx"}:
        raise ValueError("经营日报只支持 CSV 或 XLSX 文件")
    # 复用现有适配器解析表格，不在酒店领域重复实现文件读取。
    document = parse_document(source)
    # 忽略封面和说明页，只选择完整满足映射的数据工作表。
    source_records = _select_matching_records(document.tables, mapping)
    # 把来源表头替换为稳定标准字段，来源值类型保持不变。
    records = [
        {field: record.get(source_header) for field, source_header in mapping.items()}
        for record in source_records
    ]
    # 解析所有行的营业日，集合可直接发现跨日冲突。
    business_dates = {_parse_business_date(record.get("business_date")) for record in records}
    # 一个版本只能属于一个营业日，否则同期和版本计算都会失真。
    if len(business_dates) != 1:
        # 稳定排序后列出所有冲突日期，帮助负责人定位错误文件。
        conflicts = "、".join(item.isoformat() for item in sorted(business_dates))
        raise ValueError(f"发现多个营业日: {conflicts}")
    # 集合只有一个元素，取出后作为版本归属日期。
    business_date = business_dates.pop()
    # 日期对象统一转为 ISO 字符串，使 CSV 和 XLSX 的标准记录一致。
    for record in records:
        record["business_date"] = business_date.isoformat()
    # 返回不可变的中间对象，供归档和持久化步骤使用。
    return _NormalizedDailyReport(business_date, records, mapping)


def _parse_business_date(value: Any) -> date:
    """把 CSV 文本或 Excel 日期转换为统一营业日。

    Args:
        value: 来源单元格中的日期、日期时间或 ISO 日期文本。

    Returns:
        不含时间部分的营业日。

    Raises:
        ValueError: 单元格不能按 ISO 日期识别时抛出。
    """

    # Excel 日期通常解析成 datetime，需先丢弃午夜时间部分。
    if isinstance(value, datetime):
        return value.date()
    # 已经是 date 时直接返回，避免重复字符串转换。
    if isinstance(value, date):
        return value
    # CSV 日期按明确的 ISO 格式解析，避免地区格式歧义。
    try:
        return date.fromisoformat(str(value).strip())
    # 保留原异常作为原因，同时给负责人提供业务化错误信息。
    except ValueError as exc:
        raise ValueError(f"无法识别营业日: {value}") from exc


def _select_matching_records(
    tables: list[list[dict[str, Any]]], mapping: dict[str, str]
) -> list[dict[str, Any]]:
    """忽略封面等无关工作表，返回包含全部映射表头的数据行。

    Args:
        tables: 文档适配器解析出的工作表记录列表。
        mapping: 标准字段名称到来源表头的映射。

    Returns:
        所有表头完整匹配模板的工作表数据行。

    Raises:
        ValueError: 没有数据行或没有任何工作表完整满足映射时抛出。
    """

    # 空工作表没有表头或数据，对映射判断没有意义。
    non_empty_tables = [table for table in tables if table]
    # 所有工作表都为空时给出直接、可操作的错误。
    if not non_empty_tables:
        raise ValueError("经营日报没有可导入的数据行")
    # 只关心负责人映射过的来源表头，其他辅助列允许保留在原件中。
    required_headers = set(mapping.values())
    # 一个工作表必须同时拥有全部映射表头，封面或辅助页会被忽略。
    matching_tables = [
        table
        for table in non_empty_tables
        if required_headers <= set().union(*(record.keys() for record in table))
    ]
    # 多个结构相同的数据表可以按原工作表顺序合并。
    if matching_tables:
        return [record for table in matching_tables for record in table]
    # 汇总所有表头，用于区分“字段缺失”和“字段分散在不同表”。
    available_headers = set().union(
        *(record.keys() for table in non_empty_tables for record in table)
    )
    # 差集就是整个工作簿中完全不存在的模板字段。
    missing_headers = sorted(required_headers - available_headers)
    # 明确列出缺失表头，便于负责人修正模板或报表。
    if missing_headers:
        raise ValueError(f"缺少已映射字段: {', '.join(missing_headers)}")
    # 所有字段虽存在但不在同一表时，提示工作表结构不匹配。
    required = ", ".join(sorted(required_headers))
    raise ValueError(f"没有工作表同时包含已映射字段: {required}")


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    """读取指定 SQLite 表当前拥有的列名。

    Args:
        connection: 正在执行迁移的 SQLite 连接。
        table_name: 受信任的内部表名。

    Returns:
        表不存在时为空集合，否则返回全部列名。
    """

    # PRAGMA 只用于代码内固定表名，不接受任何用户输入。
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def _record_migration(connection: sqlite3.Connection, version: int) -> None:
    """幂等记录一个已经具备的酒店 schema 版本。

    Args:
        connection: 正在执行迁移的 SQLite 连接。
        version: 已完成或从旧表推断出的迁移版本号。

    Returns:
        None.
    """

    # OR IGNORE 允许重复启动时安全确认同一个版本。
    connection.execute(
        "INSERT OR IGNORE INTO hotel_schema_migrations VALUES (?, ?)",
        (version, _utc_now()),
    )


def _create_hotel_report_schema(connection: sqlite3.Connection) -> None:
    """应用版本一迁移，创建映射和日报版本基础结构。

    Args:
        connection: 已开启迁移事务的 SQLite 连接。

    Returns:
        None.
    """

    # 映射表按模板名称保存当前可复用字段配置。
    connection.execute(
        """CREATE TABLE IF NOT EXISTS hotel_report_mappings (
               template_name TEXT PRIMARY KEY,
               mapping_json TEXT NOT NULL,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           )"""
    )
    # 日报表保存标准记录、原件追溯和同日递增版本。
    connection.execute(
        """CREATE TABLE IF NOT EXISTS hotel_report_versions (
               id TEXT PRIMARY KEY,
               template_name TEXT NOT NULL,
               business_date TEXT NOT NULL,
               version INTEGER NOT NULL,
               records_json TEXT NOT NULL,
               source_name TEXT NOT NULL,
               stored_path TEXT NOT NULL,
               sha256 TEXT NOT NULL,
               imported_at TEXT NOT NULL,
               is_active INTEGER NOT NULL,
               UNIQUE(template_name, business_date, version)
           )"""
    )
    # 部分唯一索引保证同模板、同营业日只有一个生效版本。
    connection.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_hotel_report_active
               ON hotel_report_versions(template_name, business_date)
               WHERE is_active=1"""
    )


def _add_mapping_snapshot(connection: sqlite3.Connection) -> None:
    """应用版本二迁移，为每个日报版本冻结字段映射。

    Args:
        connection: 已开启迁移事务的 SQLite 连接。

    Returns:
        None.
    """

    # 默认空对象让 SQLite 可以安全升级已有非空日报表。
    connection.execute(
        """ALTER TABLE hotel_report_versions
               ADD COLUMN mapping_json TEXT NOT NULL DEFAULT '{}'"""
    )
    # 能找到同名当前模板时，用它补齐旧版本的历史映射。
    connection.execute(
        """UPDATE hotel_report_versions
           SET mapping_json=COALESCE(
               (SELECT mapping.mapping_json FROM hotel_report_mappings AS mapping
                WHERE mapping.template_name=hotel_report_versions.template_name),
               '{}'
           )"""
    )


def _add_report_validity_flag(connection: sqlite3.Connection) -> None:
    """应用版本三迁移，为日报版本记录指标校验有效性。

    Args:
        connection: 已开启迁移事务的 SQLite 连接。

    Returns:
        None.
    """

    # 已有版本默认视为有效，保持升级前当前和历史日报的读取行为。
    connection.execute(
        """ALTER TABLE hotel_report_versions
               ADD COLUMN is_valid INTEGER NOT NULL DEFAULT 1"""
    )


def _decode_report(row: sqlite3.Row) -> DailyReportVersion:
    """把 SQLite 行恢复为公共日报版本对象。

    Args:
        row: ``hotel_report_versions`` 查询返回的命名行。

    Returns:
        恢复日期、记录和映射类型后的日报版本。
    """

    # 显式按字段名构造，数据库列顺序变化不会影响解码。
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
    """把包含中文、日期或数字的值编码为数据库 JSON 文本。

    Args:
        value: 需要保存的映射或标准化记录。

    Returns:
        保留中文字符的 JSON 字符串。
    """

    # default=str 兼容来源单元格中的日期等可读对象。
    return json.dumps(value, ensure_ascii=False, default=str)


def _utc_now() -> str:
    """返回适合跨时区排序和追溯的 UTC ISO 时间。

    Returns:
        精确到秒且包含 UTC 偏移的时间字符串。
    """

    # 始终使用带时区时间，避免本地时区切换产生歧义。
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
