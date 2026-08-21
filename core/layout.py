"""命名窗口布局的捕获、匹配与恢复。"""

import fnmatch
import re
import uuid
from pathlib import Path

from core.config import load_config, save_config
from core.config_schema import AppConfig, ProfileConfig, RestorePolicy, SavedMonitor, WindowRule
from core.models import (
    MonitorInfo,
    MonitorSignature,
    Rect,
    RestorePlan,
    RestorePlanItem,
    RestoreSummary,
    WindowInfo,
)
from core.window_manager import maximize_window, move_window
from utils.win_api import get_monitors


def _title_matches(rule: WindowRule, title: str) -> bool:
    """
    判断窗口标题是否符合规则。

    Args:
        rule (WindowRule): 窗口匹配规则。
        title (str): 当前窗口标题。

    Returns:
        bool: 标题符合规则时返回 True。
    """
    if rule.match_mode == "process_only":
        return True
    if rule.match_mode == "exact":
        return title == rule.title_pattern
    if rule.match_mode == "glob":
        return fnmatch.fnmatchcase(title.casefold(), rule.title_pattern.casefold())
    if rule.match_mode == "regex":
        return re.search(rule.title_pattern, title) is not None
    return False


def _matching_candidates(
    rule: WindowRule, windows: list[WindowInfo]
) -> tuple[list[WindowInfo], str]:
    """
    查找规则的全部候选窗口并给出匹配理由。

    Args:
        rule (WindowRule): 窗口匹配规则。
        windows (list[WindowInfo]): 尚未使用的当前窗口。

    Returns:
        tuple[list[WindowInfo], str]: 候选窗口和匹配理由。
    """
    same_process = [
        window
        for window in windows
        if window.executable.casefold() == rule.executable.casefold()
    ]
    title_matches = [
        window for window in same_process if _title_matches(rule, window.title)
    ]
    if title_matches:
        labels = {
            "exact": "进程名和标题精确匹配",
            "glob": "进程名和标题通配符匹配",
            "regex": "进程名和标题正则匹配",
            "process_only": "仅进程名匹配",
        }
        return title_matches, labels.get(rule.match_mode, "窗口规则匹配")
    if rule.match_mode == "exact" and same_process:
        return same_process, "标题未精确匹配，使用同进程唯一窗口回退"
    return [], "没有找到符合规则的已打开窗口"


def monitor_signature(
    monitors: list[MonitorInfo],
) -> MonitorSignature:
    """
    生成用于检测预览后拓扑变化的显示器签名。

    Args:
        monitors (list[MonitorInfo]): 当前显示器列表。

    Returns:
        tuple[tuple[str, int, int, int, int, int, int, int, int, bool], ...]:
            包含屏幕边界和工作区的稳定拓扑签名。
    """
    return tuple(
        sorted(
            (
                monitor.device,
                monitor.bounds.left,
                monitor.bounds.top,
                monitor.bounds.right,
                monitor.bounds.bottom,
                monitor.work_area.left,
                monitor.work_area.top,
                monitor.work_area.right,
                monitor.work_area.bottom,
                monitor.primary,
            )
            for monitor in monitors
        )
    )


def find_matching_profile_names(
    config: AppConfig, monitors: list[MonitorInfo]
) -> list[str]:
    """
    查找与当前显示器拓扑匹配的命名布局。

    新保存的布局使用完整拓扑签名精确匹配；旧布局则使用窗口规则中保存的
    显示器设备名和工作区进行兼容匹配。

    Args:
        config (AppConfig): 当前应用配置。
        monitors (list[MonitorInfo]): 当前显示器列表。

    Returns:
        list[str]: 按名称排序的匹配布局。
    """
    current_signature = monitor_signature(monitors)
    current_legacy = {
        (
            monitor.device,
            monitor.work_area.left,
            monitor.work_area.top,
            monitor.work_area.right,
            monitor.work_area.bottom,
        )
        for monitor in monitors
    }
    matches: list[str] = []
    for name, profile in config.profiles.items():
        if profile.monitor_signature:
            if profile.monitor_signature == current_signature:
                matches.append(name)
            continue
        legacy_signature = {
            (
                rule.monitor.device,
                rule.monitor.work_area.left,
                rule.monitor.work_area.top,
                rule.monitor.work_area.right,
                rule.monitor.work_area.bottom,
            )
            for rule in profile.windows
        }
        if legacy_signature and legacy_signature == current_legacy:
            matches.append(name)
    return sorted(matches, key=str.casefold)


def window_to_layout_entry(window: WindowInfo) -> WindowRule:
    """
    将窗口信息转换为稳定的布局记录。

    Args:
        window (WindowInfo): 当前窗口信息。

    Returns:
        WindowRule: 强类型布局窗口规则。
    """
    return WindowRule(
        id=str(uuid.uuid4()),
        executable=window.executable,
        title_pattern=window.title,
        match_mode="exact",
        rect=window.rect,
        monitor=SavedMonitor(
            device=window.monitor.device,
            work_area=window.monitor.work_area,
        ),
        maximized=window.maximized,
    )


