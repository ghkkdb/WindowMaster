"""配置持久化、校验与迁移测试。"""

import json
from pathlib import Path
from unittest.mock import patch

from core.config import default_config, load_config, save_config
from core.config_schema import ProfileConfig
from core.models import MonitorInfo, Rect
from core.layout import monitor_signature


def test_save_and_load_config(tmp_path: Path) -> None:
    """v2 强类型配置应以 UTF-8 保存并可无损读取。"""
    path = tmp_path / "layouts.json"
    data = default_config()
    data.profiles["工作"] = ProfileConfig(id="profile-1", name="工作")
    save_config(data, path)
    assert load_config(path) == data
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 2
    assert raw["profiles"]["工作"]["name"] == "工作"


def test_default_config_enables_system_tray() -> None:
    """新配置应默认启用关闭时隐藏到系统托盘。"""
    assert default_config().preferences.tray_enabled is True


def test_profile_monitor_signature_round_trip(tmp_path: Path) -> None:
    """布局的完整显示器拓扑签名应通过 JSON 无损保存和读取。"""
    path = tmp_path / "layouts.json"
    work = Rect(0, 0, 1920, 1040)
    monitor = MonitorInfo(1, "DISPLAY1", Rect(0, 0, 1920, 1080), work, True)
    data = default_config()
    data.profiles["工作"] = ProfileConfig(
        id="profile-1",
        name="工作",
        monitor_signature=monitor_signature([monitor]),
    )
    save_config(data, path)
    loaded = load_config(path)
    assert loaded.profiles["工作"].monitor_signature == monitor_signature([monitor])


def test_v1_config_is_migrated_and_backed_up(tmp_path: Path) -> None:
    """合法 v1 配置应自动迁移到 v2，并保留原始备份。"""
    path = tmp_path / "layouts.json"
    legacy = {
        "version": 1,
        "profiles": {
            "工作": {
                "windows": [
                    {
                        "executable": "Code.exe",
                        "title": "project - Visual Studio Code",
                        "rect": [0, 0, 960, 1040],
                        "monitor": {
                            "device": "DISPLAY1",
                            "work_area": [0, 0, 1920, 1040],
                        },
                        "maximized": False,
                    }
                ]
            }
        },
    }
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    migrated = load_config(path)

    assert migrated.version == 2
    rule = migrated.profiles["工作"].windows[0]
    assert rule.executable == "Code.exe"
    assert rule.title_pattern == "project - Visual Studio Code"
    assert rule.match_mode == "exact"
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2
    backups = list(tmp_path.glob("layouts.v1-backup-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == legacy


def test_migration_write_failure_preserves_v1_file(tmp_path: Path) -> None:
    """迁移结果无法写入时应返回内存模型并保留原 v1 文件。"""
    path = tmp_path / "layouts.json"
    legacy = {"version": 1, "profiles": {}}
    original = json.dumps(legacy)
    path.write_text(original, encoding="utf-8")

    with patch("core.config._write_config", side_effect=OSError("只读")):
        migrated = load_config(path)

    assert migrated.version == 2
    assert path.read_text(encoding="utf-8") == original


def test_corrupt_config_is_backed_up(tmp_path: Path) -> None:
    """损坏配置应备份并回退到空配置。"""
    path = tmp_path / "layouts.json"
    path.write_text("{broken", encoding="utf-8")
    assert load_config(path) == default_config()
    assert not path.exists()
    assert len(list(tmp_path.glob("layouts.corrupt-*.json"))) == 1


def test_invalid_nested_v2_config_is_rejected(tmp_path: Path) -> None:
    """顶层版本正确但嵌套字段无效时也应按损坏配置处理。"""
    path = tmp_path / "layouts.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "profiles": {"工作": {"id": "x", "name": "工作", "windows": "bad"}},
                "preferences": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load_config(path) == default_config()
    assert len(list(tmp_path.glob("layouts.corrupt-*.json"))) == 1


def test_invalid_utf8_config_is_backed_up(tmp_path: Path) -> None:
    """无法按 UTF-8 解码的配置应备份并回退。"""
    path = tmp_path / "layouts.json"
    path.write_bytes(b"\xff\xfe\x00")
    assert load_config(path) == default_config()
    assert not path.exists()
    assert len(list(tmp_path.glob("layouts.corrupt-*.json"))) == 1
