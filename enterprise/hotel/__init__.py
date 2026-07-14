"""酒店负责人个人经营治理的公共接口。"""

# 从深模块导出调用方真正需要的日报结果与工作空间接口。
from .data_workspace import DailyReportVersion, HotelDataWorkspace

# 限定星号导入范围，避免内部迁移和标准化对象变成公共 API。
__all__ = ["DailyReportVersion", "HotelDataWorkspace"]
