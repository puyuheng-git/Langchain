"""每日经营驾驶舱的上传、恢复与指标编排服务。"""

from __future__ import annotations  # 延迟类型解析，保持公共方法标注简洁。

from dataclasses import dataclass  # 用不可变对象把日报和指标组成页面快照。
from datetime import date  # 页面刷新后按 PMS 营业日恢复快照。
from pathlib import Path  # 清理上传文件名并管理本地数据目录。
from tempfile import TemporaryDirectory  # 安全暂存浏览器上传字节并自动清理。

from .data_workspace import DailyReportVersion, HotelDataWorkspace  # 复用日报持久化边界。
from .room_metrics import RoomMetricsCalculator, RoomMetricsSnapshot  # 复用权威指标引擎。


# dataclass 把五个 PMS 来源表头集中为可保存、可比较的配置对象。
@dataclass(frozen=True, slots=True)
class PmsFieldMapping:
    """PMS 日报标准字段对应的来源表头配置。

    Attributes:
        business_date: PMS 营业日来源表头。
        available_rooms: 可售房来源表头。
        rooms_sold: 已售房来源表头。
        room_revenue: 客房收入来源表头。
        room_inventory_segment: 多行日报的可选库存分段来源表头。
    """

    business_date: str = "营业日期"  # 首版默认中文营业日表头。
    available_rooms: str = "可售房"  # 首版默认中文可售房表头。
    rooms_sold: str = "已售房"  # 首版默认中文已售房表头。
    room_revenue: str = "客房收入"  # 首版默认中文客房收入表头。
    room_inventory_segment: str = ""  # 单行日报默认不要求库存分段。

    def to_dict(self) -> dict[str, str]:
        """转换为日报工作空间使用的标准字段映射。

        Returns:
            不含空库存分段的“标准字段 → 来源表头”字典。
        """

        # 四个权威字段始终交给工作空间执行完整性校验。
        mapping = {
            "business_date": self.business_date,  # 营业日标准字段。
            "available_rooms": self.available_rooms,  # 可售房标准字段。
            "rooms_sold": self.rooms_sold,  # 已售房标准字段。
            "room_revenue": self.room_revenue,  # 客房收入标准字段。
        }
        # 多行库存分段只有负责人填写来源表头时才加入模板。
        if self.room_inventory_segment.strip():
            mapping["room_inventory_segment"] = self.room_inventory_segment.strip()
        # 返回普通字典以兼容日报工作空间的稳定公共接口。
        return mapping

    # classmethod 让恢复逻辑通过类本身创建对象，子类也能复用同一入口。
    @classmethod
    def from_dict(cls, mapping: dict[str, str]) -> PmsFieldMapping:
        """从已保存字典恢复强类型 PMS 字段映射。

        Args:
            mapping: 日报工作空间读取出的字段映射。

        Returns:
            页面可直接回填的 PMS 字段映射对象。
        """

        # 缺失字段使用首版默认值，兼容早期只保存部分配置的模板。
        defaults = cls()
        # 逐字段恢复可避免页面依赖字典键拼写。
        return cls(
            # 旧模板没有营业日字段时回退到首版中文默认值。
            business_date=mapping.get("business_date", defaults.business_date),
            # 旧模板没有可售房字段时回退到首版中文默认值。
            available_rooms=mapping.get("available_rooms", defaults.available_rooms),
            # 旧模板没有已售房字段时回退到首版中文默认值。
            rooms_sold=mapping.get("rooms_sold", defaults.rooms_sold),
            # 旧模板没有客房收入字段时回退到首版中文默认值。
            room_revenue=mapping.get("room_revenue", defaults.room_revenue),
            # 库存分段始终保持可选，早期单行模板恢复为空值。
            room_inventory_segment=mapping.get("room_inventory_segment", ""),
        )


# dataclass 把一次浏览器上传需要的文件、模板和映射绑定在一起。
@dataclass(frozen=True, slots=True)
class HotelReportUpload:
    """负责人提交给驾驶舱的一次完整 PMS 日报上传命令。

    Attributes:
        file_name: 浏览器上传的原始文件名。
        content: 浏览器读取到的完整文件字节。
        mapping: 本次导入使用并保存的 PMS 字段映射。
        template_name: 页面可选择和复用的模板名称。
    """

    file_name: str  # 保留来源文件名并用于确定 CSV/XLSX 类型。
    content: bytes  # 文件内容只在本地暂存、解析和归档。
    mapping: PmsFieldMapping  # 强类型映射防止多个表头参数错位。
    template_name: str = "pms-daily"  # 默认模板覆盖首个单酒店使用场景。


