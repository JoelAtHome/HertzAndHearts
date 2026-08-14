from __future__ import annotations

import unittest
from unittest import mock

from packaging.version import Version

import hnh
from hnh import update_check


def _release(tag: str, draft: bool = False) -> dict:
    return {
        "tag_name": tag,
        "draft": draft,
        "html_url": f"https://github.com/JoelAtHome/HertzAndHearts/releases/tag/{tag}",
        "published_at": "2026-08-01T12:00:00Z",
    }


class InstalledVersionTests(unittest.TestCase):
    def test_installed_version_tracks_package_version(self):
        with mock.patch.object(hnh, "__version__", "1.0.0b2"):
            self.assertEqual(update_check.installed_version_string(), "1.0.0b2")
            self.assertEqual(update_check.installed_version(), Version("1.0.0b2"))
            self.assertTrue(update_check.is_version_known())

    def test_beta_tag_style_version_is_coerced(self):
        with mock.patch.object(hnh, "__version__", "1.0.0-beta.2"):
            self.assertEqual(update_check.installed_version(), Version("1.0.0b2"))

    def test_placeholder_version_is_reported_as_unknown(self):
        with mock.patch.object(hnh, "__version__", hnh.UNKNOWN_VERSION):
            self.assertFalse(update_check.is_version_known())


class ReleaseParsingTests(unittest.TestCase):
    def test_tag_variants_parse_to_same_version(self):
        for tag in ("v1.0.0-beta.2", "1.0.0-beta.2", "v1.0.0b2"):
            self.assertEqual(update_check.parse_release_version(tag), Version("1.0.0b2"))

    def test_first_beta_without_suffix(self):
        self.assertEqual(update_check.parse_release_version("v1.0.0-beta"), Version("1.0.0b0"))

    def test_unrecognized_tag_is_ignored(self):
        self.assertIsNone(update_check.parse_release_version("nightly"))

    def test_pick_newest_skips_drafts(self):
        newest = update_check.pick_newest_release(
            [_release("v1.0.0-beta.1"), _release("v1.0.0-beta.3", draft=True)]
        )
        self.assertIsNotNone(newest)
        self.assertEqual(newest.version, Version("1.0.0b1"))


class CheckGithubForUpdateTests(unittest.TestCase):
    def _check(self, installed: str, tags: list[str]) -> update_check.UpdateCheckResult:
        payload = [_release(t) for t in tags]
        with (
            mock.patch.object(hnh, "__version__", installed),
            mock.patch.object(update_check, "fetch_releases_payload", return_value=payload),
        ):
            return update_check.check_github_for_update()

    def test_matching_release_is_not_offered_as_an_upgrade(self):
        result = self._check("1.0.0b2", ["v1.0.0-beta.1", "v1.0.0-beta.2"])
        self.assertEqual(result.outcome, "current")
        self.assertIn("1.0.0-beta.2", result.user_message)

    def test_older_install_sees_newer_release(self):
        result = self._check("1.0.0b1", ["v1.0.0-beta.1", "v1.0.0-beta.2"])
        self.assertEqual(result.outcome, "newer")
        self.assertEqual(result.release.version_display, "1.0.0-beta.2")

    def test_unreleased_local_build_is_current(self):
        result = self._check("1.0.0b3", ["v1.0.0-beta.2"])
        self.assertEqual(result.outcome, "current")

    def test_unknown_version_does_not_claim_an_update(self):
        result = self._check(hnh.UNKNOWN_VERSION, ["v1.0.0-beta.2"])
        self.assertEqual(result.outcome, "unknown_version")

    def test_no_recognizable_releases(self):
        result = self._check("1.0.0b2", ["nightly"])
        self.assertEqual(result.outcome, "no_releases")
        self.assertIsNone(result.release)


if __name__ == "__main__":
    unittest.main()
