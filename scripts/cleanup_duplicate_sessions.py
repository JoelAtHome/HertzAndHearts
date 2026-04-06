from __future__ import annotations

import argparse
import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


YEAR_RE = re.compile(r"^\d{4}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SESSION_ID_RE = re.compile(r"^\d{8}-\d{6}(?:_\d{2})?$")


@dataclass(frozen=True)
class SessionKey:
    year: str
    day: str
    session_id: str


@dataclass
class SessionRecord:
    path: Path
    key: SessionKey
    csv_hash: str


def _hash_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _as_session_key(path: Path) -> SessionKey | None:
    parts = path.parts
    if len(parts) < 3:
        return None
    year, day, session_id = parts[-3], parts[-2], parts[-1]
    if not YEAR_RE.fullmatch(year):
        return None
    if not DATE_RE.fullmatch(day):
        return None
    if not SESSION_ID_RE.fullmatch(session_id):
        return None
    return SessionKey(year=year, day=day, session_id=session_id)


def _scan_sessions(root: Path) -> list[SessionRecord]:
    records: list[SessionRecord] = []
    if not root.exists():
        return records
    for csv_path in root.rglob("session.csv"):
        session_dir = csv_path.parent
        key = _as_session_key(session_dir)
        if key is None:
            continue
        try:
            csv_hash = _hash_file(csv_path)
        except OSError:
            continue
        records.append(SessionRecord(path=session_dir, key=key, csv_hash=csv_hash))
    return records


def _build_primary_index(records: list[SessionRecord]) -> dict[tuple[SessionKey, str], list[Path]]:
    index: dict[tuple[SessionKey, str], list[Path]] = {}
    for rec in records:
        k = (rec.key, rec.csv_hash)
        index.setdefault(k, []).append(rec.path)
    return index


def cleanup_duplicates(primary_root: Path, secondary_root: Path, apply: bool) -> tuple[int, int]:
    primary_records = _scan_sessions(primary_root)
    secondary_records = _scan_sessions(secondary_root)
    primary_index = _build_primary_index(primary_records)

    matches: list[SessionRecord] = []
    for rec in secondary_records:
        if (rec.key, rec.csv_hash) in primary_index:
            matches.append(rec)

    deleted = 0
    for rec in matches:
        print(f"MATCH: {rec.path}")
        if apply:
            shutil.rmtree(rec.path)
            deleted += 1
            print(f"DELETED: {rec.path}")

    print(
        f"Scanned primary={len(primary_records)} secondary={len(secondary_records)} "
        f"matches={len(matches)} deleted={deleted}"
    )
    return len(matches), deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Safely remove duplicate session folders from a secondary tree when an identical "
            "session (same year/day/session_id and same session.csv SHA-256) exists in a primary tree."
        )
    )
    parser.add_argument("--primary", required=True, help="Primary sessions root to keep")
    parser.add_argument("--secondary", required=True, help="Secondary sessions root to prune")
    parser.add_argument("--apply", action="store_true", help="Actually delete matches")
    args = parser.parse_args()

    primary_root = Path(args.primary).expanduser()
    secondary_root = Path(args.secondary).expanduser()
    if not primary_root.exists():
        print(f"Primary root does not exist: {primary_root}")
        return 2
    if not secondary_root.exists():
        print(f"Secondary root does not exist: {secondary_root}")
        return 2
    cleanup_duplicates(primary_root, secondary_root, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
