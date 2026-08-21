"""窗口枚举与控制功能。"""

import os

import psutil
import pywintypes
import win32con
import win32gui
import win32process

from core.models import Rect, WindowInfo
from utils.win_api import get_monitor_for_window, is_window_cloaked, rect_from_tuple


def _window_process(hwnd: int) -> tuple[int, str]:
    """
    获取窗口所属进程信息。

    Args:
        hwnd (int): 窗口句柄。

    Returns:
        tuple[int, str]: 进程 ID 与可执行文件名。
    """
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid, psutil.Process(pid).name()


def _window_placement(hwnd: int) -> tuple[Rect, bool]:
    """
    获取窗口的普通状态矩形和最大化状态。

    Args:
        hwnd (int): 窗口句柄。

    Returns:
        tuple[Rect, bool]: 普通窗口矩形与是否最大化。
    """
    placement = win32gui.GetWindowPlacement(hwnd)
    normal_rect = rect_from_tuple(placement[4])
    maximized = placement[1] == win32con.SW_SHOWMAXIMIZED
    return normal_rect, maximized


def get_window_info(hwnd: int) -> WindowInfo:
    """
    获取一个窗口的完整信息。

    Args:
        hwnd (int): 窗口句柄。

    Returns:
        WindowInfo: 窗口信息。

    Raises:
        ValueError: 句柄无效或窗口没有标题时触发。
    """
    if not win32gui.IsWindow(hwnd):
        raise ValueError("窗口已经关闭")
    title = win32gui.GetWindowText(hwnd).strip()
    if not title:
        raise ValueError("窗口没有标题")
    pid, executable = _window_process(hwnd)
    exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    normal_rect, maximized = _window_placement(hwnd)
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        pid=pid,
        executable=executable,
        rect=normal_rect,
        monitor=get_monitor_for_window(hwnd),
        topmost=bool(exstyle & win32con.WS_EX_TOPMOST),
        maximized=maximized,
    )


def is_manageable_window(hwnd: int, own_pid: int | None = None) -> bool:
    """
    判断顶级窗口是否应显示在管理列表中。

    Args:
        hwnd (int): 窗口句柄。
        own_pid (int | None): 需要排除的本程序进程 ID。

    Returns:
        bool: 窗口可管理时返回 True。
    """
    try:
        if not win32gui.IsWindowVisible(hwnd) or not win32gui.GetWindowText(hwnd).strip():
            return False
        exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if exstyle & win32con.WS_EX_TOOLWINDOW or is_window_cloaked(hwnd):
            return False
        pid, _ = _window_process(hwnd)
        return own_pid is None or pid != own_pid
    except (OSError, psutil.Error, ValueError):
        return False


def enumerate_windows() -> list[WindowInfo]:
    """
    枚举当前会话中可管理的顶级窗口。

    Returns:
        list[WindowInfo]: 按进程名和标题排序的窗口列表。
    """
    windows: list[WindowInfo] = []

    def callback(hwnd: int, _: object) -> bool:
        """收集单个可管理窗口。"""
        if is_manageable_window(hwnd, os.getpid()):
            try:
                windows.append(get_window_info(hwnd))
            except (OSError, psutil.Error, ValueError):
                pass
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except pywintypes.error as error:
        raise OSError(f"无法枚举桌面窗口：{error}") from error
    return sorted(windows, key=lambda item: (item.executable.casefold(), item.title.casefold()))


def get_foreground_window() -> int:
    """
    获取当前前台窗口句柄。

    Returns:
        int: 前台窗口句柄。

    Raises:
        ValueError: 当前没有有效前台窗口时触发。
    """
    try:
        hwnd = int(win32gui.GetForegroundWindow())
    except pywintypes.error as error:
        raise OSError(f"无法获取前台窗口：{error}") from error
    if not hwnd or not win32gui.IsWindow(hwnd):
        raise ValueError("当前没有可操作的前台窗口")
    return hwnd


