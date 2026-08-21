"""ApplicationService 业务编排测试。"""

import ast
from pathlib import Path
from unittest.mock import patch

from core.application_service import ApplicationService
from core.config_schema import AppConfig, default_hotkeys
from core.models import (
    MonitorInfo,
    HotkeySetting,
    Rect,
    RestorePlan,
    RestoreSummary,
    WindowInfo,
)


def make_window(hwnd: int = 1, title: str = "窗口") -> WindowInfo:
    """
    创建服务测试使用的窗口。

    Args:
        hwnd (int): 窗口句柄。
        title (str): 窗口标题。

    Returns:
        WindowInfo: 测试窗口。
    """
    work = Rect(0, 0, 1920, 1040)
    monitor = MonitorInfo(1, "DISPLAY1", work, work, True)
    return WindowInfo(hwnd, title, hwnd, "app.exe", Rect(0, 0, 800, 600), monitor, False, False)


def make_plan() -> RestorePlan:
    """
    创建服务测试使用的空恢复计划。

    Returns:
        RestorePlan: 测试恢复计划。
    """
    return RestorePlan(
        operation_id="operation-1",
        profile_id="profile-1",
        profile_name="工作",
        preview_required=True,
        monitor_signature=(),
        items=(),
    )


def test_refresh_updates_snapshot_and_failure_preserves_it() -> None:
    """刷新失败不应清空最近一次成功窗口快照。"""
    service = ApplicationService()
    window = make_window()
    with patch("core.application_service.enumerate_windows", return_value=[window]):
        success = service.refresh_windows()
    assert success.success
    assert success.payload == (window,)
    assert service.windows == (window,)

    with patch(
        "core.application_service.enumerate_windows", side_effect=OSError("失败")
    ):
        failure = service.refresh_windows()
    assert not failure.success
    assert "刷新窗口失败" in failure.message
    assert service.windows == (window,)


def test_window_operation_returns_uniform_result() -> None:
    """窗口操作应统一返回消息、负载和刷新要求。"""
    service = ApplicationService()
    with patch("core.application_service.toggle_topmost", return_value=True) as toggle:
        result = service.toggle_window_topmost(100)
    assert result.success
    assert result.payload is True
    assert result.refresh_required
    assert result.message == "已置顶窗口"
    toggle.assert_called_once_with(100)


def test_window_operation_converts_errors_to_result() -> None:
    """底层窗口异常应转换为失败结果而不是传播到 UI。"""
    service = ApplicationService()
    with patch(
        "core.application_service.split_window", side_effect=ValueError("方向无效")
    ):
        result = service.split_window(100, "bad")
    assert not result.success
    assert "方向无效" in result.message


def test_activate_window_reports_foreground_result() -> None:
    """激活窗口应区分成功切换前台和仅完成闪烁提示。"""
    service = ApplicationService()
    with patch(
        "core.application_service.activate_and_flash_window", return_value=False
    ) as activate:
        result = service.activate_window(100)
    assert result.success
    assert result.payload is False
    assert "已闪烁目标窗口" in result.message
    activate.assert_called_once_with(100)


def test_minimize_all_programs_returns_count() -> None:
    """最小化全部程序应返回统一结果和处理数量。"""
    service = ApplicationService()
    with patch("core.application_service.minimize_all_windows", return_value=3) as minimize:
        result = service.minimize_all_programs()
    assert result.success
    assert result.payload == 3
    assert "3 个" in result.message
    minimize.assert_called_once_with(None)


def test_hotkey_update_rolls_back_when_registration_conflicts() -> None:
    """新快捷键注册冲突时应恢复旧绑定且不保存配置。"""
    service = ApplicationService()
    config = AppConfig()
    settings = tuple(
        HotkeySetting(binding.action, binding.action, binding.shortcut, binding.enabled)
        for binding in default_hotkeys()
    )
    with (
        patch("core.application_service.load_config", return_value=config),
        patch("core.application_service.unregister_hotkeys") as unregister,
        patch(
            "core.application_service.register_hotkeys",
            side_effect=[["冲突"], []],
        ) as register,
        patch("core.application_service.save_config") as save,
    ):
        result = service.update_hotkey_settings(500, settings)
    assert not result.success
    assert "冲突" in result.message
    assert unregister.call_count == 2
    assert register.call_count == 2
    save.assert_not_called()


def test_hotkey_update_saves_after_successful_registration() -> None:
    """新快捷键全部注册成功后应持久化并立即返回生效设置。"""
    service = ApplicationService()
    config = AppConfig()
    bindings = default_hotkeys()
    settings = tuple(
        HotkeySetting(
            binding.action,
            binding.action,
            "Ctrl+Alt+Q" if binding.action == "toggle_topmost" else binding.shortcut,
            binding.enabled,
        )
        for binding in bindings
    )
    with (
        patch("core.application_service.load_config", return_value=config),
        patch("core.application_service.unregister_hotkeys"),
        patch("core.application_service.register_hotkeys", return_value=[]),
        patch("core.application_service.save_config") as save,
    ):
        result = service.update_hotkey_settings(500, settings)
    assert result.success
    assert config.preferences.hotkeys[0].shortcut == "Ctrl+Alt+Q"
    save.assert_called_once_with(config)


