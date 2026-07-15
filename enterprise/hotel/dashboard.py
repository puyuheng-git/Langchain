"""每日经营驾驶舱的上传、恢复与指标编排服务。"""

from __future__ import annotations  # 延迟类型解析，保持公共方法标注简洁。

from dataclasses import dataclass  # 用不可变对象把日报和指标组成页面快照。
from datetime import date  # 页面刷新后按 PMS 营业日恢复快照。
from pathlib import Path  # 清理上传文件名并管理本地数据目录。
from tempfile import TemporaryDirectory  # 安全暂存浏览器上传字节并自动清理。

from .data_workspace import DailyReportVersion, HotelDataWorkspace  # 复用日报持久化边界。
from .room_metrics import RoomMetricsCalculator, RoomMetricsSnapshot  # 复用权威指标引擎。


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
        file_name: str,
        content: bytes,
        mapping: dict[str, str],
        template_name: str = "pms-daily",
    ) -> HotelDashboardSnapshot:
        """导入浏览器上传字节并立即生成驾驶舱快照。

        Args:
            file_name: 浏览器上传的原始 CSV/XLSX 文件名。
            content: 浏览器读取到的完整文件字节。
            mapping: 标准字段名称到 PMS 来源表头的映射。
            template_name: 保存和复用映射的日报模板名称。

        Returns:
            新生效日报版本及其客房指标组成的驾驶舱快照。

        Raises:
            ValueError: 文件名为空或底层日报、指标校验失败时抛出。
        """

        # 只保留文件名部分，避免浏览器提供的路径写出暂存目录。
        safe_name = Path(file_name).name.strip()
        # 空文件名无法确定 CSV/XLSX 类型，也无法形成可追溯来源。
        if not safe_name:
            raise ValueError("上传文件名不能为空")
        # 映射先保存，使同一 PMS 模板下次上传时可以直接复用。
        self.data.save_mapping(template_name, mapping)
        # 暂存目录位于本地个人数据空间，离开上下文后自动删除。
        with TemporaryDirectory(prefix=".hotel-upload-", dir=self.data.root) as staging:
            # 使用已经清理过的文件名创建唯一暂存路径。
            upload_path = Path(staging) / safe_name
            # 把浏览器字节写入本地文件，交给统一 CSV/XLSX 适配器解析。
            upload_path.write_bytes(content)
            # 工作空间会再次归档原件、计算摘要并生成日报版本。
            report = self.data.import_report(upload_path, template_name)
        # 暂存文件已删除，指标只读取持久化的标准化日报版本。
        metrics = RoomMetricsCalculator.calculate(report)
        # 返回页面可直接展示并在刷新后重建的不可变快照。
        return HotelDashboardSnapshot(report, metrics)

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
