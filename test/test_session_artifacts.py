"""Tests for session folder naming / profile path segments."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from hnh.session_artifacts import (
    _slugify,
    canonicalize_disk_profile_label,
    create_session_bundle,
    validate_profile_display_name,
)


class ValidateProfileDisplayNameTests(unittest.TestCase):
    def test_valid_matches_slugify(self):
        ok, reason, suggested = validate_profile_display_name("J. Kobe")
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(suggested, "J. Kobe")

    def test_double_space_invalid_with_suggestion(self):
        ok, reason, suggested = validate_profile_display_name("Alice  Bob")
        self.assertFalse(ok)
        self.assertIn("multiple spaces", reason)
        self.assertEqual(suggested, "Alice Bob")

    def test_invalid_char_in_reason(self):
        ok, reason, suggested = validate_profile_display_name("a/b")
        self.assertFalse(ok)
        self.assertIn("not allowed", reason)
        self.assertEqual(suggested, "a-b")

    def test_empty_invalid(self):
        ok, reason, suggested = validate_profile_display_name("   ")
        self.assertFalse(ok)
        self.assertIn("empty", reason.lower())
        self.assertEqual(suggested, "")


class CanonicalizeDiskProfileLabelTests(unittest.TestCase):
    def test_hyphen_after_period_from_legacy_space_replace(self):
        self.assertEqual(canonicalize_disk_profile_label("J.-Kobe"), "J. Kobe")

    def test_noop_when_no_period_hyphen_pattern(self):
        self.assertEqual(canonicalize_disk_profile_label("J. Kobe"), "J. Kobe")
        self.assertEqual(canonicalize_disk_profile_label("Alice-Bob"), "Alice-Bob")


class SessionArtifactsSlugifyTests(unittest.TestCase):
    def test_slugify_preserves_spaces(self):
        self.assertEqual(_slugify("J. Kobe"), "J. Kobe")
        self.assertEqual(_slugify("  Alice Bob  "), "Alice Bob")

    def test_slugify_strips_windows_trailing_dot_space(self):
        self.assertEqual(_slugify("name. "), "name")
        self.assertEqual(_slugify("name ."), "name")

    def test_slugify_replaces_invalid_chars(self):
        self.assertEqual(_slugify('a<b>c'), "a-b-c")
        self.assertEqual(_slugify('p/q'), "p-q")
        self.assertEqual(_slugify('x:y'), "x-y")

    def test_slugify_rejects_dot_segments(self):
        self.assertEqual(_slugify("."), "Admin")
        self.assertEqual(_slugify(".."), "Admin")

    def test_create_session_bundle_uses_space_in_profile_folder(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = create_session_bundle(root, "J. Kobe", include_profile_subpath=True)
            self.assertEqual(bundle.profile_id, "J. Kobe")
            self.assertIn("J. Kobe", str(bundle.session_dir))
            self.assertNotIn("J.-Kobe", str(bundle.session_dir))


if __name__ == "__main__":
    unittest.main()
