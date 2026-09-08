from __future__ import annotations

import unittest

from hnh.sensor import (
    PHONE_BRIDGE_CLIENT_APP,
    build_phone_bridge_client_info,
    parse_phone_bridge_discover_reply,
)


class PhoneBridgeClientInfoTests(unittest.TestCase):
    def test_build_client_info_includes_protocol_identity(self):
        payload = build_phone_bridge_client_info(
            pc_user="Sandy",
            pc_host="desk-pc",
            client_version="1.2.3",
        )
        self.assertEqual(payload["type"], "client_info")
        self.assertEqual(payload["app"], "HertzAndHearts")
        self.assertEqual(payload["client_app"], PHONE_BRIDGE_CLIENT_APP)
        self.assertEqual(payload["client_app"], "hertz_and_hearts")
        self.assertEqual(payload["pc_user"], "Sandy")
        self.assertEqual(payload["pc_host"], "desk-pc")
        self.assertEqual(payload["client_version"], "1.2.3")

    def test_build_client_info_defaults_blank_user(self):
        payload = build_phone_bridge_client_info(pc_user="  ", client_version="")
        self.assertEqual(payload["pc_user"], "Admin")
        self.assertNotIn("client_version", payload)


class PhoneBridgeDiscoverParseTests(unittest.TestCase):
    def test_accepts_role_without_fixed_app_name(self):
        row = parse_phone_bridge_discover_reply(
            {
                "role": "phone_bridge",
                "hostname": "Pixel 7",
                "port": 8765,
                "app": "SomeOtherBridgeName",
            },
            ip="192.168.1.42",
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["ip"], "192.168.1.42")
        self.assertEqual(row["hostname"], "Pixel 7")
        self.assertEqual(row["port"], 8765)
        self.assertEqual(row["app"], "SomeOtherBridgeName")

    def test_stashes_additive_protocol_fields(self):
        row = parse_phone_bridge_discover_reply(
            {
                "app": "PolarH10Bridge",
                "role": "phone_bridge",
                "hostname": "Pixel 7",
                "port": 9000,
                "protocol": "phone_bridge_ndjson_v1",
                "bridge_version": "1.0.0-beta.2",
                "features": ["stream", "record", "rmssd_snapshot", ""],
            },
            ip="10.0.0.8",
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["protocol"], "phone_bridge_ndjson_v1")
        self.assertEqual(row["bridge_version"], "1.0.0-beta.2")
        self.assertEqual(row["features"], ["stream", "record", "rmssd_snapshot"])
        self.assertEqual(row["port"], 9000)

    def test_rejects_non_bridge_role(self):
        self.assertIsNone(
            parse_phone_bridge_discover_reply(
                {"app": "PolarH10Bridge", "role": "sensor", "port": 8765},
                ip="192.168.1.1",
            )
        )

    def test_invalid_port_falls_back_to_default(self):
        row = parse_phone_bridge_discover_reply(
            {"role": "phone_bridge", "port": "nope"},
            ip="192.168.1.9",
            default_port=8765,
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["port"], 8765)


if __name__ == "__main__":
    unittest.main()
