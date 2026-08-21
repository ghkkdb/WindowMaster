"""对 WindowMaster 所需的底层 Windows API 进行封装。"""

import ctypes
from ctypes import wintypes

import win32api
import win32con
import win32gui

from core.models import MonitorInfo, Rect


DWMWA_CLOAKED = 14


def enable_per_monitor_dpi_awareness() -> None:
    """
    尽早启用 Per-Monitor DPI Awareness V2。

    已由清单或宿主设置 DPI 模式时保持现状。
    """
    try:
        context = ctypes.c_void_p(-4)
        ctypes.windll.user32.SetProcessDpiAwarenessContext(context)
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def is_window_cloaked(hwnd: int) -> bool:
    """
    判断窗口是否被桌面窗口管理器隐藏。

    Args:
        hwnd (int): 窗口句柄。

    Returns:
        bool: 被隐藏时返回 True。
    """
    cloaked = wintypes.DWORD(0)
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd), DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
    )
    return result == 0 and bool(cloaked.value)


def rect_from_tuple(values: tuple[int, int, int, int]) -> Rect:
    """
    将 pywin32 坐标元组转换为矩形。

    Args:
        values (tuple[int, int, int, int]): 左、上、右、下坐标。

    Returns:
        Rect: 对应矩形。
    """
    return Rect(*values)


def get_monitor_info(handle: int) -> MonitorInfo:
    """
    获取指定显示器的信息。

    Args:
        handle (int): 显示器句柄。

    Returns:
        MonitorInfo: 显示器边界及工作区。
    """
    data = win32api.GetMonitorInfo(handle)
    return MonitorInfo(
        handle=int(handle),
        device=str(data.get("Device", "")),
        bounds=rect_from_tuple(data["Monitor"]),
        work_area=rect_from_tuple(data["Work"]),
        primary=bool(data.get("Flags", 0) & win32con.MONITORINFOF_PRIMARY),
    )


def get_monitor_for_window(hwnd: int) -> MonitorInfo:
    """
    获取距离窗口最近的显示器。

    Args:
        hwnd (int): 窗口句柄。

    Returns:
        MonitorInfo: 窗口所在显示器。
    """
    handle = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
    return get_monitor_info(handle)


def get_monitors() -> list[MonitorInfo]:
    """
    枚举当前所有显示器。

    Returns:
        list[MonitorInfo]: 当前显示器列表。
    """
    monitors: list[MonitorInfo] = []
    for handle, _, _ in win32api.EnumDisplayMonitors():
        monitors.append(get_monitor_info(handle))
    return monitors

