from __future__ import annotations

import os
from pathlib import Path


APP_DATA_ENV_VAR = "HNH_DATA_DIR"
LEGACY_DATA_DIRNAME = "Hertz-and-Hearts"
DEFAULT_DATA_DIRNAME = "hertz-and-hearts"


def legacy_data_root() -> Path:
    return Path.home() / LEGACY_DATA_DIRNAME


def _xdg_data_home() -> Path:
    raw = os.environ.get("XDG_DATA_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".local" / "share"


def _windows_local_app_data_home() -> Path:
    raw = os.environ.get("LOCALAPPDATA", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "AppData" / "Local"


def _windows_default_data_root() -> Path:
    return _windows_local_app_data_home() / LEGACY_DATA_DIRNAME


def recommended_data_root() -> Path:
    """Preferred platform-native data root for new installs."""
    if os.name == "nt":
        return _windows_default_data_root()
    return _xdg_data_home() / DEFAULT_DATA_DIRNAME


def default_data_root() -> Path:
    legacy = legacy_data_root()
    if os.name == "nt":
        recommended = recommended_data_root()
        if recommended.exists():
            return recommended
        if legacy.exists():
            # Backward-compatible: existing users stay on the legacy path.
            return legacy
        return recommended
    if legacy.exists():
        # Backward-compatible: existing users stay on the legacy path.
        return legacy
    return recommended_data_root()


def default_data_root_tooltip() -> str:
    if os.name == "nt":
        return (
            "Default path is %LOCALAPPDATA%\\Hertz-and-Hearts. "
            "If a legacy ~/Hertz-and-Hearts folder already exists, it is reused."
        )
    return (
        "Default path is legacy ~/Hertz-and-Hearts when present; "
        "otherwise ~/.local/share/hertz-and-hearts."
    )


def app_data_root() -> Path:
    raw_override = os.environ.get(APP_DATA_ENV_VAR, "").strip()
    if raw_override:
        return Path(raw_override).expanduser()
    return default_data_root()
