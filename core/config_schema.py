"""WindowMaster 配置 v2 的强类型模型与迁移规则。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.models import MonitorSignature, Rect


SCHEMA_VERSION = 2
MATCH_MODES = {"exact", "glob", "regex", "process_only"}


def _require_dict(value: Any, field_name: str) -> dict[str, Any]:
    """
    校验并返回字典值。

    Args:
        value (Any): 待校验值。
        field_name (str): 用于错误信息的字段名。

    Returns:
        dict[str, Any]: 校验后的字典。

    Raises:
        ValueError: 值不是字典时触发。
    """
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} 必须是对象")
    return value


def _require_list(value: Any, field_name: str) -> list[Any]:
    """
    校验并返回列表值。

    Args:
        value (Any): 待校验值。
        field_name (str): 用于错误信息的字段名。

    Returns:
        list[Any]: 校验后的列表。

    Raises:
        ValueError: 值不是列表时触发。
    """
    if not isinstance(value, list):
        raise ValueError(f"{field_name} 必须是数组")
    return value


def _require_string(value: Any, field_name: str, allow_empty: bool = False) -> str:
    """
    校验并返回字符串值。

    Args:
        value (Any): 待校验值。
        field_name (str): 用于错误信息的字段名。
        allow_empty (bool): 是否允许空字符串。

    Returns:
        str: 校验后的字符串。

    Raises:
        ValueError: 值不是字符串或不允许为空时触发。
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 必须是字符串")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized


def _require_bool(value: Any, field_name: str) -> bool:
    """
    校验并返回布尔值。

    Args:
        value (Any): 待校验值。
        field_name (str): 用于错误信息的字段名。

    Returns:
        bool: 校验后的布尔值。

    Raises:
        ValueError: 值不是布尔值时触发。
    """
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} 必须是布尔值")
    return value


def _require_int(value: Any, field_name: str, minimum: int | None = None) -> int:
    """
    校验并返回整数值。

    Args:
        value (Any): 待校验值。
        field_name (str): 用于错误信息的字段名。
        minimum (int | None): 可选的最小值。

    Returns:
        int: 校验后的整数。

    Raises:
        ValueError: 值不是整数或小于最小值时触发。
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数")
    if minimum is not None and value < minimum:
        raise ValueError(f"{field_name} 不能小于 {minimum}")
    return value


def _parse_rect(value: Any, field_name: str) -> Rect:
    """
    将配置值解析为有效矩形。

    Args:
        value (Any): 四坐标数组。
        field_name (str): 用于错误信息的字段名。

    Returns:
        Rect: 解析后的矩形。

    Raises:
        ValueError: 坐标结构或尺寸无效时触发。
    """
    values = _require_list(value, field_name)
    if len(values) != 4:
        raise ValueError(f"{field_name} 必须包含四个坐标")
    coordinates = [
        _require_int(coordinate, f"{field_name}[{index}]")
        for index, coordinate in enumerate(values)
    ]
    rect = Rect.from_list(coordinates)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError(f"{field_name} 必须具有正宽度和正高度")
    return rect


def stable_config_id(kind: str, *parts: str) -> str:
    """
    为迁移数据生成稳定 UUID。

    Args:
        kind (str): 标识类型。
        *parts (str): 构成稳定标识的字段。

    Returns:
        str: UUID 字符串。
    """
    source = ":".join((kind, *parts))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"windowmaster:{source}"))


@dataclass(slots=True)
class SavedMonitor:
    """保存布局时使用的显示器工作区。"""

    device: str
    work_area: Rect

    @classmethod
    def from_dict(cls, data: Any) -> "SavedMonitor":
        """
        从字典创建显示器快照。

        Args:
            data (Any): 配置中的显示器对象。

        Returns:
            SavedMonitor: 校验后的显示器快照。
        """
        values = _require_dict(data, "monitor")
        return cls(
            device=_require_string(values.get("device"), "monitor.device"),
            work_area=_parse_rect(values.get("work_area"), "monitor.work_area"),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        将显示器快照转换为可序列化字典。

        Returns:
            dict[str, Any]: JSON 兼容字典。
        """
        return {"device": self.device, "work_area": self.work_area.to_list()}