def activate_and_flash_window(hwnd: int) -> bool:
    """
    恢复最小化窗口、请求前台激活并闪烁窗口和任务栏按钮。

    Args:
        hwnd (int): 目标窗口句柄。

    Returns:
        bool: 目标窗口成功成为前台窗口时返回 True。

    Raises:
        ValueError: 窗口已经关闭时触发。
        OSError: Windows API 调用失败时触发。
    """
    target_hwnd = get_root_owner_window(hwnd)
    try:
        if win32gui.IsIconic(target_hwnd):
            win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)
        win32gui.BringWindowToTop(target_hwnd)
        win32gui.SetForegroundWindow(target_hwnd)
        activated = int(win32gui.GetForegroundWindow()) == target_hwnd
        win32gui.FlashWindowEx(target_hwnd, win32con.FLASHW_ALL, 3, 0)
    except pywintypes.error as error:
        raise OSError(f"无法激活或闪烁窗口：{error}") from error
    return activated


def minimize_all_windows(manager_hwnd: int | None = None) -> int:
    """
    最小化当前全部可管理程序窗口，并在可见时包含管理器自身。

    Args:
        manager_hwnd (int | None): WindowMaster 主窗口句柄。

    Returns:
        int: 已请求最小化的窗口数量。

    Raises:
        OSError: 枚举窗口或最小化窗口失败时触发。
    """
    windows = enumerate_windows()
    minimized = 0
    failures: list[str] = []
    for window in windows:
        try:
            win32gui.ShowWindow(window.hwnd, win32con.SW_MINIMIZE)
            minimized += 1
        except pywintypes.error as error:
            failures.append(f"{window.title}：{error}")
    if manager_hwnd and win32gui.IsWindowVisible(manager_hwnd):
        try:
            win32gui.ShowWindow(manager_hwnd, win32con.SW_MINIMIZE)
            minimized += 1
        except pywintypes.error as error:
            failures.append(f"WindowMaster：{error}")
    if failures:
        raise OSError("部分窗口无法最小化：" + "；".join(failures))
    return minimized


def set_opacity(hwnd: int, percent: int) -> None:
    """
    设置窗口透明度。

    Args:
        hwnd (int): 窗口句柄。
        percent (int): 30 到 100 的不透明度百分比。

    Raises:
        ValueError: 百分比越界或窗口无效时触发。
    """
    if not 30 <= percent <= 100:
        raise ValueError("透明度必须在 30% 到 100% 之间")
    if not win32gui.IsWindow(hwnd):
        raise ValueError("窗口已经关闭")
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style | win32con.WS_EX_LAYERED)
    alpha = round(percent * 255 / 100)
    win32gui.SetLayeredWindowAttributes(hwnd, 0, alpha, win32con.LWA_ALPHA)


def get_root_owner_window(hwnd: int) -> int:
    """
    获取适合执行置顶操作的可见根拥有者窗口。

    Args:
        hwnd (int): 原始窗口句柄。

    Returns:
        int: 规范化后的顶级窗口句柄。

    Raises:
        ValueError: 窗口已经关闭时触发。
        OSError: Windows API 调用失败时触发。
    """
    if not win32gui.IsWindow(hwnd):
        raise ValueError("窗口已经关闭")
    try:
        root = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOT)) or hwnd
        root_owner = int(win32gui.GetAncestor(hwnd, win32con.GA_ROOTOWNER)) or root
        if win32gui.IsWindow(root_owner) and win32gui.IsWindowVisible(root_owner):
            return root_owner
        return root
    except pywintypes.error as error:
        raise OSError(f"无法获取窗口根拥有者：{error}") from error


