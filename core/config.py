"""用户配置与命名布局的持久化。"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from core.config_schema import AppConfig, SCHEMA_VERSION, migrate_v1_config


CONFIG_VERSION = SCHEMA_VERSION


def default_config() -> AppConfig:
    """
    创建空的默认配置。

    Returns:
        AppConfig: 当前版本的空配置。
    """
    return AppConfig()


def get_config_path() -> Path:
    """
    获取用户配置文件路径。

    Returns:
        Path: `%APPDATA%/WindowMaster/layouts.json` 路径。
    """
    appdata = os.getenv("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "WindowMaster" / "layouts.json"


def _timestamp() -> str:
    """
    生成用于备份文件名的时间戳。

    Returns:
        str: 精确到微秒的本地时间戳。
    """
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _write_config(data: AppConfig, target: Path) -> None:
    """
    以原子替换方式写入配置。

    Args:
        data (AppConfig): 已校验的完整配置。
        target (Path): 目标配置路径。
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(target)


def _backup_corrupt_config(target: Path) -> None:
    """
    将无效配置移动到带时间戳的备份文件。

    Args:
        target (Path): 无效配置路径。
    """
    backup = target.with_name(f"layouts.corrupt-{_timestamp()}.json")
    try:
        target.replace(backup)
    except OSError:
        pass


def _persist_migration(config: AppConfig, target: Path) -> None:
    """
    在保留 v1 原文件副本后持久化迁移结果。

    备份或写入失败时保持原文件不变，调用方仍可在本次会话使用内存中的迁移结果。

    Args:
        config (AppConfig): 已迁移并校验的 v2 配置。
        target (Path): 原 v1 配置路径。
    """
    backup = target.with_name(f"layouts.v1-backup-{_timestamp()}.json")
    try:
        shutil.copy2(target, backup)
        _write_config(config, target)
    except OSError:
        return


def load_config(path: Path | None = None) -> AppConfig:
    """
    读取并校验配置，必要时自动迁移 v1 数据。

    Args:
        path (Path | None): 自定义配置路径，省略时使用用户配置目录。

    Returns:
        AppConfig: 强类型配置。损坏时备份原文件并返回空配置。
    """
    target = path or get_config_path()
    if not target.exists():
        return default_config()
    try:
        raw_text = target.read_text(encoding="utf-8")
    except UnicodeError:
        _backup_corrupt_config(target)
        return default_config()
    except OSError:
        return default_config()
    try:
        raw_data: Any = json.loads(raw_text)
        if not isinstance(raw_data, dict):
            raise ValueError("配置根节点必须是对象")
        if raw_data.get("version") == 1:
            migrated = migrate_v1_config(raw_data)
            _persist_migration(migrated, target)
            return migrated
        return AppConfig.from_dict(raw_data)
    except (json.JSONDecodeError, ValueError):
        _backup_corrupt_config(target)
        return default_config()


def save_config(data: AppConfig, path: Path | None = None) -> None:
    """
    校验并以原子替换方式保存配置。

    Args:
        data (AppConfig): 要保存的完整强类型配置。
        path (Path | None): 自定义配置路径，省略时使用用户配置目录。

    Raises:
        ValueError: 配置对象无法通过 v2 模式校验时触发。
    """
    validated = AppConfig.from_dict(data.to_dict())
    _write_config(validated, path or get_config_path())
