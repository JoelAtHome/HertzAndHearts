"""Tests for contextual Help registry and packaged markdown docs."""

from __future__ import annotations

from hnh.help_content import (
    HELP_TOPICS,
    get_topic,
    resolve_docs_path,
    resolve_user_guide_path,
    topic_html,
)


EXPECTED_TOPIC_IDS = (
    "main",
    "ecg",
    "qtc",
    "poincare",
    "psd",
    "trends",
    "history",
    "settings",
)


def test_help_topics_cover_major_screens():
    assert set(EXPECTED_TOPIC_IDS) <= set(HELP_TOPICS)
    for topic_id in EXPECTED_TOPIC_IDS:
        topic = get_topic(topic_id)
        assert topic is not None
        assert topic.id == topic_id
        assert topic.title
        assert topic.blocks
        html = topic_html(topic)
        assert "<h3" in html
        assert topic.title.replace("&", "&amp;") in html or "Quick" in html
        assert "<ul>" in html or "<p>" in html
    assert get_topic("main").title == "Quick Start Guide"
    assert "Waveform Primer" in topic_html(get_topic("ecg"))


def test_get_topic_unknown_returns_none():
    assert get_topic("no-such-topic") is None
    assert get_topic("") is None


def test_resolve_user_guide_path_from_source_tree():
    path = resolve_user_guide_path()
    assert path is not None
    assert path.name == "USER_GUIDE.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "User Guide" in text
    assert "Connect a Sensor" in text


def test_help_docs_avoid_bluetooth_wording():
    for rel in (
        ("docs", "USER_GUIDE.md"),
        ("docs", "troubleshooting.md"),
    ):
        path = resolve_docs_path(*rel)
        assert path is not None
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "bluetooth" not in lower
        assert " ble" not in lower
        assert not lower.startswith("ble")
        assert "pc ble" not in lower
    for topic in HELP_TOPICS.values():
        blob = topic_html(topic).lower()
        assert "bluetooth" not in blob
        assert " ble" not in blob
        assert "pc ble" not in blob


def test_resolve_troubleshooting_and_waveform_primer():
    trouble = resolve_docs_path("docs", "troubleshooting.md")
    assert trouble is not None and trouble.is_file()
    assert "Phone Bridge" in trouble.read_text(encoding="utf-8")

    primer = resolve_docs_path("docs", "part-i-qrs-waveform-fundamentals.md")
    assert primer is not None and primer.is_file()
    assert "QRS" in primer.read_text(encoding="utf-8")
