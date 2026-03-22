"""
Export cardiac theory Word documents to Markdown in this folder.

Run from repo root:
  python docs/cardiac_md_export.py

Sources (QRS prefers local copy under docs/cardiac-source/):
  - QRS intro: docs/cardiac-source/... (fallback: OneDrive path in QRS_DOCX_FALLBACK)
  - HRV / LF-HF: project root edited .docx

Embedded images in the QRS document are extracted to docs/assets/cardiac-qrs/ and
linked from Markdown. If extraction fails, keep using the Word originals as truth.
"""

from __future__ import annotations

import datetime as _dt
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

# Paths
DOCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOCS_DIR.parent

QRS_DOCX_LOCAL = DOCS_DIR / "cardiac-source" / "Intro to QRS Cardiac Waveform rev 15MAR2026 - Reorganized.docx"
QRS_DOCX_FALLBACK = Path(
    r"C:\Users\joelb\OneDrive\Documents\Health + Medical + Dental\Cardiac (heart) Theory"
    r"\Intro to QRS Cardiac Waveform rev 15MAR2026 - Reorganized.docx"
)
HRV_DOCX = REPO_ROOT / "edited-Cardiac_Vagal Signals_ LF and HF.docx"

ASSETS_QRS_DIR = DOCS_DIR / "assets" / "cardiac-qrs"
MD_IMAGE_PREFIX = "assets/cardiac-qrs"

OUT_COMPENDIUM = DOCS_DIR / "cardiac-compendium.md"
OUT_PART_I = DOCS_DIR / "part-i-qrs-waveform-fundamentals.md"
OUT_PART_II = DOCS_DIR / "part-ii-hrv-autonomic-metrics.md"

R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def resolve_qrs_docx() -> Path:
    if QRS_DOCX_LOCAL.is_file():
        return QRS_DOCX_LOCAL
    if QRS_DOCX_FALLBACK.is_file():
        return QRS_DOCX_FALLBACK
    raise FileNotFoundError(
        f"Missing QRS source. Place file at:\n  {QRS_DOCX_LOCAL}\n"
        f"or restore:\n  {QRS_DOCX_FALLBACK}"
    )


def has_omath(paragraph: Paragraph) -> bool:
    for _ in paragraph._p.iter(qn("m:oMath")):
        return True
    return False


def escape_md(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def styled_text_to_md(text: str, style: str) -> list[str]:
    """Convert non-empty paragraph text to markdown lines (no equations)."""
    raw = text or ""
    text_stripped = escape_md(raw).strip()
    if not text_stripped:
        return []

    text_out = escape_md(raw).rstrip()

    if style.startswith("Heading 1"):
        return [f"# {text_out.strip()}"]
    if style.startswith("Heading 2"):
        return [f"## {text_out.strip()}"]
    if style.startswith("Heading 3"):
        return [f"### {text_out.strip()}"]
    if style == "Caption":
        return [f"*{text_out.strip()}*"]
    if style in ("List Bullet", "List Paragraph"):
        line = text_out.strip()
        if line.startswith("- "):
            return [line]
        if line.startswith("• "):
            return [f"- {line[2:].strip()}"]
        return [f"- {line}"]
    return [text_out.strip()]


def paragraph_to_md(
    p: Paragraph,
    omath_index: list[int],
) -> list[str]:
    """Return markdown lines for one paragraph (may be empty)."""
    style = (p.style and p.style.name) or "Normal"
    raw = p.text or ""

    if has_omath(p):
        idx = omath_index[0]
        omath_index[0] += 1
        if idx == 0:
            return [
                "$$",
                "P_{\\mathrm{HF}} = \\int_{0.15}^{0.40} S(f) \\, df",
                "$$",
            ]
        return [
            "$$",
            "\\mathrm{nHF} = \\frac{\\mathrm{HF}}{\\text{Total Power} - \\mathrm{VLF}} \\times 100",
            "$$",
        ]

    if not raw.strip():
        return []

    return styled_text_to_md(raw, style)


def load_document_rels(z: zipfile.ZipFile) -> dict[str, str]:
    root = ET.fromstring(z.read("word/_rels/document.xml.rels"))
    rels: dict[str, str] = {}
    for rel in root:
        if rel.tag.endswith("Relationship"):
            rid = rel.get("Id")
            target = rel.get("Target")
            if rid and target:
                rels[rid] = target
    return rels


class QrsImageExtractor:
    """Pull embedded images from the QRS .docx into docs/assets/cardiac-qrs/."""

    def __init__(self, docx_path: Path) -> None:
        self.docx_path = docx_path
        self._zip = zipfile.ZipFile(docx_path, "r")
        self._rels = load_document_rels(self._zip)
        self._counter = 0
        ASSETS_QRS_DIR.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self) -> QrsImageExtractor:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def reset_output_dir(self) -> None:
        if ASSETS_QRS_DIR.is_dir():
            for p in ASSETS_QRS_DIR.iterdir():
                if p.is_file():
                    p.unlink()

    def save_by_rid(self, rid: str) -> str:
        target = self._rels.get(rid)
        if not target:
            return ""
        internal = "word/" + target.lstrip("/").replace("\\", "/")
        try:
            data = self._zip.read(internal)
        except KeyError:
            return ""
        ext = Path(target).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"):
            ext = ".bin"
        self._counter += 1
        name = f"fig-{self._counter:03d}{ext}"
        out_path = ASSETS_QRS_DIR / name
        out_path.write_bytes(data)
        return f"{MD_IMAGE_PREFIX}/{name}"


