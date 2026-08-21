"""Windows 全局快捷键解析、校验、注册与注销。"""

import ctypes

from core.config_schema import HotkeyBinding, default_hotkeys


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

HOTKEY_ACTION_IDS: dict[str, int] = {
    "toggle_topmost": 1,
    "split_left": 2,
    "split_right": 3,
    "minimize_all": 4,
}
HOTKEY_LABELS: dict[str, str] = {
    "toggle_topmost": "切换前台窗口置顶",
    "split_left": "前台窗口移动到左半屏",
    "split_right": "前台窗口移动到右半屏",
    "minimize_all": "最小化全部程序",
}
SPECIAL_KEYS: dict[str, int] = {
    "SPACE": 0x20,
    "TAB": 0x09,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PGUP": 0x21,
    "PGDOWN": 0x22,
    "HOME": 0x24,
    "END": 0x23,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
}


def parse_shortcut(shortcut: str) -> tuple[int, int]:
    """
    将便携格式快捷键转换为 RegisterHotKey 参数。

    Args:
        shortcut (str): 例如 `Ctrl+Alt+T` 的快捷键文本。

    Returns:
        tuple[int, int]: 修饰键标志和虚拟键码。

    Raises:
        ValueError: 快捷键缺少修饰键、主键或包含不支持的按键时触发。
    """
    parts = [part.strip() for part in shortcut.split("+") if part.strip()]
    if len(parts) < 2:
        raise ValueError("快捷键必须包含至少一个修饰键和一个主键")
    modifiers = MOD_NOREPEAT
    modifier_map = {
        "CTRL": MOD_CONTROL,
        "CONTROL": MOD_CONTROL,
        "ALT": MOD_ALT,
        "SHIFT": MOD_SHIFT,
        "WIN": MOD_WIN,
        "META": MOD_WIN,
    }
    for part in parts[:-1]:
        flag = modifier_map.get(part.upper())
        if flag is None:
            raise ValueError(f"不支持的快捷键修饰键：{part}")
        modifiers |= flag
    key_name = parts[-1].upper()
    if len(key_name) == 1 and key_name.isalnum():
        virtual_key = ord(key_name)
    elif key_name.startswith("F") and key_name[1:].isdigit():
        function_number = int(key_name[1:])
        if not 1 <= function_number <= 24:
            raise ValueError("功能键只支持 F1 到 F24")
        virtual_key = 0x70 + function_number - 1
    elif key_name in SPECIAL_KEYS:
        virtual_key = SPECIAL_KEYS[key_name]
    else:
        raise ValueError(f"不支持的快捷键主键：{parts[-1]}")
    return modifiers, virtual_key


def normalize_hotkey_bindings(
    bindings: list[HotkeyBinding],
) -> list[HotkeyBinding]:
    """
    用已保存值覆盖默认动作，并补齐新版本新增的快捷键动作。

    Args:
        bindings (list[HotkeyBinding]): 配置中已有的快捷键绑定。

    Returns:
        list[HotkeyBinding]: 按固定动作顺序排列的完整绑定。
    """
    saved = {binding.action: binding for binding in bindings}
    return [saved.get(binding.action, binding) for binding in default_hotkeys()]


def validate_hotkey_bindings(bindings: list[HotkeyBinding]) -> None:
    """
    校验快捷键动作完整性、组合键格式及重复绑定。

    Args:
        bindings (list[HotkeyBinding]): 待校验的完整快捷键绑定。

    Raises:
        ValueError: 动作缺失、动作重复、组合键无效或快捷键重复时触发。
    """
    actions = [binding.action for binding in bindings]
    expected = set(HOTKEY_ACTION_IDS)
    if set(actions) != expected or len(actions) != len(expected):
        raise ValueError("快捷键动作缺失、重复或包含未知动作")
    used: dict[tuple[int, int], str] = {}
    for binding in bindings:
        if not binding.enabled:
            continue
        parsed = parse_shortcut(binding.shortcut)
        previous = used.get(parsed)
        if previous is not None:
            raise ValueError(
                f"快捷键重复：{HOTKEY_LABELS[previous]} 与 "
                f"{HOTKEY_LABELS[binding.action]}"
            )
        used[parsed] = binding.action


def register_hotkeys(
    hwnd: int, bindings: list[HotkeyBinding] | None = None
) -> list[str]:
    """
    为指定窗口注册配置中的全局快捷键。

    Args:
        hwnd (int): 接收 WM_HOTKEY 消息的窗口句柄。
        bindings (list[HotkeyBinding] | None): 快捷键绑定；省略时使用默认值。

    Returns:
        list[str]: 注册失败的快捷键说明。

    Raises:
        ValueError: 快捷键配置无效时触发。
    """
    configured = normalize_hotkey_bindings(bindings or default_hotkeys())
    validate_hotkey_bindings(configured)
    failures: list[str] = []
    for binding in configured:
        if not binding.enabled:
            continue
        modifiers, virtual_key = parse_shortcut(binding.shortcut)
        hotkey_id = HOTKEY_ACTION_IDS[binding.action]
        result = ctypes.windll.user32.RegisterHotKey(
            hwnd, hotkey_id, modifiers, virtual_key
        )
        if not result:
            failures.append(f"{HOTKEY_LABELS[binding.action]}（{binding.shortcut}）")
    return failures


def unregister_hotkeys(hwnd: int) -> None:
    """
    注销指定窗口的全部全局快捷键。

    Args:
        hwnd (int): 注册快捷键时使用的窗口句柄。
    """
    for hotkey_id in HOTKEY_ACTION_IDS.values():
        ctypes.windll.user32.UnregisterHotKey(hwnd, hotkey_id)


def action_for_hotkey_id(hotkey_id: int) -> str | None:
    """
    获取 Windows 快捷键 ID 对应的业务动作。

    Args:
        hotkey_id (int): RegisterHotKey 使用的快捷键 ID。

    Returns:
        str | None: 对应动作，未知 ID 返回 None。
    """
    return next(
        (action for action, action_id in HOTKEY_ACTION_IDS.items() if action_id == hotkey_id),
        None,
    )
