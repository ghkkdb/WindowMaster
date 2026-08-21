"""布局匹配和坐标恢复测试。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.config import default_config, load_config, save_config
from core.config_schema import ProfileConfig, SavedMonitor, WindowRule
from core.layout import (
    choose_monitor,
    create_restore_plan,
    execute_restore_plan,
    find_matching_profile_names,
    match_layout_windows,
    monitor_signature,
    restore_profile,
    save_profile,
    scale_and_clamp_rect,
)
from core.models import MonitorInfo, Rect, WindowInfo


def make_monitor(device: str, work: Rect, primary: bool = False) -> MonitorInfo:
    """
    创建测试显示器。

    Args:
        device (str): 显示器设备名。
        work (Rect): 工作区。
        primary (bool): 是否为主显示器。

    Returns:
        MonitorInfo: 测试显示器对象。
    """
    return MonitorInfo(1, device, work, work, primary)


def make_window(hwnd: int, executable: str, title: str) -> WindowInfo:
    """
    创建测试窗口。

    Args:
        hwnd (int): 窗口句柄。
        executable (str): 进程名。
        title (str): 窗口标题。

    Returns:
        WindowInfo: 测试窗口对象。
    """
    monitor = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    return WindowInfo(hwnd, title, hwnd, executable, Rect(0, 0, 800, 600), monitor, False, False)


def make_rule(
    rule_id: str,
    executable: str,
    title: str,
    match_mode: str = "exact",
) -> WindowRule:
    """
    创建精确标题匹配的测试窗口规则。

    Args:
        rule_id (str): 规则标识。
        executable (str): 进程名。
        title (str): 精确窗口标题。
        match_mode (str): 标题匹配模式。

    Returns:
        WindowRule: 测试窗口规则。
    """
    return WindowRule(
        id=rule_id,
        executable=executable,
        title_pattern=title,
        match_mode=match_mode,
        rect=Rect(0, 0, 960, 1040),
        monitor=SavedMonitor("DISPLAY1", Rect(0, 0, 1920, 1040)),
        maximized=False,
    )


def save_test_profile(path: Path, rules: list[WindowRule]) -> None:
    """
    保存供恢复计划测试使用的布局。

    Args:
        path (Path): 测试配置路径。
        rules (list[WindowRule]): 布局窗口规则。
    """
    config = default_config()
    config.profiles["工作"] = ProfileConfig(
        id="profile-1",
        name="工作",
        windows=rules,
    )
    save_config(config, path)


def test_matching_is_one_to_one_and_prefers_exact_title() -> None:
    """同进程多窗口应优先匹配标题且不重复使用句柄。"""
    windows = [make_window(1, "code.exe", "B"), make_window(2, "code.exe", "A")]
    entries = [
        make_rule("1", "CODE.EXE", "A"),
        make_rule("2", "code.exe", "missing"),
        make_rule("3", "code.exe", "extra"),
    ]
    matches = match_layout_windows(entries, windows)
    assert [window.hwnd if window else None for _, window in matches] == [2, 1, None]


def test_monitor_topology_matches_new_and_legacy_profiles() -> None:
    """新布局应精确匹配拓扑，旧布局应按保存的设备名和工作区兼容匹配。"""
    monitor = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    config = default_config()
    config.profiles["新布局"] = ProfileConfig(
        id="new",
        name="新布局",
        windows=[make_rule("1", "code.exe", "A")],
        monitor_signature=monitor_signature([monitor]),
    )
    config.profiles["旧布局"] = ProfileConfig(
        id="legacy",
        name="旧布局",
        windows=[make_rule("2", "notepad.exe", "B")],
    )
    assert set(find_matching_profile_names(config, [monitor])) == {"旧布局", "新布局"}

    changed = make_monitor("DISPLAY1", Rect(0, 0, 2560, 1400), True)
    assert find_matching_profile_names(config, [changed]) == []


def test_save_profile_records_complete_monitor_topology(tmp_path: Path) -> None:
    """保存布局时应同时记录当前完整显示器拓扑。"""
    path = tmp_path / "layouts.json"
    primary = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    secondary = make_monitor("DISPLAY2", Rect(1920, 0, 3840, 1040))
    with patch("core.layout.get_monitors", return_value=[primary, secondary]):
        save_profile("工作", [make_window(1, "code.exe", "A")], path)
    profile = load_config(path).profiles["工作"]
    assert profile.monitor_signature == monitor_signature([primary, secondary])


def test_matching_supports_glob_and_regex_titles() -> None:
    """v2 的 glob 和 regex 标题规则应只选择符合规则的窗口。"""
    windows = [
        make_window(1, "code.exe", "notes.txt - Visual Studio Code"),
        make_window(2, "code.exe", "README.md - Visual Studio Code"),
    ]
    entries = [
        make_rule("1", "code.exe", "*.md - Visual Studio Code", "glob"),
        make_rule("2", "code.exe", r"^notes\.txt\s-", "regex"),
    ]
    matches = match_layout_windows(entries, windows)
    assert [window.hwnd if window else None for _, window in matches] == [2, 1]


def test_non_exact_rule_does_not_fall_back_to_wrong_title() -> None:
    """glob 或 regex 未匹配时不应退化为仅进程名匹配。"""
    windows = [make_window(1, "code.exe", "README.md")]
    matches = match_layout_windows(
        [make_rule("1", "code.exe", "*.txt", "glob")], windows
    )
    assert matches[0][1] is None


def test_missing_monitor_falls_back_to_primary() -> None:
    """保存的显示器缺失时应选择当前主显示器。"""
    secondary = make_monitor("DISPLAY2", Rect(-1280, 0, 0, 984))
    primary = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    assert choose_monitor("MISSING", [secondary, primary]) == primary


def test_scale_rect_supports_negative_coordinates() -> None:
    """缩放矩形应支持位于主屏左侧的负坐标显示器。"""
    result = scale_and_clamp_rect(
        Rect(960, 0, 1920, 1040),
        Rect(0, 0, 1920, 1040),
        Rect(-1280, 0, 0, 984),
    )
    assert result == Rect(-640, 0, 0, 984)


def test_restore_continues_when_a_window_is_missing(tmp_path: Path) -> None:
    """布局部分窗口缺失时应继续恢复其余窗口。"""
    path = tmp_path / "layouts.json"
    config = default_config()
    config.profiles["工作"] = ProfileConfig(
        id="profile-1",
        name="工作",
        windows=[
            make_rule("1", "code.exe", "A"),
            make_rule("2", "missing.exe", "B"),
        ],
    )
    save_config(config, path)
    monitor = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    with patch("core.layout.move_window") as move:
        summary = restore_profile(
            "工作", [make_window(1, "code.exe", "A")], path, [monitor]
        )
    assert summary.succeeded == 1
    assert summary.skipped == 1
    assert summary.failed == 0
    move.assert_called_once()


def test_create_restore_plan_has_no_window_side_effects(tmp_path: Path) -> None:
    """生成恢复计划时不应移动或最大化任何窗口。"""
    path = tmp_path / "layouts.json"
    save_test_profile(path, [make_rule("1", "code.exe", "A")])
    monitor = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    with (
        patch("core.layout.move_window") as move,
        patch("core.layout.maximize_window") as maximize,
    ):
        plan = create_restore_plan(
            "工作", [make_window(1, "code.exe", "A")], path, [monitor]
        )
    assert plan.ready_count == 1
    assert plan.skipped_count == 0
    assert plan.conflict_count == 0
    assert plan.items[0].target_rect == Rect(0, 0, 960, 1040)
    move.assert_not_called()
    maximize.assert_not_called()


def test_restore_plan_reports_ambiguous_process_fallback(tmp_path: Path) -> None:
    """精确标题缺失且存在多个同进程窗口时应报告冲突。"""
    path = tmp_path / "layouts.json"
    save_test_profile(path, [make_rule("1", "code.exe", "missing")])
    monitor = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    windows = [
        make_window(1, "code.exe", "A"),
        make_window(2, "code.exe", "B"),
    ]
    plan = create_restore_plan("工作", windows, path, [monitor])
    assert plan.ready_count == 0
    assert plan.conflict_count == 1
    assert "2 个候选" in plan.items[0].reason


def test_restore_plan_uses_primary_when_saved_monitor_is_missing(tmp_path: Path) -> None:
    """保存显示器缺失时计划应明确回退到主屏。"""
    path = tmp_path / "layouts.json"
    rule = make_rule("1", "code.exe", "A")
    rule.monitor = SavedMonitor("MISSING", Rect(0, 0, 1920, 1040))
    save_test_profile(path, [rule])
    primary = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    plan = create_restore_plan(
        "工作", [make_window(1, "code.exe", "A")], path, [primary]
    )
    assert plan.items[0].target_monitor_device == "DISPLAY1"
    assert "回退到 DISPLAY1" in plan.items[0].reason


def test_execute_rejects_changed_monitor_topology(tmp_path: Path) -> None:
    """预览后显示器工作区变化时应在任何窗口副作用前拒绝执行。"""
    path = tmp_path / "layouts.json"
    save_test_profile(path, [make_rule("1", "code.exe", "A")])
    original = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    changed = make_monitor("DISPLAY1", Rect(0, 0, 2560, 1400), True)
    plan = create_restore_plan(
        "工作", [make_window(1, "code.exe", "A")], path, [original]
    )
    with (
        patch("core.layout.move_window") as move,
        pytest.raises(ValueError, match="拓扑已变化"),
    ):
        execute_restore_plan(plan, [changed])
    move.assert_not_called()
    assert monitor_signature([original]) != monitor_signature([changed])


def test_execute_plan_continues_after_single_window_failure(tmp_path: Path) -> None:
    """一个窗口执行失败时应继续处理计划中的其他就绪项。"""
    path = tmp_path / "layouts.json"
    save_test_profile(
        path,
        [
            make_rule("1", "code.exe", "A"),
            make_rule("2", "notepad.exe", "B"),
        ],
    )
    monitor = make_monitor("DISPLAY1", Rect(0, 0, 1920, 1040), True)
    windows = [
        make_window(1, "code.exe", "A"),
        make_window(2, "notepad.exe", "B"),
    ]
    plan = create_restore_plan("工作", windows, path, [monitor])
    with patch(
        "core.layout.move_window", side_effect=[OSError("拒绝"), None]
    ) as move:
        summary = execute_restore_plan(plan, [monitor])
    assert summary.succeeded == 1
    assert summary.failed == 1
    assert summary.skipped == 0
    assert summary.conflicts == 0
    assert move.call_count == 2