def iter_r_elements(p_el: ET.Element) -> list[ET.Element]:
    """Ordered w:r nodes inside a paragraph (including inside w:hyperlink)."""
    runs: list[ET.Element] = []
    for child in p_el:
        tag = child.tag
        if tag == qn("w:r"):
            runs.append(child)
        elif tag == qn("w:hyperlink"):
            for sub in child:
                if sub.tag == qn("w:r"):
                    runs.append(sub)
    return runs


def embed_ids_in_run(r_el: ET.Element) -> list[str]:
    ids: list[str] = []
    for el in r_el.iter():
        tag = el.tag
        if tag.endswith("}blip"):
            rid = el.get(R_EMBED) or el.get("embed")
            if rid:
                ids.append(rid)
        elif tag.endswith("}imagedata"):
            rid = el.get(R_ID) or el.get("id")
            if rid:
                ids.append(rid)
    return ids


def iter_text_and_images_in_order(p_el: ET.Element) -> list[tuple[str, str]]:
    """
    Ordered parts: ('text', str) and ('image', rId).
    Preserves run order within the paragraph.
    """
    parts: list[tuple[str, str]] = []
    for r in iter_r_elements(p_el):
        texts: list[str] = []
        for t in r.findall(qn("w:t")):
            if t.text:
                texts.append(t.text)
        chunk = "".join(texts)
        if chunk:
            parts.append(("text", chunk))
        for rid in embed_ids_in_run(r):
            parts.append(("image", rid))
    return parts


def interleaved_paragraph_md(
    p_el: ET.Element,
    para: Paragraph,
    extractor: QrsImageExtractor,
) -> list[str]:
    style = (para.style and para.style.name) or "Normal"
    lines: list[str] = []
    buf: list[str] = []

    for kind, val in iter_text_and_images_in_order(p_el):
        if kind == "text":
            buf.append(val)
        else:
            if buf:
                merged = "".join(buf)
                buf = []
                lines.extend(styled_text_to_md(merged, style))
            path = extractor.save_by_rid(val)
            if path:
                lines.append(f"![]({path})")
    if buf:
        lines.extend(styled_text_to_md("".join(buf), style))
    return lines


def paragraph_has_images(p_el: ET.Element) -> bool:
    for kind, _ in iter_text_and_images_in_order(p_el):
        if kind == "image":
            return True
    return False


def table_to_md(table: Table) -> list[str]:
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [escape_md(c.text).strip().replace("\n", " ").replace("|", "\\|") for c in row.cells]
        rows.append(cells)
    if not rows:
        return []
    header = rows[0]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    for body_row in rows[1:]:
        padded = body_row + [""] * (len(header) - len(body_row))
        padded = padded[: len(header)]
        lines.append("| " + " | ".join(padded) + " |")
    return lines


def _is_bullet_line(line: str) -> bool:
    return line.startswith("- ")


def _needs_gap_before(prev_line: str | None, new_line: str) -> bool:
    if prev_line is None or prev_line == "":
        return False
    if new_line.startswith("!["):
        return True
    if prev_line.startswith("!["):
        return True
    if new_line.startswith("| "):
        return True
    if prev_line.startswith("| "):
        return True
    if _is_bullet_line(new_line) and _is_bullet_line(prev_line):
        return False
    if _is_bullet_line(new_line) and not _is_bullet_line(prev_line):
        return True
    if not _is_bullet_line(new_line) and _is_bullet_line(prev_line):
        return True
    if new_line.startswith("#") or prev_line.startswith("#"):
        return True
    return True


