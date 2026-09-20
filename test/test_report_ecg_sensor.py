from __future__ import annotations

import unittest

from hnh.report import format_ecg_sensor_display_name


class EcgSensorDisplayNameTests(unittest.TestCase):
    def test_maps_protocol_source_devices(self):
        self.assertEqual(format_ecg_sensor_display_name("FEATHER"), "Feather ECG-Box")
        self.assertEqual(format_ecg_sensor_display_name("POLAR_H10"), "Polar H10")
        self.assertEqual(format_ecg_sensor_display_name("feather"), "Feather ECG-Box")

    def test_maps_ble_menu_labels(self):
        self.assertEqual(
            format_ecg_sensor_display_name(
                None,
                selected_device="Polar H10, AA:BB:CC:DD:EE:FF",
            ),
            "Polar H10",
        )
        self.assertEqual(
            format_ecg_sensor_display_name(
                None,
                selected_device="Feather ECG-Box",
            ),
            "Feather ECG-Box",
        )

    def test_unknown_falls_back(self):
        self.assertEqual(format_ecg_sensor_display_name(None), "--")
        self.assertEqual(format_ecg_sensor_display_name("phone_bridge"), "--")
        self.assertEqual(format_ecg_sensor_display_name("Custom Strap"), "Custom Strap")


if __name__ == "__main__":
    unittest.main()
