"""PyInstaller runtime hook for python-docx template files.

Frozen builds keep docx Python modules in the archive, so ``docx/parts`` is
not a real directory. Linux then returns ENOENT for
``docx/parts/../templates/default-footer.xml`` even when that XML file is
present. Normalize the path before opening it.
"""

from __future__ import annotations

import os


def _read_docx_template(module_file: str, filename: str) -> bytes:
    base = os.path.dirname(os.path.abspath(module_file))
    path = os.path.normpath(os.path.join(base, "..", "templates", filename))
    with open(path, "rb") as handle:
        return handle.read()


def _install() -> None:
    try:
        from docx.parts import comments, hdrftr, settings, styles
    except Exception:
        return

    hdrftr.FooterPart._default_footer_xml = classmethod(
        lambda cls: _read_docx_template(hdrftr.__file__, "default-footer.xml")
    )
    hdrftr.HeaderPart._default_header_xml = classmethod(
        lambda cls: _read_docx_template(hdrftr.__file__, "default-header.xml")
    )
    comments.CommentsPart._default_comments_xml = classmethod(
        lambda cls: _read_docx_template(comments.__file__, "default-comments.xml")
    )
    settings.SettingsPart._default_settings_xml = classmethod(
        lambda cls: _read_docx_template(settings.__file__, "default-settings.xml")
    )
    styles.StylesPart._default_styles_xml = classmethod(
        lambda cls: _read_docx_template(styles.__file__, "default-styles.xml")
    )


_install()
