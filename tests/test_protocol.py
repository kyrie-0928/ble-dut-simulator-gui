import inspect
import json
import sys
import unittest
from pathlib import Path

HOST = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOST))

from protocol import (
    FAMILY_SCHEMAS,
    FieldSpec,
    build_config_command,
    decode_ble_name,
    encode_ble_name,
    pack_payload,
    payload_hex,
    validate_schema,
)
from serial_node import SerialNode, parse_sim_line
from app import family_structure_name
from storage import public_protocol_name


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = json.loads((HOST / "products.json").read_text(encoding="utf-8"))

    def test_all_22_ble_products_serialize(self):
        self.assertEqual(22, len(self.products))
        self.assertEqual(22, len({item["pid"] for item in self.products}))
        for product in self.products:
            with self.subTest(pid=product["pid"]):
                encoded = payload_hex(product["family"], product["fields"])
                self.assertTrue(encoded)
                self.assertLessEqual(len(encoded) // 2, 64)
                encode_ble_name(product["model"])

    def test_product_protocol_names_hide_internal_structure_ids(self):
        expected = {
            "E5 单键": "E5", "E5 双键": "E5",
            "E5 三键": "E5", "E5 四键": "E5",
            "H3 单键": "H3", "H3 双键": "H3", "H3 三键": "H3",
            "E7D 单键": "E7D", "E7D 双键": "E7D",
            "E7D 三键": "E7D", "E7D 四键": "E7D",
            "CE1": "CE1", "CE1-T2": "CE1", "CE1-PRO": "CE1",
            "C6DB": "C6",
        }
        for product in self.products:
            with self.subTest(product=product["name"]):
                actual = public_protocol_name(
                    product["family"], product["name"], product["model"]
                )
                self.assertEqual(
                    expected.get(product["name"], product["family"]), actual
                )
                self.assertNotRegex(actual, r"_[1-4]$")

    def test_internal_family_names_have_user_facing_structure_labels(self):
        expected = {
            "E5_1": "E5 · 单键字段", "E5_2": "E5 · 双键字段",
            "E5_3": "E5 · 三键字段", "E5_4": "E5 · 四键字段",
            "H3_1": "H3 · 单键字段", "H3_2": "H3 · 双键字段",
            "H3_3": "H3 · 三键字段", "T2DSB": "E7D",
            "C6": "CE1 / C6",
        }
        for internal_name, label in expected.items():
            with self.subTest(internal_name=internal_name):
                self.assertEqual(label, family_structure_name(internal_name))

    def test_payload_sizes_match_fixture_structures(self):
        expected = {
            28377: 27, 27151: 31, 30706: 10,
            31974: 7, 31975: 8, 31357: 9, 31976: 11,
            37459: 5, 37460: 6, 37461: 7,
            37767: 4, 37768: 4, 37769: 4, 37770: 4,
            28968: 10, 35744: 10, 33393: 10, 37882: 10,
            39178: 11, 39179: 11, 39180: 11, 39181: 11,
        }
        for product in self.products:
            payload = pack_payload(product["family"], product["fields"])
            self.assertEqual(expected[product["pid"]], len(payload), product["pid"])

    def test_values_are_little_endian_and_signed(self):
        payload = pack_payload("C6", {
            "version": 1, "rx_rssi": -45, "illuminance": [0x1234, 2],
            "key": [3, 4], "speed": [5, 6],
        })
        self.assertEqual("01D33412020003040506", payload.hex().upper())

    def test_config_command_contains_both_test_delays(self):
        command = build_config_command(7, self.products[-1])
        self.assertTrue(command.startswith("CONFIG 7 39181 4500 8000 0 normal 1 "))
        self.assertTrue(command.rstrip().endswith("6C696E702E7377697463682E6536646234"))
        self.assertTrue(command.endswith("\n"))

    def test_model_is_encoded_as_utf8_ble_name(self):
        encoded = encode_ble_name("E6D-四键")
        self.assertEqual("E6D-四键", decode_ble_name(encoded))

    def test_long_ble_name_is_supported_in_scan_response(self):
        name = "linp.sensor_occupy.es4b"
        self.assertEqual(name, decode_ble_name(encode_ble_name(name)))

    def test_ble_name_over_29_utf8_bytes_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "29"):
            encode_ble_name("123456789012345678901234567890")

    def test_out_of_range_field_is_rejected(self):
        fields = {"version": 300, "rx_rssi": 0, "illuminance": [0, 0],
                  "key": [0, 0], "speed": [0, 0]}
        with self.assertRaisesRegex(ValueError, "version"):
            pack_payload("C6", fields)

    def test_custom_schema_supports_32_bit_signed_values(self):
        schema = (
            FieldSpec("counter", "u32", default=0),
            FieldSpec("offset", "s32", default=-1),
        )
        validate_schema(schema)
        payload = pack_payload(
            "CUSTOM", {"counter": 0x12345678, "offset": -2}, schema
        )
        self.assertEqual("78563412FEFFFFFF", payload.hex().upper())

    def test_custom_schema_rejects_payload_over_64_bytes(self):
        with self.assertRaisesRegex(ValueError, "64"):
            validate_schema((FieldSpec("too_large", "u32", 17, 0),))

    def test_firmware_delay_limit_is_enforced(self):
        product = dict(self.products[0])
        product["ready_final_ms"] = 600001
        with self.assertRaisesRegex(ValueError, "600000"):
            build_config_command(1, product)

    def test_sim_line_parser(self):
        parsed = parse_sim_line("@SIM STATUS seq=2 pid=39181 connected=1")
        self.assertEqual("STATUS", parsed["kind"])
        self.assertEqual("39181", parsed["pid"])

    def test_serial_node_uses_fixture_uart_baudrate(self):
        baudrate = inspect.signature(SerialNode.connect).parameters["baudrate"]
        self.assertEqual(115_200, baudrate.default)


if __name__ == "__main__":
    unittest.main()
