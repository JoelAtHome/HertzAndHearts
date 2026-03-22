"""GitHub release lookup and version comparison for in-app update notices."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from packaging.version import InvalidVersion, Version

from hnh.data_paths import app_data_root

GITHUB_RELEASES_API = (
    "https://api.github.com/repos/JoelAtHome/HertzAndHearts/releases?per_page=30"
)
RELEASES_PAGE_URL = "https://github.com/JoelAtHome/HertzAndHearts/releases"

_AUTO_CHECK_INTERVAL_SEC = 24 * 60 * 60
_STATE_FILENAME = "update_notify_state.json"

_BETA_TAG_RE = re.compile(r"^(\d+\.\d+\.\d+)-beta(?:\.(\d+))?$", re.IGNORECASE)


def _installed_version_string() -> str:
    try:
        from importlib.metadata import version as pkg_version

        return pkg_version("Hertz-and-Hearts")
    except Exception:
        return "0.0.0-dev"


def _user_agent() -> str:
    return (
        f"Hertz-and-Hearts/{_installed_version_string()} "
        "(+https://github.com/JoelAtHome/HertzAndHearts)"
    )


def _display_installed(raw: str) -> str:
    """Match user-facing version labels used in the main window."""
    token = str(raw or "").strip()
    if not token:
        return "dev"
    match = re.fullmatch(r"(\d+\.\d+\.\d+)b(\d+)", token)
    if match:
        base, beta_num = match.groups()
        return f"{base}-beta" if beta_num == "0" else f"{base}-beta.{beta_num}"
    return token


def _normalize_tag(tag: str) -> str:
    tag = (tag or "").strip()
    if len(tag) > 1 and tag[0].lower() == "v" and tag[1].isdigit():
        return tag[1:]
    return tag


def _coerce_pep440(version_str: str) -> str:
    m = _BETA_TAG_RE.match(version_str.strip())
    if m:
        base, sub = m.group(1), m.group(2)
        return f"{base}b{sub or '0'}"
    return version_str.strip()


def parse_release_version(tag_name: str) -> Version | None:
    raw = _normalize_tag(tag_name)
    for candidate in (raw, _coerce_pep440(raw)):
        try:
            return Version(candidate)
        except InvalidVersion:
            continue
    return None


def installed_version() -> Version:
    try:
        return Version(_installed_version_string())
    except InvalidVersion:
        return Version("0")


@dataclass(frozen=True)
class ReleaseInfo:
    version: Version
    version_key: str
    version_display: str
    html_url: str
    tag_name: str
    release_name: str


@dataclass(frozen=True)
class UpdateCheckResult:
    outcome: Literal["newer", "current", "error", "no_releases"]
    release: ReleaseInfo | None
    user_message: str
    detail: str | None = None


def _read_state() -> dict[str, Any]:
    path = app_data_root() / _STATE_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(data: dict[str, Any]) -> None:
    path = app_data_root() / _STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def should_skip_background_check() -> bool:
    st = _read_state()
    last = st.get("last_check_unix")
    if last is None:
        return False
    try:
        elapsed = time.time() - float(last)
    except (TypeError, ValueError):
        return False
    return elapsed < _AUTO_CHECK_INTERVAL_SEC


def record_check_finished() -> None:
    st = _read_state()
    st["last_check_unix"] = time.time()
    _write_state(st)


def get_dismissed_version_key() -> str | None:
    st = _read_state()
    v = st.get("dismissed_version_key")
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def set_dismissed_version_key(key: str) -> None:
    st = _read_state()
    st["dismissed_version_key"] = str(key).strip()
    _write_state(st)


def fetch_releases_payload(timeout: float = 15.0) -> list[dict[str, Any]]:
    req = urllib.request.Request(
        GITHUB_RELEASES_API,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": _user_agent(),
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, list):
        return []
    return data


def pick_newest_release(releases: list[dict[str, Any]]) -> ReleaseInfo | None:
    best_v: Version | None = None
    best_info: ReleaseInfo | None = None
    for r in releases:
        if not isinstance(r, dict):
            continue
        if r.get("draft"):
            continue
        tag = str(r.get("tag_name") or "")
        pv = parse_release_version(tag)
        if pv is None:
            continue
        url = str(r.get("html_url") or RELEASES_PAGE_URL)
        name = str(r.get("name") or tag)
        norm = _normalize_tag(tag)
        info = ReleaseInfo(
            version=pv,
            version_key=str(pv),
            version_display=norm or str(pv),
            html_url=url,
            tag_name=tag,
            release_name=name,
        )
        if best_v is None or pv > best_v:
            best_v = pv
            best_info = info
    return best_info


def check_github_for_update() -> UpdateCheckResult:
    try:
        payload = fetch_releases_payload()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return UpdateCheckResult(
                "no_releases",
                None,
                "No releases were found for this project on GitHub.",
                str(e),
            )
        return UpdateCheckResult(
            "error",
            None,
            "Could not check for updates (GitHub returned an error).",
            str(e),
        )
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        return UpdateCheckResult(
            "error",
            None,
            "Could not reach GitHub. Check your internet connection.",
            str(reason),
        )
    except Exception as e:
        return UpdateCheckResult(
            "error",
            None,
            "Update check failed unexpectedly.",
            str(e),
        )

    newest = pick_newest_release(payload)
    if newest is None:
        return UpdateCheckResult(
            "no_releases",
            None,
            "No published releases with a recognized version tag were found.",
        )

    inst = installed_version()
    cur = _installed_version_string()
    cur_disp = _display_installed(cur)
    if newest.version > inst:
        return UpdateCheckResult(
            "newer",
            newest,
            f"A newer release is available ({newest.version_display}). "
            f"You are running {cur_disp}.",
        )
    return UpdateCheckResult(
        "current",
        newest,
        f"You are up to date. Latest public release is {newest.version_display}; "
        f"you have {cur_disp}.",
    )