@dataclass(slots=True)
class WindowRule:
    """描述一个窗口匹配规则及其目标布局状态。"""

    id: str
    executable: str
    title_pattern: str
    match_mode: str
    rect: Rect
    monitor: SavedMonitor
    maximized: bool

    @classmethod
    def from_dict(cls, data: Any) -> "WindowRule":
        """
        从字典创建窗口规则。

        Args:
            data (Any): 配置中的窗口规则对象。

        Returns:
            WindowRule: 校验后的窗口规则。

        Raises:
            ValueError: 匹配模式或正则表达式无效时触发。
        """
        values = _require_dict(data, "window_rule")
        match_mode = _require_string(values.get("match_mode"), "window_rule.match_mode")
        if match_mode not in MATCH_MODES:
            raise ValueError(f"不支持的窗口匹配模式：{match_mode}")
        title_pattern = _require_string(
            values.get("title_pattern", ""),
            "window_rule.title_pattern",
            allow_empty=match_mode == "process_only",
        )
        if match_mode == "regex":
            try:
                re.compile(title_pattern)
            except re.error as error:
                raise ValueError(f"窗口标题正则表达式无效：{error}") from error
        return cls(
            id=_require_string(values.get("id"), "window_rule.id"),
            executable=_require_string(values.get("executable"), "window_rule.executable"),
            title_pattern=title_pattern,
            match_mode=match_mode,
            rect=_parse_rect(values.get("rect"), "window_rule.rect"),
            monitor=SavedMonitor.from_dict(values.get("monitor")),
            maximized=_require_bool(values.get("maximized"), "window_rule.maximized"),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        将窗口规则转换为可序列化字典。

        Returns:
            dict[str, Any]: JSON 兼容字典。
        """
        return {
            "id": self.id,
            "executable": self.executable,
            "title_pattern": self.title_pattern,
            "match_mode": self.match_mode,
            "rect": self.rect.to_list(),
            "monitor": self.monitor.to_dict(),
            "maximized": self.maximized,
        }


@dataclass(slots=True)
class RestorePolicy:
    """控制布局恢复的安全默认行为。"""

    preview: bool = True
    auto_restore: bool = False
    continue_on_error: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> "RestorePolicy":
        """
        从字典创建恢复策略。

        Args:
            data (Any): 配置中的恢复策略对象。

        Returns:
            RestorePolicy: 校验后的恢复策略。
        """
        values = _require_dict(data, "restore_policy")
        return cls(
            preview=_require_bool(values.get("preview"), "restore_policy.preview"),
            auto_restore=_require_bool(
                values.get("auto_restore"), "restore_policy.auto_restore"
            ),
            continue_on_error=_require_bool(
                values.get("continue_on_error"),
                "restore_policy.continue_on_error",
            ),
        )

    def to_dict(self) -> dict[str, bool]:
        """
        将恢复策略转换为可序列化字典。

        Returns:
            dict[str, bool]: JSON 兼容字典。
        """
        return {
            "preview": self.preview,
            "auto_restore": self.auto_restore,
            "continue_on_error": self.continue_on_error,
        }


@dataclass(slots=True)
class ProfileConfig:
    """表示一套命名工作布局。"""

    id: str
    name: str
    windows: list[WindowRule] = field(default_factory=list)
    restore_policy: RestorePolicy = field(default_factory=RestorePolicy)
    monitor_signature: MonitorSignature = ()

    @classmethod
    def from_dict(cls, profile_name: str, data: Any) -> "ProfileConfig":
        """
        从字典创建布局配置。

        Args:
            profile_name (str): profiles 映射中的布局名称。
            data (Any): 配置中的布局对象。

        Returns:
            ProfileConfig: 校验后的布局配置。

        Raises:
            ValueError: 对象内名称与映射键不一致时触发。
        """
        normalized_name = _require_string(profile_name, "profile_name")
        values = _require_dict(data, f"profiles.{normalized_name}")
        embedded_name = _require_string(values.get("name"), "profile.name")
        if embedded_name != normalized_name:
            raise ValueError(f"布局名称与映射键不一致：{normalized_name}")
        windows = [
            WindowRule.from_dict(item)
            for item in _require_list(values.get("windows"), "profile.windows")
        ]
        raw_signature = _require_list(
            values.get("monitor_signature", []), "profile.monitor_signature"
        )
        signature_items: list[
            tuple[str, int, int, int, int, int, int, int, int, bool]
        ] = []
        for index, raw_item in enumerate(raw_signature):
            item = _require_list(raw_item, f"profile.monitor_signature[{index}]")
            if len(item) != 10:
                raise ValueError("显示器签名条目必须包含 10 个字段")
            signature_items.append(
                (
                    _require_string(item[0], f"monitor_signature[{index}].device"),
                    *(
                        _require_int(item[position], f"monitor_signature[{index}][{position}]")
                        for position in range(1, 9)
                    ),
                    _require_bool(item[9], f"monitor_signature[{index}].primary"),
                )
            )
        return cls(
            id=_require_string(values.get("id"), "profile.id"),
            name=embedded_name,
            windows=windows,
            restore_policy=RestorePolicy.from_dict(values.get("restore_policy")),
            monitor_signature=tuple(signature_items),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        将布局配置转换为可序列化字典。

        Returns:
            dict[str, Any]: JSON 兼容字典。
        """
        return {
            "id": self.id,
            "name": self.name,
            "windows": [window.to_dict() for window in self.windows],
            "restore_policy": self.restore_policy.to_dict(),
            "monitor_signature": [list(item) for item in self.monitor_signature],
        }


@dataclass(slots=True)
class HotkeyBinding:
    """表示一个可持久化的快捷键绑定。"""

    action: str
    shortcut: str
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: Any) -> "HotkeyBinding":
        """
        从字典创建快捷键绑定。

        Args:
            data (Any): 配置中的快捷键对象。

        Returns:
            HotkeyBinding: 校验后的快捷键绑定。
        """
        values = _require_dict(data, "hotkey")
        return cls(
            action=_require_string(values.get("action"), "hotkey.action"),
            shortcut=_require_string(values.get("shortcut"), "hotkey.shortcut"),
            enabled=_require_bool(values.get("enabled"), "hotkey.enabled"),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        将快捷键绑定转换为可序列化字典。

        Returns:
            dict[str, Any]: JSON 兼容字典。
        """
        return {
            "action": self.action,
            "shortcut": self.shortcut,
            "enabled": self.enabled,
        }


def default_hotkeys() -> list[HotkeyBinding]:
    """
    创建与当前版本行为一致的默认快捷键。

    Returns:
        list[HotkeyBinding]: 默认快捷键列表。
    """
    return [
        HotkeyBinding("toggle_topmost", "Ctrl+Alt+T"),
        HotkeyBinding("split_left", "Ctrl+Alt+1"),
        HotkeyBinding("split_right", "Ctrl+Alt+2"),
        HotkeyBinding("minimize_all", "Ctrl+Alt+M"),
    ]


@dataclass(slots=True)
class AppPreferences:
    """表示应用级偏好设置。"""

    hotkeys: list[HotkeyBinding] = field(default_factory=default_hotkeys)
    tray_enabled: bool = True
    auto_start: bool = False
    display_change_debounce_ms: int = 1200

    @classmethod
    def from_dict(cls, data: Any) -> "AppPreferences":
        """
        从字典创建应用偏好设置。

        Args:
            data (Any): 配置中的 preferences 对象。

        Returns:
            AppPreferences: 校验后的偏好设置。
        """
        values = _require_dict(data, "preferences")
        return cls(
            hotkeys=[
                HotkeyBinding.from_dict(item)
                for item in _require_list(values.get("hotkeys"), "preferences.hotkeys")
            ],
            tray_enabled=_require_bool(
                values.get("tray_enabled"), "preferences.tray_enabled"
            ),
            auto_start=_require_bool(values.get("auto_start"), "preferences.auto_start"),
            display_change_debounce_ms=_require_int(
                values.get("display_change_debounce_ms"),
                "preferences.display_change_debounce_ms",
                minimum=0,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        将应用偏好转换为可序列化字典。

        Returns:
            dict[str, Any]: JSON 兼容字典。
        """
        return {
            "hotkeys": [hotkey.to_dict() for hotkey in self.hotkeys],
            "tray_enabled": self.tray_enabled,
            "auto_start": self.auto_start,
            "display_change_debounce_ms": self.display_change_debounce_ms,
        }


@dataclass(slots=True)
class AppConfig:
    """WindowMaster 配置文件的根模型。"""

    version: int = SCHEMA_VERSION
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)
    preferences: AppPreferences = field(default_factory=AppPreferences)

    @classmethod
    def from_dict(cls, data: Any) -> "AppConfig":
        """
        从 v2 字典创建完整配置。

        Args:
            data (Any): 配置根对象。

        Returns:
            AppConfig: 校验后的完整配置。

        Raises:
            ValueError: 版本或任一嵌套字段无效时触发。
        """
        values = _require_dict(data, "config")
        version = _require_int(values.get("version"), "version")
        if version != SCHEMA_VERSION:
            raise ValueError(f"不支持的配置版本：{version}")
        raw_profiles = _require_dict(values.get("profiles"), "profiles")
        profiles = {
            _require_string(name, "profile_name"): ProfileConfig.from_dict(name, profile)
            for name, profile in raw_profiles.items()
        }
        return cls(
            version=version,
            profiles=profiles,
            preferences=AppPreferences.from_dict(values.get("preferences")),
        )

    def to_dict(self) -> dict[str, Any]:
        """
        将完整配置转换为可序列化字典。

        Returns:
            dict[str, Any]: JSON 兼容字典。
        """
        return {
            "version": self.version,
            "profiles": {
                name: profile.to_dict() for name, profile in self.profiles.items()
            },
            "preferences": self.preferences.to_dict(),
        }


