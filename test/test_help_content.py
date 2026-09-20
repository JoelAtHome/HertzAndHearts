"""Tests for contextual Help registry and User Guide path resolution."""

from __future__ import annotations

from hnh.help_content import (
    HELP_TOPICS,
    get_topic,
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
