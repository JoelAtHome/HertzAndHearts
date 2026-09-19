from __future__ import annotations

import unittest

from hnh.sensor import (
    PHONE_BRIDGE_CLIENT_APP,
    PhoneBridgeClient,
    SavedHrvAssembly,
    apply_ritual_chunk,
    build_phone_bridge_client_info,
    build_ritual_ack,
    finalize_saved_hrv_package,
    is_feather_profile_status_message,
    parse_phone_bridge_discover_reply,
    parse_phone_bridge_leads_off_status,
    parse_phone_bridge_rmssd,
    parse_phone_bridge_session_summary,
    saved_hrv_assembly_complete,
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


class FeatherProfileStatusMessageTests(unittest.TestCase):
    def test_recognizes_protocol_status_lines(self):
        self.assertTrue(is_feather_profile_status_message("Feather profile confirm: Payton?"))
        self.assertTrue(is_feather_profile_status_message("Feather profile switched: Payton"))
        self.assertTrue(is_feather_profile_status_message("Feather profile kept: Patient 2"))
        self.assertTrue(is_feather_profile_status_message("No Feather profile for Sandy"))

    def test_rejects_unrelated_status(self):
        self.assertFalse(is_feather_profile_status_message("Connected to Phone Bridge."))
        self.assertFalse(is_feather_profile_status_message(""))
        self.assertFalse(is_feather_profile_status_message("Receiving saved HRV…"))


class PhoneBridgeLeadsOffParseTests(unittest.TestCase):
    def test_active_when_both_true(self):
        row = parse_phone_bridge_leads_off_status(
            {
                "type": "status",
                "message": "Feather lead-off",
                "connected": True,
                "use_leads_off": True,
                "leads_off": True,
                "source_device": "FEATHER",
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["active"])
        self.assertTrue(row["use_leads_off"])
        self.assertTrue(row["leads_off"])
        self.assertEqual(row["message"], "Feather lead-off")
        self.assertEqual(row["source_device"], "FEATHER")

    def test_inactive_when_use_false(self):
        row = parse_phone_bridge_leads_off_status(
            {
                "type": "status",
                "use_leads_off": False,
                "leads_off": True,
                "source_device": "FEATHER",
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["active"])
        self.assertFalse(row["use_leads_off"])
        self.assertTrue(row["leads_off"])

    def test_clears_when_leads_reattached(self):
        row = parse_phone_bridge_leads_off_status(
            {
                "type": "status",
                "message": "Feather leads on",
                "use_leads_off": True,
                "leads_off": False,
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertFalse(row["active"])

    def test_ignores_status_without_lod_keys(self):
        self.assertIsNone(
            parse_phone_bridge_leads_off_status(
                {"type": "status", "message": "Phone bridge connected", "battery": 80}
            )
        )
        self.assertIsNone(parse_phone_bridge_leads_off_status({"type": "rr", "rr_ms": 800}))

    def test_coerces_string_bools(self):
        row = parse_phone_bridge_leads_off_status(
            {
                "type": "status",
                "use_leads_off": "true",
                "leads_off": "1",
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["active"])

    def test_missing_use_defaults_true_like_phone(self):
        """Phone FeatherLeadOffParser: absent use_leads_off → true."""
        row = parse_phone_bridge_leads_off_status(
            {"type": "status", "leads_off": True, "source_device": "FEATHER"}
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertTrue(row["use_leads_off"])
        self.assertTrue(row["active"])
        self.assertEqual(row["message"], "Feather lead-off")


class PhoneBridgeClientInfoResendTests(unittest.TestCase):
    def test_set_client_profile_name_resends_when_connected(self):
        client = PhoneBridgeClient()
        sent: list[dict] = []
        client._send_ndjson = lambda payload: sent.append(dict(payload))  # type: ignore[method-assign]
        client.is_connected = lambda: True  # type: ignore[method-assign]
        client.set_client_profile_name("Payton")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["type"], "client_info")
        self.assertEqual(sent[0]["pc_user"], "Payton")
        self.assertEqual(sent[0]["client_app"], PHONE_BRIDGE_CLIENT_APP)

    def test_set_client_profile_name_skips_when_unchanged_or_offline(self):
        client = PhoneBridgeClient()
        sent: list[dict] = []
        client._send_ndjson = lambda payload: sent.append(dict(payload))  # type: ignore[method-assign]
        client.set_client_profile_name("Admin")
        self.assertEqual(sent, [])
        client.is_connected = lambda: False  # type: ignore[method-assign]
        client.set_client_profile_name("Payton")
        self.assertEqual(sent, [])
        client.is_connected = lambda: True  # type: ignore[method-assign]
        client.set_client_profile_name("Sandy")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["pc_user"], "Sandy")
        client.set_client_profile_name("sandy")
        self.assertEqual(len(sent), 1)


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


class PhoneBridgeRmssdParseTests(unittest.TestCase):
    def test_accepts_official_bridge_snapshot(self):
        row = parse_phone_bridge_rmssd(
            {
                "type": "rmssd",
                "rmssd_ms": 12.4,
                "rmssd_source": "bridge",
                "session_id": "abc",
                "quality": {"flags": ["short_session", ""]},
                "feather_rmssd_ms": 99.0,
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["rmssd_ms"], 12.4)
        self.assertEqual(row["rmssd_source"], "bridge")
        self.assertEqual(row["flags"], ["short_session"])
        self.assertNotIn("feather_rmssd_ms", row)

    def test_rejects_missing_value(self):
        self.assertIsNone(parse_phone_bridge_rmssd({"type": "rmssd"}))
        self.assertIsNone(parse_phone_bridge_rmssd({"type": "session_state", "rmssd_ms": 40}))


class PhoneBridgeSavedHrvParseTests(unittest.TestCase):
    def test_parse_session_summary_record(self):
        row = parse_phone_bridge_session_summary(
            {
                "type": "session_summary",
                "session_id": "20260915T120000Z-a1b2",
                "mode": "record",
                "kind": "ritual",
                "duration_s": 180.5,
                "ibi_count": 220,
                "has_ecg": False,
                "source_device": "FEATHER",
                "emitted_at": "2026-09-15T12:03:00Z",
                "transfer_reason": "delayed_push",
                "rmssd_ms": 52.0,
            }
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["session_id"], "20260915T120000Z-a1b2")
        self.assertEqual(row["transfer_reason"], "delayed_push")
        self.assertEqual(row["has_ecg"], False)
        self.assertEqual(row["rmssd_ms"], 52.0)

    def test_rejects_stream_summary(self):
        self.assertIsNone(
            parse_phone_bridge_session_summary(
                {
                    "type": "session_summary",
                    "session_id": "s1",
                    "mode": "stream",
                    "transfer_reason": "delayed_push",
                }
            )
        )

    def test_build_ritual_ack(self):
        self.assertEqual(
            build_ritual_ack("abc"),
            {"type": "ritual_ack", "session_id": "abc"},
        )
        self.assertIsNone(build_ritual_ack("  "))

    def test_build_ritual_request(self):
        from hnh.sensor import build_ritual_request

        self.assertEqual(
            build_ritual_request(None),
            {"type": "ritual_request", "session_id": None},
        )
        self.assertEqual(
            build_ritual_request("sid-9"),
            {"type": "ritual_request", "session_id": "sid-9"},
        )


class PhoneBridgeRequestSavedHrvTests(unittest.TestCase):
    def test_request_saved_hrv_requires_connection(self):
        client = PhoneBridgeClient()
        sent: list[dict] = []
        client._send_ndjson = lambda payload: sent.append(dict(payload))  # type: ignore[method-assign]
        self.assertFalse(client.request_saved_hrv())
        self.assertEqual(sent, [])

    def test_request_saved_hrv_when_connected(self):
        client = PhoneBridgeClient()
        sent: list[dict] = []
        client._send_ndjson = lambda payload: sent.append(dict(payload))  # type: ignore[method-assign]
        client.is_connected = lambda: True  # type: ignore[method-assign]
        self.assertTrue(client.request_saved_hrv())
        self.assertEqual(sent, [{"type": "ritual_request", "session_id": None}])


class PhoneBridgeSavedHrvAssembleTests(unittest.TestCase):
    def _summary(self, **overrides):
        base = {
            "session_id": "sid-1",
            "mode": "record",
            "kind": "ritual",
            "transfer_reason": "delayed_push",
            "source_device": "POLAR_H10",
            "emitted_at": "2026-09-15T12:03:00Z",
            "has_ecg": False,
            "duration_s": 120.0,
            "ibi_count": 2,
            "ecg_sample_hz": None,
            "rmssd_ms": 40.0,
            "ecg_truncated": None,
        }
        base.update(overrides)
        return base

    def test_ibi_only_package_completes(self):
        assembly = SavedHrvAssembly(session_id="sid-1", summary=self._summary())
        self.assertFalse(saved_hrv_assembly_complete(assembly))
        done = apply_ritual_chunk(
            assembly,
            {
                "type": "ritual_chunk",
                "session_id": "sid-1",
                "seq": 1,
                "of": 1,
                "content": "ibi",
                "encoding": "int_ms_json",
                "samples": [800, 812],
            },
        )
        self.assertTrue(done)
        package = finalize_saved_hrv_package(assembly)
        self.assertEqual(package["ibi_ms"], [800, 812])
        self.assertEqual(package["session_id"], "sid-1")
        self.assertEqual(package["ecg_chunks"], [])

    def test_ibi_ready_but_waits_for_ecg_when_flagged(self):
        from hnh.sensor import saved_hrv_ready_to_finalize

        assembly = SavedHrvAssembly(
            session_id="sid-1",
            summary=self._summary(has_ecg=True),
        )
        self.assertTrue(
            apply_ritual_chunk(
                assembly,
                {
                    "type": "ritual_chunk",
                    "session_id": "sid-1",
                    "seq": 1,
                    "of": 1,
                    "content": "ibi",
                    "samples": [800],
                },
            )
        )
        self.assertFalse(saved_hrv_ready_to_finalize(assembly))
        self.assertTrue(
            apply_ritual_chunk(
                assembly,
                {
                    "type": "ritual_chunk",
                    "session_id": "sid-1",
                    "seq": 1,
                    "of": 1,
                    "content": "ecg",
                    "encoding": "int16_uv_b64",
                    "sample_rate_hz": 250,
                    "scale_uv_per_lsb": 1.0,
                    "data": "AAEC",
                },
            )
        )
        self.assertTrue(saved_hrv_ready_to_finalize(assembly))
        package = finalize_saved_hrv_package(assembly)
        self.assertEqual(len(package["ecg_chunks"]), 1)
        self.assertEqual(package["ecg_chunks"][0]["data"], "AAEC")

    def test_ignores_chunk_for_other_session(self):
        assembly = SavedHrvAssembly(session_id="sid-1", summary=self._summary())
        self.assertFalse(
            apply_ritual_chunk(
                assembly,
                {
                    "type": "ritual_chunk",
                    "session_id": "other",
                    "seq": 1,
                    "of": 1,
                    "content": "ibi",
                    "samples": [800],
                },
            )
        )
        self.assertIsNone(assembly.ibi_of)


class PhoneBridgeSavedHrvClientTests(unittest.TestCase):
    def test_assembles_acks_and_dedupes(self):
        client = PhoneBridgeClient()
        sent: list[dict] = []
        packages: list[dict] = []
        statuses: list[str] = []
        client._send_ndjson = lambda payload: sent.append(dict(payload))  # type: ignore[method-assign]
        client.saved_hrv_package_ready.connect(lambda p: packages.append(dict(p)))
        client.status_update.connect(lambda s: statuses.append(s))

        client._handle_bridge_message(
            {
                "type": "session_summary",
                "session_id": "sid-1",
                "mode": "record",
                "kind": "ritual",
                "has_ecg": False,
                "transfer_reason": "delayed_push",
                "rmssd_ms": 48.0,
            }
        )
        client._handle_bridge_message(
            {
                "type": "rmssd",
                "session_id": "sid-1",
                "rmssd_ms": 48.2,
                "rmssd_source": "bridge",
            }
        )
        client._handle_bridge_message(
            {
                "type": "ritual_chunk",
                "session_id": "sid-1",
                "seq": 1,
                "of": 1,
                "content": "ibi",
                "samples": [790, 800],
            }
        )

        self.assertEqual(len(packages), 1)
        self.assertEqual(packages[0]["ibi_ms"], [790, 800])
        self.assertEqual(packages[0]["rmssd_ms"], 48.2)
        self.assertEqual(sent, [{"type": "ritual_ack", "session_id": "sid-1"}])
        # Background delayed_push must not spam the status bar (misleading at session start).
        self.assertFalse(any("Receiving saved HRV" in s for s in statuses))

        # Duplicate delayed_push: re-ack, no second package emit.
        client._handle_bridge_message(
            {
                "type": "session_summary",
                "session_id": "sid-1",
                "mode": "record",
                "has_ecg": False,
                "transfer_reason": "delayed_push",
            }
        )
        self.assertEqual(len(packages), 1)
        self.assertEqual(
            sent,
            [
                {"type": "ritual_ack", "session_id": "sid-1"},
                {"type": "ritual_ack", "session_id": "sid-1"},
            ],
        )

    def test_live_rr_continues_during_assembly(self):
        client = PhoneBridgeClient()
        ibis: list[int] = []
        client.ibi_update.connect(lambda v: ibis.append(int(v)))
        client._handle_bridge_message(
            {
                "type": "session_summary",
                "session_id": "sid-2",
                "mode": "record",
                "has_ecg": False,
                "transfer_reason": "manual_send",
            }
        )
        client._handle_bridge_message({"type": "rr", "rr_ms": 812})
        client._handle_bridge_message(
            {
                "type": "ritual_chunk",
                "session_id": "sid-2",
                "seq": 1,
                "of": 1,
                "content": "ibi",
                "samples": [700],
            }
        )
        self.assertEqual(ibis, [812])

    def test_waits_for_ecg_then_finalizes(self):
        client = PhoneBridgeClient()
        packages: list[dict] = []
        client._send_ndjson = lambda payload: None  # type: ignore[method-assign]
        client.saved_hrv_package_ready.connect(lambda p: packages.append(dict(p)))
        client._handle_bridge_message(
            {
                "type": "session_summary",
                "session_id": "sid-ecg",
                "mode": "record",
                "has_ecg": True,
                "transfer_reason": "delayed_push",
            }
        )
        client._handle_bridge_message(
            {
                "type": "ritual_chunk",
                "session_id": "sid-ecg",
                "seq": 1,
                "of": 1,
                "content": "ibi",
                "samples": [800],
            }
        )
        self.assertEqual(packages, [])
        client._handle_bridge_message(
            {
                "type": "ritual_chunk",
                "session_id": "sid-ecg",
                "seq": 1,
                "of": 1,
                "content": "ecg",
                "encoding": "int16_uv_b64",
                "sample_rate_hz": 250,
                "data": "AAEC",
            }
        )
        self.assertEqual(len(packages), 1)
        self.assertEqual(len(packages[0]["ecg_chunks"]), 1)


if __name__ == "__main__":
    unittest.main()
