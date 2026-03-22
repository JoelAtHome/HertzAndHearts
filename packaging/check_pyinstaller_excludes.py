#!/usr/bin/env python3
"""
Fail if Hertz-and-Hearts.spec uses disallowed PyInstaller Analysis(excludes=...).

Aggressive stdlib excludes often break frozen builds (e.g. email, xml, http).
Allowlist is intentionally tiny; extend only after auditing imports + deps.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SPEC = Path(__file__).resolve().parent.parent / "Hertz-and-Hearts.spec"
# Only safe, deliberate excludes. Qt app does not need tkinter.
ALLOWED_EXCLUDES = frozenset({"tkinter"})


def _excludes_list_literal(text: str) -> list[str]:
    key = "excludes="
    i = text.find(key)
    if i < 0:
        raise ValueError("Could not find excludes= in spec")

    j = text.find("[", i)
    if j < 0:
        raise ValueError("excludes= is not followed by a [ list")

    depth = 0
    start = j
    for k in range(j, len(text)):
        c = text[k]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                inner = text[start + 1 : k]
                break
    else:
        raise ValueError("Unclosed excludes=[ ... ]")

    lines: list[str] = []
    for line in inner.splitlines():
        if "#" in line:
            line = line[: line.index("#")]
        lines.append(line)
    inner_clean = "\n".join(lines).strip()
    if not inner_clean:
        return []

    try:
        value = ast.literal_eval("[" + inner_clean + "]")
    except (SyntaxError, ValueError) as e:
        raise ValueError(f"Could not parse excludes list: {e}") from e

    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise ValueError("excludes must be a list of strings")
    return value


def main() -> int:
    text = SPEC.read_text(encoding="utf-8")
    try:
        excludes = _excludes_list_literal(text)
    except ValueError as e:
        print(f"check_pyinstaller_excludes: {e}", file=sys.stderr)
        return 1

    found = frozenset(excludes)
    if not found.issubset(ALLOWED_EXCLUDES):
        bad = sorted(found - ALLOWED_EXCLUDES)
        print(
            "check_pyinstaller_excludes: disallowed entries in Analysis(excludes=...): "
            f"{bad!r}\n"
            f"  Allowlist: {sorted(ALLOWED_EXCLUDES)!r}\n"
            "  Auditing stdlib imports before adding excludes; see packaging/check_pyinstaller_excludes.py.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
