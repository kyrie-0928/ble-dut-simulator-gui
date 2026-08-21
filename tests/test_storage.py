import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HOST = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOST))

from protocol import FieldSpec
from storage import Product, ProductStore, ProtocolFamily, public_protocol_name


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "test.db"
        self.store = ProductStore(self.db_path, HOST / "products.json")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_seed_contains_only_expected_ble_products(self):
        products = self.store.list()
        self.assertEqual(22, len(products))
        self.assertEqual({39178, 39179, 39180, 39181},
                         {item.pid for item in products if item.family == "E6D"})

    def test_seed_matches_configured_product_names_and_models(self):
        expected = {
            28377: ("ES4", "linp.sensor_occupy.es4b"),
            27151: ("ES5", "linp.sensor_occupy.es5b"),
            30706: ("S5", "linp.switch.s5db"),
            31974: ("E5 单键", "linp.switch.e5dbw1"),
            31975: ("E5 双键", "linp.switch.e5dbw2"),
            31357: ("E5 三键", "linp.switch.e5dbw3"),
            31976: ("E5 四键", "linp.switch.e5dbw4"),
            37459: ("H3 单键", "linp.switch.h3dbw1"),
            37460: ("H3 双键", "linp.switch.h3dbw2"),
            37461: ("H3 三键", "linp.switch.h3dbw3"),
            37767: ("E7D 单键", "linp.switch.t2dsb1"),
            37768: ("E7D 双键", "linp.switch.t2dsb2"),
            37769: ("E7D 三键", "linp.switch.t2dsb3"),
            37770: ("E7D 四键", "linp.switch.t2dsb4"),
            28968: ("CE1", "linp.curtain.ec1db"),
            35744: ("CE1-T2", "linp.curtain.t2db"),
            33393: ("C6DB", "linp.curtain.c6db"),
            37882: ("CE1-PRO", "linp.curtain.ce1pdb"),
            39178: ("E6D 单键", "linp.switch.e6db1"),
            39179: ("E6D 双键", "linp.switch.e6db2"),
            39180: ("E6D 三键", "linp.switch.e6db3"),
            39181: ("E6D 四键", "linp.switch.e6db4"),
        }
        products = self.store.list()
        actual = {item.pid: (item.name, item.model) for item in products}
        self.assertEqual(expected, actual)

        expected_protocols = {
            31974: "E5", 31975: "E5", 31357: "E5", 31976: "E5",
            37459: "H3", 37460: "H3", 37461: "H3",
            37767: "E7D", 37768: "E7D", 37769: "E7D", 37770: "E7D",
            28968: "CE1", 35744: "CE1", 37882: "CE1", 33393: "C6",
        }
        self.assertEqual(
            expected_protocols,
            {
                product.pid: product.protocol_name
                for product in products if product.pid in expected_protocols
            },
        )

        by_pid = {item.pid: item for item in products}
        expected_families = {
            31974: "E5_1", 31975: "E5_2", 31357: "E5_3", 31976: "E5_4",
            37459: "H3_1", 37460: "H3_2", 37461: "H3_3",
            37767: "T2DSB", 37768: "T2DSB",
            37769: "T2DSB", 37770: "T2DSB",
            28968: "C6", 35744: "C6", 37882: "C6",
        }
        self.assertEqual(
            expected_families,
            {pid: by_pid[pid].family for pid in expected_families},
        )
        self.assertEqual([190, 1, 1], by_pid[39178].fields["radar"])
        self.assertEqual([4, 0, 0, 0], by_pid[39178].fields["key"])
        self.assertEqual(
            {"version": 0, "rx_rssi": 0, "illuminance": [0, 0],
             "key": [0, 0], "speed": [0, 0]},
            by_pid[33393].fields,
        )
    def test_crud_round_trip(self):
        product = Product(None, "自定义", "CUSTOM", 60000, "T2DSB",
                          100, 200, 5, "timeout",
                          {"version": 2, "temperature": 30, "zero_cross": 1})
        product_id = self.store.add(product)
        loaded = self.store.get(product_id)
        self.assertEqual("CUSTOM", loaded.model)
        self.assertEqual("timeout", loaded.behavior)
        self.assertEqual("E7D", loaded.protocol_name)
        loaded.name = "已修改"
        loaded.protocol_name = "CUSTOM_PROTOCOL"
        loaded.ready_final_ms = 300
        self.store.update(loaded)
        updated = self.store.get(product_id)
        self.assertEqual("已修改", updated.name)
        self.assertEqual("CUSTOM_PROTOCOL", updated.protocol_name)
        self.assertEqual(300, updated.ready_final_ms)
        self.store.delete(product_id)
        self.assertIsNone(self.store.get(product_id))

    def test_custom_family_crud_and_product_field_migration(self):
        family = ProtocolFamily(
            "NEW_SENSOR",
            (
                FieldSpec("version", "u8", 1, 1),
                FieldSpec("samples", "u16", 2, [10, 20]),
            ),
        )
        self.store.add_family(family)
        loaded_family = self.store.get_family("NEW_SENSOR")
        self.assertEqual(("version", "samples"),
                         tuple(field.name for field in loaded_family.fields))

        product_id = self.store.add(Product(
            None, "新品", "NEW-1", 60001, "NEW_SENSOR",
            100, 200, 0, "normal",
            {"version": 2, "samples": [30, 40]},
        ))
        with self.assertRaisesRegex(ValueError, "正在被"):
            self.store.delete_family("NEW_SENSOR")

        self.store.update_family(
            "NEW_SENSOR",
            ProtocolFamily(
                "NEW_SENSOR_V2",
                (
                    FieldSpec("version", "u8", 1, 1),
                    FieldSpec("samples", "u8", 1, 7),
                    FieldSpec("counter", "u32", 1, 99),
                ),
            ),
        )
        migrated = self.store.get(product_id)
        self.assertEqual("NEW_SENSOR_V2", migrated.family)
        self.assertEqual(
            {"version": 2, "samples": 7, "counter": 99}, migrated.fields
        )

        self.store.delete(product_id)
        self.store.delete_family("NEW_SENSOR_V2")
        self.assertIsNone(self.store.get_family("NEW_SENSOR_V2"))

    def test_existing_database_is_migrated_with_builtin_families(self):
        self.store.close()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute("DROP TABLE protocol_families")
            connection.commit()
        finally:
            connection.close()
        self.store = ProductStore(self.db_path, HOST / "products.json")

        families = self.store.list_families()
        self.assertEqual(13, len(families))
        self.assertTrue(all(family.builtin for family in families))
        self.assertEqual(22, len(self.store.list()))

    def test_existing_database_adds_and_backfills_protocol_name(self):
        self.store.close()
        connection = sqlite3.connect(self.db_path)
        try:
            connection.executescript("""
                CREATE TABLE legacy_products AS
                SELECT id, name, model, pid, family, ready_pcba_ms,
                       ready_final_ms, notify_delay_ms, behavior,
                       fields_json, raw_payload_hex
                FROM products;
                DROP TABLE products;
                ALTER TABLE legacy_products RENAME TO products;
            """)
            connection.commit()
        finally:
            connection.close()

        self.store = ProductStore(self.db_path, HOST / "products.json")
        products = {product.pid: product for product in self.store.list()}
        self.assertEqual("CE1", products[28968].protocol_name)
        self.assertEqual("C6", products[33393].protocol_name)
        self.assertEqual("E5", products[31976].protocol_name)
        self.assertEqual("E7D", products[37770].protocol_name)

    def test_public_protocol_name_falls_back_from_internal_structure(self):
        self.assertEqual(
            "C6", public_protocol_name("C6", "C6DB", "linp.curtain.c6db")
        )
        self.assertEqual(
            "CE1", public_protocol_name("C6", "CE1-PRO", "linp.curtain.ce1pdb")
        )
        self.assertEqual("E5", public_protocol_name("E5_4", "E5 四键", ""))
        self.assertEqual("H3", public_protocol_name("H3_2", "H3 双键", ""))
        self.assertEqual("E7D", public_protocol_name("T2DSB", "E7D 四键", ""))

    def test_builtin_family_cannot_be_deleted(self):
        product_ids = [
            product.id for product in self.store.list() if product.family == "C6"
        ]
        for product_id in product_ids:
            self.store.delete(product_id)
        with self.assertRaisesRegex(ValueError, "内置"):
            self.store.delete_family("C6")
        with self.assertRaisesRegex(ValueError, "内置"):
            self.store.update_family(
                "C6",
                ProtocolFamily(
                    "C6_RENAMED",
                    (FieldSpec("version", "u8", 1, 0),),
                    True,
                ),
            )

    def test_seed_is_not_restored_after_user_deletes_product(self):
        product_id = self.store.list()[0].id
        self.store.delete(product_id)
        self.store.close()
        self.store = ProductStore(Path(self.temp.name) / "test.db",
                                  HOST / "products.json")
        self.assertEqual(21, len(self.store.list()))


if __name__ == "__main__":
    unittest.main()