def migrate_v1_config(data: Any) -> AppConfig:
    """
    将旧版 v1 字典迁移为强类型 v2 配置。

    Args:
        data (Any): v1 配置根对象。

    Returns:
        AppConfig: 迁移并校验后的 v2 配置。

    Raises:
        ValueError: v1 结构无效时触发。
    """
    values = _require_dict(data, "config")
    if _require_int(values.get("version"), "version") != 1:
        raise ValueError("迁移输入不是 v1 配置")
    raw_profiles = _require_dict(values.get("profiles"), "profiles")
    profiles: dict[str, ProfileConfig] = {}
    for profile_name, raw_profile in raw_profiles.items():
        normalized_name = _require_string(profile_name, "profile_name")
        profile_values = _require_dict(raw_profile, f"profiles.{normalized_name}")
        raw_windows = _require_list(
            profile_values.get("windows"), f"profiles.{normalized_name}.windows"
        )
        windows: list[WindowRule] = []
        for index, raw_window in enumerate(raw_windows):
            window_values = _require_dict(raw_window, f"window[{index}]")
            executable = _require_string(
                window_values.get("executable"), f"window[{index}].executable"
            )
            title = _require_string(
                window_values.get("title"),
                f"window[{index}].title",
                allow_empty=True,
            )
            windows.append(
                WindowRule(
                    id=stable_config_id(
                        "window", normalized_name, str(index), executable, title
                    ),
                    executable=executable,
                    title_pattern=title,
                    match_mode="exact" if title else "process_only",
                    rect=_parse_rect(window_values.get("rect"), f"window[{index}].rect"),
                    monitor=SavedMonitor.from_dict(window_values.get("monitor")),
                    maximized=_require_bool(
                        window_values.get("maximized"), f"window[{index}].maximized"
                    ),
                )
            )
        profiles[normalized_name] = ProfileConfig(
            id=stable_config_id("profile", normalized_name),
            name=normalized_name,
            windows=windows,
        )
    migrated = AppConfig(profiles=profiles)
    return AppConfig.from_dict(migrated.to_dict())
