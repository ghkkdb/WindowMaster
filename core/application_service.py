"""WindowMaster 的应用级业务编排服务。"""

from __future__ import annotations

from core.config import load_config, save_config
from core.config_schema import HotkeyBinding
from core.hotkeys import (
    HOTKEY_LABELS,
    action_for_hotkey_id,
    normalize_hotkey_bindings,
    register_hotkeys,
    unregister_hotkeys,
    validate_hotkey_bindings,
)
from core.layout import (
    create_restore_plan,
    delete_profile,
    execute_restore_plan,
    find_matching_profile_names,
    get_profile_names,
    monitor_signature,
    save_profile,
)
from core.models import (
    DisplayChangeState,
    HotkeySetting,
    OperationResult,
    Rect,
    RestorePlan,
    RestoreSummary,
    WindowInfo,
)
from core.window_manager import (
    activate_and_flash_window,
    enumerate_windows,
    get_foreground_window,
    maximize_window,
    minimize_all_windows,
    set_opacity,
    split_window,
    toggle_topmost,
)
from utils.win_api import get_monitors


class ApplicationService:
    """统一编排窗口操作、布局持久化与恢复流程。"""

    def __init__(self) -> None:
        """初始化空的窗口快照。"""
        self._windows: tuple[WindowInfo, ...] = ()

    @property
    def windows(self) -> tuple[WindowInfo, ...]:
        """返回最近一次成功刷新的不可变窗口快照。"""
        return self._windows

    def refresh_windows(self) -> OperationResult[tuple[WindowInfo, ...]]:
        """
        重新枚举可管理窗口并更新服务快照。

        Returns:
            OperationResult[tuple[WindowInfo, ...]]: 刷新结果和窗口快照。
        """
        try:
            windows = tuple(enumerate_windows())
        except OSError as error:
            return OperationResult(False, f"刷新窗口失败：{error}")
        self._windows = windows
        return OperationResult(True, "窗口列表已刷新", windows)

    def set_window_opacity(self, hwnd: int, percent: int) -> OperationResult[None]:
        """
        设置目标窗口不透明度。

        Args:
            hwnd (int): 目标窗口句柄。
            percent (int): 30 到 100 的不透明度百分比。

        Returns:
            OperationResult[None]: 操作结果。
        """
        try:
            set_opacity(hwnd, percent)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"设置透明度失败：{error}")
        return OperationResult(True, f"已设置不透明度为 {percent}%")

    def activate_window(self, hwnd: int) -> OperationResult[bool]:
        """
        激活目标窗口并闪烁提示。

        Args:
            hwnd (int): 目标窗口句柄。

        Returns:
            OperationResult[bool]: 操作结果和是否成功切换到前台。
        """
        try:
            activated = activate_and_flash_window(hwnd)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"激活窗口失败：{error}")
        if activated:
            return OperationResult(True, "已激活并闪烁目标窗口", True)
        return OperationResult(
            True,
            "Windows 阻止了前台切换，已闪烁目标窗口",
            False,
        )

    def minimize_all_programs(
        self, manager_hwnd: int | None = None
    ) -> OperationResult[int]:
        """
        最小化当前全部可管理程序窗口。

        Args:
            manager_hwnd (int | None): WindowMaster 主窗口句柄。

        Returns:
            OperationResult[int]: 操作结果和已最小化窗口数量。
        """
        try:
            count = minimize_all_windows(manager_hwnd)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"最小化全部程序失败：{error}")
        return OperationResult(True, f"已最小化 {count} 个程序窗口", count, True)

    def toggle_window_topmost(self, hwnd: int) -> OperationResult[bool]:
        """
        切换目标窗口置顶状态。

        Args:
            hwnd (int): 目标窗口句柄。

        Returns:
            OperationResult[bool]: 操作结果和切换后的置顶状态。
        """
        try:
            enabled = toggle_topmost(hwnd)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"切换置顶失败：{error}")
        state = "置顶" if enabled else "取消置顶"
        return OperationResult(True, f"已{state}窗口", enabled, True)

    def split_window(self, hwnd: int, side: str) -> OperationResult[Rect]:
        """
        将目标窗口移动到所在显示器的指定半屏。

        Args:
            hwnd (int): 目标窗口句柄。
            side (str): `left` 或 `right`。

        Returns:
            OperationResult[Rect]: 操作结果和目标矩形。
        """
        label = "左半屏" if side == "left" else "右半屏"
        try:
            rect = split_window(hwnd, side)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"移动到{label}失败：{error}")
        return OperationResult(True, f"已移动到{label}", rect, True)

    def maximize_window(self, hwnd: int) -> OperationResult[None]:
        """
        最大化目标窗口。

        Args:
            hwnd (int): 目标窗口句柄。

        Returns:
            OperationResult[None]: 操作结果。
        """
        try:
            maximize_window(hwnd)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"最大化窗口失败：{error}")
        return OperationResult(True, "已最大化窗口", refresh_required=True)

    def get_profile_names(self) -> OperationResult[list[str]]:
        """
        获取全部命名布局。

        Returns:
            OperationResult[list[str]]: 操作结果和排序后的布局名称。
        """
        try:
            names = get_profile_names()
        except (OSError, ValueError) as error:
            return OperationResult(False, f"读取布局失败：{error}")
        return OperationResult(True, "", names)

    def get_tray_enabled(self) -> OperationResult[bool]:
        """
        读取系统托盘偏好设置。

        Returns:
            OperationResult[bool]: 操作结果和系统托盘启用状态。
        """
        try:
            enabled = load_config().preferences.tray_enabled
        except (OSError, ValueError) as error:
            return OperationResult(False, f"读取系统托盘设置失败：{error}")
        return OperationResult(True, "", enabled)

    def set_tray_enabled(self, enabled: bool) -> OperationResult[bool]:
        """
        保存系统托盘偏好设置。

        Args:
            enabled (bool): 是否启用系统托盘。

        Returns:
            OperationResult[bool]: 操作结果和保存后的启用状态。
        """
        try:
            config = load_config()
            config.preferences.tray_enabled = enabled
            save_config(config)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"保存系统托盘设置失败：{error}")
        state = "启用" if enabled else "关闭"
        return OperationResult(True, f"已{state}系统托盘", enabled)

    def get_hotkey_settings(self) -> OperationResult[tuple[HotkeySetting, ...]]:
        """
        读取、补齐并转换全部可配置快捷键。

        Returns:
            OperationResult[tuple[HotkeySetting, ...]]: 快捷键设置列表。
        """
        try:
            bindings = normalize_hotkey_bindings(load_config().preferences.hotkeys)
            validate_hotkey_bindings(bindings)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"读取快捷键设置失败：{error}")
        settings = tuple(
            HotkeySetting(
                action=binding.action,
                label=HOTKEY_LABELS[binding.action],
                shortcut=binding.shortcut,
                enabled=binding.enabled,
            )
            for binding in bindings
        )
        return OperationResult(True, "", settings)

    def register_configured_hotkeys(self, hwnd: int) -> OperationResult[tuple[str, ...]]:
        """
        按当前配置注册全局快捷键。

        Args:
            hwnd (int): 接收快捷键消息的主窗口句柄。

        Returns:
            OperationResult[tuple[str, ...]]: 注册结果和冲突说明。
        """
        try:
            bindings = normalize_hotkey_bindings(load_config().preferences.hotkeys)
            failures = tuple(register_hotkeys(hwnd, bindings))
        except (OSError, ValueError) as error:
            return OperationResult(False, f"注册快捷键失败：{error}")
        if failures:
            return OperationResult(False, f"快捷键注册失败：{', '.join(failures)}", failures)
        return OperationResult(True, "快捷键已注册", ())

    def update_hotkey_settings(
        self, hwnd: int, settings: tuple[HotkeySetting, ...]
    ) -> OperationResult[tuple[HotkeySetting, ...]]:
        """
        校验并替换全局快捷键，注册或保存失败时恢复旧绑定。

        Args:
            hwnd (int): 接收快捷键消息的主窗口句柄。
            settings (tuple[HotkeySetting, ...]): 用户确认的新快捷键设置。

        Returns:
            OperationResult[tuple[HotkeySetting, ...]]: 更新结果和生效设置。
        """
        try:
            config = load_config()
            old_bindings = normalize_hotkey_bindings(config.preferences.hotkeys)
            new_bindings = [
                HotkeyBinding(item.action, item.shortcut, item.enabled)
                for item in settings
            ]
            validate_hotkey_bindings(new_bindings)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"快捷键设置无效：{error}")

        unregister_hotkeys(hwnd)
        failures = register_hotkeys(hwnd, new_bindings)
        if failures:
            unregister_hotkeys(hwnd)
            rollback_failures = register_hotkeys(hwnd, old_bindings)
            message = f"快捷键冲突：{', '.join(failures)}"
            if rollback_failures:
                message += f"；恢复旧快捷键失败：{', '.join(rollback_failures)}"
            return OperationResult(False, message)

        try:
            config.preferences.hotkeys = new_bindings
            save_config(config)
        except (OSError, ValueError) as error:
            unregister_hotkeys(hwnd)
            register_hotkeys(hwnd, old_bindings)
            return OperationResult(False, f"保存快捷键失败，已恢复旧设置：{error}")
        return OperationResult(True, "快捷键设置已保存并立即生效", settings)

    def get_display_change_state(self) -> OperationResult[DisplayChangeState]:
        """
        获取当前显示器拓扑、匹配布局和显示变化防抖时间。

        Returns:
            OperationResult[DisplayChangeState]: 显示器变化处理所需的只读状态。
        """
        try:
            config = load_config()
            monitors = get_monitors()
            if not monitors:
                raise ValueError("没有检测到显示器")
            state = DisplayChangeState(
                monitor_signature=monitor_signature(monitors),
                matching_profiles=tuple(
                    find_matching_profile_names(config, monitors)
                ),
                debounce_ms=config.preferences.display_change_debounce_ms,
            )
        except (OSError, ValueError) as error:
            return OperationResult(False, f"读取显示器状态失败：{error}")
        return OperationResult(True, "", state)

    def profile_exists(self, name: str) -> OperationResult[bool]:
        """
        判断命名布局是否存在。

        Args:
            name (str): 布局名称。

        Returns:
            OperationResult[bool]: 操作结果和存在状态。
        """
        try:
            exists = name in load_config().profiles
        except (OSError, ValueError) as error:
            return OperationResult(False, f"读取布局失败：{error}")
        return OperationResult(True, "", exists)

    def save_current_profile(self, name: str) -> OperationResult[int]:
        """
        将最近窗口快照保存为命名布局。

        Args:
            name (str): 布局名称。

        Returns:
            OperationResult[int]: 操作结果和保存的窗口数量。
        """
        try:
            save_profile(name, list(self._windows))
        except (OSError, ValueError) as error:
            return OperationResult(False, f"保存布局失败：{error}")
        count = len(self._windows)
        return OperationResult(True, f"已保存布局“{name}”，共 {count} 个窗口", count)

    def delete_profile(self, name: str) -> OperationResult[bool]:
        """
        删除指定命名布局。

        Args:
            name (str): 布局名称。

        Returns:
            OperationResult[bool]: 操作结果和是否实际删除。
        """
        try:
            deleted = delete_profile(name)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"删除布局失败：{error}")
        if not deleted:
            return OperationResult(False, f"布局不存在：{name}", False)
        return OperationResult(True, f"已删除布局“{name}”", True)

    def prepare_restore(self, name: str) -> OperationResult[RestorePlan]:
        """
        刷新窗口快照并生成不含窗口副作用的恢复计划。

        Args:
            name (str): 布局名称。

        Returns:
            OperationResult[RestorePlan]: 操作结果和恢复计划。
        """
        try:
            current_windows = enumerate_windows()
        except OSError as error:
            return OperationResult(False, f"准备恢复失败：刷新窗口失败：{error}")
        try:
            plan = create_restore_plan(name, current_windows)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"生成恢复计划失败：{error}")
        return OperationResult(True, "恢复计划已生成", plan)

    def execute_restore(self, plan: RestorePlan) -> OperationResult[RestoreSummary]:
        """
        验证并执行已确认的恢复计划。

        Args:
            plan (RestorePlan): 用户确认后的恢复计划。

        Returns:
            OperationResult[RestoreSummary]: 操作结果和恢复统计。
        """
        try:
            summary = execute_restore_plan(plan)
        except (OSError, ValueError) as error:
            return OperationResult(False, f"恢复布局失败：{error}")
        message = (
            "布局恢复完成："
            f"成功 {summary.succeeded}，跳过 {summary.skipped}，"
            f"冲突 {summary.conflicts}，失败 {summary.failed}"
        )
        return OperationResult(True, message, summary, True)

    def handle_hotkey(
        self,
        hotkey_id: int,
        manager_hwnd: int,
        selected_hwnd: int | None,
    ) -> OperationResult[None]:
        """
        将全局快捷键转换为统一窗口操作。

        Args:
            hotkey_id (int): RegisterHotKey 使用的快捷键 ID。
            manager_hwnd (int): WindowMaster 主窗口句柄。
            selected_hwnd (int | None): 主窗口当前选中窗口句柄。

        Returns:
            OperationResult[None]: 快捷键操作结果。
        """
        try:
            action = action_for_hotkey_id(hotkey_id)
            if action is None:
                return OperationResult(True, "")
            if action == "minimize_all":
                count = minimize_all_windows(manager_hwnd)
                return OperationResult(
                    True,
                    f"快捷键：已最小化 {count} 个程序窗口",
                    refresh_required=True,
                )
            hwnd = get_foreground_window()
            if action == "toggle_topmost":
                if hwnd == manager_hwnd:
                    if selected_hwnd is None:
                        raise ValueError("请先激活目标窗口，或在列表中选择一个窗口")
                    hwnd = selected_hwnd
                enabled = toggle_topmost(hwnd)
                state = "置顶" if enabled else "取消置顶"
                message = f"快捷键：已{state}前台窗口"
            elif action == "split_left":
                split_window(hwnd, "left")
                message = "快捷键：前台窗口已移动到左半屏"
            elif action == "split_right":
                split_window(hwnd, "right")
                message = "快捷键：前台窗口已移动到右半屏"
        except (OSError, ValueError) as error:
            return OperationResult(False, f"快捷键操作失败：{error}")
        return OperationResult(True, message, refresh_required=True)
