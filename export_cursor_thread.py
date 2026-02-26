#!/usr/bin/env python3
"""Export Cursor agent transcripts to Markdown for re-use in new threads."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


UUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a Cursor conversation transcript into Markdown."
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Path to a specific transcript JSONL file.",
    )
    parser.add_argument(
        "--transcript-id",
        help="Transcript UUID (without .jsonl) to resolve under transcripts root.",
    )
    parser.add_argument(
        "--transcripts-root",
        type=Path,
        help="Explicit path to an agent-transcripts directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("conversation_export.md"),
        help="Output markdown path (default: conversation_export.md).",
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy the resulting Markdown to clipboard (Windows).",
    )
    return parser.parse_args()


def discover_transcripts_root(explicit_root: Path | None) -> Path:
    if explicit_root:
        if not explicit_root.exists():
            raise FileNotFoundError(f"Transcripts root not found: {explicit_root}")
        return explicit_root

    user_profile = Path(os.environ.get("USERPROFILE", ""))
    cursor_projects = user_profile / ".cursor" / "projects"
    if not cursor_projects.exists():
        raise FileNotFoundError(f"Cursor projects directory not found: {cursor_projects}")

    candidates = [p for p in cursor_projects.glob("*/agent-transcripts") if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(
            f"No agent transcript directories found under: {cursor_projects}"
        )

    # Pick the most recently modified agent-transcripts directory.
    return max(candidates, key=lambda p: p.stat().st_mtime)


def resolve_input_file(args: argparse.Namespace) -> Path:
    if args.input:
        transcript_path = args.input
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
        return transcript_path

    root = discover_transcripts_root(args.transcripts_root)

    if args.transcript_id:
        transcript_id = args.transcript_id.strip()
        if not UUID_PATTERN.match(transcript_id):
            raise ValueError("Expected --transcript-id to be a UUID.")
        transcript_path = root / transcript_id / f"{transcript_id}.jsonl"
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
        return transcript_path

    transcript_files = [
        p
        for p in root.glob("*/*.jsonl")
        if p.parent.name == p.stem
    ]
    if not transcript_files:
        raise FileNotFoundError(f"No transcript files found in: {root}")

    # Most recently modified top-level transcript.
    return max(transcript_files, key=lambda p: p.stat().st_mtime)


def iter_text_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            yield value["text"]
        for child in value.values():
            yield from iter_text_values(child)
    elif isinstance(value, list):
        for item in value:
            yield from iter_text_values(item)


def clean_user_wrapper(text: str) -> str:
    # Strip the transport wrapper while preserving content.
    cleaned = re.sub(r"</?user_query>", "", text, flags=re.IGNORECASE).strip()
    return cleaned


def parse_transcript(transcript_path: Path) -> list[tuple[str, str]]:
    messages: list[tuple[str, str]] = []
    with transcript_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            role = str(payload.get("role", "unknown")).strip().lower()
            if role not in {"user", "assistant"}:
                continue

            message = payload.get("message", {})
            text_chunks = [chunk.strip() for chunk in iter_text_values(message) if chunk.strip()]
            if not text_chunks:
                continue

            text = "\n\n".join(text_chunks)
            if role == "user":
                text = clean_user_wrapper(text)
            messages.append((role, text))
    return messages


def to_markdown(messages: list[tuple[str, str]], source_file: Path) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Conversation Export",
        "",
        f"- Exported: {now}",
        f"- Source: `{source_file}`",
        "",
    ]
    for role, text in messages:
        heading = "User" if role == "user" else "Assistant"
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(text.rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def copy_to_clipboard(text: str) -> None:
    subprocess.run("clip", input=text, text=True, shell=True, check=True)


def main() -> int:
    args = parse_args()
    transcript_path = resolve_input_file(args)
    messages = parse_transcript(transcript_path)

    if not messages:
        raise RuntimeError(f"No user/assistant messages found in: {transcript_path}")

    markdown = to_markdown(messages, transcript_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")

    if args.copy:
        copy_to_clipboard(markdown)

    print(f"Exported {len(messages)} messages to: {args.output}")
    if args.copy:
        print("Copied Markdown to clipboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
