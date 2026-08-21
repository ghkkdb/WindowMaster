"""WindowMaster 使用的数据模型。"""

from dataclasses import dataclass
from typing import Generic, TypeVar


T = TypeVar("T")

MonitorSignature = tuple[
    tuple[str, int, int, int, int, int, int, int, int, bool], ...
]


@dataclass(frozen=True, slots=True)
class Rect:
    """表示屏幕中的矩形区域。"""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        """返回矩形宽度。"""
        return self.right - self.left

    @property
    def height(self) -> int:
        """返回矩形高度。"""
        return self.bottom - self.top

    def to_list(self) -> list[int]:
        """
        将矩形转换为可写入 JSON 的列表。

        Returns:
            list[int]: 按左、上、右、下排列的坐标。
        """
        return [self.left, self.top, self.right, self.bottom]

    @classmethod
    def from_list(cls, values: list[int]) -> "Rect":
        """
        从四个坐标创建矩形。

        Args:
            values (list[int]): 左、上、右、下坐标。

        Returns:
            Rect: 对应的矩形。

        Raises:
            ValueError: 坐标数量不是四个时触发。
        """
        if len(values) != 4:
            raise ValueError("矩形必须包含四个坐标")
        return cls(*values)


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    """表示显示器及其可用工作区。"""

    handle: int
    device: str
    bounds: Rect
    work_area: Rect
    primary: bool


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """表示一个可管理的顶级窗口。"""

    hwnd: int
    title: str
    pid: int
    executable: str
    rect: Rect
    monitor: MonitorInfo
    topmost: bool
    maximized: bool


@dataclass(frozen=True, slots=True)
class RestoreSummary:
    """表示一次布局恢复的统计结果。"""

    succeeded: int
    skipped: int
    failed: int
    conflicts: int = 0


@dataclass(frozen=True, slots=True)
class RestorePlanItem:
    """表示恢复计划中的一个窗口条目。"""

    rule_id: str
    executable: str
    title_pattern: str
    window: WindowInfo | None
    target_rect: Rect | None
    target_monitor_device: str | None
    maximized: bool
    status: str
    reason: str


@dataclass(frozen=True, slots=True)
class RestorePlan:
    """表示经匹配和坐标换算后尚未执行的不可变恢复计划。"""

    operation_id: str
    profile_id: str
    profile_name: str
    preview_required: bool
    monitor_signature: MonitorSignature
    items: tuple[RestorePlanItem, ...]

    @property
    def ready_count(self) -> int:
        """返回可以执行的计划项数量。"""
        return sum(item.status == "ready" for item in self.items)

    @property
    def skipped_count(self) -> int:
        """返回因窗口缺失而跳过的计划项数量。"""
        return sum(item.status == "skipped" for item in self.items)

    @property
    def conflict_count(self) -> int:
        """返回存在多候选冲突的计划项数量。"""
        return sum(item.status == "conflict" for item in self.items)


@dataclass(frozen=True, slots=True)
class OperationResult(Generic[T]):
    """表示应用服务执行一次操作后的统一结果。"""

    success: bool
    message: str
    payload: T | None = None
    refresh_required: bool = False


@dataclass(frozen=True, slots=True)
class DisplayChangeState:
    """表示当前显示器拓扑及与其匹配的布局。"""

    monitor_signature: MonitorSignature
    matching_profiles: tuple[str, ...]
    debounce_ms: int


@dataclass(frozen=True, slots=True)
class HotkeySetting:
    """表示快捷键设置窗口使用的一项动作绑定。"""

    action: str
    label: str
    shortcut: str
    enabled: bool