# dataclass 自动生成不可变快照的初始化与比较方法，便于页面刷新验证。
@dataclass(frozen=True, slots=True)
class HotelDashboardSnapshot:
    """每日经营驾驶舱展示所需的完整、可追溯数据。

    Attributes:
        report: 当前营业日生效的日报版本及来源原件信息。
        metrics: 从该日报版本确定性计算的客房权威指标。
    """

    report: DailyReportVersion  # 页面可展示来源文件、日报编号和版本。
    metrics: RoomMetricsSnapshot  # 页面可展示六项指标和口径版本。


class HotelDashboardService:
    """协调浏览器上传、日报版本与客房指标的应用服务。

    Args:
        root: 本地个人数据空间目录；服务不会把上传内容发送到网络。
    """

    def __init__(self, root: str | Path = "data/enterprise") -> None:
        """创建依赖同一本地数据空间的驾驶舱服务。

        Args:
            root: 本地数据库和日报归档所在目录。

        Returns:
            None.
        """

        # 复用既有工作空间，让页面导入和历史读取使用同一数据库。
        self.data = HotelDataWorkspace(root)

    def import_upload(
        self,
        upload: HotelReportUpload,
    ) -> HotelDashboardSnapshot:
        """导入浏览器上传字节并立即生成驾驶舱快照。

        Args:
            upload: 包含文件字节、模板名称和强类型映射的上传命令。

        Returns:
            新生效日报版本及其客房指标组成的驾驶舱快照。

        Raises:
            ValueError: 文件名为空或底层日报、指标校验失败时抛出。
        """

        # 只保留文件名部分，避免浏览器提供的路径写出暂存目录。
        safe_name = Path(upload.file_name).name.strip()
        # 空文件名无法确定 CSV/XLSX 类型，也无法形成可追溯来源。
        if not safe_name:
            raise ValueError("上传文件名不能为空")
        # 清理模板名称，避免首尾空格造成保存后无法恢复。
        template_name = upload.template_name.strip()
        # 空模板名称不能成为页面可复用的稳定标识。
        if not template_name:
            raise ValueError("模板名称不能为空")
        # 映射先保存，使同一 PMS 模板下次上传时可以直接复用。
        self.data.save_mapping(template_name, upload.mapping.to_dict())
        # 暂存目录位于本地个人数据空间，离开上下文后自动删除。
        with TemporaryDirectory(prefix=".hotel-upload-", dir=self.data.root) as staging:
            # 使用已经清理过的文件名创建唯一暂存路径。
            upload_path = Path(staging) / safe_name
            # 把浏览器字节写入本地文件，交给统一 CSV/XLSX 适配器解析。
            upload_path.write_bytes(upload.content)
            # 工作空间会再次归档原件、计算摘要并生成日报版本。
            report = self.data.import_report(upload_path, template_name)
        # 暂存文件已删除，指标只读取持久化的标准化日报版本。
        try:
            metrics = RoomMetricsCalculator.calculate(report)
        # 数据质量失败时保留归档历史，但恢复此前正常生效版本。
        except ValueError:
            self.data.reject_report_version(report.id)
            raise
        # 返回页面可直接展示并在刷新后重建的不可变快照。
        return HotelDashboardSnapshot(report, metrics)

    def list_templates(self) -> list[str]:
        """返回页面可选择的全部已保存 PMS 模板名称。

        Returns:
            按名称排序的模板名称列表。
        """

        # 直接复用数据工作空间排序结果，页面不再维护独立模板状态。
        return self.data.list_mapping_templates()

    def get_mapping(self, template_name: str) -> PmsFieldMapping | None:
        """读取指定模板并恢复成页面可回填的强类型字段映射。

        Args:
            template_name: 页面当前选择的 PMS 模板名称。

        Returns:
            已保存模板返回字段映射，否则返回 ``None``。
        """

        # 公共数据接口负责名称清理和不存在模板的空状态。
        mapping = self.data.get_mapping(template_name)
        # 页面可用 None 区分“未保存模板”和“保存了默认表头”。
        if mapping is None:
            return None
        # 字典恢复为页面使用的强类型配置。
        return PmsFieldMapping.from_dict(mapping)

    def get_snapshot(
        self,
        business_date: date,
        template_name: str = "pms-daily",
    ) -> HotelDashboardSnapshot | None:
        """按营业日读取当前生效日报并重新计算驾驶舱指标。

        Args:
            business_date: 页面选择的 PMS 夜审营业日。
            template_name: 需要读取的日报模板名称。

        Returns:
            找到日报时返回驾驶舱快照，否则返回 ``None``。
        """

        # 只通过日报公共接口读取当前版本，不依赖数据库表结构。
        report = self.data.get_active_report(business_date, template_name)
        # 没有该营业日数据时让页面展示空状态，而不是抛出异常。
        if report is None:
            return None
        # 重新计算可确保页面始终使用当前指标口径版本。
        metrics = RoomMetricsCalculator.calculate(report)
        # 把恢复的日报与指标重新组成页面快照。
        return HotelDashboardSnapshot(report, metrics)