def save_profile(
    name: str, windows: list[WindowInfo], path: Path | None = None
) -> None:
    """
    新建或覆盖一套命名布局。

    Args:
        name (str): 去除首尾空白后的布局名称。
        windows (list[WindowInfo]): 需要保存的窗口列表。
        path (Path | None): 测试或自定义配置路径。

    Raises:
        ValueError: 布局名称为空或窗口列表为空时触发。
    """
    normalized = name.strip()
    if not normalized:
        raise ValueError("布局名称不能为空")
    if not windows:
        raise ValueError("当前没有可保存的窗口")
    config = load_config(path)
    existing = config.profiles.get(normalized)
    current_monitors = get_monitors()
    config.profiles[normalized] = ProfileConfig(
        id=existing.id if existing is not None else str(uuid.uuid4()),
        name=normalized,
        windows=[window_to_layout_entry(window) for window in windows],
        restore_policy=(
            existing.restore_policy if existing is not None else RestorePolicy()
        ),
        monitor_signature=monitor_signature(current_monitors),
    )
    save_config(config, path)


def delete_profile(name: str, path: Path | None = None) -> bool:
    """
    删除指定命名布局。

    Args:
        name (str): 布局名称。
        path (Path | None): 测试或自定义配置路径。

    Returns:
        bool: 找到并删除布局时返回 True。
    """
    config = load_config(path)
    if name not in config.profiles:
        return False
    del config.profiles[name]
    save_config(config, path)
    return True


def get_profile_names(path: Path | None = None) -> list[str]:
    """
    获取全部布局名称。

    Args:
        path (Path | None): 测试或自定义配置路径。

    Returns:
        list[str]: 按名称排序的布局列表。
    """
    return sorted(load_config(path).profiles, key=str.casefold)


def match_layout_windows(
    entries: list[WindowRule], windows: list[WindowInfo]
) -> list[tuple[WindowRule, WindowInfo | None]]:
    """
    按进程名和标题将布局记录一对一匹配到当前窗口。

    Args:
        entries (list[WindowRule]): 布局中的窗口规则。
        windows (list[WindowInfo]): 当前可管理窗口。

    Returns:
        list[tuple[WindowRule, WindowInfo | None]]: 每条规则及匹配窗口。
    """
    unused = list(windows)
    matches: list[tuple[WindowRule, WindowInfo | None]] = []
    for entry in entries:
        executable = entry.executable.casefold()
        same_process = [
            window for window in unused if window.executable.casefold() == executable
        ]
        title_match = next(
            (window for window in same_process if _title_matches(entry, window.title)),
            None,
        )
        if entry.match_mode == "exact":
            selected = title_match or (same_process[0] if same_process else None)
        else:
            selected = title_match
        matches.append((entry, selected))
        if selected is not None:
            unused.remove(selected)
    return matches


def choose_monitor(
    device: str, monitors: list[MonitorInfo]
) -> MonitorInfo:
    """
    按设备名选择显示器，不存在时回退到主显示器。

    Args:
        device (str): 保存时的显示器设备名。
        monitors (list[MonitorInfo]): 当前显示器列表。

    Returns:
        MonitorInfo: 目标显示器。

    Raises:
        ValueError: 当前没有显示器时触发。
    """
    if not monitors:
        raise ValueError("没有检测到显示器")
    exact = next((monitor for monitor in monitors if monitor.device == device), None)
    if exact is not None:
        return exact
    return next((monitor for monitor in monitors if monitor.primary), monitors[0])


def scale_and_clamp_rect(rect: Rect, old_work: Rect, new_work: Rect) -> Rect:
    """
    按工作区比例缩放矩形并限制到当前可见范围。

    Args:
        rect (Rect): 保存的窗口矩形。
        old_work (Rect): 保存时显示器工作区。
        new_work (Rect): 当前目标显示器工作区。

    Returns:
        Rect: 缩放且可见的目标矩形。
    """
    if old_work.width <= 0 or old_work.height <= 0:
        old_work = new_work
    relative_x = (rect.left - old_work.left) / old_work.width
    relative_y = (rect.top - old_work.top) / old_work.height
    width_ratio = rect.width / old_work.width
    height_ratio = rect.height / old_work.height
    width = min(new_work.width, max(100, round(new_work.width * width_ratio)))
    height = min(new_work.height, max(80, round(new_work.height * height_ratio)))
    left = round(new_work.left + new_work.width * relative_x)
    top = round(new_work.top + new_work.height * relative_y)
    left = min(max(left, new_work.left), new_work.right - width)
    top = min(max(top, new_work.top), new_work.bottom - height)
    return Rect(left, top, left + width, top + height)


