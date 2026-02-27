from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path

from hnh.session_artifacts import SessionBundle


class ProfileStore:
    """SQLite-backed storage for profiles, per-user prefs, and session index."""
    _LEGACY_MIGRATION_KEY = "legacy_session_migration_v1"
    _LEGACY_PROFILE_NAME = "Legacy User"

    def __init__(self, root: Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "profiles.db"
        self._initialize()
        self.migrate_legacy_sessions()

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
                    csv_path TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _normalize_profile(name: str) -> str:
        value = str(name).strip()
        return value or "Default"

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
                    SELECT name, created_at, last_used_at, archived_at, age, gender, notes
                    FROM profiles
                    ORDER BY lower(name), name
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT name, created_at, last_used_at, archived_at, age, gender, notes
                    FROM profiles
                    WHERE archived_at IS NULL
                    ORDER BY lower(name), name
                    """
                ).fetchall()
        info: list[dict[str, str | int | bool | None]] = []
        for row in rows:
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
        now = datetime.now().isoformat()
        with self._db() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO profiles (name, created_at, last_used_at)
                VALUES (?, ?, ?)
                """,
                (profile_name, now, now),
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

    def list_sessions(
        self,
        profile_name: str | None = None,
        *,
        state: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, str | None]]:
        max_rows = max(1, int(limit))
        sql = [
            "SELECT session_id, profile_name, started_at, ended_at, state, session_dir, csv_path",
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
                }
            )
        return out

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