def _apply_topmost_state(hwnd: int, enabled: bool) -> bool:
    """
    对已规范化的窗口句柄应用并验证置顶状态。

    Args:
        hwnd (int): 已规范化的顶级窗口句柄。
        enabled (bool): True 表示置顶。

    Returns:
        bool: Windows API 执行后的实际置顶状态。

    Raises:
        OSError: 操作失败或执行后的状态不符合预期时触发。
    """
    target = win32con.HWND_TOPMOST if enabled else win32con.HWND_NOTOPMOST
    try:
        win32gui.SetWindowPos(
            hwnd,
            target,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
    except pywintypes.error as error:
        action = "置顶" if enabled else "取消置顶"
        raise OSError(f"无法{action}窗口：{error}") from error
    actual = is_topmost(hwnd, normalize=False)
    if actual != enabled:
        action = "置顶" if enabled else "取消置顶"
        raise OSError(f"窗口未能{action}，应用可能拒绝或立即重置了置顶状态")
    return actual


def clear_other_topmost_windows(target_hwnd: int) -> list[int]:
    """
    取消目标窗口所在显示器上的其他可管理置顶窗口。

    Args:
        target_hwnd (int): 即将置顶的目标窗口句柄。

    Returns:
        list[int]: 已成功取消置顶的根窗口句柄。

    Raises:
        OSError: 任一旧置顶窗口无法取消时触发。
    """
    normalized_target = get_root_owner_window(target_hwnd)
    target_monitor = get_monitor_for_window(normalized_target)
    cleared: list[int] = []
    processed: set[int] = {normalized_target}
    failures: list[str] = []
    for window in enumerate_windows():
        if not window.topmost or window.monitor.device != target_monitor.device:
            continue
        try:
            candidate = get_root_owner_window(window.hwnd)
            if candidate in processed:
                continue
            processed.add(candidate)
            _apply_topmost_state(candidate, False)
            cleared.append(candidate)
        except (OSError, ValueError) as error:
            failures.append(f"{window.title}：{error}")
    if failures:
        details = "；".join(failures)
        raise OSError(f"无法取消同屏旧置顶窗口：{details}")
    return cleared


def set_topmost(hwnd: int, enabled: bool) -> bool:
    """
    设置或取消窗口置顶。

    Args:
        hwnd (int): 窗口句柄，内部会规范化到可见根拥有者窗口。
        enabled (bool): True 表示置顶。

    Returns:
        bool: Windows API 执行后的实际置顶状态。

    Raises:
        OSError: 操作失败或执行后的状态不符合预期时触发。
    """
    target_hwnd = get_root_owner_window(hwnd)
    if enabled:
        clear_other_topmost_windows(target_hwnd)
    return _apply_topmost_state(target_hwnd, enabled)


def is_topmost(hwnd: int, normalize: bool = True) -> bool:
    """
    判断窗口当前是否置顶。

    Args:
        hwnd (int): 窗口句柄。
        normalize (bool): 是否先规范化到可见根拥有者窗口。

    Returns:
        bool: 窗口处于置顶层时返回 True。

    Raises:
        ValueError: 窗口已经关闭时触发。
    """
    target_hwnd = get_root_owner_window(hwnd) if normalize else hwnd
    if not win32gui.IsWindow(target_hwnd):
        raise ValueError("窗口已经关闭")
    try:
        style = win32gui.GetWindowLong(target_hwnd, win32con.GWL_EXSTYLE)
    except pywintypes.error as error:
        raise OSError(f"无法读取窗口置顶状态：{error}") from error
    return bool(style & win32con.WS_EX_TOPMOST)


def toggle_topmost(hwnd: int) -> bool:
    """
    切换窗口置顶状态。

    Args:
        hwnd (int): 窗口句柄。

    Returns:
        bool: 切换后的置顶状态。
    """
    target_hwnd = get_root_owner_window(hwnd)
    enabled = not is_topmost(target_hwnd, normalize=False)
    return set_topmost(target_hwnd, enabled)


def move_window(hwnd: int, rect: Rect) -> None:
    """
    将窗口恢复并移动到指定矩形。

    Args:
        hwnd (int): 窗口句柄。
        rect (Rect): 目标矩形。
    """
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(
        hwnd,
        0,
        rect.left,
        rect.top,
        rect.width,
        rect.height,
        win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
    )


def split_window(hwnd: int, side: str) -> Rect:
    """
    将窗口移动到所在显示器的左半区或右半区。

    Args:
        hwnd (int): 窗口句柄。
        side (str): `left` 或 `right`。

    Returns:
        Rect: 实际使用的目标矩形。

    Raises:
        ValueError: 分屏方向无效时触发。
    """
    if side not in {"left", "right"}:
        raise ValueError("分屏方向必须是 left 或 right")
    work = get_monitor_for_window(hwnd).work_area
    middle = work.left + work.width // 2
    rect = (
        Rect(work.left, work.top, middle, work.bottom)
        if side == "left"
        else Rect(middle, work.top, work.right, work.bottom)
    )
    move_window(hwnd, rect)
    return rect


def maximize_window(hwnd: int) -> None:
    """
    最大化指定窗口。

    Args:
        hwnd (int): 窗口句柄。
    """
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
