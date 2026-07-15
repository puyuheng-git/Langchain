"""酒店负责人个人经营治理的公共接口。"""

from .data_workspace import DailyReportVersion, HotelDataWorkspace  # 导出日报公共接口。
from .room_metrics import RoomMetricsCalculator, RoomMetricsSnapshot  # 导出指标公共接口。

# 限定星号导入范围，避免内部迁移和标准化对象变成公共 API。
__all__ = [
    "DailyReportVersion",  # 允许调用方把已导入日报交给指标引擎。
    "HotelDataWorkspace",  # 保留日报导入与版本读取入口。
    "RoomMetricsCalculator",  # 暴露确定性客房指标计算入口。
    "RoomMetricsSnapshot",  # 暴露可追溯指标结果类型。
]