def document_body_to_md(
    doc: Document,
    omath_counter: list[int] | None = None,
    image_extractor: QrsImageExtractor | None = None,
) -> str:
    if omath_counter is None:
        omath_counter = [0]
    out: list[str] = []
    prev: str | None = None
    in_math = False

    for el in doc.element.body:
        if el.tag == qn("w:p"):
            p = Paragraph(el, doc)

            if has_omath(p):
                chunk_lines = paragraph_to_md(p, omath_counter)
            elif image_extractor and paragraph_has_images(el):
                chunk_lines = interleaved_paragraph_md(el, p, image_extractor)
            else:
                chunk_lines = paragraph_to_md(p, omath_counter)

            for line in chunk_lines:
                if line == "$$":
                    if not in_math:
                        if prev not in (None, ""):
                            out.append("")
                        in_math = True
                    else:
                        in_math = False
                    out.append(line)
                    prev = line
                    continue

                if in_math:
                    out.append(line)
                    prev = line
                    continue

                if _needs_gap_before(prev, line):
                    out.append("")
                out.append(line)
                prev = line

        elif el.tag == qn("w:tbl"):
            t = Table(el, doc)
            tbl_lines = table_to_md(t)
            if tbl_lines:
                if prev not in (None, ""):
                    out.append("")
                out.extend(tbl_lines)
                out.append("")
                prev = ""

    text = "\n".join(out).strip() + "\n"
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def banner(title: str, source: str, generated: str) -> str:
    return (
        f"<!--\n"
        f"  Title: {title}\n"
        f"  Source: {source}\n"
        f"  Generated: {generated}\n"
        f"  Regenerate: python docs/cardiac_md_export.py\n"
        f"-->\n\n"
    )


def ensure_local_qrs_copy() -> None:
    """If no local QRS file yet, copy from OneDrive path when available (one-time seed)."""
    if QRS_DOCX_LOCAL.is_file():
        return
    if QRS_DOCX_FALLBACK.is_file():
        QRS_DOCX_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(QRS_DOCX_FALLBACK, QRS_DOCX_LOCAL)
        except OSError:
            pass


def main() -> None:
    generated = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    ensure_local_qrs_copy()
    qrs_path = resolve_qrs_docx()
    if not HRV_DOCX.is_file():
        raise SystemExit(f"Missing HRV source: {HRV_DOCX}")

    hrv_doc = Document(str(HRV_DOCX))
    part_ii_body = document_body_to_md(hrv_doc)

    with QrsImageExtractor(qrs_path) as extractor:
        extractor.reset_output_dir()
        qrs_doc = Document(str(qrs_path))
        part_i_body = document_body_to_md(qrs_doc, image_extractor=extractor)

    try:
        qrs_source_note = str(qrs_path.relative_to(REPO_ROOT))
    except ValueError:
        qrs_source_note = str(qrs_path)

    part_i = (
        banner(
            "Part I — QRS waveform fundamentals",
            qrs_source_note,
            generated,
        )
        + "> **Figures:** extracted to `docs/assets/cardiac-qrs/` for Markdown. The Word source remains authoritative if anything looks off.\n\n"
        + "## Companion documents\n\n"
        + "- Full combined guide: [cardiac-compendium.md](cardiac-compendium.md)\n"
        + "- Part II (HRV / LF–HF): [part-ii-hrv-autonomic-metrics.md](part-ii-hrv-autonomic-metrics.md)\n\n"
        + "---\n\n"
        + part_i_body
    )

    try:
        hrv_source_note = str(HRV_DOCX.relative_to(REPO_ROOT))
    except ValueError:
        hrv_source_note = str(HRV_DOCX)

    part_ii = (
        banner(
            "Part II — HRV, LF/HF, and autonomic metrics",
            hrv_source_note,
            generated,
        )
        + "## Companion documents\n\n"
        + "- Full combined guide: [cardiac-compendium.md](cardiac-compendium.md)\n"
        + "- Part I (QRS fundamentals): [part-i-qrs-waveform-fundamentals.md](part-i-qrs-waveform-fundamentals.md)\n\n"
        + "---\n\n"
        + part_ii_body
    )

    compendium = (
        banner(
            "Cardiac theory compendium (QRS + HRV)",
            f"{qrs_path.name} + {HRV_DOCX.name}",
            generated,
        )
        + "# Cardiac theory compendium\n\n"
        + "This document merges two companion guides for different uses of cardiac signal understanding:\n\n"
        + "- **Part I** — QRS waveform and ECG morphology fundamentals (ventricular depolarization, single-lead context). "
        + "Figures are embedded from `docs/assets/cardiac-qrs/`; Word sources remain authoritative.\n"
        + "- **Part II** — Heart rate variability (HRV), LF/HF bands, time-domain metrics, and practical monitoring notes.\n\n"
        + "**Standalone copies:** [Part I](part-i-qrs-waveform-fundamentals.md) · "
        + "[Part II](part-ii-hrv-autonomic-metrics.md)\n\n"
        + "---\n\n"
        + "## Part I — QRS waveform fundamentals\n\n"
        + part_i_body
        + "\n\n---\n\n"
        + "## Part II — HRV, LF/HF, and autonomic metrics\n\n"
        + part_ii_body
    )

    OUT_PART_I.write_text(part_i, encoding="utf-8")
    OUT_PART_II.write_text(part_ii, encoding="utf-8")
    OUT_COMPENDIUM.write_text(compendium, encoding="utf-8")

    print("QRS source:", qrs_path)
    print("Wrote:", OUT_PART_I)
    print("Wrote:", OUT_PART_II)
    print("Wrote:", OUT_COMPENDIUM)
    print("Images:", ASSETS_QRS_DIR, "(see fig-*.png/jpeg)")


if __name__ == "__main__":
    main()
