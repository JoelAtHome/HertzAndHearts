"""Contextual Help topics (F1 / i buttons) and User Guide viewer.

Content is a typed registry rendered to HTML. Keep topics short: purpose,
how-to-use, guardrails, shortcuts, next action — not a second product surface.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from hnh.config import ECG_QTc_UNCERTAINTY_PCT

HelpBlockKind = Literal["paragraph", "list", "note"]


@dataclass(frozen=True)
class HelpBlock:
    kind: HelpBlockKind
    """Section heading shown in bold (optional for bare paragraphs)."""
    title: str | None = None
    """Body text for paragraph/note blocks (may include light HTML)."""
    text: str | None = None
    """Bullet items for list blocks (may include light HTML)."""
    items: tuple[str, ...] = ()


@dataclass(frozen=True)
class HelpTopic:
    id: str
    title: str
    blocks: tuple[HelpBlock, ...]


def _escape_plain(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _render_block(block: HelpBlock) -> str:
    parts: list[str] = []
    if block.title:
        parts.append(f"<p><b>{block.title}</b></p>")
    if block.kind == "list":
        items = "".join(f"<li>{item}</li>" for item in block.items)
        parts.append(f"<ul>{items}</ul>")
    elif block.kind == "note":
        body = block.text or ""
        parts.append(
            f'<p style="color:#555;"><i>Note:</i> {body}</p>'
        )
    else:
        body = block.text or ""
        parts.append(f"<p>{body}</p>")
    return "".join(parts)


def topic_html(topic: HelpTopic) -> str:
    body = "".join(_render_block(b) for b in topic.blocks)
    return f"<h3 style='margin-top:0;'>{_escape_plain(topic.title)}</h3>{body}"


HELP_TOPICS: dict[str, HelpTopic] = {
    "main": HelpTopic(
        id="main",
        title="Quick Start Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text=(
                    "Live monitoring dashboard: connect the phone bridge, run a "
                    "session, and watch HR / RMSSD (and optional SDNN) while you work."
                ),
            ),
            HelpBlock(
                kind="list",
                title="How to use",
                items=(
                    "<b>Scan / Connect</b>: find the Android Phone Bridge on Wi‑Fi, then Connect.",
                    "<b>Start New</b>: begin recording for the active profile.",
                    "<b>Stop / Stop &amp; Save</b>: end the session; Save finalizes reports.",
                    "<b>ECG / QTc / Poincare / PSD</b>: open popup analysis windows.",
                    "<b>More</b>: History, Trends, Profiles, Import, Saved recordings, Help (incl. About).",
                    "<b>Settings (gear)</b>: preferences and data folder (also Ctrl+,).",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Research / educational use only — not for diagnosis or treatment.",
                    "Poor strap contact, motion, or dropouts can distort HRV metrics.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=(
                    "<b>F1</b>: this Quick Guide.",
                ),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Connect the phone bridge, then Start New when ready to record.",
            ),
        ),
    ),
    "ecg": HelpTopic(
        id="ecg",
        title="ECG Monitor — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text="Live single-lead ECG waveform for signal quality and interval measurement.",
            ),
            HelpBlock(
                kind="list",
                title="How to use",
                items=(
                    "<b>Freeze</b>: pause the stream to place cursors and measure Δt.",
                    "<b>Cursors A / B</b>: drag lines or nudge with keyboard when frozen.",
                    "<b>Log Δt</b>: save the interval as a session annotation and attach a "
                    "plot snippet to the report (up to 5 per session). Optional type label "
                    "(R-R / QRS / QT / …) — leave as — if you only need duration.",
                    "<b>Zoom / Relock</b>: inspect a window of time; Relock follows the main plot.",
                    "<b>Capture Image</b>: snapshot the plot into the session folder.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Morphology interpretation requires clinical judgment; this is not diagnostic.",
                    "Single-lead consumer straps are sensitive to motion and contact quality.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=(
                    "<b>F1</b>: this Quick Guide.",
                    "<b>A / B</b> (when frozen): select active cursor.",
                    "<b>← / →</b> (when frozen): nudge active cursor (Shift = larger step).",
                ),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text=(
                    "Freeze a clean segment, place A/B on landmarks, then Log Δt if needed. "
                    "Use <b>Waveform Primer…</b> below for P/QRS/T landmarks (non-diagnostic)."
                ),
            ),
        ),
    ),
    "qtc": HelpTopic(
        id="qtc",
        title="QTc Trend — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text="Rolling QTc trend with uncertainty context from the live ECG stream.",
            ),
            HelpBlock(
                kind="list",
                title="How to read / use",
                items=(
                    "<b>Rolling median QTc</b>: smoothed central QTc estimate.",
                    "<b>Uncertainty band (IQR)</b>: wider band means less confidence.",
                    "<b>Dashed segments</b>: lower signal quality periods.",
                    "<b>Shaded area above 470 ms</b>: elevated reference zone.",
                    f"<b>Measurement uncertainty</b>: QTc from single-lead ECG may vary by "
                    f"approximately ±{ECG_QTc_UNCERTAINTY_PCT}% from reference.",
                    "<b>Freeze / Zoom / Relock</b>: inspect timeline; Relock follows the main plot.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Trend context only; requires clinical review.",
                    "Research use only — not for diagnosis or treatment.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=("<b>F1</b>: this Quick Guide.",),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Watch quality markers; Freeze to inspect any elevated or noisy stretches.",
            ),
        ),
    ),
    "poincare": HelpTopic(
        id="poincare",
        title="Poincare Plot — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text=(
                    "Each dot is one heartbeat interval compared with the next: "
                    "RR(n) on the x-axis and RR(n+1) on the y-axis."
                ),
            ),
            HelpBlock(
                kind="list",
                title="How to read / use",
                items=(
                    "<b>Tight cluster</b>: usually steadier rhythm and cleaner signal.",
                    "<b>Wider cloud</b>: more variability — may be physiologic or noise/artifact.",
                    "<b>SD1</b>: short-term variability.",
                    "<b>SD2</b>: longer-term variability.",
                    "<b>SD1/SD2</b>: balance of short vs longer-term variability (SD = standard deviation).",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Motion artifact, poor strap contact, or dropouts can distort the plot.",
                    "Research / educational context only.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=("<b>F1</b>: this Quick Guide.",),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Compare shape before vs after a breathing or stillness change in the same session.",
            ),
        ),
    ),
    "psd": HelpTopic(
        id="psd",
        title="PSD & Vagal Resonance — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text=(
                    "Power Spectral Density (PSD) of heart rate variability from the "
                    "interpolated R‑R interval stream (Welch / FFT-based)."
                ),
            ),
            HelpBlock(
                kind="list",
                title="How to read / use",
                items=(
                    "<b>Vagal Resonance (~0.1 Hz)</b>: shaded band at 0.07 - 0.13 Hz "
                    "(~6 breaths/min). A narrow, high-amplitude peak often tracks coherent breathing.",
                    "<b>Timing</b>: plot uses roughly the last minute of beats — expect 1 - 2 minutes "
                    "of steady breathing before the peak shifts or stabilizes.",
                    "<b>Interaction</b>: drag to pan; mouse wheel or +/− to zoom; Reset restores 0 - 0.5 Hz.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Contributors include breathing consistency, stillness, electrode contact, "
                    "and physiological state (stress, caffeine, etc.).",
                    "Research / educational context only — not a clinical diagnosis.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=("<b>F1</b>: this Quick Guide.",),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Settle into a steady breathing rate, wait a minute or two, then read the peak location.",
            ),
        ),
    ),
    "trends": HelpTopic(
        id="trends",
        title="Session Trends — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text="Review saved-session averages over time, compare sessions, and explore tag associations.",
            ),
            HelpBlock(
                kind="list",
                title="How to use",
                items=(
                    "<b>Trend Plots</b>: long-term HR / RMSSD / SDNN / QTc averages; pan and zoom axes.",
                    "<b>RMSSD recovery zones</b>: personal green/amber/red bands vs your recent baseline "
                    "(see Why these zones?).",
                    "<b>Compare</b>: side-by-side sessions with deltas.",
                    "<b>Tag Insights</b>: exploratory links between annotations and metric shifts "
                    "(association, not causation).",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Zones and insights are personal research cues — not population norms or diagnosis.",
                    "Signal quality and protocol consistency (e.g. morning baseline) affect comparability.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=("<b>F1</b>: this Quick Guide.",),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Pick a profile, scan Trend Plots, then use Compare when you need session-to-session deltas.",
            ),
        ),
    ),
    "history": HelpTopic(
        id="history",
        title="Session History & Replay — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text="Browse past sessions for the active profile and replay HR / RMSSD / ECG timelines. "
                "Open from More → Session History… or More → Session Replay… (same window, matching tab).",
            ),
            HelpBlock(
                kind="list",
                title="How to use",
                items=(
                    "<b>History tab</b>: list sessions; generate reports; copy folder/CSV paths; "
                    "hide/unhide; delete selected (confirm → history + folder); "
                    "<b>Replay selected</b> jumps to Replay with that session loaded.",
                    "<b>Replay tab</b>: load a session, scrub the timeline, zoom/pan time "
                    "(shared across plots; Fit time resets), and jump to annotations.",
                    "Wheel-zoom keeps Replay plots time-aligned.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Abandoned or incomplete sessions may lack reports until you Generate report.",
                    "Hidden sessions stay on disk until you delete them or purge abandoned ones.",
                    "Delete selected removes the folder permanently — prefer Hide when unsure.",
                    "The session currently recording cannot be deleted from History.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=("<b>F1</b>: this Quick Guide.",),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Select a session in History, or switch to Replay to scrub the timeline.",
            ),
        ),
    ),
    "settings": HelpTopic(
        id="settings",
        title="Settings — Quick Guide",
        blocks=(
            HelpBlock(
                kind="paragraph",
                title="Purpose",
                text="Preferences for data location, plotting, and advanced engineering options.",
            ),
            HelpBlock(
                kind="list",
                title="How to use",
                items=(
                    "<b>Data Folder</b>: active root for profiles, session index, and diagnostics.",
                    "<b>Move Data to Recommended Location…</b>: use when dual-boot or legacy paths "
                    "split your sessions; restart after migrating.",
                    "Hover any setting label for a tooltip (includes factory default).",
                    "<b>Show Advanced</b>: reveals engineering controls — leave off for day-to-day use.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Guardrails",
                items=(
                    "Advanced users can override the data root with the <code>HNH_DATA_DIR</code> environment variable.",
                    "Changing advanced timing/filter settings can alter metrics — prefer defaults unless you know why.",
                ),
            ),
            HelpBlock(
                kind="list",
                title="Keyboard shortcuts",
                items=("<b>F1</b>: this Quick Guide.",),
            ),
            HelpBlock(
                kind="paragraph",
                title="Next action",
                text="Confirm Data Folder is where you expect, then Save &amp; Close.",
            ),
        ),
    ),
}


def get_topic(topic_id: str) -> HelpTopic | None:
    return HELP_TOPICS.get(str(topic_id or "").strip())


def _ensure_linux_window_decorations(widget: QWidget) -> None:
    if platform.system() != "Linux":
        return
    flags = widget.windowFlags()
    flags |= (
        Qt.WindowType.Dialog
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowSystemMenuHint
        | Qt.WindowType.WindowCloseButtonHint
    )
    flags &= ~Qt.WindowType.FramelessWindowHint
    widget.setWindowFlags(flags)


class HelpTopicDialog(QDialog):
    """Scrollable Quick Guide dialog for one help topic."""

    def __init__(self, topic: HelpTopic, parent: QWidget | None = None):
        super().__init__(parent)
        self._topic = topic
        self.setWindowTitle(topic.title)
        self.setMinimumSize(560, 420)
        self.setModal(True)
        _ensure_linux_window_decorations(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(False)
        browser.setReadOnly(True)
        browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        browser.setHtml(topic_html(topic))
        browser.setStyleSheet(
            "QTextBrowser { background: white; color: #333; font-size: 13px; padding: 4px; }"
        )
        root.addWidget(browser, stretch=1)

        btn_row = QHBoxLayout()
        if topic.id == "ecg":
            primer_btn = QPushButton("Waveform Primer…")
            primer_btn.setToolTip(
                "Open a short P/QRS/T reference (research/educational; not diagnostic)."
            )
            primer_btn.clicked.connect(lambda: show_waveform_primer(self))
            btn_row.addWidget(primer_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)


class MarkdownDocDialog(QDialog):
    """In-app viewer for a packaged markdown doc."""

    def __init__(
        self,
        title: str,
        markdown_text: str,
        parent: QWidget | None = None,
        *,
        base_dir: Path | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 560)
        self.setModal(True)
        _ensure_linux_window_decorations(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        browser = QTextBrowser(self)
        browser.setOpenExternalLinks(True)
        browser.setReadOnly(True)
        browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        if base_dir is not None:
            browser.document().setBaseUrl(
                QUrl.fromLocalFile(str(base_dir.resolve()) + "/")
            )
        browser.setMarkdown(markdown_text)
        browser.setStyleSheet(
            "QTextBrowser { background: white; color: #333; font-size: 14px; padding: 4px; }"
        )
        root.addWidget(browser, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)


# Back-compat alias used by older call sites / tests.
UserGuideDialog = MarkdownDocDialog


def show_help(parent: QWidget | None, topic_id: str) -> None:
    topic = get_topic(topic_id)
    if topic is None:
        QMessageBox.information(
            parent,
            "Help",
            "No help is available for this screen yet.",
        )
        return
    HelpTopicDialog(topic, parent).exec()


def install_f1_help(widget: QWidget, topic_id: str) -> QShortcut:
    """Bind Window-scoped F1 on *widget* to show the given help topic."""
    shortcut = QShortcut(QKeySequence(Qt.Key.Key_F1), widget)
    shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
    shortcut.activated.connect(lambda: show_help(widget, topic_id))
    # Keep a strong ref so the shortcut is not garbage-collected.
    bucket = getattr(widget, "_hnh_f1_help_shortcuts", None)
    if bucket is None:
        bucket = []
        setattr(widget, "_hnh_f1_help_shortcuts", bucket)
    bucket.append(shortcut)
    return shortcut


def resolve_docs_path(*relative_parts: str) -> Path | None:
    """Locate a docs file from the source tree or frozen bundle."""
    rel = Path(*relative_parts)
    candidates: list[Path] = []
    repo_root = Path(__file__).resolve().parents[1]
    candidates.append(repo_root / rel)
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", repo_root))
        candidates.append(meipass / rel)
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / rel)
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_file():
            return resolved
    return None


def resolve_user_guide_path() -> Path | None:
    """Locate packaged or source-tree User Guide markdown."""
    return resolve_docs_path("docs", "USER_GUIDE.md")


def show_markdown_doc(
    parent: QWidget | None,
    *,
    title: str,
    relative_parts: tuple[str, ...],
    missing_label: str,
    prepend: str = "",
) -> None:
    path = resolve_docs_path(*relative_parts)
    if path is None:
        rel = "/".join(relative_parts)
        QMessageBox.warning(
            parent,
            missing_label,
            f"Could not find {missing_label} ({rel}).",
        )
        return
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        QMessageBox.warning(
            parent,
            missing_label,
            f"Could not read {missing_label}:\n{exc}",
        )
        return
    if not text:
        QMessageBox.warning(parent, missing_label, f"{missing_label} file is empty.")
        return
    if prepend:
        text = f"{prepend.rstrip()}\n\n{text}"
    MarkdownDocDialog(title, text, parent, base_dir=path.parent).exec()


def show_user_guide(parent: QWidget | None = None) -> None:
    show_markdown_doc(
        parent,
        title="Hertz & Hearts — User Guide",
        relative_parts=("docs", "USER_GUIDE.md"),
        missing_label="User Guide",
    )


def show_troubleshooting(parent: QWidget | None = None) -> None:
    show_markdown_doc(
        parent,
        title="Hertz & Hearts — Troubleshooting",
        relative_parts=("docs", "troubleshooting.md"),
        missing_label="Troubleshooting",
    )


_WAVEFORM_PRIMER_NOTE = (
    "> **Research / educational reference only.** Waveform morphology "
    "interpretation requires clinician judgment. This primer is not a "
    "diagnostic tool.\n"
)


def show_waveform_primer(parent: QWidget | None = None) -> None:
    show_markdown_doc(
        parent,
        title="Hertz & Hearts — ECG Waveform Primer",
        relative_parts=("docs", "part-i-qrs-waveform-fundamentals.md"),
        missing_label="Waveform Primer",
        prepend=_WAVEFORM_PRIMER_NOTE,
    )