def create_restore_plan(
    name: str,
    windows: list[WindowInfo],
    path: Path | None = None,
    monitors: list[MonitorInfo] | None = None,
) -> RestorePlan:
    """
    为命名布局生成不执行窗口副作用的恢复计划。

    Args:
        name (str): 布局名称。
        windows (list[WindowInfo]): 当前可管理窗口快照。
        path (Path | None): 测试或自定义配置路径。
        monitors (list[MonitorInfo] | None): 测试时注入的显示器快照。

    Returns:
        RestorePlan: 包含就绪、跳过和冲突项的不可变计划。

    Raises:
        ValueError: 布局不存在或当前没有显示器时触发。
    """
    profile = load_config(path).profiles.get(name)
    if profile is None:
        raise ValueError(f"布局不存在：{name}")
    current_monitors = list(monitors) if monitors is not None else get_monitors()
    if not current_monitors:
        raise ValueError("没有检测到显示器")

    unused = list(windows)
    items: list[RestorePlanItem] = []
    for rule in profile.windows:
        candidates, reason = _matching_candidates(rule, unused)
        if not candidates:
            items.append(
                RestorePlanItem(
                    rule_id=rule.id,
                    executable=rule.executable,
                    title_pattern=rule.title_pattern,
                    window=None,
                    target_rect=None,
                    target_monitor_device=None,
                    maximized=rule.maximized,
                    status="skipped",
                    reason=reason,
                )
            )
            continue
        if len(candidates) > 1:
            items.append(
                RestorePlanItem(
                    rule_id=rule.id,
                    executable=rule.executable,
                    title_pattern=rule.title_pattern,
                    window=None,
                    target_rect=None,
                    target_monitor_device=None,
                    maximized=rule.maximized,
                    status="conflict",
                    reason=f"{reason}，存在 {len(candidates)} 个候选窗口",
                )
            )
            continue

        selected = candidates[0]
        unused.remove(selected)
        target_monitor = choose_monitor(rule.monitor.device, current_monitors)
        target_rect = scale_and_clamp_rect(
            rule.rect, rule.monitor.work_area, target_monitor.work_area
        )
        if target_monitor.device != rule.monitor.device:
            reason = f"{reason}；保存的显示器缺失，回退到 {target_monitor.device}"
        items.append(
            RestorePlanItem(
                rule_id=rule.id,
                executable=rule.executable,
                title_pattern=rule.title_pattern,
                window=selected,
                target_rect=target_rect,
                target_monitor_device=target_monitor.device,
                maximized=rule.maximized,
                status="ready",
                reason=reason,
            )
        )

    return RestorePlan(
        operation_id=str(uuid.uuid4()),
        profile_id=profile.id,
        profile_name=profile.name,
        preview_required=profile.restore_policy.preview,
        monitor_signature=monitor_signature(current_monitors),
        items=tuple(items),
    )


def execute_restore_plan(
    plan: RestorePlan,
    monitors: list[MonitorInfo] | None = None,
) -> RestoreSummary:
    """
    在确认显示器拓扑未变化后执行恢复计划。

    Args:
        plan (RestorePlan): 预先生成的不可变恢复计划。
        monitors (list[MonitorInfo] | None): 测试时注入的执行期显示器列表。

    Returns:
        RestoreSummary: 成功、跳过、失败和冲突数量。

    Raises:
        ValueError: 预览后显示器拓扑发生变化时触发，且不会移动任何窗口。
    """
    current_monitors = list(monitors) if monitors is not None else get_monitors()
    if monitor_signature(current_monitors) != plan.monitor_signature:
        raise ValueError("显示器拓扑已变化，请重新预览布局")

    succeeded = 0
    failed = 0
    for item in plan.items:
        if (
            item.status != "ready"
            or item.window is None
            or item.target_rect is None
        ):
            continue
        try:
            move_window(item.window.hwnd, item.target_rect)
            if item.maximized:
                maximize_window(item.window.hwnd)
            succeeded += 1
        except (ValueError, OSError):
            failed += 1
    return RestoreSummary(
        succeeded=succeeded,
        skipped=plan.skipped_count,
        failed=failed,
        conflicts=plan.conflict_count,
    )


def restore_profile(
    name: str,
    windows: list[WindowInfo],
    path: Path | None = None,
    monitors: list[MonitorInfo] | None = None,
) -> RestoreSummary:
    """
    恢复一套命名布局并汇总执行结果。

    Args:
        name (str): 布局名称。
        windows (list[WindowInfo]): 当前可管理窗口。
        path (Path | None): 测试或自定义配置路径。
        monitors (list[MonitorInfo] | None): 测试时注入的显示器列表。

    Returns:
        RestoreSummary: 成功、跳过和失败数量。

    Raises:
        ValueError: 布局不存在或结构无效时触发。
    """
    current_monitors = monitors if monitors is not None else get_monitors()
    plan = create_restore_plan(name, windows, path, current_monitors)
    return execute_restore_plan(plan, current_monitors)
