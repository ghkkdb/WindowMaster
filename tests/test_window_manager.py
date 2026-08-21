"""窗口筛选和操作测试。"""

from unittest.mock import patch

import pytest
import win32con

from core.models import MonitorInfo, Rect, WindowInfo
from core.window_manager import (
    activate_and_flash_window,
    clear_other_topmost_windows,
    get_root_owner_window,
    is_manageable_window,
    minimize_all_windows,
    set_topmost,
    set_opacity,
    split_window,
    toggle_topmost,
)


def test_activate_and_flash_restores_minimized_window() -> None:
    """激活最小化窗口时应先恢复，再切换前台并闪烁提示。"""
    with (
        patch("core.window_manager.get_root_owner_window", return_value=200),
        patch("core.window_manager.win32gui.IsIconic", return_value=True),
        patch("core.window_manager.win32gui.ShowWindow") as show,
        patch("core.window_manager.win32gui.BringWindowToTop") as bring,
        patch("core.window_manager.win32gui.SetForegroundWindow") as foreground,
        patch("core.window_manager.win32gui.GetForegroundWindow", return_value=200),
        patch("core.window_manager.win32gui.FlashWindowEx") as flash,
    ):
        assert activate_and_flash_window(100)
    show.assert_called_once_with(200, win32con.SW_RESTORE)
    bring.assert_called_once_with(200)
    foreground.assert_called_once_with(200)
    flash.assert_called_once_with(200, win32con.FLASHW_ALL, 3, 0)


def test_activate_and_flash_reports_foreground_rejection() -> None:
    """Windows 拒绝前台切换时仍应闪烁窗口并返回 False。"""
    with (
        patch("core.window_manager.get_root_owner_window", return_value=200),
        patch("core.window_manager.win32gui.IsIconic", return_value=False),
        patch("core.window_manager.win32gui.ShowWindow") as show,
        patch("core.window_manager.win32gui.BringWindowToTop"),
        patch("core.window_manager.win32gui.SetForegroundWindow"),
        patch("core.window_manager.win32gui.GetForegroundWindow", return_value=300),
        patch("core.window_manager.win32gui.FlashWindowEx") as flash,
    ):
        assert not activate_and_flash_window(100)
    show.assert_not_called()
    flash.assert_called_once()


def test_minimize_all_windows_minimizes_each_manageable_window() -> None:
    """最小化全部程序应逐一最小化当前可管理窗口。"""
    monitor = MonitorInfo(1, "DISPLAY1", Rect(0, 0, 100, 100), Rect(0, 0, 100, 100), True)
    windows = [
        WindowInfo(100, "A", 1, "a.exe", Rect(0, 0, 50, 50), monitor, False, False),
        WindowInfo(200, "B", 2, "b.exe", Rect(0, 0, 50, 50), monitor, False, False),
    ]
    with (
        patch("core.window_manager.enumerate_windows", return_value=windows),
        patch("core.window_manager.win32gui.ShowWindow") as show,
    ):
        assert minimize_all_windows() == 2
    assert [call.args for call in show.call_args_list] == [
        (100, win32con.SW_MINIMIZE),
        (200, win32con.SW_MINIMIZE),
    ]


def test_minimize_all_includes_visible_manager_window() -> None:
    """从主界面执行最小化全部时应包含可见的 WindowMaster 窗口。"""
    with (
        patch("core.window_manager.enumerate_windows", return_value=[]),
        patch("core.window_manager.win32gui.IsWindowVisible", return_value=True),
        patch("core.window_manager.win32gui.ShowWindow") as show,
    ):
        assert minimize_all_windows(500) == 1
    show.assert_called_once_with(500, win32con.SW_MINIMIZE)


@patch("core.window_manager._window_process", return_value=(10, "app.exe"))
@patch("core.window_manager.is_window_cloaked", return_value=False)
@patch("core.window_manager.win32gui.GetWindowLong", return_value=0)
@patch("core.window_manager.win32gui.GetWindowText", return_value="窗口")
@patch("core.window_manager.win32gui.IsWindowVisible", return_value=True)
def test_manageable_window_filter(
    visible: object,
    title: object,
    style: object,
    cloaked: object,
    process: object,
) -> None:
    """普通可见顶级窗口应通过筛选，本进程窗口应排除。"""
    assert is_manageable_window(100, own_pid=20)
    assert not is_manageable_window(100, own_pid=10)


