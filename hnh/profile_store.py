from __future__ import annotations

import hashlib
import json
import secrets
import re
import sqlite3
import shutil
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from hnh.session_artifacts import SessionBundle


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class ProfileStore:
    """SQLite-backed storage for profiles, per-user prefs, and session index."""
    _LEGACY_MIGRATION_KEY = "legacy_session_migration_v1"
    _DEFAULT_TO_ADMIN_MIGRATION_KEY = "default_to_admin_migration_v1"
    _TRENDS_BACKFILL_KEY = "session_trends_backfill_v1"
    _LEGACY_PROFILE_NAME = "Legacy User"

    def __init__(self, root: Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "profiles.db"
        self._initialize()
        self.migrate_legacy_sessions()
        self.migrate_default_to_admin()
        self._backfill_session_trends()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._db() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    archived_at TEXT,
                    age INTEGER,
                    gender TEXT,
                    notes TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            columns = {
                str(row["name"]).casefold()
                for row in conn.execute("PRAGMA table_info(profiles)").fetchall()
            }
            if "archived_at" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN archived_at TEXT")
            if "age" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN age INTEGER")
            if "gender" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN gender TEXT")
            if "notes" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN notes TEXT")
            if "dob" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN dob TEXT")
            if "password_hash" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN password_hash TEXT")
            if "role" not in columns:
                conn.execute("ALTER TABLE profiles ADD COLUMN role TEXT DEFAULT 'user'")
                conn.execute(
                    "UPDATE profiles SET role = 'admin' WHERE role IS NULL OR role = ''"
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_preferences (
                    profile_name TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY(profile_name, key)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_history (
                    session_id TEXT PRIMARY KEY,
                    profile_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    state TEXT NOT NULL,
                    session_dir TEXT NOT NULL,
                    csv_path TEXT NOT NULL,
                    is_hidden INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            session_history_columns = {
                str(row["name"]).casefold()
                for row in conn.execute("PRAGMA table_info(session_history)").fetchall()
            }
            if "is_hidden" not in session_history_columns:
                conn.execute("ALTER TABLE session_history ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_trends (
                    session_id TEXT PRIMARY KEY,
                    profile_name TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    avg_hr REAL,
                    avg_rmssd REAL,
                    avg_sdnn REAL,
                    qtc_ms REAL,
                    baseline_hr REAL,
                    baseline_rmssd REAL
                )
                """
            )

    @staticmethod
    def _normalize_profile(name: str) -> str:
        value = str(name).strip()
        return value or "Admin"

    def _get_app_state(self, key: str) -> str | None:
        with self._db() as conn:
            row = conn.execute(
                "SELECT value FROM app_state WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        value = str(row["value"]).strip()
        return value or None

    def _set_app_state(self, key: str, value: str) -> None:
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, str(value)),
            )

    LINUX_PHONE_BRIDGE_ECG_PROMPT_KEY = "linux_phone_bridge_ecg_prompt_v1"

    def get_linux_phone_bridge_ecg_prompt_choice(self) -> str:
        """
        Linux Phone Bridge ECG offer persistence (separate from PC BLE PMD setting).
        Returns '' (prompt each connection), 'always' (enable ECG without asking),
        or 'never' (declined; do not prompt again).
        """
        raw = self._get_app_state(self.LINUX_PHONE_BRIDGE_ECG_PROMPT_KEY)
        if raw in ("always", "never"):
            return raw
        return ""

    def set_linux_phone_bridge_ecg_prompt_choice(self, choice: str) -> None:
        if choice == "always":
            self._set_app_state(self.LINUX_PHONE_BRIDGE_ECG_PROMPT_KEY, "always")
        elif choice == "never":
            self._set_app_state(self.LINUX_PHONE_BRIDGE_ECG_PROMPT_KEY, "never")
        else:
            with self._db() as conn:
                conn.execute(
                    "DELETE FROM app_state WHERE key = ?",
                    (self.LINUX_PHONE_BRIDGE_ECG_PROMPT_KEY,),
                )

    @staticmethod
    def _safe_started_at(session_id: str, fallback: datetime) -> str:
        try:
            return datetime.strptime(session_id, "%Y%m%d-%H%M%S").isoformat()
        except ValueError:
            return fallback.isoformat()

    @classmethod
    def _infer_profile_name(cls, session_dir: Path, sessions_root: Path) -> str:
        try:
            rel = session_dir.relative_to(sessions_root)
            parts = list(rel.parts)
        except ValueError:
            return cls._LEGACY_PROFILE_NAME
        if not parts:
            return cls._LEGACY_PROFILE_NAME
        first = str(parts[0]).strip()
        if re.fullmatch(r"\d{4}", first or ""):
            return cls._LEGACY_PROFILE_NAME
        return cls._normalize_profile(first)

    def migrate_legacy_sessions(self) -> int:
        marker = self._get_app_state(self._LEGACY_MIGRATION_KEY)
        if marker == "done":
            return 0

        sessions_root = self._root / "Sessions"
        if not sessions_root.exists():
            self._set_app_state(self._LEGACY_MIGRATION_KEY, "done")
            return 0

        migrated = 0
        now = datetime.now()
        manifest_paths = sorted(sessions_root.rglob("session_manifest.json"))
        for manifest_path in manifest_paths:
            session_dir = manifest_path.parent
            payload: dict = {}
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}

            session_id = str(payload.get("session_id") or session_dir.name).strip() or session_dir.name
            profile_name = self._normalize_profile(
                str(payload.get("profile_id") or self._infer_profile_name(session_dir, sessions_root))
            )
            state = str(payload.get("state") or "finalized").strip() or "finalized"
            timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
            started_at = str(
                timing.get("started_at")
                or payload.get("updated_at")
                or self._safe_started_at(session_id, now)
            )
            ended_at = timing.get("ended_at") if isinstance(timing, dict) else None
            artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
            csv_meta = artifacts.get("csv") if isinstance(artifacts, dict) else {}
            csv_raw = csv_meta.get("path") if isinstance(csv_meta, dict) else None
            if csv_raw:
                csv_path = Path(str(csv_raw))
                if not csv_path.is_absolute():
                    csv_path = session_dir / csv_path
            else:
                csv_path = session_dir / "session.csv"

            self.ensure_profile(profile_name)
            with self._db() as conn:
                before = conn.execute(
                    "SELECT 1 FROM session_history WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO session_history (
                        session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        profile_name,
                        started_at,
                        str(ended_at) if ended_at else None,
                        state,
                        str(session_dir),
                        str(csv_path),
                    ),
                )
                if before is None:
                    migrated += 1

        self._set_app_state(self._LEGACY_MIGRATION_KEY, "done")
        return migrated

    def migrate_default_to_admin(self) -> int:
        """Rename Default profile to Admin and ensure admin role. One-time migration."""
        if self._get_app_state(self._DEFAULT_TO_ADMIN_MIGRATION_KEY) == "done":
            return 0
        migrated = 0
        with self._db() as conn:
            default_row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                ("Default",),
            ).fetchone()
            admin_row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                ("Admin",),
            ).fetchone()
            if default_row is not None and admin_row is None:
                actual_default = str(default_row["name"])
                conn.execute(
                    "UPDATE profiles SET name = ?, role = ? WHERE name = ? COLLATE NOCASE",
                    ("Admin", "admin", actual_default),
                )
                conn.execute(
                    "UPDATE profile_preferences SET profile_name = ? WHERE profile_name = ? COLLATE NOCASE",
                    ("Admin", actual_default),
                )
                conn.execute(
                    "UPDATE session_history SET profile_name = ? WHERE profile_name = ? COLLATE NOCASE",
                    ("Admin", actual_default),
                )
                conn.execute(
                    "UPDATE app_state SET value = ? WHERE key = ? AND lower(value) = lower(?)",
                    ("Admin", "last_active_profile", actual_default),
                )
                migrated = 1
            elif default_row is not None and admin_row is not None:
                actual_default = str(default_row["name"])
                conn.execute("DELETE FROM profile_preferences WHERE profile_name = ? COLLATE NOCASE", (actual_default,))
                conn.execute(
                    "UPDATE session_history SET profile_name = ? WHERE profile_name = ? COLLATE NOCASE",
                    ("Admin", actual_default),
                )
                conn.execute(
                    "UPDATE app_state SET value = ? WHERE key = ? AND lower(value) = lower(?)",
                    ("Admin", "last_active_profile", actual_default),
                )
                conn.execute("DELETE FROM profiles WHERE name = ? COLLATE NOCASE", (actual_default,))
                migrated = 1
        self._set_app_state(self._DEFAULT_TO_ADMIN_MIGRATION_KEY, "done")
        return migrated

    def list_profiles(self, include_archived: bool = False) -> list[str]:
        with self._db() as conn:
            if include_archived:
                rows = conn.execute(
                    "SELECT name FROM profiles ORDER BY lower(name), name"
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT name FROM profiles
                    WHERE archived_at IS NULL
                    ORDER BY lower(name), name
                    """
                ).fetchall()
        return [str(row["name"]) for row in rows]

    def list_profiles_info(
        self, include_archived: bool = True
    ) -> list[dict[str, str | int | bool | None]]:
        with self._db() as conn:
            if include_archived:
                rows = conn.execute(
                    """
                    SELECT name, created_at, last_used_at, archived_at, age, gender, notes, role
                    FROM profiles
                    ORDER BY lower(name), name
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT name, created_at, last_used_at, archived_at, age, gender, notes, role
                    FROM profiles
                    WHERE archived_at IS NULL
                    ORDER BY lower(name), name
                    """
                ).fetchall()
        info: list[dict[str, str | int | bool | None]] = []
        for row in rows:
            role_val = row["role"] if hasattr(row, "keys") and "role" in row.keys() else None
            role_str = str(role_val).strip().lower() if role_val else "user"
            role_str = "admin" if role_str == "admin" else "user"
            info.append(
                {
                    "name": str(row["name"]),
                    "created_at": str(row["created_at"]) if row["created_at"] else None,
                    "last_used_at": str(row["last_used_at"]) if row["last_used_at"] else None,
                    "archived_at": str(row["archived_at"]) if row["archived_at"] else None,
                    "archived": row["archived_at"] is not None,
                    "age": int(row["age"]) if row["age"] is not None else None,
                    "gender": str(row["gender"]) if row["gender"] else None,
                    "notes": str(row["notes"]) if row["notes"] else None,
                    "role": role_str,
                }
            )
        return info

    @staticmethod
    def _age_from_dob(dob_str: str | None) -> int | None:
        if not dob_str or not isinstance(dob_str, str):
            return None
        try:
            birth = datetime.strptime(dob_str.strip()[:10], "%Y-%m-%d").date()
            today = date.today()
            age = today.year - birth.year
            if (today.month, today.day) < (birth.month, birth.day):
                age -= 1
            return age if 1 <= age <= 130 else None
        except (ValueError, TypeError):
            return None

    def get_profile_details(self, name: str) -> dict[str, str | int | None]:
        profile_name = self._normalize_profile(name)
        with self._db() as conn:
            row = conn.execute(
                """
                SELECT name, age, dob, gender, notes
                FROM profiles
                WHERE name = ? COLLATE NOCASE
                """,
                (profile_name,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Profile not found: {profile_name}")
        dob_raw = row["dob"] if hasattr(row, "keys") and "dob" in row.keys() else None
        dob = str(dob_raw).strip() if dob_raw else None
        age = self._age_from_dob(dob)
        if age is None and row["age"] is not None:
            age = int(row["age"]) if 1 <= int(row["age"]) <= 130 else None
        return {
            "name": str(row["name"]),
            "dob": dob or None,
            "age": age,
            "gender": str(row["gender"]) if row["gender"] else None,
            "notes": str(row["notes"]) if row["notes"] else None,
        }

    def update_profile_details(
        self,
        name: str,
        *,
        dob: str | None = None,
        gender: str | None = None,
        notes: str | None = None,
    ) -> None:
        profile_name = self._normalize_profile(name)
        normalized_dob: str | None = None
        if dob is not None:
            s = str(dob).strip()
            if s:
                try:
                    datetime.strptime(s[:10], "%Y-%m-%d")
                    normalized_dob = s[:10]
                except ValueError:
                    pass
        age_computed = self._age_from_dob(normalized_dob) if normalized_dob else None
        normalized_gender = str(gender).strip() if gender is not None else ""
        normalized_notes = str(notes).strip() if notes is not None else ""
        with self._db() as conn:
            row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile_name,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Profile not found: {profile_name}")
            conn.execute(
                """
                UPDATE profiles
                SET dob = ?, age = ?, gender = ?, notes = ?
                WHERE name = ? COLLATE NOCASE
                """,
                (
                    normalized_dob,
                    age_computed,
                    normalized_gender or None,
                    normalized_notes or None,
                    profile_name,
                ),
            )

    def ensure_profile(self, name: str) -> str:
        profile_name = self._normalize_profile(name)
        role = "admin" if profile_name.casefold() == "admin" else "user"
        now = datetime.now().isoformat()
        with self._db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (name, created_at, last_used_at, role)
                VALUES (?, ?, ?, ?)
                """,
                (profile_name, now, now, role),
            )
            conn.execute(
                """
                UPDATE profiles
                SET archived_at = NULL
                WHERE name = ? COLLATE NOCASE
                """,
                (profile_name,),
            )
        return profile_name

    def rename_profile(self, old_name: str, new_name: str) -> str:
        source = self._normalize_profile(old_name)
        target = self._normalize_profile(new_name)
        if source.casefold() == target.casefold():
            return source
        with self._db() as conn:
            src_row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                (source,),
            ).fetchone()
            if src_row is None:
                raise ValueError(f"Profile not found: {source}")
            dst_row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                (target,),
            ).fetchone()
            if dst_row is not None:
                raise ValueError(f"Profile already exists: {target}")
            actual_source = str(src_row["name"])
            conn.execute(
                "UPDATE profiles SET name = ? WHERE name = ? COLLATE NOCASE",
                (target, actual_source),
            )
            conn.execute(
                """
                UPDATE profile_preferences
                SET profile_name = ?
                WHERE profile_name = ? COLLATE NOCASE
                """,
                (target, actual_source),
            )
            conn.execute(
                """
                UPDATE session_history
                SET profile_name = ?
                WHERE profile_name = ? COLLATE NOCASE
                """,
                (target, actual_source),
            )
            conn.execute(
                """
                UPDATE app_state
                SET value = ?
                WHERE key = ? AND lower(value) = lower(?)
                """,
                (target, "last_active_profile", actual_source),
            )
        return target

    def archive_profile(self, name: str) -> None:
        profile = self._normalize_profile(name)
        active_profile = self.get_last_active_profile()
        if active_profile and active_profile.casefold() == profile.casefold():
            raise ValueError("Cannot archive the active profile.")
        with self._db() as conn:
            row = conn.execute(
                "SELECT name, archived_at FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Profile not found: {profile}")
            if row["archived_at"] is not None:
                return
            remaining = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM profiles
                WHERE archived_at IS NULL AND lower(name) != lower(?)
                """,
                (profile,),
            ).fetchone()
            if remaining is None or int(remaining["total"]) < 1:
                raise ValueError("At least one active profile must remain.")
            conn.execute(
                """
                UPDATE profiles
                SET archived_at = ?
                WHERE name = ? COLLATE NOCASE
                """,
                (datetime.now().isoformat(), profile),
            )

    def delete_profile(self, name: str) -> None:
        profile = self._normalize_profile(name)
        active_profile = self.get_last_active_profile()
        if active_profile and active_profile.casefold() == profile.casefold():
            raise ValueError("Cannot delete the active profile.")
        with self._db() as conn:
            row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Profile not found: {profile}")
            remaining = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM profiles
                WHERE archived_at IS NULL AND lower(name) != lower(?)
                """,
                (profile,),
            ).fetchone()
            if remaining is None or int(remaining["total"]) < 1:
                raise ValueError("At least one active profile must remain.")
            conn.execute(
                "DELETE FROM profile_preferences WHERE profile_name = ? COLLATE NOCASE",
                (profile,),
            )
            conn.execute(
                "DELETE FROM session_history WHERE profile_name = ? COLLATE NOCASE",
                (profile,),
            )
            conn.execute(
                "DELETE FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            )

    def get_last_active_profile(self) -> str | None:
        return self._get_app_state("last_active_profile")

    def set_last_active_profile(self, name: str) -> str:
        profile_name = self.ensure_profile(name)
        now = datetime.now().isoformat()
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO app_state (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("last_active_profile", profile_name),
            )
            conn.execute(
                "UPDATE profiles SET last_used_at = ? WHERE name = ? COLLATE NOCASE",
                (now, profile_name),
            )
        return profile_name

    def get_profile_pref(self, profile_name: str, key: str, default: str = "") -> str:
        profile = self._normalize_profile(profile_name)
        with self._db() as conn:
            row = conn.execute(
                """
                SELECT value FROM profile_preferences
                WHERE profile_name = ? COLLATE NOCASE AND key = ?
                """,
                (profile, key),
            ).fetchone()
        return default if row is None else str(row["value"])

    def set_profile_pref(self, profile_name: str, key: str, value: str) -> None:
        profile = self.set_last_active_profile(profile_name)
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO profile_preferences (profile_name, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_name, key)
                DO UPDATE SET value = excluded.value
                """,
                (profile, key, str(value)),
            )

    _PW_PREFIX = "hnh:"

    def _hash_password(self, profile_name: str, password: str) -> str:
        data = f"{self._PW_PREFIX}{profile_name}||{password}".encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def get_profile_password_hash(self, profile_name: str) -> str | None:
        profile = self._normalize_profile(profile_name)
        with self._db() as conn:
            row = conn.execute(
                "SELECT password_hash FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            ).fetchone()
        if row is None or row["password_hash"] is None:
            return None
        return str(row["password_hash"]).strip() or None

    def profile_has_password(self, profile_name: str) -> bool:
        return self.get_profile_password_hash(profile_name) is not None

    def verify_profile_password(self, profile_name: str, password: str) -> bool:
        stored = self.get_profile_password_hash(profile_name)
        if stored is None:
            return True
        if not password:
            return False
        expected = self._hash_password(profile_name, password)
        return secrets.compare_digest(stored, expected)

    def get_profile_role(self, profile_name: str) -> str:
        """Return 'admin' or 'user'. Missing/Guest legacy profiles default to 'admin'."""
        if not profile_name or str(profile_name).strip().casefold() == "guest":
            return "user"
        profile = self._normalize_profile(profile_name)
        with self._db() as conn:
            row = conn.execute(
                "SELECT role FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            ).fetchone()
        if row is None or row["role"] is None or not str(row["role"]).strip():
            return "admin"
        r = str(row["role"]).strip().lower()
        return r if r in ("admin", "user") else "admin"

    def profile_is_admin(self, profile_name: str) -> bool:
        """Return True if the profile has admin role. Guest and missing/legacy profiles are treated as non-admin."""
        return self.get_profile_role(profile_name) == "admin"

    def set_profile_role(self, profile_name: str, role: str) -> None:
        """Set profile role to 'admin' or 'user'. Admin only."""
        profile = self._normalize_profile(profile_name)
        r = str(role).strip().lower()
        if r not in ("admin", "user"):
            raise ValueError("Role must be 'admin' or 'user'")
        with self._db() as conn:
            row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Profile not found: {profile}")
            conn.execute(
                "UPDATE profiles SET role = ? WHERE name = ? COLLATE NOCASE",
                (r, profile),
            )

    def set_profile_password(self, profile_name: str, password: str) -> None:
        profile = self._normalize_profile(profile_name)
        with self._db() as conn:
            row = conn.execute(
                "SELECT name FROM profiles WHERE name = ? COLLATE NOCASE",
                (profile,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Profile not found: {profile}")
            actual_name = str(row["name"])
        pw_hash = self._hash_password(actual_name, password) if password else None
        with self._db() as conn:
            conn.execute(
                "UPDATE profiles SET password_hash = ? WHERE name = ? COLLATE NOCASE",
                (pw_hash, profile),
            )

    def clear_profile_pref(self, profile_name: str, key: str) -> None:
        profile = self._normalize_profile(profile_name)
        with self._db() as conn:
            conn.execute(
                """
                DELETE FROM profile_preferences
                WHERE profile_name = ? COLLATE NOCASE AND key = ?
                """,
                (profile, key),
            )

    def clear_profile_pref_for_all(self, key: str) -> None:
        with self._db() as conn:
            conn.execute(
                "DELETE FROM profile_preferences WHERE key = ?",
                (key,),
            )

    def record_session_started(self, profile_name: str, bundle: SessionBundle) -> None:
        profile = self.set_last_active_profile(profile_name)
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO session_history (
                    session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    profile_name = excluded.profile_name,
                    started_at = excluded.started_at,
                    state = excluded.state,
                    session_dir = excluded.session_dir,
                    csv_path = excluded.csv_path
                """,
                (
                    bundle.session_id,
                    profile,
                    bundle.started_at.isoformat(),
                    None,
                    "recording",
                    str(bundle.session_dir),
                    str(bundle.csv_path),
                ),
            )

    def record_session_finished(self, session_id: str, state: str) -> None:
        now = datetime.now().isoformat()
        with self._db() as conn:
            conn.execute(
                """
                UPDATE session_history
                SET ended_at = ?, state = ?
                WHERE session_id = ?
                """,
                (now, state, session_id),
            )

    def record_session_trend(
        self,
        profile_name: str,
        session_id: str,
        ended_at: datetime | str,
        *,
        avg_hr: float | None = None,
        avg_rmssd: float | None = None,
        avg_sdnn: float | None = None,
        qtc_ms: float | None = None,
        baseline_hr: float | None = None,
        baseline_rmssd: float | None = None,
    ) -> None:
        """Store average session metrics for trends comparison."""
        profile = self._normalize_profile(profile_name)
        ended = ended_at.isoformat() if isinstance(ended_at, datetime) else str(ended_at)
        with self._db() as conn:
            conn.execute(
                """
                INSERT INTO session_trends (
                    session_id, profile_name, ended_at,
                    avg_hr, avg_rmssd, avg_sdnn, qtc_ms,
                    baseline_hr, baseline_rmssd
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    profile_name = excluded.profile_name,
                    ended_at = excluded.ended_at,
                    avg_hr = excluded.avg_hr,
                    avg_rmssd = excluded.avg_rmssd,
                    avg_sdnn = excluded.avg_sdnn,
                    qtc_ms = excluded.qtc_ms,
                    baseline_hr = excluded.baseline_hr,
                    baseline_rmssd = excluded.baseline_rmssd
                """,
                (
                    session_id,
                    profile,
                    ended,
                    avg_hr,
                    avg_rmssd,
                    avg_sdnn,
                    qtc_ms,
                    baseline_hr,
                    baseline_rmssd,
                ),
            )

    def list_session_trends(
        self,
        profile_name: str,
        *,
        span: str = "month",
    ) -> list[dict[str, str | float | None]]:
        """List session trend rows for a profile within the given time span."""
        profile = self._normalize_profile(profile_name)
        now = datetime.now()
        if span == "day":
            since = now - timedelta(days=1)
        elif span == "week":
            since = now - timedelta(days=7)
        elif span == "month":
            since = now - timedelta(days=30)
        elif span == "year":
            since = now - timedelta(days=365)
        else:
            since = now - timedelta(days=30)
        since_iso = since.isoformat()
        with self._db() as conn:
            rows = conn.execute(
                """
                SELECT session_id, profile_name, ended_at,
                       avg_hr, avg_rmssd, avg_sdnn, qtc_ms,
                       baseline_hr, baseline_rmssd
                FROM session_trends
                WHERE profile_name = ? COLLATE NOCASE AND ended_at >= ?
                ORDER BY ended_at ASC
                """,
                (profile, since_iso),
            ).fetchall()
        out: list[dict[str, str | float | None]] = []
        for row in rows:
            out.append(
                {
                    "session_id": str(row["session_id"]),
                    "profile_name": str(row["profile_name"]),
                    "ended_at": str(row["ended_at"]),
                    "avg_hr": float(row["avg_hr"]) if row["avg_hr"] is not None else None,
                    "avg_rmssd": float(row["avg_rmssd"]) if row["avg_rmssd"] is not None else None,
                    "avg_sdnn": float(row["avg_sdnn"]) if row["avg_sdnn"] is not None else None,
                    "qtc_ms": float(row["qtc_ms"]) if row["qtc_ms"] is not None else None,
                    "baseline_hr": float(row["baseline_hr"]) if row["baseline_hr"] is not None else None,
                    "baseline_rmssd": float(row["baseline_rmssd"]) if row["baseline_rmssd"] is not None else None,
                }
            )
        return out

    def _ingest_session_trend_from_manifest(
        self,
        *,
        session_id: str,
        profile_name: str,
        ended_at: str,
        session_dir: str,
    ) -> bool:
        """Read session_manifest.json under session_dir and upsert session_trends. Returns True if written."""
        sid = str(session_id).strip()
        if not sid:
            return False
        manifest_path = Path(str(session_dir).strip()) / "session_manifest.json"
        if not manifest_path.is_file():
            return False
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        metrics = payload.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}
        qtc_data = metrics.get("qtc") if isinstance(metrics.get("qtc"), dict) else {}
        qtc_ms = qtc_data.get("session_value_ms")
        if qtc_ms is not None:
            try:
                qtc_ms = float(qtc_ms)
            except (TypeError, ValueError):
                qtc_ms = None
        self.record_session_trend(
            profile_name=str(profile_name),
            session_id=sid,
            ended_at=str(ended_at),
            avg_hr=_float_or_none(metrics.get("last_hr")),
            avg_rmssd=_float_or_none(metrics.get("last_rmssd")),
            avg_sdnn=None,
            qtc_ms=qtc_ms,
            baseline_hr=_float_or_none(metrics.get("baseline_hr")),
            baseline_rmssd=_float_or_none(metrics.get("baseline_rmssd")),
        )
        return True

    def fill_missing_session_trends_from_manifests(self) -> int:
        """
        Insert session_trends rows for completed session_history rows that have no trend row yet,
        using metrics from each folder's session_manifest.json (same rules as the one-time backfill).
        """
        with self._db() as conn:
            rows = conn.execute(
                """
                SELECT h.session_id, h.profile_name, h.ended_at, h.session_dir
                FROM session_history h
                LEFT JOIN session_trends t ON t.session_id = h.session_id
                WHERE h.ended_at IS NOT NULL AND t.session_id IS NULL
                ORDER BY h.ended_at ASC
                """
            ).fetchall()
        filled = 0
        for row in rows:
            if self._ingest_session_trend_from_manifest(
                session_id=str(row["session_id"]),
                profile_name=str(row["profile_name"]),
                ended_at=str(row["ended_at"]),
                session_dir=str(row["session_dir"]),
            ):
                filled += 1
        return filled

    def _backfill_session_trends(self) -> int:
        """One-time backfill of session_trends from existing manifests."""
        if self._get_app_state(self._TRENDS_BACKFILL_KEY) == "done":
            return 0
        migrated = 0
        with self._db() as conn:
            rows = conn.execute(
                """
                SELECT session_id, profile_name, ended_at, session_dir
                FROM session_history
                WHERE ended_at IS NOT NULL
                ORDER BY ended_at ASC
                """
            ).fetchall()
        for row in rows:
            if self._ingest_session_trend_from_manifest(
                session_id=str(row["session_id"]),
                profile_name=str(row["profile_name"]),
                ended_at=str(row["ended_at"]),
                session_dir=str(row["session_dir"]),
            ):
                migrated += 1
        self._set_app_state(self._TRENDS_BACKFILL_KEY, "done")
        return migrated

    def list_sessions(
        self,
        profile_name: str | None = None,
        *,
        state: str | None = None,
        include_hidden: bool = False,
        limit: int = 100,
    ) -> list[dict[str, str | None]]:
        max_rows = max(1, int(limit))
        sql = [
            "SELECT session_id, profile_name, started_at, ended_at, state, session_dir, csv_path, is_hidden",
            "FROM session_history",
        ]
        params: list[str | int] = []
        where: list[str] = []
        if profile_name:
            where.append("profile_name = ? COLLATE NOCASE")
            params.append(self._normalize_profile(profile_name))
        if state:
            where.append("state = ?")
            params.append(str(state).strip())
        if not include_hidden:
            where.append("is_hidden = 0")
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY started_at DESC, session_id DESC")
        sql.append("LIMIT ?")
        params.append(max_rows)
        query = "\n".join(sql)
        with self._db() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        out: list[dict[str, str | None]] = []
        for row in rows:
            out.append(
                {
                    "session_id": str(row["session_id"]),
                    "profile_name": str(row["profile_name"]),
                    "started_at": str(row["started_at"]),
                    "ended_at": str(row["ended_at"]) if row["ended_at"] is not None else None,
                    "state": str(row["state"]),
                    "session_dir": str(row["session_dir"]),
                    "csv_path": str(row["csv_path"]),
                    "is_hidden": "1" if int(row["is_hidden"] or 0) else "0",
                }
            )
        return out

    def get_sessions_by_ids(self, session_ids: list[str]) -> list[dict[str, str | None]]:
        ids = [str(s).strip() for s in session_ids if str(s).strip()]
        if not ids:
            return []
        qmarks = ",".join(["?"] * len(ids))
        query = (
            "SELECT session_id, profile_name, started_at, ended_at, state, session_dir, csv_path, is_hidden "
            f"FROM session_history WHERE session_id IN ({qmarks}) "
            "ORDER BY started_at DESC, session_id DESC"
        )
        with self._db() as conn:
            rows = conn.execute(query, tuple(ids)).fetchall()
        out: list[dict[str, str | None]] = []
        for row in rows:
            out.append(
                {
                    "session_id": str(row["session_id"]),
                    "profile_name": str(row["profile_name"]),
                    "started_at": str(row["started_at"]),
                    "ended_at": str(row["ended_at"]) if row["ended_at"] is not None else None,
                    "state": str(row["state"]),
                    "session_dir": str(row["session_dir"]),
                    "csv_path": str(row["csv_path"]),
                    "is_hidden": "1" if int(row["is_hidden"] or 0) else "0",
                }
            )
        return out

    def _session_record_from_manifest(
        self,
        *,
        manifest_path: Path,
        scan_root: Path,
        fallback_now: datetime,
    ) -> dict[str, str | None] | None:
        session_dir = manifest_path.parent
        payload: dict[str, Any] = {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}

        session_id = str(payload.get("session_id") or session_dir.name).strip() or session_dir.name
        timing = payload.get("timing") if isinstance(payload.get("timing"), dict) else {}
        started_at = str(
            timing.get("started_at")
            or payload.get("updated_at")
            or self._safe_started_at(session_id, fallback_now)
        )
        ended_at_val = timing.get("ended_at") if isinstance(timing, dict) else None
        ended_at = str(ended_at_val).strip() if ended_at_val else None
        state = str(payload.get("state") or "finalized").strip() or "finalized"
        profile_name = str(payload.get("profile_id") or "").strip()
        if not profile_name:
            profile_name = self._infer_profile_name(session_dir, scan_root)
        profile_name = self._normalize_profile(profile_name or self._LEGACY_PROFILE_NAME)

        artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
        csv_meta = artifacts.get("csv") if isinstance(artifacts, dict) else {}
        csv_raw = csv_meta.get("path") if isinstance(csv_meta, dict) else None
        if csv_raw:
            csv_path = Path(str(csv_raw))
            if not csv_path.is_absolute():
                csv_path = session_dir / csv_path
        else:
            csv_path = session_dir / "session.csv"

        return {
            "session_id": session_id,
            "profile_name": profile_name,
            "started_at": started_at,
            "ended_at": ended_at,
            "state": state,
            "session_dir": str(session_dir),
            "csv_path": str(csv_path),
        }

    @staticmethod
    def _disk_record_strip_meta(row: dict[str, Any]) -> dict[str, str | None]:
        return {
            "session_id": str(row.get("session_id") or ""),
            "profile_name": str(row.get("profile_name") or ""),
            "started_at": str(row.get("started_at") or ""),
            "ended_at": row.get("ended_at"),
            "state": str(row.get("state") or ""),
            "session_dir": str(row.get("session_dir") or ""),
            "csv_path": str(row.get("csv_path") or ""),
        }

    def resolve_disk_duplicate_session(
        self,
        *,
        keep_session_dir: str,
        remove_session_dirs: list[str],
    ) -> dict[str, int]:
        """
        Keep one session folder and delete other duplicate locations on disk, then upsert DB from the kept manifest.
        remove_session_dirs must not include keep_session_dir.
        """
        keep = Path(str(keep_session_dir).strip()).resolve()
        if not keep.exists():
            raise ValueError(f"Keep path does not exist: {keep}")
        manifest_keep = keep / "session_manifest.json"
        if not manifest_keep.is_file():
            raise ValueError(f"Missing manifest in keep folder: {manifest_keep}")

        removed = 0
        for raw in remove_session_dirs:
            p = Path(str(raw).strip()).resolve()
            if not str(raw).strip() or p == keep:
                continue
            if not p.exists():
                continue
            shutil.rmtree(p, ignore_errors=False)
            removed += 1

        rec = self._session_record_from_manifest(
            manifest_path=manifest_keep,
            scan_root=self._root / "Sessions",
            fallback_now=datetime.now(),
        )
        if rec is None:
            raise ValueError("Could not read kept session manifest.")
        upserted = self._upsert_session_history_rows([self._disk_record_strip_meta(rec)])
        return {"removed_folders": removed, "upserted_rows": upserted}

    def _upsert_session_history_rows(
        self,
        rows: list[dict[str, str | None]],
    ) -> int:
        cleaned: list[dict[str, str | None]] = []
        seen: set[str] = set()
        for row in rows:
            sid = str(row.get("session_id") or "").strip()
            profile = str(row.get("profile_name") or "").strip()
            started_at = str(row.get("started_at") or "").strip()
            state = str(row.get("state") or "").strip()
            session_dir = str(row.get("session_dir") or "").strip()
            csv_path = str(row.get("csv_path") or "").strip()
            ended_at_raw = row.get("ended_at")
            ended_at = str(ended_at_raw).strip() if ended_at_raw else None
            if not sid or sid in seen:
                continue
            if not profile or not started_at or not state or not session_dir or not csv_path:
                continue
            seen.add(sid)
            cleaned.append(
                {
                    "session_id": sid,
                    "profile_name": profile,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "state": state,
                    "session_dir": session_dir,
                    "csv_path": csv_path,
                }
            )
        if not cleaned:
            return 0

        for profile_name in sorted({str(r["profile_name"]) for r in cleaned}):
            self.ensure_profile(profile_name)

        with self._db() as conn:
            for row in cleaned:
                profile = str(row["profile_name"])
                sid = str(row["session_id"])
                conn.execute(
                    """
                    INSERT INTO session_history (
                        session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        profile_name = excluded.profile_name,
                        started_at = excluded.started_at,
                        ended_at = excluded.ended_at,
                        state = excluded.state,
                        session_dir = excluded.session_dir,
                        csv_path = excluded.csv_path
                    """,
                    (
                        sid,
                        profile,
                        str(row["started_at"]),
                        str(row["ended_at"]) if row["ended_at"] else None,
                        str(row["state"]),
                        str(row["session_dir"]),
                        str(row["csv_path"]),
                    ),
                )
                conn.execute(
                    """
                    UPDATE session_trends
                    SET profile_name = ?
                    WHERE session_id = ?
                    """,
                    (profile, sid),
                )
        return len(cleaned)

    def audit_session_history_integrity(
        self,
        *,
        scan_roots: list[Path],
    ) -> dict[str, Any]:
        roots: list[Path] = []
        seen_roots: set[str] = set()
        for root in scan_roots:
            p = Path(root).expanduser()
            key = str(p).casefold()
            if key in seen_roots:
                continue
            seen_roots.add(key)
            roots.append(p)

        now = datetime.now()
        entries_by_sid: dict[str, list[dict[str, Any]]] = defaultdict(list)
        manifest_count = 0
        for root in roots:
            if not root.exists():
                continue
            for manifest_path in root.rglob("session_manifest.json"):
                manifest_count += 1
                rec = self._session_record_from_manifest(
                    manifest_path=manifest_path,
                    scan_root=root,
                    fallback_now=now,
                )
                if rec is None:
                    continue
                sid = str(rec.get("session_id") or "").strip()
                if not sid:
                    continue
                try:
                    man_mtime = manifest_path.stat().st_mtime
                except OSError:
                    man_mtime = 0.0
                session_dir = Path(str(rec.get("session_dir") or manifest_path.parent))
                try:
                    dir_mtime = session_dir.stat().st_mtime
                except OSError:
                    dir_mtime = 0.0
                row: dict[str, Any] = dict(rec)
                row["manifest_mtime"] = man_mtime
                row["session_dir_mtime"] = dir_mtime
                entries_by_sid[sid].append(row)

        disk_by_id: dict[str, dict[str, str | None]] = {}
        duplicate_disk_groups: list[dict[str, Any]] = []
        for sid in sorted(entries_by_sid.keys()):
            entries = entries_by_sid[sid]
            if len(entries) == 1:
                disk_by_id[sid] = self._disk_record_strip_meta(entries[0])
                continue
            sorted_by_time = sorted(entries, key=lambda e: float(e.get("manifest_mtime") or 0.0))
            duplicate_disk_groups.append(
                {
                    "session_id": sid,
                    "locations": [
                        {
                            "session_dir": str(e.get("session_dir") or ""),
                            "csv_path": str(e.get("csv_path") or ""),
                            "profile_name": str(e.get("profile_name") or ""),
                            "manifest_mtime": float(e.get("manifest_mtime") or 0.0),
                            "session_dir_mtime": float(e.get("session_dir_mtime") or 0.0),
                        }
                        for e in sorted_by_time
                    ],
                }
            )
            best = max(entries, key=lambda e: float(e.get("manifest_mtime") or 0.0))
            disk_by_id[sid] = self._disk_record_strip_meta(best)

        with self._db() as conn:
            rows = conn.execute(
                """
                SELECT session_id, profile_name, started_at, ended_at, state, session_dir, csv_path
                FROM session_history
                """
            ).fetchall()
        db_by_id: dict[str, dict[str, str | None]] = {}
        for row in rows:
            sid = str(row["session_id"] or "").strip()
            if not sid:
                continue
            db_by_id[sid] = {
                "session_id": sid,
                "profile_name": str(row["profile_name"] or ""),
                "started_at": str(row["started_at"] or ""),
                "ended_at": str(row["ended_at"]) if row["ended_at"] is not None else None,
                "state": str(row["state"] or ""),
                "session_dir": str(row["session_dir"] or ""),
                "csv_path": str(row["csv_path"] or ""),
            }

        missing_on_disk: list[dict[str, str | None]] = []
        missing_in_db: list[dict[str, str | None]] = []
        path_mismatch: list[dict[str, str | None]] = []
        profile_mismatch: list[dict[str, str | None]] = []

        for sid, db_row in db_by_id.items():
            disk_row = disk_by_id.get(sid)
            if disk_row is None:
                missing_on_disk.append(db_row)
                continue
            db_dir = str(db_row.get("session_dir") or "").strip()
            disk_dir = str(disk_row.get("session_dir") or "").strip()
            if db_dir != disk_dir:
                path_mismatch.append(
                    {
                        "session_id": sid,
                        "db_session_dir": db_dir,
                        "disk_session_dir": disk_dir,
                        "disk_csv_path": str(disk_row.get("csv_path") or ""),
                    }
                )
            db_profile = str(db_row.get("profile_name") or "").strip()
            disk_profile = str(disk_row.get("profile_name") or "").strip()
            if db_profile.casefold() != disk_profile.casefold():
                profile_mismatch.append(
                    {
                        "session_id": sid,
                        "db_profile": db_profile,
                        "disk_profile": disk_profile,
                    }
                )

        for sid, disk_row in disk_by_id.items():
            if sid not in db_by_id:
                missing_in_db.append(disk_row)

        return {
            "scan_roots": [str(p) for p in roots],
            "db_rows": len(db_by_id),
            "manifest_count": manifest_count,
            "disk_unique_sessions": len(disk_by_id),
            "disk_records": list(disk_by_id.values()),
            "missing_on_disk": missing_on_disk,
            "missing_in_db": missing_in_db,
            "path_mismatch": path_mismatch,
            "profile_mismatch": profile_mismatch,
            "duplicate_disk_groups": duplicate_disk_groups,
            "duplicate_disk_session_ids": sorted(
                {str(g.get("session_id") or "").strip() for g in duplicate_disk_groups if str(g.get("session_id") or "").strip()}
            ),
            "has_issues": bool(
                missing_on_disk
                or missing_in_db
                or path_mismatch
                or profile_mismatch
                or duplicate_disk_groups
            ),
        }

    def repair_session_history_integrity(
        self,
        *,
        audit: dict[str, Any],
        remove_missing_on_disk: bool = True,
        add_missing_in_db: bool = True,
        repair_mismatched_rows: bool = True,
        fill_missing_session_trends: bool = True,
    ) -> dict[str, int]:
        removed_rows = 0
        removed_trends = 0
        upserted_rows = 0
        filled_trends_rows = 0

        if remove_missing_on_disk:
            ids = [
                str(row.get("session_id") or "").strip()
                for row in list(audit.get("missing_on_disk") or [])
                if str(row.get("session_id") or "").strip()
            ]
            if ids:
                deleted = self.delete_sessions_by_ids(ids)
                removed_rows = int(deleted.get("removed_rows") or 0)
                removed_trends = int(deleted.get("removed_trends") or 0)

        if add_missing_in_db:
            rows = [r for r in list(audit.get("missing_in_db") or []) if isinstance(r, dict)]
            upserted_rows += self._upsert_session_history_rows(rows)

        if repair_mismatched_rows:
            repair_ids: set[str] = set()
            for row in list(audit.get("path_mismatch") or []):
                sid = str(row.get("session_id") or "").strip()
                if sid:
                    repair_ids.add(sid)
            for row in list(audit.get("profile_mismatch") or []):
                sid = str(row.get("session_id") or "").strip()
                if sid:
                    repair_ids.add(sid)
            if repair_ids:
                disk_rows = [
                    r for r in list(audit.get("disk_records") or []) if isinstance(r, dict)
                ]
                disk_by_id = {
                    str(r.get("session_id") or "").strip(): r
                    for r in disk_rows
                    if str(r.get("session_id") or "").strip()
                }
                rows_to_fix = [disk_by_id[sid] for sid in sorted(repair_ids) if sid in disk_by_id]
                upserted_rows += self._upsert_session_history_rows(rows_to_fix)

        if fill_missing_session_trends:
            filled_trends_rows = self.fill_missing_session_trends_from_manifests()

        return {
            "removed_rows": removed_rows,
            "removed_trends": removed_trends,
            "upserted_rows": upserted_rows,
            "filled_trends_rows": filled_trends_rows,
        }

    def reassign_sessions(
        self,
        *,
        target_profile: str,
        updates: list[dict[str, str]],
    ) -> int:
        """
        Reassign session ownership and storage paths.

        Expected update item keys:
        - session_id (required)
        - session_dir (required)
        - csv_path (required)
        """
        profile = self.ensure_profile(target_profile)
        clean_updates: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for row in updates:
            sid = str(row.get("session_id") or "").strip()
            session_dir = str(row.get("session_dir") or "").strip()
            csv_path = str(row.get("csv_path") or "").strip()
            if not sid or not session_dir or not csv_path:
                continue
            if sid in seen:
                continue
            seen.add(sid)
            clean_updates.append((sid, session_dir, csv_path))
        if not clean_updates:
            return 0

        updated = 0
        with self._db() as conn:
            for sid, session_dir, csv_path in clean_updates:
                cur = conn.execute(
                    """
                    UPDATE session_history
                    SET profile_name = ?, session_dir = ?, csv_path = ?
                    WHERE session_id = ?
                    """,
                    (profile, session_dir, csv_path, sid),
                )
                conn.execute(
                    """
                    UPDATE session_trends
                    SET profile_name = ?
                    WHERE session_id = ?
                    """,
                    (profile, sid),
                )
                updated += int(cur.rowcount or 0)
        return updated

    def delete_sessions_by_ids(self, session_ids: list[str]) -> dict[str, int]:
        """Delete session rows (history + trends) for explicit session IDs."""
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in session_ids:
            sid = str(raw or "").strip()
            if not sid or sid in seen:
                continue
            seen.add(sid)
            cleaned.append(sid)
        if not cleaned:
            return {"removed_rows": 0, "removed_trends": 0}

        qmarks = ",".join(["?"] * len(cleaned))
        removed_rows = 0
        removed_trends = 0
        with self._db() as conn:
            cur_history = conn.execute(
                f"DELETE FROM session_history WHERE session_id IN ({qmarks})",
                tuple(cleaned),
            )
            cur_trends = conn.execute(
                f"DELETE FROM session_trends WHERE session_id IN ({qmarks})",
                tuple(cleaned),
            )
            removed_rows = int(cur_history.rowcount or 0)
            removed_trends = int(cur_trends.rowcount or 0)
        return {"removed_rows": removed_rows, "removed_trends": removed_trends}

    def set_session_hidden(self, session_id: str, hidden: bool) -> bool:
        sid = str(session_id).strip()
        if not sid:
            return False
        with self._db() as conn:
            cur = conn.execute(
                """
                UPDATE session_history
                SET is_hidden = ?
                WHERE session_id = ?
                """,
                (1 if hidden else 0, sid),
            )
        return cur.rowcount > 0

    def count_sessions(self, profile_name: str | None = None) -> int:
        with self._db() as conn:
            if profile_name:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM session_history
                    WHERE profile_name = ? COLLATE NOCASE
                    """,
                    (self._normalize_profile(profile_name),),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS total FROM session_history"
                ).fetchone()
        return 0 if row is None else int(row["total"])

    def purge_abandoned_sessions(self, profile_name: str | None = None) -> dict[str, int]:
        """Delete abandoned sessions from DB and remove their session folders."""
        return self.purge_sessions_by_state("abandoned", profile_name=profile_name)

    def purge_recording_sessions(self, profile_name: str | None = None) -> dict[str, int]:
        """Delete stale recording sessions from DB and remove their session folders."""
        return self.purge_sessions_by_state("recording", profile_name=profile_name)

    def purge_sessions_by_state(
        self,
        state: str,
        profile_name: str | None = None,
    ) -> dict[str, int]:
        """Delete sessions in a given state from DB and remove their session folders."""
        target_state = str(state or "").strip().lower()
        if not target_state:
            return {"found": 0, "deleted_dirs": 0, "missing_dirs": 0, "removed_rows": 0}

        sql = [
            "SELECT session_id, session_dir",
            "FROM session_history",
            "WHERE lower(state) = ?",
        ]
        params: list[str] = [target_state]
        if profile_name:
            sql.append("AND profile_name = ? COLLATE NOCASE")
            params.append(self._normalize_profile(profile_name))
        query = "\n".join(sql)
        with self._db() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()

        session_ids: list[str] = []
        deleted_dirs = 0
        missing_dirs = 0
        for row in rows:
            sid = str(row["session_id"]).strip()
            if not sid:
                continue
            session_ids.append(sid)
            session_dir = Path(str(row["session_dir"] or "")).resolve()
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)
                deleted_dirs += 1
            else:
                missing_dirs += 1

        removed_rows = 0
        if session_ids:
            qmarks = ",".join(["?"] * len(session_ids))
            with self._db() as conn:
                cur = conn.execute(
                    f"DELETE FROM session_history WHERE session_id IN ({qmarks})",
                    tuple(session_ids),
                )
                conn.execute(
                    f"DELETE FROM session_trends WHERE session_id IN ({qmarks})",
                    tuple(session_ids),
                )
                removed_rows = int(cur.rowcount or 0)

        return {
            "found": len(rows),
            "deleted_dirs": deleted_dirs,
            "missing_dirs": missing_dirs,
            "removed_rows": removed_rows,
        }
