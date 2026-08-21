"""全局快捷键注册测试。"""

from unittest.mock import patch

import pytest

from core.config_schema import HotkeyBinding, default_hotkeys
from core.hotkeys import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    parse_shortcut,
    register_hotkeys,
    validate_hotkey_bindings,
)


def test_hotkeys_disable_key_repeat() -> None:
    """全局快捷键应禁用按住按键产生的重复消息。"""
    with patch(
        "core.hotkeys.ctypes.windll.user32.RegisterHotKey", return_value=1
    ) as register:
        assert register_hotkeys(100) == []
    modifiers = register.call_args_list[0].args[2]
    assert modifiers == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT


def test_parse_shortcut_supports_modifiers_and_function_keys() -> None:
    """快捷键解析应支持组合修饰键和 F1 至 F24。"""
    modifiers, virtual_key = parse_shortcut("Ctrl+Shift+F12")
    assert modifiers == MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
    assert virtual_key == 0x7B


def test_duplicate_enabled_shortcuts_are_rejected() -> None:
    """两个启用动作不能使用相同的全局快捷键。"""
    bindings = default_hotkeys()
    bindings[1].shortcut = bindings[0].shortcut
    with pytest.raises(ValueError, match="快捷键重复"):
        validate_hotkey_bindings(bindings)


def test_disabled_hotkey_is_not_registered() -> None:
    """关闭的快捷键动作不应调用 Windows 注册接口。"""
    bindings = default_hotkeys()
    bindings[-1] = HotkeyBinding("minimize_all", "Ctrl+Alt+M", False)
    with patch(
        "core.hotkeys.ctypes.windll.user32.RegisterHotKey", return_value=1
    ) as register:
        assert register_hotkeys(100, bindings) == []
    assert register.call_count == len(bindings) - 1
