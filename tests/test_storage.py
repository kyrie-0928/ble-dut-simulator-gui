import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HOST = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOST))

from protocol import FieldSpec
from storage import Product, ProductStore, ProtocolFamily


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

    def test_crud_round_trip(self):
        product = Product(None, "自定义", "CUSTOM", 60000, "T2DSB",
                          100, 200, 5, "timeout",
                          {"version": 2, "temperature": 30, "zero_cross": 1})
        product_id = self.store.add(product)
        loaded = self.store.get(product_id)
        self.assertEqual("CUSTOM", loaded.model)
        self.assertEqual("timeout", loaded.behavior)
        loaded.name = "已修改"
        loaded.ready_final_ms = 300
        self.store.update(loaded)
        updated = self.store.get(product_id)
        self.assertEqual("已修改", updated.name)
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