def test_legacy_hotkey_config_is_completed_with_new_actions() -> None:
    """旧配置缺少新动作时，读取设置应自动补齐最小化全部快捷键。"""
    service = ApplicationService()
    config = AppConfig()
    config.preferences.hotkeys = default_hotkeys()[:3]
    with patch("core.application_service.load_config", return_value=config):
        result = service.get_hotkey_settings()
    assert result.success
    assert result.payload is not None
    assert [item.action for item in result.payload][-1] == "minimize_all"


def test_save_profile_uses_latest_service_snapshot() -> None:
    """保存布局应使用服务持有的最近窗口快照。"""
    service = ApplicationService()
    windows = [make_window(1), make_window(2)]
    with patch("core.application_service.enumerate_windows", return_value=windows):
        service.refresh_windows()
    with patch("core.application_service.save_profile") as save:
        result = service.save_current_profile("工作")
    assert result.success
    assert result.payload == 2
    save.assert_called_once_with("工作", windows)


def test_prepare_restore_refreshes_before_planning() -> None:
    """准备恢复应先刷新窗口，再将同一快照传给计划生成器。"""
    service = ApplicationService()
    windows = [make_window()]
    plan = make_plan()
    with (
        patch("core.application_service.enumerate_windows", return_value=windows),
        patch("core.application_service.create_restore_plan", return_value=plan) as create,
    ):
        result = service.prepare_restore("工作")
    assert result.success
    assert result.payload == plan
    create.assert_called_once_with("工作", windows)
    assert service.windows == ()


def test_tray_preference_is_read_and_persisted_through_service() -> None:
    """系统托盘偏好应由应用服务读取和保存，UI 不直接依赖配置模块。"""
    service = ApplicationService()
    config = AppConfig()
    config.preferences.tray_enabled = True
    with patch("core.application_service.load_config", return_value=config):
        read_result = service.get_tray_enabled()
    assert read_result.success
    assert read_result.payload is True

    config.preferences.tray_enabled = False
    with (
        patch("core.application_service.load_config", return_value=config),
        patch("core.application_service.save_config") as save,
    ):
        write_result = service.set_tray_enabled(True)
    assert write_result.success
    assert write_result.payload is True
    assert config.preferences.tray_enabled is True
    save.assert_called_once_with(config)


def test_display_change_state_contains_topology_matches_and_debounce() -> None:
    """显示器变化状态应统一返回拓扑、匹配布局和配置的防抖时间。"""
    service = ApplicationService()
    config = AppConfig()
    config.preferences.display_change_debounce_ms = 900
    monitor = make_window().monitor
    with (
        patch("core.application_service.load_config", return_value=config),
        patch("core.application_service.get_monitors", return_value=[monitor]),
        patch(
            "core.application_service.find_matching_profile_names",
            return_value=["工作"],
        ),
    ):
        result = service.get_display_change_state()
    assert result.success
    assert result.payload is not None
    assert result.payload.matching_profiles == ("工作",)
    assert result.payload.debounce_ms == 900
    assert result.payload.monitor_signature


def test_execute_restore_returns_summary_and_refresh_requirement() -> None:
    """执行恢复应返回统一统计消息并要求界面刷新。"""
    service = ApplicationService()
    plan = make_plan()
    summary = RestoreSummary(2, 1, 0, 1)
    with patch(
        "core.application_service.execute_restore_plan", return_value=summary
    ) as execute:
        result = service.execute_restore(plan)
    assert result.success
    assert result.payload == summary
    assert result.refresh_required
    assert "成功 2" in result.message
    assert "冲突 1" in result.message
    execute.assert_called_once_with(plan)


def test_hotkey_uses_selected_window_when_manager_is_foreground() -> None:
    """管理界面位于前台时，置顶快捷键应使用 UI 传入的选中窗口。"""
    service = ApplicationService()
    with (
        patch("core.application_service.get_foreground_window", return_value=500),
        patch("core.application_service.toggle_topmost", return_value=False) as toggle,
    ):
        result = service.handle_hotkey(1, manager_hwnd=500, selected_hwnd=200)
    assert result.success
    assert "取消置顶" in result.message
    toggle.assert_called_once_with(200)


def test_minimize_all_hotkey_does_not_require_foreground_window() -> None:
    """最小化全部快捷键应直接处理全部窗口，无需读取前台窗口。"""
    service = ApplicationService()
    with (
        patch("core.application_service.minimize_all_windows", return_value=4) as minimize,
        patch("core.application_service.get_foreground_window") as foreground,
    ):
        result = service.handle_hotkey(4, manager_hwnd=500, selected_hwnd=None)
    assert result.success
    assert "4 个" in result.message
    minimize.assert_called_once_with(500)
    foreground.assert_not_called()


def test_main_window_only_imports_application_service_for_business_actions() -> None:
    """主窗口不应重新直接依赖配置、布局或窗口管理模块。"""
    source = Path("ui/main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "core.application_service" in imported_modules
    assert "core.config" not in imported_modules
    assert "core.layout" not in imported_modules
    assert "core.window_manager" not in imported_modules
    assert 'self.navigation_tabs.addTab("快捷键设置")' in source
    assert 'self.navigation_tabs.addTab("设置")' in source
    assert "def open_settings" in source
    assert "def open_hotkey_settings" in source
    assert "self.tray_checkbox" not in source
    assert "cellDoubleClicked.connect(self.activate_row_window)" in source