def test_tool_window_is_filtered() -> None:
    """工具窗口不应出现在管理列表中。"""
    with (
        patch("core.window_manager.win32gui.IsWindowVisible", return_value=True),
        patch("core.window_manager.win32gui.GetWindowText", return_value="工具"),
        patch("core.window_manager.win32gui.GetWindowLong", return_value=win32con.WS_EX_TOOLWINDOW),
    ):
        assert not is_manageable_window(100)


def test_opacity_rejects_unsafe_value() -> None:
    """透明度低于 30% 时应拒绝操作。"""
    with pytest.raises(ValueError, match="30%"):
        set_opacity(100, 20)


def test_toggle_topmost_can_enable_and_disable() -> None:
    """置顶切换应返回 Windows API 验证后的实际状态。"""
    with (
        patch("core.window_manager.get_root_owner_window", return_value=100),
        patch(
            "core.window_manager.is_topmost",
            side_effect=[False, True, True, False],
        ),
        patch("core.window_manager.clear_other_topmost_windows"),
        patch("core.window_manager.win32gui.SetWindowPos") as set_window_pos,
    ):
        assert toggle_topmost(100)
        assert not toggle_topmost(100)
    assert set_window_pos.call_args_list[0].args[1] == win32con.HWND_TOPMOST
    assert set_window_pos.call_args_list[1].args[1] == win32con.HWND_NOTOPMOST


def test_set_topmost_rejects_unconfirmed_state() -> None:
    """执行后状态不符合预期时不应报告虚假的成功。"""
    with (
        patch("core.window_manager.get_root_owner_window", return_value=100),
        patch("core.window_manager.clear_other_topmost_windows"),
        patch("core.window_manager.win32gui.SetWindowPos"),
        patch("core.window_manager.is_topmost", return_value=True),
        pytest.raises(OSError, match="未能取消置顶"),
    ):
        set_topmost(100, False)


def test_enabling_topmost_clears_only_same_monitor() -> None:
    """新窗口置顶前只应取消同一显示器上的旧置顶窗口。"""
    monitor_a = MonitorInfo(1, "DISPLAY1", Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True)
    monitor_b = MonitorInfo(2, "DISPLAY2", Rect(1920, 0, 3840, 1080), Rect(1920, 0, 3840, 1040), False)
    old_same = WindowInfo(200, "同屏旧窗口", 2, "old.exe", Rect(0, 0, 800, 600), monitor_a, True, False)
    old_other = WindowInfo(300, "异屏窗口", 3, "other.exe", Rect(1920, 0, 2720, 600), monitor_b, True, False)
    with (
        patch("core.window_manager.get_root_owner_window", side_effect=lambda hwnd: hwnd),
        patch("core.window_manager.get_monitor_for_window", return_value=monitor_a),
        patch("core.window_manager.enumerate_windows", return_value=[old_same, old_other]),
        patch("core.window_manager._apply_topmost_state", return_value=False) as apply_state,
    ):
        assert clear_other_topmost_windows(100) == [200]
    apply_state.assert_called_once_with(200, False)


def test_enabling_topmost_clears_old_before_new() -> None:
    """设置新置顶窗口时应先执行同屏旧窗口清理。"""
    call_order: list[str] = []
    with (
        patch("core.window_manager.get_root_owner_window", return_value=100),
        patch(
            "core.window_manager.clear_other_topmost_windows",
            side_effect=lambda hwnd: call_order.append("clear") or [],
        ),
        patch(
            "core.window_manager._apply_topmost_state",
            side_effect=lambda hwnd, enabled: call_order.append("set") or enabled,
        ),
    ):
        assert set_topmost(100, True)
    assert call_order == ["clear", "set"]


def test_root_owner_is_used_for_topmost() -> None:
    """拥有弹窗的应用应规范化到可见根拥有者窗口。"""
    with (
        patch("core.window_manager.win32gui.IsWindow", return_value=True),
        patch(
            "core.window_manager.win32gui.GetAncestor",
            side_effect=[200, 300],
        ),
        patch("core.window_manager.win32gui.IsWindowVisible", return_value=True),
    ):
        assert get_root_owner_window(100) == 300


def test_right_split_uses_monitor_work_area() -> None:
    """右分屏应使用目标显示器工作区并保留负坐标。"""
    monitor = MonitorInfo(
        1,
        "DISPLAY2",
        Rect(-1280, 0, 0, 1024),
        Rect(-1280, 0, 0, 984),
        False,
    )
    with (
        patch("core.window_manager.get_monitor_for_window", return_value=monitor),
        patch("core.window_manager.move_window") as move,
    ):
        result = split_window(100, "right")
    assert result == Rect(-640, 0, 0, 984)
    move.assert_called_once_with(100, result)
